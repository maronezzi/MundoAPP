#!/bin/bash

# --- CONFIGURAÇÃO ---
REMOTE_USER="ubuntu"
REMOTE_HOST="167.126.18.152"
REMOTE_DIR="/home/ubuntu/radio-monitor"
LOCAL_SCRIPT="mundoVPS.py"
SERVICE_NAME="radio-monitor"

# Cores para facilitar a leitura
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}=== INICIANDO DEPLOY AUTOMATIZADO (COM FASTAPI) ===${NC}"

# 1. VERIFICAÇÕES LOCAIS
echo -e "${YELLOW}--> Verificando arquivos locais...${NC}"

if [ ! -f "$LOCAL_SCRIPT" ]; then
    echo -e "${RED}Erro: '$LOCAL_SCRIPT' não encontrado!${NC}"
    echo -e "Certifique-se de que o arquivo Python tem esse nome exato."
    exit 1
fi

if [ ! -f "requirements.txt" ]; then
    echo -e "${YELLOW}Aviso: 'requirements.txt' não encontrado. Criando um básico...${NC}"
    echo "requests" > requirements.txt
    echo "python-dotenv" >> requirements.txt
    echo "spotipy" >> requirements.txt
    echo "fastapi" >> requirements.txt
    echo "uvicorn" >> requirements.txt
fi

if [ ! -f ".env" ]; then
    echo -e "${RED}Erro: Arquivo '.env' não encontrado!${NC}"
    exit 1
fi

# 2. PREPARAR DIRETÓRIO REMOTO
echo -e "${YELLOW}--> Criando diretório na VPS: $REMOTE_DIR${NC}"
ssh "$REMOTE_USER@$REMOTE_HOST" "mkdir -p $REMOTE_DIR"

# 3. ENVIAR ARQUIVOS
echo -e "${YELLOW}--> Enviando arquivos via SCP...${NC}"
scp "$LOCAL_SCRIPT" ".env" "requirements.txt" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

if [ $? -ne 0 ]; then
    echo -e "${RED}Falha crítica ao copiar arquivos. Verifique sua conexão ou VPN.${NC}"
    exit 1
fi

# 4. CONFIGURAÇÃO REMOTA (PYTHON + SYSTEMD + FIREWALL)
echo -e "${YELLOW}--> Configurando ambiente, firewall e serviços na VPS...${NC}"

# O bloco abaixo é executado DENTRO da VPS
ssh "$REMOTE_USER@$REMOTE_HOST" "bash -s" <<EOF

    # A. Instalação de dependências do sistema
    if ! dpkg -s python3-venv >/dev/null 2>&1; then
        echo "Instalando pacote python3-venv..."
        sudo apt-get update -qq
        sudo apt-get install -y python3-venv
    fi

    cd $REMOTE_DIR

    # B. Configuração do Python VENV
    if [ ! -d "venv" ]; then
        echo "Criando ambiente virtual (venv)..."
        python3 -m venv venv
    fi

    echo "Atualizando bibliotecas do Python..."
    source venv/bin/activate
    
    # Garante que pip esteja atualizado
    pip install --upgrade pip --quiet
    
    # Instala requirements E garante as libs da API
    pip install -r requirements.txt --quiet
    pip install fastapi uvicorn --quiet
    
    # C. LIBERAÇÃO DE FIREWALL (Para acessar a API externamente)
    if sudo ufw status | grep -q "Active"; then
        echo "Configurando Firewall (UFW) para porta 8000..."
        sudo ufw allow 8000/tcp
    fi

    # D. CRIAÇÃO AUTOMÁTICA DO SERVIÇO SYSTEMD
    echo "Configurando Systemd Service..."
    
cat > radio_temp.service <<SERVICE_DEF
[Unit]
Description=Radio Monitor API Service
After=network.target

[Service]
User=$REMOTE_USER
Group=$REMOTE_USER
WorkingDirectory=$REMOTE_DIR
ExecStart=$REMOTE_DIR/venv/bin/python $REMOTE_DIR/$LOCAL_SCRIPT
EnvironmentFile=$REMOTE_DIR/.env
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE_DEF

    # Movemos o arquivo temporário para a pasta do sistema
    sudo mv radio_temp.service /etc/systemd/system/$SERVICE_NAME.service

    # E. Recarregar e Reiniciar
    echo "Recarregando daemon do Systemd..."
    sudo systemctl daemon-reload
    
    echo "Habilitando serviço para iniciar no boot..."
    sudo systemctl enable $SERVICE_NAME

    echo "Reiniciando o serviço agora..."
    sudo systemctl restart $SERVICE_NAME

    # Aguarda 2 segundos para o serviço subir antes de checar status
    sleep 2

    echo "--- STATUS DO SERVIÇO ---"
    sudo systemctl status $SERVICE_NAME --no-pager | head -n 10
EOF

echo -e "${GREEN}=== DEPLOY CONCLUÍDO COM SUCESSO! ===${NC}"
echo -e "${CYAN}Logs do sistema:${NC} ssh $REMOTE_USER@$REMOTE_HOST 'sudo journalctl -u $SERVICE_NAME -f'"
echo -e "${GREEN}ACESSE SUA API EM:${NC} http://$REMOTE_HOST:8000/docs"
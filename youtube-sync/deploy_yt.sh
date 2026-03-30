#!/bin/bash

# ==========================================
#      SCRIPT DE DEPLOY AUTOMATIZADO
#        YouTube Music Bot -> VPS
# ==========================================

# --- CONFIGURAÇÃO ---
REMOTE_USER="ubuntu"
REMOTE_HOST="167.126.18.152"
REMOTE_DIR="/home/ubuntu/yt-playlists"
LOCAL_SCRIPT="conectaYT.py"

# Arquivos sensíveis que DEVEM ser enviados
FILE_ENV=".env"
FILE_HEADERS="headers_secreto.txt"

# --- CORES E FORMATAÇÃO ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- FUNÇÕES DE LOG ---
log_info() { echo -e "${CYAN}[INFO] $1${NC}"; }
log_step() { echo -e "${YELLOW}--> $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_error() { echo -e "${RED}❌ ERRO: $1${NC}"; exit 1; }

# ==========================================
#           INÍCIO DO PROCESSO
# ==========================================

clear
echo -e "${GREEN}=== INICIANDO DEPLOY PARA VPS ($REMOTE_HOST) ===${NC}"
echo "--------------------------------------------------------"

# 1. VERIFICAÇÕES LOCAIS
log_step "Verificando arquivos locais essenciais..."

# Verifica o script Python
if [ ! -f "$LOCAL_SCRIPT" ]; then
    log_error "O arquivo script '$LOCAL_SCRIPT' não foi encontrado."
fi

# Verifica o .env
if [ ! -f "$FILE_ENV" ]; then
    log_error "O arquivo '$FILE_ENV' não foi encontrado. Crie-o com as variáveis de ambiente."
fi

# Verifica o headers_secreto.txt
if [ ! -f "$FILE_HEADERS" ]; then
    log_error "O arquivo '$FILE_HEADERS' não foi encontrado. Crie-o com os headers brutos."
fi

# Gera requirements.txt se não existir ou garante que python-dotenv esteja nele
log_info "Verificando dependências..."
if [ ! -f "requirements.txt" ]; then
    log_info "Criando 'requirements.txt' padrão..."
    # Adicionado python-dotenv na lista
    echo -e "ytmusicapi\npandas\nrequests\npython-dotenv" > requirements.txt || log_error "Falha ao criar requirements.txt"
else
    # Se já existe, vamos garantir que o python-dotenv está lá (append se não existir)
    if ! grep -q "python-dotenv" requirements.txt; then
        echo "python-dotenv" >> requirements.txt
        log_info "Adicionado 'python-dotenv' ao requirements.txt existente."
    fi
fi

log_success "Todos os arquivos locais estão prontos."

# 2. PREPARAR DIRETÓRIO REMOTO
log_step "Conectando à VPS para criar diretório..."
ssh -o BatchMode=yes -o ConnectTimeout=10 "$REMOTE_USER@$REMOTE_HOST" "mkdir -p $REMOTE_DIR"
if [ $? -ne 0 ]; then
    log_error "Não foi possível conectar ou criar pasta na VPS. Verifique conexão/VPN/Chave SSH."
fi
log_success "Diretório remoto garantido: $REMOTE_DIR"

# 3. ENVIAR ARQUIVOS (ATUALIZADO PARA INCLUIR SEGREDOS)
log_step "Enviando arquivos via SCP (.env, headers, script)..."

scp -o ConnectTimeout=10 \
    "$LOCAL_SCRIPT" \
    "requirements.txt" \
    "$FILE_ENV" \
    "$FILE_HEADERS" \
    "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

if [ $? -ne 0 ]; then
    log_error "Falha na transferência de arquivos via SCP."
fi
log_success "Arquivos transferidos com sucesso."

# 4. EXECUÇÃO REMOTA
log_step "Iniciando configuração do ambiente na VPS..."

ssh "$REMOTE_USER@$REMOTE_HOST" "bash -s" <<EOF

    # Para o script se houver erro
    set -e

    echo "[VPS] Iniciando configuração..."
    cd "$REMOTE_DIR"

    # --- A. SEGURANÇA DOS ARQUIVOS ---
    echo "[VPS] 🔒 Ajustando permissões de arquivos sensíveis..."
    chmod 600 .env headers_secreto.txt
    # O script python precisa ser executável
    chmod +x $LOCAL_SCRIPT

    # --- B. VERIFICAÇÃO E INSTALAÇÃO DO CRON ---
    if ! command -v crontab &> /dev/null; then
        echo "[VPS] ⚠️ 'crontab' não encontrado. Instalando..."
        sudo apt-get update -qq
        sudo apt-get install -y cron
        sudo systemctl enable cron
        sudo systemctl start cron
        echo "[VPS] ✅ Cron instalado."
    fi

    # --- C. PYTHON VENV ---
    if ! dpkg -s python3-venv >/dev/null 2>&1; then
        echo "[VPS] ⚠️ Pacote python3-venv ausente. Instalando..."
        sudo apt-get update -qq
        sudo apt-get install -y python3-venv
    fi

    if [ ! -d "venv" ]; then
        echo "[VPS] 🔨 Criando Ambiente Virtual (venv)..."
        python3 -m venv venv
    else
        echo "[VPS] ✅ Ambiente Virtual já existe."
    fi

    # --- D. DEPENDÊNCIAS ---
    echo "[VPS] 📦 Instalando bibliotecas Python..."
    source venv/bin/activate
    
    pip install --upgrade pip --quiet
    
    # Instala requirements (agora inclui python-dotenv)
    if pip install -r requirements.txt --quiet; then
        echo "[VPS] ✅ Dependências instaladas com sucesso."
    else
        echo "[VPS] ❌ Falha ao instalar dependências."
        exit 1
    fi

    # --- E. AGENDAMENTO (CRON) ---
    echo "[VPS] ⏰ Configurando Cron Job..."
    
    # Remove browser.json antigo se existir para forçar regeneração limpa com os novos headers
    # (Opcional: descomente a linha abaixo se quiser forçar re-login sempre que fizer deploy)
    rm -f browser.json

    # Monta a linha do Cron diretamente (expansão local das variáveis)
    NEW_CRON_LINE="20 15 * * * cd $REMOTE_DIR && $REMOTE_DIR/venv/bin/python $REMOTE_DIR/$LOCAL_SCRIPT >> $REMOTE_DIR/execution.log 2>&1"
    
    # Atualiza o cron de forma segura (|| true evita erro se grep não achar nada)
    (crontab -l 2>/dev/null | grep -v "$LOCAL_SCRIPT" || true; echo "\$NEW_CRON_LINE") | crontab -
    
    echo "[VPS] ✅ Agendado para todo dia às 14:35."
    echo "[VPS] 📋 Lista atual do Crontab:"
    crontab -l

    # --- F. TESTE FINAL ---
    echo "---------------------------------------------------"
    echo "[VPS] 🚀 EXECUÇÃO DE TESTE IMEDIATA..."
    echo "---------------------------------------------------"
    
    # Executa o script python agora
    if venv/bin/python "$LOCAL_SCRIPT"; then
        echo ""
        echo "---------------------------------------------------"
        echo "[VPS] ✅ SUCESSO! O script rodou e conectou corretamente."
    else
        echo ""
        echo "---------------------------------------------------"
        echo "[VPS] ❌ ERRO: O script falhou no teste."
        echo "Verifique os logs acima ou o arquivo execution.log."
        exit 1
    fi

EOF

# Captura resultado do SSH
SSH_EXIT_CODE=$?

if [ $SSH_EXIT_CODE -eq 0 ]; then
    echo ""
    log_success "=== DEPLOY FINALIZADO COM SUCESSO! ==="
    echo -e "${CYAN}Monitoramento:${NC} cat $REMOTE_DIR/execution.log"
else
    log_error "Erro na configuração remota (Código: $SSH_EXIT_CODE)."
fi
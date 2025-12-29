# Mundo Livre FM - Sistema de Monitoramento e Reprodução

Sistema completo para monitoramento, reprodução e gerenciamento da rádio Mundo Livre FM, composto por um cliente de reprodução, servidor de monitoramento, integração com YouTube Music e painel de estatísticas.

## Visão Geral

O projeto MundoAPP é uma solução completa para gerenciamento de uma rádio online, com as seguintes funcionalidades:

- **Cliente de reprodução**: Aplicativo desktop com interface gráfica para ouvir a rádio com recursos avançados
- **Servidor de monitoramento**: API em FastAPI que monitora em tempo real as músicas tocadas na rádio
- **Integração com YouTube Music**: Sincronização automática das músicas tocadas em playlists do YouTube Music
- **Painel de estatísticas**: Interface web com gráficos e análise de dados da programação

## Componentes do Projeto

### 1. Cliente de Reprodução (mundo.py)

Aplicativo desktop desenvolvido com PyQt6 que permite ouvir a rádio Mundo Livre FM com recursos avançados:

- Interface moderna com capas de álbum, informações de música e popularidade
- Sistema de bloqueio de propagandas com transição suave para música de fundo (lo-fi)
- Sincronização local de histórico de músicas tocadas
- Controle de volume e botões de reprodução/pausa
- Minimização para bandeja do sistema
- Exibição de informações do programa e locutor atuais
- Histórico local das últimas músicas tocadas

#### Recursos principais:
- Bloqueio automático de intervalos comerciais
- Transição suave entre áudio da rádio e música de fundo durante propagandas
- Exibição de capa do álbum (buscada automaticamente via iTunes API)
- Barra de popularidade baseada nos dados do Spotify
- Notificações de novas músicas

### 2. Servidor de Monitoramento (mundoVPS/mundoVPS.py)

API REST desenvolvida com FastAPI que monitora continuamente as músicas tocadas na rádio:

- Monitoramento contínuo da API da rádio (a cada 15 segundos)
- Integração com Spotify para obter dados de popularidade
- Banco de dados local para armazenar histórico de músicas e intervalos comerciais
- API REST com endpoints para histórico e intervalos
- Detecção automática de intervalos comerciais e duração média
- Captura de informações adicionais como programa e locutor

#### Endpoints da API:
- `GET /` - Status do serviço
- `GET /history` - Histórico de músicas tocadas
- `GET /intervals` - Histórico de intervalos comerciais

### 3. Integração com YouTube Music (conectaYT/conectaYT.py)

Script que sincroniza automaticamente as músicas tocadas em playlists do YouTube Music:

- Autenticação segura com YouTube Music API
- Geração de playlists temáticas baseadas na programação:
  - "Apostas da Rádio": Músicas com baixa popularidade que podem se tornar hits
  - "As Gigantes do Streaming": Músicas mais populares da rádio
  - "No Ritmo do Programa": Curadoria baseada no programa mais frequente
 - "Café da Manhã na Rádio": Seleção para o horário da manhã (6-9h)
  - "Ouro da Casa": Músicas mais tocadas na rádio
- Tratamento e limpeza de dados para remover metadados indesejados
- Atualização automática das playlists existentes

### 4. Painel de Estatísticas (estatisticas.html)

Interface web com gráficos e análise de dados da programação da rádio:

- Dashboard com KPIs e métricas importantes
- Gráficos interativos usando Chart.js:
  - Top artistas por execuções
  - Timeline de volume e popularidade média
  - Popularidade média por hora
  - Popularidade média por programa
  - Volume por programa
  - Top locutores
- Filtros avançados por data, horário e conteúdo
- Tabela de histórico com filtros estilo Excel
- Design responsivo e tema escuro

## Arquitetura

```
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Cliente       │    │   Servidor       │    │   YouTube Music  │
│   (mundo.py)    │◄──►│   (VPS API)      │◄──►│   (conectaYT)    │
│                 │    │                  │
│ - Reprodução    │    │ - Monitoramento  │    │ - Playlists      │
│ - Bloqueio Ads  │    │ - Histórico      │    │ - Sincronização  │
│ - Interface     │    │ - Popularidade   │    │ - Automação      │
└─────────────────┘    └──────────────────┘    └──────────────────┘
                                ▲
                                │
                       ┌──────────────────┐
                       │  Banco de Dados  │
                       │  (SQLite)        │
                       │  - Histórico     │
                       │  - Intervalos    │
                       └──────────────────┘
```

## Instalação e Configuração

### Requisitos

- Python 3.8 ou superior
- Conta no Spotify para obter credenciais de API
- Conta no YouTube com acesso à YouTube Music API

### Instalação

1. Clone o repositório:
```bash
git clone <url-do-repositorio>
cd MundoAPP
```

2. Crie um ambiente virtual:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows
```

3. Instale as dependências principais:
```bash
pip install -r requirements.txt
```

4. Instale as dependências do servidor VPS:
```bash
cd mundoVPS
pip install -r requirements.txt
```

5. Instale as dependências do módulo YouTube:
```bash
cd ../conectaYT
pip install -r requirements.txt
```

### Configuração

1. Crie os arquivos `.env` com suas credenciais:

No diretório raiz:
```env
SPOTIPY_CLIENT_ID='seu_client_id_do_spotify'
SPOTIPY_CLIENT_SECRET='seu_client_secret_do_spotify'
```

No diretório `mundoVPS`:
```env
SPOTIPY_CLIENT_ID='seu_client_id_do_spotify'
SPOTIPY_CLIENT_SECRET='seu_client_secret_do_spotify'
```

2. Para o módulo YouTube Music, você precisará:
   - Obter os headers de autenticação do YouTube Music
   - Salvar em um arquivo `headers_secreto.txt`
   - O script `conectaYT.py` gerará automaticamente o arquivo `browser.json` na primeira execução

### Execução

#### Cliente de Reprodução
```bash
cd /caminho/para/MundoAPP
python mundo.py
```

#### Servidor de Monitoramento
```bash
cd /caminho/para/MundoAPP/mundoVPS
python mundoVPS.py
```
Ou usando uvicorn:
```bash
uvicorn mundoVPS:app --host 0.0.0.0 --port 8000
```

#### Integração com YouTube Music
```bash
cd /caminho/para/MundoAPP/conectaYT
python conectaYT.py
```

#### Painel de Estatísticas
Abra o arquivo `estatisticas.html` em um navegador. Certifique-se de que o servidor VPS esteja em execução para que o painel possa obter os dados da API.

## Estrutura de Pastas

```
MundoAPP/
├── mundo.py                    # Cliente de reprodução
├── requirements.txt            # Dependências do cliente
├── .env                        # Variáveis de ambiente (cliente)
├── radio_local_buffer.db       # Banco de dados local do cliente
├── mundoVPS/                   # Servidor de monitoramento
│   ├── mundoVPS.py            # Código do servidor
│   ├── requirements.txt       # Dependências do servidor
│   ├── .env                   # Variáveis de ambiente (servidor)
│   └── radio_data.db          # Banco de dados do servidor
├── conectaYT/                  # Integração com YouTube Music
│   ├── conectaYT.py           # Código de integração
│   ├── requirements.txt       # Dependências do módulo YT
│   └── headers_secreto.txt    # Headers de autenticação (não versionado)
├── estatisticas.html          # Painel de estatísticas
└── README.md                  # Este arquivo
```

## Funcionalidades Avançadas

### Bloqueio de Propagandas
O cliente implementa um sistema avançado de bloqueio de propagandas que:
- Detecta automaticamente intervalos comerciais
- Transiciona suavemente para música de fundo (lo-fi)
- Estima o tempo restante do intervalo
- Retorna automaticamente ao áudio da rádio após o intervalo

### Análise de Popularidade
- Integração com Spotify API para obter dados de popularidade
- Exibição em tempo real da popularidade das músicas tocadas
- Análise estatística no painel de estatísticas

### Sincronização Multi-Plataforma
- Histórico local sincronizado entre o cliente e o servidor
- Integração com YouTube Music para playlists automatizadas
- API REST para acesso a dados em tempo real

## Segurança e Privacidade

- Armazenamento local de dados em banco SQLite
- Autenticação segura com APIs de terceiros
- Nenhum dado pessoal é compartilhado sem consentimento
- Credenciais armazenadas em arquivos .env (não versionados)

## Contribuição

Sinta-se à vontade para contribuir com este projeto:

1. Faça um fork do repositório
2. Crie uma branch para sua feature (`git checkout -b feature/AmazingFeature`)
3. Faça commit de suas alterações (`git commit -m 'Add some AmazingFeature'`)
4. Faça push para a branch (`git push origin feature/AmazingFeature`)
5. Abra um Pull Request

## Licença

Este projeto é licenciado sob a licença MIT - veja o arquivo [LICENSE](LICENSE) para detalhes.

## Contato

Projeto criado para a rádio Mundo Livre FM.

---

*Este sistema foi desenvolvido para melhorar a experiência de ouvinte e fornecer insights valiosos sobre a programação da rádio.*
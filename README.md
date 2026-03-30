# Mundo Livre FM - Sistema Completo

Sistema para monitoramento e reprodução da rádio Mundo Livre FM.

## Estrutura do Projeto

```
MundoAPP/
├── desktop-player/     # Player desktop (PyQt6) com ADBLOCK
├── servidor/           # API FastAPI - monitoramento em tempo real (VPS)
├── estatisticas/       # Dashboard web com gráficos e análise
├── youtube-sync/       # Integração com YouTube Music
└── README.md
```

## Componentes

### 🎵 Desktop Player (`desktop-player/`)

Player desktop com PyQt6 para ouvir a rádio com interface moderna:

- Streaming de áudio da rádio
- Sistema ADBLOCK (toca lo-fi durante comerciais)
- Fade suave entre rádio e overlay
- Capas de álbum, popularidade, histórico
- Bandeja do sistema

```bash
cd desktop-player
pip install -r requirements.txt
python mundo.py
```

### 🖥️ Servidor API (`servidor/`)

API FastAPI que roda na VPS monitorando a rádio em tempo real:

- Monitoramento contínuo (15s)
- Dados de popularidade via Spotify
- Endpoints: `/now`, `/history`, `/intervals`

```bash
cd servidor
pip install -r requirements.txt
# Deploy na VPS:
./deploy.sh
```

**API Docs:** veja `servidor/API_CLIENT.md`

### 📊 Estatísticas (`estatisticas/`)

Dashboard web com analytics completo:

- KPIs em tempo real (músicas, programas, locutores)
- Gráficos: top artistas, timeline, popularidade por hora/programa
- Tabela com filtros estilo Excel
- Filtros por data e horário

Basta abrir `estatisticas/index.html` no navegador.

### 🎬 YouTube Sync (`youtube-sync/`)

Sincronização automática das músicas tocadas com playlists do YouTube Music.

## API Reference

O servidor disponibiliza os seguintes endpoints:

| Endpoint | Descrição |
|----------|-----------|
| `GET /` | Status do serviço |
| `GET /now` | Música/intervalo atual |
| `GET /history?limit=N` | Histórico de músicas |
| `GET /intervals?limit=N` | Histórico de intervalos comerciais |

## Requisitos

- Python 3.10+
- VPS com acesso à API da rádio
- Spotify API (para popularidade)

## Autor

Bruno Maronezzi

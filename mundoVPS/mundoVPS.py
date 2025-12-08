import os
import time
import requests
import sqlite3
import logging
import threading
from datetime import datetime
from typing import List, Optional
from dotenv import load_dotenv

# Bibliotecas novas para a API
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# --- CONFIGURAÇÃO ---
load_dotenv()

# Configuração de Logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- CONSTANTES ---
URL_RADIO_JSON = "https://music-stream-data.grpcomradios.com.br/player/rML939.json"
BLOCKLIST_TERMS = ["MUNDO LIVRE", "INTERVALO", "COMERCIAL", "AUDIO", "VINHETA", "RADIO"]
DB_NAME = "radio_data.db"
CHECK_INTERVAL = 15

# --- MODELOS PYDANTIC (Para a API) ---
class SongResponse(BaseModel):
    id: int
    title: str
    artist: str
    program: Optional[str] = None  # Novo campo
    announcer: Optional[str] = None # Novo campo
    popularity: int
    played_at: str

class IntervalResponse(BaseModel):
    id: int
    start_time: str
    end_time: str
    duration_seconds: float

# --- DATABASE ---
class DatabaseHandler:
    def __init__(self, db_name=DB_NAME):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        try:
            with sqlite3.connect(self.db_name, check_same_thread=False) as conn:
                c = conn.cursor()
                # Cria a tabela com os novos campos se não existir
                c.execute('''
                    CREATE TABLE IF NOT EXISTS songs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT,
                        artist TEXT,
                        program TEXT,
                        announcer TEXT,
                        popularity INTEGER,
                        played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                c.execute('''
                    CREATE TABLE IF NOT EXISTS intervals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        start_time TIMESTAMP,
                        end_time TIMESTAMP,
                        duration_seconds REAL
                    )
                ''')
                
                # --- MIGRATION SIMPLES ---
                # Tenta adicionar as colunas caso o banco já exista e elas não estejam lá
                try:
                    c.execute("ALTER TABLE songs ADD COLUMN program TEXT")
                except sqlite3.OperationalError:
                    pass # Coluna já existe
                
                try:
                    c.execute("ALTER TABLE songs ADD COLUMN announcer TEXT")
                except sqlite3.OperationalError:
                    pass # Coluna já existe
                
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao inicializar DB: {e}")

    # --- Métodos de Escrita (Usados pelo Monitor) ---
    def log_song(self, title, artist, popularity, program, announcer):
        try:
            with sqlite3.connect(self.db_name) as conn:
                c = conn.cursor()
                c.execute("SELECT title, artist FROM songs ORDER BY id DESC LIMIT 1")
                last_entry = c.fetchone()
                
                # Evita duplicatas se a música for a mesma da última checagem
                if last_entry:
                    last_title, last_artist = last_entry
                    if last_title == title and last_artist == artist:
                        return False 
                
                c.execute("""
                    INSERT INTO songs (title, artist, popularity, program, announcer) 
                    VALUES (?, ?, ?, ?, ?)
                """, (title, artist, popularity, program, announcer))
                conn.commit()
                logger.info(f"🎶 Nova música salva: {title} - {artist} | Programa: {program}")
                return True
        except Exception as e:
            logger.error(f"Erro ao salvar música: {e}")
            return False

    def log_interval(self, start_time, end_time, duration):
        try:
            with sqlite3.connect(self.db_name) as conn:
                c = conn.cursor()
                c.execute("INSERT INTO intervals (start_time, end_time, duration_seconds) VALUES (?, ?, ?)", 
                          (start_time, end_time, duration))
                conn.commit()
            logger.info(f"⏸️ Intervalo registrado: {duration:.2f} segundos")
        except Exception as e:
            logger.error(f"Erro ao salvar intervalo: {e}")

    # --- Métodos de Leitura (Usados pela API) ---
    def get_songs(self, limit: int = 50):
        try:
            with sqlite3.connect(self.db_name) as conn:
                # Retorna dicionários para facilitar o parse do Pydantic
                conn.row_factory = sqlite3.Row 
                c = conn.cursor()
                c.execute("SELECT * FROM songs ORDER BY id DESC LIMIT ?", (limit,))
                rows = c.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erro ao ler músicas: {e}")
            return []

    def get_intervals(self, limit: int = 50):
        try:
            with sqlite3.connect(self.db_name) as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute("SELECT * FROM intervals ORDER BY id DESC LIMIT ?", (limit,))
                rows = c.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erro ao ler intervalos: {e}")
            return []

# --- MONITOR (Lógica Original) ---
class RadioMonitor:
    def __init__(self):
        self.db = DatabaseHandler()
        self.client_id = os.getenv("SPOTIPY_CLIENT_ID", "")
        self.client_secret = os.getenv("SPOTIPY_CLIENT_SECRET", "")
        self.spotify_ready = False
        
        # Controle de Estado
        self.current_song_check = "" 
        self.is_in_ad_block = False
        self.ad_start_time = None
        self.running = True # Para controle de parada suave se necessário
        
        self.setup_spotify()

    def setup_spotify(self):
        if self.client_id and self.client_secret:
            try:
                self.auth_manager = SpotifyClientCredentials(client_id=self.client_id, client_secret=self.client_secret)
                self.sp = spotipy.Spotify(auth_manager=self.auth_manager)
                self.spotify_ready = True
                logger.info("Spotify API configurada com sucesso.")
            except Exception as e:
                logger.error(f"Erro ao configurar Spotify: {e}")
        else:
            logger.warning("Credenciais do Spotify não encontradas no .env")

    def get_spotify_data(self, track, artist):
        if not self.spotify_ready:
            return 0
        try:
            query = f"track:{track} artist:{artist}"
            results = self.sp.search(q=query, type='track', limit=1)
            items = results['tracks']['items']
            if items:
                return items[0]['popularity']
        except Exception:
            # Silencia erro pontual para não sujar log, tenta reconectar na proxima
            try:
                self.setup_spotify()
            except:
                pass
        return 0

    def start_loop(self):
        """Método para rodar em Thread separada"""
        logger.info("Iniciando monitoramento da rádio (Background Thread)...")
        while self.running:
            try:
                self.check_radio()
            except Exception as e:
                logger.error(f"Erro no loop principal: {e}")
            time.sleep(CHECK_INTERVAL)

    def check_radio(self):
        try:
            res = requests.get(URL_RADIO_JSON, timeout=5)
            if res.status_code != 200:
                return
            
            data = res.json()
            raw_artist = str(data.get("artista", "")).strip().upper()
            raw_music = str(data.get("musica", "")).strip().upper()
            
            # Novos campos capturados
            raw_program = str(data.get("programa", "")).strip()
            raw_announcer = str(data.get("locutor", "")).strip()

            is_ad = (not raw_artist or not raw_music or 
                     any(t in raw_artist for t in BLOCKLIST_TERMS) or 
                     any(t in raw_music for t in BLOCKLIST_TERMS))

            if is_ad:
                if not self.is_in_ad_block:
                    self.is_in_ad_block = True
                    self.ad_start_time = datetime.now()
                    self.current_song_check = "" 
                    logger.info("Início de bloco comercial/fala.")
                return 

            if self.is_in_ad_block:
                self.is_in_ad_block = False
                if self.ad_start_time:
                    end_time = datetime.now()
                    duration = (end_time - self.ad_start_time).total_seconds()
                    self.db.log_interval(self.ad_start_time, end_time, duration)
                    self.ad_start_time = None

            musica_real = data.get("musica")
            artista_real = data.get("artista")

            if musica_real == self.current_song_check:
                return

            self.current_song_check = musica_real
            popularity = self.get_spotify_data(musica_real, artista_real)
            
            # Passa os novos campos para o log_song
            self.db.log_song(musica_real, artista_real, popularity, raw_program, raw_announcer)

        except requests.RequestException:
            pass # Erros de conexão momentâneos
        except Exception as e:
            logger.error(f"Erro inesperado: {e}")

# --- API FASTAPI ---

app = FastAPI(title="Radio Monitor API", version="1.0")

# Habilita CORS (permite acesso de qualquer origem, útil para frontend em outro IP)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

monitor = RadioMonitor()

@app.on_event("startup")
def startup_event():
    # Inicia o monitoramento em uma thread separada para não travar a API
    t = threading.Thread(target=monitor.start_loop, daemon=True)
    t.start()

@app.get("/")
def home():
    return {"status": "online", "service": "Radio Monitor API"}

@app.get("/history", response_model=List[SongResponse])
def get_history(limit: int = 20):
    """Retorna as últimas músicas tocadas."""
    return monitor.db.get_songs(limit)

@app.get("/intervals", response_model=List[IntervalResponse])
def get_intervals(limit: int = 20):
    """Retorna os últimos intervalos comerciais."""
    return monitor.db.get_intervals(limit)

# --- EXECUÇÃO ---
if __name__ == "__main__":
    import uvicorn
    # host="0.0.0.0" permite acesso externo
    # port=8000 é a porta padrão
    uvicorn.run(app, host="0.0.0.0", port=8000)
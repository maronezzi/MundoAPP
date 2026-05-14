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
VOZ_DO_BRASIL_TERMS = ["A VOZ DO BRASIL", "VOZ DO BRASIL"]
DB_NAME = "radio_data.db"
CHECK_INTERVAL = 5

# --- MODELOS PYDANTIC (Para a API) ---
class SongResponse(BaseModel):
    id: int
    title: str
    artist: str
    program: Optional[str] = None  # Novo campo
    announcer: Optional[str] = None # Novo campo
    popularity: int
    cover_url: Optional[str] = None  # Album cover from Spotify
    played_at: str

class IntervalResponse(BaseModel):
    id: int
    start_time: str
    end_time: str
    duration_seconds: float

class VozDoBrasilResponse(BaseModel):
    id: int
    title: str
    program: str
    announcer: Optional[str] = None
    started_at: str

class NowPlayingResponse(BaseModel):
    status: str  # "interval", "playing", or "voz_do_brasil"
    song_id: Optional[int] = None  # Song ID from history, null when in interval
    voz_entry_id: Optional[int] = None  # Voz do Brasil entry ID

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
                        cover_url TEXT,
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

                try:
                    c.execute("ALTER TABLE songs ADD COLUMN cover_url TEXT")
                except sqlite3.OperationalError:
                    pass # Coluna já existe

                # Tabela para programas especiais (A Voz do Brasil, etc)
                c.execute('''
                    CREATE TABLE IF NOT EXISTS special_programs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT,
                        program TEXT,
                        announcer TEXT,
                        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        program_type TEXT  -- 'voz_do_brasil', 'jornalismo', etc
                    )
                ''')

                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao inicializar DB: {e}")

    # --- Métodos de Escrita (Usados pelo Monitor) ---
    def log_song(self, title, artist, popularity, cover_url, program, announcer):
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
                    INSERT INTO songs (title, artist, popularity, cover_url, program, announcer)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (title, artist, popularity, cover_url, program, announcer))
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

    def log_special_program(self, title, program, announcer, program_type):
        """Log special programs like A Voz do Brasil."""
        try:
            with sqlite3.connect(self.db_name) as conn:
                c = conn.cursor()
                # Check if the same program is already active (avoid duplicates)
                c.execute("SELECT title FROM special_programs ORDER BY id DESC LIMIT 1")
                last_entry = c.fetchone()
                if last_entry and last_entry[0] == title:
                    return False  # Already logged, skip duplicate

                c.execute("""
                    INSERT INTO special_programs (title, program, announcer, program_type)
                    VALUES (?, ?, ?, ?)
                """, (title, program, announcer, program_type))
                conn.commit()
                logger.info(f"📢 Programa especial registrado: {title} | Tipo: {program_type}")
                return True
        except Exception as e:
            logger.error(f"Erro ao salvar programa especial: {e}")
            return False

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

    def get_special_programs(self, limit: int = 50):
        """Get special programs like A Voz do Brasil."""
        try:
            with sqlite3.connect(self.db_name) as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute("SELECT * FROM special_programs ORDER BY id DESC LIMIT ?", (limit,))
                rows = c.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erro ao ler programas especiais: {e}")
            return []

    def get_current_song_id(self, title: str, artist: str) -> Optional[int]:
        """Get the ID of the most recent song matching title and artist."""
        try:
            with sqlite3.connect(self.db_name) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT id FROM songs
                    WHERE title = ? AND artist = ?
                    ORDER BY id DESC LIMIT 1
                """, (title, artist))
                result = c.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"Erro ao buscar ID da música: {e}")
            return None

    def get_current_voz_entry_id(self, title: str) -> Optional[int]:
        """Get the ID of the most recent Voz do Brasil entry."""
        try:
            with sqlite3.connect(self.db_name) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT id FROM special_programs
                    WHERE title = ? AND program_type = 'voz_do_brasil'
                    ORDER BY id DESC LIMIT 1
                """, (title,))
                result = c.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"Erro ao buscar ID do programa especial: {e}")
            return None

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

        # Controle de Estado - Voz do Brasil
        self.current_voz_check = ""
        self.is_in_voz_do_brasil = False
        self.voz_entry_id = None
        
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
            return 0, None
        try:
            query = f"track:{track} artist:{artist}"
            results = self.sp.search(q=query, type='track', limit=1)
            items = results['tracks']['items']
            if items:
                popularity = items[0]['popularity']
                # Get the cover image URL (usually the first image, 640x640)
                cover_url = items[0]['album']['images'][0]['url'] if items[0]['album']['images'] else None
                return popularity, cover_url
        except Exception:
            # Silencia erro pontual para não sujar log, tenta reconectar na proxima
            try:
                self.setup_spotify()
            except:
                pass
        return 0, None

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
            raw_program_upper = str(data.get("programa", "")).strip().upper()

            # Novos campos capturados
            raw_program = str(data.get("programa", "")).strip()
            raw_announcer = str(data.get("locutor", "")).strip()

            # Check for Voz do Brasil (check in program, artist, and music fields)
            is_voz_do_brasil = (
                any(t in raw_program_upper for t in VOZ_DO_BRASIL_TERMS) or
                any(t in raw_artist for t in VOZ_DO_BRASIL_TERMS) or
                any(t in raw_music for t in VOZ_DO_BRASIL_TERMS)
            )

            if is_voz_do_brasil:
                # Get the title to use (prefer program name, then music title)
                voz_title = raw_program if raw_program else data.get("musica", "A Voz do Brasil")

                if voz_title != self.current_voz_check:
                    self.current_voz_check = voz_title
                    self.is_in_voz_do_brasil = True
                    # Log the special program
                    self.db.log_special_program(voz_title, raw_program, raw_announcer, "voz_do_brasil")
                    # Get the entry ID for API responses
                    self.voz_entry_id = self.db.get_current_voz_entry_id(voz_title)
                    logger.info("📢 A Voz do Brasil detectado.")
                return

            # Reset Voz do Brasil state if no longer active
            if self.is_in_voz_do_brasil:
                self.is_in_voz_do_brasil = False
                self.current_voz_check = ""
                self.voz_entry_id = None

            # Check for regular ads (not Voz do Brasil)
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
            popularity, cover_url = self.get_spotify_data(musica_real, artista_real)

            # Passa os novos campos para o log_song
            self.db.log_song(musica_real, artista_real, popularity, cover_url, raw_program, raw_announcer)

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

@app.get("/now", response_model=NowPlayingResponse)
def get_now_playing():
    """Returns current status: interval, playing (with song_id), or voz_do_brasil."""
    if monitor.is_in_voz_do_brasil:
        return NowPlayingResponse(status="voz_do_brasil", song_id=None, voz_entry_id=monitor.voz_entry_id)

    if monitor.is_in_ad_block:
        return NowPlayingResponse(status="interval", song_id=None, voz_entry_id=None)

    # Get current song ID from database
    song_id = None
    if monitor.current_song_check:
        # Need to fetch current artist from radio API to get song_id
        try:
            res = requests.get(URL_RADIO_JSON, timeout=3)
            if res.status_code == 200:
                data = res.json()
                title = data.get("musica")
                artist = data.get("artista")
                if title and artist:
                    song_id = monitor.db.get_current_song_id(title, artist)
        except:
            pass

    return NowPlayingResponse(
        status="playing" if song_id else "interval",
        song_id=song_id,
        voz_entry_id=None
    )

@app.get("/special-programs", response_model=List[VozDoBrasilResponse])
def get_special_programs(limit: int = 20):
    """Retorna os programas especiais (A Voz do Brasil, etc)."""
    return monitor.db.get_special_programs(limit)

# --- EXECUÇÃO ---
if __name__ == "__main__":
    import uvicorn
    # host="0.0.0.0" permite acesso externo
    # port=8000 é a porta padrão
    uvicorn.run(app, host="0.0.0.0", port=8000)
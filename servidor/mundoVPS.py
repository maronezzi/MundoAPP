import os
import time
import requests
import sqlite3
import logging
import threading
from datetime import datetime
from typing import List, Optional
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# --- CONFIGURAÇÃO ---
load_dotenv()

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

# --- MODELOS PYDANTIC ---
class SongResponse(BaseModel):
    id: int
    title: str
    artist: str
    program: Optional[str] = None
    announcer: Optional[str] = None
    popularity: int
    cover_url: Optional[str] = None
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
    status: str
    song_id: Optional[int] = None
    voz_entry_id: Optional[int] = None
    title: Optional[str] = None
    artist: Optional[str] = None

# --- DATABASE (Thread-safe com conexão dedicada) ---
class DatabaseHandler:
    def __init__(self, db_name=DB_NAME):
        self.db_name = db_name
        self._local = threading.local()
        self.init_db()

    def _get_conn(self):
        """Uma conexão SQLite por thread (thread-safe)."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(self.db_name, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def init_db(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, artist TEXT, program TEXT, announcer TEXT,
            popularity INTEGER, cover_url TEXT,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS intervals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TIMESTAMP, end_time TIMESTAMP, duration_seconds REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS special_programs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, program TEXT, announcer TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            program_type TEXT)''')
        # Migrations
        for col in ['program', 'announcer', 'cover_url']:
            try:
                c.execute(f"ALTER TABLE songs ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
        conn.commit()

    def log_song(self, title, artist, popularity, cover_url, program, announcer):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT title, artist FROM songs ORDER BY id DESC LIMIT 1")
        last = c.fetchone()
        if last and last['title'] == title and last['artist'] == artist:
            return False
        c.execute("INSERT INTO songs (title, artist, popularity, cover_url, program, announcer) VALUES (?,?,?,?,?,?)",
                  (title, artist, popularity, cover_url, program, announcer))
        conn.commit()
        logger.info(f"🎶 {title} - {artist} | {program}")
        return True

    def log_interval(self, start_time, end_time, duration):
        conn = self._get_conn()
        conn.execute("INSERT INTO intervals (start_time, end_time, duration_seconds) VALUES (?,?,?)",
                     (start_time, end_time, duration))
        conn.commit()

    def log_special_program(self, title, program, announcer, program_type):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT title FROM special_programs ORDER BY id DESC LIMIT 1")
        last = c.fetchone()
        if last and last['title'] == title:
            return False
        c.execute("INSERT INTO special_programs (title, program, announcer, program_type) VALUES (?,?,?,?)",
                  (title, program, announcer, program_type))
        conn.commit()
        logger.info(f"📢 {title} | {program_type}")
        return True

    def get_songs(self, limit=50):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM songs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in c.fetchall()]

    def get_intervals(self, limit=50):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM intervals ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in c.fetchall()]

    def get_special_programs(self, limit=50):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM special_programs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in c.fetchall()]

    def get_current_song_id(self, title, artist):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT id FROM songs WHERE title=? AND artist=? ORDER BY id DESC LIMIT 1", (title, artist))
        r = c.fetchone()
        return r['id'] if r else None

    def get_current_voz_entry_id(self, title):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT id FROM special_programs WHERE title=? AND program_type='voz_do_brasil' ORDER BY id DESC LIMIT 1", (title,))
        r = c.fetchone()
        return r['id'] if r else None


# --- MONITOR ---
class RadioMonitor:
    def __init__(self):
        self.db = DatabaseHandler()
        self.client_id = os.getenv("SPOTIPY_CLIENT_ID", "")
        self.client_secret = os.getenv("SPOTIPY_CLIENT_SECRET", "")
        self.spotify_ready = False

        # Estado em memória (thread-safe via GIL)
        self.is_in_ad_block = False
        self.is_in_voz_do_brasil = False
        self.ad_start_time = None
        self.current_song_check = ""
        self.current_voz_check = ""
        self.voz_entry_id = None
        self.running = True

        # Cache da música atual (evita request extra no /now)
        self._current_title = ""
        self._current_artist = ""
        self._current_song_id = None

        # Session com connection pooling
        self._session = requests.Session()
        self._session.headers.update({'User-Agent': 'RadioMonitor/2.0'})

        self.setup_spotify()

    def setup_spotify(self):
        if self.client_id and self.client_secret:
            try:
                self.auth_manager = SpotifyClientCredentials(client_id=self.client_id, client_secret=self.client_secret)
                self.sp = spotipy.Spotify(auth_manager=self.auth_manager)
                self.spotify_ready = True
                logger.info("Spotify API OK.")
            except Exception as e:
                logger.error(f"Spotify error: {e}")

    def get_spotify_data(self, track, artist):
        if not self.spotify_ready:
            return 0, None
        try:
            results = self.sp.search(q=f"track:{track} artist:{artist}", type='track', limit=1)
            items = results['tracks']['items']
            if items:
                return items[0]['popularity'], items[0]['album']['images'][0]['url'] if items[0]['album']['images'] else None
        except Exception:
            try:
                self.setup_spotify()
            except:
                pass
        return 0, None

    def start_loop(self):
        logger.info("Monitor iniciado (background thread)...")
        while self.running:
            try:
                self.check_radio()
            except Exception as e:
                logger.error(f"Loop error: {e}")
            time.sleep(CHECK_INTERVAL)

    def check_radio(self):
        try:
            res = self._session.get(URL_RADIO_JSON, timeout=5)
            if res.status_code != 200:
                return

            data = res.json()
            raw_artist = str(data.get("artista", "")).strip().upper()
            raw_music = str(data.get("musica", "")).strip().upper()
            raw_program_upper = str(data.get("programa", "")).strip().upper()
            raw_program = str(data.get("programa", "")).strip()
            raw_announcer = str(data.get("locutor", "")).strip()

            # Check Voz do Brasil
            is_voz = (
                any(t in raw_program_upper for t in VOZ_DO_BRASIL_TERMS) or
                any(t in raw_artist for t in VOZ_DO_BRASIL_TERMS) or
                any(t in raw_music for t in VOZ_DO_BRASIL_TERMS)
            )

            if is_voz:
                voz_title = raw_program if raw_program else data.get("musica", "A Voz do Brasil")
                if voz_title != self.current_voz_check:
                    self.current_voz_check = voz_title
                    self.is_in_voz_do_brasil = True
                    self.is_in_ad_block = False
                    self.db.log_special_program(voz_title, raw_program, raw_announcer, "voz_do_brasil")
                    self.voz_entry_id = self.db.get_current_voz_entry_id(voz_title)
                    # Limpa cache de música
                    self._current_title = ""
                    self._current_artist = ""
                    self._current_song_id = None
                return

            # Reset Voz do Brasil
            if self.is_in_voz_do_brasil:
                self.is_in_voz_do_brasil = False
                self.current_voz_check = ""
                self.voz_entry_id = None

            # Check ads
            is_ad = (not raw_artist or not raw_music or
                     any(t in raw_artist for t in BLOCKLIST_TERMS) or
                     any(t in raw_music for t in BLOCKLIST_TERMS))

            if is_ad:
                if not self.is_in_ad_block:
                    self.is_in_ad_block = True
                    self.ad_start_time = datetime.now()
                    self.current_song_check = ""
                    # Limpa cache
                    self._current_title = ""
                    self._current_artist = ""
                    self._current_song_id = None
                return

            # Fim do intervalo
            if self.is_in_ad_block:
                self.is_in_ad_block = False
                if self.ad_start_time:
                    end = datetime.now()
                    self.db.log_interval(self.ad_start_time, end, (end - self.ad_start_time).total_seconds())
                    self.ad_start_time = None

            musica_real = data.get("musica")
            artista_real = data.get("artista")

            if musica_real == self.current_song_check:
                return

            self.current_song_check = musica_real
            popularity, cover_url = self.get_spotify_data(musica_real, artista_real)
            self.db.log_song(musica_real, artista_real, popularity, cover_url, raw_program, raw_announcer)

            # Atualiza cache em memória
            self._current_title = musica_real
            self._current_artist = artista_real
            self._current_song_id = self.db.get_current_song_id(musica_real, artista_real)

        except requests.RequestException:
            pass
        except Exception as e:
            logger.error(f"check_radio error: {e}")


# --- API ---
app = FastAPI(title="Radio Monitor API", version="2.0")

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
    t = threading.Thread(target=monitor.start_loop, daemon=True)
    t.start()

@app.get("/")
def home():
    return {"status": "online", "service": "Radio Monitor API v2"}

@app.get("/now", response_model=NowPlayingResponse)
def get_now_playing():
    """Status atual — usa cache em memória, SEM request extra."""
    if monitor.is_in_voz_do_brasil:
        return NowPlayingResponse(
            status="voz_do_brasil",
            song_id=None,
            voz_entry_id=monitor.voz_entry_id,
            title="A Voz do Brasil",
        )

    if monitor.is_in_ad_block:
        return NowPlayingResponse(status="interval")

    # Usa cache em memória — sem query extra
    return NowPlayingResponse(
        status="playing" if monitor._current_song_id else "interval",
        song_id=monitor._current_song_id,
        voz_entry_id=None,
        title=monitor._current_title or None,
        artist=monitor._current_artist or None,
    )

@app.get("/history", response_model=List[SongResponse])
def get_history(limit: int = 20):
    return monitor.db.get_songs(limit)

@app.get("/intervals", response_model=List[IntervalResponse])
def get_intervals(limit: int = 20):
    return monitor.db.get_intervals(limit)

@app.get("/special-programs", response_model=List[VozDoBrasilResponse])
def get_special_programs(limit: int = 20):
    return monitor.db.get_special_programs(limit)

# --- EXECUÇÃO ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

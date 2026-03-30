#!/usr/bin/env python3
"""
Mundo Livre FM Radio Player
Um player moderno e elegante para a rádio Mundo Livre FM com funcionalidade ADBLOCK.

Características:
- Streaming de áudio da rádio Mundo Livre FM
- Sistema ADBLOCK que toca música lo-fi durante intervalos comerciais
- Fade suave entre rádio e música de overlay
- Histórico de músicas tocadas
- Bandeja do sistema para minimizar
- Interface moderna e responsiva

Autor: Melhorado e otimizado
Versão: 2.0.0
"""

import sys
import os
import sqlite3
import datetime
import logging
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Callable
from contextlib import contextmanager

import requests
from dotenv import load_dotenv

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QProgressBar, QFrame, QSlider, 
    QCheckBox, QSystemTrayIcon, QMenu, QStyle, QGraphicsDropShadowEffect,
    QSizePolicy, QToolTip
)
from PyQt6.QtCore import (
    QThread, pyqtSignal, Qt, QUrl, QTimer, QPoint, 
    QPropertyAnimation, QEasingCurve, QSize, QMutex, QMutexLocker
)
from PyQt6.QtGui import (
    QFont, QPixmap, QAction, QColor, QPainter, QPainterPath, 
    QCursor, QLinearGradient, QFontDatabase
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()


# ============================================================================
# CONFIGURAÇÕES E CONSTANTES
# ============================================================================

@dataclass(frozen=True)
class Config:
    """Configurações centralizadas do aplicativo."""
    # URLs
    api_base_url: str = "http://167.126.18.152:8000"
    url_streaming: str = "https://playerservices.streamtheworld.com/api/livestream-redirect/MUNDOLIVRE_CWBAAC_64.aac"
    url_lofi_overlay: str = "http://stream.zeno.fm/0r0xa792kwzuv"
    
    # Banco de dados
    db_name: str = "radio_local_buffer.db"
    
    # Áudio
    fade_step: float = 0.03
    fade_interval: int = 50
    overlay_max_vol: float = 0.5
    default_volume: int = 80
    
    # Timing
    api_poll_interval: int = 10000
    connection_timeout: int = 5
    image_timeout: int = 10
    
    # Janela
    window_width: int = 400
    window_height: int = 780
    
    # Cores do tema
    color_bg: str = "#0a0c0b"
    color_primary: str = "#13ec6a"
    color_secondary: str = "#1DB954"
    color_card: str = "#1a1c1b"
    color_card_light: str = "#252726"
    color_text: str = "#ffffff"
    color_text_secondary: str = "#b3b3b3"
    color_accent: str = "#9C27B0"
    color_warning: str = "#FFB74D"
    color_danger: str = "#ff5555"


CONFIG = Config()


class FadeState(Enum):
    """Estados possíveis para o fade de áudio."""
    NONE = auto()
    TO_AD = auto()
    TO_RADIO = auto()


class PlaybackState(Enum):
    """Estados de reprodução."""
    STOPPED = auto()
    PLAYING = auto()
    PAUSED = auto()


# ============================================================================
# GERENCIADOR DE BANCO DE DADOS
# ============================================================================

class DatabaseManager:
    """
    Gerenciador de banco de dados com connection pooling e thread safety.
    Implementa o padrão Singleton para garantir uma única instância.
    """
    _instance: Optional['DatabaseManager'] = None
    _mutex = QMutex()
    
    def __new__(cls, db_name: str = CONFIG.db_name) -> 'DatabaseManager':
        if cls._instance is None:
            with QMutexLocker(cls._mutex):
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_name: str = CONFIG.db_name):
        if self._initialized:
            return
        self._initialized = True
        self.db_name = db_name
        self._init_db()
    
    def _init_db(self) -> None:
        """Inicializa as tabelas do banco de dados."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS songs (
                        id INTEGER PRIMARY KEY,
                        title TEXT NOT NULL,
                        artist TEXT NOT NULL,
                        program TEXT,
                        announcer TEXT,
                        popularity INTEGER DEFAULT 0,
                        cover_url TEXT,
                        played_at TEXT NOT NULL
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS intervals (
                        id INTEGER PRIMARY KEY,
                        start_time TEXT NOT NULL,
                        end_time TEXT,
                        duration_seconds REAL
                    )
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_songs_played_at 
                    ON songs(played_at DESC)
                ''')
                conn.commit()
                logger.info("Banco de dados inicializado com sucesso")
        except sqlite3.Error as e:
            logger.error(f"Erro ao inicializar banco de dados: {e}")
    
    @contextmanager
    def _get_connection(self):
        """Context manager para conexões com o banco."""
        conn = sqlite3.connect(self.db_name, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def sync_song(self, song: Dict[str, Any]) -> bool:
        """Sincroniza uma música com o banco de dados local."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO songs 
                    (id, title, artist, program, announcer, popularity, cover_url, played_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    song['id'],
                    song['title'],
                    song['artist'],
                    song.get('program', ''),
                    song.get('announcer', ''),
                    song.get('popularity', 0),
                    song.get('cover_url', ''),
                    song['played_at']
                ))
                conn.commit()
                return True
        except (sqlite3.Error, KeyError) as e:
            logger.error(f"Erro ao sincronizar música: {e}")
            return False
    
    def sync_interval(self, interval: Dict[str, Any]) -> bool:
        """Sincroniza um intervalo comercial com o banco de dados local."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO intervals 
                    (id, start_time, end_time, duration_seconds)
                    VALUES (?, ?, ?, ?)
                ''', (
                    interval['id'],
                    interval['start_time'],
                    interval.get('end_time'),
                    interval.get('duration_seconds')
                ))
                conn.commit()
                return True
        except (sqlite3.Error, KeyError) as e:
            logger.error(f"Erro ao sincronizar intervalo: {e}")
            return False
    
    def get_average_interval_duration(self) -> float:
        """Retorna a duração média dos intervalos comerciais."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                result = cursor.execute('''
                    SELECT AVG(duration_seconds) 
                    FROM intervals 
                    WHERE duration_seconds > 30
                ''').fetchone()
                return result[0] if result and result[0] else 180.0
        except sqlite3.Error as e:
            logger.error(f"Erro ao buscar duração média: {e}")
            return 180.0
    
    def get_last_songs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retorna as últimas músicas tocadas."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                rows = cursor.execute('''
                    SELECT title, artist, 
                           strftime('%H:%M', datetime(played_at, 'localtime')) as time
                    FROM songs 
                    ORDER BY id DESC 
                    LIMIT ?
                ''', (limit,)).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Erro ao buscar histórico: {e}")
            return []


# ============================================================================
# WIDGETS PERSONALIZADOS
# ============================================================================

class RoundedImageLabel(QLabel):
    """Label para exibir imagens com bordas arredondadas e estado de loading."""
    
    def __init__(self, size: int = 280, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._size = size
        self._pixmap: Optional[QPixmap] = None
        self._loading: bool = False
        self.setFixedSize(size, size)
        self._placeholder_text = "MUNDO\nLIVRE"
    
    def set_image(self, pixmap: Optional[QPixmap]) -> None:
        """Define a imagem a ser exibida."""
        self._pixmap = pixmap
        self._loading = False
        self.update()
    
    def set_loading(self, loading: bool = True) -> None:
        """Define o estado de carregamento."""
        self._loading = loading
        self.update()
    
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # Desenha o path arredondado
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 20, 20)
        painter.setClipPath(path)
        
        if self._pixmap and not self._pixmap.isNull():
            # Desenha a imagem escalada
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            # Desenha placeholder com gradiente
            gradient = QLinearGradient(0, 0, 0, self.height())
            gradient.setColorAt(0, QColor("#2a2a2a"))
            gradient.setColorAt(1, QColor("#1a1a1a"))
            painter.fillRect(self.rect(), gradient)
            
            # Desenha texto do placeholder
            painter.setPen(QColor("#444"))
            font = QFont("Segoe UI", 18, QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                self._placeholder_text
            )
            
            # Indicador de loading
            if self._loading:
                painter.setPen(QColor(CONFIG.color_primary))
                font.setPointSize(10)
                painter.setFont(font)
                painter.drawText(
                    self.rect().adjusted(0, 50, 0, 0),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                    "Carregando..."
                )


class AnimatedButton(QPushButton):
    """Botão com animação de hover e press."""
    
    def __init__(
        self, 
        text: str = "", 
        parent: Optional[QWidget] = None,
        icon_size: int = 16
    ):
        super().__init__(text, parent)
        self._icon_size = icon_size
        self._hover = False
        self._pressed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)
    
    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)
    
    def mousePressEvent(self, event) -> None:
        self._pressed = True
        self.update()
        super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event) -> None:
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)


class ProgressBar(QProgressBar):
    """Barra de progresso estilizada com animação."""
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self.setTextVisible(False)
        self.setValue(0)
        self._animated_value = 0


class VolumeSlider(QSlider):
    """Slider de volume com visual moderno."""
    
    def __init__(self, orientation: Qt.Orientation, parent: Optional[QWidget] = None):
        super().__init__(orientation, parent)
        self.setRange(0, 100)
        self.setValue(CONFIG.default_volume)
        self.setFixedSize(30, 70)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


# ============================================================================
# WORKERS (THREADS)
# ============================================================================

class ApiWorker(QThread):
    """Worker para buscar dados da API em background."""
    
    data_updated = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._running = True
    
    def run(self) -> None:
        """Executa a busca de dados da API."""
        try:
            # Busca status atual
            response = requests.get(
                f"{CONFIG.api_base_url}/now",
                timeout=CONFIG.connection_timeout
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") in ["interval", "voz_do_brasil"]:
                self.data_updated.emit({
                    "status": "ad_break",
                    "type": data.get("status")
                })
            else:
                # Busca histórico de músicas
                hist_response = requests.get(
                    f"{CONFIG.api_base_url}/history?limit=1",
                    timeout=CONFIG.connection_timeout
                )
                hist_response.raise_for_status()
                history = hist_response.json()
                
                if history:
                    song = history[0]
                    song["status"] = "playing"
                    self.data_updated.emit(song)
            
            # Sincroniza dados em background
            self._sync_background()
            
        except requests.RequestException as e:
            logger.error(f"Erro na requisição API: {e}")
            self.error_occurred.emit(f"Erro de conexão: {e}")
        except Exception as e:
            logger.error(f"Erro inesperado: {e}")
            self.error_occurred.emit(str(e))
    
    def _sync_background(self) -> None:
        """Sincroniza dados com o banco local."""
        db = DatabaseManager()
        try:
            # Sincroniza músicas
            songs_response = requests.get(
                f"{CONFIG.api_base_url}/history?limit=10",
                timeout=CONFIG.connection_timeout
            )
            songs_response.raise_for_status()
            for song in songs_response.json():
                db.sync_song(song)
            
            # Sincroniza intervalos
            intervals_response = requests.get(
                f"{CONFIG.api_base_url}/intervals?limit=10",
                timeout=CONFIG.connection_timeout
            )
            intervals_response.raise_for_status()
            for interval in intervals_response.json():
                db.sync_interval(interval)
                
        except requests.RequestException as e:
            logger.warning(f"Erro na sincronização background: {e}")
    
    def stop(self) -> None:
        """Para o worker de forma segura."""
        self._running = False
        self.wait()


class ImageLoaderWorker(QThread):
    """Worker para carregar imagens de forma assíncrona."""
    
    image_loaded = pyqtSignal(QPixmap)
    load_failed = pyqtSignal()
    
    def __init__(self, url: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._url = url
    
    def run(self) -> None:
        """Carrega a imagem da URL."""
        try:
            response = requests.get(self._url, timeout=CONFIG.image_timeout)
            response.raise_for_status()
            
            pixmap = QPixmap()
            if pixmap.loadFromData(response.content):
                self.image_loaded.emit(pixmap)
            else:
                self.load_failed.emit()
                
        except requests.RequestException as e:
            logger.warning(f"Erro ao carregar imagem: {e}")
            self.load_failed.emit()


# ============================================================================
# APLICAÇÃO PRINCIPAL
# ============================================================================

class RadioPlayer(QWidget):
    """Player de rádio principal com interface moderna."""
    
    def __init__(self):
        super().__init__()
        
        # Estado interno
        self._current_song_id: int = -1
        self._is_ad_mode: bool = False
        self._user_volume: float = CONFIG.default_volume / 100
        self._playback_state: PlaybackState = PlaybackState.STOPPED
        self._fade_state: FadeState = FadeState.NONE
        self._ad_start_time: Optional[datetime.datetime] = None
        self._estimated_ad_duration: float = 180.0
        
        # Componentes
        self._db = DatabaseManager()
        self._api_worker: Optional[ApiWorker] = None
        self._image_worker: Optional[ImageLoaderWorker] = None
        
        # Inicialização
        self._setup_players()
        self._setup_ui()
        self._setup_tray()
        self._setup_timers()
        
        # Inicia a primeira busca de dados
        QTimer.singleShot(100, self._fetch_api_data)
    
    # ========================================================================
    # SETUP
    # ========================================================================
    
    def _setup_players(self) -> None:
        """Configura os players de áudio."""
        # Player principal
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        self._player.setSource(QUrl(CONFIG.url_streaming))
        self._audio_output.setVolume(self._user_volume)
        
        # Player de overlay (lo-fi)
        self._overlay_player = QMediaPlayer()
        self._overlay_output = QAudioOutput()
        self._overlay_player.setAudioOutput(self._overlay_output)
        self._overlay_output.setVolume(0)
        
        # Conectar sinais de erro
        self._player.errorOccurred.connect(self._on_player_error)
        self._overlay_player.errorOccurred.connect(self._on_overlay_error)
    
    def _setup_ui(self) -> None:
        """Configura a interface do usuário."""
        self.setWindowTitle("Mundo Livre Player")
        self.setFixedSize(CONFIG.window_width, CONFIG.window_height)
        self.setStyleSheet(self._get_stylesheet())
        
        # Layout principal
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 30, 25, 30)
        layout.setSpacing(0)
        
        # Header
        layout.addLayout(self._create_header())
        layout.addSpacing(25)
        
        # Capa do álbum
        layout.addLayout(self._create_cover_section())
        layout.addSpacing(30)
        
        # Informações da música
        layout.addLayout(self._create_info_section())
        layout.addSpacing(20)
        
        # Barra de popularidade
        layout.addLayout(self._create_popularity_section())
        
        layout.addStretch()
        
        # Dock de controles
        layout.addWidget(self._create_controls_dock())
    
    def _create_header(self) -> QHBoxLayout:
        """Cria o cabeçalho com logo e ADBLOCK toggle."""
        header = QHBoxLayout()
        
        # Logo
        logo_label = QLabel("MUNDO LIVRE")
        logo_label.setStyleSheet(f"""
            color: {CONFIG.color_primary};
            font-weight: 900;
            letter-spacing: 2px;
            font-size: 14px;
        """)
        
        # ADBLOCK toggle
        self._chk_adblock = QCheckBox("ADBLOCK")
        self._chk_adblock.setChecked(True)
        self._chk_adblock.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chk_adblock.setToolTip(
            "Quando ativo, toca música lo-fi durante intervalos comerciais"
        )
        self._chk_adblock.setStyleSheet(f"""
            QCheckBox {{
                color: #888;
                font-weight: bold;
                font-size: 10px;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 9px;
                border: 2px solid #444;
            }}
            QCheckBox::indicator:checked {{
                background-color: {CONFIG.color_primary};
                border-color: {CONFIG.color_primary};
            }}
            QCheckBox::indicator:hover {{
                border-color: {CONFIG.color_primary};
            }}
        """)
        
        header.addWidget(logo_label)
        header.addStretch()
        header.addWidget(self._chk_adblock)
        
        return header
    
    def _create_cover_section(self) -> QHBoxLayout:
        """Cria a seção da capa do álbum."""
        self._lbl_cover = RoundedImageLabel(280)
        
        # Sombra
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(50)
        shadow.setColor(QColor(19, 236, 106, 60))
        shadow.setOffset(0, 15)
        self._lbl_cover.setGraphicsEffect(shadow)
        
        layout = QHBoxLayout()
        layout.addStretch()
        layout.addWidget(self._lbl_cover)
        layout.addStretch()
        
        return layout
    
    def _create_info_section(self) -> QVBoxLayout:
        """Cria a seção de informações da música."""
        layout = QVBoxLayout()
        layout.setSpacing(8)
        
        # Badge de intervalo
        self._badge_ad = QLabel("INTERVALO COMERCIAL")
        self._badge_ad.setFixedHeight(28)
        self._badge_ad.setStyleSheet(f"""
            background: {CONFIG.color_accent};
            color: white;
            border-radius: 14px;
            font-weight: bold;
            font-size: 11px;
            padding: 0 15px;
        """)
        self._badge_ad.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge_ad.hide()
        
        badge_layout = QHBoxLayout()
        badge_layout.addStretch()
        badge_layout.addWidget(self._badge_ad)
        badge_layout.addStretch()
        layout.addLayout(badge_layout)
        
        # Título da música
        self._lbl_title = QLabel("Conectando...")
        self._lbl_title.setStyleSheet("""
            font-size: 22px;
            font-weight: bold;
        """)
        self._lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_title.setWordWrap(True)
        
        # Artista
        self._lbl_artist = QLabel("Aguarde")
        self._lbl_artist.setStyleSheet(f"""
            font-size: 14px;
            color: {CONFIG.color_text_secondary};
        """)
        self._lbl_artist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Timer de countdown
        self._lbl_timer = QLabel("")
        self._lbl_timer.setStyleSheet(f"""
            color: {CONFIG.color_warning};
            font-size: 13px;
            font-weight: bold;
            margin-top: 5px;
        """)
        self._lbl_timer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(self._lbl_title)
        layout.addWidget(self._lbl_artist)
        layout.addWidget(self._lbl_timer)
        
        return layout
    
    def _create_popularity_section(self) -> QHBoxLayout:
        """Cria a seção de popularidade."""
        layout = QHBoxLayout()
        
        fire_label = QLabel("🔥")
        fire_label.setStyleSheet("font-size: 16px;")
        
        self._bar_popularity = ProgressBar()
        self._bar_popularity.setStyleSheet(f"""
            QProgressBar {{
                background: #333;
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {CONFIG.color_primary};
                border-radius: 3px;
            }}
        """)
        
        layout.addWidget(fire_label)
        layout.addSpacing(8)
        layout.addWidget(self._bar_popularity)
        
        return layout
    
    def _create_controls_dock(self) -> QFrame:
        """Cria o dock de controles."""
        dock = QFrame()
        dock.setFixedHeight(100)
        dock.setStyleSheet(f"""
            QFrame {{
                background: {CONFIG.color_card};
                border-radius: 24px;
                border: 1px solid #333;
            }}
        """)
        
        layout = QHBoxLayout(dock)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(10)
        
        # Botão histórico
        self._btn_history = AnimatedButton("📜")
        self._btn_history.setFixedSize(40, 40)
        self._btn_history.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                font-size: 20px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.1);
                border-radius: 20px;
            }
        """)
        self._btn_history.setToolTip("Ver histórico de músicas")
        self._btn_history.clicked.connect(self._show_history_menu)
        
        # Botão stop
        self._btn_stop = AnimatedButton("⏹")
        self._btn_stop.setFixedSize(44, 44)
        self._btn_stop.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255,85,85,0.2);
                border-radius: 22px;
                color: {CONFIG.color_danger};
                font-size: 18px;
            }}
            QPushButton:hover {{
                background: rgba(255,85,85,0.3);
            }}
        """)
        self._btn_stop.setToolTip("Parar reprodução")
        self._btn_stop.clicked.connect(self._stop_playback)
        
        # Botão play/pause principal
        self._btn_play = AnimatedButton("▶")
        self._btn_play.setFixedSize(64, 64)
        self._btn_play.setStyleSheet(f"""
            QPushButton {{
                background: white;
                color: black;
                border-radius: 32px;
                font-size: 26px;
                padding-left: 4px;
            }}
            QPushButton:hover {{
                background: {CONFIG.color_primary};
            }}
            QPushButton:pressed {{
                background: #0fb85a;
            }}
        """)
        self._btn_play.setToolTip("Play/Pause")
        self._btn_play.clicked.connect(self._toggle_play_pause)
        
        # Botão refresh
        self._btn_refresh = AnimatedButton("↻")
        self._btn_refresh.setFixedSize(40, 40)
        self._btn_refresh.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #777;
                font-size: 22px;
            }
            QPushButton:hover {
                color: white;
                background: rgba(255,255,255,0.1);
                border-radius: 20px;
            }
        """)
        self._btn_refresh.setToolTip("Atualizar informações")
        self._btn_refresh.clicked.connect(self._fetch_api_data)
        
        # Slider de volume
        self._slider_volume = VolumeSlider(Qt.Orientation.Vertical)
        self._slider_volume.setStyleSheet(f"""
            QSlider::groove:vertical {{
                width: 6px;
                background: #333;
                border-radius: 3px;
            }}
            QSlider::sub-page:vertical {{
                background: transparent;
            }}
            QSlider::add-page:vertical {{
                background: {CONFIG.color_primary};
                border-radius: 3px;
            }}
            QSlider::handle:vertical {{
                width: 14px;
                height: 14px;
                margin: 0 -4px;
                background: white;
                border-radius: 7px;
            }}
            QSlider::handle:vertical:hover {{
                background: {CONFIG.color_primary};
            }}
        """)
        self._slider_volume.setToolTip("Volume")
        self._slider_volume.valueChanged.connect(self._on_volume_changed)
        
        layout.addWidget(self._btn_history)
        layout.addStretch()
        layout.addWidget(self._btn_stop)
        layout.addSpacing(8)
        layout.addWidget(self._btn_play)
        layout.addSpacing(8)
        layout.addWidget(self._btn_refresh)
        layout.addStretch()
        layout.addWidget(self._slider_volume)
        
        return dock
    
    def _setup_timers(self) -> None:
        """Configura os timers do aplicativo."""
        # Timer de polling da API
        self._timer_api = QTimer(self)
        self._timer_api.setInterval(CONFIG.api_poll_interval)
        self._timer_api.timeout.connect(self._fetch_api_data)
        self._timer_api.start()
        
        # Timer de fade
        self._timer_fade = QTimer(self)
        self._timer_fade.setInterval(CONFIG.fade_interval)
        self._timer_fade.timeout.connect(self._process_fade)
        
        # Timer de countdown
        self._timer_countdown = QTimer(self)
        self._timer_countdown.setInterval(1000)
        self._timer_countdown.timeout.connect(self._update_countdown)
    
    def _setup_tray(self) -> None:
        """Configura o ícone na bandeja do sistema."""
        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self._tray_icon.setToolTip("Mundo Livre Player")
        
        # Menu do tray
        tray_menu = QMenu()
        tray_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {CONFIG.color_card};
                color: white;
                border: 1px solid #444;
                padding: 8px;
                border-radius: 8px;
            }}
            QMenu::item {{
                padding: 8px 25px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {CONFIG.color_primary};
                color: black;
            }}
        """)
        
        # Ação play/pause
        self._tray_action_play = QAction("▶ Play", self)
        self._tray_action_play.triggered.connect(self._toggle_play_pause)
        tray_menu.addAction(self._tray_action_play)
        
        # Ação stop
        action_stop = QAction("⏹ Parar", self)
        action_stop.triggered.connect(self._stop_playback)
        tray_menu.addAction(action_stop)
        
        tray_menu.addSeparator()
        
        # Ação restaurar janela
        action_restore = QAction("📦 Restaurar", self)
        action_restore.triggered.connect(self._restore_window)
        tray_menu.addAction(action_restore)
        
        tray_menu.addSeparator()
        
        # Ação sair
        action_exit = QAction("❌ Sair", self)
        action_exit.triggered.connect(self._quit_application)
        tray_menu.addAction(action_exit)
        
        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()
    
    # ========================================================================
    # STYLESHEET
    # ========================================================================
    
    def _get_stylesheet(self) -> str:
        """Retorna o stylesheet principal do aplicativo."""
        return f"""
            QWidget {{
                background-color: {CONFIG.color_bg};
                color: {CONFIG.color_text};
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            
            QToolTip {{
                background-color: {CONFIG.color_card_light};
                color: white;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            
            QMenu {{
                background-color: {CONFIG.color_card};
                color: white;
                border: 1px solid #444;
                padding: 8px;
                border-radius: 8px;
            }}
            
            QMenu::item {{
                padding: 8px 20px;
                border-radius: 4px;
            }}
            
            QMenu::item:selected {{
                background-color: {CONFIG.color_primary};
                color: black;
            }}
        """
    
    # ========================================================================
    # LÓGICA DE API
    # ========================================================================
    
    def _fetch_api_data(self) -> None:
        """Busca dados da API."""
        # Verifica se há um worker ativo de forma segura
        try:
            if self._api_worker is not None:
                # Tenta verificar se está rodando - pode falhar se objeto foi deletado
                try:
                    if self._api_worker.isRunning():
                        return
                except RuntimeError:
                    # Objeto C++ foi deletado, cria novo
                    self._api_worker = None
        except RuntimeError:
            self._api_worker = None
        
        self._api_worker = ApiWorker()
        self._api_worker.data_updated.connect(self._on_data_updated)
        self._api_worker.error_occurred.connect(self._on_api_error)
        self._api_worker.finished.connect(self._on_api_worker_finished)
        self._api_worker.start()
    
    def _on_api_worker_finished(self) -> None:
        """Callback quando o worker termina."""
        sender = self.sender()
        if sender:
            sender.deleteLater()
    
    def _on_data_updated(self, data: Dict[str, Any]) -> None:
        """Processa dados recebidos da API."""
        if data.get("status") == "ad_break":
            self._enter_ad_mode()
            return
        
        self._exit_ad_mode()
        
        # Atualiza informações da música
        title = data.get("title", "Desconhecido")
        artist = data.get("artist", "Artista desconhecido")
        popularity = data.get("popularity", 0)
        
        self._lbl_title.setText(title)
        self._lbl_artist.setText(artist)
        self._bar_popularity.setValue(min(100, popularity))
        
        # Carrega capa se a música mudou
        if data.get("id") != self._current_song_id:
            self._current_song_id = data.get("id", -1)
            
            if data.get("cover_url"):
                self._load_cover_image(data["cover_url"])
            else:
                self._lbl_cover.set_image(None)
            
            # Notificação do tray
            self._tray_icon.showMessage(
                "Tocando Agora",
                f"{title} - {artist}",
                QSystemTrayIcon.MessageIcon.NoIcon,
                3000
            )
    
    def _on_api_error(self, error_message: str) -> None:
        """Trata erros da API."""
        logger.warning(f"Erro da API: {error_message}")
        self._lbl_title.setText("Sem conexão")
        self._lbl_artist.setText("Verificando...")
    
    def _load_cover_image(self, url: str) -> None:
        """Carrega a imagem de capa de forma assíncrona."""
        self._lbl_cover.set_loading(True)
        
        # Para worker anterior de forma segura
        try:
            if self._image_worker is not None:
                try:
                    if self._image_worker.isRunning():
                        self._image_worker.quit()
                        self._image_worker.wait(1000)
                except RuntimeError:
                    # Objeto já foi deletado
                    self._image_worker = None
        except RuntimeError:
            self._image_worker = None
        
        self._image_worker = ImageLoaderWorker(url)
        self._image_worker.image_loaded.connect(self._lbl_cover.set_image)
        self._image_worker.load_failed.connect(
            lambda: self._lbl_cover.set_image(None)
        )
        self._image_worker.finished.connect(self._on_image_worker_finished)
        self._image_worker.start()
    
    def _on_image_worker_finished(self) -> None:
        """Callback quando o worker de imagem termina."""
        sender = self.sender()
        if sender:
            sender.deleteLater()
    
    # ========================================================================
    # LÓGICA DE REPRODUÇÃO
    # ========================================================================
    
    def _toggle_play_pause(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self._overlay_player.pause()
            self._playback_state = PlaybackState.PAUSED
            self._btn_play.setText("▶")
            self._tray_action_play.setText("▶ Play")
        else:
            # Verifica se está em modo de intervalo com ADBLOCK ativo
            if self._is_ad_mode and self._chk_adblock.isChecked():
                # Garante que o source está definido
                if self._overlay_player.source().isEmpty():
                    self._overlay_player.setSource(QUrl(CONFIG.url_lofi_overlay))
                # Configura volumes para modo intervalo
                self._audio_output.setVolume(0)
                self._overlay_output.setVolume(CONFIG.overlay_max_vol)
                self._overlay_player.play()
            else:
                # Modo normal - garante volume correto
                self._audio_output.setVolume(self._user_volume)
            
            self._player.play()
            self._playback_state = PlaybackState.PLAYING
            self._btn_play.setText("❚❚")
            self._tray_action_play.setText("❚❚ Pause")
    
    def _stop_playback(self) -> None:
        """Para a reprodução."""
        self._player.stop()
        self._overlay_player.stop()
        self._playback_state = PlaybackState.STOPPED
        self._btn_play.setText("▶")
        self._tray_action_play.setText("▶ Play")
    
    def _on_volume_changed(self, value: int) -> None:
        """Trata mudanças de volume."""
        self._user_volume = value / 100
        if not self._is_ad_mode:
            self._audio_output.setVolume(self._user_volume)
    
    # ========================================================================
    # LÓGICA DE INTERVALO COMERCIAL
    # ========================================================================
    
    def _enter_ad_mode(self) -> None:
        """Entra no modo de intervalo comercial."""
        if self._is_ad_mode:
            return
        
        self._is_ad_mode = True
        self._ad_start_time = datetime.datetime.now()
        self._estimated_ad_duration = self._db.get_average_interval_duration()
        
        # Atualiza UI
        self._lbl_title.setText("Intervalo Comercial")
        self._lbl_artist.setText("Mundo Livre FM")
        self._lbl_cover.set_image(None)
        self._bar_popularity.setValue(0)
        self._badge_ad.show()
        self._lbl_timer.show()
        
        # Inicia countdown
        self._timer_countdown.start()
        
        # Fade para overlay se ADBLOCK ativo
        if self._chk_adblock.isChecked():
            # Verifica se o rádio está tocando (estado real do player)
            is_radio_playing = self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            
            # Sempre define o source do overlay
            self._overlay_player.setSource(QUrl(CONFIG.url_lofi_overlay))
            
            if is_radio_playing:
                # Fade suave: rádio -> overlay
                self._overlay_player.play()
                self._fade_state = FadeState.TO_AD
                self._timer_fade.start()
            else:
                # Rádio não está tocando, inicia overlay diretamente
                self._audio_output.setVolume(0)
                self._overlay_output.setVolume(CONFIG.overlay_max_vol)
                self._overlay_player.play()
    
    def _exit_ad_mode(self) -> None:
        """Sai do modo de intervalo comercial."""
        if not self._is_ad_mode:
            return
        
        self._is_ad_mode = False
        self._badge_ad.hide()
        self._lbl_timer.hide()
        self._timer_countdown.stop()
        
        # Verifica estado real do player
        is_radio_playing = self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        
        if self._chk_adblock.isChecked():
            # ADBLOCK estava ativo - precisamos voltar para rádio
            if is_radio_playing:
                # Fade suave: overlay -> rádio
                self._fade_state = FadeState.TO_RADIO
                self._timer_fade.start()
            else:
                # Rádio não está tocando, apenas para o overlay
                self._overlay_player.stop()
                self._overlay_output.setVolume(0)
                # Restaura volume do rádio para quando voltar a tocar
                self._audio_output.setVolume(self._user_volume)
        else:
            # ADBLOCK não estava ativo, apenas restaura volume do rádio
            self._audio_output.setVolume(self._user_volume)
            # Garante que overlay está parado
            self._overlay_player.stop()
    
    def _update_countdown(self) -> None:
        """Atualiza o countdown do intervalo."""
        if not self._ad_start_time:
            return
        
        elapsed = (datetime.datetime.now() - self._ad_start_time).total_seconds()
        remaining = max(0, self._estimated_ad_duration - elapsed)
        
        minutes, seconds = divmod(int(remaining), 60)
        self._lbl_timer.setText(f"⏱ Retorno em: {minutes:02d}:{seconds:02d}")
    
    # ========================================================================
    # LÓGICA DE FADE
    # ========================================================================
    
    def _process_fade(self) -> None:
        """Processa o fade de áudio."""
        main_vol = self._audio_output.volume()
        overlay_vol = self._overlay_output.volume()
        
        if self._fade_state == FadeState.TO_AD:
            # Fade out do rádio, fade in do overlay
            new_main = max(0.0, main_vol - CONFIG.fade_step)
            new_overlay = min(CONFIG.overlay_max_vol, overlay_vol + CONFIG.fade_step)
            
            self._audio_output.setVolume(new_main)
            self._overlay_output.setVolume(new_overlay)
            
            if new_main <= 0:
                self._fade_state = FadeState.NONE
                self._timer_fade.stop()
        
        elif self._fade_state == FadeState.TO_RADIO:
            # Fade out do overlay, fade in do rádio
            new_overlay = max(0.0, overlay_vol - CONFIG.fade_step)
            new_main = min(self._user_volume, main_vol + CONFIG.fade_step)
            
            self._overlay_output.setVolume(new_overlay)
            self._audio_output.setVolume(new_main)
            
            if new_overlay <= 0:
                self._overlay_player.stop()
                self._fade_state = FadeState.NONE
                self._timer_fade.stop()
    
    # ========================================================================
    # HISTÓRICO
    # ========================================================================
    
    def _show_history_menu(self) -> None:
        """Exibe o menu de histórico de músicas."""
        songs = self._db.get_last_songs(10)
        
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {CONFIG.color_card};
                color: white;
                border: 1px solid {CONFIG.color_primary};
                padding: 10px;
                border-radius: 10px;
                min-width: 300px;
            }}
            QMenu::item {{
                padding: 10px 15px;
                border-radius: 6px;
                margin: 2px 0;
            }}
            QMenu::item:selected {{
                background-color: {CONFIG.color_primary};
                color: black;
            }}
        """)
        
        if not songs:
            menu.addAction("Nenhuma música no histórico")
        else:
            for song in songs:
                text = f"{song['time']} • {song['title']} - {song['artist']}"
                menu.addAction(text)
        
        menu.exec(self._btn_history.mapToGlobal(
            QPoint(0, -menu.sizeHint().height() - 10)
        ))
    
    # ========================================================================
    # EVENTOS
    # ========================================================================
    
    def _on_player_error(self, error) -> None:
        """Trata erros do player principal."""
        logger.error(f"Erro no player principal: {error}")
        self._lbl_title.setText("Erro de reprodução")
        self._lbl_artist.setText("Tente novamente")
    
    def _on_overlay_error(self, error) -> None:
        """Trata erros do player de overlay."""
        logger.error(f"Erro no player de overlay: {error}")
    
    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Trata ativações do ícone de bandeja."""
        # Clique esquerdo ou duplo clique = restaurar janela
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick
        ):
            self._restore_window()
    
    def _restore_window(self) -> None:
        """Restaura a janela principal."""
        self.show()
        self.activateWindow()
        self.raise_()
    
    def closeEvent(self, event) -> None:
        """Trata o fechamento da janela."""
        event.ignore()
        self.hide()
        self._tray_icon.showMessage(
            "Mundo Livre Player",
            "Minimizado para a bandeja. Clique para restaurar.",
            QSystemTrayIcon.MessageIcon.NoIcon,
            2000
        )
    
    def _quit_application(self) -> None:
        """Encerra o aplicativo de forma segura."""
        # Para timers
        self._timer_api.stop()
        self._timer_fade.stop()
        self._timer_countdown.stop()
        
        # Para workers
        if self._api_worker:
            self._api_worker.stop()
        if self._image_worker:
            self._image_worker.quit()
            self._image_worker.wait()
        
        # Para players
        self._player.stop()
        self._overlay_player.stop()
        
        # Esconde tray
        self._tray_icon.hide()
        
        # Sai
        QApplication.quit()


# ============================================================================
# PONTO DE ENTRADA
# ============================================================================

def main():
    """Função principal do aplicativo."""
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # Configura fonte da aplicação
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    # Cria e exibe a janela
    window = RadioPlayer()
    window.show()
    
    logger.info("Mundo Livre Player iniciado")
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
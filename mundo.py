import sys
import os
import requests
import sqlite3
import datetime
from dotenv import load_dotenv

from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QProgressBar, QFrame, QSlider, 
                             QCheckBox, QSystemTrayIcon, QMenu, QStyle, QGraphicsDropShadowEffect,
                             QDialog, QScrollArea, QShortcut)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QUrl, QTimer, QPoint, QByteArray
from PyQt6.QtGui import QFont, QPixmap, QImage, QAction, QCloseEvent, QColor, QPainter, QPainterPath, QLinearGradient, QKeySequence
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

load_dotenv()

# --- CONSTANTES ---
API_BASE_URL = "http://167.126.18.152:8000" 
URL_RADIO_JSON = "https://music-stream-data.grpcomradios.com.br/player/rML939.json"
URL_STREAMING = "https://playerservices.streamtheworld.com/api/livestream-redirect/MUNDOLIVRE_CWBAAC_64.aac"
URL_LOFI_OVERLAY = "http://stream.zeno.fm/0r0xa792kwzuv" 
BLOCKLIST_TERMS = ["MUNDO LIVRE", "INTERVALO", "COMERCIAL", "AUDIO", "VINHETA", "RADIO"]
DB_NAME = "radio_local_buffer.db"
FADE_STEP = 0.05      
FADE_INTERVAL = 100   
OVERLAY_MAX_VOL = 0.5 

# --- DATABASE (BUFFER LOCAL) ---
class DatabaseHandler:
    def __init__(self, db_name=DB_NAME):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        try:
            with sqlite3.connect(self.db_name) as conn:
                c = conn.cursor()
                c.execute('''
                    CREATE TABLE IF NOT EXISTS songs (
                        id INTEGER PRIMARY KEY,
                        title TEXT,
                        artist TEXT,
                        program TEXT,
                        announcer TEXT,
                        popularity INTEGER,
                        played_at TEXT
                    )
                ''')
                
                # Migrações para evitar erro se DB já existir antigo
                try: c.execute("ALTER TABLE songs ADD COLUMN program TEXT")
                except: pass
                try: c.execute("ALTER TABLE songs ADD COLUMN announcer TEXT")
                except: pass

                c.execute('''
                    CREATE TABLE IF NOT EXISTS intervals (
                        id INTEGER PRIMARY KEY,
                        start_time TEXT,
                        end_time TEXT,
                        duration_seconds REAL
                    )
                ''')
                conn.commit()
        except Exception as e:
            print(f"Erro DB: {e}")

    def sync_song(self, song_data):
        try:
            with sqlite3.connect(self.db_name) as conn:
                c = conn.cursor()
                program = song_data.get('program', '')
                announcer = song_data.get('announcer', '')
                
                c.execute("""
                    INSERT OR IGNORE INTO songs (id, title, artist, program, announcer, popularity, played_at) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (song_data['id'], song_data['title'], song_data['artist'], 
                      program, announcer, song_data['popularity'], song_data['played_at']))
                conn.commit()
        except Exception as e:
            print(f"Erro sync song: {e}")

    def sync_interval(self, interval_data):
        try:
            with sqlite3.connect(self.db_name) as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT OR IGNORE INTO intervals (id, start_time, end_time, duration_seconds) 
                    VALUES (?, ?, ?, ?)
                """, (interval_data['id'], interval_data['start_time'], interval_data['end_time'], interval_data['duration_seconds']))
                conn.commit()
        except Exception as e:
            print(f"Erro sync interval: {e}")

    def get_average_interval_duration(self):
        try:
            with sqlite3.connect(self.db_name) as conn:
                c = conn.cursor()
                c.execute("SELECT AVG(duration_seconds) FROM intervals WHERE duration_seconds BETWEEN 30 AND 600")
                res = c.fetchone()[0]
                return res if res else 180
        except:
            return 180

    def get_last_songs(self, limit=5):
        try:
            with sqlite3.connect(self.db_name) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT title, artist, strftime('%H:%M', datetime(played_at, 'localtime'))
                    FROM songs 
                    ORDER BY id DESC LIMIT ?
                """, (limit,))
                return c.fetchall()
        except:
            return []

# --- GUI AUXILIARES ---
class RoundedImage(QLabel):
    def __init__(self, size, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.target_pixmap = None

    def set_image(self, pixmap):
        self.target_pixmap = pixmap
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 20, 20)
        painter.setClipPath(path)
        
        if self.target_pixmap:
            scaled = self.target_pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, QColor("#333"))
            grad.setColorAt(1.0, QColor("#1a1a1a"))
            painter.fillRect(self.rect(), grad)
            
            painter.setPen(QColor("#555"))
            painter.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "MUNDO LIVRE")

# --- WORKER DE IMAGEM (NOVO) ---
class ImageWorker(QThread):
    image_loaded = pyqtSignal(QPixmap)

    def __init__(self, query):
        super().__init__()
        self.query = query

    def run(self):
        if not self.query: return
        try:
            # 1. Busca na API do iTunes
            search_url = f"https://itunes.apple.com/search?term={self.query}&media=music&limit=1"
            resp = requests.get(search_url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data["resultCount"] > 0:
                    # Pega a url de 100x100 e transforma em 600x600 para alta qualidade
                    img_url = data["results"][0]["artworkUrl100"]
                    img_url = img_url.replace("100x100bb", "600x600bb")
                    
                    img_resp = requests.get(img_url, timeout=10)
                    if img_resp.status_code == 200:
                        pixmap = QPixmap()
                        pixmap.loadFromData(img_resp.content)
                        if not pixmap.isNull():
                            self.image_loaded.emit(pixmap)
        except Exception as e:
            print(f"Erro ao baixar imagem: {e}")

# --- WORKER API/REMOTO ---
class ApiWorker(QThread):
    data_updated = pyqtSignal(dict) 
    sync_finished = pyqtSignal()    
    error = pyqtSignal(str)

    def __init__(self, current_track_name=None):
        super().__init__()
        self.current_track_name = current_track_name 

    def run(self):
        try:
            # Check Radio JSON (Ad detection fallback)
            try:
                res = requests.get(URL_RADIO_JSON, timeout=3)
                radio_data = res.json()
            except:
                radio_data = {}

            art = str(radio_data.get("artista", "")).strip().upper()
            mus = str(radio_data.get("musica", "")).strip().upper()
            is_ad = False
            
            if not art or not mus or any(t in art for t in BLOCKLIST_TERMS) or any(t in mus for t in BLOCKLIST_TERMS):
                is_ad = True
                self.data_updated.emit({"status": "ad_break"})
            
            # Check VPS API
            try:
                res_hist = requests.get(f"{API_BASE_URL}/history?limit=1", timeout=4)
                if res_hist.status_code == 200:
                    history_list = res_hist.json()
                    if history_list:
                        latest_song = history_list[0]
                        if not is_ad:
                            api_title = latest_song['title'].strip().upper()
                            radio_title = mus.strip().upper()
                            
                            # Logica de match simples
                            if api_title in radio_title or radio_title in api_title or not mus:
                                self.data_updated.emit({
                                    "status": "playing",
                                    "title": latest_song['title'],
                                    "artist": latest_song['artist'],
                                    "program": latest_song.get('program', ''),
                                    "announcer": latest_song.get('announcer', ''),
                                    "popularity": latest_song['popularity'],
                                    "obj": latest_song 
                                })
                            else:
                                self.data_updated.emit({
                                    "status": "playing",
                                    "title": radio_data.get("musica"),
                                    "artist": radio_data.get("artista"),
                                    "program": "",
                                    "announcer": "",
                                    "popularity": 0,
                                    "obj": None
                                })
            except Exception:
                if not is_ad:
                     self.data_updated.emit({
                        "status": "playing",
                        "title": radio_data.get("musica"),
                        "artist": radio_data.get("artista"),
                        "program": "",
                        "announcer": "",
                        "popularity": 0,
                        "obj": None
                    })

            self.sync_local_buffer()

        except Exception as e:
            self.error.emit(str(e))

    def sync_local_buffer(self):
        db = DatabaseHandler()
        try:
            r_songs = requests.get(f"{API_BASE_URL}/history?limit=10", timeout=5)
            if r_songs.status_code == 200:
                for song in r_songs.json(): db.sync_song(song)
            r_intervals = requests.get(f"{API_BASE_URL}/intervals?limit=5", timeout=5)
            if r_intervals.status_code == 200:
                for interval in r_intervals.json(): db.sync_interval(interval)
            self.sync_finished.emit()
        except: pass

# --- APP PRINCIPAL ---
class RadioApp(QWidget):
    def __init__(self):
        super().__init__()
        self.current_song_name = ""
        self.last_notified_song = ""
        self.is_ad_mode = False       
        self.user_volume = 0.8        
        self.fade_state = None        
        self.user_stopped = True 
        
        self.db = DatabaseHandler()
        self.ad_start_time = None
        self.estimated_ad_duration = 0
        self.image_worker = None # Variável para guardar o worker da imagem
        
        # Novos estados
        self.last_volume = 0.8
        self.is_online = False

        self.init_players()
        self.initUI()
        self.init_tray()
        self.init_timers()
        self.init_shortcuts()  # Novo: atalhos de teclado 

    def init_players(self):
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setSource(QUrl(URL_STREAMING))
        self.audio_output.setVolume(self.user_volume)

        self.overlay_player = QMediaPlayer()
        self.overlay_output = QAudioOutput()
        self.overlay_player.setAudioOutput(self.overlay_output)
        self.overlay_output.setVolume(0) 

    def init_timers(self):
        self.check_timer = QTimer()
        self.check_timer.setInterval(10000)
        self.check_timer.timeout.connect(self.auto_fetch_data)
        self.check_timer.start()

        self.countdown_timer = QTimer()
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self.update_ad_countdown)

        self.fade_timer = QTimer()
        self.fade_timer.setInterval(FADE_INTERVAL)
        self.fade_timer.timeout.connect(self.process_fade)

    def init_shortcuts(self):
        """Atalhos de teclado globais"""
        # Espaço: Play/Pause
        play_shortcut = QShortcut(QKeySequence("Space"), self)
        play_shortcut.activated.connect(self.toggle_play_pause)
        
        # S: Stop
        stop_shortcut = QShortcut(QKeySequence("S"), self)
        stop_shortcut.activated.connect(self.stop_radio)
        
        # Ctrl+R: Refresh
        refresh_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        refresh_shortcut.activated.connect(lambda: self.start_worker(False))
        
        # Ctrl+H: History
        history_shortcut = QShortcut(QKeySequence("Ctrl+H"), self)
        history_shortcut.activated.connect(self.show_history_dialog)
        
        # Ctrl+Q: Quit
        quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        quit_shortcut.activated.connect(self.quit_app)
        
        # M: Mute
        mute_shortcut = QShortcut(QKeySequence("M"), self)
        mute_shortcut.activated.connect(self.toggle_mute)

    def initUI(self):
        self.setWindowTitle("Mundo Livre Player (Client)")
        self.setFixedSize(380, 700)
        self.setStyleSheet("""
            QWidget { background-color: #121212; color: #FFFFFF; font-family: 'Segoe UI', sans-serif; }
            QToolTip { color: #ffffff; background-color: #333333; border: 1px solid #555555; padding: 5px; }
            QMenu { background-color: #252525; border: 1px solid #444; padding: 5px; border-radius: 8px; }
            QMenu::item { padding: 8px 20px; font-size: 13px; color: #ddd; border-radius: 4px; }
            QMenu::item:selected { background-color: #1DB954; color: white; }
        """)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(25, 30, 25, 30)
        main_layout.setSpacing(0)

        header = QHBoxLayout()
        lbl_logo = QLabel("MUNDO LIVRE")
        lbl_logo.setStyleSheet("color: #1DB954; font-weight: 900; letter-spacing: 1px;")
        
        # Status indicator (novo)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(10, 10)
        self.status_dot.setStyleSheet("background-color: #FF5252; border-radius: 5px;")
        self.status_indicator = QLabel("Offline")
        self.status_indicator.setStyleSheet("color: #888; font-size: 11px;")
        
        status_container = QHBoxLayout()
        status_container.addWidget(self.status_dot)
        status_container.addWidget(self.status_indicator)
        status_container.setSpacing(5)
        
        self.chk_adblock = QCheckBox("Bloquear Ads")
        self.chk_adblock.setChecked(True)
        self.chk_adblock.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_adblock.setStyleSheet("""
            QCheckBox { color: #888; font-weight: 600; padding: 5px; }
            QCheckBox::indicator { width: 36px; height: 18px; border-radius: 9px; }
            QCheckBox::indicator:unchecked { background-color: #333; border: 2px solid #555; }
            QCheckBox::indicator:checked { background-color: #1DB954; border: 2px solid #1DB954; }
        """)
        
        # Checkbox de notificações (novo)
        self.chk_notifications = QCheckBox("Notificações")
        self.chk_notifications.setChecked(True)
        self.chk_notifications.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_notifications.setStyleSheet("""
            QCheckBox { color: #888; font-weight: 600; padding: 5px; }
            QCheckBox::indicator { width: 36px; height: 18px; border-radius: 9px; }
            QCheckBox::indicator:unchecked { background-color: #333; border: 2px solid #555; }
            QCheckBox::indicator:checked { background-color: #1DB954; border: 2px solid #1DB954; }
        """)
        
        # Loading indicator (novo)
        self.loading_indicator = QLabel("⏳")
        self.loading_indicator.setStyleSheet("color: #FFA726; font-size: 14px;")
        self.loading_indicator.hide()
        
        header.addWidget(lbl_logo)
        header.addSpacing(10)
        header.addLayout(status_container)
        header.addStretch()
        header.addWidget(self.loading_indicator)
        header.addWidget(self.chk_adblock)
        header.addWidget(self.chk_notifications)
        main_layout.addLayout(header)
        main_layout.addSpacing(20)

        self.lbl_image = RoundedImage(260)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(50)
        shadow.setColor(QColor(0,0,0, 180))
        shadow.setOffset(0, 15)
        self.lbl_image.setGraphicsEffect(shadow)
        
        center_layout = QHBoxLayout()
        center_layout.addStretch()
        center_layout.addWidget(self.lbl_image)
        center_layout.addStretch()
        main_layout.addLayout(center_layout)

        main_layout.addSpacing(25)
        
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        
        self.lbl_track = QLabel("Conectando API...")
        self.lbl_track.setStyleSheet("font-size: 19px; font-weight: bold; color: #FFF; margin-top: 5px;")
        self.lbl_track.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_track.setWordWrap(True)
        
        self.lbl_artist = QLabel("Aguarde...")
        self.lbl_artist.setStyleSheet("font-size: 15px; color: #B3B3B3; margin-bottom: 3px;")
        self.lbl_artist.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_program = QLabel("")
        self.lbl_program.setStyleSheet("font-size: 13px; color: #1DB954; font-weight: 600;")
        self.lbl_program.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_announcer = QLabel("")
        self.lbl_announcer.setStyleSheet("font-size: 12px; color: #777; font-style: italic;")
        self.lbl_announcer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.lbl_ad_timer = QLabel("")
        self.lbl_ad_timer.setStyleSheet("color: #FFB74D; font-size: 12px; font-weight: bold; margin-top: 5px;")
        self.lbl_ad_timer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_ad_timer.hide()

        self.lbl_badge = QLabel("INTERVALO")
        self.lbl_badge.setFixedSize(140, 24)
        self.lbl_badge.setStyleSheet("background-color: #9C27B0; color: white; border-radius: 12px; font-weight: bold; font-size: 11px;")
        self.lbl_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_badge.hide()
        
        badge_box = QHBoxLayout()
        badge_box.addStretch()
        badge_box.addWidget(self.lbl_badge)
        badge_box.addStretch()

        text_layout.addWidget(self.lbl_track)
        text_layout.addWidget(self.lbl_artist)
        text_layout.addWidget(self.lbl_program)
        text_layout.addWidget(self.lbl_announcer)
        text_layout.addWidget(self.lbl_ad_timer)
        text_layout.addSpacing(5)
        text_layout.addLayout(badge_box)
        main_layout.addLayout(text_layout)

        main_layout.addSpacing(20) 

        pop_container = QHBoxLayout()
        pop_container.setSpacing(10)
        lbl_pop_icon = QLabel("🔥")
        self.bar_pop = QProgressBar()
        self.bar_pop.setFixedHeight(4)
        self.bar_pop.setTextVisible(False)
        self.bar_pop.setRange(0, 100)
        self.bar_pop.setValue(0)
        self.bar_pop.setStyleSheet("QProgressBar { background-color: #333; border-radius: 2px; } QProgressBar::chunk { background-color: #1DB954; border-radius: 2px; }")
        self.lbl_pop_val = QLabel("0%")
        self.lbl_pop_val.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        self.lbl_pop_val.setFixedWidth(30)
        pop_container.addWidget(lbl_pop_icon)
        pop_container.addWidget(self.bar_pop)
        pop_container.addWidget(self.lbl_pop_val)
        main_layout.addLayout(pop_container)
        
        main_layout.addStretch() 

        dock_frame = QFrame()
        dock_frame.setFixedHeight(90)
        dock_frame.setStyleSheet("background-color: #252525; border-radius: 20px;")
        
        dock_layout = QHBoxLayout(dock_frame)
        dock_layout.setContentsMargins(15, 10, 15, 10)
        dock_layout.setSpacing(10) 

        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setFixedSize(30, 30)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setStyleSheet("QPushButton { color: #777; background: transparent; font-size: 18px; border:none; } QPushButton:hover { color: white; }")
        self.btn_refresh.clicked.connect(lambda: self.start_worker(False))

        self.btn_history = QPushButton("📜")
        self.btn_history.setFixedSize(30, 30)
        self.btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_history.setToolTip("Últimas Tocadas")
        self.btn_history.setStyleSheet("QPushButton { color: #777; background: transparent; font-size: 16px; border:none; } QPushButton:hover { color: white; }")
        self.btn_history.clicked.connect(self.show_history_menu)

        self.btn_stop = QPushButton("⏹")
        self.btn_stop.setFixedSize(45, 45)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setStyleSheet("QPushButton { color: #E91E63; background: transparent; font-size: 20px; border: 1px solid #444; border-radius: 22px; }")
        self.btn_stop.clicked.connect(self.stop_radio)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(60, 60)
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play.setStyleSheet("QPushButton { background-color: white; color: black; border-radius: 30px; font-size: 26px; padding-left: 4px; } QPushButton:hover { background-color: #ddd; }")
        self.btn_play.clicked.connect(self.toggle_play_pause)

        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setFixedSize(100, 20)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(80)
        self.slider_vol.setStyleSheet("""
            QSlider::groove:horizontal { height: 4px; background: #444; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #444; border-radius: 2px; }
            QSlider::add-page:horizontal { background: #1DB954; border-radius: 2px; }
            QSlider::handle:horizontal { background: #fff; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
        """)
        self.slider_vol.valueChanged.connect(self.change_volume)
        
        # Botão de mute (novo)
        self.btn_mute = QPushButton("🔊")
        self.btn_mute.setFixedSize(24, 24)
        self.btn_mute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mute.setStyleSheet("QPushButton { background: transparent; border: none; font-size: 14px; } QPushButton:hover { color: white; }")
        self.btn_mute.clicked.connect(self.toggle_mute)

        dock_layout.addWidget(self.btn_refresh)
        dock_layout.addWidget(self.btn_history)
        dock_layout.addStretch(1) 
        dock_layout.addWidget(self.btn_stop)
        dock_layout.addSpacing(15)
        dock_layout.addWidget(self.btn_play)
        dock_layout.addStretch(1)
        
        # Container para volume e mute
        volume_container = QVBoxLayout()
        volume_container.setSpacing(5)
        volume_container.addWidget(self.btn_mute)
        volume_container.addWidget(self.slider_vol)
        dock_layout.addLayout(volume_container)
        
        main_layout.addWidget(dock_frame)
        self.setLayout(main_layout)
        
        QTimer.singleShot(500, lambda: self.start_worker(False))

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        menu = QMenu()
        menu.setStyleSheet("QMenu { background-color: #333; color: white; }")
        menu.addAction("Abrir Player", self.show_window)
        menu.addSeparator()
        menu.addAction("Sair", self.quit_app)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_click)
        self.tray_icon.show()

    def show_window(self):
        self.show()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage("Player Rodando", "Minimizado na bandeja.", QSystemTrayIcon.MessageIcon.NoIcon, 1000)

    def quit_app(self):
        QApplication.instance().quit()

    def on_tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible(): self.hide()
            else: self.show_window()

    def show_history_menu(self):
        """Mostra diálogo de histórico aprimorado"""
        songs = self.db.get_last_songs(20)
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Histórico de Músicas")
        dialog.setFixedSize(500, 450)
        dialog.setStyleSheet("""
            QDialog { background-color: #121212; color: white; }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { background: #333; width: 8px; border-radius: 4px; }
            QScrollBar::handle:vertical { background: #555; border-radius: 4px; min-height: 30px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Header
        header = QLabel("🕒 Últimas Tocadas")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #1DB954; padding: 10px;")
        layout.addWidget(header)
        
        # Scrollable list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(8)
        
        if not songs:
            no_data = QLabel("Nenhum dado sincronizado ainda.")
            no_data.setStyleSheet("color: #888; font-style: italic; padding: 20px;")
            no_data.setAlignment(Qt.AlignmentFlag.AlignCenter)
            container_layout.addWidget(no_data)
        else:
            for title, artist, time_played in songs:
                song_widget = self.create_song_item(title, artist, time_played)
                container_layout.addWidget(song_widget)
        
        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)
        
        # Close button
        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(dialog.close)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton { 
                background-color: #1DB954; 
                color: white; 
                padding: 12px; 
                border-radius: 8px; 
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #1ed760; }
        """)
        layout.addWidget(btn_close)
        
        dialog.exec()
    
    def create_song_item(self, title, artist, time_played):
        """Cria um widget para exibir uma música no histórico"""
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame { 
                background-color: #252525; 
                border-radius: 10px; 
                border: 1px solid #333;
            }
            QFrame:hover {
                background-color: #2a2a2a;
                border: 1px solid #444;
            }
        """)
        widget.setFixedHeight(65)
        
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(15, 8, 15, 8)
        
        # Time badge
        time_lbl = QLabel(time_played)
        time_lbl.setStyleSheet("""
            color: #1DB954; 
            font-weight: bold; 
            font-size: 13px;
            background-color: rgba(29, 185, 84, 0.1);
            padding: 5px 10px;
            border-radius: 5px;
        """)
        time_lbl.setFixedWidth(65)
        
        # Song info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        title_lbl = QLabel(title[:35] + "..." if len(title) > 35 else title)
        title_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        
        artist_lbl = QLabel(artist[:40] + "..." if len(artist) > 40 else artist)
        artist_lbl.setStyleSheet("color: #B3B3B3; font-size: 12px;")
        
        info_layout.addWidget(title_lbl)
        info_layout.addWidget(artist_lbl)
        
        layout.addWidget(time_lbl)
        layout.addSpacing(10)
        layout.addLayout(info_layout)
        
        return widget
    
    def show_history_dialog(self):
        """Alias para show_history_menu (usado nos atalhos)"""
        self.show_history_menu()

    def toggle_play_pause(self):
        state = self.player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.user_stopped = True
            self.player.pause()
            self.overlay_player.pause()
            self.update_play_button_style("pause")
        else:
            self.user_stopped = False
            if self.is_ad_mode:
                if self.chk_adblock.isChecked():
                    self.audio_output.setVolume(0)
                    self.overlay_output.setVolume(OVERLAY_MAX_VOL)
                    self.overlay_player.play()
                self.player.play() 
            else:
                self.audio_output.setVolume(self.user_volume)
                self.player.play()
            self.update_play_button_style("play")

    def stop_radio(self):
        self.user_stopped = True
        self.player.stop()
        self.overlay_player.stop()
        self.update_play_button_style("stop")

    def update_play_button_style(self, status):
        if status == "play":
            self.btn_play.setText("II")
            self.btn_play.setStyleSheet("background-color: #1DB954; color: white; border-radius: 30px; font-size: 16px; font-weight: bold;")
        else:
            self.btn_play.setText("▶")
            self.btn_play.setStyleSheet("background-color: white; color: black; border-radius: 30px; font-size: 26px; padding-left: 4px;")

    def change_volume(self, val):
        self.user_volume = val / 100
        if self.user_volume > 0:
            self.btn_mute.setText("🔊")
        else:
            self.btn_mute.setText("🔇")
        if not self.is_ad_mode:
            self.audio_output.setVolume(self.user_volume)

    def toggle_mute(self):
        """Alterna entre mute/unmute"""
        if self.user_volume > 0:
            self.last_volume = self.user_volume
            self.user_volume = 0
            self.slider_vol.setValue(0)
            self.btn_mute.setText("🔇")
        else:
            self.user_volume = self.last_volume if hasattr(self, 'last_volume') else 0.8
            self.slider_vol.setValue(int(self.user_volume * 100))
            self.btn_mute.setText("🔊")
        
        if not self.is_ad_mode:
            self.audio_output.setVolume(self.user_volume)

    def enter_ad_mode(self):
        if self.is_ad_mode: return
        self.is_ad_mode = True
        
        self.ad_start_time = datetime.datetime.now()
        self.estimated_ad_duration = self.db.get_average_interval_duration()
        self.lbl_ad_timer.show()
        self.countdown_timer.start()
        
        if self.chk_adblock.isChecked():
            self.overlay_player.stop()
            self.overlay_player.setSource(QUrl(URL_LOFI_OVERLAY))
            self.overlay_output.setVolume(0) 
            
            if not self.user_stopped:
                self.overlay_player.play()
                self.fade_state = 'to_ad'
                self.fade_timer.start()
            
            self.lbl_badge.show()

    def exit_ad_mode(self):
        if not self.is_ad_mode: return
        self.is_ad_mode = False
        
        self.lbl_ad_timer.hide()
        self.countdown_timer.stop()
        self.lbl_badge.hide()

        if not self.user_stopped:
            if self.chk_adblock.isChecked():
                self.fade_state = 'to_radio'
                self.fade_timer.start()
            else:
                self.audio_output.setVolume(self.user_volume)

    def process_fade(self):
        curr_main = self.audio_output.volume()
        curr_over = self.overlay_output.volume()

        if self.fade_state == 'to_ad':
            new_main = max(0.0, curr_main - FADE_STEP)
            new_over = min(OVERLAY_MAX_VOL, curr_over + FADE_STEP)
            if new_main < 0.01: new_main = 0.0
            
            self.audio_output.setVolume(new_main)
            self.overlay_output.setVolume(new_over)
            
            if new_main == 0.0 and new_over >= OVERLAY_MAX_VOL:
                self.fade_timer.stop()
                
        elif self.fade_state == 'to_radio':
            new_main = min(self.user_volume, curr_main + FADE_STEP)
            new_over = max(0.0, curr_over - FADE_STEP)
            if new_over < 0.01: new_over = 0.0
            if abs(new_main - self.user_volume) < 0.01: new_main = self.user_volume

            self.audio_output.setVolume(new_main)
            self.overlay_output.setVolume(new_over)
            
            if new_over == 0.0:
                self.overlay_player.stop()
                if new_main >= self.user_volume:
                    self.fade_timer.stop()

    def update_ad_countdown(self):
        if not self.ad_start_time: return
        elapsed = (datetime.datetime.now() - self.ad_start_time).total_seconds()
        remaining = max(0, self.estimated_ad_duration - elapsed)
        mins, secs = divmod(int(remaining), 60)
        self.lbl_ad_timer.setText(f"Retorno estimado: {mins:02d}:{secs:02d}")
        if remaining <= 0: self.lbl_ad_timer.setText("Retornando...")

    def auto_fetch_data(self): 
        self.start_worker(True)

    def start_worker(self, is_auto):
        self.loading_indicator.show()
        self.worker = ApiWorker(self.current_song_name)
        self.worker.data_updated.connect(self.on_data)
        self.worker.error.connect(self.on_api_error)
        self.worker.start()

    def on_api_error(self, error_msg):
        """Callback para erros da API"""
        self.loading_indicator.hide()
        self.is_online = False
        self.status_dot.setStyleSheet("background-color: #FF5252; border-radius: 5px;")
        self.status_indicator.setText("Offline")
        print(f"API Error: {error_msg}")

    def update_cover_image(self, pixmap):
        self.lbl_image.set_image(pixmap)

    def on_data(self, data):
        self.loading_indicator.hide()
        status = data.get("status")

        if status == "ad_break":
            self.lbl_track.setText("Intervalo Comercial")
            self.lbl_artist.setText("Mundo Livre FM")
            self.lbl_program.setText("")
            self.lbl_announcer.setText("")
            self.lbl_image.set_image(None) # Limpa imagem no comercial
            self.bar_pop.setValue(0)
            self.lbl_pop_val.setText("0%")
            self.current_song_name = ""
            self.enter_ad_mode()
            return

        self.exit_ad_mode()

        musica = data.get("title", "Carregando...")
        artista = data.get("artist", "-")
        programa = data.get("program", "")
        locutor = data.get("announcer", "")
        pop = data.get("popularity", 0)

        if data.get("obj"):
            self.db.sync_song(data["obj"])

        # Update status indicator
        if not self.is_online:
            self.is_online = True
            self.status_dot.setStyleSheet("background-color: #1DB954; border-radius: 5px;")
            self.status_indicator.setText("Online")

        # Se a música mudou, busca a capa nova
        if musica != self.current_song_name:
            self.lbl_image.set_image(None) # Limpa a anterior enquanto busca
            if artista and musica and artista != "-":
                query = f"{artista} {musica}"
                self.image_worker = ImageWorker(query)
                self.image_worker.image_loaded.connect(self.update_cover_image)
                self.image_worker.start()

        self.current_song_name = musica
        self.lbl_track.setText(musica)
        self.lbl_artist.setText(artista)
        self.lbl_program.setText(programa)
        
        if locutor:
            self.lbl_announcer.setText(f"No ar: {locutor}")
        else:
            self.lbl_announcer.setText("")

        self.bar_pop.setValue(pop)
        self.lbl_pop_val.setText(f"{pop}%")

        # Notificações inteligentes - só notifica se estiver minimizado
        if musica != self.last_notified_song and self.chk_notifications.isChecked():
            if not self.isVisible():
                self.tray_icon.showMessage("Nova Música", f"{musica} - {artista}", 
                                           QSystemTrayIcon.MessageIcon.NoIcon, 3000)
            self.last_notified_song = musica

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False) 
    window = RadioApp()
    window.show()
    sys.exit(app.exec())
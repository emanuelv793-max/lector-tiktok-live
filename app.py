from __future__ import annotations

import asyncio
import ctypes
import json
import queue
import re
import sys
import threading
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image
import pythoncom
import win32com.client
import edge_tts
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, ConnectEvent, DisconnectEvent


APP_NAME = "Lector de comentarios TikTok LIVE"
CONFIG_PATH = Path.home() / ".tiktok_live_lector.json"
MAX_VISIBLE_COMMENTS = 250
VOICE_OPTIONS = {
    "Elvira · España (mujer)": "es-ES-ElviraNeural",
    "Álvaro · España (hombre)": "es-ES-AlvaroNeural",
    "Dalia · México (mujer)": "es-MX-DaliaNeural",
    "Jorge · México (hombre)": "es-MX-JorgeNeural",
}


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def clean_username(value: str) -> str:
    value = value.strip()
    match = re.search(r"tiktok\.com/@([A-Za-z0-9._-]+)", value, re.IGNORECASE)
    if match:
        return match.group(1)
    return value.lstrip("@").strip()


class SpeechWorker:
    def __init__(self, events: queue.Queue):
        self.events = events
        self.items: queue.Queue[tuple[str, int, str] | None] = queue.Queue(maxsize=100)
        self.enabled = threading.Event()
        self.enabled.set()
        self.thread = threading.Thread(target=self._run, daemon=True, name="lector-voz")
        self.thread.start()

    def say(self, text: str, rate: int, voice: str) -> None:
        if not self.enabled.is_set():
            return
        try:
            self.items.put_nowait((text, rate, voice))
        except queue.Full:
            self.events.put(("notice", "La cola de voz está llena; se omitió un comentario."))

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self.enabled.set()
        else:
            self.enabled.clear()
            while True:
                try:
                    self.items.get_nowait()
                except queue.Empty:
                    break

    def close(self) -> None:
        self.enabled.clear()
        try:
            self.items.put_nowait(None)
        except queue.Full:
            pass

    def _run(self) -> None:
        # SAPI is a COM component. Each background thread must initialize COM
        # before creating a Windows voice, otherwise some PCs stay silent.
        pythoncom.CoInitialize()
        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            voices = list(speaker.GetVoices())
            spanish = next((voice for voice in voices if "spanish" in voice.GetDescription().lower()), None)
            if spanish:
                speaker.Voice = spanish
            speaker.Volume = 100
        except Exception as exc:
            self.events.put(("speech_error", f"No se pudo iniciar la voz de Windows: {exc}"))
            pythoncom.CoUninitialize()
            return

        while True:
            item = self.items.get()
            if item is None:
                break
            if not self.enabled.is_set():
                continue
            text, rate, voice = item
            try:
                self._speak_neural(text, rate, voice)
            except Exception as exc:
                # Keep comments audible if the online neural service is
                # temporarily unavailable.
                self.events.put(("notice", f"Voz neuronal no disponible; usando la voz de Windows. ({exc})"))
                try:
                    speaker.Rate = max(-6, min(6, round((rate - 190) / 18)))
                    speaker.Speak(text)
                except Exception as fallback_exc:
                    self.events.put(("speech_error", f"Error al leer un comentario: {fallback_exc}"))
        del voices, spanish, speaker
        pythoncom.CoUninitialize()

    @staticmethod
    def _speak_neural(text: str, rate: int, voice: str) -> None:
        speed = max(-35, min(35, round((rate - 190) * 0.5)))
        rate_value = f"{speed:+d}%"
        temp = tempfile.NamedTemporaryFile(prefix="tiktok_voz_", suffix=".mp3", delete=False)
        audio_path = Path(temp.name)
        temp.close()
        alias = "tiktok_neural_voice"
        winmm = ctypes.windll.winmm

        def mci(command: str) -> None:
            result = winmm.mciSendStringW(command, None, 0, None)
            if result:
                error = ctypes.create_unicode_buffer(256)
                winmm.mciGetErrorStringW(result, error, len(error))
                raise RuntimeError(error.value or f"error de audio {result}")

        try:
            edge_tts.Communicate(text, voice, rate=rate_value).save_sync(str(audio_path))
            mci(f'open "{audio_path}" type mpegvideo alias {alias}')
            try:
                mci(f"play {alias} wait")
            finally:
                winmm.mciSendStringW(f"close {alias}", None, 0, None)
        finally:
            audio_path.unlink(missing_ok=True)


class LiveConnection:
    def __init__(self, events: queue.Queue):
        self.events = events
        self.loop: asyncio.AbstractEventLoop | None = None
        self.client: TikTokLiveClient | None = None
        self.thread: threading.Thread | None = None
        self.running = False
        self._lock = threading.Lock()

    def connect(self, username: str) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
        self.thread = threading.Thread(
            target=self._thread_main, args=(username,), daemon=True, name="tiktok-live"
        )
        self.thread.start()
        return True

    def disconnect(self) -> None:
        loop, client = self.loop, self.client
        if loop and client and loop.is_running():
            asyncio.run_coroutine_threadsafe(client.disconnect(close_client=True), loop)

    def _thread_main(self, username: str) -> None:
        try:
            asyncio.run(self._listen(username))
        except Exception as exc:
            name = type(exc).__name__
            if name == "UserOfflineError":
                message = f"@{username} no está en directo ahora mismo."
            elif name in {"UserNotFoundError", "LiveNotFound"}:
                message = f"No se encontró el usuario @{username}."
            else:
                message = f"No se pudo conectar: {exc or name}"
            self.events.put(("error", message))
        finally:
            with self._lock:
                self.running = False
            self.loop = None
            self.client = None
            self.events.put(("stopped", None))

    async def _listen(self, username: str) -> None:
        self.loop = asyncio.get_running_loop()
        client = TikTokLiveClient(unique_id=f"@{username}")
        self.client = client

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent) -> None:
            self.events.put(("connected", username))

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent) -> None:
            nickname = (event.user.nickname or event.user.unique_id or "Alguien").strip()
            comment = (event.comment or "").strip()
            if comment:
                self.events.put(("comment", (nickname, comment)))

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent) -> None:
            self.events.put(("notice", "El LIVE se ha desconectado."))

        task = await client.start(
            fetch_room_info=False,
            fetch_gift_info=False,
            fetch_live_check=True,
        )
        await task
        await client.close()


class App(ctk.CTk):
    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title(APP_NAME)
        self.geometry("900x700")
        self.minsize(760, 600)
        self.configure(fg_color="#090B10")
        try:
            self.iconbitmap(str(resource_path("assets/app-icon.ico")))
        except tk.TclError:
            pass

        self.events: queue.Queue = queue.Queue()
        self.connection = LiveConnection(self.events)
        self.speech = SpeechWorker(self.events)
        self.comment_count = 0

        saved = self._load_config()
        self.username = tk.StringVar(value=saved.get("username", ""))
        self.read_names = tk.BooleanVar(value=saved.get("read_names", True))
        self.voice_enabled = tk.BooleanVar(value=True)
        self.rate = tk.IntVar(value=int(saved.get("rate", 185)))
        saved_voice = saved.get("voice", next(iter(VOICE_OPTIONS)))
        self.voice = tk.StringVar(value=saved_voice if saved_voice in VOICE_OPTIONS else next(iter(VOICE_OPTIONS)))
        self.status = tk.StringVar(value="Desconectado")
        self.counter = tk.StringVar(value="0 comentarios")

        self._build_modern_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#101114")
        style.configure("Card.TFrame", background="#191b20")
        style.configure("TLabel", background="#101114", foreground="#f5f5f5", font=("Segoe UI", 10))
        style.configure("Muted.TLabel", foreground="#a8abb4")
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 20))
        style.configure("Card.TCheckbutton", background="#191b20", foreground="#f5f5f5")
        style.map("Card.TCheckbutton", background=[("active", "#191b20")])
        style.configure("Accent.TButton", background="#fe2c55", foreground="white", padding=(18, 9))
        style.map("Accent.TButton", background=[("active", "#db2147"), ("disabled", "#5f303b")])
        style.configure("Stop.TButton", background="#30333b", foreground="white", padding=(18, 9))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=24)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Lector de comentarios", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Conecta con un TikTok LIVE y escucha sus comentarios en tiempo real.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 18))

        connection_card = ttk.Frame(outer, style="Card.TFrame", padding=16)
        connection_card.pack(fill="x")
        ttk.Label(connection_card, text="Usuario del LIVE", background="#191b20").grid(row=0, column=0, sticky="w")
        self.user_entry = ttk.Entry(connection_card, textvariable=self.username, font=("Segoe UI", 11))
        self.user_entry.grid(row=1, column=0, sticky="ew", pady=(6, 0), padx=(0, 10))
        self.user_entry.bind("<Return>", lambda _event: self._connect())
        self.connect_button = ttk.Button(connection_card, text="Conectar", style="Accent.TButton", command=self._connect)
        self.connect_button.grid(row=1, column=1, padx=(0, 8))
        self.stop_button = ttk.Button(connection_card, text="Parar", style="Stop.TButton", command=self._disconnect, state="disabled")
        self.stop_button.grid(row=1, column=2)
        connection_card.columnconfigure(0, weight=1)

        options = ttk.Frame(outer, style="Card.TFrame", padding=14)
        options.pack(fill="x", pady=12)
        ttk.Checkbutton(
            options, text="Leer nombres", variable=self.read_names, style="Card.TCheckbutton"
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            options,
            text="Voz activada",
            variable=self.voice_enabled,
            command=self._toggle_voice,
            style="Card.TCheckbutton",
        ).grid(row=0, column=1, sticky="w", padx=24)
        ttk.Button(options, text="Probar voz", command=self._test_voice).grid(row=0, column=2, sticky="e")
        ttk.Label(options, text="Voz natural", background="#191b20").grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.voice_combo = ttk.Combobox(
            options, textvariable=self.voice, values=list(VOICE_OPTIONS), state="readonly", width=28
        )
        self.voice_combo.grid(row=1, column=1, sticky="ew", padx=(0, 18), pady=(12, 0))
        speed_frame = ttk.Frame(options, style="Card.TFrame")
        speed_frame.grid(row=1, column=2, sticky="ew", pady=(12, 0))
        ttk.Label(speed_frame, text="Velocidad", background="#191b20").pack(side="left")
        ttk.Scale(speed_frame, from_=120, to=260, variable=self.rate, orient="horizontal").pack(
            side="left", fill="x", expand=True, padx=(10, 0)
        )
        options.columnconfigure(1, weight=1)
        options.columnconfigure(2, weight=1)

        status_row = ttk.Frame(outer)
        status_row.pack(fill="x", pady=(2, 7))
        ttk.Label(status_row, textvariable=self.status).pack(side="left")
        ttk.Label(status_row, textvariable=self.counter, style="Muted.TLabel").pack(side="right")

        log_frame = ttk.Frame(outer, style="Card.TFrame")
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_frame,
            wrap="word",
            state="disabled",
            bg="#191b20",
            fg="#f3f3f3",
            insertbackground="white",
            selectbackground="#3c4250",
            relief="flat",
            padx=14,
            pady=12,
            font=("Segoe UI", 10),
        )
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.log.tag_configure("name", foreground="#25f4ee", font=("Segoe UI Semibold", 10))
        self.log.tag_configure("notice", foreground="#a8abb4", font=("Segoe UI", 9, "italic"))

    def _build_modern_ui(self) -> None:
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=30, pady=26)

        header = ctk.CTkFrame(outer, fg_color="transparent")
        header.pack(fill="x", pady=(0, 22))
        self.logo_image = ctk.CTkImage(Image.open(resource_path("assets/app-icon.png")), size=(62, 62))
        ctk.CTkLabel(header, text="", image=self.logo_image).pack(side="left", padx=(0, 15))
        heading = ctk.CTkFrame(header, fg_color="transparent")
        heading.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            heading, text="Lector de comentarios", text_color="#F7F8FC",
            font=ctk.CTkFont(family="Segoe UI Variable Display", size=27, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            heading, text="Tu chat de TikTok LIVE, ahora con una voz más humana.",
            text_color="#8E95A5", font=ctk.CTkFont(family="Segoe UI", size=13),
        ).pack(anchor="w", pady=(3, 0))
        self.status_badge = ctk.CTkLabel(
            header, textvariable=self.status, fg_color="#171A22", text_color="#C2C7D2",
            corner_radius=14, height=30, padx=14, font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.status_badge.pack(side="right")

        connection_card = ctk.CTkFrame(
            outer, fg_color="#12151D", corner_radius=20, border_width=1, border_color="#242936"
        )
        connection_card.pack(fill="x")
        ctk.CTkLabel(
            connection_card, text="Conectar al LIVE", text_color="#F5F6FA",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=20, pady=(16, 10))
        self.user_entry = ctk.CTkEntry(
            connection_card, textvariable=self.username, placeholder_text="@usuario de TikTok",
            height=44, corner_radius=12, border_width=1, border_color="#303645",
            fg_color="#0C0F15", font=ctk.CTkFont(size=14),
        )
        self.user_entry.grid(row=1, column=0, sticky="ew", padx=(20, 12), pady=(0, 18))
        self.user_entry.bind("<Return>", lambda _event: self._connect())
        self.connect_button = ctk.CTkButton(
            connection_card, text="Conectar", command=self._connect, height=44, width=120,
            corner_radius=12, fg_color="#FF3B67", hover_color="#E72E58",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.connect_button.grid(row=1, column=1, padx=(0, 10), pady=(0, 18))
        self.stop_button = ctk.CTkButton(
            connection_card, text="Parar", command=self._disconnect, state="disabled",
            height=44, width=95, corner_radius=12, fg_color="#262B37", hover_color="#343A49",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.stop_button.grid(row=1, column=2, padx=(0, 20), pady=(0, 18))
        connection_card.columnconfigure(0, weight=1)

        options = ctk.CTkFrame(
            outer, fg_color="#12151D", corner_radius=20, border_width=1, border_color="#242936"
        )
        options.pack(fill="x", pady=14)
        switch_args = {
            "progress_color": "#20D6D0", "button_color": "#FFFFFF",
            "font": ctk.CTkFont(size=13),
        }
        ctk.CTkSwitch(options, text="Leer nombres", variable=self.read_names, **switch_args).grid(
            row=0, column=0, sticky="w", padx=20, pady=(17, 14)
        )
        ctk.CTkSwitch(
            options, text="Voz activada", variable=self.voice_enabled,
            command=self._toggle_voice, **switch_args,
        ).grid(row=0, column=1, sticky="w", padx=20, pady=(17, 14))
        ctk.CTkButton(
            options, text="▶  Probar voz", command=self._test_voice, height=36,
            corner_radius=10, fg_color="#232936", hover_color="#303747",
        ).grid(row=0, column=2, sticky="e", padx=20, pady=(14, 11))
        ctk.CTkLabel(
            options, text="Voz natural", text_color="#8E95A5", font=ctk.CTkFont(size=12)
        ).grid(row=1, column=0, sticky="w", padx=20)
        self.voice_combo = ctk.CTkOptionMenu(
            options, variable=self.voice, values=list(VOICE_OPTIONS), height=38, corner_radius=10,
            fg_color="#202532", button_color="#2B3140", button_hover_color="#373E50",
            dropdown_fg_color="#171B24", font=ctk.CTkFont(size=12),
        )
        self.voice_combo.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(20, 12), pady=(6, 18))
        speed_frame = ctk.CTkFrame(options, fg_color="transparent")
        speed_frame.grid(row=1, column=2, rowspan=2, sticky="ew", padx=20, pady=(0, 13))
        ctk.CTkLabel(
            speed_frame, text="Velocidad", text_color="#8E95A5", font=ctk.CTkFont(size=12)
        ).pack(anchor="w")
        ctk.CTkSlider(
            speed_frame, from_=120, to=260, variable=self.rate, progress_color="#20D6D0",
            button_color="#FFFFFF", button_hover_color="#D8FBFA",
        ).pack(fill="x", pady=(8, 0))
        for column in range(3):
            options.columnconfigure(column, weight=1)

        log_frame = ctk.CTkFrame(
            outer, fg_color="#12151D", corner_radius=20, border_width=1, border_color="#242936"
        )
        log_frame.pack(fill="both", expand=True)
        log_header = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header.pack(fill="x", padx=20, pady=(15, 8))
        ctk.CTkLabel(
            log_header, text="Comentarios en directo", text_color="#F5F6FA",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            log_header, textvariable=self.counter, text_color="#8E95A5", font=ctk.CTkFont(size=12),
        ).pack(side="right")
        self.log = ctk.CTkTextbox(
            log_frame, wrap="word", fg_color="#0C0F15", text_color="#E8EAF0",
            corner_radius=13, border_width=0, font=ctk.CTkFont(family="Segoe UI", size=13),
            padx=10, pady=8,
        )
        self.log.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.log.tag_config("name", foreground="#42E6DF")
        self.log.tag_config("notice", foreground="#7F8797")
        self.log.configure(state="disabled")

    def _connect(self) -> None:
        username = clean_username(self.username.get())
        if not username:
            messagebox.showinfo(APP_NAME, "Escribe el @usuario que está haciendo el LIVE.")
            self.user_entry.focus_set()
            return
        self.username.set(username)
        self._save_config()
        self.status.set(f"Conectando con @{username}…")
        self.connect_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.user_entry.configure(state="disabled")
        self._add_notice(f"Buscando el LIVE de @{username}…")
        if not self.connection.connect(username):
            self._add_notice("Ya hay una conexión activa.")

    def _disconnect(self) -> None:
        self.status.set("Desconectando…")
        self.stop_button.configure(state="disabled")
        self.connection.disconnect()

    def _toggle_voice(self) -> None:
        self.speech.set_enabled(self.voice_enabled.get())

    def _test_voice(self) -> None:
        self.voice_enabled.set(True)
        self.speech.set_enabled(True)
        self.speech.say(
            "Prueba de voz natural. El lector funciona correctamente.",
            int(self.rate.get()),
            VOICE_OPTIONS[self.voice.get()],
        )
        self._add_notice("Prueba de voz neuronal enviada. Puede tardar un instante.")

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "connected":
                    self.status.set(f"● Conectado a @{payload}")
                    self._add_notice("Conectado. Esperando comentarios…")
                elif kind == "comment":
                    nickname, comment = payload
                    self._add_comment(nickname, comment)
                    spoken = f"{nickname} dice: {comment}" if self.read_names.get() else comment
                    self.speech.say(spoken[:450], int(self.rate.get()), VOICE_OPTIONS[self.voice.get()])
                elif kind == "notice":
                    self._add_notice(payload)
                elif kind == "error":
                    self._add_notice(payload)
                    messagebox.showerror(APP_NAME, payload)
                elif kind == "speech_error":
                    self.voice_enabled.set(False)
                    self._add_notice(payload)
                elif kind == "stopped":
                    self.status.set("Desconectado")
                    self.connect_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.user_entry.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _add_comment(self, nickname: str, comment: str) -> None:
        self.comment_count += 1
        self.counter.set(f"{self.comment_count} comentario" + ("" if self.comment_count == 1 else "s"))
        self.log.configure(state="normal")
        self.log.insert("end", f"{nickname}: ", "name")
        self.log.insert("end", f"{comment}\n")
        self._trim_log()
        self.log.see("end")
        self.log.configure(state="disabled")

    def _add_notice(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{text}\n", "notice")
        self._trim_log()
        self.log.see("end")
        self.log.configure(state="disabled")

    def _trim_log(self) -> None:
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > MAX_VISIBLE_COMMENTS:
            self.log.delete("1.0", f"{lines - MAX_VISIBLE_COMMENTS}.0")

    def _load_config(self) -> dict:
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_config(self) -> None:
        try:
            CONFIG_PATH.write_text(
                json.dumps(
                    {
                        "username": clean_username(self.username.get()),
                        "read_names": self.read_names.get(),
                        "rate": int(self.rate.get()),
                        "voice": self.voice.get(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _on_close(self) -> None:
        self._save_config()
        self.connection.disconnect()
        self.speech.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()

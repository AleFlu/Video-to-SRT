#!/usr/bin/env python3
"""
app_mac.py — GUI macOS per Video → SRT
Interfaccia grafica con tkinter, ottimizzata per qualità italiano.
"""

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path

script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from engine import run_pipeline, check_ffmpeg, MODELS, DEFAULT_MODEL

# ============================================================
# UI Constants
# ============================================================
APP_TITLE = "Video → SRT"
WINDOW_WIDTH = 600
WINDOW_HEIGHT = 520
BG_COLOR = "#1e1e2e"
FG_COLOR = "#cdd6f4"
ACCENT_COLOR = "#89b4fa"
SUCCESS_COLOR = "#a6e3a1"
ERROR_COLOR = "#f38ba8"
SURFACE_COLOR = "#313244"
MUTED_COLOR = "#6c7086"

SUPPORTED_FORMATS = (
    ("File multimediali", "*.mp4 *.mkv *.avi *.mov *.mp3 *.wav *.m4a *.flac *.webm *.ogg"),
    ("Video", "*.mp4 *.mkv *.avi *.mov *.webm"),
    ("Audio", "*.mp3 *.wav *.m4a *.flac *.ogg"),
    ("Tutti i file", "*.*"),
)

# Dropdown options: label → model key
MODEL_OPTIONS = {v["label"]: k for k, v in MODELS.items()}
DEFAULT_LABEL = MODELS[DEFAULT_MODEL]["label"]


class VideoToSrtApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(False, False)
        self.root.configure(bg=BG_COLOR)

        self.input_path: str | None = None
        self.is_running = False

        self._setup_styles()
        self._build_ui()
        self.root.after(500, self._check_deps)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("App.TFrame", background=BG_COLOR)
        style.configure("App.TLabel", background=BG_COLOR, foreground=FG_COLOR,
                        font=("SF Pro Display", 13))
        style.configure("Title.TLabel", background=BG_COLOR, foreground=FG_COLOR,
                        font=("SF Pro Display", 22, "bold"))
        style.configure("Subtitle.TLabel", background=BG_COLOR, foreground=MUTED_COLOR,
                        font=("SF Pro Display", 11))
        style.configure("Status.TLabel", background=BG_COLOR, foreground=ACCENT_COLOR,
                        font=("SF Pro Display", 11))
        style.configure("Success.TLabel", background=BG_COLOR, foreground=SUCCESS_COLOR,
                        font=("SF Pro Display", 12, "bold"))
        style.configure("Error.TLabel", background=BG_COLOR, foreground=ERROR_COLOR,
                        font=("SF Pro Display", 11))
        style.configure("File.TLabel", background=SURFACE_COLOR, foreground=FG_COLOR,
                        font=("SF Mono", 11), padding=(12, 8))
        style.configure("App.Horizontal.TProgressbar",
                        background=ACCENT_COLOR, troughcolor=SURFACE_COLOR,
                        borderwidth=0, lightcolor=ACCENT_COLOR, darkcolor=ACCENT_COLOR)

    def _build_ui(self):
        main = ttk.Frame(self.root, style="App.TFrame", padding=30)
        main.pack(fill="both", expand=True)

        # Header
        ttk.Label(main, text="🎬 Video → SRT", style="Title.TLabel").pack(anchor="w")
        ttk.Label(main, text="Trascrizione automatica in italiano · faster-whisper + large-v3",
                  style="Subtitle.TLabel").pack(anchor="w", pady=(2, 20))

        # File selection
        file_frame = ttk.Frame(main, style="App.TFrame")
        file_frame.pack(fill="x", pady=(0, 12))
        ttk.Label(file_frame, text="File di input", style="App.TLabel").pack(anchor="w")

        btn_frame = ttk.Frame(file_frame, style="App.TFrame")
        btn_frame.pack(fill="x", pady=(6, 0))

        self.file_label = ttk.Label(btn_frame, text="Nessun file selezionato",
                                    style="File.TLabel", width=42)
        self.file_label.pack(side="left", fill="x", expand=True)

        self.browse_btn = tk.Button(
            btn_frame, text="Scegli file", command=self._browse_file,
            bg=ACCENT_COLOR, fg=BG_COLOR, font=("SF Pro Display", 12, "bold"),
            relief="flat", padx=16, pady=6, cursor="hand2",
        )
        self.browse_btn.pack(side="right", padx=(10, 0))

        # Model selection
        model_frame = ttk.Frame(main, style="App.TFrame")
        model_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(model_frame, text="Modello (large-v3 = massima qualità italiano)",
                  style="App.TLabel").pack(anchor="w")

        self.model_var = tk.StringVar(value=DEFAULT_LABEL)
        self.model_menu = ttk.Combobox(
            model_frame, textvariable=self.model_var,
            values=list(MODEL_OPTIONS.keys()), state="readonly",
            font=("SF Pro Display", 11), width=42,
        )
        self.model_menu.pack(anchor="w", pady=(6, 0))

        # Options row
        opts_frame = ttk.Frame(main, style="App.TFrame")
        opts_frame.pack(fill="x", pady=(0, 12))

        self.vad_var = tk.BooleanVar(value=True)
        vad_check = tk.Checkbutton(
            opts_frame, text="VAD (filtra silenzi, riduce errori)",
            variable=self.vad_var, bg=BG_COLOR, fg=FG_COLOR,
            selectcolor=SURFACE_COLOR, activebackground=BG_COLOR,
            activeforeground=FG_COLOR, font=("SF Pro Display", 11),
        )
        vad_check.pack(side="left")

        # Start button
        self.start_btn = tk.Button(
            main, text="▶ Avvia trascrizione", command=self._start,
            bg=ACCENT_COLOR, fg=BG_COLOR, font=("SF Pro Display", 14, "bold"),
            relief="flat", padx=20, pady=10, cursor="hand2", state="disabled",
        )
        self.start_btn.pack(fill="x", pady=(8, 16))

        # Progress
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            main, variable=self.progress_var, maximum=1.0,
            style="App.Horizontal.TProgressbar",
        )
        self.progress_bar.pack(fill="x", pady=(0, 8))

        # Status
        self.status_label = ttk.Label(main, text="", style="Status.TLabel")
        self.status_label.pack(anchor="w")

        # Output (hidden until done)
        self.output_frame = ttk.Frame(main, style="App.TFrame")
        self.output_label = ttk.Label(self.output_frame, text="", style="Success.TLabel")
        self.output_label.pack(anchor="w")

        self.open_btn = tk.Button(
            self.output_frame, text="📂 Apri nel Finder",
            command=self._open_output, bg=SUCCESS_COLOR, fg=BG_COLOR,
            font=("SF Pro Display", 11, "bold"), relief="flat",
            padx=14, pady=6, cursor="hand2",
        )
        self.open_btn.pack(anchor="w", pady=(6, 0))

    def _check_deps(self):
        if not check_ffmpeg():
            self._set_status("FFmpeg non trovato. Installa con: brew install ffmpeg", error=True)

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Seleziona un file video o audio",
            filetypes=SUPPORTED_FORMATS,
        )
        if path:
            self.input_path = path
            name = Path(path).name
            display = name if len(name) <= 45 else name[:42] + "..."
            self.file_label.configure(text=display)
            self.start_btn.configure(state="normal")
            self.output_frame.pack_forget()
            self._set_status("")

    def _set_status(self, msg: str, error: bool = False):
        def _update():
            style = "Error.TLabel" if error else "Status.TLabel"
            self.status_label.configure(text=msg, style=style)
        self.root.after(0, _update)

    def _set_progress(self, value: float):
        self.root.after(0, lambda: self.progress_var.set(value))

    def _start(self):
        if self.is_running or not self.input_path:
            return

        self.is_running = True
        self.start_btn.configure(state="disabled", text="⏳ Trascrizione in corso...")
        self.browse_btn.configure(state="disabled")
        self.output_frame.pack_forget()
        self.progress_var.set(0)

        model_label = self.model_var.get()
        model_size = MODEL_OPTIONS.get(model_label, DEFAULT_MODEL)
        vad = self.vad_var.get()

        thread = threading.Thread(
            target=self._run_transcription,
            args=(self.input_path, model_size, vad),
            daemon=True,
        )
        thread.start()

    def _run_transcription(self, input_path: str, model_size: str, vad: bool):
        try:
            output_path = run_pipeline(
                input_path=input_path,
                model_size=model_size,
                beam_size=5,
                vad_filter=vad,
                on_status=self._set_status,
                on_progress=self._set_progress,
            )
            self.root.after(0, lambda: self._on_success(output_path))
        except Exception as e:
            self.root.after(0, lambda: self._on_error(str(e)))

    def _on_success(self, output_path: str):
        self.is_running = False
        self.start_btn.configure(state="normal", text="▶ Avvia trascrizione")
        self.browse_btn.configure(state="normal")
        self.progress_var.set(1.0)
        self._output_path = output_path
        name = Path(output_path).name
        self.output_label.configure(text=f"✅ Generato: {name}")
        self.output_frame.pack(fill="x", pady=(8, 0))
        self._set_status("Completato!")

    def _on_error(self, error_msg: str):
        self.is_running = False
        self.start_btn.configure(state="normal", text="▶ Avvia trascrizione")
        self.browse_btn.configure(state="normal")
        self._set_status(f"Errore: {error_msg}", error=True)

    def _open_output(self):
        if hasattr(self, "_output_path") and os.path.exists(self._output_path):
            subprocess.run(["open", "-R", self._output_path])

    def run(self):
        self.root.mainloop()


def main():
    app = VideoToSrtApp()
    app.run()


if __name__ == "__main__":
    main()

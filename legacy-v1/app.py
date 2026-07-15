#!/usr/bin/env python3
"""
app.py — Video → SRT
Splash istantaneo → caricamento progressivo → app principale
"""

# ============================================================
# SOLO tkinter a livello di modulo — tutto il resto è lazy.
# Questo garantisce che lo splash appaia PRIMA di qualsiasi
# import pesante (customtkinter, faster-whisper, onnxruntime).
# ============================================================
import sys
import tkinter as tk
from pathlib import Path

script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))


# ============================================================
# Splash Screen — usa SOLO tkinter puro
# ============================================================
class SplashScreen:
    BG = "#0f0f23"
    FG = "#cdd6f4"
    ACCENT = "#4f8cff"
    MUTED = "#6c7086"

    STEPS = [
        "Inizializzazione...",
        "Caricamento interfaccia...",
        "Verifica FFmpeg...",
        "Caricamento motore IA...",
        "Caricamento modello...",
        "Pronto!",
    ]

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.configure(bg=self.BG)
        self.root.attributes("-alpha", 0.95)

        w, h = 420, 200
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        tk.Label(self.root, text="🎬  Video → SRT",
                 font=("Helvetica Neue", 22, "bold"),
                 bg=self.BG, fg=self.FG).pack(pady=(30, 4))

        tk.Label(self.root, text="Trascrizione automatica in italiano",
                 font=("Helvetica Neue", 11),
                 bg=self.BG, fg=self.MUTED).pack()

        bar_frame = tk.Frame(self.root, bg=self.BG)
        bar_frame.pack(fill="x", padx=40, pady=(24, 6))

        self._canvas = tk.Canvas(bar_frame, height=4, bg="#1e1e3a", highlightthickness=0)
        self._canvas.pack(fill="x")
        self._bar = self._canvas.create_rectangle(0, 0, 0, 4, fill=self.ACCENT, width=0)

        self._label = tk.Label(self.root, text=self.STEPS[0],
                                font=("Helvetica Neue", 10),
                                bg=self.BG, fg=self.MUTED)
        self._label.pack()

        # Forza il rendering immediato
        self.root.update_idletasks()
        self.root.update()

    def set_step(self, index, text=None):
        def _do():
            msg = text or (self.STEPS[index] if index < len(self.STEPS) else "Pronto!")
            self._label.configure(text=msg)
            pct = (index + 1) / len(self.STEPS)
            bw = self._canvas.winfo_width()
            self._canvas.coords(self._bar, 0, 0, int(bw * pct), 4)
        self.root.after(0, _do)

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass


# ============================================================
# Caricamento progressivo + lancio app
# ============================================================
def launch():
    import multiprocessing
    multiprocessing.freeze_support()

    splash = SplashScreen()
    state = {"ok": False, "ffmpeg": False, "model": False}

    def _load():
        import threading  # noqa — lazy

        # Step 1: customtkinter
        splash.set_step(1)
        import customtkinter  # noqa

        # Step 2: FFmpeg
        splash.set_step(2)
        from engine import check_ffmpeg
        state["ffmpeg"] = check_ffmpeg()

        # Step 3: Engine
        splash.set_step(3)
        from engine import preload_model, DEFAULT_MODEL

        # Step 4: Modello
        splash.set_step(4)
        state["model"] = preload_model(
            model_size=DEFAULT_MODEL,
            on_status=lambda msg: splash.set_step(4, msg),
        )

        # Step 5
        splash.set_step(5)
        state["ok"] = True

    def _poll():
        if not state["ok"]:
            splash.root.after(100, _poll)
            return
        splash.close()
        _start_main_app(state["ffmpeg"], state["model"])

    import threading
    threading.Thread(target=_load, daemon=True).start()
    splash.root.after(200, _poll)
    splash.root.mainloop()


# ============================================================
# App principale — tutti gli import pesanti sono già in memoria
# ============================================================
def _start_main_app(ffmpeg_ok, model_ok):
    import os
    import platform
    import subprocess
    import threading
    from tkinter import filedialog

    import customtkinter as ctk

    # Drag & Drop
    dnd_available = False
    tkdnd = None
    try:
        import tkinterdnd2
        tkdnd = tkinterdnd2
        dnd_available = True
    except ImportError:
        pass

    from engine import MODELS, DEFAULT_MODEL

    # ---- Costanti ----
    BG = "#1a1a2e"
    SURFACE = "#16213e"
    CARD = "#1e2a47"
    ACCENT = "#4f8cff"
    ACCENT_H = "#3a6fd8"
    OK = "#2ecc71"
    ERR = "#e74c3c"
    MUTED = "#7f8c9b"
    TEXT = "#e0e6ed"
    BORDER = "#2a3a5c"

    EXTS = {".mp4",".mkv",".avi",".mov",".webm",".mp3",".wav",".m4a",".flac",".ogg",".aac",".wma"}
    FTYPES = (
        ("File multimediali", "*.mp4 *.mkv *.avi *.mov *.mp3 *.wav *.m4a *.flac *.webm *.ogg"),
        ("Video", "*.mp4 *.mkv *.avi *.mov *.webm"),
        ("Audio", "*.mp3 *.wav *.m4a *.flac *.ogg"),
        ("Tutti i file", "*.*"),
    )

    M_LABELS = [v["label"] for v in MODELS.values()]
    M_KEYS = list(MODELS.keys())
    M_DEFAULT = MODELS[DEFAULT_MODEL]["label"]

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    def fmt_size(p):
        try:
            s = os.path.getsize(p)
            if s < 1024:      return f"{s} B"
            if s < 1024**2:   return f"{s/1024:.1f} KB"
            if s < 1024**3:   return f"{s/1024**2:.1f} MB"
            return f"{s/1024**3:.2f} GB"
        except OSError:
            return ""

    def open_folder(fp):
        p = platform.system()
        try:
            if p == "Darwin":    subprocess.run(["open", "-R", fp])
            elif p == "Windows": subprocess.run(["explorer", "/select,", fp])
            else:                subprocess.run(["xdg-open", str(Path(fp).parent)])
        except Exception:
            pass

    # ---- Finestra ----
    if dnd_available:
        root = tkdnd.TkinterDnD.Tk()
    else:
        root = tk.Tk()

    root.title("Video → SRT")
    root.geometry("620x640")
    root.resizable(False, False)
    root.configure(bg=BG)

    # Stato
    app = {
        "input": None, "output": None,
        "running": False, "cancel": None,
    }

    # ---- Topbar ----
    topbar = ctk.CTkFrame(root, height=56, corner_radius=0, fg_color=SURFACE, border_width=0)
    topbar.pack(fill="x", side="top")
    topbar.pack_propagate(False)

    ctk.CTkLabel(topbar, text="🎬  Video → SRT",
                 font=ctk.CTkFont(size=18, weight="bold"),
                 text_color=TEXT).pack(side="left", padx=20)

    ffmpeg_badge = ctk.CTkLabel(topbar, font=ctk.CTkFont(size=11),
                                 corner_radius=8, fg_color=CARD,
                                 text="  ✅ FFmpeg  " if ffmpeg_ok else "  ❌ FFmpeg  ",
                                 text_color=OK if ffmpeg_ok else ERR)
    ffmpeg_badge.pack(side="right", padx=(6, 20))

    model_badge = ctk.CTkLabel(topbar, font=ctk.CTkFont(size=11),
                                corner_radius=8, fg_color=CARD,
                                text="  ✅ Modello pronto  " if model_ok else "  ⚠️ Modello  ",
                                text_color=OK if model_ok else ERR)
    model_badge.pack(side="right", padx=6)

    # ---- Content ----
    scroll = ctk.CTkScrollableFrame(root, fg_color=BG, corner_radius=0)
    scroll.pack(fill="both", expand=True)
    px = 20

    # Drop zone
    drop_card = ctk.CTkFrame(scroll, corner_radius=14, fg_color=CARD,
                              border_color=BORDER, border_width=2, height=120)
    drop_card.pack(fill="x", padx=px, pady=(16, 8))
    drop_card.pack_propagate(False)

    drop_inner = ctk.CTkFrame(drop_card, fg_color="transparent")
    drop_inner.place(relx=0.5, rely=0.5, anchor="center")

    drop_icon = ctk.CTkLabel(drop_inner, text="📁", font=ctk.CTkFont(size=28))
    drop_icon.pack()
    drop_text = ctk.CTkLabel(drop_inner,
                              text="Trascina un file qui o clicca per sceglierlo" if dnd_available
                              else "Clicca per scegliere un file",
                              font=ctk.CTkFont(size=13), text_color=MUTED)
    drop_text.pack(pady=(4, 0))
    drop_detail = ctk.CTkLabel(drop_inner, text="MP4, MOV, MKV, AVI, MP3, WAV, FLAC...",
                                font=ctk.CTkFont(size=10), text_color="#4a5568")
    drop_detail.pack(pady=(2, 0))

    # Settings card
    scard = ctk.CTkFrame(scroll, corner_radius=14, fg_color=CARD)
    scard.pack(fill="x", padx=px, pady=(8, 0))

    ctk.CTkLabel(scard, text="⚙️  Impostazioni", font=ctk.CTkFont(size=14, weight="bold"),
                 text_color=TEXT, anchor="w").pack(fill="x", padx=16, pady=(14, 8))
    ctk.CTkFrame(scard, height=1, fg_color=BORDER).pack(fill="x", padx=16)

    mrow = ctk.CTkFrame(scard, fg_color="transparent")
    mrow.pack(fill="x", padx=16, pady=(10, 6))
    ctk.CTkLabel(mrow, text="Modello", font=ctk.CTkFont(size=13), text_color=TEXT).pack(side="left")
    model_var = ctk.StringVar(value=M_DEFAULT)
    ctk.CTkOptionMenu(mrow, variable=model_var, values=M_LABELS, font=ctk.CTkFont(size=11),
                       width=280, fg_color=SURFACE, button_color=ACCENT,
                       button_hover_color=ACCENT_H).pack(side="right")

    ctk.CTkFrame(scard, height=1, fg_color=BORDER).pack(fill="x", padx=16)

    vrow = ctk.CTkFrame(scard, fg_color="transparent")
    vrow.pack(fill="x", padx=16, pady=(10, 14))
    vleft = ctk.CTkFrame(vrow, fg_color="transparent")
    vleft.pack(side="left")
    ctk.CTkLabel(vleft, text="Filtro VAD", font=ctk.CTkFont(size=13), text_color=TEXT).pack(anchor="w")
    ctk.CTkLabel(vleft, text="Filtra silenzi, riduce errori",
                 font=ctk.CTkFont(size=10), text_color=MUTED).pack(anchor="w")
    vad_var = ctk.BooleanVar(value=True)
    ctk.CTkSwitch(vrow, variable=vad_var, text="", fg_color=SURFACE,
                   progress_color=ACCENT, button_color=TEXT).pack(side="right")

    ctk.CTkFrame(scard, height=1, fg_color=BORDER).pack(fill="x", padx=16)

    # Alta precisione (WhisperX)
    hrow = ctk.CTkFrame(scard, fg_color="transparent")
    hrow.pack(fill="x", padx=16, pady=(10, 14))
    hleft = ctk.CTkFrame(hrow, fg_color="transparent")
    hleft.pack(side="left")

    htitle_row = ctk.CTkFrame(hleft, fg_color="transparent")
    htitle_row.pack(anchor="w")
    ctk.CTkLabel(htitle_row, text="Alta precisione", font=ctk.CTkFont(size=13),
                 text_color=TEXT).pack(side="left")

    info_label = ctk.CTkLabel(htitle_row, text=" ⓘ", font=ctk.CTkFont(size=12),
                               text_color=MUTED, cursor="hand2")
    info_label.pack(side="left", padx=(4, 0))

    _tooltip = {"win": None}
    def _show_tip(e):
        x = info_label.winfo_rootx() + 20
        y = info_label.winfo_rooty() - 40
        tw = tk.Toplevel(root)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.configure(bg="#2a2a3e")
        tk.Label(tw, text="Usa WhisperX con allineamento fonetico\n"
                          "wav2vec2 per timestamp precisi (±20ms).\n"
                          "Più lento, ma molto più accurato.\n"
                          "Richiede: pip install whisperx",
                 bg="#2a2a3e", fg="#cdd6f4", font=("Helvetica Neue", 10),
                 justify="left", padx=8, pady=6).pack()
        _tooltip["win"] = tw
    def _hide_tip(e):
        if _tooltip["win"]:
            _tooltip["win"].destroy()
            _tooltip["win"] = None
    info_label.bind("<Enter>", _show_tip)
    info_label.bind("<Leave>", _hide_tip)

    ctk.CTkLabel(hleft, text="WhisperX · Allineamento fonetico",
                 font=ctk.CTkFont(size=10), text_color=MUTED).pack(anchor="w")
    accuracy_var = ctk.BooleanVar(value=False)
    ctk.CTkSwitch(hrow, variable=accuracy_var, text="", fg_color=SURFACE,
                   progress_color="#8b5cf6", button_color=TEXT).pack(side="right")

    # Buttons
    btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
    btn_row.pack(fill="x", padx=px, pady=(16, 8))

    start_btn = ctk.CTkButton(btn_row, text="▶   Avvia trascrizione",
                               font=ctk.CTkFont(size=15, weight="bold"), height=48,
                               fg_color=ACCENT, hover_color=ACCENT_H,
                               corner_radius=12, state="disabled")
    start_btn.pack(side="left", fill="x", expand=True)

    cancel_btn = ctk.CTkButton(btn_row, text="■  Stop", width=90,
                                font=ctk.CTkFont(size=14, weight="bold"), height=48,
                                fg_color=ERR, hover_color="#c0392b", corner_radius=12)

    progress = ctk.CTkProgressBar(scroll, height=6, corner_radius=3,
                                   fg_color=SURFACE, progress_color=ACCENT)
    progress.pack(fill="x", padx=px + 4, pady=(4, 2))
    progress.set(0)

    status_lbl = ctk.CTkLabel(scroll, text="", font=ctk.CTkFont(size=12),
                               text_color=ACCENT, anchor="w")
    status_lbl.pack(fill="x", padx=px + 4, pady=(2, 8))

    # Output card
    out_card = ctk.CTkFrame(scroll, corner_radius=14, fg_color=CARD,
                             border_color=OK, border_width=2)
    out_inner = ctk.CTkFrame(out_card, fg_color="transparent")
    out_inner.pack(fill="x", padx=16, pady=14)
    out_label = ctk.CTkLabel(out_inner, text="", font=ctk.CTkFont(size=14, weight="bold"),
                              text_color=OK, anchor="w")
    out_label.pack(fill="x")
    out_detail = ctk.CTkLabel(out_inner, text="", font=ctk.CTkFont(size=11),
                               text_color=MUTED, anchor="w")
    out_detail.pack(fill="x", pady=(2, 8))
    ctk.CTkButton(out_inner, text="📂  Apri nella cartella",
                   font=ctk.CTkFont(size=12, weight="bold"), height=36,
                   fg_color=OK, hover_color="#27ae60", text_color=BG,
                   corner_radius=10,
                   command=lambda: open_folder(app["output"]) if app["output"] and os.path.exists(app["output"]) else None
                   ).pack(anchor="w")

    if not ffmpeg_ok:
        set_status("FFmpeg non trovato. Installalo: brew install ffmpeg", True)

    # ---- Funzioni ----
    def set_status(msg, error=False):
        root.after(0, lambda: status_lbl.configure(
            text=msg, text_color=ERR if error else ACCENT))

    def set_progress(v):
        root.after(0, lambda: progress.set(v))

    def hide_output():
        out_card.pack_forget()

    def set_file(path):
        app["input"] = path
        name = Path(path).name
        drop_card.configure(border_color=ACCENT)
        drop_icon.configure(text="🎬")
        drop_text.configure(text=name if len(name) <= 50 else name[:47] + "...", text_color=TEXT)
        drop_detail.configure(text=f"{fmt_size(path)}  ·  {Path(path).suffix.upper()}")
        start_btn.configure(state="normal")
        hide_output()
        set_status("")

    def browse():
        if app["running"]:
            return
        p = filedialog.askopenfilename(title="Seleziona un file video o audio", filetypes=FTYPES)
        if p:
            set_file(p)

    def reset_ui():
        app["running"] = False
        start_btn.configure(state="normal", text="▶   Avvia trascrizione")
        cancel_btn.pack_forget()
        cancel_btn.configure(state="normal", text="■  Stop")

    def on_start():
        if app["running"] or not app["input"]:
            return
        app["running"] = True
        app["cancel"] = threading.Event()
        start_btn.configure(state="disabled", text="⏳  Trascrizione in corso...")
        cancel_btn.pack(side="right", padx=(8, 0))
        hide_output()
        progress.set(0)

        label = model_var.get()
        idx = M_LABELS.index(label) if label in M_LABELS else M_KEYS.index(M_DEFAULT)
        ms = M_KEYS[idx]
        vad = vad_var.get()
        ha = accuracy_var.get()

        threading.Thread(target=run_transcription, args=(app["input"], ms, vad, ha), daemon=True).start()

    def on_cancel():
        if app["cancel"]:
            app["cancel"].set()
        cancel_btn.configure(state="disabled", text="⏳ ...")
        app["_tick"] = 0
        animate_cancel()

    def animate_cancel():
        if not app["running"]:
            return
        dots = "." * ((app.get("_tick", 0) % 3) + 1)
        status_lbl.configure(text=f"Annullamento in corso{dots}", text_color=MUTED)
        app["_tick"] = app.get("_tick", 0) + 1
        root.after(500, animate_cancel)

    def run_transcription(input_path, model_size, vad, high_accuracy):
        try:
            from engine import run_pipeline, TranscriptionCancelled
            outp = run_pipeline(
                input_path=input_path, model_size=model_size, beam_size=5,
                vad_filter=vad, high_accuracy=high_accuracy,
                cancel_event=app["cancel"],
                on_status=set_status, on_progress=set_progress)
            root.after(0, lambda o=outp: on_success(o))
        except TranscriptionCancelled:
            root.after(0, on_cancelled)
        except Exception as e:
            import traceback
            em = str(e) if str(e) and str(e) != "None" else type(e).__name__
            print(f"\n{'='*50}\nERRORE:\n{'='*50}\n{traceback.format_exc()}{'='*50}\n")
            root.after(0, lambda m=em: on_error(m))

    def on_success(outp):
        reset_ui()
        app["output"] = outp
        progress.set(1.0)
        out_label.configure(text=f"✅  {Path(outp).name}")
        out_detail.configure(text=f"{fmt_size(outp)}  ·  Salvato nella stessa cartella del video")
        out_card.pack(fill="x", padx=20, pady=(8, 16))
        set_status("Completato!")

    def on_cancelled():
        reset_ui()
        progress.set(0)
        set_status("Trascrizione annullata")

    def on_error(msg):
        reset_ui()
        set_status(f"Errore: {msg}", True)

    # ---- Drag & Drop ----
    def on_drag_enter(e):
        drop_card.configure(border_color=ACCENT)
        drop_text.configure(text="Rilascia per caricare", text_color=ACCENT)

    def on_drag_leave(e):
        if not app["input"]:
            drop_card.configure(border_color=BORDER)
            drop_text.configure(text="Trascina un file qui o clicca per sceglierlo", text_color=MUTED)

    def on_drop(e):
        raw = e.data.strip()
        if raw.startswith("{") and raw.endswith("}"): raw = raw[1:-1]
        if "\n" in raw: raw = raw.split("\n")[0].strip()
        if " " in raw and not os.path.exists(raw): raw = raw.split()[0]
        ext = Path(raw).suffix.lower()
        if ext not in EXTS:
            set_status(f"Formato non supportato: {ext}", True)
            drop_card.configure(border_color=ERR)
            root.after(2000, lambda: drop_card.configure(border_color=BORDER))
            return
        if os.path.isfile(raw):
            set_file(raw)

    # Bind
    for w in [drop_card, drop_inner, drop_icon, drop_text, drop_detail]:
        w.bind("<Button-1>", lambda e: browse())

    if dnd_available:
        drop_card.drop_target_register(tkdnd.DND_FILES)
        drop_card.dnd_bind("<<DropEnter>>", on_drag_enter)
        drop_card.dnd_bind("<<DropLeave>>", on_drag_leave)
        drop_card.dnd_bind("<<Drop>>", on_drop)

    start_btn.configure(command=on_start)
    cancel_btn.configure(command=on_cancel)

    # ---- Cleanup alla chiusura ----
    def on_close():
        """Chiusura pulita: cancella la trascrizione, libera modello, chiudi."""
        # 1. Segnala al thread di trascrizione di fermarsi
        if app["cancel"]:
            app["cancel"].set()

        # 2. Libera il modello dalla cache per restituire la RAM
        try:
            from engine import _release_cached_model
            _release_cached_model()
        except Exception:
            pass

        # 3. Chiudi la finestra
        try:
            root.quit()
            root.destroy()
        except Exception:
            pass

    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()


# ============================================================
# Entry point
# ============================================================
if __name__ == "__main__":
    launch()
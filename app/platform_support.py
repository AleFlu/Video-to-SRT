"""
platform_support.py — Unico punto di accesso alle differenze tra sistemi operativi.

Nessun altro modulo dell'app deve usare ``sys.platform`` / ``platform.system()``:
font, cartelle di cache, scorciatoie, apertura nel file manager e logging
passano da qui. Questo modulo non importa ``core``, ``ui`` né ``engine``;
PySide6 viene importato solo dentro le funzioni che ne hanno bisogno.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

IS_MAC: bool = sys.platform == "darwin"
IS_WIN: bool = sys.platform.startswith("win")
IS_LINUX: bool = not IS_MAC and not IS_WIN

_APP_DIR_NAME = "VideoSRT"


# ── CPU e strumenti ──────────────────────────────────────────────────────────

def _sysctl_int(name: str) -> int:
    """Legge un intero da ``sysctl -n`` (solo macOS). 0 se non disponibile."""
    try:
        out = subprocess.run(
            ["sysctl", "-n", name], capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            return int(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0


@lru_cache(maxsize=1)
def cpu_threads() -> int:
    """Numero di thread ottimale per l'inferenza (mai inferiore a 1)."""
    count = 0
    if IS_MAC:
        count = _sysctl_int("hw.perflevel0.logicalcpu") or _sysctl_int("hw.physicalcpu")
    if count < 1:
        count = max(4, (os.cpu_count() or 8) // 2)
    return max(1, count)


@lru_cache(maxsize=1)
def total_ram_bytes() -> int:
    """RAM fisica totale in byte (0 se non si riesce a leggerla)."""
    try:
        if IS_MAC:
            return _sysctl_int("hw.memsize")
        if IS_WIN:
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = _MemStatus()
            status.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
            return 0
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (OSError, ValueError, AttributeError):
        return 0


def ffmpeg_executable_name() -> str:
    """Nome dell'eseguibile ffmpeg per il sistema corrente."""
    return "ffmpeg.exe" if IS_WIN else "ffmpeg"


def subprocess_kwargs() -> Dict[str, object]:
    """Argomenti extra per ``subprocess.run`` (nasconde la console su Windows)."""
    if IS_WIN:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


# ── Cartelle ─────────────────────────────────────────────────────────────────

def app_cache_dir() -> Path:
    """Cartella di cache dell'app (creata se manca), con fallback su tempdir."""
    home = Path.home()
    if IS_MAC:
        base = home / "Library" / "Caches"
    elif IS_WIN:
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        base = Path(xdg) if xdg else home / ".cache"

    path = base / _APP_DIR_NAME
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError as exc:
        logger.warning("Cartella cache %s non disponibile (%s): uso tempdir", path, exc)
    fallback = Path(tempfile.gettempdir()) / f"{_APP_DIR_NAME}_cache"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def legacy_cache_dirs() -> List[Path]:
    """Vecchie cartelle di cache da scandire per gli autosave (solo macOS)."""
    if IS_MAC:
        return [Path.home() / ".cache" / _APP_DIR_NAME]
    return []


def temp_dir() -> Path:
    """Cartella temporanea del sistema."""
    return Path(tempfile.gettempdir())


# ── Formati media ────────────────────────────────────────────────────────────

def native_media_exts() -> frozenset:
    """Estensioni che il backend multimediale della piattaforma riproduce nativamente."""
    exts = {".mp4", ".mov", ".m4a", ".m4v", ".mp3", ".wav", ".aac"}
    if IS_MAC:
        exts.add(".aiff")
    elif IS_WIN:
        exts.add(".wma")
    return frozenset(exts)


# ── Font ─────────────────────────────────────────────────────────────────────
# IBM Plex (inclusi in assets/fonts, caricati da ui/fonts.py) vengono per primi;
# i font di sistema restano come ripiego se il caricamento fallisce.

UI_FONT = "IBM Plex Sans"
MONO_FONT = "IBM Plex Mono"


def _system_ui_stack() -> str:
    if IS_MAC:
        return '".AppleSystemUIFont", "Helvetica Neue"'
    if IS_WIN:
        return '"Segoe UI", "Arial"'
    return '"Inter", "Noto Sans", "DejaVu Sans"'


def _system_mono_stack() -> str:
    if IS_MAC:
        return '"Menlo", "Monaco"'
    if IS_WIN:
        return '"Cascadia Mono", "Consolas"'
    return '"DejaVu Sans Mono", "Liberation Mono"'


def font_stack_ui() -> str:
    """Stringa CSS ``font-family`` per l'interfaccia."""
    return f'"{UI_FONT}", {_system_ui_stack()}'


def font_stack_mono() -> str:
    """Stringa CSS ``font-family`` per il testo a spaziatura fissa."""
    return f'"{MONO_FONT}", {_system_mono_stack()}'


def ui_font_family() -> str:
    """Primo nome di famiglia per ``QFont`` dell'interfaccia."""
    return UI_FONT


def mono_font_family() -> str:
    """Famiglia monospace per ``QFont``."""
    return MONO_FONT


# ── Scorciatoie ──────────────────────────────────────────────────────────────

_MAC_GLYPHS = {"ctrl": "⌘", "meta": "⌃", "shift": "⇧", "alt": "⌥", "return": "↵",
               "enter": "↵"}


def shortcut_label(seq: str) -> str:
    """Etichetta leggibile di una scorciatoia ("Ctrl+Shift+T" -> "⌘⇧T" su macOS)."""
    if not IS_MAC:
        return seq
    parts = seq.split("+")
    return "".join(_MAC_GLYPHS.get(p.strip().lower(), p.strip()) for p in parts)


def fullscreen_shortcut() -> str:
    """Scorciatoia per lo schermo intero."""
    return "Meta+Ctrl+F" if IS_MAC else "F11"


def project_tab_shortcuts() -> tuple:
    """
    (successivo, precedente): sequenze per scorrere i tab dei progetti.
    ⌘⇧] / ⌘⇧[ non si digitano su tutte le tastiere (su quella italiana ] e [ richiedono
    ⌥): si aggiunge Ctrl+Tab / Ctrl+Maiusc+Tab, che su macOS è ⌃Tab (⌘Tab è del sistema).
    """
    ctrl = "Meta" if IS_MAC else "Ctrl"
    return (["Ctrl+Shift+]", f"{ctrl}+Tab"],
            ["Ctrl+Shift+[", f"{ctrl}+Shift+Backtab", f"{ctrl}+Shift+Tab"])


# ── File manager e icone ─────────────────────────────────────────────────────

def reveal_in_file_manager(path: str) -> bool:
    """Mostra il file nel file manager di sistema. False se l'operazione fallisce."""
    try:
        if IS_MAC:
            cmd = ["open", "-R", path]
        elif IS_WIN:
            # Qt restituisce percorsi con "/": explorer /select vuole i backslash
            cmd = ["explorer", f"/select,{os.path.normpath(path)}"]
        else:
            cmd = ["xdg-open", str(Path(path).parent)]
        # explorer restituisce spesso codice 1 anche con successo: non lo si controlla.
        subprocess.run(cmd, **subprocess_kwargs())
        return True
    except Exception as exc:  # noqa: BLE001 — qualsiasi errore = operazione fallita
        logger.warning("Impossibile aprire il file manager per %s: %s", path, exc)
        return False


def app_icon_path(assets_dir: Path) -> Optional[Path]:
    """Percorso dell'icona dell'app per la piattaforma, o None se assente."""
    names = ["app.icns"] if IS_MAC else ["app.ico"] if IS_WIN else []
    for name in names + ["app_512.png"]:
        candidate = Path(assets_dir) / name
        if candidate.exists():
            return candidate
    return None


def set_dock_icon(pixmap) -> None:
    """Imposta l'icona del Dock (solo macOS, via pyobjc); altrove non fa nulla."""
    if not IS_MAC:
        return
    try:
        from AppKit import NSApplication, NSData, NSImage
        from PySide6.QtCore import QBuffer, QIODevice

        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        pixmap.save(buf, "PNG")
        buf.close()
        png_bytes = bytes(buf.data())
        ns_img = NSImage.alloc().initWithData_(
            NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
        )
        NSApplication.sharedApplication().setApplicationIconImage_(ns_img)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Icona Dock non impostata: %s", exc)


# ── Logging ──────────────────────────────────────────────────────────────────

def configure_logging() -> Optional[Path]:
    """Configura il root logger (console + file a rotazione). Ritorna il path del log."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not any(getattr(h, "_videosrt", False) for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        stream._videosrt = True  # type: ignore[attr-defined]
        root.addHandler(stream)

    log_path: Optional[Path] = None
    try:
        log_path = app_cache_dir() / "videosrt.log"
        if not any(isinstance(h, logging.handlers.RotatingFileHandler)
                   and getattr(h, "_videosrt", False) for h in root.handlers):
            fh = logging.handlers.RotatingFileHandler(
                log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8",
            )
            fh.setFormatter(fmt)
            fh._videosrt = True  # type: ignore[attr-defined]
            root.addHandler(fh)
    except OSError as exc:
        logger.warning("File di log non disponibile: %s", exc)
        log_path = None
    return log_path

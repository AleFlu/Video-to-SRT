"""
whisper_models.py — Catalogo dei modelli Whisper, modello consigliato per il computer,
modelli già scaricati e download con avanzamento.

I modelli stanno nella cache di Hugging Face (la stessa che usa faster-whisper):
``$HF_HUB_CACHE``, altrimenti ``$HF_HOME/hub``, altrimenti ``~/.cache/huggingface/hub``.
Nessun import pesante a livello di modulo: faster-whisper serve solo per scaricare.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

GIB = 1024 ** 3

# label/ram/quality: mostrati nella Home. download_gb: dimensione del download.
MODELS: Dict[str, Dict] = {
    "tiny":           {"label": "tiny — Test rapidi",               "ram": "~1 GB",
                       "quality": "★☆☆☆☆", "download_gb": 0.08},
    "base":           {"label": "base — Qualità base",              "ram": "~1 GB",
                       "quality": "★★☆☆☆", "download_gb": 0.15},
    "small":          {"label": "small — Discreta per italiano",    "ram": "~2 GB",
                       "quality": "★★★☆☆", "download_gb": 0.48},
    "medium":         {"label": "medium — Buona qualità",           "ram": "~5 GB",
                       "quality": "★★★★☆", "download_gb": 1.5},
    "large-v3":       {"label": "large-v3 — Massima qualità",       "ram": "~6 GB",
                       "quality": "★★★★★", "download_gb": 3.1},
    "large-v3-turbo": {"label": "large-v3-turbo — Ottima e veloce", "ram": "~4 GB",
                       "quality": "★★★★½", "download_gb": 1.6},
}
DEFAULT_MODEL = "large-v3"

# Repository Hugging Face (come faster_whisper.utils._MODELS)
_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}


class DownloadCancelled(Exception):
    """Download interrotto dall'utente (riprende da dove era arrivato la volta dopo)."""


# ── Consiglio in base all'hardware ───────────────────────────────────────────

def recommend_model(ram_bytes: int, has_cuda: bool) -> str:
    """Modello consigliato: il migliore che il computer usa senza fatica.

    GPU NVIDIA o almeno 16 GB di RAM → large-v3; 8 GB → large-v3-turbo (quasi la stessa
    qualità, metà memoria, molto più veloce); 4 GB → small; meno → base. RAM sconosciuta
    (0) → large-v3-turbo. Le soglie tollerano la RAM "vista" un po' sotto quella dichiarata.
    """
    if has_cuda:
        return "large-v3"
    if ram_bytes <= 0:
        return "large-v3-turbo"
    gib = ram_bytes / GIB
    if gib >= 15:
        return "large-v3"
    if gib >= 7:
        return "large-v3-turbo"
    if gib >= 3.5:
        return "small"
    return "base"


# ── Cache di Hugging Face ────────────────────────────────────────────────────

def model_repo(key: str) -> str:
    return _REPOS[key]


def hub_cache_dir() -> Path:
    env = os.environ.get("HF_HUB_CACHE")
    if env:
        return Path(env)
    home = os.environ.get("HF_HOME")
    if home:
        return Path(home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _repo_dir(key: str) -> Path:
    return hub_cache_dir() / ("models--" + model_repo(key).replace("/", "--"))


def is_downloaded(key: str) -> bool:
    """True se nella cache c'è una copia completa del modello (pesi e configurazione)."""
    if key not in _REPOS:
        return False
    snapshots = _repo_dir(key) / "snapshots"
    try:
        return any((s / "model.bin").is_file() and (s / "config.json").is_file()
                   for s in snapshots.iterdir())
    except OSError:
        return False


def _downloaded_bytes(key: str) -> int:
    """Byte già arrivati (file completi e parziali), per l'avanzamento."""
    blobs = _repo_dir(key) / "blobs"
    total = 0
    try:
        for f in blobs.iterdir():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


# ── Download ─────────────────────────────────────────────────────────────────

def _fetch(key: str) -> None:
    """Scarica il modello nella cache (riprende un download interrotto)."""
    from faster_whisper.utils import download_model
    download_model(key)


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f}".replace(".", ",")


def download(key: str, *, on_status: Optional[Callable[[str], None]] = None,
             on_progress: Optional[Callable[[float], None]] = None,
             cancel_event: Optional[threading.Event] = None, poll_s: float = 0.5) -> None:
    """Scarica ``key`` riportando stato e avanzamento (0–1, mai all'indietro).

    ``cancel_event`` interrompe l'attesa con DownloadCancelled: i file parziali restano
    nella cache e il download successivo riparte da lì. Errori di rete → RuntimeError
    con un messaggio in italiano.
    """
    expected = max(1, int(MODELS[key]["download_gb"] * 1e9))
    errors: list = []

    def run():
        try:
            _fetch(key)
        except BaseException as e:  # noqa: BLE001 — riportato al chiamante
            errors.append(e)

    worker = threading.Thread(target=run, name=f"download-{key}", daemon=True)
    worker.start()
    last = 0.0
    shown = ""
    logger.info("Download del modello %s (~%s GB)", key, _gb(expected))
    while True:
        worker.join(poll_s)
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled(key)
        if not worker.is_alive():
            break
        got = _downloaded_bytes(key)
        frac = min(0.99, got / expected)
        if frac > last:
            last = frac
            if on_progress:
                on_progress(frac)
        text = f"Download del modello {key}: {_gb(got)} di ~{_gb(expected)} GB"
        if on_status and text != shown:      # una riga ogni 0,1 GB, non a ogni controllo
            shown = text
            on_status(text)
    if errors:
        logger.warning("Download del modello %s fallito: %s", key, errors[0])
        raise RuntimeError(
            f"Download del modello {key} non riuscito ({errors[0]}). Controlla la "
            "connessione e riprova: il download riparte da dove si è fermato.") from errors[0]
    if on_progress:
        on_progress(1.0)
    if on_status:
        on_status(f"Modello {key} scaricato")

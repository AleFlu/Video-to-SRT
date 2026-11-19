"""
prefs.py — Lettura robusta delle preferenze (QSettings).

Con un solo elemento, alcuni backend di QSettings (es. file INI, plist) restituiscono
una lista salvata come semplice `str`: `list(valore)` la spezzerebbe in caratteri.

Qui vive anche la persistenza dell'ultima configurazione di trascrizione usata
(JSON di core.transcription_config): un valore illeggibile non blocca mai l'avvio.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from core.transcription_config import TranscriptionConfig

log = logging.getLogger(__name__)


def read_list(settings, key: str) -> list:
    """Legge una lista da `settings` (QSettings o compatibile), sempre come `list`."""
    val = settings.value(key, [])
    if val is None or val == "":
        return []
    if isinstance(val, (list, tuple)):
        return list(val)
    return [val]


RECENT_KEY = "recent_files"
MAX_RECENT = 10


def add_recent(settings, path: str, key: str = RECENT_KEY, limit: int = MAX_RECENT) -> list:
    """Mette `path` in cima alla lista dei recenti (unica per menu File e Home)."""
    recent = [str(p) for p in read_list(settings, key) if str(p) != path]
    recent.insert(0, path)
    recent = recent[:limit]
    settings.setValue(key, recent)
    return recent


CONFIG_KEY = "transcription_config"            # JSON dell'ultima configurazione usata
CONFIG_NAME_KEY = "transcription_config_name"  # origine: nome del file importato o ""
CONFIG_DIR_KEY = "transcription_config_dir"    # ultima cartella di import/export


def read_config(settings, default_model: Optional[str] = None
                ) -> Tuple[TranscriptionConfig, str]:
    """Ultima configurazione usata e nome della sua origine.

    Se manca (primo avvio) o non è più valida (file delle preferenze modificato,
    versione più recente) si usano i predefiniti, senza eccezioni, col modello
    ``default_model`` se indicato (il consigliato per il computer).
    """
    default = (TranscriptionConfig(model_size=default_model) if default_model
               else TranscriptionConfig())
    raw = settings.value(CONFIG_KEY, "")
    if not raw or not isinstance(raw, str):
        return default, ""
    try:
        config = TranscriptionConfig.from_json(raw)
    except ValueError as e:
        log.warning("Configurazione salvata non valida, uso i predefiniti: %s", e)
        return default, ""
    name = settings.value(CONFIG_NAME_KEY, "")
    return config, name if isinstance(name, str) else ""


def write_config(settings, config: TranscriptionConfig, name: str = "") -> None:
    """Ricorda ``config`` come ultima configurazione usata."""
    settings.setValue(CONFIG_KEY, config.to_json())
    settings.setValue(CONFIG_NAME_KEY, name)

"""
prefs.py — Lettura robusta delle preferenze (QSettings).

Con un solo elemento, alcuni backend di QSettings (es. file INI, plist) restituiscono
una lista salvata come semplice `str`: `list(valore)` la spezzerebbe in caratteri.
"""

from __future__ import annotations


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

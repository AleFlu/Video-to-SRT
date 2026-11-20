"""
timing_edit.py — Regole per cambiare i tempi di un sottotitolo a mano.

Usate dal trascinamento dei blocchi sulla forma d'onda e dai tasti I/O (inizio/fine al
cursore di riproduzione). Funzioni pure, indipendenti dall'unità (secondi o millisecondi:
basta usare la stessa per tempi, durata minima e durata del media).

Regole:
- un sottotitolo non scavalca i vicini: l'inizio non va prima della fine del precedente,
  la fine non va oltre l'inizio del successivo (al massimo si toccano). Se è già sovrapposto
  a un vicino non lo si costringe a spostarsi, solo a non sovrapporsi di più;
- trascinando un bordo la durata non scende sotto ``min_duration`` (se era già più corto,
  quel bordo può solo allargarlo);
- inizio ≥ 0 e fine ≤ durata del media, se nota.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence, Tuple

Times = Sequence[Tuple[float, float]]

MIN_DURATION_S = 0.2


def neighbour_limits(times: Times, row: int,
                     media_end: Optional[float] = None) -> Tuple[float, float]:
    """(limite basso, limite alto) per i tempi della riga ``row``."""
    start, end = times[row]
    lo, hi = 0.0, math.inf
    for r, (s, e) in enumerate(times):
        if r == row:
            continue
        if s <= start:
            lo = max(lo, min(e, start))
        else:
            hi = min(hi, max(s, end))
    if media_end is not None and media_end > 0:
        hi = min(hi, max(media_end, end))
    return lo, hi


def trim_start(times: Times, row: int, value: float, min_duration: float,
               media_end: Optional[float] = None) -> float:
    """Nuovo inizio della riga, portato dentro i limiti."""
    start, end = times[row]
    lo, _ = neighbour_limits(times, row, media_end)
    upper = max(end - min_duration, start)
    return max(lo, min(value, upper))


def trim_end(times: Times, row: int, value: float, min_duration: float,
             media_end: Optional[float] = None) -> float:
    """Nuova fine della riga, portata dentro i limiti."""
    start, end = times[row]
    _, hi = neighbour_limits(times, row, media_end)
    lower = min(start + min_duration, end)
    return min(hi, max(value, lower))


def move(times: Times, row: int, delta: float,
         media_end: Optional[float] = None) -> Tuple[float, float]:
    """Sposta inizio e fine insieme di ``delta`` (limitato dai vicini)."""
    start, end = times[row]
    lo, hi = neighbour_limits(times, row, media_end)
    delta = max(lo - start, min(delta, hi - end))
    return start + delta, end + delta


def mark_target(times: Times, selected: int, pos: float, edge: str) -> int:
    """Riga a cui il tasto I (``edge`` "start") o O ("end") assegna il tempo ``pos``.

    Il sottotitolo selezionato, se il nuovo tempo per lui ha senso (inizio prima della
    fine, fine dopo l'inizio). Altrimenti, per l'inizio, il primo sottotitolo che non è
    ancora finito (il cursore è in una pausa prima di lui); per la fine, l'ultimo già
    cominciato. -1 se non ce n'è.
    """
    if 0 <= selected < len(times):
        s, e = times[selected]
        if (edge == "start" and pos < e) or (edge == "end" and pos > s):
            return selected
    order = sorted(range(len(times)), key=lambda r: times[r])
    if edge == "start":
        return next((r for r in order if times[r][1] > pos), -1)
    return next((r for r in reversed(order) if times[r][0] < pos), -1)

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

Oltre i vicini (trascinando un blocco più in là dello spazio che ha attorno):
- lasciato sopra un altro sottotitolo, i due si scambiano il testo (``row_at``): i tempi
  restano dove sono, legati al parlato;
- lasciato in una pausa, ci entra con la sua durata se c'è posto (``free_slot``);
- trascinando nella corsia vuota, o con un doppio clic, nasce un sottotitolo nuovo dentro
  la pausa dove si è cominciato (``new_block``, ``default_block``).
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


def _limit(media_end: Optional[float]) -> float:
    return media_end if media_end is not None and media_end > 0 else math.inf


def row_at(times: Times, at: float, exclude: int = -1) -> int:
    """Riga del sottotitolo che contiene il tempo ``at`` (escluso ``exclude``), o -1."""
    for r, (s, e) in enumerate(times):
        if r != exclude and s <= at <= e:
            return r
    return -1


def gap_at(times: Times, at: float, exclude: int = -1,
           media_end: Optional[float] = None) -> Optional[Tuple[float, float]]:
    """Pausa (inizio, fine) tra i sottotitoli che contiene ``at``; None se ``at`` cade
    dentro un sottotitolo (escluso ``exclude``) o fuori dal media."""
    hi = _limit(media_end)
    if at < 0 or at > hi:
        return None
    lo = 0.0
    for r, (s, e) in enumerate(times):
        if r == exclude:
            continue
        if s < at < e:
            return None
        if e <= at:
            lo = max(lo, e)
        elif s >= at:
            hi = min(hi, s)
    return lo, hi


def free_slot(times: Times, row: int, at: float,
              media_end: Optional[float] = None) -> Optional[Tuple[float, float]]:
    """Posto per la riga ``row``, con la sua durata, nella pausa che contiene ``at``:
    centrato su ``at`` e spinto dentro la pausa. None se non c'è pausa o è troppo corta."""
    start, end = times[row]
    duration = end - start
    gap = gap_at(times, at, row, media_end)
    if gap is None or gap[1] - gap[0] < duration - 1e-9:
        return None
    lo, hi = gap
    new_start = min(max(at - duration / 2, lo), hi - duration)
    return new_start, new_start + duration


def new_block(times: Times, press: float, at: float, min_duration: float,
              media_end: Optional[float] = None) -> Optional[Tuple[float, float]]:
    """Sottotitolo nuovo disegnato da ``press`` ad ``at``, tenuto dentro la pausa dove si
    è premuto e lungo almeno ``min_duration``. None se lì non c'è spazio."""
    gap = gap_at(times, press, -1, media_end)
    if gap is None or gap[1] - gap[0] < min_duration:
        return None
    lo, hi = gap
    start, end = sorted((press, at))
    start, end = max(lo, start), min(hi, end)
    if end - start < min_duration:
        if at >= press:
            end = min(hi, start + min_duration)
            start = end - min_duration
        else:
            start = max(lo, end - min_duration)
            end = start + min_duration
    return start, end


def default_block(times: Times, at: float, duration: float, min_duration: float,
                  media_end: Optional[float] = None) -> Optional[Tuple[float, float]]:
    """Sottotitolo nuovo che comincia in ``at`` (doppio clic), lungo ``duration`` o quanto
    resta della pausa. None se lì non c'è spazio."""
    gap = gap_at(times, at, -1, media_end)
    if gap is None or gap[1] - gap[0] < min_duration:
        return None
    lo, hi = gap
    length = min(duration, hi - lo)
    start = min(max(at, lo), hi - length)
    return start, start + length


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

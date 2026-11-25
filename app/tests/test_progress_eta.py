"""
test_progress_eta.py — Tempo rimanente stimato durante la trascrizione.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication

from ui import progress_widget as pwm


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.mark.parametrize("seconds, text", [
    (600, "Circa 10 min rimanenti"),
    (130, "Circa 2 min rimanenti"),
    (70, "Circa un minuto rimanente"),
    (40, "Meno di un minuto"),
    (3, "Quasi finito"),
])
def test_remaining_text(seconds, text):
    assert pwm.remaining_text(seconds) == text


def test_estimate_waits_for_enough_data():
    est = pwm.RemainingEstimate()
    assert est.update(0.10, now=0.0) is None          # pre-elaborazione: non conta
    assert est.update(0.15, now=10.0) is None         # comincia la trascrizione vera
    assert est.update(0.17, now=12.0) is None         # troppo poco per stimare
    # 0,15 → 0,30 in 30 s: 0,15 ogni 30 s; da 0,30 a 0,90 restano 0,60 → 120 s
    assert est.update(0.30, now=40.0) == pytest.approx(120.0)


def test_estimate_counts_down_between_updates_and_never_goes_negative():
    est = pwm.RemainingEstimate()
    est.update(0.15, now=0.0)
    est.update(0.30, now=30.0)                        # 120 s rimanenti
    assert est.remaining(now=50.0) == pytest.approx(100.0)
    assert est.remaining(now=500.0) == 0.0


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(pwm.time, "monotonic", c)
    return c


def test_progress_widget_shows_the_estimate(app, clock):
    w = pwm.ProgressWidget()
    w._reset_eta()
    w._on_progress(0.15)
    clock.now = 10.0
    w._on_progress(0.17)
    assert w.eta_lbl.text() == ""                      # ancora troppo presto
    clock.now = 40.0
    w._on_progress(0.40)
    assert w.eta_lbl.text().startswith("Circa")
    w._on_finished([])
    assert w.eta_lbl.text() == ""


# ── Segni di vita tra un blocco e l'altro ───────────────────────────────────

@pytest.mark.parametrize("seconds, text", [
    (0, "In corso da 0:00"), (42.7, "In corso da 0:42"), (125, "In corso da 2:05"),
    (3930, "In corso da 1:05:30"),
])
def test_elapsed_text(seconds, text):
    assert pwm.elapsed_text(seconds) == text


def test_audio_clock():
    assert pwm.audio_clock(83.4) == "01:23"
    assert pwm.audio_clock(3723) == "1:02:03"


def test_smooth_progress_moves_between_engine_updates():
    sp = pwm.SmoothProgress()
    assert sp.real(0.10, now=0.0) == 0.10
    assert sp.real(0.15, now=5.0) == 0.15
    assert sp.shown(now=60.0) == 0.15        # nessuna velocità nota: resta ferma
    assert sp.real(0.30, now=35.0) == 0.30   # un blocco: +0,15 in 30 s
    assert sp.shown(now=45.0) == pytest.approx(0.35)
    # blocco in ritardo: si ferma al salto più grande visto, poi aspetta il valore vero
    assert sp.shown(now=500.0) == pytest.approx(0.45)
    # il valore vero più basso di quello mostrato non la fa scendere
    assert sp.real(0.40, now=510.0) == pytest.approx(0.45)
    assert sp.real(0.60, now=520.0) == pytest.approx(0.60)


def test_smooth_progress_never_passes_90_and_stays_still_after():
    sp = pwm.SmoothProgress()
    sp.real(0.15, now=0.0)
    sp.real(0.85, now=10.0)
    assert sp.shown(now=1000.0) < 0.90
    sp.real(0.92, now=1001.0)                # recupero del parlato e segmentazione
    assert sp.shown(now=5000.0) == pytest.approx(0.92)


def test_widget_ticks_shows_phrases_and_final_duration(app, clock):
    w = pwm.ProgressWidget()
    w._reset_eta()
    w._t_start = 0.0
    w._on_progress(0.15)
    clock.now = 30.0
    w._on_progress(0.30)
    clock.now = 40.0
    w._tick()
    assert w.elapsed_lbl.text() == "In corso da 0:40"
    assert w.pct_lbl.text().count(">35<") == 1        # salita tra i due blocchi
    w._on_text(83.4, "Cos'è l'intelligenza artificiale civica?")
    assert w.log.toPlainText().endswith("01:23  Cos'è l'intelligenza artificiale civica?")
    clock.now = 95.0
    w._on_finished([])
    assert w.elapsed_lbl.text() == "Completata in 1:35"
    w._on_cancelled()
    assert w.elapsed_lbl.text() == ""

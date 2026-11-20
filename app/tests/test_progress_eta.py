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


def test_progress_widget_shows_the_estimate(app, monkeypatch):
    w = pwm.ProgressWidget()
    clock = iter([0.0, 10.0, 40.0, 40.0])
    monkeypatch.setattr(pwm.time, "monotonic", lambda: next(clock))
    w._reset_eta()
    w._on_progress(0.15)
    w._on_progress(0.17)
    assert w.eta_lbl.text() == ""                      # ancora troppo presto
    w._on_progress(0.40)
    assert w.eta_lbl.text().startswith("Circa")
    w._on_finished([])
    assert w.eta_lbl.text() == ""

"""
test_whisper_models.py — Modelli Whisper: consiglio in base all'hardware, modelli già
scaricati e download con avanzamento.

Prima: l'app usava sempre large-v3 (~3 GB, ~6 GB di RAM) anche su computer con 8 GB, e se il
modello mancava lo scaricava all'avvio, durante lo splash, senza dire niente. Ora propone il
modello adatto al computer e lo scarica solo quando serve, con l'avanzamento visibile.
"""

from __future__ import annotations

import os
import sys
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import platform_support as ps
from core import whisper_models as wm

GIB = 1024 ** 3


# ── Consiglio in base all'hardware ───────────────────────────────────────────

@pytest.mark.parametrize("ram_gib, cuda, expected", [
    (64, False, "large-v3"),
    (16, False, "large-v3"),
    (15.6, False, "large-v3"),      # 16 GB dichiarati, un po' meno visti dal sistema
    (8, False, "large-v3-turbo"),
    (7.6, False, "large-v3-turbo"),
    (4, False, "small"),
    (2, False, "base"),
    (8, True, "large-v3"),          # GPU NVIDIA: il modello migliore
    (0, False, "large-v3-turbo"),   # RAM sconosciuta: scelta prudente
])
def test_recommended_model(ram_gib, cuda, expected):
    assert wm.recommend_model(int(ram_gib * GIB), cuda) == expected


def test_every_model_has_label_ram_quality_and_size():
    for key, info in wm.MODELS.items():
        assert info["label"] and info["ram"] and info["quality"], key
        assert info["download_gb"] > 0, key
        assert wm.model_repo(key).count("/") == 1, key


def test_total_ram_is_known_on_this_computer():
    assert ps.total_ram_bytes() > GIB


# ── Modelli già scaricati (cache di Hugging Face) ─────────────────────────────

def _fake_download(cache, key, complete=True):
    repo = wm.model_repo(key)
    snap = cache / ("models--" + repo.replace("/", "--")) / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}", encoding="utf-8")
    if complete:
        (snap / "model.bin").write_bytes(b"x")
    return snap


def test_downloaded_models_are_found_in_the_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    assert not wm.is_downloaded("small")
    _fake_download(tmp_path, "small")
    _fake_download(tmp_path, "medium", complete=False)   # download interrotto
    assert wm.is_downloaded("small")
    assert not wm.is_downloaded("medium")
    assert not wm.is_downloaded("large-v3")


def test_hf_home_is_respected(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert wm.hub_cache_dir() == tmp_path / "hub"


# ── Download con avanzamento ─────────────────────────────────────────────────

def test_download_reports_progress_and_finishes(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    repo_dir = tmp_path / ("models--" + wm.model_repo("tiny").replace("/", "--"))
    total = int(wm.MODELS["tiny"]["download_gb"] * 1e9)
    release = threading.Event()

    def fake_fetch(key):
        blobs = repo_dir / "blobs"
        blobs.mkdir(parents=True)
        (blobs / "a.incomplete").write_bytes(b"\0" * (total // 2))
        release.wait(2)
        _fake_download(tmp_path, key)

    monkeypatch.setattr(wm, "_fetch", fake_fetch)
    statuses, progress = [], []

    def on_progress(p):
        progress.append(p)
        if p >= 0.4:
            release.set()

    wm.download("tiny", on_status=statuses.append, on_progress=on_progress, poll_s=0.01)
    assert wm.is_downloaded("tiny")
    assert progress[-1] == 1.0
    assert any(0.4 <= p < 1.0 for p in progress)
    assert all(a <= b for a, b in zip(progress, progress[1:]))
    assert any("Download del modello tiny" in s for s in statuses)


def test_download_can_be_cancelled(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    stop = threading.Event()
    monkeypatch.setattr(wm, "_fetch", lambda key: stop.wait(5))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(wm.DownloadCancelled):
        wm.download("small", cancel_event=cancel, poll_s=0.01)
    stop.set()


def test_download_error_is_explained_in_italian(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))

    def boom(key):
        raise OSError("connection refused")

    monkeypatch.setattr(wm, "_fetch", boom)
    with pytest.raises(RuntimeError, match="Download del modello small non riuscito"):
        wm.download("small", poll_s=0.01)


# ── Motore: scarica solo quando serve, mai allo splash ───────────────────────

def _engine_with_fake_model(monkeypatch):
    import engine
    from types import SimpleNamespace

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            info = SimpleNamespace(duration=2.0, language="it", language_probability=0.9)
            return iter([]), info

    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    monkeypatch.setattr(engine, "_get_or_load_model", lambda *a, **k: FakeModel())
    return engine


def test_transcribe_downloads_a_missing_model_first(monkeypatch):
    engine = _engine_with_fake_model(monkeypatch)
    assert not engine.is_model_available("small")
    statuses, progress = [], []
    engine.transcribe("x.wav", model_size="small", denoise=False, vad_filter=False,
                      on_status=statuses.append, on_progress=progress.append)
    assert engine.is_model_available("small")
    assert "Modello small scaricato" in statuses
    assert progress == sorted(progress) and progress[-1] <= 1.0


def test_transcribe_with_a_downloaded_model_does_not_download(monkeypatch):
    engine = _engine_with_fake_model(monkeypatch)
    wm._fetch("base")
    calls = []
    monkeypatch.setattr(wm, "_fetch", lambda key: calls.append(key))
    engine.transcribe("x.wav", model_size="base", denoise=False, vad_filter=False)
    assert calls == []


def test_cancelled_download_cancels_the_transcription(monkeypatch):
    engine = _engine_with_fake_model(monkeypatch)
    stop = threading.Event()
    monkeypatch.setattr(wm, "_fetch", lambda key: stop.wait(5))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(engine.TranscriptionCancelled):
        engine.transcribe("x.wav", model_size="medium", denoise=False, vad_filter=False,
                          cancel_event=cancel)
    stop.set()


def test_preload_never_downloads(monkeypatch):
    import engine
    calls = []
    monkeypatch.setattr(wm, "_fetch", lambda key: calls.append(key))
    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    statuses = []
    assert engine.preload_model("large-v3-turbo", on_status=statuses.append) is False
    assert calls == []
    assert "da scaricare" in statuses[-1]


def test_recommended_model_uses_the_detected_hardware(monkeypatch):
    import engine
    monkeypatch.setitem(engine._hardware_cache, "hw", (8 * GIB, False))
    assert engine.recommended_model() == "large-v3-turbo"


def test_download_messages_do_not_jump_progress_phases():
    from ui.progress_widget import phase_for_status
    assert phase_for_status("Download del modello small: 0,2 di ~0,5 GB") is None
    assert phase_for_status("Modello small scaricato") is None
    assert phase_for_status("Caricamento modello 'small'...") == 1

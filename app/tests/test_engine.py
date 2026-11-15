"""
test_engine.py — Test del motore di trascrizione senza caricare modelli Whisper.

Usa oggetti finti (SimpleNamespace) per parole e segmenti, e moduli finti
``faster_whisper`` / ``ctranslate2`` iniettati in ``sys.modules``.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import types
from types import SimpleNamespace

import pytest

import engine


# ── Helper ────────────────────────────────────────────────────────────────────

def _w(word: str, start: float, end: float, prob: float = 0.9) -> SimpleNamespace:
    return SimpleNamespace(word=word, start=start, end=end, probability=prob)


def _seg(words, text: str = "", start: float = None, end: float = None) -> SimpleNamespace:
    if start is None:
        start = words[0].start if words else 0.0
    if end is None:
        end = words[-1].end if words else 0.0
    if not text:
        text = " ".join(w.word.strip() for w in words)
    return SimpleNamespace(
        words=words, text=text, start=start, end=end,
        no_speech_prob=0.0, avg_logprob=-0.2,
    )


def _all_text(subs) -> str:
    return " ".join(s["text"] for s in subs)


# ── Bug parole perse ──────────────────────────────────────────────────────────

def test_synthetic_segment_followed_by_real_words_keeps_all_words():
    """Segmento senza parole affidabili seguito da parlato: nessuna parola sparisce."""
    low = [_w(" ok", 0.0, 0.3, 0.1), _w(" va", 0.3, 0.6, 0.1), _w(" bene", 0.6, 1.0, 0.1)]
    seg1 = _seg(low, text=" ok va bene", start=0.0, end=1.0)
    real_words = ["allora", "oggi", "parliamo", "di", "sottotitoli"]
    seg2 = _seg([_w(" " + t, 1.05 + i * 0.3, 1.3 + i * 0.3) for i, t in enumerate(real_words)])

    words, boundaries = engine.collect_all_words([seg1, seg2])
    subs = engine.segment_words_semantic(words, boundaries)
    text = _all_text(subs)
    for token in ["ok", "va", "bene"] + real_words:
        assert token in text.split(), f"parola persa: {token!r} in {text!r}"


def test_collect_all_words_returns_module_level_fake_word():
    seg = _seg([_w(" ehm", 0.0, 0.5, 0.05)], text=" ehm", start=0.0, end=0.5)
    words, boundaries = engine.collect_all_words([seg])
    assert len(words) == 1
    assert isinstance(words[0], engine._FakeWord)
    assert words[0].word == "ehm"
    assert boundaries == set()


def test_synthetic_word_is_isolated_in_its_own_block():
    """Un word sintetico forza uno split prima e dopo di sé (prima del merge)."""
    seg0 = _seg([_w(" Buongiorno", 0.0, 0.4), _w(" a", 0.42, 0.5), _w(" tutti", 0.52, 0.8)])
    seg1 = _seg([_w(" xx", 0.85, 1.0, 0.1)], text=" mh mh", start=0.85, end=1.0)
    seg2 = _seg([_w(" e", 1.05, 1.1), _w(" benvenuti", 1.12, 1.6)])
    words, boundaries = engine.collect_all_words([seg0, seg1, seg2])
    # Disattiva il merge per osservare i blocchi grezzi
    old = engine.MERGE_MIN_CHARS
    engine.MERGE_MIN_CHARS = 0
    try:
        subs = engine.segment_words_semantic(words, boundaries)
    finally:
        engine.MERGE_MIN_CHARS = old
    assert [s["text"] for s in subs] == ["Buongiorno a tutti", "mh mh", "e benvenuti"]


# ── Merge frammenti corti ─────────────────────────────────────────────────────

def test_merge_respects_max_duration():
    seg1 = _seg([_w(" Ciao.", 0.0, 0.5)])
    tokens = ["uno", "due", "tre", "quattro"]
    # Il secondo blocco dura 6.75 s: unito al primo supererebbe MAX_SUBTITLE_DURATION
    seg2 = _seg([_w(" " + t, 0.6 + i * 1.7, 0.6 + i * 1.7 + 1.65) for i, t in enumerate(tokens)])
    words, boundaries = engine.collect_all_words([seg1, seg2])
    subs = engine.segment_words_semantic(words, boundaries)
    assert subs[0]["text"] == "Ciao."
    for s in subs:
        assert s["end"] - s["start"] <= engine.MAX_SUBTITLE_DURATION
    assert _all_text(subs).split() == ["Ciao."] + tokens


def test_merge_respects_hard_limit():
    seg1 = _seg([_w(" Ciao.", 0.0, 0.5)])
    tokens = ["parola%02d" % i for i in range(9)]  # 9 * 8 + 8 spazi = 80 caratteri
    seg2 = _seg([_w(" " + t, 0.6 + i * 0.3, 0.6 + i * 0.3 + 0.25) for i, t in enumerate(tokens)])
    words, boundaries = engine.collect_all_words([seg1, seg2])
    subs = engine.segment_words_semantic(words, boundaries)
    for s in subs:
        assert len(s["text"]) <= engine.HARD_LIMIT
    assert _all_text(subs).split() == ["Ciao."] + tokens


def test_merge_still_joins_short_fragments():
    seg1 = _seg([_w(" Ciao.", 0.0, 0.5)])
    seg2 = _seg([_w(" Come", 0.6, 0.9), _w(" stai?", 0.92, 1.3)])
    words, boundaries = engine.collect_all_words([seg1, seg2])
    subs = engine.segment_words_semantic(words, boundaries)
    assert [s["text"] for s in subs] == ["Ciao. Come stai?"]


# ── post_process_timing ───────────────────────────────────────────────────────

def test_post_process_timing_overlapping_segments():
    segs = [
        {"start": 0.0, "end": 2.0, "text": "uno"},
        {"start": 1.5, "end": 3.0, "text": "due"},
        {"start": 2.9, "end": 4.0, "text": "tre"},
        {"start": 1.0001, "end": 1.0002, "text": "quattro"},
        {"start": 1.0802, "end": 1.5, "text": "cinque"},
    ]
    out = engine.post_process_timing(segs)
    assert len(out) == 5
    for s in out:
        assert s["end"] > s["start"], s
    for cur, nxt in zip(out, out[1:]):
        limit = nxt["start"] - engine.MIN_GAP_BETWEEN_SUBS
        if limit > cur["start"]:
            assert cur["end"] <= limit + 1e-9, (cur, nxt)


def test_post_process_timing_rounding_never_collapses():
    segs = [
        {"start": 1.0001, "end": 1.0002, "text": "a"},
        {"start": 1.0803, "end": 2.0, "text": "b"},
    ]
    out = engine.post_process_timing(segs)
    assert all(s["end"] > s["start"] for s in out), out


# ── Cache modello thread-safe ─────────────────────────────────────────────────

@pytest.fixture
def fake_backends(monkeypatch):
    """Inietta moduli finti faster_whisper e ctranslate2."""
    calls = []
    lock = threading.Lock()

    class FakeWhisperModel:
        def __init__(self, path, **kwargs):
            time.sleep(0.05)
            with lock:
                calls.append((path, kwargs))
            self.path = path

    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = FakeWhisperModel
    ct2 = types.ModuleType("ctranslate2")
    ct2.cuda_count = 0
    ct2.get_cuda_device_count = lambda: ct2.cuda_count
    ct2.get_supported_compute_types = lambda device: {"int8", "float32"}
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    monkeypatch.setitem(sys.modules, "ctranslate2", ct2)
    monkeypatch.setitem(engine._model_cache, "model", None)
    monkeypatch.setitem(engine._model_cache, "model_key", None)
    return SimpleNamespace(calls=calls, ct2=ct2)


def test_model_cache_concurrent_loads_once(fake_backends):
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(engine._get_or_load_model("tiny"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len(fake_backends.calls) == 1
    assert len(results) == 2
    assert results[0] is results[1]
    assert results[0].path == "tiny"
    assert fake_backends.calls[0][1].get("num_workers") == 1


def test_model_cache_reload_on_different_key(fake_backends):
    m1 = engine._get_or_load_model("tiny")
    m2 = engine._get_or_load_model("tiny")
    m3 = engine._get_or_load_model("base")
    assert m1 is m2
    assert m3 is not m1
    assert len(fake_backends.calls) == 2


def test_get_optimal_device_uses_ctranslate2(fake_backends):
    assert engine.get_optimal_device() == ("cpu", "int8")
    fake_backends.ct2.cuda_count = 1
    assert engine.get_optimal_device() == ("cuda", "float16")


# ── Varie ─────────────────────────────────────────────────────────────────────

def test_check_cancel():
    engine._check_cancel(None)
    ev = threading.Event()
    engine._check_cancel(ev)
    ev.set()
    with pytest.raises(engine.TranscriptionCancelled, match="annullata dall'utente"):
        engine._check_cancel(ev)


def test_renamed_postprocessors():
    assert engine._postprocess_codeswitching("il macchina lerning") == "il machine learning"
    assert engine._postprocess_typography("ciao , un po bene") == "ciao, un po' bene"
    assert not hasattr(engine, "_postprocess_italian")
    assert not hasattr(engine, "_postprocess_italian_subs")


def test_dead_code_removed():
    for name in ("format_timestamp_srt", "wrap_subtitle_text", "generate_srt",
                 "write_srt", "_unique_output_path", "split_segment_by_words",
                 "SILENCE_THRESHOLD", "END_PAD_SPEECH", "END_PAD_SILENCE",
                 "READING_SPEED_CPS"):
        assert not hasattr(engine, name), name


def test_vad_params_constant():
    assert engine.VAD_PARAMS == dict(min_silence_duration_ms=150, speech_pad_ms=100,
                                     threshold=0.50)


def test_vad_error_classification():
    assert engine._is_vad_unavailable_error(ImportError("No module named 'onnxruntime'"))
    assert engine._is_vad_unavailable_error(
        RuntimeError("[ONNXRuntimeError] : 3 : NO_SUCHFILE silero_vad.onnx"))
    assert not engine._is_vad_unavailable_error(RuntimeError("out of memory"))
    assert not engine._is_vad_unavailable_error(FileNotFoundError("video.mp4"))


class _FakePopen:
    """Popen finto: ``communicate`` va in timeout finché non viene terminato."""

    instances = []

    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.stop = False
        _FakePopen.instances.append(self)

    def communicate(self, timeout=None):
        import subprocess
        if self.stop:
            self.returncode = 1 if self.returncode is None else self.returncode
            return "", "errore"
        time.sleep(min(timeout or 0.01, 0.01))
        raise subprocess.TimeoutExpired(self.cmd, timeout)

    def terminate(self):
        self.terminated = True
        self.stop = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.stop = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode


def test_preprocess_audio_failure_reports_status(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "_FFMPEG_TIMEOUT_S", 0.3)
    monkeypatch.setattr(engine.subprocess, "Popen", _FakePopen)
    msgs = []
    assert engine.preprocess_audio(str(tmp_path / "x.mp4"), on_status=msgs.append) is None
    assert any("Pre-elaborazione audio non riuscita" in m for m in msgs)
    assert _FakePopen.instances[-1].terminated   # ffmpeg non resta in giro dopo il timeout


def test_preprocess_audio_uses_absolute_path(monkeypatch):
    _FakePopen.instances.clear()

    class Fail(_FakePopen):
        def communicate(self, timeout=None):
            self.returncode = 1
            return "", "errore"

    monkeypatch.setattr(engine.subprocess, "Popen", Fail)
    engine.preprocess_audio("-strano.mp4")
    cmd = _FakePopen.instances[-1].cmd
    i = cmd.index("-i")
    assert cmd[i + 1].startswith(("/", "\\")) or ":" in cmd[i + 1]


def test_preprocess_audio_cancel_terminates_ffmpeg_and_removes_temp(monkeypatch):
    _FakePopen.instances.clear()
    created = []
    real_ntf = engine.tempfile.NamedTemporaryFile

    def tracking_ntf(*a, **k):
        f = real_ntf(*a, **k)
        created.append(f.name)
        return f

    monkeypatch.setattr(engine.tempfile, "NamedTemporaryFile", tracking_ntf)
    monkeypatch.setattr(engine.subprocess, "Popen", _FakePopen)
    ev = threading.Event()
    threading.Timer(0.3, ev.set).start()
    t0 = time.monotonic()
    with pytest.raises(engine.TranscriptionCancelled):
        engine.preprocess_audio("x.mp4", cancel_event=ev)
    assert time.monotonic() - t0 < 3
    proc = _FakePopen.instances[-1]
    assert proc.terminated or proc.killed
    assert created and not os.path.exists(created[0])


def test_preprocess_audio_already_cancelled_does_not_leave_temp(monkeypatch):
    _FakePopen.instances.clear()
    monkeypatch.setattr(engine.subprocess, "Popen", _FakePopen)
    ev = threading.Event()
    ev.set()
    with pytest.raises(engine.TranscriptionCancelled):
        engine.preprocess_audio("x.mp4", cancel_event=ev)
    assert all(p.terminated or p.killed for p in _FakePopen.instances)


def test_transcribe_passes_cancel_event_to_preprocess(monkeypatch):
    seen = {}

    def fake_pre(path, on_status=None, cancel_event=None):
        seen["ev"] = cancel_event
        raise engine.TranscriptionCancelled()

    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    monkeypatch.setattr(engine, "preprocess_audio", fake_pre)
    ev = threading.Event()
    with pytest.raises(engine.TranscriptionCancelled):
        engine.transcribe("x.mp4", denoise=True, cancel_event=ev)
    assert seen["ev"] is ev


def test_transcribe_is_keyword_only():
    import inspect
    params = inspect.signature(engine.transcribe).parameters
    names = list(params)
    assert names[0] == "input_path"
    for name in names[1:]:
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name
    assert "language" in params


def test_check_ffmpeg_uses_which(monkeypatch):
    monkeypatch.setattr(engine, "get_bundled_ffmpeg", lambda: None)
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)
    assert engine.check_ffmpeg() is False
    monkeypatch.setattr(engine.shutil, "which", lambda name: "/usr/bin/" + name)
    assert engine.check_ffmpeg() is True


# ── Lingua "auto" ─────────────────────────────────────────────────────────────

def _fake_whisper_model(detected: str, captured: dict):
    """Modello finto che cattura i kwargs di transcribe e rileva ``detected``."""
    word = _w("Machine", 0.0, 0.5)
    word2 = _w("learning", 0.5, 1.0)
    seg = _seg([word, word2], text="Machine learning", start=0.0, end=1.0)

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            info = SimpleNamespace(duration=1.0, language=detected,
                                   language_probability=0.9)
            return iter([seg]), info

    return FakeModel()


def _run_transcribe(monkeypatch, language, detected="en"):
    captured = {}
    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    monkeypatch.setattr(engine, "_get_or_load_model",
                        lambda *a, **k: _fake_whisper_model(detected, captured))
    out = engine.transcribe("x.wav", denoise=False, vad_filter=False, language=language)
    return captured, out


@pytest.mark.parametrize("raw", ["auto", "", None])
def test_transcribe_auto_passes_none_language(monkeypatch, raw):
    captured, _ = _run_transcribe(monkeypatch, raw, detected="en")
    assert captured["language"] is None
    assert captured["initial_prompt"] is None


def test_transcribe_italian_uses_prompt(monkeypatch):
    captured, _ = _run_transcribe(monkeypatch, "it", detected="it")
    assert captured["language"] == "it"
    assert captured["initial_prompt"] == engine.ITALIAN_PROMPT


def test_transcribe_auto_detected_italian_applies_codeswitching(monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "_postprocess_codeswitching",
                        lambda t: calls.append(t) or t)
    _run_transcribe(monkeypatch, "auto", detected="it")
    assert calls


def test_transcribe_auto_detected_english_skips_codeswitching(monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "_postprocess_codeswitching",
                        lambda t: calls.append(t) or t)
    _run_transcribe(monkeypatch, "auto", detected="en")
    assert not calls


def test_normalize_language():
    from core.constants import normalize_language
    assert normalize_language("auto") is None
    assert normalize_language(None) is None
    assert normalize_language(" IT ") == "it"


# ── "Alta precisione" non disponibile: mai un ripiego silenzioso ─────────────

def test_high_accuracy_unavailable_is_reported(monkeypatch):
    captured, statuses = {}, []
    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    monkeypatch.setattr(engine, "_has_whisperx", lambda: False)
    monkeypatch.setattr(engine, "high_accuracy_unavailable_reason",
                        lambda: "WhisperX non è installato (pip install whisperx)")
    monkeypatch.setattr(engine, "_get_or_load_model",
                        lambda *a, **k: _fake_whisper_model("it", captured))
    out = engine.transcribe("x.wav", denoise=False, vad_filter=False, language="it",
                            high_accuracy=True, on_status=statuses.append)
    assert out, "deve comunque trascrivere in modalità standard"
    assert any("Alta precisione non disponibile" in s and "WhisperX" in s for s in statuses)


def test_high_accuracy_reason_when_package_missing(monkeypatch):
    import importlib.util
    monkeypatch.setattr(engine, "_is_frozen", lambda: False)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert "WhisperX" in engine.high_accuracy_unavailable_reason()
    assert engine.high_accuracy_available() is False
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert engine.high_accuracy_available() is True
    monkeypatch.setattr(engine, "_is_frozen", lambda: True)
    assert engine.high_accuracy_available() is False

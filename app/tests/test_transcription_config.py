"""
test_transcription_config.py — Configurazione dei parametri di trascrizione (.vsrtconfig).

Copre: valori predefiniti identici al tuning storico (anche nei kwargs passati a
faster-whisper), round-trip dict/JSON/file, validazione di tipi e intervalli, file
corrotti e versioni future, passaggio della configurazione da worker a motore (glossario
come ``hotwords``), limiti di leggibilità applicati a editor ed esportazione, glossario
nella schermata iniziale, persistenza in QSettings e voci del menu File.
"""

from __future__ import annotations

import json
import math
import os
import sys
import types
from dataclasses import replace
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

import engine
import platform_support
from core import constants
from core.subtitle_model import Subtitle
from core.transcription_config import (
    CONFIG_FORMAT, CONFIG_VERSION, DEFAULT_GLOSSARY, ITALIAN_PROMPT, MAX_FILE_BYTES,
    DecodingOptions, ReadabilityLimits, TranscriptionConfig, VadOptions, active_readability,
    load_config, parse_glossary, save_config, set_active_readability,
)
from core.transcription_worker import TranscriptionParams, TranscriptionWorker


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_active_readability():
    """I limiti attivi sono globali: ogni test riparte dai predefiniti."""
    set_active_readability(None)
    yield
    set_active_readability(None)


def _custom_config() -> TranscriptionConfig:
    """Configurazione con tutti i valori diversi dai predefiniti."""
    return TranscriptionConfig(
        model_size="medium", language="en", vad_filter=False, high_accuracy=True,
        beam_size=3, denoise=False,
        decoding=DecodingOptions(
            initial_prompts={"en": "Tech talk: Kubernetes, PyTorch.", "it": "Glossario: RAG."},
            glossary=("Kubernetes", "PyTorch", "Mario Rossi"),
            temperature=(0.0, 0.3), patience=1.5, no_speech_threshold=0.6,
            log_prob_threshold=-1.0, compression_ratio_threshold=2.2,
            condition_on_previous_text=True,
        ),
        vad=VadOptions(threshold=0.4, min_silence_duration_ms=300, speech_pad_ms=200),
        readability=ReadabilityLimits(max_chars_per_line=32, max_lines=1, max_cps=15.0,
                                      warn_cps=12.0, min_duration_s=0.8, max_duration_s=5.0,
                                      min_gap_s=0.1, keep_low_confidence_words=False),
    )


def _write(tmp_path, data, name="cfg.vsrtconfig") -> str:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


# Parametri di decodifica storici (prima della configurazione), copiati alla lettera;
# l'unica aggiunta voluta dei predefiniti è il glossario passato come hotwords.
_HISTORIC_DECODE = dict(
    task="transcribe", beam_size=5, patience=1.0, word_timestamps=True,
    condition_on_previous_text=False, no_speech_threshold=0.5, log_prob_threshold=-1.2,
    compression_ratio_threshold=2.4, temperature=[0.0, 0.2, 0.4, 0.6],
)
_HISTORIC_VAD = dict(min_silence_duration_ms=150, speech_pad_ms=100, threshold=0.50)


# ── Predefiniti = valori storici ──────────────────────────────────────────────

def test_defaults_match_historic_values():
    c = TranscriptionConfig()
    assert (c.model_size, c.language, c.vad_filter, c.high_accuracy, c.beam_size,
            c.denoise) == ("large-v3", "it", True, False, 5, True)
    assert c.model_size == engine.DEFAULT_MODEL
    d = c.decoding
    assert d.prompt_for("it") == ITALIAN_PROMPT == engine.ITALIAN_PROMPT
    assert d.temperature == (0.0, 0.2, 0.4, 0.6)
    assert (d.patience, d.no_speech_threshold, d.log_prob_threshold,
            d.compression_ratio_threshold, d.condition_on_previous_text) == (
        1.0, 0.5, -1.2, 2.4, False)
    assert c.vad.as_dict() == _HISTORIC_VAD == engine.VAD_PARAMS
    r = c.readability
    assert (r.max_chars_per_line, r.max_cps, r.warn_cps, r.min_duration_s,
            r.max_duration_s) == (
        constants.MAX_CHARS_PER_LINE, constants.MAX_CPS, constants.WARN_CPS,
        constants.MIN_SUBTITLE_DURATION, constants.MAX_SUBTITLE_DURATION)
    assert r.max_lines == 2 and r.keep_low_confidence_words is True
    assert r.min_gap_s == engine.MIN_GAP_BETWEEN_SUBS
    # glossario predefinito = anglicismi e marchi già elencati nel prompt italiano
    assert d.glossary == DEFAULT_GLOSSARY
    assert all(term in ITALIAN_PROMPT for term in d.glossary)
    assert c.is_default() and not _custom_config().is_default()


def test_params_defaults_match_config_defaults():
    p = TranscriptionParams(input_path="a.mp4")
    c = TranscriptionConfig()
    assert p.config == c
    assert (p.model_size, p.beam_size, p.vad_filter, p.denoise, p.high_accuracy) == (
        c.model_size, c.beam_size, c.vad_filter, c.denoise, c.high_accuracy)
    assert p.language == c.whisper_language == "it"


def _fake_model(captured: list, detected: str = "it"):
    word = SimpleNamespace(word="ciao", start=0.0, end=0.5, probability=0.9)
    seg = SimpleNamespace(words=[word], text="ciao", start=0.0, end=0.5,
                          no_speech_prob=0.0, avg_logprob=-0.2)

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            captured.append(kwargs)
            return iter([seg]), SimpleNamespace(duration=1.0, language=detected,
                                                language_probability=0.9)
    return FakeModel()


def _capture_transcribe(monkeypatch, **kwargs) -> dict:
    captured: list = []
    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    monkeypatch.setattr(engine, "_get_or_load_model", lambda *a, **k: _fake_model(captured))
    engine.transcribe("x.wav", denoise=False, **kwargs)
    return captured[-1]


@pytest.mark.parametrize("language, prompt", [("it", ITALIAN_PROMPT), ("en", None),
                                              ("auto", None)])
@pytest.mark.parametrize("vad", [True, False])
def test_default_config_produces_historic_whisper_kwargs_plus_glossary(monkeypatch, language,
                                                                       prompt, vad):
    expected = dict(_HISTORIC_DECODE, language=engine.normalize_language(language),
                    initial_prompt=prompt, vad_filter=vad,
                    hotwords=", ".join(DEFAULT_GLOSSARY))
    if vad:
        expected["vad_parameters"] = _HISTORIC_VAD
    without = _capture_transcribe(monkeypatch, language=language, vad_filter=vad)
    with_default = _capture_transcribe(monkeypatch, language=language, vad_filter=vad,
                                       config=TranscriptionConfig())
    assert without == expected
    assert with_default == expected


def test_custom_config_reaches_faster_whisper(monkeypatch):
    cfg = _custom_config()
    kw = _capture_transcribe(monkeypatch, language="en", vad_filter=True, config=cfg)
    assert kw["initial_prompt"] == "Tech talk: Kubernetes, PyTorch."
    assert kw["hotwords"] == "Kubernetes, PyTorch, Mario Rossi"
    assert kw["temperature"] == [0.0, 0.3]
    assert (kw["patience"], kw["no_speech_threshold"], kw["log_prob_threshold"],
            kw["compression_ratio_threshold"], kw["condition_on_previous_text"]) == (
        1.5, 0.6, -1.0, 2.2, True)
    assert kw["vad_parameters"] == dict(min_silence_duration_ms=300, speech_pad_ms=200,
                                        threshold=0.4)


def test_empty_glossary_passes_no_hotwords(monkeypatch):
    cfg = replace(TranscriptionConfig(),
                  decoding=replace(DecodingOptions(), glossary=()))
    kw = _capture_transcribe(monkeypatch, language="it", vad_filter=False, config=cfg)
    assert "hotwords" not in kw


def test_hotwords_skipped_when_faster_whisper_lacks_them(monkeypatch):
    captured = []

    class OldModel:                                  # firma senza hotwords né **kwargs
        def transcribe(self, audio, language=None, task=None, beam_size=5, patience=1.0,
                       initial_prompt=None, word_timestamps=False,
                       condition_on_previous_text=True, no_speech_threshold=0.6,
                       log_prob_threshold=-1.0, compression_ratio_threshold=2.4,
                       temperature=0.0, vad_filter=False, vad_parameters=None):
            captured.append(initial_prompt)
            return iter([]), SimpleNamespace(duration=1.0, language="it",
                                             language_probability=0.9)

    monkeypatch.setattr(engine, "_setup_environment", lambda: None)
    monkeypatch.setattr(engine, "_get_or_load_model", lambda *a, **k: OldModel())
    assert engine.transcribe("x.wav", denoise=False, vad_filter=False) == []
    assert captured == [ITALIAN_PROMPT]


def test_parse_glossary():
    assert parse_glossary(" machine  learning, , Google,\nnpm, Google ") == (
        "machine learning", "Google", "npm")
    assert parse_glossary("") == ()


# ── Round-trip ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cfg", [TranscriptionConfig(), _custom_config()])
def test_dict_and_json_roundtrip(cfg):
    assert TranscriptionConfig.from_dict(cfg.to_dict()) == cfg
    assert TranscriptionConfig.from_json(cfg.to_json()) == cfg
    # il JSON è leggibile e ha intestazione e sezioni attese
    data = json.loads(cfg.to_json())
    assert data["format"] == CONFIG_FORMAT and data["version"] == CONFIG_VERSION
    assert set(data) == {"format", "version", "transcription", "decoding", "vad",
                         "readability"}
    assert isinstance(data["decoding"]["initial_prompts"], dict)


def test_file_roundtrip_is_atomic_and_overwrites(tmp_path):
    path = str(tmp_path / "podcast.vsrtconfig")
    save_config(TranscriptionConfig(), path)
    save_config(_custom_config(), path)          # sovrascrive
    assert load_config(path) == _custom_config()
    assert os.listdir(tmp_path) == ["podcast.vsrtconfig"]   # nessun file temporaneo
    assert "Glossario: RAG." in (tmp_path / "podcast.vsrtconfig").read_text(encoding="utf-8")


def test_load_accepts_utf8_bom(tmp_path):
    p = tmp_path / "bom.vsrtconfig"
    p.write_bytes(b"\xef\xbb\xbf" + _custom_config().to_json().encode("utf-8"))
    assert load_config(str(p)) == _custom_config()


def test_exported_config_reproduces_same_worker_and_engine_params(tmp_path, monkeypatch):
    """Esporta → reimporta → stessi parametri passati al motore e al timing."""
    cfg = _custom_config()
    path = str(tmp_path / "x.vsrtconfig")
    save_config(cfg, path)
    reloaded = load_config(path)

    def run(config):
        seen = {}

        def fake_transcribe(**kw):
            seen["transcribe"] = kw
            return [{"start": 0.0, "end": 1.0, "text": "x"}]

        def fake_timing(segs, **kw):
            seen["timing"] = kw
            return segs

        fake = types.SimpleNamespace(transcribe=fake_transcribe, post_process_timing=fake_timing,
                                     TranscriptionCancelled=RuntimeError)
        monkeypatch.setitem(sys.modules, "engine", fake)
        TranscriptionWorker(TranscriptionParams.from_config("in.mp4", config)).run()
        for key in ("cancel_event", "on_status", "on_progress"):
            seen["transcribe"].pop(key)
        return seen

    original, again = run(cfg), run(reloaded)
    assert original == again
    t = again["transcribe"]
    assert (t["model_size"], t["language"], t["beam_size"], t["vad_filter"], t["denoise"],
            t["high_accuracy"], t["config"]) == ("medium", "en", 3, False, False, True, cfg)
    assert again["timing"] == {}           # chiamata storica, senza argomenti in più


# ── Lettura tollerante ────────────────────────────────────────────────────────

def test_minimal_file_gives_defaults(tmp_path):
    path = _write(tmp_path, {"format": CONFIG_FORMAT, "version": 1})
    assert load_config(path) == TranscriptionConfig()


def test_missing_fields_take_defaults_and_unknown_fields_are_ignored(tmp_path):
    data = {
        "format": CONFIG_FORMAT, "version": 1, "commento": "mio preset",
        "transcription": {"beam_size": 2, "colore": "rosso"},
        "vad": {"threshold": 0.3, "nuovo_parametro": 1},
        "futuro": {"x": 1},
    }
    cfg = load_config(_write(tmp_path, data))
    assert cfg.beam_size == 2 and cfg.vad.threshold == 0.3
    assert cfg.vad.speech_pad_ms == 100 and cfg.model_size == "large-v3"
    assert cfg.decoding == DecodingOptions() and cfg.readability == ReadabilityLimits()


def test_null_section_means_defaults():
    data = {"format": CONFIG_FORMAT, "version": 1, "decoding": None}
    assert TranscriptionConfig.from_dict(data).decoding == DecodingOptions()


def test_value_normalisation():
    cfg = TranscriptionConfig.from_dict({
        "format": CONFIG_FORMAT, "version": 1,
        "transcription": {"language": " EN ", "beam_size": 4.0},
        "decoding": {"temperature": 0, "no_speech_threshold": 1,
                     "initial_prompts": {"IT": "b", "de": "a"}},
    })
    assert cfg.language == "en" and cfg.beam_size == 4
    assert cfg.decoding.temperature == (0.0,)
    assert cfg.decoding.no_speech_threshold == 1.0
    assert cfg.decoding.initial_prompts == (("de", "a"), ("it", "b"))   # forma canonica
    for raw in ("auto", "AUTO", "", None):
        c = TranscriptionConfig(language=raw)
        assert c.language == "auto" and c.whisper_language is None


def test_prompt_for():
    d = DecodingOptions(initial_prompts={"it": "ciao", "en": ""})
    assert d.prompt_for("it") == "ciao"
    assert d.prompt_for("en") is None        # vuoto = nessun prompt
    assert d.prompt_for("fr") is None
    assert d.prompt_for(None) is None        # rilevamento automatico


def test_config_is_frozen_hashable_and_replace_validates():
    cfg = TranscriptionConfig()
    with pytest.raises(Exception):
        cfg.beam_size = 3  # type: ignore[misc]
    assert hash(cfg) == hash(TranscriptionConfig())
    assert replace(cfg, beam_size=7).beam_size == 7
    with pytest.raises(ValueError, match="beam_size"):
        replace(cfg, beam_size=99)


# ── Validazione ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("section, key, value", [
    ("transcription", "beam_size", 0),
    ("transcription", "beam_size", 16),
    ("transcription", "beam_size", 2.5),
    ("transcription", "beam_size", "5"),
    ("transcription", "beam_size", True),
    ("transcription", "vad_filter", "sì"),
    ("transcription", "vad_filter", 1),
    ("transcription", "denoise", None),
    ("transcription", "high_accuracy", 0),
    ("transcription", "language", "italiano"),
    ("transcription", "language", 5),
    ("transcription", "model_size", ""),
    ("transcription", "model_size", "../modello"),
    ("transcription", "model_size", 3),
    ("decoding", "temperature", []),
    ("decoding", "temperature", [0.0, 1.5]),
    ("decoding", "temperature", "0.2"),
    ("decoding", "temperature", [True]),
    ("decoding", "temperature", [0.1] * 11),
    ("decoding", "no_speech_threshold", 1.5),
    ("decoding", "no_speech_threshold", float("nan")),
    ("decoding", "no_speech_threshold", 10 ** 400),
    ("decoding", "log_prob_threshold", 1.0),
    ("decoding", "compression_ratio_threshold", 0.5),
    ("decoding", "patience", 0),
    ("decoding", "condition_on_previous_text", "no"),
    ("decoding", "initial_prompts", "testo"),
    ("decoding", "initial_prompts", {"italiano": "x"}),
    ("decoding", "initial_prompts", {"it": 5}),
    ("decoding", "initial_prompts", {"it": "x" * 2001}),
    ("vad", "threshold", 0),
    ("vad", "threshold", 1),
    ("vad", "min_silence_duration_ms", -1),
    ("vad", "speech_pad_ms", 1.5),
    ("readability", "max_chars_per_line", 5),
    ("readability", "max_cps", 100),
    ("readability", "min_duration_s", 0),
    ("readability", "max_duration_s", float("inf")),
    ("readability", "max_lines", 4),
    ("readability", "min_gap_s", -0.1),
    ("readability", "keep_low_confidence_words", "sì"),
    ("decoding", "glossary", "machine learning, deploy"),
    ("decoding", "glossary", ["a, b"]),
    ("decoding", "glossary", [1]),
    ("decoding", "glossary", ["x" * 101]),
    ("decoding", "glossary", ["t"] * 101),
])
def test_invalid_values_are_rejected_with_field_path(section, key, value):
    data = {"format": CONFIG_FORMAT, "version": 1, section: {key: value}}
    with pytest.raises(ValueError) as exc:
        TranscriptionConfig.from_dict(data)
    msg = str(exc.value)
    assert f"'{section}.{key}" in msg and "non valido" in msg.lower()


def test_cross_field_rules():
    with pytest.raises(ValueError, match="warn_cps"):
        ReadabilityLimits(max_cps=15.0, warn_cps=16.0)
    with pytest.raises(ValueError, match="min_duration_s"):
        ReadabilityLimits(min_duration_s=3.0, max_duration_s=3.0)


def test_section_with_wrong_type_is_rejected():
    with pytest.raises(ValueError, match="sezione \"vad\""):
        TranscriptionConfig.from_dict({"format": CONFIG_FORMAT, "version": 1, "vad": [1, 2]})


# ── File corrotti, formato sbagliato, versione futura ─────────────────────────

@pytest.mark.parametrize("data, needle", [
    ([1, 2, 3], "oggetto JSON"),
    ({"version": 1}, "non è una configurazione"),
    ({"format": "altro", "version": 1}, "non è una configurazione"),
    ({"format": CONFIG_FORMAT}, "version"),
    ({"format": CONFIG_FORMAT, "version": 0}, "version"),
    ({"format": CONFIG_FORMAT, "version": "1"}, "version"),
    ({"format": CONFIG_FORMAT, "version": True}, "version"),
    ({"format": CONFIG_FORMAT, "version": CONFIG_VERSION + 1}, "più recente"),
])
def test_bad_header_is_rejected(tmp_path, data, needle):
    with pytest.raises(ValueError, match=needle):
        load_config(_write(tmp_path, data))


def test_v2srt_project_is_not_a_config(tmp_path):
    data = {"version": 1, "source_path": "", "subtitles": []}
    with pytest.raises(ValueError, match="non è una configurazione"):
        load_config(_write(tmp_path, data, "progetto.v2srt"))


@pytest.mark.parametrize("raw, needle", [
    (b"", "JSON malformato"),
    (b"{\"format\": \"videosrt-config\", ", "JSON malformato"),
    (b"\xff\xfe\x00\x01binario", "UTF-8"),
    (b"[" * 100000 + b"]" * 100000, "annidata"),
])
def test_corrupted_files_raise_italian_value_error(tmp_path, raw, needle):
    p = tmp_path / "rotto.vsrtconfig"
    p.write_bytes(raw)
    with pytest.raises(ValueError, match=needle):
        load_config(str(p))


def test_missing_file_and_directory_raise_value_error(tmp_path):
    with pytest.raises(ValueError, match="Impossibile leggere"):
        load_config(str(tmp_path / "manca.vsrtconfig"))
    with pytest.raises(ValueError, match="Impossibile leggere"):
        load_config(str(tmp_path))


def test_too_big_file_is_refused(tmp_path):
    p = tmp_path / "video.mp4"
    p.write_bytes(b"\0" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="troppo grande"):
        load_config(str(p))


# ── Motore: run_pipeline ──────────────────────────────────────────────────────

def test_run_pipeline_passes_config_and_wraps_srt(monkeypatch, tmp_path):
    seen = {}

    def fake_transcribe(path, **kw):
        seen.update(kw)
        return [{"start": 0.0, "end": 9.0, "text": "uno due tre quattro cinque sei sette otto"}]

    monkeypatch.setattr(engine, "transcribe", fake_transcribe)
    cfg = replace(_custom_config(), readability=ReadabilityLimits(max_chars_per_line=20))
    out = engine.run_pipeline("in.mp4", str(tmp_path / "out.srt"), config=cfg)
    assert seen["config"] is cfg
    text = open(out, encoding="utf-8").read()
    assert "\n" in text.split("\n\n")[0].split("\n", 2)[2]   # testo a capo su due righe


# ── Worker ────────────────────────────────────────────────────────────────────

def test_params_accept_config_object_dict_or_none():
    cfg = _custom_config()
    assert TranscriptionParams(input_path="a", config=cfg).config is cfg
    assert TranscriptionParams.from_dict({"input_path": "a", "config": cfg.to_dict()}).config == cfg
    assert TranscriptionParams(input_path="a", config=None).config == TranscriptionConfig()
    with pytest.raises(ValueError, match="config"):
        TranscriptionParams(input_path="a", config="x")  # type: ignore[arg-type]


def test_params_from_config():
    p = TranscriptionParams.from_config("a.mp4", _custom_config())
    assert (p.model_size, p.language, p.vad_filter, p.high_accuracy, p.beam_size,
            p.denoise) == ("medium", "en", False, True, 3, False)
    auto = TranscriptionParams.from_config("a.mp4", TranscriptionConfig(language="auto"))
    assert auto.language is None


def test_worker_default_config_keeps_historic_timing_call(monkeypatch):
    calls = []

    def strict_timing(segs):                 # stessa firma della chiamata storica
        calls.append(segs)
        return segs

    fake = types.SimpleNamespace(
        transcribe=lambda **kw: [{"start": 0.0, "end": 1.0, "text": "x"}],
        post_process_timing=strict_timing, TranscriptionCancelled=RuntimeError,
    )
    monkeypatch.setitem(sys.modules, "engine", fake)
    w = TranscriptionWorker({"input_path": "a.mp4"})
    failed = []
    w.failed.connect(failed.append)
    w.run()
    assert calls and not failed


# ── Editor ed esportazione: limiti attivi ─────────────────────────────────────

@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_table_model_follows_active_limits(qapp):
    from core.subtitle_table_model import (
        COL_CPS, ISSUE_TOO_FAST, ISSUE_TOO_SHORT, SubtitleTableModel,
    )
    # 30 caratteri in 2 s = 15 CPS; 0.6 s di durata
    m = SubtitleTableModel([Subtitle(0.0, 2.0, "x" * 30), Subtitle(3.0, 3.6, "ok")])
    assert m.row_issue_codes(0) == [] and m.row_issue_codes(1) == []
    assert m.data(m.index(0, COL_CPS), Qt.ForegroundRole) is None

    changed = []
    m.dataChanged.connect(lambda top, bot, roles: changed.append((top.row(), bot.row())))
    set_active_readability(ReadabilityLimits(max_cps=14.0, warn_cps=10.0, min_duration_s=1.0))
    m.refresh_checks()
    assert changed == [(0, 1)]
    assert m.row_issue_codes(0) == [ISSUE_TOO_FAST]
    assert m.row_issue_codes(1) == [ISSUE_TOO_SHORT]
    assert m.row_issues(0) == ["Troppo veloce (15.0 CPS, max 14)"]
    assert m.row_issues(1) == ["Durata troppo breve (0.60s < 1s)"]
    assert m.data(m.index(0, COL_CPS), Qt.ForegroundRole) is not None


def test_issue_word_and_wrap_follow_active_limits():
    from core.srt_io import subtitles_to_srt, wrap_subtitle_text
    from ui.subtitle_timeline import issue_word
    text = "uno due tre quattro cinque sei sette"     # 35 caratteri
    assert wrap_subtitle_text(text) == text
    assert issue_word([], cps=12.0) is None
    set_active_readability(ReadabilityLimits(max_chars_per_line=20, warn_cps=11.0))
    assert wrap_subtitle_text(text) == "uno due tre quattro\ncinque sei sette"
    assert wrap_subtitle_text(text, max_chars=42) == text     # argomento esplicito
    assert issue_word([], cps=12.0) == ("veloce", "warn")
    assert "quattro\ncinque" in subtitles_to_srt([Subtitle(0.0, 3.0, text)])
    assert active_readability().max_chars_per_line == 20


# ── Preferenze (QSettings) ────────────────────────────────────────────────────

class _FakeSettings:
    """QSettings in memoria (le preferenze reali dell'utente restano intatte)."""

    store: dict = {}

    def __init__(self, *_a, **_k):
        pass

    def value(self, key, default=None, type=None):  # noqa: A002
        return self.store.get(key, default)

    def setValue(self, key, value):  # noqa: N802
        self.store[key] = value

    def remove(self, key):
        self.store.pop(key, None)


def test_prefs_roundtrip_and_bad_values():
    from ui.prefs import CONFIG_KEY, read_config, write_config
    s = _FakeSettings()
    s.store = {}
    assert read_config(s) == (TranscriptionConfig(), "")
    write_config(s, _custom_config(), "podcast")
    assert read_config(s) == (_custom_config(), "podcast")
    future = dict(TranscriptionConfig().to_dict(), version=CONFIG_VERSION + 1)
    for bad in ("{rotto", json.dumps(future), 42, ["a"]):
        s.store[CONFIG_KEY] = bad
        assert read_config(s) == (TranscriptionConfig(), "")


# ── Schermata iniziale e menu File ────────────────────────────────────────────

@pytest.fixture
def ui_env(qapp, monkeypatch, tmp_path):
    """Nessuna preferenza reale, cache in tmp, nessun dialog modale."""
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(platform_support, "app_cache_dir", lambda: cache)
    monkeypatch.setattr(platform_support, "legacy_cache_dirs", lambda: [])
    _FakeSettings.store = {}
    import ui.home_widget as hw
    import ui.main_window as mw
    import ui.project_widget as pwm
    import ui.workspace as wsm
    for mod in (hw, mw, pwm, wsm):
        monkeypatch.setattr(mod, "QSettings", _FakeSettings)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a) or 0)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: warnings.append(a) or 0)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: 0)
    return SimpleNamespace(warnings=warnings, store=_FakeSettings.store)


@pytest.fixture
def window(ui_env):
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    yield win
    for pw in win._projects:
        pw.teardown()
        pw._export_panel.close()
    win.deleteLater()


def test_home_defaults_and_settings_keys_unchanged(ui_env):
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    assert home.current_config() == TranscriptionConfig()
    assert home._config_lbl.full_text() == "Parametri predefiniti"
    assert home._get_settings() == {"model_size": "large-v3", "language": "it",
                                    "vad_filter": True, "denoise": True,
                                    "high_accuracy": False, "beam_size": 5}


def test_home_glossary_field(ui_env, tmp_path):
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    assert home.glossary_edit.text() == ", ".join(DEFAULT_GLOSSARY)
    home.glossary_edit.setText("Kubernetes,  PyTorch , ,Kubernetes")
    assert home.current_config().decoding.glossary == ("Kubernetes", "PyTorch")
    # glossario non valido: la trascrizione non parte e il motivo è visibile
    got = []
    home.start_requested.connect(lambda p, s: got.append(p))
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x" * 10)
    home._on_file_selected(str(clip))
    home.glossary_edit.setText("x" * 150)
    home._on_start()
    assert not got and "Glossario non valido" in home._hint_lbl.text()
    home.glossary_edit.setText("")
    home._on_start()
    assert got == [str(clip)]


def test_home_apply_config_shows_values_and_roundtrips(ui_env, monkeypatch):
    monkeypatch.setattr(engine, "high_accuracy_unavailable_reason", lambda: "")
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    cfg = _custom_config()
    home.apply_config(cfg, "podcast")
    assert home.model_combo.currentData() == "medium"
    assert home.lang_combo.currentData() == "en"
    assert not home.vad_toggle.isChecked() and home.accuracy_toggle.isChecked()
    assert home.beam_spin.value() == 3
    assert home.glossary_edit.text() == "Kubernetes, PyTorch, Mario Rossi"
    assert home._config_lbl.full_text() == "Configurazione: podcast"
    assert "Inglese" in home._preset_lbl.full_text()
    assert home.current_config() == cfg
    assert home._get_settings()["denoise"] is False


def test_home_keeps_high_accuracy_intent_when_unavailable(ui_env, monkeypatch):
    monkeypatch.setattr(engine, "high_accuracy_unavailable_reason", lambda: "manca WhisperX")
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    home.apply_config(_custom_config())
    assert not home.accuracy_toggle.isChecked()
    assert home._get_settings()["high_accuracy"] is False     # si trascrive in standard
    assert home.current_config().high_accuracy is True         # ma l'export la conserva


def test_home_unknown_language_is_added_unknown_model_refused(ui_env):
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    home.apply_config(TranscriptionConfig(language="pt"))
    assert home.lang_combo.currentData() == "pt"
    assert home.current_config().language == "pt"
    before = home.current_config()
    with pytest.raises(ValueError, match="non è disponibile"):
        home.apply_config(TranscriptionConfig(model_size="distil-large-v3"), "x")
    assert home.current_config() == before and home.config_name() == ""


def test_home_config_label_uses_theme_tokens(ui_env):
    from ui import theme
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    original = theme.get_theme()
    try:
        for name in ("light", "dark"):
            theme.set_theme(name)
            theme.MANAGER.theme_changed.emit(name)
            assert theme.c("dim") in home._config_lbl.styleSheet()
            assert theme.c("line") in home.glossary_edit.styleSheet()
    finally:
        theme.set_theme(original)
        theme.MANAGER.theme_changed.emit(original)


def _file_menu_texts(win) -> list:
    menu = win.menuBar().actions()[0].menu()
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_file_menu_has_config_actions(window):
    texts = _file_menu_texts(window)
    for label in ("Importa configurazione…", "Esporta configurazione…", "Ripristina predefiniti"):
        assert label in texts
    assert texts.index("Ripristina predefiniti") < texts.index("Esci")


def test_import_applies_to_all_projects_and_is_remembered(window, ui_env, tmp_path):
    from ui.prefs import CONFIG_NAME_KEY, read_config
    window._new_project()
    path = str(tmp_path / "Podcast tecnico.vsrtconfig")
    save_config(_custom_config(), path)
    assert window.import_config_file(path) is True
    for pw in window._projects:
        assert pw.home.model_combo.currentData() == "medium"
        assert pw.home.current_config().decoding == _custom_config().decoding
        assert pw.home.config_name() == "Podcast tecnico"
    assert read_config(_FakeSettings())[0].readability == _custom_config().readability
    assert ui_env.store[CONFIG_NAME_KEY] == "Podcast tecnico"
    assert active_readability().max_cps == 15.0
    assert "Podcast tecnico" in window.status_main.text()
    # un nuovo progetto parte dall'ultima configurazione
    window._new_project()
    assert window._projects[-1].home.config_name() == "Podcast tecnico"
    assert window._projects[-1].home.beam_spin.value() == 3


def test_import_invalid_file_warns_and_changes_nothing(window, ui_env, tmp_path):
    bad = tmp_path / "rotto.vsrtconfig"
    bad.write_text("{non json", encoding="utf-8")
    future = _write(tmp_path, dict(TranscriptionConfig().to_dict(), version=99), "nuovo.vsrtconfig")
    unknown_model = _write(tmp_path, dict(TranscriptionConfig().to_dict(),
                                          transcription={"model_size": "enorme"}), "m.vsrtconfig")
    for path in (str(bad), future, unknown_model):
        assert window.import_config_file(path) is False
    assert len(ui_env.warnings) == 3
    assert "più recente" in ui_env.warnings[1][2]
    assert window._active().home.current_config() == TranscriptionConfig()
    assert ui_env.store == {} or "transcription_config" not in ui_env.store


def test_export_writes_current_home_config(window, ui_env, tmp_path):
    home = window._active().home
    home.apply_config(_custom_config(), "mio")
    home.beam_spin.setValue(9)
    written = window.export_config_file(str(tmp_path / "uscita"))     # estensione aggiunta
    assert written.endswith(".vsrtconfig")
    assert load_config(written) == replace(_custom_config(), beam_size=9,
                                           high_accuracy=home.current_config().high_accuracy)
    assert "uscita.vsrtconfig" in window.status_main.text()


def test_export_failure_shows_error(window, ui_env, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert window.export_config_file(str(blocker / "dentro.vsrtconfig")) is None
    assert ui_env.warnings


def test_reset_restores_defaults_after_confirmation(window, ui_env, tmp_path, monkeypatch):
    window._apply_config_everywhere(_custom_config(), "podcast")
    monkeypatch.setattr(window, "_confirm_reset_config", lambda: False)
    window._reset_config()
    assert window._active().home.config_name() == "podcast"
    monkeypatch.setattr(window, "_confirm_reset_config", lambda: True)
    window._reset_config()
    home = window._active().home
    assert home.current_config() == TranscriptionConfig() and home.config_name() == ""
    assert home._config_lbl.full_text() == "Parametri predefiniti"
    assert active_readability() == ReadabilityLimits()


def test_reset_with_defaults_does_not_ask(window, monkeypatch):
    def boom():
        raise AssertionError("conferma non necessaria")
    monkeypatch.setattr(window, "_confirm_reset_config", boom)
    window._reset_config()


def test_start_passes_config_to_worker_and_remembers_it(window, ui_env, monkeypatch, tmp_path):
    from ui.prefs import read_config
    pw = window._active()
    pw.home.apply_config(_custom_config(), "podcast")
    pw.home.beam_spin.setValue(4)
    got = {}
    monkeypatch.setattr(pw.progress, "start",
                        lambda path, settings, config=None: got.update(config=config))
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x" * 10)
    pw.home._on_file_selected(str(clip))
    pw.home._on_start()
    assert got["config"] == replace(pw.home.current_config(), beam_size=4)
    assert read_config(_FakeSettings()) == (got["config"], "podcast")


def test_saved_config_restored_at_startup(ui_env, qapp):
    from ui.main_window import MainWindow
    from ui.prefs import write_config
    write_config(_FakeSettings(), _custom_config(), "podcast")
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    try:
        assert win._active().home.current_config().decoding == _custom_config().decoding
        assert win._active().home.config_name() == "podcast"
        assert math.isclose(active_readability().max_cps, 15.0)
    finally:
        for pw in win._projects:
            pw.teardown()
            pw._export_panel.close()
        win.deleteLater()

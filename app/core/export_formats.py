"""
export_formats.py — I formati in cui si esportano i sottotitoli, in un posto solo.

Li usano la finestra Esporta (⌘S), la tab Esportazione e il menu dell'editor: stessa
etichetta, stesso filtro dei file e stessa scrittura (atomica, ``core.srt_io``) ovunque.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from core.srt_io import write_ass, write_srt, write_txt, write_vtt
from core.subtitle_model import Subtitle, SubtitleProject
from core.v2srt_io import EXTENSION as V2SRT_EXT, save_project


@dataclass(frozen=True)
class ExportFormat:
    ext: str
    label: str         # voce del menu a tendina della finestra Esporta
    file_filter: str   # filtro del dialog di salvataggio
    hint: str          # riga di spiegazione sotto il menu

    @property
    def is_project(self) -> bool:
        return self.ext == V2SRT_EXT


FORMATS = (
    ExportFormat(".srt", "SRT — SubRip", "SubRip SRT (*.srt)",
                 "Compatibile con tutti i player e piattaforme."),
    ExportFormat(".vtt", "VTT — WebVTT", "WebVTT (*.vtt)",
                 "Per il web, YouTube, HTML5 video."),
    ExportFormat(".txt", "TXT — Testo semplice", "Testo semplice (*.txt)",
                 "Solo testo, senza timing."),
    ExportFormat(".ass", "ASS — Advanced Sub", "Advanced SubStation Alpha (*.ass)",
                 "Styling avanzato per video amatoriali/anime."),
    ExportFormat(V2SRT_EXT, "V2SRT — Progetto", "Progetto V2SRT (*.v2srt)",
                 "Progetto Video→SRT: riapri per continuare a editare."),
)
BY_EXT: Dict[str, ExportFormat] = {f.ext: f for f in FORMATS}


def with_ext(path: str, ext: str) -> str:
    """``path`` con l'estensione ``ext`` (aggiunta se manca, maiuscole comprese)."""
    return path if path.lower().endswith(ext) else path + ext


def write(subtitles: List[Subtitle], path: str, ext: str, source_path: str = "",
          project: Optional[SubtitleProject] = None) -> None:
    """Scrive ``subtitles`` in ``path`` nel formato ``ext``.

    Il titolo dentro l'ASS è il nome del video (``source_path``), altrimenti quello del
    file. Il progetto .v2srt salva ``project`` con questi sottotitoli (o un progetto nuovo
    sul video ``source_path``).
    """
    if ext == ".srt":
        write_srt(subtitles, path)
    elif ext == ".vtt":
        write_vtt(subtitles, path)
    elif ext == ".txt":
        write_txt(subtitles, path)
    elif ext == ".ass":
        write_ass(subtitles, path, title=Path(source_path or path).stem)
    elif ext == V2SRT_EXT:
        if project is None:
            project = SubtitleProject(source_path=source_path)
        project.subtitles = list(subtitles)
        save_project(project, path)
    else:
        raise ValueError(f"Formato di esportazione sconosciuto: {ext}")

#!/usr/bin/env python3
"""
check_bundle.py — Controlla che l'app macOS non dipenda da librerie fuori dal bundle.

Sul Mac della build ffmpeg, Qt & co. trovano le librerie di Homebrew (/opt/homebrew,
/usr/local): l'app parte. Su un Mac pulito no. Questo script legge con ``otool -L`` ogni
file Mach-O dentro ``.app`` e segnala i riferimenti assoluti a librerie che non sono del
sistema (/System, /usr/lib). Codice di uscita 1 se ne trova.

Uso (dalla root del repo):
    python3 packaging/macos/check_bundle.py [dist/Video-to-SRT.app]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict, List

_MACHO_MAGIC = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",      # 32 bit
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",      # 64 bit
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",      # universale
}
_SYSTEM_PREFIXES = ("/System/", "/usr/lib/")


def is_macho(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) in _MACHO_MAGIC
    except OSError:
        return False


def external_deps(otool_output: str) -> List[str]:
    """Librerie con percorso assoluto fuori dal sistema, dall'output di ``otool -L``."""
    deps = []
    for line in otool_output.splitlines()[1:]:
        lib = line.strip().split(" (compatibility", 1)[0].strip()
        if lib.startswith("/") and not lib.startswith(_SYSTEM_PREFIXES):
            deps.append(lib)
    return deps


def scan(app: Path) -> Dict[str, List[str]]:
    problems: Dict[str, List[str]] = {}
    for f in sorted(app.rglob("*")):
        if not f.is_file() or f.is_symlink() or not is_macho(f):
            continue
        out = subprocess.run(["otool", "-L", str(f)], capture_output=True, text=True).stdout
        deps = external_deps(out)
        if deps:
            problems[str(f.relative_to(app))] = deps
    return problems


def main(argv: List[str]) -> int:
    app = Path(argv[1]) if len(argv) > 1 else (
        Path(__file__).resolve().parents[2] / "dist" / "Video-to-SRT.app")
    if not app.is_dir():
        print(f"❌  App non trovata: {app}")
        return 1
    problems = scan(app)
    if not problems:
        print(f"✅  {app.name}: nessuna libreria fuori dal bundle")
        return 0
    print(f"❌  {app.name}: librerie caricate da fuori (su un Mac pulito mancano):")
    for name, deps in problems.items():
        print(f"   {name}")
        for d in deps:
            print(f"      → {d}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

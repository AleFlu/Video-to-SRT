#!/usr/bin/env python3
"""
check_bundle.py — Controlla che l'app macOS non dipenda da librerie fuori dal bundle.

Sul Mac della build ffmpeg, Qt & co. trovano le librerie di Homebrew (/opt/homebrew,
/usr/local): l'app parte. Su un Mac pulito no. Questo script legge con ``otool -L`` ogni
file Mach-O dentro ``.app`` e segnala i riferimenti assoluti a librerie che non sono del
sistema (/System, /usr/lib) e quelli relativi (``@rpath``, ``@loader_path``,
``@executable_path``) che non portano a un file del bundle. Codice di uscita 1 se ne trova.

Uso (dalla root del repo):
    python3 packaging/macos/check_bundle.py [dist/Video-to-SRT.app]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

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


def dependencies(otool_output: str, own_id: str = "") -> List[str]:
    """Tutte le librerie dall'output di ``otool -L`` (esclusa l'identità della libreria)."""
    deps = []
    for line in otool_output.splitlines()[1:]:
        lib = line.strip().split(" (compatibility", 1)[0].strip()
        if lib and lib != own_id:
            deps.append(lib)
    return deps


def rpaths(otool_l_output: str) -> List[str]:
    """Percorsi LC_RPATH dall'output di ``otool -l``."""
    out, in_rpath = [], False
    for line in otool_l_output.splitlines():
        line = line.strip()
        if line.startswith("cmd "):
            in_rpath = line == "cmd LC_RPATH"
        elif in_rpath and line.startswith("path "):
            out.append(line[5:].split(" (offset", 1)[0].strip())
    return out


def resolve(dep: str, origin: Path, rpath_list: List[str],
            executable_dir: Path) -> Optional[Path]:
    """File a cui punta ``dep`` caricato da ``origin`` (None se non esiste)."""
    def expand(p: str) -> Path:
        return Path(p.replace("@loader_path", str(origin.parent))
                    .replace("@executable_path", str(executable_dir)))
    if dep.startswith("@rpath/"):
        rest = dep[len("@rpath/"):]
        for r in rpath_list:
            candidate = expand(r) / rest
            if candidate.exists():
                return candidate
        return None
    candidate = expand(dep)
    return candidate if candidate.exists() else None


def _own_id(f: Path) -> str:
    out = subprocess.run(["otool", "-D", str(f)], capture_output=True, text=True).stdout
    lines = out.strip().splitlines()
    return lines[1].strip() if len(lines) > 1 else ""


def scan(app: Path) -> Dict[str, List[str]]:
    """Problemi per file: librerie caricate da fuori dal bundle e librerie relative
    (``@rpath``, ``@loader_path``) che nel bundle non ci sono."""
    problems: Dict[str, List[str]] = {}
    exe_dir = app / "Contents" / "MacOS"
    for f in sorted(app.rglob("*")):
        if not f.is_file() or f.is_symlink() or not is_macho(f):
            continue
        out = subprocess.run(["otool", "-L", str(f)], capture_output=True, text=True).stdout
        found = list(external_deps(out))
        rel = [d for d in dependencies(out, _own_id(f)) if d.startswith("@")]
        if rel:
            load = subprocess.run(["otool", "-l", str(f)], capture_output=True,
                                  text=True).stdout
            rp = rpaths(load)
            found += [f"{d} (non trovata nel bundle)" for d in rel
                      if resolve(d, f, rp, exe_dir) is None]
        if found:
            problems[str(f.relative_to(app))] = found
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

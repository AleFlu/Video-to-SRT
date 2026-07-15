# -*- mode: python ; coding: utf-8 -*-
import shutil

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all

# Il modello Whisper va scaricato in _build_model/ prima della build
# (vedi README.md); ffmpeg viene preso dal PATH di sistema.
datas = [('engine.py', '.'), ('_build_model', 'whisper_model')]
binaries = [(shutil.which('ffmpeg'), '.')]
hiddenimports = ['faster_whisper', 'ctranslate2', 'huggingface_hub', 'tokenizers', 'numpy', 'av', 'customtkinter', 'tkinterdnd2']
datas += collect_data_files('faster_whisper')
for pkg in ('onnxruntime', 'ctranslate2', 'customtkinter', 'tkinterdnd2'):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyi_rth_threads.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Video-to-SRT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Video-to-SRT',
)
app = BUNDLE(
    coll,
    name='Video-to-SRT.app',
    icon=None,
    bundle_identifier=None,
)

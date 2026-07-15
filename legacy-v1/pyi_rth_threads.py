"""
pyi_rth_threads.py — PyInstaller runtime hook
Questo file viene eseguito da PyInstaller PRIMA di qualsiasi
import dell'applicazione. Setta le variabili d'ambiente per
il threading CPU in modo che CTranslate2 e onnxruntime usino
tutti i core disponibili.
"""
import os

cpu_count = os.cpu_count() or 4
t = str(cpu_count)

os.environ.setdefault("OMP_NUM_THREADS", t)
os.environ.setdefault("MKL_NUM_THREADS", t)
os.environ.setdefault("CT2_NUM_THREADS", t)
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")

# CTranslate2: forza il backend CPU ottimizzato
os.environ.setdefault("CT2_VERBOSE", "1")  # Debug: mostra quale backend usa
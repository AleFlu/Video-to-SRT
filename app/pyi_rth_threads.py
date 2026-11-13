"""
pyi_rth_threads.py — PyInstaller runtime hook.
Setta env CPU threading PRIMA di qualsiasi import dell'app.
"""
import os

cpu_count = os.cpu_count() or 4
t = str(cpu_count)

os.environ.setdefault("OMP_NUM_THREADS", t)
os.environ.setdefault("MKL_NUM_THREADS", t)
os.environ.setdefault("CT2_NUM_THREADS", t)
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")

os.environ.setdefault("CT2_VERBOSE", "1")

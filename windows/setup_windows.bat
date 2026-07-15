@echo off
REM setup_windows.bat — Setup ambiente dev su Windows
REM Uso: setup_windows.bat [--run]
REM   --run : avvia l'app dopo il setup
REM
REM Requisiti:
REM   - Python 3.10+ (64-bit) installato e nel PATH
REM   - ffmpeg.exe nel PATH oppure nella stessa cartella

setlocal EnableDelayedExpansion

REM ── Verifica Python ──────────────────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Python non trovato nel PATH.
    echo Scarica Python 3.10+ da https://www.python.org/downloads/
    echo Assicurati di spuntare "Add Python to PATH" durante l'installazione.
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [INFO] %PYVER%

REM ── Crea venv ─────────────────────────────────────────────────────────────────
if not exist "venv\" (
    echo [INFO] Creazione ambiente virtuale...
    python -m venv venv
    if errorlevel 1 (
        echo [ERRORE] Impossibile creare il venv.
        exit /b 1
    )
)

REM ── Attiva venv ───────────────────────────────────────────────────────────────
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERRORE] Impossibile attivare il venv.
    exit /b 1
)

REM ── Aggiorna pip ─────────────────────────────────────────────────────────────
echo [INFO] Aggiornamento pip...
python -m pip install --upgrade pip --quiet

REM ── Installa dipendenze ───────────────────────────────────────────────────────
echo [INFO] Installazione dipendenze (può richiedere alcuni minuti)...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERRORE] Installazione dipendenze fallita.
    echo Verifica connessione internet e versione Python.
    exit /b 1
)

REM ── Verifica ffmpeg ───────────────────────────────────────────────────────────
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [AVVISO] ffmpeg non trovato nel PATH.
    echo Per la trascrizione e' necessario ffmpeg.
    echo Scarica da: https://www.gyan.dev/ffmpeg/builds/
    echo Poi metti ffmpeg.exe nel PATH oppure nella cartella windows\
    echo.
) else (
    for /f "tokens=*" %%i in ('ffmpeg -version 2^>^&1 ^| findstr /i "ffmpeg version"') do (
        echo [INFO] %%i
        goto :ffmpeg_ok
    )
    :ffmpeg_ok
)

REM ── Download modello Whisper ──────────────────────────────────────────────────
echo [INFO] Verifica modello Whisper large-v3...
python -c "from faster_whisper import WhisperModel; print('[INFO] Download modello large-v3 (prima esecuzione, ~3 GB)...'); WhisperModel('large-v3', device='cpu', compute_type='int8'); print('[INFO] Modello pronto.')" 2>&1
if errorlevel 1 (
    echo [AVVISO] Download modello fallito o gia' presente.
    echo Il modello verra' scaricato al primo avvio dell'app.
)

echo.
echo [OK] Setup completato.
echo.

REM ── Avvio opzionale ───────────────────────────────────────────────────────────
if "%1"=="--run" (
    echo [INFO] Avvio applicazione...
    python main.py
)

endlocal

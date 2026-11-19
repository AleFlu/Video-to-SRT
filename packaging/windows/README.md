# Video → SRT — Windows

## System requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 64-bit | Windows 11 64-bit |
| Python | 3.10 x64 | 3.11 x64 |
| RAM | 8 GB | 16 GB |
| Disk | 5 GB free (app, dependencies and the chosen model) | SSD |
| GPU | — | NVIDIA with CUDA 11.8+ (faster transcription) |

## Setup and run (development)

1. **Python 3.10+ (64-bit)** from https://www.python.org/downloads/ — tick *Add Python to PATH*.
2. **FFmpeg**, one of:
   ```powershell
   scoop install ffmpeg
   ```
   ```powershell
   choco install ffmpeg
   ```
   or download the `essentials` build from https://www.gyan.dev/ffmpeg/builds/ and add
   `ffmpeg.exe` to `PATH`.
3. From the repository root:
   ```bat
   packaging\windows\setup_windows.bat --run
   ```
   This creates `.venv\` at the repository root, installs `app\requirements.txt` and starts the
   app. The app recommends a Whisper model for the computer and downloads it at the first
   transcription (once).

Later runs:

```bat
.venv\Scripts\activate
python app\main.py
```

## Build the .exe

From the repository root:

```bat
.venv\Scripts\activate
pip install pyinstaller
python packaging\windows\build_windows.py
```

Output: `dist\VideoSRT\VideoSRT.exe`. The build uses `app\assets\app.ico` if present and
bundles `ffmpeg.exe` if it is in `PATH` or in `packaging\windows\`.

Single-file build (slower to start):

```bat
python packaging\windows\build_windows.py --onefile
```

PyInstaller executables sometimes trigger antivirus false positives; if so, add `dist\` to the
exclusions.

## Differences from macOS

| | macOS | Windows |
|---|---|---|
| Full screen | ⌃⌘F | F11 |
| Shortcut modifier | ⌘ | Ctrl |
| Autosave and log folder | `~/Library/Caches/VideoSRT` | `%LOCALAPPDATA%\VideoSRT` |
| Video playback | AVFoundation | Media Foundation |
| Icon | `app.icns` | `app.ico` |
| Build | `.app` + `.dmg` | `.exe` |

Media Foundation plays MP4 (H.264/H.265), MP3, WAV, M4A, WMA and AAC natively. MKV, AVI, FLAC,
OGG and other formats still transcribe through FFmpeg; the player then shows the waveform only.

## Troubleshooting

Logs go to the console and to `%LOCALAPPDATA%\VideoSRT\videosrt.log`. To capture a crash:

```bat
python app\main.py > log.txt 2>&1
```

| Problem | Fix |
|---|---|
| `No module named 'ctranslate2'` | `pip install -r app\requirements.txt` |
| FFmpeg not found | install FFmpeg and add it to `PATH` |
| Video shows no picture | install the Windows media codecs or use an MP4 |
| Slow transcription | normal on CPU; with an NVIDIA GPU install CUDA 11.8+ |
| Antivirus blocks the .exe | add `dist\VideoSRT\` to the exclusions |

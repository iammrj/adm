# Apex Download Manager (ADM)

[![Build](https://github.com/iammrj/adm/actions/workflows/release.yml/badge.svg?branch=main)](https://github.com/iammrj/adm/actions/workflows/release.yml)
[![Latest Release](https://img.shields.io/github/v/release/iammrj/adm?display_name=tag&sort=semver)](https://github.com/iammrj/adm/releases)
[![License](https://img.shields.io/github/license/iammrj/adm)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)

ADM is a desktop download manager focused on fast segmented downloads, reliable queue recovery, and a clean modern UI.

Note: Internal package/module path remains `odm/` for now, while product branding is ADM.

## Features

- Download flow similar to IDM:
  - Add one URL or a list of URLs
  - Click `Analyze`
  - For single URL, choose quality/format from dropdown (best quality preselected)
  - Click `Download` to queue/start
- Dual download engine:
  - `yt-dlp` mode for stream/video platforms with format analysis
  - Segmented direct-download engine for normal file URLs (multi-connection with fallback)
- Queue and job controls:
  - Parallel queue processing
  - Pause/resume per job and globally
  - Clear completed jobs
  - Status tracking: queued, downloading, completed, failed, stopped
- Recovery and persistence:
  - SQLite-backed job store at `odm/internal/downloads.db`
  - Interrupted jobs recovered as `Stopped` on next launch
- Organized output handling:
  - Base download location is configurable
  - Auto category folders (Music, Video, Documents, Programs, Compressed)
  - Open download location directly from UI
- UI/UX:
  - Popup-style download dialog
  - Quality dropdown with compact labels and detailed selection hint
  - Sidebar filters include `Failed` and `Completed`
  - Dark/Light themes
  - Font family and font size controls
  - Main window opens centered at ~90% of screen

## Known Behavior

- Resume for segmented/direct jobs is queue/job-level restart behavior after app restart, not persisted byte-level resume from exact byte offsets.

## Tech Stack

- Python 3.12+
- PyQt6
- yt-dlp
- certifi
- imageio-ffmpeg (bundled ffmpeg runtime fallback)
- SQLite (built-in via Python `sqlite3`)

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Build Locally

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name ADM --icon assets/icons/adm.png --collect-all imageio_ffmpeg --add-data "odm/theme:odm/theme" --add-data "assets/icons:assets/icons" main.py
```

Output binary/app bundle is generated under `dist/`.

## CI/CD and Releases

GitHub Actions workflow: `.github/workflows/release.yml`

- Push to `main`:
  - Builds Windows, macOS, Linux artifacts in Actions
- Push tag `v*` (example `v1.0.0`):
  - Builds artifacts
  - Creates/updates a draft GitHub Release and uploads assets automatically

Assets generated:

- Windows: `.exe`, `.zip`
- macOS: `.dmg`, `.pkg`
- Linux: `.deb`, `.tar.gz`

Create a release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

## License

See [LICENSE](./LICENSE).

# Tingjian · Local

A Mac-first lecture and meeting companion with live bilingual captions, local AI notes, timestamped playback, recording Q&A, and Markdown/SRT/JSON export.

[English setup and usage tutorial](docs/QUICKSTART.md) · [中文说明](README.zh-CN.md) · [千问配置说明](实时API配置.md)

## Two caption modes

| Mode | Speech and translation | Notes and questions |
| --- | --- | --- |
| Qwen live captions | Streams microphone audio and glossary hints to Alibaba Cloud Model Studio; displays source and translated text incrementally | Your local language model |
| Local offline mode | MLX Whisper transcription and a local LiteRT-LM/MLX language model; microphone audio processed in 15-second batches | Your local language model |

Live mode uses `qwen3.8-livetranslate-flash-realtime`. Imported audio files always use the local processing workflow. The app has no analytics or external frontend assets and listens on `127.0.0.1:8765`.

## Quick start

Requires an Apple Silicon Mac, macOS, and [uv](https://docs.astral.sh/uv/). The environment uses Python 3.11. Model weights and credentials are not included.

1. Clone or download the repository and open its folder in Finder.
2. Double-click **初始化环境.command** (Initialize environment), or run `uv sync --locked --python 3.11` in the project directory.
3. For live captions, double-click **启动实时字幕.command**, enter your own Key at the hidden prompt, and configure its region and workspace in the page. For local transcription, first run **准备语音模型.command** and configure your local text model.
4. From then on, double-click **打开听笺.command** (Open Tingjian). It opens an existing service immediately; if stopped, it starts a mode using your local configuration.
5. In the page, choose a caption mode, create a recording, and click **开始录音** (Start recording). Allow microphone access. Stop recording and wait for the remaining captions before closing the page.

The interface currently uses Chinese labels. The [English tutorial](docs/QUICKSTART.md) explains every setup step and button, including model paths, API Host/workspace IDs, backup, troubleshooting, and development commands.

If the service is stopped, live mode asks for the Key again unless it is supplied through `DASHSCOPE_API_KEY` in the launch environment. Keys are not saved in application files. An existing compatible Foresight Gemma `.litertlm` file can be selected in place; you must supply your own model and comply with its terms.

## Features and limits

- Live bilingual microphone captions, including draft/final updates and provider speaker labels.
- Local recording storage, audio import, timestamped playback, and browser WAV backup.
- Course folders and search, local AI notes, and recording-grounded Q&A with time references.
- Markdown, bilingual SRT, and JSON export.
- Local import support for WAV, MP3, M4A, MP4, WebM, OGG, FLAC, AAC and AIFF; up to 500 MB / 3 hours per file.
- No translated speech playback, system-audio capture, or slide/PDF ingestion in this version. Live captions require a working internet connection and paid API access; local inference requires compatible weights.

A short real-API test on 2026-10-16 used 7.47 seconds of synthetic English speech: after connection establishment, the first source caption appeared at about 2.27 seconds and the first translation at about 2.30 seconds. Final captions were saved after the stream drained. This is one first-caption measurement, not a continuous lecture latency guarantee.

## Privacy and repository contents

This repository contains source code, launchers, tests, dependency metadata and documentation. It excludes API Keys, personal workspace configuration, local model paths, model weights, recordings, databases, caches, screenshots and generated verification reports.

- `DASHSCOPE_API_KEY`: server process environment only; never returned to the browser.
- `data/`: private recordings, captions, notes, questions and cloud workspace settings; ignored by Git.
- `settings.json`: private local model paths; ignored by Git.
- `models/`, `.venv/`, `.cache/`: local dependencies and model artifacts; ignored by Git.

When live recording starts, microphone audio and the recording's glossary are sent to the selected Alibaba Cloud region. Provider data policies and fees apply. Local mode does not upload audio to Qwen. Existing recordings are not automatically uploaded.

## Development

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked --extra dev --python 3.11
.venv/bin/pytest -q
node --test tests/*.test.mjs
.venv/bin/ruff check app tests scripts
node --check web/app.js
```

Before publishing, inspect the staged files and run `.venv/bin/python scripts/audit_publish.py`. The audit checks the Git index for common private artifacts, personal paths, workspace identifiers and credential patterns without echoing matching values. It supplements manual review and an explicit file allowlist.

## Project layout

- `app/`: FastAPI service, SQLite storage, local model inference and Qwen stream handling.
- `web/`: browser interface, AudioWorklet recorder, WAV encoding and realtime client.
- `scripts/`: unified opener, API-mode launcher, speech model download, model smoke test and publication audit.
- `tests/`: API, recording, stream lifecycle, persistence, launcher and publication checks.
- `docs/QUICKSTART.md`: complete English tutorial.

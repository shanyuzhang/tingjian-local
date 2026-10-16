# English setup and usage tutorial

Tingjian runs a browser interface on your Mac. It can stream microphone audio to Qwen for live bilingual captions or process recordings locally with MLX Whisper and a local language model. Notes and recording questions use your local language model in both modes.

The interface currently uses Chinese labels. This tutorial gives the matching labels for each step.

## 1. Requirements

- An Apple Silicon Mac running macOS. The local model workflow was tested on an M5 Pro with 48 GB of unified memory; this is a test machine, not a universal minimum requirement.
- [uv](https://docs.astral.sh/uv/) to create the Python 3.11 environment and install dependencies. A global Python installation is not needed if uv can install Python.
- A browser with microphone and AudioWorklet support. If the embedded browser cannot record, use Safari or Chrome at `http://127.0.0.1:8765`.
- For live captions: an Alibaba Cloud Model Studio account, API Key, workspace ID, matching Beijing or Singapore region, model access, and available credit.
- For offline transcription: the speech model downloaded in step 3.
- For notes, questions, and offline translation: an existing compatible local `.litertlm` file or MLX language model directory. No text model is bundled or downloaded automatically.

Network access is needed to install dependencies and download the speech model. Live captions use a paid cloud API. Offline inference uses local weights and does not fall back to cloud inference.

## 2. Download and initialize

Clone this repository or download and extract its source archive. Keep the application folder in a stable location because recordings and settings are stored relative to it.

In Finder, double-click `初始化环境.command` (Initialize environment). Alternatively, open Terminal in the application folder and run:

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked --python 3.11
```

If uv is installed with Homebrew but is not on your Terminal PATH, use `/opt/homebrew/bin/uv` instead of `uv`. Initialization does not download model weights.

## 3. Choose your transcription mode

### Live Qwen captions

1. Open your Alibaba Cloud Model Studio console and choose Beijing or Singapore.
2. Create an API Key in the workspace you intend to use. Verify that `qwen3.8-livetranslate-flash-realtime` is available to that workspace.
3. Expand the workspace menu and copy the **Workspace ID** or **API Host**. For example, an API Host of `ws-example.cn-beijing.maas.aliyuncs.com` means the workspace ID is `ws-example`. Other prefixes, such as `llm-`, may be used; copy the actual value. Do not enter an API Key list's numeric row ID or the literal `{WorkspaceId}` placeholder.
4. Double-click `启动实时字幕.command` (Start live captions). Paste your Key at the hidden Terminal prompt and press Return. No characters appear while you paste; this is expected.
5. In the browser, click **配置千问 API** (Configure Qwen API). Select the matching **服务地域** (Region), enter **百炼业务空间 ID** (Workspace ID), and click **保存千问配置** (Save Qwen configuration).
6. Select **千问 · 实时双语字幕** (Qwen live bilingual captions) in **字幕模式** (Caption mode).

The Key stays in the server process environment. It is not written to an application settings file, returned to the browser, or included in the repository. You need to enter it again after restarting the service unless you provide `DASHSCOPE_API_KEY` in the launch environment. Do not put a real Key into a committed script, a shell command argument, a screenshot, or an issue.

For existing environment-based setups, `DASHSCOPE_WORKSPACE_ID` overrides the workspace ID saved in the page. The region is selected in the page. Region, workspace and Key must belong together.

### Fully local transcription and translation

1. Double-click `准备语音模型.command` (Prepare speech model), or run:

   ```sh
   .venv/bin/python scripts/download_models.py --only speech
   ```

   This downloads `mlx-community/whisper-large-v3-turbo` into `models/whisper` (about 1.6 GB). The exact revision is recorded locally in `models/downloads.json`.
2. Double-click `打开听笺.command` (Open Tingjian), choose local mode if prompted, and select **本地 · 离线转写翻译** (Local offline transcription and translation).
3. Open **本地模型设置** (Local model settings), available inside the configuration dialog. Set the speech directory to the absolute path of `models/whisper` in your checkout.
4. Set **翻译、笔记与问答模型** (Translation, notes and questions model) to a compatible local `.litertlm` file or MLX model directory, then save.

An existing Foresight Gemma download can be reused if you have a compatible model file and the right to use it. Select the file on your own machine; another person's model path is not portable. The app reads the weights in place. LiteRT may create several GB of compiled GPU cache under `.cache/litert` on first use.

The speech model is not required for live microphone captions. A local text model is still required for notes and questions. Imported audio files always use the local speech workflow.

## 4. Open the application each day

Double-click **打开听笺.command**.

- If this copy of Tingjian is already running, it opens the browser immediately and leaves the existing service, Key and recording untouched.
- If the service is stopped and a Qwen workspace was configured, it starts live mode and asks for the Key with hidden input.
- Otherwise, it offers live or local mode. Press Return for local mode.
- Keep the service Terminal window open. Stop the service with Control-C when you are finished. Closing only the browser does not stop the service.

To explicitly start a mode from Terminal:

```sh
.venv/bin/python -m scripts.open_app --mode local
# Or:
.venv/bin/python -m scripts.open_app --mode realtime
```

If a service is already running, the launcher opens that service. To replace a running local service with a Key-enabled one, use `启动实时字幕.command` after pending jobs and recordings finish. It checks that the old process belongs to this project before restarting it.

## 5. Record, translate, and review

1. Click **新建录音** (New recording). Enter a title, optional course/folder, and target language. Live mode detects the spoken source language automatically.
2. Optional glossary: enter one fixed translation per line, such as `gradient descent=梯度下降`. This glossary is sent to Qwen together with live audio. Offline mode accepts general terminology hints.
3. Click **开始录音** (Start recording) and grant microphone access. In live mode the app connects to Qwen before sending audio. Source and translated captions update incrementally; **草稿** means the text has not been fully confirmed.
4. Click **结束录音** (Stop recording). Wait while the last audio and subtitles are saved. Keep the page open until saving finishes. **保存录音备份** downloads a WAV backup of the current browser recording.
5. Click a transcript timestamp to listen to that part of the original audio.
6. Click **整理课程笔记** (Generate course notes), open **AI 笔记** (AI notes), or type a question into **问问这段录音** (Ask about this recording). These actions use your local text model.
7. Choose Markdown, bilingual SRT, or JSON, then click **导出** (Export).

**导入音频** (Import audio) accepts WAV, MP3, M4A, MP4, WebM, OGG, FLAC, AAC and AIFF. Video imports extract only the audio track. Import limits are 500 MB and 3 hours per file. Offline microphone processing uses 15-second batches; live mode sends approximately 256 ms PCM chunks.

Cloud/network failures stop the live recording with an explicit message. Already received audio and captions stay on disk; partially confirmed captions remain labeled as drafts. Save the browser backup if needed, then use **继续录音** (Continue recording) to create a new connection. The app does not silently replay audio or automatically retry paid sessions.

## 6. Privacy, storage, and backup

| Item | Local storage | Included in Git |
| --- | --- | --- |
| Qwen Key | Server environment only | No |
| Workspace and region | `data/realtime.json` | No |
| Local model paths | `settings.json` | No |
| Recordings, captions, notes, Q&A | `data/` | No |
| Model weights | `models/` or an external path | No |
| Generated caches, logs and verification reports | `.cache/`, ignored output files | No |

Live mode transmits microphone audio and that recording's glossary to Alibaba Cloud in the chosen region. Your cloud provider's data rules and charges apply. Local mode does not send audio to Qwen. Existing recordings are not uploaded automatically when you open the page or switch modes. The frontend has no external assets or analytics.

Stop the service before backing up `data/` and `settings.json`. Treat the backup as private. The Delete action permanently removes the selected recording and its related local data, so export important work first. The repository contains source code and tutorials, not another user's recordings, credentials or model files.

## 7. Troubleshooting

| Symptom | Check |
| --- | --- |
| Page unavailable | Start `打开听笺.command`; keep the service Terminal open; use `http://127.0.0.1:8765`. |
| Key missing | Launch with `启动实时字幕.command` and paste the Key at its hidden prompt. Opening the page alone cannot add a Key to an existing process. |
| Workspace endpoint invalid | Copy the actual Workspace ID from the console's workspace menu or API Host. Check the region. |
| Authentication/model error | Verify Key ownership, region, workspace permissions, supported model and available credit. Raw provider errors are not echoed to the page. |
| No local notes or translation | Configure a compatible local text model. Qwen live captions do not replace that model for notes and questions. |
| Microphone does not work | Check browser/macOS microphone permissions, or use another supported browser. No system audio capture is implemented. |
| Long delay | Compare live and local modes. Network conditions and provider load affect live captions; a first-caption benchmark is not a latency guarantee. |
| Port belongs to another service | Close the conflicting service or use the intended project copy. The launcher refuses to open an unrelated service. |

Current limitations include no translated speech playback, no direct system-audio capture, no slide/PDF ingestion, and no automatic cloud reconnect. Live speaker labels depend on provider events.

## 8. Development and safe publishing

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked --extra dev --python 3.11
.venv/bin/pytest -q
node --test tests/*.test.mjs
.venv/bin/ruff check app tests scripts
node --check web/app.js
```

Before committing or pushing, review the exact staged files and run:

```sh
git diff --cached --stat
.venv/bin/python scripts/audit_publish.py
```

The audit reads the Git index and reports file names and finding categories. It never prints matched secret values. It checks common private artifacts and credential patterns; it cannot guarantee that every possible secret is detectable. Stage an explicit source-file allowlist and inspect it. Never force-add ignored runtime files.

The optional `scripts/smoke_test.py` creates synthetic English speech on macOS and exercises real local models. It adds a sample recording and writes a private verification report. Real cloud tests require your own Key and incur provider charges; automated tests use a simulated provider.

Provider references: [Qwen live translation](https://help.aliyun.com/zh/model-studio/qwen3-5-livetranslate-flash-realtime), [regions and API Hosts](https://help.aliyun.com/zh/model-studio/regions), [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper), [LiteRT-LM](https://github.com/google-ai-edge/LiteRT-LM).

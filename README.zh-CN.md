# 听笺 · Local

在 Apple Silicon Mac 上运行的录音、双语转写和课程笔记网页。支持千问实时字幕，以及原有的本地离线处理。当前已在 Apple M5 Pro / 48GB 上验证本地模型链路。

**千问真实接口已于 2026-10-16 验证通过。** 在连接建立后，以 7.47 秒合成英文音频按实时速度发送，首条原文约 2.27 秒、首条译文约 2.30 秒出现，结束后的剩余字幕已完整保存。此结果不代表长时间连续讲课的延迟。配置步骤见 [实时API配置.md](实时API配置.md)。

## 启动

首次使用请先按 [英文教程](docs/QUICKSTART.md) 准备环境和模型。之后双击 **打开听笺.command**。服务运行时会直接打开已有页面；服务未启动时，根据本机配置启动实时或离线模式。关闭服务终端或按 Control-C 停止服务，已写入磁盘的数据仍保留。

1. 新建录音，或运行 `scripts/smoke_test.py` 生成示例。仓库不包含任何人的录音、笔记和测试数据库。
2. 选择千问实时字幕或本地离线模式。点击「新建录音」，选择原文语言、目标语言，填写课程名及可选术语。实时模型自动识别源语种。
3. 导入音频，或开始麦克风录音。首次录音需要允许浏览器访问麦克风；若内嵌浏览器不支持，请用 Safari 或 Chrome 打开同一地址。
4. 本地模式每 15 秒提交一段；千问模式以小片段持续发送，原文与译文增量更新。完成后可以整理笔记、提问并导出 Markdown、双语 SRT 或 JSON。点击转写时间可定位回听。

录音期间请保留页面，并在结束后等待待处理音频保存完成。页面提供本次录音 WAV 备份下载；不要在未保存时刷新。麦克风断开时会尝试保存剩余片段。

## 当前模型

| 用途 | 模型与运行方式 | 位置 |
| --- | --- | --- |
| 语音转写 | Whisper large-v3-turbo，MLX | `models/whisper`，约 1.61GB |
| 翻译、笔记、问答 | Gemma 4 12B，LiteRT-LM GPU | 自行选择已有 `.litertlm` 文件，不随仓库分发 |

Gemma 型号经 Foresight 自带配置及实际推理确认，直接读取原权重，没有复制或修改 Foresight 文件。若 Foresight 更新后移动模型，在「本地模型设置」中重新选择 `.litertlm` 的绝对路径。不要同时在多个应用运行大型模型，以免争用内存与 GPU。

`settings.json` 保存本机模型路径，不纳入版本控制。也支持通过设置选择本地 MLX 文本模型文件夹。首次 LiteRT 加载会在 `.cache/litert` 生成数 GB 的 GPU 编译缓存，之后可复用。总磁盘占用还包含 Python 依赖和原音频。

模型下载与推理分开。本地模式使用本机模型，禁止 Hugging Face 在线回退，无遥测或外部前端资源。页面与服务仅监听 `127.0.0.1`。千问实时模式需要自己的 API Key，录音时由本地后端向选定地域的阿里云百炼发送音频和术语提示；Key 仅从服务器环境变量读取。原音频、字幕和笔记仍保存于本机，云端数据处理适用供应商规则。

## 第一版范围

- 麦克风分段录音、导入音频/视频音轨、保留原音频、时间戳回听。
- 英语、中文、日语或自动识别；翻译目标支持中、英、日语。
- 双语转写、术语提示、课程分组与搜索、笔记、基于录音内容的问答。
- 单个导入文件上限 500MB / 3 小时；GPU 任务串行执行，失败任务可重试。
- 支持 WAV、MP3、M4A、MP4、WebM、OGG、FLAC、AAC、AIFF；视频仅提取音轨。

本地模式字幕按约 15 秒录音片段更新。千问模式支持增量双语字幕和接口返回的发言人标识，已通过短音频真实接口测试。尚未实现同传语音朗读、系统音频直录和 PPT/PDF 解析。物理麦克风完整流程仍需在用户授权麦克风后试录；已验证 AudioWorklet 缓冲与 WAV 编码，以及真实音频导入的完整本地模型流程。

## 数据与备份

`data/` 内保存 SQLite 数据库、上传的原音频和浏览器可播放的 16kHz 单声道 WAV 副本。退出服务后备份整个 `data/` 与 `settings.json`。删除录音会删除对应音频、副本和数据库内容，请先导出所需内容。

## 环境重建

需要 Apple Silicon macOS、uv、Python 3.11、Node.js（仅前端检查需要）。不依赖系统安装的 FFmpeg，使用 imageio-ffmpeg 自带程序。当前机器已安装，无需重复初始化。

```sh
cd /path/to/tingjian-local
UV_CACHE_DIR="$PWD/.cache/uv" /opt/homebrew/bin/uv sync --locked --python 3.11
.venv/bin/python scripts/download_models.py --only speech
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  .venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8765
```

也可依次双击「初始化环境.command」「准备语音模型.command」「启动听笺.command」。只有初始化依赖、准备语音模型需要联网，下载脚本不下载文本模型。语音模型版本记录在 `models/downloads.json`。

## 验证

```sh
UV_CACHE_DIR="$PWD/.cache/uv" /opt/homebrew/bin/uv sync --locked --extra dev --python 3.11
.venv/bin/pytest -q
node --test tests/*.test.mjs
.venv/bin/ruff check app tests scripts
node --check web/app.js
zsh -n 启动听笺.command 初始化环境.command 准备语音模型.command 启动实时字幕.command
```

服务运行时，`.venv/bin/python scripts/smoke_test.py` 会用 macOS 合成英语语音创建一条示例录音，调用真实本地模型，验证转写、翻译、笔记、问答及三种导出，并写入 `verification.json`。重新执行会新增一条示例。

2026-10-15 首次实测：约 17 秒英语音频，冷启动转写及翻译约 18.21 秒，笔记约 8.04 秒，问答约 3.03 秒。正确回答训练 5 轮、学习率 0.001，带录音时间引用。这是单条短音频结果，不能代表长课或噪声环境性能。

## 文件说明

- `app/server.py`：本地 API、任务队列、导出和音频上传。
- `app/engine.py`：音频解码、MLX 转写、LiteRT/MLX 文本推理及长录音分段处理。
- `app/store.py`：SQLite 持久化与任务恢复。
- `app/realtime.py`：千问 WebSocket 连接、双语字幕对应和边录边保存。
- `web/`：本地网页、录音工作线程和 WAV 编码。
- `scripts/`：显式模型下载及真实模型验证。
- `tests/`：API、持久化、失败重试、翻译对应关系与录音缓冲测试。
- `.command` 文件：统一打开入口、环境初始化、语音模型下载、本地启动和实时字幕启动。

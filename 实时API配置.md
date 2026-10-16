# 配置千问实时字幕

已接入 `qwen3.8-livetranslate-flash-realtime`，只生成原文和译文字幕；课程笔记、问答继续调用本地 Gemma。导入文件保留原有本地处理方式。

## 开通和使用

1. 在阿里云百炼开通模型服务，选择北京或新加坡地域，确认账户额度和该实时翻译模型的调用权限。
2. 在同一地域的业务空间中创建 API Key，并记下**业务空间 ID**。地域、Key、业务空间必须对应。

   在控制台顶部展开业务空间菜单，复制「业务空间 ID」或「API Host」。例如 `ws-xxxx.cn-beijing.maas.aliyuncs.com` 对应的业务空间 ID 为 `ws-xxxx`。也可能是 `llm-` 等其他前缀，以控制台实际显示为准；不要填 API Key 列表的数字编号或文档中的 `{WorkspaceId}` 占位符。
3. 双击项目内的 **启动实时字幕.command**，在终端粘贴 Key。输入时不会显示字符，也不会把 Key 写入文件、浏览器或命令行参数。每次启动需重新输入；也可事先通过环境变量提供。
4. 网页点击「配置千问 API」，填写地域和业务空间 ID，保存。
5. 选择「千问 · 实时双语字幕」，新建录音并开始。首次连接会检查真实 API 权限，连接成功后才发送音频。

启动脚本会在确认没有待处理任务、没有实时录音，且端口上的服务确实属于本项目时，替换已有听笺服务，使新 Key 生效。不会终止其他应用。关闭启动终端或按 Control-C 停止服务。

## 不通过启动脚本

在 zsh 终端运行下列命令。先停止原听笺服务，再启动新进程。`read -s` 隐藏输入，Key 不进入 shell 命令历史。

```sh
cd /path/to/tingjian-local
read -rs 'DASHSCOPE_API_KEY?粘贴千问 API Key（隐藏输入）：'
export DASHSCOPE_API_KEY
printf '\n'
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  .venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8765
```

业务空间也可用 `DASHSCOPE_WORKSPACE_ID` 环境变量提供；该变量存在时优先于页面保存的业务空间 ID。页面只显示 Key 是否已提供，不显示 Key 内容。不要把 Key 发到聊天中或写入源码。

## 实时录音的行为

- 16kHz 单声道 PCM 音频约每 256 毫秒发送一次，原文和译文按接口增量立即更新。
- 部分字幕会标记「草稿」，收到完整原文与成功翻译响应后成为最终字幕。
- 结束时先发送剩余录音，再发送 `session.finish`，等待服务端排出剩余字幕后关闭连接，最多等待 30 秒。
- 服务器边接收边写入本地 WAV；页面保留可下载的录音备份。网络失败会停止录音并明确提示，不会悄悄积压或自动重发产生重复费用。恢复后点击「继续录音」建立新连接，时间线接续到已保存音频末尾。
- 术语固定译法在新建录音时按每行 `原词=译词` 填写，例如 `gradient descent=梯度下降`。实时模型自动识别源语种。
- 不会自动把已有录音或导入文件发送到云端。只在选择实时模式并开始录音后发送音频和该录音的术语提示。
- 2026-10-16 已使用真实千问 API 验证：连接握手约 1.17 秒，随后开始按实时速度发送 7.47 秒合成英语音频。音频开始后首条原文约 2.27 秒、首条译文约 2.30 秒出现；从音频开始到全部剩余字幕保存约 13.24 秒。该数据衡量首条字幕和结束收尾，不代表每句话或长课的持续延迟。实测记录保存在 `.cache/realtime-verification.json`，不包含 Key。

## 验证与限制

模拟接口测试覆盖握手、短片段即时发送、原文/译文对应、重复与乱序事件、字幕最终确认、结束收尾、断线保留 WAV、Key 不返回页面及跨站 WebSocket 拦截。模拟测试不会验证真实云端模型输出质量。

连接失败时先核对地域、业务空间、Key 和额度。出于密钥保护，页面不会直接展示供应商原始错误响应。真实联调时应使用不含私人内容的测试音频，并测量字幕出现延迟。

官方参考：[实时翻译接入](https://help.aliyun.com/zh/model-studio/qwen3-5-livetranslate-flash-realtime)、[客户端事件](https://help.aliyun.com/zh/model-studio/live-translator-client-events)、[服务端事件](https://help.aliyun.com/zh/model-studio/live-translator-server-events)。

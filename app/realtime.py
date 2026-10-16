"""Qwen 3.8 streaming subtitles. Credentials stay on this local server."""

import asyncio
import base64
import json
import os
import re
import time
import wave
from contextlib import suppress
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

from app.store import new_id

MODEL = "qwen3.8-livetranslate-flash-realtime"
REGIONS = {"cn-beijing": "北京", "ap-southeast-1": "新加坡"}
SAMPLE_RATE = 16000
MAX_SECONDS = 10800


class RealtimeError(RuntimeError):
    pass


class RealtimeConfig:
    def __init__(self, path: Path):
        self.path = path

    def settings(self):
        settings = {"region": "cn-beijing", "workspace_id": ""}
        if self.path.exists():
            settings.update(json.loads(self.path.read_text()))
        settings["workspace_id"] = os.environ.get(
            "DASHSCOPE_WORKSPACE_ID", settings["workspace_id"]
        ).strip()
        return settings

    def configure(self, region, workspace_id):
        if region not in REGIONS:
            raise RealtimeError("请选择北京或新加坡地域。")
        if workspace_id and not re.fullmatch(r"[A-Za-z0-9-]{1,100}", workspace_id):
            raise RealtimeError("业务空间 ID 只能包含字母、数字和连字符。")
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"region": region, "workspace_id": workspace_id}))
        temporary.replace(self.path)

    def status(self):
        settings = self.settings()
        key = bool(os.environ.get("DASHSCOPE_API_KEY", "").strip())
        workspace = bool(re.fullmatch(r"[A-Za-z0-9-]{1,100}", settings["workspace_id"]))
        return {
            **settings,
            "model": MODEL,
            "key_configured": key,
            "ready": key and workspace and settings["region"] in REGIONS,
        }

    def connection(self):
        settings = self.status()
        if not settings["ready"]:
            raise RealtimeError("请先设置千问 API Key、业务空间 ID 和对应地域。")
        host = f"{settings['workspace_id']}.{settings['region']}.maas.aliyuncs.com"
        return (
            f"wss://{host}/api-ws/v1/realtime?model={MODEL}",
            {"Authorization": f"Bearer {os.environ['DASHSCOPE_API_KEY'].strip()}"},
        )


class Captions:
    """Join source/translation item IDs; deltas may arrive before their mapping."""

    def __init__(self, store, sid, aid, offset):
        self.store, self.sid, self.aid, self.offset = store, sid, aid, offset
        self.sources, self.translations, self.seen = {}, {}, set()
        self.duration = 0.0

    def source(self, item_id):
        if item_id not in self.sources:
            self.sources[item_id] = {
                "id": new_id(), "text": "", "start": None, "end": None,
                "speaker": "", "done": False,
            }
        return self.sources[item_id]

    def translation(self, item_id):
        return self.translations.setdefault(item_id, {"source": None, "text": "", "done": False})

    def apply(self, event):
        event_id = event.get("event_id")
        if event_id and event_id in self.seen:
            return []
        if event_id:
            self.seen.add(event_id)
        kind, item_id = event.get("type", ""), event.get("item_id")
        affected = set()
        if kind.startswith("input_audio_buffer.speech_") and item_id:
            source = self.source(item_id)
            if kind.endswith("speech_started"):
                source["start"] = max(0, event["audio_start_ms"] / 1000)
                source["speaker"] = str(event.get("speaker_id", ""))
            else:
                source["end"] = max(0, event["audio_end_ms"] / 1000)
            affected.add(item_id)
        elif kind.startswith("conversation.item.input_audio_transcription.") and item_id:
            source = self.source(item_id)
            if kind.endswith(".delta"):
                source["text"] += event.get("delta", "")
            elif kind.endswith(".completed"):
                source["text"] = event.get("transcript", source["text"])
                source["done"] = True
            elif kind.endswith(".failed"):
                raise RealtimeError("千问原文识别失败，音频已在本机保留。")
            affected.add(item_id)
        elif kind == "conversation.item.created":
            item = event.get("item", {})
            if item.get("role") == "assistant" and event.get("previous_item_id"):
                row = self.translation(item["id"])
                row["source"] = event["previous_item_id"]
                self.source(row["source"])
                affected.add(row["source"])
        elif kind in ("response.text.delta", "response.text.done") and item_id:
            row = self.translation(item_id)
            if kind.endswith(".delta"):
                row["text"] += event.get("delta", "")
            else:
                row["text"] = event.get("text", row["text"])
            if row["source"]:
                affected.add(row["source"])
        elif kind == "response.done":
            response = event.get("response", {})
            for item in response.get("output", []):
                row = self.translation(item["id"])
                content = "".join(p.get("text", "") for p in item.get("content", []))
                if content:
                    row["text"] = content
                row["done"] = response.get("status") == "completed"
                if row["source"]:
                    affected.add(row["source"])
        return [row for source_id in affected if (row := self.persist(source_id))]

    def persist(self, source_id):
        source = self.sources[source_id]
        targets = [r for r in self.translations.values() if r["source"] == source_id]
        translation = "".join(r["text"] for r in targets)
        if not source["text"] and not translation:
            return None
        start = source["start"] if source["start"] is not None else 0
        end = source["end"] if source["end"] is not None else self.duration
        row = {
            "id": source["id"], "session_id": self.sid, "audio_id": self.aid,
            "start": self.offset + start, "end": self.offset + max(start + 0.001, end),
            "text": source["text"], "translation": translation, "speaker": source["speaker"],
            "is_final": int(source["done"] and bool(targets) and all(r["done"] for r in targets)),
        }
        with self.store.connection() as db:
            db.execute(
                "INSERT INTO segments(id,session_id,audio_id,start,end,text,translation,"
                "is_final,speaker) VALUES(:id,:session_id,:audio_id,:start,:end,:text,"
                ":translation,:is_final,:speaker) ON CONFLICT(id) DO UPDATE SET "
                "start=excluded.start,end=excluded.end,text=excluded.text,"
                "translation=excluded.translation,is_final=excluded.is_final,speaker=excluded.speaker",
                row,
            )
        return row


def provider_error(event):
    if event.get("type") == "error" or event.get("code"):
        # Never forward arbitrary provider payloads: they may contain credentials or user audio.
        raise RealtimeError("千问接口返回错误，请检查 Key、地域、业务空间、模型权限和账户额度。")


class RealtimeHub:
    def __init__(self, store):
        self.store = store
        self.config = RealtimeConfig(store.root / "realtime.json")
        self.active = set()
        self.connector = None  # Tests can inject an in-process protocol peer.

    async def run(self, client: WebSocket, session):
        sid = session["id"]
        if sid in self.active:
            raise RealtimeError("这段录音已经有实时连接，请先结束它。")
        url, headers = self.config.connection()
        self.active.add(sid)
        tasks, output, aid, frames = [], None, None, 0
        error = None
        try:
            from websockets.asyncio.client import connect

            connector = self.connector or connect
            async with connector(
                url, additional_headers=headers, open_timeout=15, close_timeout=3,
                max_size=1024 * 1024, max_queue=16,
            ) as upstream:
                async def receive():
                    event = json.loads(await upstream.recv())
                    provider_error(event)
                    return event

                async def expect(kind):
                    async with asyncio.timeout(15):
                        for _ in range(20):
                            if (await receive()).get("type") == kind:
                                return
                    raise RealtimeError("千问连接握手未完成，请稍后重试。")

                await expect("session.created")
                translation = {"language": session["target_language"]}
                phrases = {}
                for line in session["glossary"].splitlines():
                    source, separator, target = line.partition("=")
                    if separator and source.strip() and target.strip():
                        phrases[source.strip()] = target.strip()
                if phrases:
                    translation["corpus"] = {"phrases": phrases}
                await upstream.send(json.dumps({
                    "type": "session.update",
                    "session": {"output_modalities": ["text"], "translation": translation},
                }))
                await expect("session.updated")
                offset = max(
                    [r["offset"] + r["duration"] for r in self.store.query(
                        "SELECT offset,duration FROM audio WHERE session_id=?", (sid,)
                    )] + [0]
                )
                aid = new_id()
                output = wave.open(str(self.store.audio_dir / f"{aid}.wav"), "wb")
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(SAMPLE_RATE)
                output.writeframes(b"")
                self.store.execute(
                    "INSERT INTO audio(id,session_id,filename,offset) VALUES(?,?,?,?)",
                    (aid, sid, f"{aid}.wav", offset),
                )
                captions = Captions(self.store, sid, aid, offset)
                await client.send_json({"type": "ready", "audio_id": aid, "offset": offset})
                finishing = False
                started = time.monotonic()

                async def send_audio():
                    nonlocal frames, finishing
                    last_saved = 0
                    while True:
                        message = await asyncio.wait_for(client.receive(), timeout=45)
                        if message["type"] == "websocket.disconnect":
                            raise RealtimeError("页面连接已断开，已收到的音频和字幕保留在本机。")
                        if message.get("bytes") is not None:
                            pcm = message["bytes"]
                            if not pcm or len(pcm) % 2 or len(pcm) > 32000:
                                raise RealtimeError("录音分片格式无效，请重新开始录音。")
                            frames += len(pcm) // 2
                            if frames > SAMPLE_RATE * MAX_SECONDS:
                                raise RealtimeError("本次录音已达到 3 小时上限，请继续新的一段。")
                            # Bound client buffering and accidental faster-than-realtime uploads.
                            if frames / SAMPLE_RATE > time.monotonic() - started + 5:
                                raise RealtimeError("音频发送过快，请使用导入音频功能。")
                            output.writeframes(pcm)
                            captions.duration = frames / SAMPLE_RATE
                            if frames - last_saved >= SAMPLE_RATE:
                                self.save_duration(aid, frames)
                                last_saved = frames
                            await upstream.send(json.dumps({
                                "type": "input_audio_buffer.append",
                                "audio": base64.b64encode(pcm).decode("ascii"),
                            }))
                        elif json.loads(message.get("text", "{}")) == {"type": "finish"}:
                            finishing = True
                            await upstream.send(json.dumps({"type": "session.finish"}))
                            return
                        else:
                            raise RealtimeError("无法识别录音控制消息。")

                async def receive_captions():
                    while True:
                        event = await receive()
                        for row in captions.apply(event):
                            await client.send_json({"type": "segment", "segment": row})
                        if event.get("type") == "response.done":
                            if event.get("response", {}).get("status") != "completed":
                                raise RealtimeError(
                                    "千问返回了未完成的译文，已保留字幕草稿和音频。"
                                )
                        if event.get("type") == "session.finished":
                            if not finishing:
                                raise RealtimeError("千问提前结束了会话，请继续录制新的一段。")
                            return

                sender = asyncio.create_task(send_audio())
                receiver = asyncio.create_task(receive_captions())
                tasks = [sender, receiver]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
                if receiver in done and not sender.done():
                    raise RealtimeError("千问连接意外中断，已收到的录音保留在本机。")
                await asyncio.wait_for(receiver, timeout=30)
        except RealtimeError as exc:
            error = str(exc)
        except (TimeoutError, asyncio.TimeoutError):
            error = "实时连接超时，已收到的音频和字幕保留在本机；请检查网络后继续录音。"
        except Exception:
            error = "实时连接失败，请检查网络、Key 与账户权限；已收到的录音保留在本机。"
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Close files and release the session even if ASGI cancels this coroutine.
            if output is not None:
                output.close()
            if aid:
                self.save_duration(aid, frames)
                self.store.touch(sid)
            self.active.discard(sid)
            await asyncio.gather(*tasks, return_exceptions=True)
        with suppress(WebSocketDisconnect, RuntimeError, OSError):
            await client.send_json({
                "type": "error" if error else "finished",
                "message": error or "实时字幕与录音已保存。",
            })

    def save_duration(self, aid, frames):
        self.store.execute("UPDATE audio SET duration=? WHERE id=?", (frames / SAMPLE_RATE, aid))

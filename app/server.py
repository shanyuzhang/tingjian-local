import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.engine import ROOT, Engine, ModelError, clock, save_playback
from app.realtime import RealtimeError, RealtimeHub
from app.store import Store, new_id, now

LOG = logging.getLogger(__name__)
MAX_UPLOAD = 500 * 1024 * 1024


class NewSession(BaseModel):
    title: str = Field(default="未命名录音", min_length=1, max_length=150)
    folder: str = Field(default="", max_length=80)
    language: Literal["auto", "en", "zh", "ja"] = "en"
    target_language: Literal["zh", "en", "ja"] = "zh"
    glossary: str = Field(default="", max_length=2500)


class RenameSession(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    folder: str = Field(default="", max_length=80)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1500)


class Settings(BaseModel):
    speech_model: str = Field(max_length=1500)
    text_model: str = Field(default="", max_length=1500)


class CloudSettings(BaseModel):
    region: Literal["cn-beijing", "ap-southeast-1"]
    workspace_id: str = Field(default="", max_length=100)


class Jobs:
    def __init__(self, store, engine):
        self.store, self.engine = store, engine
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-model")
        self.lock = threading.Lock()
        store.execute(
            "UPDATE jobs SET status='failed', error=? WHERE status IN ('queued','running')",
            ("上次运行被中断，音频已保留，可以重试这个任务。",),
        )

    def submit(self, sid, kind, payload, client_key=None):
        with self.lock:
            if client_key:
                rows = self.store.query(
                    "SELECT id FROM jobs WHERE session_id=? AND client_key=?", (sid, client_key)
                )
                if rows:
                    return self.store.job(rows[0]["id"])
            if self.busy_count() >= 32:
                raise HTTPException(429, "本地处理队列已满，请等待当前任务完成。")
            jid = new_id()
            self.store.execute(
                "INSERT INTO jobs(id,session_id,kind,payload,client_key,status,created_at) "
                "VALUES(?,?,?,?,?,'queued',?)",
                (jid, sid, kind, json.dumps(payload), client_key, now()),
            )
            self.pool.submit(self.run, jid)
            return self.store.job(jid)

    def busy_count(self, sid=None):
        sql = "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','running')"
        rows = self.store.query(sql + (" AND session_id=?" if sid else ""), (sid,) if sid else ())
        return rows[0]["n"]

    def progress(self, jid, text):
        self.store.execute("UPDATE jobs SET progress=? WHERE id=?", (text, jid))

    def run(self, jid):
        self.store.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
        job = self.store.job(jid)
        sid, kind, payload = job["session_id"], job["kind"], job["payload"]

        def progress(text):
            self.progress(jid, text)

        try:
            session = self.store.session(sid)
            if kind == "audio":
                result = self.audio(sid, payload, session, progress)
            elif kind == "translation":
                result = self.translate(sid, session, progress)
            elif kind == "summary":
                text = self.engine.summarize(self.store.segments(sid), progress)
                self.store.execute("UPDATE sessions SET summary=? WHERE id=?", (text, sid))
                result = {"summary": text}
            elif kind == "question":
                text = self.engine.answer(self.store.segments(sid), payload["question"], progress)
                self.store.execute(
                    "INSERT INTO messages VALUES(?,?,?,?,?)",
                    (new_id(), sid, payload["question"], text, now()),
                )
                result = {"answer": text}
            else:
                raise ModelError("不支持这个任务类型。")
            self.store.touch(sid)
            self.store.execute(
                "UPDATE jobs SET status='done',result=?,progress=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False), result.get("message", "处理完成"), jid),
            )
        except Exception as exc:
            LOG.exception("Local job %s failed", jid)
            self.store.execute(
                "UPDATE jobs SET status='failed',error=? WHERE id=?",
                (
                    str(exc)
                    if isinstance(exc, ModelError)
                    else f"本地处理失败（{type(exc).__name__}）：{str(exc)[:300]}",
                    jid,
                ),
            )

    def audio(self, sid, payload, session, progress):
        audio = self.store.query("SELECT * FROM audio WHERE id=?", (payload["audio_id"],))[0]
        progress("正在读取音频")
        samples = self.engine.decode_audio(self.store.audio_dir / audio["filename"])
        save_playback(samples, self.store.audio_dir / f"{audio['id']}.playback.wav")
        duration = len(samples) / 16000
        self.store.execute("UPDATE audio SET duration=? WHERE id=?", (duration, audio["id"]))
        self.store.execute("DELETE FROM segments WHERE audio_id=?", (audio["id"],))
        size = 30 * 16000
        total = max(1, (len(samples) + size - 1) // size)
        count = 0
        for index, start in enumerate(range(0, len(samples), size)):
            progress(f"正在转写 {index + 1}/{total} · {clock(audio['offset'] + start / 16000)}")
            rows = self.engine.transcribe(
                samples[start : start + size], session["language"], session["glossary"]
            )
            for row in rows:
                begin = audio["offset"] + start / 16000 + max(0.0, float(row["start"]))
                end = min(
                    audio["offset"] + duration, audio["offset"] + start / 16000 + float(row["end"])
                )
                if end <= begin or not row["text"].strip():
                    continue
                self.store.execute(
                    "INSERT INTO segments(id,session_id,audio_id,start,end,text) "
                    "VALUES(?,?,?,?,?,?)",
                    (new_id(), sid, audio["id"], begin, end, row["text"].strip()),
                )
                count += 1
            self.store.touch(sid)
        message = "转写完成" if count else "未识别到有效语音，原音频已保留"
        if payload.get("translate") and count:
            if self.engine.status()["text"]["ready"]:
                self.translate(sid, session, progress)
            else:
                message += "；配置文本模型后可生成译文"
        return {"segments": count, "message": message}

    def translate(self, sid, session, progress):
        segments = [s for s in self.store.segments(sid) if not s["translation"]]
        for index in range(0, len(segments), 5):
            batch = segments[index : index + 5]
            progress(f"正在翻译 {index + 1}–{index + len(batch)}/{len(segments)} 段")
            translations = self.engine.translate(
                batch, session["target_language"], session["glossary"]
            )
            with self.store.connection() as db:
                for segment in batch:
                    db.execute(
                        "UPDATE segments SET translation=? WHERE id=?",
                        (translations[segment["id"]], segment["id"]),
                    )
        return {"message": "翻译完成"}


def create_app(data_dir: Path | None = None, engine=None):
    store = Store(data_dir or Path(os.environ.get("VOICE_DATA_DIR", ROOT / "data")))
    engine = engine or Engine()
    jobs = Jobs(store, engine)
    realtime = RealtimeHub(store)

    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.pool.shutdown(wait=True)

    app = FastAPI(title="听笺 · Local", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.jobs, app.state.engine = store, jobs, engine
    app.state.realtime = realtime
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            if origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "只接受本地页面发起的操作。"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; media-src 'self' blob:; "
            "connect-src 'self' ws://127.0.0.1:8765 ws://localhost:8765; "
            "worker-src 'self'; frame-ancestors 'none'; object-src 'none'"
        )
        return response

    def get_session(sid):
        session = store.session(sid)
        if not session:
            raise HTTPException(404, "录音不存在。")
        return session

    def text_ready():
        if not engine.status()["text"]["ready"]:
            raise HTTPException(409, "请先在模型设置中选择本地文本模型。")

    def idle(sid):
        if sid in realtime.active:
            raise HTTPException(409, "请先结束这段实时录音，并等待字幕保存完成。")

    @app.get("/api/status")
    def status():
        return {
            "models": engine.status(), "pending_jobs": jobs.busy_count(),
            "realtime": realtime.config.status(),
            "application": "local-lecsync", "project_root": str(ROOT), "pid": os.getpid(),
            "active_realtime": len(realtime.active),
        }

    @app.put("/api/realtime/settings")
    def cloud_settings(body: CloudSettings):
        if realtime.active:
            raise HTTPException(409, "请先结束实时录音，再修改连接设置。")
        try:
            realtime.config.configure(body.region, body.workspace_id.strip())
        except RealtimeError as exc:
            raise HTTPException(422, str(exc)) from exc
        return realtime.config.status()

    @app.websocket("/api/sessions/{sid}/realtime")
    async def realtime_socket(socket: WebSocket, sid: str):
        expected = f"http://{socket.headers.get('host', '')}"
        if socket.headers.get("origin") != expected:
            await socket.close(code=1008)
            return
        await socket.accept()
        session = store.session(sid)
        try:
            if not session:
                raise RealtimeError("录音不存在。")
            if jobs.busy_count(sid):
                raise RealtimeError("这段录音仍在处理，请等待完成后再开始实时录音。")
            await realtime.run(socket, session)
        except RealtimeError as exc:
            with suppress(WebSocketDisconnect, RuntimeError):
                await socket.send_json({"type": "error", "message": str(exc)})
        finally:
            with suppress(WebSocketDisconnect, RuntimeError):
                await socket.close()

    @app.put("/api/settings")
    def settings(body: Settings):
        if jobs.busy_count() or realtime.active:
            raise HTTPException(409, "请等待当前任务完成后再切换模型。")
        try:
            engine.configure(body.speech_model, body.text_model)
        except ModelError as exc:
            raise HTTPException(422, str(exc)) from exc
        return engine.status()

    @app.get("/api/sessions")
    def sessions():
        return store.sessions()

    @app.post("/api/sessions", status_code=201)
    def create(body: NewSession):
        return store.create_session(**body.model_dump())

    @app.get("/api/sessions/{sid}")
    def detail(sid: str):
        session = get_session(sid)
        return {
            **session,
            "segments": store.segments(sid),
            "live": sid in realtime.active,
            "audio": store.query("SELECT * FROM audio WHERE session_id=? ORDER BY offset", (sid,)),
            "messages": store.query(
                "SELECT * FROM messages WHERE session_id=? ORDER BY created_at", (sid,)
            ),
            "jobs": store.query(
                "SELECT id,kind,status,progress,error FROM jobs "
                "WHERE session_id=? ORDER BY created_at",
                (sid,),
            ),
        }

    @app.patch("/api/sessions/{sid}")
    def rename(sid: str, body: RenameSession):
        get_session(sid)
        store.execute(
            "UPDATE sessions SET title=?,folder=?,updated_at=? WHERE id=?",
            (body.title, body.folder, now(), sid),
        )
        return store.session(sid)

    @app.delete("/api/sessions/{sid}", status_code=204)
    def remove(sid: str):
        get_session(sid)
        idle(sid)
        if jobs.busy_count(sid):
            raise HTTPException(409, "这段录音仍在处理中，请完成后再删除。")
        files = store.query("SELECT id,filename FROM audio WHERE session_id=?", (sid,))
        store.execute("DELETE FROM sessions WHERE id=?", (sid,))
        for row in files:
            (store.audio_dir / row["filename"]).unlink(missing_ok=True)
            (store.audio_dir / f"{row['id']}.playback.wav").unlink(missing_ok=True)

    @app.post("/api/sessions/{sid}/audio", status_code=202)
    async def upload(
        sid: str,
        file: Annotated[UploadFile, File()],
        offset: Annotated[float, Form(ge=0, le=10800)] = 0,
        translate: Annotated[bool, Form()] = True,
        client_key: Annotated[str, Form(max_length=80)] = "",
    ):
        get_session(sid)
        idle(sid)
        if client_key:
            existing = store.query(
                "SELECT id FROM jobs WHERE session_id=? AND client_key=?", (sid, client_key)
            )
            if existing:
                return store.job(existing[0]["id"])
        if not engine.status()["speech"]["ready"]:
            raise HTTPException(409, "转写模型未就绪，请先完成模型准备。")
        suffix = Path(file.filename or "audio.wav").suffix.lower()
        if suffix not in {
            ".wav",
            ".mp3",
            ".m4a",
            ".mp4",
            ".webm",
            ".ogg",
            ".flac",
            ".aac",
            ".aiff",
        }:
            raise HTTPException(415, "支持 WAV、MP3、M4A、MP4、WebM、OGG、FLAC、AAC、AIFF。")
        aid, size = new_id(), 0
        filename = aid + suffix
        path = store.audio_dir / filename
        try:
            with path.open("wb") as output:
                while data := await file.read(1024 * 1024):
                    size += len(data)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "文件超过 500MB，请先拆分或压缩。")
                    output.write(data)
            if not size:
                raise HTTPException(422, "音频文件为空。")
            store.execute(
                "INSERT INTO audio(id,session_id,filename,offset) VALUES(?,?,?,?)",
                (aid, sid, filename, offset),
            )
            job = jobs.submit(
                sid,
                "audio",
                {"audio_id": aid, "translate": translate},
                client_key=client_key or None,
            )
            if job["payload"].get("audio_id") != aid:
                store.execute("DELETE FROM audio WHERE id=?", (aid,))
                path.unlink(missing_ok=True)
            return job
        except Exception:
            store.execute("DELETE FROM audio WHERE id=?", (aid,))
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    @app.post("/api/sessions/{sid}/actions/{operation}", status_code=202)
    def process(sid: str, operation: Literal["summary", "translation"]):
        get_session(sid)
        idle(sid)
        text_ready()
        if not store.segments(sid):
            raise HTTPException(409, "先录音或导入音频，生成转写后再处理。")
        return jobs.submit(sid, operation, {})

    @app.post("/api/sessions/{sid}/questions", status_code=202)
    def question(sid: str, body: Question):
        get_session(sid)
        idle(sid)
        text_ready()
        if not store.segments(sid):
            raise HTTPException(409, "这段录音还没有转写内容。")
        return jobs.submit(sid, "question", body.model_dump())

    @app.get("/api/jobs/{jid}")
    def job_detail(jid: str):
        row = store.job(jid)
        if not row:
            raise HTTPException(404, "任务不存在。")
        return row

    @app.post("/api/jobs/{jid}/retry", status_code=202)
    def retry(jid: str):
        row = store.job(jid)
        if not row or row["status"] != "failed":
            raise HTTPException(409, "只有失败的任务可以重试。")
        idle(row["session_id"])
        result = jobs.submit(row["session_id"], row["kind"], row["payload"])
        store.execute("UPDATE jobs SET status='retried' WHERE id=?", (jid,))
        return result

    @app.get("/api/audio/{aid}")
    def audio(aid: str):
        rows = store.query("SELECT filename FROM audio WHERE id=?", (aid,))
        if not rows:
            raise HTTPException(404, "音频不存在。")
        return FileResponse(store.audio_dir / rows[0]["filename"])

    @app.get("/api/audio/{aid}/playback")
    def playback(aid: str):
        rows = store.query("SELECT id,filename FROM audio WHERE id=?", (aid,))
        if not rows:
            raise HTTPException(404, "音频不存在。")
        path = store.audio_dir / f"{rows[0]['id']}.playback.wav"
        if not path.is_file() and Path(rows[0]["filename"]).suffix == ".wav":
            path = store.audio_dir / rows[0]["filename"]
        if not path.is_file():
            raise HTTPException(404, "音频尚未完成解码，请稍后重试。")
        return FileResponse(path, media_type="audio/wav")

    @app.get("/api/sessions/{sid}/export/{format}")
    def export(sid: str, format: Literal["md", "srt", "json"]):
        session, segments = get_session(sid), store.segments(sid)
        if format == "json":
            text = json.dumps({**session, "segments": segments}, ensure_ascii=False, indent=2)
        elif format == "srt":

            def stamp(t):
                milliseconds = max(0, round(t * 1000))
                return f"{clock(milliseconds // 1000)},{milliseconds % 1000:03}"

            text = "\n\n".join(
                f"{i + 1}\n{stamp(s['start'])} --> {stamp(s['end'])}\n{s['text']}"
                + (f"\n{s['translation']}" if s["translation"] else "")
                for i, s in enumerate(segments)
            )
        else:
            text = f"# {session['title']}\n\n{session['summary']}\n\n## 双语转写\n\n"
            text += "\n\n".join(
                f"[{clock(s['start'])}] {s['text']}\n\n{s['translation']}" for s in segments
            )
        return Response(
            text,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="transcript-{sid[:8]}.{format}"'
            },
        )

    app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
    return app


app = create_app()

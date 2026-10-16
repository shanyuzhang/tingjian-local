import io
import time
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.engine import Engine, ModelError, parse_translations, transcript_chunks
from app.server import create_app
from app.store import Store


class FakeEngine:
    def __init__(self):
        self.speech_calls = 0

    def status(self):
        return {
            k: {"ready": True, "path": "/local/test", "label": "test"} for k in ("speech", "text")
        }

    def decode_audio(self, path):
        if path.read_bytes() == b"invalid":
            raise ModelError("无法读取这个音频文件")
        return np.full(32000, 0.1, dtype=np.float32)

    def transcribe(self, samples, language, glossary):
        self.speech_calls += 1
        return [{"start": 0.25, "end": 1.5, "text": "Neural networks learn patterns."}]

    def translate(self, segments, language, glossary):
        return {s["id"]: "神经网络学习模式。" for s in segments}

    def summarize(self, segments, progress):
        assert segments
        progress("正在整理")
        return "## 重点\n[00:00:31] 神经网络学习模式。"

    def answer(self, segments, question, progress):
        return "录音提到了神经网络。[00:00:31]"


@pytest.fixture
def client(tmp_path):
    engine = FakeEngine()
    app = create_app(tmp_path, engine)
    with TestClient(app) as client:
        yield client, app, engine


def create(client):
    response = client.post("/api/sessions", json={"title": "机器学习", "folder": "课程"})
    assert response.status_code == 201
    return response.json()["id"]


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 32000)
    return output.getvalue()


def upload(client, sid, key="test-audio", content=None, offset=31):
    return client.post(
        f"/api/sessions/{sid}/audio",
        files={"file": ("lecture.wav", content or wav_bytes(), "audio/wav")},
        data={"offset": offset, "client_key": key, "translate": "true"},
    )


def await_job(client, jid):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{jid}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.01)
    pytest.fail("job did not finish")


def test_audio_pipeline_preserves_offsets_translation_and_export(client):
    client, app, engine = client
    sid = create(client)
    response = upload(client, sid)
    assert response.status_code == 202
    assert await_job(client, response.json()["id"])["status"] == "done"
    segment = client.get(f"/api/sessions/{sid}").json()["segments"][0]
    assert segment["start"] == 31.25
    assert segment["end"] == 32.5
    assert segment["translation"] == "神经网络学习模式。"
    srt = client.get(f"/api/sessions/{sid}/export/srt").text
    assert "00:00:31,250 --> 00:00:32,500" in srt
    assert "Neural networks" in srt
    assert "神经网络" in srt
    saved = Store(app.state.store.root).segments(sid)
    assert saved[0]["id"] == segment["id"]
    playback = client.get(f"/api/audio/{segment['audio_id']}/playback")
    assert playback.status_code == 200
    assert playback.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(playback.content), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getnframes()) == (16000, 1, 32000)
        assert wav.readframes(1) == b"\xcc\x0c"


def test_duplicate_audio_submission_is_idempotent(client):
    client, app, engine = client
    sid = create(client)
    first = upload(client, sid).json()
    second = upload(client, sid).json()
    assert first["id"] == second["id"]
    await_job(client, first["id"])
    assert engine.speech_calls == 1
    assert len(client.get(f"/api/sessions/{sid}").json()["audio"]) == 1


def test_invalid_audio_is_kept_for_retry_and_does_not_create_segments(client):
    client, app, engine = client
    sid = create(client)
    job = upload(client, sid, content=b"invalid").json()
    result = await_job(client, job["id"])
    assert result["status"] == "failed"
    assert "无法读取" in result["error"]
    detail = client.get(f"/api/sessions/{sid}").json()
    assert detail["segments"] == []
    aid = detail["audio"][0]["id"]
    assert client.get(f"/api/audio/{aid}").content == b"invalid"
    retry = client.post(f"/api/jobs/{job['id']}/retry")
    assert retry.status_code == 202
    assert retry.json()["payload"]["audio_id"] == aid


def test_summary_and_questions_are_separate_routes(client):
    client, app, engine = client
    sid = create(client)
    await_job(client, upload(client, sid).json()["id"])
    summary = client.post(f"/api/sessions/{sid}/actions/summary")
    assert summary.status_code == 202
    assert await_job(client, summary.json()["id"])["status"] == "done"
    question = client.post(f"/api/sessions/{sid}/questions", json={"question": "讲了什么？"})
    assert question.status_code == 202
    assert await_job(client, question.json()["id"])["status"] == "done"
    detail = client.get(f"/api/sessions/{sid}").json()
    assert "## 重点" in detail["summary"]
    assert detail["messages"][0]["question"] == "讲了什么？"


def test_delete_removes_session_content_and_audio(client):
    client, app, engine = client
    sid = create(client)
    await_job(client, upload(client, sid).json()["id"])
    aid = client.get(f"/api/sessions/{sid}").json()["audio"][0]["id"]
    assert client.delete(f"/api/sessions/{sid}").status_code == 204
    assert client.get(f"/api/sessions/{sid}").status_code == 404
    assert client.get(f"/api/audio/{aid}").status_code == 404
    assert list(app.state.store.audio_dir.iterdir()) == []


def test_cross_origin_mutations_and_untrusted_hosts_are_rejected(client):
    client, app, engine = client
    assert (
        client.post("/api/sessions", json={}, headers={"Origin": "https://example.com"}).status_code
        == 403
    )
    assert client.get("/api/status", headers={"Host": "malicious.invalid"}).status_code == 400
    assert client.get("/").headers["content-security-policy"].find("connect-src 'self'") >= 0


def test_missing_models_are_reported_without_network(tmp_path):
    engine = Engine(tmp_path / "settings.json")
    engine.configure(str(tmp_path / "missing"), "")
    assert not engine.status()["speech"]["ready"]
    assert not engine.status()["text"]["ready"]
    with pytest.raises(ModelError, match="选择本地"):
        engine._model_path("text_model")


def test_restarted_jobs_are_marked_failed_without_discarding_payload(tmp_path):
    store = Store(tmp_path)
    session = store.create_session("恢复测试", "", "en", "zh", "")
    store.execute(
        "INSERT INTO jobs(id,session_id,kind,payload,status,created_at) "
        "VALUES(?,?,'summary','{}','running','now')",
        ("interrupted", session["id"]),
    )
    app = create_app(tmp_path, FakeEngine())
    with TestClient(app):
        job = store.job("interrupted")
        assert job["status"] == "failed"
        assert "中断" in job["error"]
        assert job["payload"] == {}


@pytest.mark.parametrize(
    "output",
    [
        '[{"id":"wrong","translation":"错误"}]',
        '[{"id":"one","translation":"甲"},{"id":"one","translation":"乙"}]',
        '[{"id":"one","translation":""}]',
        "not json",
        "[null]",
    ],
)
def test_invalid_translation_does_not_match_unrelated_segments(output):
    with pytest.raises(ModelError):
        parse_translations(output, ["one"])


def test_translation_parser_accepts_fences_and_reordered_ids():
    result = parse_translations(
        '```json\n[{"id":"b","translation":"乙"},{"id":"a","translation":"甲"}]\n```', ["a", "b"]
    )
    assert result == {"a": "甲", "b": "乙"}


def test_chunked_transcript_keeps_every_source_segment_and_timestamp():
    segments = [{"start": i * 20, "text": f"segment number {i}"} for i in range(30)]
    chunks = transcript_chunks(segments, limit=100)
    assert len(chunks) > 1
    for segment in segments:
        assert sum(segment["text"] + "\n" in chunk for chunk in chunks) == 1
    assert "[00:00:00]" in chunks[0]


def test_unknown_session_and_invalid_formats_fail_before_work(client):
    client, app, engine = client
    assert client.get("/api/sessions/nonexistent").status_code == 404
    sid = create(client)
    response = client.post(f"/api/sessions/{sid}/audio", files={"file": ("x.exe", b"x")})
    assert response.status_code == 415
    assert not list(app.state.store.audio_dir.iterdir())

import asyncio
import base64
import io
import json
import wave

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.realtime import Captions, RealtimeConfig
from app.server import create_app
from app.store import Store


class FakeProvider:
    def __init__(self, fail=False):
        self.messages = []
        self.queue = asyncio.Queue()
        self.fail = fail

    async def __aenter__(self):
        self.queue.put_nowait({"type": "session.created"})
        return self

    async def __aexit__(self, *_):
        pass

    async def recv(self):
        return json.dumps(await self.queue.get())

    async def send(self, raw):
        event = json.loads(raw)
        self.messages.append(event)
        kind = event["type"]
        if kind == "session.update":
            assert event["session"]["output_modalities"] == ["text"]
            self.queue.put_nowait({"type": "session.updated"})
        elif kind == "input_audio_buffer.append":
            assert len(base64.b64decode(event["audio"])) == 3200
            for row in [
                {"type": "input_audio_buffer.speech_started", "item_id": "source",
                 "audio_start_ms": 0, "speaker_id": 1},
                {"type": "conversation.item.created", "previous_item_id": "source",
                 "item": {"id": "target", "role": "assistant", "content": []}},
                {"type": "conversation.item.input_audio_transcription.delta",
                 "item_id": "source", "delta": "Welcome"},
                {"type": "response.text.delta", "item_id": "target", "delta": "欢迎"},
            ]:
                self.queue.put_nowait(row)
            if self.fail:
                self.queue.put_nowait({"type": "error", "error": {"message": "test-key-only"}})
        elif kind == "session.finish":
            for row in [
                {"type": "conversation.item.input_audio_transcription.completed",
                 "item_id": "source", "transcript": "Welcome to class."},
                {"type": "input_audio_buffer.speech_stopped", "item_id": "source",
                 "audio_end_ms": 100},
                {"type": "response.text.done", "item_id": "target", "text": "欢迎来到课堂。"},
                {"type": "response.done", "response": {"status": "completed", "output": [
                    {"id": "target", "content": [{"type": "text", "text": "欢迎来到课堂。"}]}]}},
                {"type": "session.finished"},
            ]:
                self.queue.put_nowait(row)


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key-only")
    monkeypatch.delenv("DASHSCOPE_WORKSPACE_ID", raising=False)
    app = create_app(tmp_path)
    app.state.realtime.config.configure("cn-beijing", "workspace-example")
    peer = FakeProvider()
    connections = []

    def connect(url, **kwargs):
        connections.append((url, kwargs))
        return peer

    app.state.realtime.connector = connect
    with TestClient(app) as client:
        sid = client.post("/api/sessions", json={
            "glossary": "neural network=神经网络",
        }).json()["id"]
        yield client, app, sid, peer, connections


def stream(client, sid, **kwargs):
    return client.websocket_connect(
        f"/api/sessions/{sid}/realtime", headers={"Origin": "http://testserver"}, **kwargs
    )


def until(socket, kind):
    for _ in range(30):
        event = socket.receive_json()
        if event["type"] == kind:
            return event
    pytest.fail(f"No {kind} event")


def test_stream_shows_partial_before_finish_and_drains_final_subtitle(cloud):
    client, app, sid, peer, connections = cloud
    with stream(client, sid) as socket:
        ready = socket.receive_json()
        assert ready["type"] == "ready"
        socket.send_bytes(b"\x01\x00" * 1600)
        assert until(socket, "segment")["segment"]["text"] == "Welcome"
        partial = until(socket, "segment")["segment"]
        assert partial["translation"] == "欢迎" and partial["is_final"] == 0
        socket.send_json({"type": "finish"})
        assert until(socket, "finished")
    detail = client.get(f"/api/sessions/{sid}").json()
    assert not detail["live"]
    assert len(detail["segments"]) == 1
    row = detail["segments"][0]
    assert row["text"] == "Welcome to class."
    assert row["translation"] == "欢迎来到课堂。" and row["is_final"] == 1
    assert (row["start"], row["end"], row["speaker"]) == (0, 0.1, "1")
    exported = client.get(f"/api/sessions/{sid}/export/json").json()
    assert exported["segments"][0]["translation"] == "欢迎来到课堂。"
    audio = client.get(f"/api/audio/{ready['audio_id']}/playback")
    with wave.open(io.BytesIO(audio.content), "rb") as wav:
        assert wav.getnframes() == 1600 and wav.getframerate() == 16000
    assert peer.messages[-1]["type"] == "session.finish"
    assert peer.messages[0]["session"]["translation"]["corpus"]["phrases"] == {
        "neural network": "神经网络"
    }
    assert connections[0][0].startswith("wss://workspace-example.cn-beijing.maas.aliyuncs.com/")
    assert "test-key-only" not in client.get("/api/status").text


def test_disconnect_error_retains_audio_and_partial_subtitles_without_leaking_key(cloud):
    client, app, sid, peer, connections = cloud
    peer.fail = True
    with stream(client, sid) as socket:
        ready = socket.receive_json()
        socket.send_bytes(b"\x01\x00" * 1600)
        error = until(socket, "error")
        assert "test-key-only" not in json.dumps(error)
    detail = client.get(f"/api/sessions/{sid}").json()
    assert detail["audio"][0]["duration"] == 0.1
    assert detail["segments"][0]["is_final"] == 0
    assert client.get(f"/api/audio/{ready['audio_id']}/playback").status_code == 200


def test_live_session_blocks_delete_import_model_switch_and_second_stream(cloud):
    client, app, sid, peer, connections = cloud
    with stream(client, sid) as socket:
        socket.receive_json()
        assert client.delete(f"/api/sessions/{sid}").status_code == 409
        assert client.post(f"/api/sessions/{sid}/actions/summary").status_code == 409
        question = client.post(f"/api/sessions/{sid}/questions", json={"question": "hi"})
        assert question.status_code == 409
        assert client.put("/api/realtime/settings", json={
            "region": "ap-southeast-1", "workspace_id": "other",
        }).status_code == 409
        with stream(client, sid) as second:
            assert second.receive_json()["type"] == "error"
        assert len(connections) == 1
        socket.send_json({"type": "finish"})
        until(socket, "finished")


def test_unconfigured_key_never_contacts_cloud_and_origin_is_checked(cloud, monkeypatch):
    client, app, sid, peer, connections = cloud
    monkeypatch.delenv("DASHSCOPE_API_KEY")
    with stream(client, sid) as socket:
        assert socket.receive_json()["type"] == "error"
    assert not connections
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/sessions/{sid}/realtime", headers={
            "Origin": "https://malicious.invalid",
        }):
            pass
    assert not client.get(f"/api/sessions/{sid}").json()["audio"]


def test_configuration_cannot_redirect_key_to_arbitrary_host(cloud):
    client, app, sid, peer, connections = cloud
    assert client.put("/api/realtime/settings", json={
        "region": "cn-beijing", "workspace_id": "evil.example/path",
    }).status_code == 422
    assert client.put("/api/realtime/settings", json={
        "region": "ap-southeast-1", "workspace_id": "example-workspace",
    }).status_code == 200
    url, _ = app.state.realtime.config.connection()
    assert url.startswith("wss://example-workspace.ap-southeast-1.maas.aliyuncs.com/")
    assert "test-key-only" not in app.state.realtime.config.path.read_text()


def test_resume_uses_saved_audio_duration_and_keeps_previous_segments(cloud):
    client, app, sid, peer, connections = cloud
    for expected_offset in (0, 0.1):
        with stream(client, sid) as socket:
            assert socket.receive_json()["offset"] == expected_offset
            socket.send_bytes(b"\x01\x00" * 1600)
            until(socket, "segment")
            socket.send_json({"type": "finish"})
            until(socket, "finished")
    detail = client.get(f"/api/sessions/{sid}").json()
    assert len(detail["audio"]) == len(detail["segments"]) == 2
    assert [r["start"] for r in detail["segments"]] == [0, 0.1]
    assert all(r["is_final"] for r in detail["segments"])


def test_browser_disconnection_still_closes_a_readable_wav(cloud):
    client, app, sid, peer, connections = cloud
    with stream(client, sid) as socket:
        ready = socket.receive_json()
        socket.send_bytes(b"\x01\x00" * 1600)
        until(socket, "segment")
    with wave.open(str(app.state.store.audio_dir / f"{ready['audio_id']}.wav")) as wav:
        assert wav.getnframes() == 1600
    assert sid not in app.state.realtime.active


def test_out_of_order_translation_mapping_and_duplicate_deltas(tmp_path):
    store = Store(tmp_path)
    sid = store.create_session("test", "", "en", "zh", "")["id"]
    store.execute("INSERT INTO audio(id,session_id,filename,offset) VALUES('audio',?,'a.wav',10)",
                  (sid,))
    captions = Captions(store, sid, "audio", 10)
    delta = {"type": "response.text.delta", "event_id": "unique", "item_id": "target",
             "delta": "你好"}
    assert captions.apply(delta) == []
    assert captions.apply(delta) == []
    captions.apply({"type": "conversation.item.created", "previous_item_id": "source",
                    "item": {"id": "target", "role": "assistant"}})
    captions.apply({"type": "input_audio_buffer.speech_started", "item_id": "source",
                    "audio_start_ms": 500})
    captions.apply({"type": "conversation.item.input_audio_transcription.completed",
                    "item_id": "source", "transcript": "Hello"})
    captions.apply({"type": "response.done", "response": {"status": "incomplete", "output": [
        {"id": "target", "content": []}]}})
    row = store.segments(sid)[0]
    assert row["translation"] == "你好" and row["start"] == 10.5
    assert row["is_final"] == 0


def test_default_cloud_status_contains_no_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_WORKSPACE_ID", raising=False)
    status = RealtimeConfig(tmp_path / "realtime.json").status()
    assert status["ready"] is False and status["key_configured"] is False

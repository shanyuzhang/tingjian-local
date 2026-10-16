import pytest

from scripts import open_app
from scripts.audit_publish import findings


def test_launcher_opens_existing_app_without_prompting_for_or_replacing_key(monkeypatch):
    monkeypatch.setattr(open_app.start_realtime, "status", lambda: {
        "application": "local-lecsync", "project_root": str(open_app.ROOT),
    })
    calls = []
    monkeypatch.setattr(open_app.subprocess, "run", lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr(open_app, "preferred_mode", lambda: pytest.fail("must not prompt"))
    monkeypatch.setattr(open_app.start_realtime, "main", lambda: pytest.fail("must not restart"))
    open_app.main([])
    assert calls == [["/usr/bin/open", "http://127.0.0.1:8765"]]


def test_launcher_does_not_open_another_service(monkeypatch):
    monkeypatch.setattr(open_app.start_realtime, "status", lambda: {"application": "other"})
    monkeypatch.setattr(open_app.subprocess, "run", lambda *a, **k: pytest.fail("must not open"))
    with pytest.raises(RuntimeError, match="另一个服务"):
        open_app.main([])


def test_launcher_explicit_local_mode_does_not_prompt_for_a_key(monkeypatch):
    monkeypatch.setattr(open_app.start_realtime, "status", lambda: None)
    monkeypatch.setattr(open_app.start_realtime, "main", lambda: pytest.fail("must not use API"))
    calls = []
    monkeypatch.setattr(open_app.subprocess, "run", lambda args, **kwargs: calls.append(args))
    open_app.main(["--mode", "local"])
    assert calls == [["/bin/zsh", str(open_app.ROOT / "启动听笺.command")]]


@pytest.mark.parametrize("path", [
    "data/library.sqlite3", "models/whisper/config.json", "settings.json", ".env.local",
    "verification.json", "preview.jpg", ".cache/receipt.json", "data/realtime.json",
])
def test_publish_audit_blocks_runtime_files(path):
    assert "private runtime file" in findings(path, b"content")


def test_publish_audit_blocks_secrets_and_personal_paths_without_echoing_values():
    assert "API key or access token" in findings("example.py", b"sk-" + b"x" * 32)
    assert "personal model or home path" in findings("README.md", b"/Users/" + b"someone/models/")
    assert "workspace identifier" in findings("example.json", b"ws-" + b"x" * 16)
    assert findings("app/realtime.py", b'key = os.environ["DASHSCOPE_API_KEY"]') == []

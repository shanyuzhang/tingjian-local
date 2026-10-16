"""Exercise real local models against synthetic speech; the server must already be running."""

import argparse
import json
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def wait(client, jid):
    deadline, last = time.monotonic() + 600, None
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{jid}")
        response.raise_for_status()
        job = response.json()
        message = (job["status"], job["progress"])
        if message != last:
            print(message, flush=True)
            last = message
        if job["status"] == "failed":
            raise RuntimeError(job["error"])
        if job["status"] == "done":
            return job
        time.sleep(1)
    raise TimeoutError("Model integration test timed out")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    audio = ROOT / ".cache" / "example-lecture.aiff"
    audio.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "/usr/bin/say",
            "-v",
            "Daniel",
            "-r",
            "155",
            "-o",
            str(audio),
            "Welcome to our machine learning lecture. "
            "Neural networks learn patterns from training data. "
            "We train the model for five epochs with a learning rate of zero point zero zero one. "
            "Keep the training data separate from the validation data. "
            "Next week we will discuss overfitting and regularization.",
        ],
        check=True,
    )
    timings = {}
    with httpx.Client(base_url=args.origin, timeout=30) as client:
        status = client.get("/api/status").json()
        assert status["models"]["speech"]["ready"]
        assert status["models"]["text"]["ready"]
        session = client.post(
            "/api/sessions",
            json={
                "title": "示例 · 神经网络入门",
                "folder": "示例课程",
                "language": "en",
                "target_language": "zh",
                "glossary": "neural networks, epochs, learning rate, overfitting, regularization",
            },
        )
        session.raise_for_status()
        sid = session.json()["id"]
        print("Session:", sid, flush=True)
        start = time.monotonic()
        with audio.open("rb") as file:
            response = client.post(f"/api/sessions/{sid}/audio", files={"file": (audio.name, file)})
        response.raise_for_status()
        wait(client, response.json()["id"])
        timings["transcription_and_translation_seconds"] = round(time.monotonic() - start, 2)
        detail = client.get(f"/api/sessions/{sid}").json()
        assert detail["segments"], "No transcript was produced"
        assert all(s["translation"] for s in detail["segments"]), "Missing translation"
        assert "neural" in " ".join(s["text"] for s in detail["segments"]).lower()
        for operation in ("summary", "question"):
            start = time.monotonic()
            response = client.post(
                f"/api/sessions/{sid}/actions/summary"
                if operation == "summary"
                else f"/api/sessions/{sid}/questions",
                **(
                    {"json": {"question": "模型训练了多少轮？学习率是多少？请引用录音时间。"}}
                    if operation == "question"
                    else {}
                ),
            )
            response.raise_for_status()
            job = wait(client, response.json()["id"])
            timings[f"{operation}_seconds"] = round(time.monotonic() - start, 2)
            print(operation, job["result"], flush=True)
        detail = client.get(f"/api/sessions/{sid}").json()
        assert detail["summary"]
        assert detail["messages"][0]["answer"]
        for export_format in ("md", "srt", "json"):
            response = client.get(f"/api/sessions/{sid}/export/{export_format}")
            assert response.status_code == 200 and response.content
        result = {
            "session_id": sid,
            "models": status["models"],
            "timings": timings,
            "segments": detail["segments"],
            "summary": detail["summary"],
            "messages": detail["messages"],
            "fixture": "macOS Daniel synthetic English speech",
        }
        (ROOT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print("Integration passed", json.dumps(timings), flush=True)


if __name__ == "__main__":
    main()

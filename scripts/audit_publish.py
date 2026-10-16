"""Check the Git index for private runtime files and common credential patterns.

Only paths and finding categories are printed. Matched values are never logged.
This supplements an explicit source-file allowlist; it is not a secret detector guarantee.
"""

import re
import subprocess
import sys
from pathlib import PurePosixPath

PRIVATE_DIRS = {"data", "models", ".cache", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
PRIVATE_NAMES = {"settings.json", "realtime.json", "verification.json", ".env"}
PRIVATE_SUFFIXES = {
    ".wav", ".mp3", ".m4a", ".aiff", ".mp4", ".webm", ".ogg", ".flac",
    ".litertlm", ".safetensors", ".npz", ".sqlite3", ".db", ".pem", ".key",
    ".p12", ".pfx", ".jpg", ".jpeg", ".png", ".zip", ".pyc",
}
PATTERNS = {
    "API key or access token": re.compile(
        rb"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|"
        rb"github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b"
    ),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "personal model or home path": re.compile(rb"/Users/" + rb"[A-Za-z0-9][^/\s]*/"),
    "workspace identifier": re.compile(rb"\b(?:ws|llm)-[a-z0-9]{10,}\b"),
    "credential in URL": re.compile(rb"https?://[^\s/'\"]+:[^\s/'\"]+@"),
}


def findings(path, content):
    file = PurePosixPath(path)
    results = []
    if (set(file.parts) & PRIVATE_DIRS or file.name in PRIVATE_NAMES
            or file.name.startswith(".env.") or file.suffix.lower() in PRIVATE_SUFFIXES
            or ".sqlite" in file.name):
        results.append("private runtime file")
    results.extend(label for label, pattern in PATTERNS.items() if pattern.search(content))
    return results


def main():
    result = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True)
    paths = [path.decode() for path in result.stdout.split(b"\0") if path]
    if not paths:
        print("No staged/tracked files to audit.", file=sys.stderr)
        return 1
    issues = []
    for path in paths:
        content = subprocess.run(
            ["git", "show", f":{path}"], check=True, capture_output=True,
        ).stdout
        issues.extend((path, label) for label in findings(path, content))
    for path, label in issues:
        print(f"BLOCKED: {path}: {label}")
    if issues:
        return 1
    print(f"Publication audit passed: {len(paths)} indexed files; no flagged private artifacts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

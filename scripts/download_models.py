"""Explicit network step. Application inference only reads these local directories."""

import argparse
import json
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "speech": ("mlx-community/whisper-large-v3-turbo", "whisper"),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=MODELS)
    args = parser.parse_args()
    receipts = {}
    receipt_path = ROOT / "models" / "downloads.json"
    if receipt_path.exists():
        receipts = json.loads(receipt_path.read_text())
    for key, (repo, folder) in MODELS.items():
        if args.only and args.only != key:
            continue
        revision = receipts.get(key, {}).get("revision") or HfApi().model_info(repo).sha
        print(f"Downloading {repo}@{revision} to models/{folder}", flush=True)
        snapshot_download(
            repo_id=repo,
            revision=revision,
            local_dir=ROOT / "models" / folder,
            allow_patterns=["*.json", "*.safetensors", "*.npz", "*.model", "*.txt", "*.jinja"],
            max_workers=3,
        )
        receipts[key] = {"repository": repo, "revision": revision}
        receipt_path.write_text(json.dumps(receipts, indent=2) + "\n")
    print("Models downloaded. You can now run the app without internet.", flush=True)


if __name__ == "__main__":
    main()

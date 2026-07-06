import json
from pathlib import Path
from typing import Any

def load_json(path: str | Path, default: Any) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to read/parse JSON from {path}: {e}")
        return default

def save_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Failed to save JSON to {path}: {e}")

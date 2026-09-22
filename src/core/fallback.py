import json
import os
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
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"Failed to save JSON to {path}: {e}")
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

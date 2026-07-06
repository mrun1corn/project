import asyncio
import json
from pathlib import Path
from typing import Any

from src.core.config import settings  # noqa: F401 to ensure dotenv is loaded
from src.core.database import get_collection


CONFIG_COLLECTION = get_collection("bot_config")
GROUPS_COLLECTION = get_collection("group_data")
GROUP_COMMANDS_COLLECTION = get_collection("group_management_command_states")
NOTES_COLLECTION = get_collection("notes")
NOTES_COMMANDS_COLLECTION = get_collection("notes_command_states")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default


async def migrate_global_config():
    command_states = _load_json(Path("command_states.json"), {}).get("command_states", {})
    approved_users = _load_json(Path("approved_users.json"), [])

    await CONFIG_COLLECTION.update_one(
        {"_id": "global"},
        {"$set": {"command_states": command_states, "approved_users": approved_users}},
        upsert=True,
    )
    print(f"Migrated global command states ({len(command_states)}) and approved users ({len(approved_users)}).")


async def migrate_group_data():
    group_dir = Path("group_data")
    if not group_dir.exists():
        return

    count = 0
    for file in group_dir.glob("*.json"):
        try:
            chat_id = int(file.stem)
        except ValueError:
            continue
        data = _load_json(file, {})
        await GROUPS_COLLECTION.update_one({"_id": chat_id}, {"$set": data}, upsert=True)
        count += 1
    print(f"Migrated {count} group data files.")


async def migrate_group_command_states():
    raw = _load_json(Path("group_management_command_states.json"), {}).get("group_management_commands", {})
    count = 0
    for chat_id_str, states in raw.items():
        try:
            chat_id = int(chat_id_str)
        except ValueError:
            continue
        await GROUP_COMMANDS_COLLECTION.update_one({"_id": chat_id}, {"$set": {"commands": states}}, upsert=True)
        count += 1
    print(f"Migrated group command states for {count} chats.")


async def migrate_notes():
    notes_dir = Path("notes")
    count = 0
    if notes_dir.exists():
        for file in notes_dir.glob("*.json"):
            stem = file.stem
            if stem.startswith("chat_"):
                chat_id_str = stem.replace("chat_", "")
            else:
                chat_id_str = stem
            try:
                chat_id = int(chat_id_str)
            except ValueError:
                continue
            data = _load_json(file, {"group_notes": {}, "user_notes": {}})
            await NOTES_COLLECTION.update_one({"_id": chat_id}, {"$set": data}, upsert=True)
            count += 1

    # Legacy notes_data directory (simple key->value)
    notes_data_dir = Path("notes_data")
    if notes_data_dir.exists():
        for file in notes_data_dir.glob("*.json"):
            try:
                chat_id = int(file.stem)
            except ValueError:
                continue
            legacy_data = _load_json(file, {})
            if legacy_data:
                await NOTES_COLLECTION.update_one(
                    {"_id": chat_id},
                    {"$set": {"legacy_notes_data": legacy_data}},
                    upsert=True,
                )
    print(f"Migrated notes for {count} chats.")


async def migrate_notes_command_states():
    raw = _load_json(Path("notes_command_states.json"), {}).get("notes_commands", {})
    count = 0
    for chat_id_str, states in raw.items():
        try:
            chat_id = int(chat_id_str)
        except ValueError:
            continue
        await NOTES_COMMANDS_COLLECTION.update_one({"_id": chat_id}, {"$set": {"commands": states}}, upsert=True)
        count += 1
    print(f"Migrated notes command states for {count} chats.")


async def main():
    await migrate_global_config()
    await migrate_group_data()
    await migrate_group_command_states()
    await migrate_notes()
    await migrate_notes_command_states()
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())

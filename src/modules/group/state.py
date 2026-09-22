import copy
from src.core.database import get_collection
from src.core.fallback import load_json, save_json
from src.core.registry import get_default_group_commands
from .constants import (
    DEFAULT_GROUP_DATA,
    LOCK_KEY_ALIASES,
    LOCK_LABELS,
    LOCKABLE_TYPES,
)

GROUPS_COLLECTION = get_collection("group_data")
GROUP_COMMANDS_COLLECTION = get_collection("group_management_command_states")
GROUP_COMMANDS = get_default_group_commands()

_group_cache: dict[int, dict] = {}


def _lock_label(lock_type: str) -> str:
    """Format lock names for button labels."""
    return LOCK_LABELS.get(lock_type, lock_type.replace('_', ' ').title())


def _normalize_locks(raw_locks: dict) -> dict:
    """Normalize lock keys coming from disk to the canonical list."""
    if not isinstance(raw_locks, dict):
        return {}

    normalized = {key: False for key in LOCKABLE_TYPES}
    for key, value in raw_locks.items():
        canonical = LOCK_KEY_ALIASES.get(key, key)
        if canonical in LOCKABLE_TYPES:
            normalized[canonical] = bool(value)
    return normalized


async def load_group_command_states(chat_id: int) -> dict:
    try:
        doc = await GROUP_COMMANDS_COLLECTION.find_one({"_id": chat_id})
        if not doc:
            return GROUP_COMMANDS.copy()
        stored = doc.get("commands", {})
    except Exception as exc:
        print(f"Failed to load group command states for {chat_id} from database, falling back to JSON: {exc}")
        all_states = load_json("group_management_command_states.json", {})
        stored = all_states.get("group_management_commands", {}).get(str(chat_id), {})

    states = GROUP_COMMANDS.copy()
    states.update({name: bool(value) for name, value in stored.items() if name in GROUP_COMMANDS})
    return states


async def save_group_command_states(chat_id: int, states: dict) -> None:
    try:
        await GROUP_COMMANDS_COLLECTION.update_one(
            {"_id": chat_id},
            {"$set": {"commands": states}},
            upsert=True,
        )
    except Exception as exc:
        print(f"Failed to save group command states for {chat_id} to database, falling back to JSON: {exc}")

    all_states = load_json("group_management_command_states.json", {})
    all_states.setdefault("group_management_commands", {})[str(chat_id)] = states
    save_json("group_management_command_states.json", all_states)


async def load_group(chat_id: int) -> dict:
    if chat_id in _group_cache:
        return _group_cache[chat_id]

    doc = None
    try:
        doc = await GROUPS_COLLECTION.find_one({"_id": chat_id})
    except Exception as exc:
        print(f"Failed to load group {chat_id} from database, falling back to JSON: {exc}")
        doc = load_json(f"group_data/{chat_id}.json", None)

    group_data = copy.deepcopy(DEFAULT_GROUP_DATA)
    if doc:
        doc_data = {k: v for k, v in doc.items() if k != "_id"}
        group_data.update(doc_data)
    group_data['locks'] = _normalize_locks(group_data.get('locks', {}))

    _group_cache[chat_id] = group_data
    return group_data


async def save_group(chat_id: int, data: dict) -> None:
    _group_cache[chat_id] = data
    to_store = data.copy()
    try:
        await GROUPS_COLLECTION.update_one({"_id": chat_id}, {"$set": to_store}, upsert=True)
    except Exception as exc:
        print(f"Failed to save group {chat_id} to database, falling back to JSON: {exc}")
    save_json(f"group_data/{chat_id}.json", to_store)

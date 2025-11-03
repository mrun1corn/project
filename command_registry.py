"""Central registry for default command states across the bot."""

from __future__ import annotations

from copy import deepcopy


def _freeze(data: dict[str, bool]) -> dict[str, bool]:
    """Return a shallow copy of command defaults to avoid accidental mutation."""
    return deepcopy(data)


_GLOBAL_COMMANDS: dict[str, bool] = {
    "ai": True,
    "bgremove": True,
    "help": True,
    "kang": True,
    "music": True,
    "ping": True,
    "reboot": True,
    "reel": True,
    "shell": True,
    "speedtest": True,
    "video": True,
}

_GROUP_MANAGEMENT_COMMANDS: dict[str, bool] = {
    "welcome": True,
    "goodbye": True,
    "filter": True,
    "stop": True,
    "mute": True,
    "tmute": True,
    "unmute": True,
    "kick": True,
    "ban": True,
    "tban": True,
    "unban": True,
    "warn": True,
    "warns": True,
    "warnlimit": True,
    "warnmode": True,
    "locks": True,
    "pin": True,
    "action": True,
    "promote": True,
    "demote": True,
    "permissions": True,
    "tagadmin": True,
    "purge": True,
}

_NOTES_COMMANDS: dict[str, bool] = {
    "keep": True,
    "notes": True,
    "delete": True,
    "getnote": True,
}


def get_default_global_commands() -> dict[str, bool]:
    """Return the default enabled state for all global commands."""
    return _freeze(_GLOBAL_COMMANDS)


def get_default_group_commands() -> dict[str, bool]:
    """Return the default enabled state for group management commands."""
    return _freeze(_GROUP_MANAGEMENT_COMMANDS)


def get_default_notes_commands() -> dict[str, bool]:
    """Return the default enabled state for notes commands."""
    return _freeze(_NOTES_COMMANDS)


def get_all_command_defaults() -> dict[str, dict[str, bool]]:
    """Return a combined mapping of all command defaults grouped by category."""
    return {
        "global": get_default_global_commands(),
        "group": get_default_group_commands(),
        "notes": get_default_notes_commands(),
    }

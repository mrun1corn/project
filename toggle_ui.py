from __future__ import annotations

from collections.abc import Iterable, Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def toggle_text(enabled: bool) -> str:
    return "On" if enabled else "Off"


def build_toggle_keyboard(
    items: Iterable[tuple[str, bool, str]],
    *,
    columns: int = 2,
    extra_rows: Sequence[Sequence[InlineKeyboardButton]] | None = None,
) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for index, (label, enabled, callback_data) in enumerate(items, start=1):
        row.append(
            InlineKeyboardButton(
                f"{toggle_text(enabled)} {label}",
                callback_data=callback_data,
            )
        )
        if index % columns == 0:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    if extra_rows:
        keyboard.extend([list(extra_row) for extra_row in extra_rows])

    return InlineKeyboardMarkup(keyboard)

"""History and the current sheet, kept in the project's data/ folder."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("PASCALINE_DATA", ROOT / "data"))
HISTORY = DATA / "history.txt"
SHEET = DATA / "sheet.json"
MAX_HISTORY = 5000


def load_history() -> list[str]:
    try:
        return HISTORY.read_text().splitlines()[-MAX_HISTORY:]
    except OSError:
        return []


def append_history(line: str, history: list[str]) -> None:
    if not line.strip() or (history and history[-1] == line):
        return
    history.append(line)
    DATA.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a") as f:
        f.write(line.replace("\n", " ") + "\n")


def load_sheet() -> dict:
    try:
        data = json.loads(SHEET.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def sheet_cells(sheet: dict) -> list[tuple[str, bool]]:
    """(source, hidden) pairs; hidden cells were cleared from view but still run."""
    out = []
    for c in sheet.get("cells", []):
        if isinstance(c, str):
            out.append((c, False))
        elif isinstance(c, dict) and isinstance(c.get("src"), str):
            out.append((c["src"], bool(c.get("hidden"))))
    return out


def save_sheet(cells: list[tuple[str, bool]], degrees: bool, digits: int) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = SHEET.with_suffix(".tmp")
    data = [{"src": src, "hidden": True} if hidden else {"src": src} for src, hidden in cells]
    tmp.write_text(json.dumps({"cells": data, "degrees": degrees, "digits": digits}, indent=1))
    tmp.replace(SHEET)

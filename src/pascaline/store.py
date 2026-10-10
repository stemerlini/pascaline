"""History and named sheets, kept in the project's data/ folder."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("PASCALINE_DATA", ROOT / "data"))
HISTORY = DATA / "history.txt"
SHEETS = DATA / "sheets"
STATE = DATA / "state.json"
EXPORTS = DATA / "exports"
MAX_HISTORY = 5000
DEFAULT_SHEET = "main"
NAME_RE = re.compile(r"^[\w][\w .+-]{0,39}$")


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


# -- sheets ----------------------------------------------------------------


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name)) and name not in (".", "..")


def _path(name: str) -> Path:
    return SHEETS / f"{name}.json"


def _migrate() -> None:
    """Before named sheets there was one data/sheet.json; it becomes 'main'."""
    old = DATA / "sheet.json"
    if old.exists() and not _path(DEFAULT_SHEET).exists():
        SHEETS.mkdir(parents=True, exist_ok=True)
        old.replace(_path(DEFAULT_SHEET))


def current_sheet() -> str:
    _migrate()
    try:
        name = json.loads(STATE.read_text()).get("sheet", DEFAULT_SHEET)
    except (OSError, ValueError, AttributeError):
        name = DEFAULT_SHEET
    return name if isinstance(name, str) and valid_name(name) else DEFAULT_SHEET


def set_current_sheet(name: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"sheet": name}))


def list_sheets() -> list[str]:
    """Sheet names, most recently used first."""
    _migrate()
    files = sorted(SHEETS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if SHEETS.exists() else []
    return [p.stem for p in files]


def load_sheet(name: str = DEFAULT_SHEET) -> dict:
    _migrate()
    try:
        data = json.loads(_path(name).read_text())
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


def save_sheet(name: str, cells: list[tuple[str, bool]], degrees: bool, digits: int) -> None:
    SHEETS.mkdir(parents=True, exist_ok=True)
    path = _path(name)
    tmp = path.with_suffix(".tmp")
    data = [{"src": src, "hidden": True} if hidden else {"src": src} for src, hidden in cells]
    tmp.write_text(json.dumps({"cells": data, "degrees": degrees, "digits": digits}, indent=1))
    tmp.replace(path)


def rename_sheet(old: str, new: str) -> None:
    if _path(new).exists():
        raise FileExistsError(new)
    if _path(old).exists():
        _path(old).replace(_path(new))


def delete_sheet(name: str) -> None:
    _path(name).unlink(missing_ok=True)

"""Load known_bugs.yaml (simple subset) and match log lines."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("mm.known_bugs")


def _parse_simple_yaml(text: str) -> list[dict[str, Any]]:
    """
    Minimal parser for:
    bugs:
      - id: X
        title: Y
        status: open
        symptoms:
          - "foo"
        notes: bar
    """
    bugs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_symptoms = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^bugs\s*:\s*$", line):
            continue
        m_bug = re.match(r"^-\s+id\s*:\s*(.+)$", line.strip())
        if line.lstrip().startswith("- id:") or m_bug:
            if current:
                bugs.append(current)
            # handle "- id: value"
            rest = line.strip()[1:].strip()  # drop leading -
            if rest.startswith("id:"):
                val = rest[3:].strip().strip("\"'")
                current = {"id": val, "symptoms": [], "status": "open"}
            in_symptoms = False
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("title:"):
            current["title"] = stripped[6:].strip().strip("\"'")
            in_symptoms = False
        elif stripped.startswith("status:"):
            current["status"] = stripped[7:].strip().strip("\"'")
            in_symptoms = False
        elif stripped.startswith("notes:"):
            current["notes"] = stripped[6:].strip().strip("\"'")
            in_symptoms = False
        elif stripped.startswith("symptoms:"):
            in_symptoms = True
            current.setdefault("symptoms", [])
        elif in_symptoms and stripped.startswith("- "):
            current.setdefault("symptoms", []).append(
                stripped[2:].strip().strip("\"'")
            )
        elif stripped.startswith("id:"):
            current["id"] = stripped[3:].strip().strip("\"'")
    if current:
        bugs.append(current)
    return bugs


class KnownBugMatcher:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.bugs: list[dict[str, Any]] = []
        self._patterns: list[tuple[dict[str, Any], re.Pattern[str]]] = []
        self.reload()

    def reload(self) -> None:
        self.bugs = []
        self._patterns = []
        if not self.path.is_file():
            return
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
            self.bugs = _parse_simple_yaml(text)
        except OSError as e:
            log.warning("could not read known bugs: %s", e)
            return
        for bug in self.bugs:
            if str(bug.get("status", "open")).lower() not in ("open", ""):
                continue
            for sym in bug.get("symptoms") or []:
                try:
                    self._patterns.append((bug, re.compile(sym, re.I)))
                except re.error:
                    self._patterns.append((bug, re.compile(re.escape(sym), re.I)))

    def match_line(self, line: str) -> dict[str, Any] | None:
        for bug, pat in self._patterns:
            if pat.search(line):
                return bug
        return None

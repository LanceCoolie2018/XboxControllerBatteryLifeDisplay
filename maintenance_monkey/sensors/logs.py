"""Tail log files for exceptions and pattern matches."""

from __future__ import annotations

import glob
import logging
import os
from pathlib import Path

from maintenance_monkey.config import Config
from maintenance_monkey.patterns import (
    DEFAULT_INCLUDE,
    StackAssembler,
    compile_patterns,
    line_matches,
)
from maintenance_monkey.pipeline.fingerprint import fingerprint_stack, fingerprint_text
from maintenance_monkey.pipeline.queue import enqueue_incident
from maintenance_monkey.sensors.known_bugs import KnownBugMatcher
from maintenance_monkey.state import State

log = logging.getLogger("mm.logs")


class LogTailer:
    def __init__(
        self,
        cfg: Config,
        state: State,
        known: KnownBugMatcher | None = None,
    ) -> None:
        self.cfg = cfg
        self.state = state
        self.known = known
        include = cfg.patterns.include or DEFAULT_INCLUDE
        self.include = compile_patterns(include)
        self.exclude = compile_patterns(cfg.patterns.exclude)
        self._positions: dict[str, tuple[int, int]] = {}  # path -> (inode, offset)
        self._assemblers: dict[str, StackAssembler] = {}
        self._recent_window: dict[str, list[str]] = {}

        if not cfg.logs.from_start:
            for path in self._resolve_paths():
                try:
                    st = os.stat(path)
                    self._positions[path] = (st.st_ino, st.st_size)
                except OSError:
                    pass

    def _resolve_paths(self) -> list[str]:
        found: list[str] = []
        root = self.cfg.project.root
        for pattern in self.cfg.logs.paths:
            p = Path(pattern)
            if p.is_absolute():
                matches = glob.glob(pattern, recursive=True)
            else:
                matches = glob.glob(str(root / pattern), recursive=True)
            for m in matches:
                if os.path.isfile(m):
                    found.append(os.path.realpath(m))
        return sorted(set(found))

    def poll(self) -> list[str]:
        messages: list[str] = []
        for path in self._resolve_paths():
            messages.extend(self._poll_file(path))
        return messages

    def _poll_file(self, path: str) -> list[str]:
        messages: list[str] = []
        try:
            st = os.stat(path)
        except OSError:
            return messages

        inode, size = st.st_ino, st.st_size
        prev = self._positions.get(path)
        if prev is None:
            # new file mid-run: start at end unless from_start
            offset = 0 if self.cfg.logs.from_start else size
            self._positions[path] = (inode, offset)
            return messages

        prev_ino, prev_off = prev
        if inode != prev_ino or size < prev_off:
            # rotated or truncated
            prev_off = 0

        if size == prev_off:
            return messages

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(prev_off)
                data = f.read()
                new_off = f.tell()
        except OSError as e:
            log.warning("read %s failed: %s", path, e)
            return messages

        self._positions[path] = (inode, new_off)
        assembler = self._assemblers.setdefault(path, StackAssembler())
        window = self._recent_window.setdefault(path, [])

        for line in data.splitlines():
            window.append(line)
            if len(window) > 50:
                del window[:-50]

            stack = assembler.feed(line)
            if stack:
                messages.extend(self._emit_stack(path, stack, window))
                continue

            # known bug symptoms
            if self.known:
                bug = self.known.match_line(line)
                if bug:
                    messages.extend(self._emit_known(path, bug, line, window))
                    continue

            if line_matches(line, self.include, self.exclude):
                # avoid double-firing if we're mid-stack
                if not assembler._active:
                    messages.extend(self._emit_line(path, line, window))

        return messages

    def _emit_stack(self, path: str, stack: str, window: list[str]) -> list[str]:
        fp = fingerprint_stack(stack)
        title = f"Stack in {os.path.basename(path)}"
        # first non-empty line often has the type
        for ln in stack.splitlines():
            if "Error" in ln or "Exception" in ln or "panic" in ln.lower():
                title = ln.strip()[:100]
                break
        body = (
            f"# Stack trace from log\n\n"
            f"**File:** `{path}`\n\n"
            f"## Stack\n```\n{stack}\n```\n\n"
            f"## Recent log window\n```\n" + "\n".join(window[-40:]) + "\n```\n"
        )
        _, job, msg = enqueue_incident(
            self.state,
            self.cfg,
            source="log_stack",
            fingerprint=fp,
            title=title,
            body=body,
            meta={"path": path},
        )
        return [f"log stack {path}: {msg}"] if job or msg else []

    def _emit_line(self, path: str, line: str, window: list[str]) -> list[str]:
        fp = fingerprint_text("logline", line)
        title = line.strip()[:100] or "log match"
        body = (
            f"# Log line match\n\n"
            f"**File:** `{path}`\n\n"
            f"**Line:** {line}\n\n"
            f"## Recent log window\n```\n" + "\n".join(window[-40:]) + "\n```\n"
        )
        _, job, msg = enqueue_incident(
            self.state,
            self.cfg,
            source="log_line",
            fingerprint=fp,
            title=title,
            body=body,
            meta={"path": path},
        )
        return [f"log line {path}: {msg}"]

    def _emit_known(
        self, path: str, bug: dict, line: str, window: list[str]
    ) -> list[str]:
        bug_id = bug.get("id") or "unknown"
        fp = fingerprint_text("known", f"{bug_id}:{line}")
        title = f"Known bug {bug_id}: {bug.get('title', '')}"[:100]
        body = (
            f"# Known bug signature match\n\n"
            f"**Bug id:** {bug_id}\n"
            f"**Title:** {bug.get('title')}\n"
            f"**Notes:** {bug.get('notes', '')}\n"
            f"**File:** `{path}`\n"
            f"**Line:** {line}\n\n"
            f"## Recent log window\n```\n" + "\n".join(window[-40:]) + "\n```\n"
        )
        _, job, msg = enqueue_incident(
            self.state,
            self.cfg,
            source="known_bug",
            fingerprint=fp,
            title=title,
            body=body,
            meta={"path": path, "bug_id": bug_id},
        )
        return [f"known bug {bug_id}: {msg}"]

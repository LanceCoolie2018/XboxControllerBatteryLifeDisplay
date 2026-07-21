"""Parse and watch UserReport.md checklist items."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from maintenance_monkey.config import Config
from maintenance_monkey.pipeline.fingerprint import fingerprint_id, fingerprint_text
from maintenance_monkey.pipeline.queue import enqueue_incident
from maintenance_monkey.state import State

log = logging.getLogger("mm.user_report")

# - [ ] title
# - [ ] [id] title
# - [x] done
ITEM_RE = re.compile(
    r"""^
    \s*[-*]\s*
    \[
      (?P<check>[ xX])
    \]\s*
    (?:\[(?P<id>[^\]]+)\]\s*)?
    (?P<title>.+?)
    \s*$
    """,
    re.VERBOSE,
)


@dataclass
class UserReportItem:
    checked: bool
    item_id: str | None
    title: str
    line_no: int
    raw: str

    @property
    def fingerprint(self) -> str:
        if self.item_id:
            return fingerprint_id("userreport", self.item_id)
        return fingerprint_text("userreport", self.title)


def parse_user_report(text: str) -> tuple[list[UserReportItem], str]:
    """Return (items, notes_blob). Notes = non-checklist content."""
    items: list[UserReportItem] = []
    notes_lines: list[str] = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = ITEM_RE.match(line)
        if m:
            items.append(
                UserReportItem(
                    checked=m.group("check").lower() == "x",
                    item_id=(m.group("id") or None),
                    title=m.group("title").strip(),
                    line_no=i,
                    raw=line,
                )
            )
        else:
            notes_lines.append(line)
    notes = "\n".join(notes_lines).strip()
    return items, notes


def open_items(text: str) -> tuple[list[UserReportItem], str]:
    items, notes = parse_user_report(text)
    return [i for i in items if not i.checked], notes


def scan_user_report(
    cfg: Config,
    state: State,
    *,
    trigger: str = "manual",
) -> list[str]:
    """Parse UserReport and enqueue open items. Returns status messages."""
    path = cfg.project.root / cfg.user_report.path
    messages: list[str] = []
    if not cfg.user_report.enabled:
        return ["user_report disabled"]
    if not path.is_file():
        return [f"UserReport not found: {path}"]

    if cfg.user_report.pull_before_scan:
        from maintenance_monkey.dispatch import git_workflow

        msg = git_workflow.ff_pull(cfg)
        messages.append(msg)

    text = path.read_text(encoding="utf-8", errors="replace")
    opens, notes = open_items(text)
    if not opens:
        messages.append("no open UserReport items")
        return messages

    for item in opens:
        body_parts = [
            f"# UserReport item",
            f"",
            f"**Title:** {item.title}",
            f"**Line:** {item.line_no}",
            f"**Id:** {item.item_id or '(none)'}",
            f"**Trigger:** {trigger}",
            f"",
            f"## Item",
            item.raw,
            f"",
            f"## Full UserReport notes (non-checklist)",
            notes or "(none)",
            f"",
            f"## Full UserReport file",
            "```markdown",
            text,
            "```",
        ]
        body = "\n".join(body_parts)
        title = f"UserReport: {item.title[:80]}"
        _, job, msg = enqueue_incident(
            state,
            cfg,
            source="user_report",
            fingerprint=item.fingerprint,
            title=title,
            body=body,
            meta={
                "item_id": item.item_id,
                "line_no": item.line_no,
                "trigger": trigger,
                "path": str(path),
            },
        )
        messages.append(f"{item.title[:60]}: {msg}")
        if job:
            log.info("UserReport item queued as job %s", job.id)
    return messages


class UserReportWatcher:
    """Daemon helper: re-scan when mtime changes."""

    def __init__(self, cfg: Config, state: State) -> None:
        self.cfg = cfg
        self.state = state
        self._mtime: float | None = None
        self._pending_since: float | None = None

    def poll(self, now: float) -> list[str]:
        if not self.cfg.user_report.enabled:
            return []
        path = self.cfg.project.root / self.cfg.user_report.path
        if not path.is_file():
            return []
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return []

        if self._mtime is None:
            self._mtime = mtime
            return []

        if mtime != self._mtime:
            self._mtime = mtime
            self._pending_since = now
            return []

        if self._pending_since is None:
            return []

        if now - self._pending_since < self.cfg.user_report.debounce_seconds:
            return []

        self._pending_since = None
        return scan_user_report(self.cfg, self.state, trigger="daemon")

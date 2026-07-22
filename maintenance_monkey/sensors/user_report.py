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
# Title must start with a non-whitespace char so "- [ ] " alone is not an item.
ITEM_RE = re.compile(
    r"""^
    \s*[-*]\s*
    \[
      (?P<check>[ xX])
    \]\s*
    (?:\[(?P<id>[^\]]+)\]\s*)?
    (?P<title>\S.*?)
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
    # Skip blank titles (e.g. accidental "- [ ] " lines) — nothing to fix.
    return [i for i in items if not i.checked and i.title.strip()], notes


def mark_item_checked(
    path: Path,
    *,
    item_id: str | None = None,
    title: str | None = None,
    fingerprint: str | None = None,
) -> tuple[bool, str]:
    """
    Flip the first matching open checklist line to - [x].

    Match order: stable [id], then fingerprint (title hash), then exact title.
    Returns (changed, message).
    """
    if not path.is_file():
        return False, f"UserReport not found: {path}"

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    if not lines and text:
        lines = [text]

    changed = False
    new_lines: list[str] = []
    for line in lines:
        # Preserve original line ending
        raw = line.rstrip("\r\n")
        ending = line[len(raw) :]
        m = ITEM_RE.match(raw)
        if not m or changed:
            new_lines.append(line)
            continue
        checked = m.group("check").lower() == "x"
        if checked:
            new_lines.append(line)
            continue

        mid = (m.group("id") or None)
        mtitle = m.group("title").strip()
        item = UserReportItem(
            checked=False,
            item_id=mid,
            title=mtitle,
            line_no=0,
            raw=raw,
        )

        match = False
        if item_id and mid and mid == item_id:
            match = True
        elif fingerprint and item.fingerprint == fingerprint:
            match = True
        elif title and mtitle == title.strip():
            match = True
        elif title and mtitle.lower() == title.strip().lower():
            match = True

        if not match:
            new_lines.append(line)
            continue

        # Replace first [ ] or [ ] with [x] after the list marker
        marked = re.sub(
            r"^(\s*[-*]\s*)\[[ ]\]",
            r"\1[x]",
            raw,
            count=1,
        )
        if marked == raw:
            # already x or odd spacing
            new_lines.append(line)
            continue
        new_lines.append(marked + ending)
        changed = True
        log.info("checked UserReport item: %s", marked.strip())

    if not changed:
        return False, "no matching open UserReport item to check"

    path.write_text("".join(new_lines), encoding="utf-8")
    return True, f"checked item in {path.name}"


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

    ignore_pats = []
    for pat in cfg.user_report.ignore or []:
        try:
            ignore_pats.append(re.compile(pat))
        except re.error:
            ignore_pats.append(re.compile(re.escape(pat), re.I))

    for item in opens:
        if not item.title.strip():
            messages.append(f"line {item.line_no}: skipped empty checklist title")
            log.info("skipping empty UserReport item at line %s", item.line_no)
            continue
        if ignore_pats and any(
            p.search(item.title) or (item.item_id and p.search(item.item_id))
            for p in ignore_pats
        ):
            messages.append(f"{item.title[:60]}: ignored by config")
            log.info("ignoring UserReport item: %s", item.title[:80])
            continue
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

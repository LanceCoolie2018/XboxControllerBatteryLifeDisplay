"""Live terminal dashboard for Maintenance Monkey activity."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from maintenance_monkey import __version__
from maintenance_monkey.config import Config
from maintenance_monkey.sensors.user_report import open_items
from maintenance_monkey.state import Job, State

# ANSI
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
WHITE = "\033[37m"


def _use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    if not _use_color():
        return text
    return f"{code}{text}{RESET}"


def _clear() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def _age(ts: float) -> str:
    if not ts:
        return "-"
    secs = max(0, int(time.time() - ts))
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _status_color(status: str) -> str:
    s = (status or "").lower()
    if s in ("running", "pushing"):
        return YELLOW
    if s in ("queued",):
        return CYAN
    if s in ("done",):
        return GREEN
    if s in ("failed", "cancelled"):
        return RED
    return WHITE


def _daemon_info(cfg: Config) -> tuple[bool, str]:
    if not cfg.pidfile.is_file():
        return False, "stopped"
    try:
        pid = int(cfg.pidfile.read_text().strip())
    except (ValueError, OSError):
        return False, "stopped (bad pidfile)"
    try:
        os.kill(pid, 0)
        return True, f"running  pid={pid}"
    except OSError:
        return False, f"stopped (stale pid {pid})"


def _git_line(root: Path) -> str:
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        sb = subprocess.run(
            ["git", "status", "-sb"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip().splitlines()
        tracking = sb[0] if sb else ""
        return f"{branch or '?'} @ {head}  {tracking}"
    except (OSError, subprocess.TimeoutExpired):
        return "(git unavailable)"


def _job_title(state: State, job: Job, limit: int = 60) -> str:
    inc = state.get_incident(job.incident_id)
    if not inc:
        return "(no title)"
    t = inc.title
    if t.startswith("UserReport: "):
        t = t[len("UserReport: ") :]
    return t[:limit]


def _short_pr(url: str) -> str:
    return url.replace("https://github.com/", "")


def _user_report_open(cfg: Config) -> list[str]:
    path = cfg.project.root / cfg.user_report.path
    if not path.is_file():
        return ["(UserReport.md missing)"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        items, _ = open_items(text)
        if not items:
            return ["(no open checklist items)"]
        lines = []
        for it in items[:10]:
            tag = f"[{it.item_id}] " if it.item_id else ""
            lines.append(f"• {tag}{it.title[:70]}")
        if len(items) > 10:
            lines.append(f"  … +{len(items) - 10} more")
        return lines
    except OSError as e:
        return [f"(error: {e})"]


def _box_title(title: str, width: int) -> str:
    t = f" {title} "
    fill = max(0, width - len(t) - 2)
    left = fill // 2
    right = fill - left
    return _c(DIM, "─" * left) + _c(BOLD + CYAN, t) + _c(DIM, "─" * right)


def render_frame(cfg: Config, state: State, *, interval: float) -> str:
    cols = shutil.get_terminal_size((100, 40)).columns
    width = max(60, min(cols, 120))

    alive, daemon_txt = _daemon_info(cfg)
    daemon_disp = _c(GREEN if alive else RED, daemon_txt)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []

    header = (
        f"{_c(BOLD + MAGENTA, '🐵 Maintenance Monkey')}"
        f"  {_c(DIM, 'v' + __version__)}"
        f"  {_c(BOLD, cfg.project.name)}"
    )
    lines.append(header)
    lines.append(_c(DIM, f"  {now}  ·  refresh {interval:g}s  ·  Ctrl+C to exit"))
    lines.append("")

    # Overview
    lines.append(_box_title("OVERVIEW", width))
    lines.append(f"  Daemon     {daemon_disp}")
    lines.append(f"  Branch     {_git_line(cfg.project.root)}")
    lines.append(
        f"  PR base    {_c(CYAN, cfg.project.default_branch or '?')}"
        f"  ·  fixes {_c(CYAN, cfg.dispatch.branch_prefix + '*')}"
    )
    lines.append("")

    jobs = state.list_jobs(40)
    active = [j for j in jobs if j.status in ("queued", "running", "pushing")]
    # Done with a PR URL = waiting for you to review/merge
    review = [j for j in jobs if j.status == "done" and j.pr_url]
    failed = [j for j in jobs if j.status == "failed"]

    # —— ACTIVE WORK ——
    lines.append(_box_title("ACTIVE WORK", width))
    if not active:
        lines.append(_c(DIM, "  (idle — nothing queued or running)"))
    else:
        for j in active:
            st = _c(_status_color(j.status) + BOLD, f"{j.status:8}")
            title = _job_title(state, j, 58)
            branch = j.branch or "(pending branch)"
            lines.append(f"  {st}  {_c(BOLD, title)}")
            lines.append(
                f"           id={j.id}  branch={_c(CYAN, branch)}"
                f"  {_c(DIM, _age(j.updated_at))}"
            )
    lines.append("")

    # —— READY FOR REVIEW ——
    lines.append(_box_title("READY FOR REVIEW", width))
    if not review:
        lines.append(_c(DIM, "  (no open PRs from the monkey yet)"))
    else:
        for j in review[:12]:
            title = _job_title(state, j, 55)
            pr = _short_pr(j.pr_url or "")
            branch = j.branch or "-"
            lines.append(f"  {_c(GREEN + BOLD, 'PR')}  {_c(BOLD, title)}")
            lines.append(f"       {_c(GREEN, pr)}")
            lines.append(
                f"       branch={_c(CYAN, branch)}"
                f"  id={j.id}  {_c(DIM, _age(j.updated_at))}"
            )
        if len(review) > 12:
            lines.append(_c(DIM, f"  … +{len(review) - 12} more"))
    lines.append("")

    # Failed (compact — only if any)
    if failed:
        lines.append(_box_title("FAILED", width))
        for j in failed[:5]:
            title = _job_title(state, j, 50)
            err = (j.error or "")[:50]
            lines.append(f"  {_c(RED, 'fail')}  {title}")
            if err:
                lines.append(f"       {_c(RED, err)}")
        lines.append("")

    # Open UserReport checklist (what's still unchecked on AssIsstant)
    lines.append(_box_title("USER REPORT (open)", width))
    for row in _user_report_open(cfg):
        lines.append(f"  {row}")

    lines.append("")
    lines.append(
        _c(
            DIM,
            "  merge PRs on GitHub · mark [x] in UserReport after merge · push AssIsstant",
        )
    )
    return "\n".join(lines) + "\n"


def run_dashboard(cfg: Config, state: State, *, interval: float = 2.0) -> int:
    """Block and redraw until Ctrl+C."""
    interval = max(0.5, float(interval))
    try:
        while True:
            state = State(cfg.state_db)
            frame = render_frame(cfg, state, interval=interval)
            _clear()
            sys.stdout.write(frame)
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        return 0

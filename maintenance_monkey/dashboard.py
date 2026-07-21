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
from maintenance_monkey.state import State

# ANSI
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
WHITE = "\033[37m"
BG_DARK = "\033[48;5;235m"


def _use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    if not _use_color():
        return text
    return f"{code}{text}{RESET}"


def _clear() -> None:
    # Clear screen + home cursor (works in lxterminal)
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


def _tail_log(path: Path, n: int = 8) -> list[str]:
    if not path.is_file():
        return ["(no monkey.log yet)"]
    try:
        # Efficient-ish tail for small logs
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return data[-n:] if data else ["(empty log)"]
    except OSError as e:
        return [f"(read error: {e})"]


def _user_report_open(cfg: Config) -> list[str]:
    path = cfg.project.root / cfg.user_report.path
    if not path.is_file():
        return ["(UserReport.md missing)"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        items, _ = open_items(text)
        if not items:
            return ["(no open items)"]
        lines = []
        for it in items[:8]:
            tag = f"[{it.item_id}] " if it.item_id else ""
            lines.append(f"• {tag}{it.title[:70]}")
        if len(items) > 8:
            lines.append(f"  … +{len(items) - 8} more")
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
    lines.append(f"  Project    {cfg.project.root}")
    lines.append(f"  Branch     {_git_line(cfg.project.root)}")
    lines.append(
        f"  Base/PR    {_c(CYAN, cfg.project.default_branch or '?')}"
        f"  ·  fix prefix {_c(CYAN, cfg.dispatch.branch_prefix)}"
    )
    dry = _c(YELLOW, "ON") if cfg.dispatch.dry_run else _c(GREEN, "off")
    lines.append(f"  dry_run    {dry}  ·  max concurrent {cfg.dispatch.max_concurrent_jobs}")
    lines.append("")

    # Active work
    jobs = state.list_jobs(20)
    active = [j for j in jobs if j.status in ("queued", "running", "pushing")]
    lines.append(_box_title("ACTIVE WORK", width))
    if not active:
        lines.append(_c(DIM, "  (idle — nothing queued or running)"))
    else:
        for j in active:
            st = _c(_status_color(j.status) + BOLD, f"{j.status:8}")
            title = ""
            inc = state.get_incident(j.incident_id)
            if inc:
                title = inc.title[:55]
            branch = j.branch or "-"
            lines.append(f"  {st}  {_c(BOLD, j.id)}  {title}")
            lines.append(f"           branch={_c(CYAN, branch)}  {_c(DIM, _age(j.updated_at))}")
    lines.append("")

    # Recent jobs
    lines.append(_box_title("RECENT JOBS", width))
    if not jobs:
        lines.append(_c(DIM, "  (no jobs yet)"))
    else:
        for j in jobs[:8]:
            st = _c(_status_color(j.status), f"{j.status:8}")
            pr = ""
            if j.pr_url:
                pr = _c(GREEN, "  " + j.pr_url.replace("https://github.com/", ""))
            err = ""
            if j.error:
                err = _c(RED, f"  {j.error[:40]}")
            lines.append(
                f"  {st}  {j.id}  {_c(DIM, _age(j.created_at))}{pr}{err}"
            )
    lines.append("")

    # UserReport
    lines.append(_box_title("USER REPORT (open)", width))
    for row in _user_report_open(cfg):
        lines.append(f"  {row}")
    lines.append("")

    # Log
    log_path = cfg.logs_dir / "monkey.log"
    lines.append(_box_title("MONKEY LOG (tail)", width))
    for row in _tail_log(log_path, 10):
        # dim noisy prefixes slightly
        short = row if len(row) <= width - 4 else row[: width - 7] + "..."
        lines.append(_c(DIM, "  " + short))

    lines.append("")
    lines.append(
        _c(
            DIM,
            "  tips:  mm status · mm job show <id> · mm stop · edit UserReport.md on AssIsstant",
        )
    )
    return "\n".join(lines) + "\n"


def run_dashboard(cfg: Config, state: State, *, interval: float = 2.0) -> int:
    """Block and redraw until Ctrl+C."""
    interval = max(0.5, float(interval))
    try:
        while True:
            # Re-open state each frame so we see concurrent daemon writes
            state = State(cfg.state_db)
            frame = render_frame(cfg, state, interval=interval)
            _clear()
            sys.stdout.write(frame)
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        return 0

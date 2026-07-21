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


# Cache remote heads so we don't hit the network every 2s refresh
_remote_heads_cache: tuple[float, set[str]] | None = None
_REMOTE_HEADS_TTL = 20.0


def _remote_heads(root: Path) -> set[str]:
    """Branch names currently on origin (e.g. AssIsstant-fix-abc)."""
    global _remote_heads_cache
    now = time.time()
    if _remote_heads_cache and (now - _remote_heads_cache[0]) < _REMOTE_HEADS_TTL:
        return _remote_heads_cache[1]
    heads: set[str] = set()
    try:
        r = subprocess.run(
            ["git", "ls-remote", "--heads", "origin"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if r.returncode == 0 and r.stdout:
            for line in r.stdout.splitlines():
                # <sha>\trefs/heads/<name>
                parts = line.split()
                if len(parts) >= 2 and parts[1].startswith("refs/heads/"):
                    heads.add(parts[1][len("refs/heads/") :])
    except (OSError, subprocess.TimeoutExpired):
        # Fall back to previous cache if any
        if _remote_heads_cache:
            return _remote_heads_cache[1]
    _remote_heads_cache = (now, heads)
    return heads


def _local_heads(root: Path) -> set[str]:
    try:
        r = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if r.returncode != 0:
            return set()
        return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}
    except (OSError, subprocess.TimeoutExpired):
        return set()


def _branch_still_present(root: Path, branch: str | None, remote: set[str]) -> bool:
    """True if fix branch still exists on origin (or locally if remote list empty)."""
    if not branch:
        return False
    if remote:
        return branch in remote
    # Offline / ls-remote failed: use local branches only
    return branch in _local_heads(root)


def archive_done_jobs_without_branches(cfg: Config, state: State) -> int:
    """Mark done+PR jobs as archived when their fix branch is gone.

    Returns number of jobs archived. Keeps Ready for Review in sync with
    deleted remote branches after you merge and delete.
    """
    remote = _remote_heads(cfg.project.root)
    if not remote and not _local_heads(cfg.project.root):
        return 0
    n = 0
    for job in state.list_jobs(100):
        if job.status != "done" or not job.pr_url:
            continue
        if _branch_still_present(cfg.project.root, job.branch, remote):
            continue
        state.update_job(
            job.id,
            status="archived",
            error=None,
            meta={**(job.meta or {}), "archived_reason": "branch_deleted"},
        )
        n += 1
    return n


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
    work = (cfg.dispatch.work_branch or "AssIsstant").strip()
    base = cfg.project.default_branch or "?"

    lines.append(_box_title("OVERVIEW", width))
    lines.append(f"  Daemon     {daemon_disp}")
    lines.append(f"  Checkout   {_git_line(cfg.project.root)}")
    lines.append(
        f"  Work on    {_c(CYAN, work)}"
        f"  ·  merge to {_c(CYAN, base)} when you are ready"
    )
    lines.append("")

    jobs = state.list_jobs(40)
    active = [j for j in jobs if j.status in ("queued", "running", "pushing")]
    # Recent fixes pushed to AssIsstant (shared branch)
    recent_done = [j for j in jobs if j.status == "done"][:8]
    failed = [j for j in jobs if j.status == "failed"]

    # —— ACTIVE WORK ——
    lines.append(_box_title("ACTIVE WORK", width))
    if not active:
        lines.append(_c(DIM, "  (idle — nothing queued or running)"))
    else:
        for j in active:
            st = _c(_status_color(j.status) + BOLD, f"{j.status:8}")
            title = _job_title(state, j, 58)
            lines.append(f"  {st}  {_c(BOLD, title)}")
            lines.append(
                f"           id={j.id}  → {_c(CYAN, work)}"
                f"  {_c(DIM, _age(j.updated_at))}"
            )
    lines.append("")

    # —— READY FOR REVIEW (shared AssIsstant vs master) ——
    lines.append(_box_title("READY FOR REVIEW", width))
    lines.append(
        f"  All monkey commits land on {_c(BOLD + CYAN, work)} "
        f"(not per-bug branches)."
    )
    # Open PR AssIsstant → master if any
    pr_url = ""
    for j in recent_done:
        if j.pr_url:
            pr_url = j.pr_url
            break
    if pr_url:
        lines.append(f"  {_c(GREEN + BOLD, 'PR')}  {_c(GREEN, _short_pr(pr_url))}")
    try:
        from maintenance_monkey.dispatch import git_workflow

        ahead = git_workflow.commits_ahead(cfg, limit=10)
    except Exception:
        ahead = []
    if ahead:
        lines.append(_c(DIM, f"  commits on {work} not in {base}:"))
        for c in ahead:
            short = c if len(c) <= width - 6 else c[: width - 9] + "..."
            lines.append(f"    {_c(GREEN, '•')} {short}")
    else:
        lines.append(
            _c(DIM, f"  (no commits on {work} ahead of {base} — nothing pending)")
        )
    if recent_done:
        lines.append(_c(DIM, "  recent jobs:"))
        for j in recent_done[:5]:
            title = _job_title(state, j, 50)
            lines.append(f"    {_c(DIM, _age(j.updated_at))}  {title}")
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

    # Open UserReport checklist
    lines.append(_box_title("USER REPORT (open)", width))
    for row in _user_report_open(cfg):
        lines.append(f"  {row}")

    lines.append("")
    lines.append(
        _c(
            DIM,
            f"  review {work} → merge to {base} when happy · [x] UserReport after merge",
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

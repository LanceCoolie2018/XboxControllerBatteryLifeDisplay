"""Clear Ready-for-Review items when the human commits 'task … complete'."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from maintenance_monkey.config import Config
from maintenance_monkey.state import Job, State

log = logging.getLogger("mm.ack")

# Commit message patterns (subject or full message, first line preferred)
# - "task complete" / "tasks complete" / "mm complete" → clear ALL done jobs
# - "task UR-spacing complete" / "task disconnect complete" / "task abc123 complete"
RE_ALL = re.compile(
    r"(?i)\b(?:tasks?\s+complete|mm\s+complete|all\s+tasks?\s+complete)\b"
)
RE_ONE = re.compile(
    r"(?i)\btask\s+(.+?)\s+complete\b"
)


def _work_branch(cfg: Config) -> str:
    return (cfg.dispatch.work_branch or "AssIsstant").strip()


def _cursor_path(cfg: Config) -> Path:
    return cfg.mm_dir / "ack_cursor"


def _run_git(cfg: Config, args: list[str]) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=cfg.project.root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip()


def _recent_commit_messages(cfg: Config, since_sha: str | None, limit: int = 40) -> list[tuple[str, str]]:
    """Return list of (sha, subject) newest first on work_branch."""
    branch = _work_branch(cfg)
    # Prefer origin/work_branch after fetch
    ref = f"origin/{branch}"
    if not _run_git(cfg, ["rev-parse", "--verify", ref]):
        ref = branch
    if since_sha:
        rev_range = f"{since_sha}..{ref}"
        out = _run_git(cfg, ["log", rev_range, f"-{limit}", "--format=%H\t%s"])
    else:
        out = _run_git(cfg, ["log", ref, f"-{limit}", "--format=%H\t%s"])
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        sha, subj = line.split("\t", 1)
        rows.append((sha.strip(), subj.strip()))
    return rows


def _job_matches_token(state: State, job: Job, token: str) -> bool:
    t = token.strip().strip("\"'`[]").lower()
    if not t:
        return False
    if job.id.lower() == t or job.id.lower().startswith(t):
        return True
    if job.fingerprint.lower() == t or t in job.fingerprint.lower():
        return True
    inc = state.get_incident(job.incident_id)
    if not inc:
        return False
    title = inc.title
    if title.lower().startswith("userreport: "):
        title = title[len("UserReport: ") :]
    if t in title.lower() or title.lower() in t:
        return True
    meta = inc.meta or {}
    item_id = meta.get("item_id") if isinstance(meta, dict) else None
    if item_id and str(item_id).lower() == t:
        return True
    if item_id and t in str(item_id).lower():
        return True
    # fingerprint userreport:UR-foo
    if item_id and f"userreport:{item_id}".lower() == job.fingerprint.lower():
        return True
    return False


def process_task_complete_commits(cfg: Config, state: State) -> list[str]:
    """
    Scan new commits on the work branch for 'task … complete' messages.
    Archive matching done jobs so Ready for Review clears.

    Returns human-readable messages for logs/dashboard.
    """
    cfg.mm_dir.mkdir(parents=True, exist_ok=True)
    cursor_file = _cursor_path(cfg)
    since = cursor_file.read_text(encoding="utf-8").strip() if cursor_file.is_file() else ""
    if since and not _run_git(cfg, ["rev-parse", "--verify", since]):
        since = ""

    commits = _recent_commit_messages(cfg, since or None, limit=50)
    if not commits:
        # Still advance cursor to tip so we don't re-scan forever on first run
        tip = _run_git(cfg, ["rev-parse", f"origin/{_work_branch(cfg)}"])
        if not tip:
            tip = _run_git(cfg, ["rev-parse", _work_branch(cfg)])
        if tip:
            cursor_file.write_text(tip + "\n", encoding="utf-8")
        return []

    # Process oldest first so multiple ack commits apply in order
    commits_chrono = list(reversed(commits))
    messages: list[str] = []
    done_jobs = [j for j in state.list_jobs(100) if j.status == "done"]

    for sha, subject in commits_chrono:
        # Skip monkey's own chore commits from auto-check (optional)
        if RE_ALL.search(subject):
            n = 0
            for j in list(done_jobs):
                state.update_job(
                    j.id,
                    status="archived",
                    meta={**(j.meta or {}), "acked_by": sha, "acked_msg": subject},
                )
                n += 1
            done_jobs = [j for j in state.list_jobs(100) if j.status == "done"]
            messages.append(f"ack all ({n} jobs) via commit {sha[:8]}: {subject}")
            log.info("%s", messages[-1])
            continue

        m = RE_ONE.search(subject)
        if not m:
            continue
        token = m.group(1).strip()
        # Avoid treating "task complete" as token "complete" only — RE_ALL should catch
        if token.lower() in ("", "all"):
            continue
        matched = 0
        for j in list(done_jobs):
            if _job_matches_token(state, j, token):
                state.update_job(
                    j.id,
                    status="archived",
                    meta={**(j.meta or {}), "acked_by": sha, "acked_msg": subject},
                )
                matched += 1
        done_jobs = [j for j in state.list_jobs(100) if j.status == "done"]
        messages.append(
            f"ack {matched} job(s) for {token!r} via commit {sha[:8]}: {subject}"
        )
        log.info("%s", messages[-1])

    # Advance cursor to newest commit we considered
    newest = commits[0][0]
    cursor_file.write_text(newest + "\n", encoding="utf-8")
    return messages

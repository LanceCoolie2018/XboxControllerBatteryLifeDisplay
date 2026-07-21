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


def _reviewable_jobs(state: State) -> list[Job]:
    """Jobs shown in Ready for Review or Failed until resolved/acked."""
    return [j for j in state.list_jobs(100) if j.status in ("done", "failed")]


def process_task_complete_commits(cfg: Config, state: State) -> list[str]:
    """
    Scan new commits on the work branch for 'task … complete' messages.
    Archive matching done *and* failed jobs.

    Returns human-readable messages for logs/dashboard.
    """
    cfg.mm_dir.mkdir(parents=True, exist_ok=True)
    cursor_file = _cursor_path(cfg)
    since = cursor_file.read_text(encoding="utf-8").strip() if cursor_file.is_file() else ""
    if since and not _run_git(cfg, ["rev-parse", "--verify", since]):
        since = ""

    commits = _recent_commit_messages(cfg, since or None, limit=50)
    if not commits:
        tip = _run_git(cfg, ["rev-parse", f"origin/{_work_branch(cfg)}"])
        if not tip:
            tip = _run_git(cfg, ["rev-parse", _work_branch(cfg)])
        if tip:
            cursor_file.write_text(tip + "\n", encoding="utf-8")
        return []

    commits_chrono = list(reversed(commits))
    messages: list[str] = []
    pending = _reviewable_jobs(state)

    for sha, subject in commits_chrono:
        if RE_ALL.search(subject):
            n = 0
            for j in list(pending):
                state.update_job(
                    j.id,
                    status="archived",
                    meta={**(j.meta or {}), "acked_by": sha, "acked_msg": subject},
                )
                n += 1
            pending = _reviewable_jobs(state)
            messages.append(f"ack all ({n} jobs) via commit {sha[:8]}: {subject}")
            log.info("%s", messages[-1])
            continue

        m = RE_ONE.search(subject)
        if not m:
            continue
        token = m.group(1).strip()
        if token.lower() in ("", "all"):
            continue
        matched = 0
        for j in list(pending):
            if _job_matches_token(state, j, token):
                state.update_job(
                    j.id,
                    status="archived",
                    meta={**(j.meta or {}), "acked_by": sha, "acked_msg": subject},
                )
                matched += 1
        pending = _reviewable_jobs(state)
        messages.append(
            f"ack {matched} job(s) for {token!r} via commit {sha[:8]}: {subject}"
        )
        log.info("%s", messages[-1])

    newest = commits[0][0]
    cursor_file.write_text(newest + "\n", encoding="utf-8")
    return messages


def clear_resolved_failures(cfg: Config, state: State) -> list[str]:
    """
    Archive failed jobs whose issue no longer persists:

    1. A later (or any) **done** job shares the same fingerprint — fixed.
    2. UserReport item for that fingerprint is checked off — no longer open.
    3. Manual: same as Ready for Review via "task … complete" (handled separately).
    """
    from maintenance_monkey.sensors.user_report import open_items

    messages: list[str] = []
    jobs = state.list_jobs(100)
    failed = [j for j in jobs if j.status == "failed"]
    if not failed:
        return messages

    # Fingerprints that successfully completed
    done_fps = {j.fingerprint for j in jobs if j.status == "done"}
    # Also treat archived-from-done as success? If archived after done, fingerprint
    # may only have archived jobs. Count any non-failed success:
    success_fps = {
        j.fingerprint
        for j in jobs
        if j.status in ("done", "archived")
        and (j.meta or {}).get("archived_reason") != "branch_deleted"
    }
    # Simpler: any job with same fingerprint that is done clears failures
    # If only archived exists after task-complete of a done job, failures already cleared.
    success_fps |= done_fps

    # Open UserReport fingerprints still active
    open_fps: set[str] = set()
    ur_path = cfg.project.root / cfg.user_report.path
    if ur_path.is_file():
        try:
            text = ur_path.read_text(encoding="utf-8", errors="replace")
            opens, _ = open_items(text)
            open_fps = {i.fingerprint for i in opens}
        except OSError:
            pass

    for j in failed:
        reason = None
        if j.fingerprint in success_fps:
            # Prefer only if there is a done job (explicit fix)
            if j.fingerprint in done_fps:
                reason = "superseded_by_successful_job"
            else:
                # archived success without done in list — check any archived with pr or fix
                for other in jobs:
                    if (
                        other.fingerprint == j.fingerprint
                        and other.id != j.id
                        and other.status == "archived"
                        and other.pr_url
                    ):
                        reason = "superseded_by_successful_job"
                        break
        if reason is None and j.fingerprint.startswith("userreport:"):
            # UserReport: if item is no longer open, issue considered cleared
            if j.fingerprint not in open_fps:
                reason = "user_report_item_no_longer_open"

        if not reason:
            continue

        state.update_job(
            j.id,
            status="archived",
            meta={**(j.meta or {}), "resolved_reason": reason},
        )
        messages.append(f"cleared failed job {j.id} ({reason})")
        log.info("%s", messages[-1])

    return messages


def cancel_closed_user_report_jobs(cfg: Config, state: State) -> list[str]:
    """
    Cancel queued/running/pushing UserReport jobs whose checklist item is
    already [x] (or gone). Prevents working on issues that were closed.
    """
    from maintenance_monkey.sensors.user_report import open_items

    messages: list[str] = []
    ur_path = cfg.project.root / cfg.user_report.path
    if not ur_path.is_file():
        return messages
    try:
        text = ur_path.read_text(encoding="utf-8", errors="replace")
        opens, _ = open_items(text)
    except OSError as e:
        return [f"cancel_closed: cannot read UserReport: {e}"]

    open_fps = {i.fingerprint for i in opens}
    for j in state.list_jobs(100):
        if j.status not in ("queued", "running", "pushing"):
            continue
        if not j.fingerprint.startswith("userreport:"):
            continue
        if j.fingerprint in open_fps:
            continue
        state.update_job(
            j.id,
            status="cancelled",
            error="UserReport item closed — cancelled stale job",
            meta={
                **(j.meta or {}),
                "cancelled_reason": "user_report_item_closed",
            },
        )
        messages.append(
            f"cancelled job {j.id} ({j.fingerprint}): item no longer open"
        )
        log.info("%s", messages[-1])
    return messages


def archive_failed_for_fingerprint(state: State, fingerprint: str, *, by_job: str) -> int:
    """When a job succeeds, drop older failures for the same issue."""
    n = 0
    for j in state.list_jobs(100):
        if j.status != "failed":
            continue
        if j.fingerprint != fingerprint:
            continue
        state.update_job(
            j.id,
            status="archived",
            meta={
                **(j.meta or {}),
                "resolved_reason": "superseded_by_successful_job",
                "resolved_by_job": by_job,
            },
        )
        n += 1
    return n

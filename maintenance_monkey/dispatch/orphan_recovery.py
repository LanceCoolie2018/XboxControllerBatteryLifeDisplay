"""Recover jobs stuck in running/pushing after Grok finished or daemon restart."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from maintenance_monkey.config import Config
from maintenance_monkey.dispatch import git_workflow
from maintenance_monkey.pipeline.acknowledge import archive_failed_for_fingerprint
from maintenance_monkey.sensors.user_report import mark_item_checked
from maintenance_monkey.state import State

log = logging.getLogger("mm.orphan")

# How long a job can sit in running/pushing with no live grok before we recover
ORPHAN_GRACE_SECONDS = 90


def _live_grok_for_job(job_id: str) -> bool:
    """True if a headless grok process is running for this job id."""
    needle = job_id
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            raw = open(f"/proc/{pid}/cmdline", "rb").read()
            cmd = raw.replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if not cmd.startswith("grok"):
            continue
        if "--prompt-file" not in cmd:
            continue
        if needle in cmd:
            return True
    return False


def recover_orphaned_jobs(cfg: Config, state: State) -> list[str]:
    """
    If a job is running/pushing but Grok is gone:
    - worktree has commits ahead of origin/work_branch → finish push + mark done
    - otherwise after grace → mark failed and free the queue
    """
    messages: list[str] = []
    work = (cfg.dispatch.work_branch or "AssIsstant").strip()
    now = time.time()

    for job in state.list_jobs(30):
        if job.status not in ("running", "pushing"):
            continue
        if _live_grok_for_job(job.id):
            continue
        age = now - job.updated_at
        if age < ORPHAN_GRACE_SECONDS:
            continue

        incident = state.get_incident(job.incident_id)
        wt = Path(job.worktree) if job.worktree else None
        log.warning(
            "orphaned job %s status=%s age=%.0fs worktree=%s",
            job.id,
            job.status,
            age,
            wt,
        )

        # Try to complete if there is a committed fix ahead of remote
        if wt and wt.is_dir():
            try:
                git_workflow._run(["git", "fetch", "origin"], wt, check=False)
                ahead = git_workflow._run(
                    ["git", "rev-list", "--count", f"origin/{work}..HEAD"],
                    wt,
                    check=False,
                )
                n_ahead = int((ahead.stdout or "0").strip() or "0")
            except Exception:
                n_ahead = 0

            if n_ahead > 0:
                try:
                    if incident and incident.source == "user_report":
                        title = incident.title
                        if title.startswith("UserReport: "):
                            title = title[len("UserReport: ") :]
                        ok, _ = mark_item_checked(
                            wt / cfg.user_report.path,
                            item_id=(incident.meta or {}).get("item_id")
                            if isinstance(incident.meta, dict)
                            else None,
                            title=title,
                            fingerprint=incident.fingerprint,
                        )
                        if ok:
                            git_workflow.commit_if_needed(
                                wt,
                                f"chore: mark UserReport done for job {job.id}",
                            )
                    state.update_job(job.id, status="pushing")
                    git_workflow.push_branch(cfg, wt, work)
                    pr_url = job.pr_url or ""
                    if cfg.dispatch.create_pr and cfg.dispatch.push:
                        body = (
                            f"## Job `{job.id}` (orphan recovery)\n\n"
                            f"{incident.title if incident else ''}\n"
                        )
                        try:
                            pr_url = git_workflow.ensure_pr(
                                cfg,
                                f"{cfg.project.name}: AssIsstant fixes",
                                body,
                            )
                        except Exception as e:
                            log.warning("pr on orphan recovery: %s", e)
                    state.update_job(
                        job.id,
                        status="done",
                        pr_url=pr_url or None,
                        branch=work,
                        meta={
                            **(job.meta or {}),
                            "recovered": "orphan_push",
                        },
                    )
                    if incident:
                        archive_failed_for_fingerprint(
                            state, incident.fingerprint, by_job=job.id
                        )
                        try:
                            title = incident.title
                            if title.startswith("UserReport: "):
                                title = title[len("UserReport: ") :]
                            mark_item_checked(
                                cfg.project.root / cfg.user_report.path,
                                title=title,
                                fingerprint=incident.fingerprint,
                            )
                        except OSError:
                            pass
                        try:
                            from maintenance_monkey.sensors.github_issues import (
                                mark_ready_for_incident,
                            )

                            ready_msg = mark_ready_for_incident(
                                cfg,
                                incident,
                                job_id=job.id,
                                pr_url=pr_url or "",
                            )
                            if ready_msg:
                                log.info("%s", ready_msg)
                        except Exception:
                            log.exception(
                                "GitHub issue ready-for-review failed for orphan job %s",
                                job.id,
                            )
                    try:
                        git_workflow.remove_worktree(cfg, wt)
                    except Exception:
                        pass
                    msg = f"recovered orphan job {job.id}: pushed {n_ahead} commit(s) → {work}"
                    messages.append(msg)
                    log.info("%s", msg)
                    continue
                except Exception as e:
                    log.exception("orphan push failed for %s", job.id)
                    state.update_job(
                        job.id,
                        status="failed",
                        error=f"orphan recovery push failed: {e}",
                    )
                    messages.append(f"orphan job {job.id}: push failed: {e}")
                    continue

        # No useful commits — free the queue
        state.update_job(
            job.id,
            status="failed",
            error=f"orphaned: no live grok after {int(age)}s; no unpushed commits",
        )
        if wt and wt.is_dir():
            try:
                git_workflow.remove_worktree(cfg, wt)
            except Exception:
                pass
        msg = f"failed orphan job {job.id}: no agent, no commits to push"
        messages.append(msg)
        log.warning("%s", msg)

    return messages

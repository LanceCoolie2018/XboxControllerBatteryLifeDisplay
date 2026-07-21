"""Run Grok CLI headless for a job and publish results."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from maintenance_monkey.config import Config
from maintenance_monkey.dispatch import git_workflow
from maintenance_monkey.dispatch.prompt import build_prompt, write_prompt
from maintenance_monkey.pipeline.context import build_evidence_dir
from maintenance_monkey.state import Incident, Job, State

log = logging.getLogger("mm.grok")


class GrokRunner:
    def __init__(self, cfg: Config, state: State) -> None:
        self.cfg = cfg
        self.state = state

    def process_queue(self) -> list[str]:
        messages: list[str] = []
        while True:
            if self.state.count_running() >= self.cfg.dispatch.max_concurrent_jobs:
                break
            job = self.state.next_queued_job()
            if not job:
                break
            messages.append(self.run_job(job))
            # serial default: one per process_queue call if max is 1
            if self.cfg.dispatch.max_concurrent_jobs <= 1:
                break
        return messages

    def run_job(self, job: Job) -> str:
        incident = self.state.get_incident(job.incident_id)
        if not incident:
            self.state.update_job(job.id, status="failed", error="incident missing")
            return f"job {job.id}: missing incident"

        log.info("running job %s: %s", job.id, incident.title)
        self.state.update_job(job.id, status="running")

        job_dir = build_evidence_dir(self.cfg, incident, job.id)

        try:
            worktree, branch = git_workflow.create_worktree(self.cfg, job.id)
        except Exception as e:
            self.state.update_job(job.id, status="failed", error=str(e))
            log.exception("worktree failed")
            return f"job {job.id}: worktree failed: {e}"

        self.state.update_job(job.id, branch=branch, worktree=str(worktree))

        prompt = build_prompt(self.cfg, incident, job, branch)
        prompt_path = write_prompt(job_dir / "prompt.md", prompt)
        git_workflow.copy_incident_into_worktree(worktree, job_dir)
        # also place prompt at well-known path inside worktree
        write_prompt(worktree / ".mm" / "incident" / "prompt.md", prompt)

        if self.cfg.dispatch.dry_run:
            self.state.update_job(
                job.id,
                status="done",
                meta={"dry_run": True, "prompt": str(prompt_path)},
            )
            return f"job {job.id}: dry_run — prompt at {prompt_path} worktree {worktree}"

        try:
            session_id, grok_text = self._invoke_grok(worktree, prompt_path)
            self.state.update_job(job.id, session_id=session_id)

            git_workflow.commit_if_needed(
                worktree,
                f"fix: {incident.title[:72]}\n\nMaintenance Monkey job {job.id}",
            )

            # Mark UserReport item [x] so remote poll does not re-queue it
            check_msg = self._auto_check_user_report(incident, worktree)
            if check_msg:
                log.info("%s", check_msg)
                git_workflow.commit_if_needed(
                    worktree,
                    f"chore: mark UserReport done for job {job.id}\n\n{incident.title[:72]}",
                )

            if self.cfg.dispatch.push:
                self.state.update_job(job.id, status="pushing")
                git_workflow.push_branch(self.cfg, worktree, branch)

            pr_url = ""
            if self.cfg.dispatch.create_pr and self.cfg.dispatch.push:
                body = (
                    f"## Maintenance Monkey job\n\n"
                    f"- Job: `{job.id}`\n"
                    f"- Incident: `{incident.id}`\n"
                    f"- Source: `{incident.source}`\n"
                    f"- Fingerprint: `{incident.fingerprint}`\n"
                    f"- Branch: `{branch}` (shared work branch)\n\n"
                    f"### Title\n{incident.title}\n\n"
                    f"### Grok summary\n\n{grok_text[:4000] if grok_text else '(no text)'}\n"
                )
                pr_url = git_workflow.ensure_pr(
                    self.cfg,
                    f"{self.cfg.project.name}: AssIsstant fixes",
                    body,
                )
                self.state.update_job(job.id, pr_url=pr_url)

            self.state.update_job(job.id, status="done")
            # Failed section: drop older failures for the same fingerprint
            try:
                from maintenance_monkey.pipeline.acknowledge import (
                    archive_failed_for_fingerprint,
                )

                n = archive_failed_for_fingerprint(
                    self.state, incident.fingerprint, by_job=job.id
                )
                if n:
                    log.info(
                        "archived %s failed job(s) for fingerprint %s",
                        n,
                        incident.fingerprint,
                    )
            except Exception:
                log.exception("could not archive superseded failures")

            try:
                git_workflow.remove_worktree(self.cfg, worktree)
            except Exception:
                log.warning("worktree cleanup failed for %s", worktree)

            # Keep primary checkout UserReport in sync if it is on AssIsstant
            self._sync_user_report_on_primary(incident)

            msg = f"job {job.id}: done → {branch}"
            if check_msg:
                msg += f" ({check_msg})"
            if pr_url:
                msg += f" PR {pr_url}"
            return msg

        except Exception as e:
            log.exception("job %s failed", job.id)
            self.state.update_job(job.id, status="failed", error=str(e))
            return f"job {job.id}: failed: {e}"

    def _auto_check_user_report(self, incident: Incident, worktree: Path) -> str:
        """Mark the checklist item done in worktree UserReport.md if enabled."""
        if not self.cfg.user_report.auto_check_on_pr:
            return ""
        if incident.source != "user_report":
            return ""
        from maintenance_monkey.sensors.user_report import mark_item_checked

        path = worktree / self.cfg.user_report.path
        meta = incident.meta or {}
        item_id = meta.get("item_id") if isinstance(meta, dict) else None
        title = incident.title
        if title.startswith("UserReport: "):
            title = title[len("UserReport: ") :]
        ok, msg = mark_item_checked(
            path,
            item_id=item_id,
            title=title,
            fingerprint=incident.fingerprint,
        )
        return msg if ok else ""

    def _sync_user_report_on_primary(self, incident: Incident) -> None:
        """Also check the box on the daemon's checkout (after pull it matches)."""
        if not self.cfg.user_report.auto_check_on_pr:
            return
        if incident.source != "user_report":
            return
        from maintenance_monkey.sensors.user_report import mark_item_checked

        path = self.cfg.project.root / self.cfg.user_report.path
        meta = incident.meta or {}
        item_id = meta.get("item_id") if isinstance(meta, dict) else None
        title = incident.title
        if title.startswith("UserReport: "):
            title = title[len("UserReport: ") :]
        try:
            mark_item_checked(
                path,
                item_id=item_id,
                title=title,
                fingerprint=incident.fingerprint,
            )
        except OSError as e:
            log.warning("primary UserReport sync failed: %s", e)

    def _invoke_grok(self, worktree: Path, prompt_path: Path) -> tuple[str | None, str]:
        grok = self.cfg.dispatch.grok_bin
        if not shutil.which(grok) and not Path(grok).is_file():
            raise RuntimeError(f"grok binary not found: {grok}")

        cmd = [
            grok,
            "--prompt-file",
            str(prompt_path),
            "--cwd",
            str(worktree),
            "--yolo",
            "--output-format",
            "json",
            "--max-turns",
            str(self.cfg.dispatch.max_turns),
            "--no-auto-update",
            "--rules",
            self.cfg.dispatch.rules,
        ]
        if self.cfg.dispatch.model:
            cmd.extend(["-m", self.cfg.dispatch.model])

        log.info("invoking grok in %s", worktree)
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.cfg.dispatch.job_timeout_seconds,
            check=False,
        )
        # persist raw output
        out_path = worktree / ".mm" / "incident" / "grok_stdout.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(r.stdout or "", encoding="utf-8")
        if r.stderr:
            (worktree / ".mm" / "incident" / "grok_stderr.txt").write_text(
                r.stderr, encoding="utf-8"
            )

        if r.returncode != 0:
            raise RuntimeError(
                f"grok exited {r.returncode}: {(r.stderr or r.stdout or '')[:500]}"
            )

        session_id = None
        text = r.stdout or ""
        try:
            data = json.loads(r.stdout or "{}")
            if isinstance(data, dict):
                session_id = data.get("sessionId")
                text = data.get("text") or text
                if data.get("type") == "error":
                    raise RuntimeError(data.get("message") or "grok error")
        except json.JSONDecodeError:
            pass
        return session_id, text

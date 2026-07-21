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

            committed = git_workflow.commit_if_needed(
                worktree,
                f"fix: {incident.title[:72]}\n\nMaintenance Monkey job {job.id}",
            )
            # If still no commits ahead of base, fail softly
            ahead = subprocess.run(
                ["git", "rev-list", "--count", f"origin/{self.cfg.project.default_branch}..HEAD"],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            # ignore count errors
            _ = committed

            if self.cfg.dispatch.push:
                self.state.update_job(job.id, status="pushing")
                git_workflow.push_branch(self.cfg, worktree, branch)

            pr_url = ""
            if self.cfg.dispatch.create_pr and self.cfg.dispatch.push:
                body = (
                    f"## Maintenance Monkey\n\n"
                    f"- Job: `{job.id}`\n"
                    f"- Incident: `{incident.id}`\n"
                    f"- Source: `{incident.source}`\n"
                    f"- Fingerprint: `{incident.fingerprint}`\n\n"
                    f"### Title\n{incident.title}\n\n"
                    f"### Grok summary\n\n{grok_text[:4000] if grok_text else '(no text)'}\n"
                )
                pr_url = git_workflow.create_pr(
                    self.cfg, branch, f"fix: {incident.title[:80]}", body
                )
                self.state.update_job(job.id, pr_url=pr_url)

            self.state.update_job(job.id, status="done")
            # cleanup worktree on success
            try:
                git_workflow.remove_worktree(self.cfg, worktree)
            except Exception:
                log.warning("worktree cleanup failed for %s", worktree)

            msg = f"job {job.id}: done"
            if pr_url:
                msg += f" PR {pr_url}"
            return msg

        except Exception as e:
            log.exception("job %s failed", job.id)
            self.state.update_job(job.id, status="failed", error=str(e))
            return f"job {job.id}: failed: {e}"

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

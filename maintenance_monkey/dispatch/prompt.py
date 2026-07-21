"""Build Grok prompt files for fix jobs."""

from __future__ import annotations

from pathlib import Path

from maintenance_monkey.config import Config
from maintenance_monkey.pipeline.context import collect_env, collect_repo_hints
from maintenance_monkey.state import Incident, Job


def build_prompt(cfg: Config, incident: Incident, job: Job, branch: str) -> str:
    hints = collect_repo_hints(cfg.project.root)
    env = collect_env()
    source_note = {
        "user_report": "This came from the project's UserReport.md checklist.",
        "log_stack": "This came from a stack trace in application logs.",
        "log_line": "This came from a matching error line in application logs.",
        "process": "This came from process stderr/stdout.",
        "process_stack": "This came from a process stack trace.",
        "process_crash": "The supervised process crashed.",
        "known_bug": "A known_bugs.yaml symptom matched live logs.",
        "manual": "The user filed this manually via `mm report`.",
    }.get(incident.source, f"Source: {incident.source}")

    return f"""# Maintenance Monkey fix job

You are running unattended in a **git worktree** on branch `{branch}`.
Project: **{cfg.project.name}**
Base branch for the eventual PR: **{cfg.project.default_branch or 'main'}**

## Mission

Investigate and fix the issue below. Make a minimal, correct change.
Run existing tests if the project has them.
Commit your changes on the current branch with a clear message.
Do **not** merge to main/master. Do **not** force-push.
Do **not** push yourself unless needed — the monkey may push after you exit.
Leave other UserReport checklist items alone.

{source_note}

## Job metadata

- Job ID: `{job.id}`
- Incident ID: `{incident.id}`
- Fingerprint: `{incident.fingerprint}`
- Title: {incident.title}

## Environment

{env}

{hints}

## Evidence

{incident.body}

## Evidence files

Also see files under `.mm/incident/` in this worktree (if present).

## Done criteria

1. Root cause addressed (or explain why not in the commit message).
2. Changes committed on `{branch}`.
3. Summarize what you changed in your final response.
"""


def write_prompt(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path

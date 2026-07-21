"""Collect context for Grok prompts."""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

from maintenance_monkey.config import Config
from maintenance_monkey.state import Incident


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        r = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return (r.stdout or r.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"(failed: {e})"


def collect_repo_hints(root: Path) -> str:
    parts = [
        f"## Git log (last 5)\n```\n{_run(['git', 'log', '-5', '--oneline'], root)}\n```",
        f"## Git status\n```\n{_run(['git', 'status', '-sb'], root)}\n```",
        f"## Recent files (name-status)\n```\n{_run(['git', 'log', '-3', '--name-status', '--oneline'], root)}\n```",
    ]
    return "\n\n".join(parts)


def collect_env() -> str:
    return "\n".join(
        [
            f"- OS: {platform.platform()}",
            f"- Python: {platform.python_version()}",
            f"- Machine: {platform.machine()}",
            f"- grok: {shutil.which('grok') or 'not found'}",
            f"- gh: {shutil.which('gh') or 'not found'}",
        ]
    )


def build_evidence_dir(cfg: Config, incident: Incident, job_id: str) -> Path:
    d = cfg.jobs_dir / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "evidence.txt").write_text(incident.body, encoding="utf-8")
    meta = (
        f"id: {incident.id}\n"
        f"source: {incident.source}\n"
        f"fingerprint: {incident.fingerprint}\n"
        f"title: {incident.title}\n"
    )
    (d / "meta.txt").write_text(meta, encoding="utf-8")
    return d

"""Poll GitHub Issues (customer-report) and enqueue AssIsstant jobs.

Uses `gh api` when available so Pi auth stays with `gh auth login`.
No secrets in the app; this sensor runs only on the maintainer machine/Pi.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from maintenance_monkey.config import Config
from maintenance_monkey.pipeline.fingerprint import fingerprint_id
from maintenance_monkey.pipeline.queue import enqueue_incident
from maintenance_monkey.state import State

log = logging.getLogger("mm.github_issues")


@dataclass
class GhIssue:
    number: int
    title: str
    body: str
    html_url: str
    labels: list[str]
    state: str
    updated_at: str


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _run_gh(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", "gh not found"
    except subprocess.TimeoutExpired:
        return 124, "", "gh timed out"


def fetch_open_issues(cfg: Config) -> tuple[list[GhIssue], str]:
    """Return (issues, status_message)."""
    gi = cfg.github_issues
    if not gi.enabled:
        return [], "github_issues disabled"
    if not _gh_available():
        return [], "gh CLI not found — run: gh auth login"

    # Search open issues with all required labels
    label_qs = " ".join(f'label:"{lab}"' for lab in (gi.labels or ["customer-report"]))
    q = f"repo:{gi.repo} is:issue is:{gi.state} {label_qs}".strip()
    code, out, err = _run_gh(
        [
            "api",
            "search/issues",
            "-X",
            "GET",
            "-f",
            f"q={q}",
            "-f",
            "per_page=50",
            "--jq",
            ".items",
        ]
    )
    if code != 0:
        return [], f"gh api failed ({code}): {(err or out)[:200]}"

    try:
        items = json.loads(out) if out.strip() else []
    except json.JSONDecodeError as e:
        return [], f"bad JSON from gh: {e}"

    issues: list[GhIssue] = []
    if not isinstance(items, list):
        return [], "unexpected gh payload"

    for raw in items:
        if not isinstance(raw, dict):
            continue
        labels = []
        for lab in raw.get("labels") or []:
            if isinstance(lab, dict) and lab.get("name"):
                labels.append(str(lab["name"]))
            elif isinstance(lab, str):
                labels.append(lab)
        issues.append(
            GhIssue(
                number=int(raw.get("number") or 0),
                title=str(raw.get("title") or "").strip(),
                body=str(raw.get("body") or ""),
                html_url=str(raw.get("html_url") or ""),
                labels=labels,
                state=str(raw.get("state") or "open"),
                updated_at=str(raw.get("updated_at") or ""),
            )
        )
    return issues, f"fetched {len(issues)} open issue(s)"


def scan_github_issues(
    cfg: Config,
    state: State,
    *,
    trigger: str = "manual",
) -> list[str]:
    """Enqueue open labeled Issues as monkey jobs. Returns status messages."""
    messages: list[str] = []
    if not cfg.github_issues.enabled:
        return ["github_issues disabled"]

    issues, status = fetch_open_issues(cfg)
    messages.append(status)
    if not issues:
        return messages

    for issue in issues:
        if issue.number <= 0:
            continue
        fp = fingerprint_id("github-issue", str(issue.number))
        body_parts = [
            "# GitHub Issue (customer report)",
            "",
            f"**Number:** #{issue.number}",
            f"**Title:** {issue.title}",
            f"**URL:** {issue.html_url}",
            f"**Labels:** {', '.join(issue.labels) or '(none)'}",
            f"**Trigger:** {trigger}",
            f"**Updated:** {issue.updated_at}",
            "",
            "## Issue body",
            issue.body or "(empty)",
            "",
            "## Instructions",
            "Fix on AssIsstant only. Do not merge master.",
            f"Reference this issue as UR-gh-{issue.number} in the commit message when possible.",
            "Do not close the GitHub Issue unless asked — maintainer reviews AssIsstant first.",
        ]
        body = "\n".join(body_parts)
        title = f"GitHub #{issue.number}: {issue.title[:80]}"
        _, job, msg = enqueue_incident(
            state,
            cfg,
            source="github_issue",
            fingerprint=fp,
            title=title,
            body=body,
            meta={
                "issue_number": issue.number,
                "html_url": issue.html_url,
                "trigger": trigger,
                "labels": issue.labels,
            },
        )
        messages.append(f"#{issue.number} {issue.title[:50]}: {msg}")
        if job:
            log.info("GitHub issue #%s queued as job %s", issue.number, job.id)
    return messages


class GitHubIssuesWatcher:
    """Daemon helper: poll Issues on an interval."""

    def __init__(self, cfg: Config, state: State) -> None:
        self.cfg = cfg
        self.state = state
        self._last_poll: float | None = None

    def poll(self, now: float) -> list[str]:
        if not self.cfg.github_issues.enabled:
            return []
        interval = float(self.cfg.github_issues.poll_seconds or 0)
        if interval <= 0:
            return []
        if self._last_poll is not None and (now - self._last_poll) < interval:
            return []
        self._last_poll = now
        return scan_github_issues(self.cfg, self.state, trigger="daemon")

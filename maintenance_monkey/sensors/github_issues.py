"""Poll GitHub Issues (customer-report) and enqueue AssIsstant jobs.

Uses `gh api` when available so Pi auth stays with `gh auth login`.
No secrets in the app; this sensor runs only on the maintainer machine/Pi.

Lifecycle
---------
1. Open issue with customer-report → monkey queues Grok fix on AssIsstant.
2. Grok succeeds → label ``mm-ready-for-review`` (issue stays OPEN for human review).
3. You commit ``task complete`` (and merge when ready) → monkey closes the issue.
4. False report → ``python -m maintenance_monkey github-issues dismiss N``
   (or add label invalid / wontfix / false-report / mm-dismissed) so it is
   never re-queued; dismiss CLI also closes the issue with a comment.
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
from maintenance_monkey.state import Incident, Job, State

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


def _norm_labels(labels: list[str] | None) -> set[str]:
    return {str(x).strip().lower() for x in (labels or []) if str(x).strip()}


def _ready_label(cfg: Config) -> str:
    return (cfg.github_issues.ready_label or "mm-ready-for-review").strip()


def _dismiss_label_set(cfg: Config) -> set[str]:
    return _norm_labels(cfg.github_issues.dismiss_labels)


def issue_is_ready_for_review(cfg: Config, labels: list[str] | None) -> bool:
    ready = _ready_label(cfg).lower()
    return ready in _norm_labels(labels)


def issue_is_dismissed(cfg: Config, labels: list[str] | None) -> bool:
    labs = _norm_labels(labels)
    return bool(labs & _dismiss_label_set(cfg))


def ensure_label(cfg: Config, name: str, *, color: str = "0E8A16", description: str = "") -> None:
    """Create a repo label if missing (best-effort)."""
    if not name or not _gh_available():
        return
    repo = cfg.github_issues.repo
    code, _out, _err = _run_gh(
        ["label", "list", "--repo", repo, "--json", "name", "--jq", ".[].name"],
        timeout=30,
    )
    if code != 0:
        return
    existing = {(ln or "").strip().lower() for ln in (_out or "").splitlines()}
    if name.lower() in existing:
        return
    args = ["label", "create", name, "--repo", repo, "--color", color.lstrip("#")]
    if description:
        args.extend(["--description", description[:100]])
    _run_gh(args, timeout=30)


# Body markers from BatteryHUD Bug button (customers usually cannot apply labels).
_APP_REPORT_MARKERS = (
    "<!-- filed from batteryhud bug button -->",
    "### what went wrong?",
)


def _looks_like_app_report(body: str, title: str = "") -> bool:
    text = (body or "").lower()
    if "filed from batteryhud bug button" in text:
        return True
    if "### what went wrong?" in text and (
        "app version:" in text or "**app version:**" in text
    ):
        return True
    return False


def _parse_search_items(out: str) -> list[dict[str, Any]]:
    try:
        items = json.loads(out) if out.strip() else []
    except json.JSONDecodeError:
        return []
    return items if isinstance(items, list) else []


def _gh_issue_from_raw(raw: dict[str, Any]) -> GhIssue | None:
    if not isinstance(raw, dict):
        return None
    labels: list[str] = []
    for lab in raw.get("labels") or []:
        if isinstance(lab, dict) and lab.get("name"):
            labels.append(str(lab["name"]))
        elif isinstance(lab, str):
            labels.append(lab)
    number = int(raw.get("number") or 0)
    if number <= 0:
        return None
    return GhIssue(
        number=number,
        title=str(raw.get("title") or "").strip(),
        body=str(raw.get("body") or ""),
        html_url=str(raw.get("html_url") or ""),
        labels=labels,
        state=str(raw.get("state") or "open"),
        updated_at=str(raw.get("updated_at") or ""),
    )


def _search_issues(cfg: Config, q: str) -> tuple[list[dict[str, Any]], str]:
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
    return _parse_search_items(out), ""


def ensure_customer_labels(cfg: Config, issue_number: int, existing: list[str]) -> list[str]:
    """Add customer-report (+ needs-triage if none) when customers could not set labels."""
    labs = list(existing)
    norm = _norm_labels(labs)
    wanted = [str(x) for x in (cfg.github_issues.labels or ["customer-report"])]
    to_add: list[str] = []
    for w in wanted:
        if w.lower() not in norm:
            to_add.append(w)
    if "needs-triage" not in norm and "mm-ready-for-review" not in norm:
        # Only add triage if not already ready-for-review
        if "needs-triage" not in {x.lower() for x in to_add}:
            to_add.append("needs-triage")
    if not to_add or not _gh_available():
        return labs
    repo = cfg.github_issues.repo
    for lab in to_add:
        ensure_label(cfg, lab)
    args = [
        "issue",
        "edit",
        str(issue_number),
        "--repo",
        repo,
    ]
    for lab in to_add:
        args.extend(["--add-label", lab])
    code, _out, err = _run_gh(args, timeout=45)
    if code != 0:
        log.warning(
            "could not auto-label issue #%s: %s",
            issue_number,
            (err or "")[:200],
        )
        return labs
    for lab in to_add:
        if lab not in labs:
            labs.append(lab)
    log.info("auto-labeled issue #%s with %s", issue_number, ", ".join(to_add))
    return labs


def fetch_open_issues(cfg: Config) -> tuple[list[GhIssue], str]:
    """Return open customer-report issues (and unlabeled app Bug-button reports)."""
    gi = cfg.github_issues
    if not gi.enabled:
        return [], "github_issues disabled"
    if not _gh_available():
        return [], "gh CLI not found — run: gh auth login"

    by_num: dict[int, GhIssue] = {}
    errors: list[str] = []

    # 1) Labeled customer-report (or configured labels)
    label_qs = " ".join(f'label:"{lab}"' for lab in (gi.labels or ["customer-report"]))
    q_labeled = f"repo:{gi.repo} is:issue is:{gi.state} {label_qs}".strip()
    items, err = _search_issues(cfg, q_labeled)
    if err:
        errors.append(err)
    for raw in items:
        issue = _gh_issue_from_raw(raw)
        if issue:
            by_num[issue.number] = issue

    # 2) App-filed reports that lost labels (GitHub strips labels for non-collaborators)
    # Search by marker in body; also open issues with the What went wrong template.
    q_app = (
        f'repo:{gi.repo} is:issue is:open '
        f'"filed from BatteryHUD Bug button"'
    )
    items2, err2 = _search_issues(cfg, q_app)
    if err2:
        errors.append(err2)
    for raw in items2:
        issue = _gh_issue_from_raw(raw)
        if not issue:
            continue
        if issue.number in by_num:
            continue
        if not _looks_like_app_report(issue.body, issue.title):
            continue
        # Maintainer can apply labels customers could not
        issue.labels = ensure_customer_labels(cfg, issue.number, issue.labels)
        by_num[issue.number] = issue

    # 3) Fallback: all open issues — catch unlabeled app reports + any with required labels
    # (search API may lag on brand-new body text / labels)
    q_open = f"repo:{gi.repo} is:issue is:open"
    items3, err3 = _search_issues(cfg, q_open)
    if err3 and not by_num:
        errors.append(err3)
    for raw in items3:
        issue = _gh_issue_from_raw(raw)
        if not issue or issue.number in by_num:
            continue
        if issue_is_dismissed(cfg, issue.labels):
            continue
        has_required = any(
            lab.lower() in _norm_labels(issue.labels)
            for lab in (gi.labels or ["customer-report"])
        )
        if has_required:
            by_num[issue.number] = issue
            continue
        if _looks_like_app_report(issue.body, issue.title):
            issue.labels = ensure_customer_labels(cfg, issue.number, issue.labels)
            by_num[issue.number] = issue

    issues = sorted(by_num.values(), key=lambda i: i.number)
    status = f"fetched {len(issues)} open issue(s)"
    if errors:
        status += f" ({'; '.join(errors)})"
    return issues, status


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

    ready = _ready_label(cfg)
    for issue in issues:
        if issue.number <= 0:
            continue
        if issue_is_dismissed(cfg, issue.labels):
            msg = f"#{issue.number} skipped: dismissed (false report / invalid)"
            messages.append(msg)
            log.info("%s", msg)
            continue
        if issue_is_ready_for_review(cfg, issue.labels):
            msg = (
                f"#{issue.number} skipped: {ready} "
                "(awaiting task complete / merge)"
            )
            messages.append(msg)
            log.info("%s", msg)
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
            "Do not close the GitHub Issue yourself.",
            "After your fix, Maintenance Monkey labels it ready-for-review;",
            "the maintainer closes it with a 'task complete' commit after review/merge.",
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


def build_ready_comment(
    *,
    job_id: str,
    pr_url: str = "",
    branch: str = "AssIsstant",
    summary: str = "",
    ready_label: str = "mm-ready-for-review",
) -> str:
    """Comment when marking an issue ready for human review (still open)."""
    lines = [
        "### Maintenance Monkey — ready for review",
        "",
        f"- Job: `{job_id}`",
        f"- Branch: `{branch}`",
        f"- Label: `{ready_label}`",
    ]
    if pr_url:
        lines.append(f"- PR: {pr_url}")
    lines.extend(
        [
            "",
            "Fix landed on **AssIsstant**. This issue stays **open** until you:",
            "1. Review the change / PR",
            "2. Commit `task complete` (or `task UR-gh-N complete`)",
            "3. Merge to main/master when ready",
            "",
            "Monkey will not re-queue while this label is present.",
            "If this is a false report: "
            "`python -m maintenance_monkey github-issues dismiss N`",
        ]
    )
    if summary and summary.strip():
        snippet = summary.strip()[:1500]
        lines.extend(["", "#### Grok summary", "", snippet])
    return "\n".join(lines)


def build_close_comment(
    *,
    job_id: str,
    pr_url: str = "",
    branch: str = "AssIsstant",
    summary: str = "",
    reason: str = "task_complete",
) -> str:
    """Body posted when closing after task complete (or dismiss)."""
    if reason == "dismiss":
        lines = [
            "### Maintenance Monkey — dismissed (false report)",
            "",
            f"- Job / ref: `{job_id or 'n/a'}`",
            "",
            "Closed as not a real product issue (false or out-of-scope report).",
            "Monkey will not work this issue further.",
        ]
        if summary and summary.strip():
            lines.extend(["", summary.strip()[:800]])
        return "\n".join(lines)

    lines = [
        "### Maintenance Monkey — accepted (task complete)",
        "",
        f"- Job: `{job_id}`",
        f"- Branch: `{branch}`",
    ]
    if pr_url:
        lines.append(f"- PR: {pr_url}")
    lines.extend(
        [
            "",
            "Closed after maintainer `task complete` review.",
            "Reopen if the problem is still present after the next build/release.",
        ]
    )
    if summary and summary.strip():
        snippet = summary.strip()[:1500]
        lines.extend(["", "#### Notes", "", snippet])
    return "\n".join(lines)


def mark_issue_ready_for_review(
    cfg: Config,
    issue_number: int,
    *,
    job_id: str,
    pr_url: str = "",
    branch: str = "",
    summary: str = "",
) -> tuple[bool, str]:
    """Label issue ready-for-review after a successful fix; leave OPEN."""
    if not cfg.github_issues.enabled:
        return False, "github_issues disabled"
    if not cfg.github_issues.mark_ready_on_done:
        return False, "mark_ready_on_done disabled"
    if issue_number <= 0:
        return False, "invalid issue number"
    if not _gh_available():
        return False, "gh CLI not found"

    repo = cfg.github_issues.repo
    ready = _ready_label(cfg)
    work_branch = branch or cfg.dispatch.work_branch or "AssIsstant"
    ensure_label(
        cfg,
        ready,
        color="1D76DB",
        description="Monkey fixed on AssIsstant; awaiting task complete",
    )

    # Comment first so the timeline shows the ready state even if label fails
    comment = build_ready_comment(
        job_id=job_id,
        pr_url=pr_url or "",
        branch=work_branch,
        summary=summary or "",
        ready_label=ready,
    )
    c_code, _c_out, c_err = _run_gh(
        [
            "issue",
            "comment",
            str(issue_number),
            "--repo",
            repo,
            "--body",
            comment,
        ],
        timeout=60,
    )
    if c_code != 0:
        log.warning(
            "ready comment on #%s failed: %s",
            issue_number,
            (c_err or "")[:200],
        )

    # Add ready label; drop needs-triage if present
    edit_args = [
        "issue",
        "edit",
        str(issue_number),
        "--repo",
        repo,
        "--add-label",
        ready,
    ]
    # Best-effort remove needs-triage
    edit_args.extend(["--remove-label", "needs-triage"])
    e_code, _e_out, e_err = _run_gh(edit_args, timeout=60)
    if e_code != 0:
        # Retry without remove-label (may not exist)
        e_code, _e_out, e_err = _run_gh(
            [
                "issue",
                "edit",
                str(issue_number),
                "--repo",
                repo,
                "--add-label",
                ready,
            ],
            timeout=60,
        )
    if e_code != 0:
        detail = (e_err or "").strip()[:300]
        msg = f"failed to mark issue #{issue_number} ready: {detail}"
        log.warning("%s", msg)
        return False, msg

    msg = f"marked GitHub issue #{issue_number} {ready} (still open for review)"
    log.info("%s (job %s)", msg, job_id)
    return True, msg


def close_issue(
    cfg: Config,
    issue_number: int,
    *,
    job_id: str = "",
    pr_url: str = "",
    branch: str = "",
    summary: str = "",
    reason: str = "task_complete",
    extra_labels: list[str] | None = None,
) -> tuple[bool, str]:
    """Close a GitHub issue with a comment. Returns (ok, message)."""
    if not cfg.github_issues.enabled:
        return False, "github_issues disabled"
    if issue_number <= 0:
        return False, "invalid issue number"
    if not _gh_available():
        return False, "gh CLI not found — cannot close issue"

    repo = cfg.github_issues.repo
    work_branch = branch or cfg.dispatch.work_branch or "AssIsstant"
    comment = build_close_comment(
        job_id=job_id or "n/a",
        pr_url=pr_url or "",
        branch=work_branch,
        summary=summary or "",
        reason=reason,
    )

    # Optional labels before close (e.g. invalid on dismiss)
    for lab in extra_labels or []:
        if not lab:
            continue
        ensure_label(cfg, lab, color="e4e669", description="Dismissed / not a bug")
        _run_gh(
            [
                "issue",
                "edit",
                str(issue_number),
                "--repo",
                repo,
                "--add-label",
                lab,
            ],
            timeout=45,
        )

    # Drop ready label so a reopen path is clean
    ready = _ready_label(cfg)
    _run_gh(
        [
            "issue",
            "edit",
            str(issue_number),
            "--repo",
            repo,
            "--remove-label",
            ready,
        ],
        timeout=30,
    )

    code, out, err = _run_gh(
        [
            "issue",
            "close",
            str(issue_number),
            "--repo",
            repo,
            "--comment",
            comment,
        ],
        timeout=90,
    )
    if code != 0:
        detail = (err or out or "").strip()[:300]
        low = detail.lower()
        if "already closed" in low or "not open" in low:
            msg = f"issue #{issue_number} already closed"
            log.info("%s", msg)
            return True, msg
        msg = f"failed to close issue #{issue_number}: {detail}"
        log.warning("%s", msg)
        return False, msg

    msg = f"closed GitHub issue #{issue_number} ({reason})"
    log.info("%s (job %s)", msg, job_id or "-")
    return True, msg


# Back-compat names used by older call sites / tests
def close_issue_after_fix(
    cfg: Config,
    issue_number: int,
    *,
    job_id: str,
    pr_url: str = "",
    branch: str = "",
    summary: str = "",
) -> tuple[bool, str]:
    """Legacy: only closes if auto_close_on_done is enabled (default off)."""
    if not cfg.github_issues.auto_close_on_done:
        return False, "auto_close_on_done disabled (use ready-for-review + task complete)"
    return close_issue(
        cfg,
        issue_number,
        job_id=job_id,
        pr_url=pr_url,
        branch=branch,
        summary=summary,
        reason="task_complete",
    )


def is_issue_open(cfg: Config, issue_number: int) -> bool | None:
    """Return True if open, False if closed, None if unknown/unavailable."""
    if issue_number <= 0 or not _gh_available():
        return None
    repo = cfg.github_issues.repo
    code, out, _err = _run_gh(
        [
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repo,
            "--json",
            "state",
            "--jq",
            ".state",
        ],
        timeout=30,
    )
    if code != 0:
        return None
    state = (out or "").strip().lower()
    if state == "open":
        return True
    if state in ("closed", "completed"):
        return False
    return None


def get_issue_labels(cfg: Config, issue_number: int) -> list[str] | None:
    if issue_number <= 0 or not _gh_available():
        return None
    repo = cfg.github_issues.repo
    code, out, _err = _run_gh(
        [
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repo,
            "--json",
            "labels",
            "--jq",
            ".labels[].name",
        ],
        timeout=30,
    )
    if code != 0:
        return None
    return [ln.strip() for ln in (out or "").splitlines() if ln.strip()]


def issue_should_skip_work(cfg: Config, issue_number: int) -> tuple[bool, str]:
    """True if monkey should not run a job for this issue."""
    open_state = is_issue_open(cfg, issue_number)
    if open_state is False:
        return True, "issue closed"
    labels = get_issue_labels(cfg, issue_number)
    if labels is None:
        return False, ""
    if issue_is_dismissed(cfg, labels):
        return True, "dismissed (false report)"
    if issue_is_ready_for_review(cfg, labels):
        return True, f"{_ready_label(cfg)} (awaiting review)"
    return False, ""


def mark_ready_for_incident(
    cfg: Config,
    incident: Incident,
    *,
    job_id: str,
    pr_url: str = "",
    summary: str = "",
) -> str:
    """Mark github_issue incident ready-for-review. Returns status or ''."""
    if incident.source != "github_issue":
        return ""
    meta = incident.meta or {}
    if not isinstance(meta, dict):
        return ""
    try:
        number_i = int(meta.get("issue_number"))
    except (TypeError, ValueError):
        return ""
    _ok, msg = mark_issue_ready_for_review(
        cfg,
        number_i,
        job_id=job_id,
        pr_url=pr_url or "",
        branch=cfg.dispatch.work_branch,
        summary=summary or "",
    )
    return msg


def close_issue_for_incident(
    cfg: Config,
    incident: Incident,
    *,
    job_id: str,
    pr_url: str = "",
    summary: str = "",
    reason: str = "task_complete",
) -> str:
    """Close linked GitHub issue for an incident (task complete path)."""
    if incident.source != "github_issue":
        return ""
    if reason == "task_complete" and not cfg.github_issues.close_on_task_complete:
        return "close_on_task_complete disabled"
    meta = incident.meta or {}
    if not isinstance(meta, dict):
        return ""
    try:
        number_i = int(meta.get("issue_number"))
    except (TypeError, ValueError):
        return ""
    _ok, msg = close_issue(
        cfg,
        number_i,
        job_id=job_id,
        pr_url=pr_url or "",
        branch=cfg.dispatch.work_branch,
        summary=summary or "",
        reason=reason,
    )
    return msg


def dismiss_issue(
    cfg: Config,
    state: State,
    issue_number: int,
    *,
    reason: str = "",
) -> list[str]:
    """
    Mark a customer report as a false / non-issue:
    - add dismiss label (false-report)
    - close the GitHub issue with a comment
    - cancel/archive related monkey jobs so they leave Ready for Review
    """
    messages: list[str] = []
    if issue_number <= 0:
        return ["invalid issue number"]
    if not cfg.github_issues.enabled:
        return ["github_issues disabled"]

    dismiss_lab = "false-report"
    preferred = ("false-report", "mm-dismissed", "invalid")
    for lab in cfg.github_issues.dismiss_labels or []:
        if lab.strip().lower() in preferred:
            dismiss_lab = lab.strip()
            break
    else:
        if cfg.github_issues.dismiss_labels:
            dismiss_lab = str(cfg.github_issues.dismiss_labels[0]).strip() or dismiss_lab

    summary = reason.strip() if reason else "Maintainer dismissed as false / not a product issue."
    ok, msg = close_issue(
        cfg,
        issue_number,
        job_id="dismiss",
        summary=summary,
        reason="dismiss",
        extra_labels=[dismiss_lab],
    )
    messages.append(msg)
    if not ok and "already closed" not in msg.lower():
        # Still try to label even if close failed
        ensure_label(cfg, dismiss_lab, color="e4e669", description="False report")
        _run_gh(
            [
                "issue",
                "edit",
                str(issue_number),
                "--repo",
                cfg.github_issues.repo,
                "--add-label",
                dismiss_lab,
            ],
            timeout=45,
        )

    fp = fingerprint_id("github-issue", str(issue_number))
    n = 0
    for job in state.list_jobs(200):
        if job.fingerprint != fp:
            continue
        if job.status in ("archived", "cancelled"):
            continue
        state.update_job(
            job.id,
            status="cancelled" if job.status in ("queued", "running", "pushing") else "archived",
            error="dismissed as false report",
            meta={
                **(job.meta or {}),
                "dismissed": True,
                "dismiss_reason": summary[:200],
            },
        )
        n += 1
    messages.append(f"cleared {n} local job(s) for #{issue_number}")
    log.info("dismissed GitHub issue #%s (%s jobs cleared)", issue_number, n)
    return messages


def close_issues_for_acked_jobs(
    cfg: Config,
    state: State,
    jobs: list[Job],
) -> list[str]:
    """Close GitHub issues linked to jobs just acked via task complete."""
    if not cfg.github_issues.enabled or not cfg.github_issues.close_on_task_complete:
        return []
    messages: list[str] = []
    seen: set[int] = set()
    for job in jobs:
        inc = state.get_incident(job.incident_id)
        if not inc or inc.source != "github_issue":
            continue
        meta = inc.meta or {}
        if not isinstance(meta, dict):
            continue
        try:
            num = int(meta.get("issue_number"))
        except (TypeError, ValueError):
            continue
        if num in seen:
            continue
        seen.add(num)
        _ok, msg = close_issue(
            cfg,
            num,
            job_id=job.id,
            pr_url=job.pr_url or "",
            branch=job.branch or cfg.dispatch.work_branch,
            reason="task_complete",
        )
        messages.append(msg)
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

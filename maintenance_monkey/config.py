"""Load and validate mm.toml configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_RULES = """\
Work only in this worktree. Commit with a clear message.
All work is pushed to the AssIsstant branch only — no extra branches.
Never checkout or push main/master. Never force-push.
Do not modify secrets, credentials, or .mm/state.
Prefer minimal diffs. Run existing tests if available.
Do not merge to master. Do not delete other UserReport checklist items.
"""


@dataclass
class LogWatchConfig:
    paths: list[str] = field(default_factory=list)
    from_start: bool = False


@dataclass
class ProcessWatchConfig:
    enabled: bool = False
    command: list[str] = field(default_factory=list)
    cwd: str = "."
    restart_on_exit: bool = False
    incident_on_crash: bool = True


@dataclass
class PatternsConfig:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


@dataclass
class KnownBugsConfig:
    path: str = "known_bugs.yaml"
    match_logs: bool = True


@dataclass
class UserReportConfig:
    enabled: bool = True
    path: str = "UserReport.md"
    debounce_seconds: float = 2.0
    pull_before_scan: bool = False
    # When a UserReport job finishes successfully, mark - [ ] → - [x] on
    # AssIsstant so the next scan does not re-queue before you review.
    auto_check_on_pr: bool = True
    # How often the daemon fetches/pulls the current branch and re-scans
    # UserReport for laptop pushes. 0 disables (local mtime watch only).
    remote_poll_seconds: float = 30.0
    # Regexes (Python re) — open items matching any are never enqueued
    ignore: list[str] = field(default_factory=list)


@dataclass
class GitHubIssuesConfig:
    """Poll public GitHub Issues labeled for customer reports (Pi/maintainer only)."""

    enabled: bool = False
    repo: str = "LanceCoolie2018/XboxControllerBatteryLifeDisplay"
    labels: list[str] = field(default_factory=lambda: ["customer-report"])
    state: str = "open"
    poll_seconds: float = 60.0


@dataclass
class DispatchConfig:
    grok_bin: str = "grok"
    model: str = ""
    max_turns: int = 80
    max_concurrent_jobs: int = 1
    cooldown_seconds: int = 300
    worktree_parent: str = ".."
    # Single branch for all monkey fixes (no per-job branches)
    work_branch: str = "AssIsstant"
    # Deprecated: ignored for pushes; kept for older mm.toml files
    branch_prefix: str = ""
    push: bool = True
    # One ongoing PR: work_branch → default_branch (commented on each job)
    create_pr: bool = True
    dry_run: bool = False
    rules: str = DEFAULT_RULES
    job_timeout_seconds: int = 3600


@dataclass
class HooksConfig:
    install_pre_push: bool = True
    install_post_commit: bool = False


@dataclass
class NotifyConfig:
    on_job_start: bool = True
    on_pr_created: bool = True


@dataclass
class ProjectConfig:
    name: str = ""
    default_branch: str = ""
    root: Path = field(default_factory=Path.cwd)


@dataclass
class Config:
    project: ProjectConfig = field(default_factory=ProjectConfig)
    logs: LogWatchConfig = field(default_factory=LogWatchConfig)
    process: ProcessWatchConfig = field(default_factory=ProcessWatchConfig)
    patterns: PatternsConfig = field(default_factory=PatternsConfig)
    known_bugs: KnownBugsConfig = field(default_factory=KnownBugsConfig)
    user_report: UserReportConfig = field(default_factory=UserReportConfig)
    github_issues: GitHubIssuesConfig = field(default_factory=GitHubIssuesConfig)
    dispatch: DispatchConfig = field(default_factory=DispatchConfig)
    hooks: HooksConfig = field(default_factory=HooksConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)

    @property
    def mm_dir(self) -> Path:
        return self.project.root / ".mm"

    @property
    def state_db(self) -> Path:
        return self.mm_dir / "state.db"

    @property
    def jobs_dir(self) -> Path:
        return self.mm_dir / "jobs"

    @property
    def logs_dir(self) -> Path:
        return self.mm_dir / "logs"

    @property
    def pidfile(self) -> Path:
        return self.mm_dir / "monkey.pid"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(x) for x in value]
    raise TypeError(f"expected list or string, got {type(value)}")


def _section(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(key, {})
    return cur if isinstance(cur, dict) else {}


def load_config(root: Path | None = None, path: Path | None = None) -> Config:
    """Load mm.toml from project root (or explicit path)."""
    root = (root or Path.cwd()).resolve()
    cfg_path = path or (root / "mm.toml")
    if not cfg_path.is_file():
        raise FileNotFoundError(
            f"No mm.toml at {cfg_path}. Run: python -m maintenance_monkey init"
        )

    with cfg_path.open("rb") as f:
        raw = tomllib.load(f)

    proj = _section(raw, "project")
    logs = _section(raw, "watch", "logs")
    # also allow flat [watch.logs] via nested watch
    if not logs and "watch" in raw and isinstance(raw["watch"], dict):
        logs = raw["watch"].get("logs") or {}
    process = _section(raw, "watch", "process")
    user_report = _section(raw, "watch", "user_report")
    github_issues = _section(raw, "watch", "github_issues")
    patterns = _section(raw, "patterns")
    known = _section(raw, "known_bugs")
    dispatch = _section(raw, "dispatch")
    hooks = _section(raw, "hooks")
    notify = _section(raw, "notify")

    name = str(proj.get("name") or root.name)
    default_branch = str(proj.get("default_branch") or "")

    cmd = process.get("command") or []
    if isinstance(cmd, str):
        cmd = cmd.split()

    cfg = Config(
        project=ProjectConfig(name=name, default_branch=default_branch, root=root),
        logs=LogWatchConfig(
            paths=_as_list(logs.get("paths")),
            from_start=bool(logs.get("from_start", False)),
        ),
        process=ProcessWatchConfig(
            enabled=bool(process.get("enabled", False)),
            command=[str(c) for c in cmd],
            cwd=str(process.get("cwd") or "."),
            restart_on_exit=bool(process.get("restart_on_exit", False)),
            incident_on_crash=bool(process.get("incident_on_crash", True)),
        ),
        patterns=PatternsConfig(
            include=_as_list(patterns.get("include")),
            exclude=_as_list(patterns.get("exclude")),
        ),
        known_bugs=KnownBugsConfig(
            path=str(known.get("path") or "known_bugs.yaml"),
            match_logs=bool(known.get("match_logs", True)),
        ),
        user_report=UserReportConfig(
            enabled=bool(user_report.get("enabled", True)),
            path=str(user_report.get("path") or "UserReport.md"),
            debounce_seconds=float(user_report.get("debounce_seconds", 2)),
            pull_before_scan=bool(user_report.get("pull_before_scan", False)),
            auto_check_on_pr=bool(user_report.get("auto_check_on_pr", True)),
            remote_poll_seconds=float(user_report.get("remote_poll_seconds", 30)),
            ignore=_as_list(user_report.get("ignore")),
        ),
        github_issues=GitHubIssuesConfig(
            enabled=bool(github_issues.get("enabled", False)),
            repo=str(
                github_issues.get("repo")
                or "LanceCoolie2018/XboxControllerBatteryLifeDisplay"
            ),
            labels=_as_list(github_issues.get("labels"))
            or ["customer-report"],
            state=str(github_issues.get("state") or "open"),
            poll_seconds=float(github_issues.get("poll_seconds", 60)),
        ),
        dispatch=DispatchConfig(
            grok_bin=str(dispatch.get("grok_bin") or "grok"),
            model=str(dispatch.get("model") or ""),
            max_turns=int(dispatch.get("max_turns", 80)),
            max_concurrent_jobs=int(dispatch.get("max_concurrent_jobs", 1)),
            cooldown_seconds=int(dispatch.get("cooldown_seconds", 300)),
            worktree_parent=str(dispatch.get("worktree_parent") or ".."),
            work_branch=str(dispatch.get("work_branch") or "AssIsstant"),
            branch_prefix=str(dispatch.get("branch_prefix") or ""),
            push=bool(dispatch.get("push", True)),
            create_pr=bool(dispatch.get("create_pr", True)),
            dry_run=bool(dispatch.get("dry_run", False)),
            rules=str(dispatch.get("rules") or DEFAULT_RULES),
            job_timeout_seconds=int(dispatch.get("job_timeout_seconds", 3600)),
        ),
        hooks=HooksConfig(
            install_pre_push=bool(hooks.get("install_pre_push", True)),
            install_post_commit=bool(hooks.get("install_post_commit", False)),
        ),
        notify=NotifyConfig(
            on_job_start=bool(notify.get("on_job_start", True)),
            on_pr_created=bool(notify.get("on_pr_created", True)),
        ),
    )
    return cfg


def example_toml(project_name: str = "my-project", default_branch: str = "main") -> str:
    return f'''# Maintenance Monkey project config
# https://github.com/LanceCoolie2018/maintenance-monkey

[project]
name = "{project_name}"
default_branch = "{default_branch}"

[watch.logs]
# Globs relative to repo root, or absolute paths
paths = ["logs/**/*.log"]
from_start = false

[watch.process]
enabled = false
# command = ["python", "-m", "myapp"]
# cwd = "."
restart_on_exit = false
incident_on_crash = true

[watch.user_report]
enabled = true
path = "UserReport.md"
debounce_seconds = 2
pull_before_scan = false
auto_check_on_pr = true
# Pi daemon: pull AssIsstant from origin this often so laptop pushes are seen
remote_poll_seconds = 30
# Never enqueue items matching these (jokes / out-of-scope)
ignore = [
  '(?i)monkey.*voice',
  '(?i)doesn.?t have a voice',
]

[patterns]
include = [
  '(?i)exception',
  '(?i)traceback \\(most recent call last\\)',
  'Unhandled exception',
  '(?i)fatal error',
  'panic:',
]
exclude = [
  '(?i)healthcheck failed.*retrying',
]

[known_bugs]
path = "known_bugs.yaml"
match_logs = true

[dispatch]
grok_bin = "grok"
# model = ""
max_turns = 80
max_concurrent_jobs = 1
cooldown_seconds = 300
worktree_parent = ".."
# All fixes land on this one branch (no AssIsstant-fix-* branches)
work_branch = "AssIsstant"
push = true
# Keep one PR: AssIsstant → main/master; each job comments on it
create_pr = true
dry_run = false
job_timeout_seconds = 3600
rules = """
Work only in this worktree. Commit your fix with a clear message.
All work is pushed to the AssIsstant branch only.
Never checkout or push main/master. Never force-push.
Do not modify secrets, credentials, or .mm/state.
Prefer minimal diffs. Run existing tests if available.
Do not open extra branches or PRs. Do not merge to master.
Do not delete other UserReport checklist items.
"""

[hooks]
install_pre_push = true
install_post_commit = false

[notify]
on_job_start = true
on_pr_created = true
'''

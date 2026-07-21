"""Git worktree, branch, push, and PR helpers with hard safety guards."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

from maintenance_monkey.config import Config

log = logging.getLogger("mm.git")

PROTECTED = frozenset({"main", "master", "HEAD"})


class GitError(RuntimeError):
    pass


def _run(
    cmd: list[str],
    cwd: Path,
    *,
    check: bool = True,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    log.debug("git cmd: %s (cwd=%s)", cmd, cwd)
    r = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and r.returncode != 0:
        raise GitError(
            f"command failed ({r.returncode}): {' '.join(cmd)}\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
    return r


def detect_default_branch(root: Path) -> str:
    r = _run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        root,
        check=False,
    )
    if r.returncode == 0 and r.stdout.strip():
        # refs/remotes/origin/main
        ref = r.stdout.strip()
        return ref.rsplit("/", 1)[-1]
    for name in ("main", "master"):
        r = _run(
            ["git", "show-ref", "--verify", f"refs/remotes/origin/{name}"],
            root,
            check=False,
        )
        if r.returncode == 0:
            return name
    r = _run(["git", "branch", "--show-current"], root, check=False)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return "main"


def ff_pull(cfg: Config) -> str:
    """Fast-forward the *current* branch from its origin remote (e.g. AssIsstant).

    Used by UserReport pull_before_scan so a Pi daemon on the AssIsstant branch
    picks up laptop pushes. Does not merge origin/main into the feature branch.
    """
    root = cfg.project.root
    try:
        _run(["git", "fetch", "origin"], root)
        cur = _run(["git", "branch", "--show-current"], root, check=False)
        branch = (cur.stdout or "").strip()
        if not branch:
            branch = cfg.project.default_branch or detect_default_branch(root)
        # Prefer tracking remote ref when present
        remote_ref = f"origin/{branch}"
        r = _run(["git", "rev-parse", "--verify", remote_ref], root, check=False)
        if r.returncode != 0:
            return f"pull skipped: no {remote_ref}"
        m = _run(
            ["git", "merge", "--ff-only", remote_ref],
            root,
            check=False,
        )
        if m.returncode != 0:
            return f"pull skipped/failed: {m.stderr.strip() or m.stdout.strip()}"
        return f"ff-only pull {remote_ref} ok"
    except GitError as e:
        return f"pull error: {e}"


def assert_safe_branch(cfg: Config, branch: str) -> None:
    if not branch.startswith(cfg.dispatch.branch_prefix):
        raise GitError(
            f"refusing branch {branch!r}: must start with {cfg.dispatch.branch_prefix!r}"
        )
    base = branch.split("/")[-1]
    if branch in PROTECTED or base in PROTECTED:
        raise GitError(f"refusing protected branch name {branch!r}")


def create_worktree(cfg: Config, job_id: str) -> tuple[Path, str]:
    root = cfg.project.root
    branch = f"{cfg.dispatch.branch_prefix}{job_id}"
    assert_safe_branch(cfg, branch)

    parent = Path(cfg.dispatch.worktree_parent)
    if not parent.is_absolute():
        parent = (root / parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)

    wt_name = f"{root.name}-mm-{job_id}"
    worktree = (parent / wt_name).resolve()

    # Confine worktree under parent
    if parent not in worktree.parents and worktree.parent != parent:
        raise GitError(f"worktree path escapes parent: {worktree}")

    if worktree.exists():
        raise GitError(f"worktree path already exists: {worktree}")

    base = cfg.project.default_branch or detect_default_branch(root)
    _run(["git", "fetch", "origin"], root)
    start_ref = f"origin/{base}"
    # fallback to local base
    r = _run(["git", "rev-parse", "--verify", start_ref], root, check=False)
    if r.returncode != 0:
        start_ref = base
        _run(["git", "rev-parse", "--verify", start_ref], root)

    _run(
        ["git", "worktree", "add", "-b", branch, str(worktree), start_ref],
        root,
    )
    log.info("created worktree %s on %s", worktree, branch)
    return worktree, branch


def copy_incident_into_worktree(worktree: Path, job_dir: Path) -> None:
    dest = worktree / ".mm" / "incident"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("evidence.txt", "meta.txt", "prompt.md"):
        src = job_dir / name
        if src.is_file():
            shutil.copy2(src, dest / name)


def has_changes(worktree: Path) -> bool:
    r = _run(["git", "status", "--porcelain"], worktree, check=False)
    return bool(r.stdout.strip())


def commit_if_needed(worktree: Path, message: str) -> bool:
    if not has_changes(worktree):
        # maybe agent already committed
        return False
    _run(["git", "add", "-A"], worktree)
    # avoid committing .mm state noise if any
    r = _run(["git", "status", "--porcelain"], worktree, check=False)
    if not r.stdout.strip():
        return False
    _run(["git", "commit", "-m", message], worktree)
    return True


def push_branch(cfg: Config, worktree: Path, branch: str) -> None:
    assert_safe_branch(cfg, branch)
    if branch in PROTECTED or branch.endswith("/main") or branch.endswith("/master"):
        raise GitError(f"refusing to push protected branch {branch}")
    _run(["git", "push", "-u", "origin", branch], worktree, timeout=180)


def create_pr(cfg: Config, branch: str, title: str, body: str) -> str:
    assert_safe_branch(cfg, branch)
    base = cfg.project.default_branch or detect_default_branch(cfg.project.root)
    if base in (branch,):
        raise GitError("PR base equals head")
    body_file = cfg.mm_dir / "pr_body.md"
    body_file.write_text(body, encoding="utf-8")
    r = _run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            base,
            "--head",
            branch,
            "--title",
            title[:200],
            "--body-file",
            str(body_file),
        ],
        cfg.project.root,
        timeout=120,
    )
    url = (r.stdout or "").strip().splitlines()
    return url[-1] if url else ""


def remove_worktree(cfg: Config, worktree: Path) -> None:
    root = cfg.project.root
    if not worktree.exists():
        return
    _run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        root,
        check=False,
    )
    if worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)


def short_job_slug(job_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9-]", "", job_id)[:12]

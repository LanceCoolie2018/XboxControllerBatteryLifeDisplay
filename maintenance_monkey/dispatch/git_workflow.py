"""Git worktree, AssIsstant work branch, push, and PR helpers with safety guards."""

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


def work_branch(cfg: Config) -> str:
    """Single branch where all monkey fixes land (default AssIsstant)."""
    name = (cfg.dispatch.work_branch or "AssIsstant").strip()
    if not name or name in PROTECTED:
        raise GitError(f"invalid work_branch {name!r}")
    return name


def ff_pull(cfg: Config) -> str:
    """Fast-forward the *current* branch from its origin remote (e.g. AssIsstant).

    The Pi daemon treats origin as source of truth for UserReport.md — local
    dirt on that file is discarded so a laptop push is never blocked.
    """
    root = cfg.project.root
    try:
        _run(["git", "fetch", "origin"], root)
        cur = _run(["git", "branch", "--show-current"], root, check=False)
        branch = (cur.stdout or "").strip()
        if not branch:
            branch = cfg.project.default_branch or detect_default_branch(root)
        remote_ref = f"origin/{branch}"
        r = _run(["git", "rev-parse", "--verify", remote_ref], root, check=False)
        if r.returncode != 0:
            return f"pull skipped: no {remote_ref}"

        # Discard local edits to UserReport so ff-only pull cannot get stuck
        ur = cfg.user_report.path
        st = _run(["git", "status", "--porcelain", "--", ur], root, check=False)
        if st.stdout.strip():
            _run(["git", "checkout", "--", ur], root, check=False)
            log.info("ff_pull: restored local %s from HEAD before pull", ur)

        m = _run(
            ["git", "merge", "--ff-only", remote_ref],
            root,
            check=False,
        )
        if m.returncode != 0:
            # Last resort: if still blocked by UserReport, force checkout from remote
            err = (m.stderr or m.stdout or "").strip()
            if "UserReport" in err or "overwritten by merge" in err:
                _run(["git", "checkout", "-f", remote_ref, "--", ur], root, check=False)
                m2 = _run(
                    ["git", "merge", "--ff-only", remote_ref],
                    root,
                    check=False,
                )
                if m2.returncode == 0:
                    return f"ff-only pull {remote_ref} ok (after UserReport reset)"
            return f"pull skipped/failed: {err}"
        return f"ff-only pull {remote_ref} ok"
    except GitError as e:
        return f"pull error: {e}"


def assert_safe_work_branch(cfg: Config, branch: str) -> None:
    """Only the configured work_branch may receive monkey pushes (never main/master)."""
    allowed = work_branch(cfg)
    if branch != allowed:
        raise GitError(
            f"refusing branch {branch!r}: monkey only pushes to {allowed!r}"
        )
    if branch in PROTECTED:
        raise GitError(f"refusing protected branch {branch!r}")


def create_worktree(cfg: Config, job_id: str) -> tuple[Path, str]:
    """Detached worktree at origin/<work_branch> — all fixes share that branch name.

    Detached HEAD avoids checking AssIsstant out twice (main tree already uses it).
    After commits, push with: git push origin HEAD:AssIsstant
    """
    root = cfg.project.root
    branch = work_branch(cfg)
    assert_safe_work_branch(cfg, branch)

    parent = Path(cfg.dispatch.worktree_parent)
    if not parent.is_absolute():
        parent = (root / parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)

    wt_name = f"{root.name}-mm-{job_id}"
    worktree = (parent / wt_name).resolve()

    if parent not in worktree.parents and worktree.parent != parent:
        raise GitError(f"worktree path escapes parent: {worktree}")

    if worktree.exists():
        # leftover from a crashed job
        remove_worktree(cfg, worktree)

    _run(["git", "fetch", "origin"], root)
    start_ref = f"origin/{branch}"
    r = _run(["git", "rev-parse", "--verify", start_ref], root, check=False)
    if r.returncode != 0:
        # first-time: create work_branch from default if missing on remote
        base = cfg.project.default_branch or detect_default_branch(root)
        base_ref = f"origin/{base}"
        _run(["git", "rev-parse", "--verify", base_ref], root)
        _run(
            ["git", "worktree", "add", "-b", branch, str(worktree), base_ref],
            root,
        )
        _run(["git", "push", "-u", "origin", branch], worktree, timeout=180)
        log.info("created work_branch %s and worktree %s", branch, worktree)
        return worktree, branch

    # Detached at latest AssIsstant — no new branch name
    _run(
        ["git", "worktree", "add", "--detach", str(worktree), start_ref],
        root,
    )
    log.info("created detached worktree %s at %s", worktree, start_ref)
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
        return False
    _run(["git", "add", "-A"], worktree)
    # Don't commit monkey runtime noise if present
    r = _run(["git", "status", "--porcelain"], worktree, check=False)
    if not r.stdout.strip():
        return False
    _run(["git", "commit", "-m", message], worktree)
    return True


def push_branch(cfg: Config, worktree: Path, branch: str) -> None:
    """Push current worktree HEAD to origin/<work_branch> (no per-job branches)."""
    assert_safe_work_branch(cfg, branch)
    # Refresh remote tip; if others pushed, try rebase for serial agent work
    _run(["git", "fetch", "origin"], worktree, check=False)
    remote = f"origin/{branch}"
    r = _run(["git", "rev-parse", "--verify", remote], worktree, check=False)
    if r.returncode == 0:
        # Rebase our commits onto latest AssIsstant if needed
        rb = _run(
            ["git", "rebase", remote],
            worktree,
            check=False,
            timeout=120,
        )
        if rb.returncode != 0:
            _run(["git", "rebase", "--abort"], worktree, check=False)
            raise GitError(
                f"cannot rebase onto {remote}; pull AssIsstant and retry.\n"
                f"{rb.stderr or rb.stdout}"
            )
    # Push detached HEAD to the single work branch
    _run(
        ["git", "push", "origin", f"HEAD:refs/heads/{branch}"],
        worktree,
        timeout=180,
    )
    log.info("pushed worktree HEAD → origin/%s", branch)


def ensure_pr(cfg: Config, title: str, body: str) -> str:
    """Ensure a single PR work_branch → default_branch exists; return URL."""
    branch = work_branch(cfg)
    assert_safe_work_branch(cfg, branch)
    base = cfg.project.default_branch or detect_default_branch(cfg.project.root)
    if base == branch:
        raise GitError("PR base equals work_branch")

    # Existing open PR?
    listed = _run(
        [
            "gh",
            "pr",
            "list",
            "--base",
            base,
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "url",
            "--limit",
            "1",
        ],
        cfg.project.root,
        check=False,
        timeout=60,
    )
    if listed.returncode == 0 and listed.stdout.strip():
        try:
            import json

            rows = json.loads(listed.stdout)
            if rows and rows[0].get("url"):
                url = rows[0]["url"]
                # Comment with this job's summary
                _run(
                    ["gh", "pr", "comment", url, "--body", body[:6000]],
                    cfg.project.root,
                    check=False,
                    timeout=60,
                )
                return url
        except Exception:
            pass

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


def create_pr(cfg: Config, branch: str, title: str, body: str) -> str:
    """Back-compat name: single work_branch PR."""
    return ensure_pr(cfg, title, body)


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


def commits_ahead(cfg: Config, limit: int = 12) -> list[str]:
    """Recent commits on work_branch not in default_branch (for dashboard)."""
    root = cfg.project.root
    branch = work_branch(cfg)
    base = cfg.project.default_branch or detect_default_branch(root)
    _run(["git", "fetch", "origin"], root, check=False)
    r = _run(
        [
            "git",
            "log",
            f"origin/{base}..origin/{branch}",
            "--oneline",
            f"-{limit}",
        ],
        root,
        check=False,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]

"""CLI entrypoint: python -m maintenance_monkey <command>."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from maintenance_monkey import __version__
from maintenance_monkey.config import Config, example_toml, load_config
from maintenance_monkey.daemon import Daemon, run_once
from maintenance_monkey.dispatch import git_workflow
from maintenance_monkey.dispatch.grok_runner import GrokRunner
from maintenance_monkey.pipeline.fingerprint import fingerprint_text
from maintenance_monkey.pipeline.queue import enqueue_incident
from maintenance_monkey.dashboard import run_dashboard
from maintenance_monkey.sensors.user_report import scan_user_report
from maintenance_monkey.state import State


def _setup_logging(cfg: Config | None, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if cfg:
        cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(cfg.logs_dir / "monkey.log", encoding="utf-8")
        handlers.append(fh)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _root_from_args(args: argparse.Namespace) -> Path:
    root = Path(args.cwd).resolve() if getattr(args, "cwd", None) else Path.cwd().resolve()
    return root


def _load(args: argparse.Namespace) -> tuple[Config, State]:
    root = _root_from_args(args)
    cfg = load_config(root)
    if not cfg.project.default_branch:
        cfg.project.default_branch = git_workflow.detect_default_branch(root)
    cfg.mm_dir.mkdir(parents=True, exist_ok=True)
    state = State(cfg.state_db)
    return cfg, state


def cmd_init(args: argparse.Namespace) -> int:
    root = _root_from_args(args)
    cfg_path = root / "mm.toml"
    branch = "main"
    try:
        branch = git_workflow.detect_default_branch(root)
    except Exception:
        pass

    if cfg_path.exists() and not args.force:
        print(f"mm.toml already exists at {cfg_path}")
    else:
        name = root.name
        cfg_path.write_text(example_toml(name, branch), encoding="utf-8")
        print(f"wrote {cfg_path}")

    ur = root / "UserReport.md"
    if not ur.exists():
        example = Path(__file__).resolve().parent.parent / "UserReport.md.example"
        if example.is_file():
            ur.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            ur.write_text(
                "# User Report\n\n## Open\n\n- [ ] Example: describe something to fix\n",
                encoding="utf-8",
            )
        print(f"wrote {ur}")

    gi = root / ".gitignore"
    line = ".mm/"
    if gi.exists():
        text = gi.read_text(encoding="utf-8")
        if line not in text.splitlines() and ".mm" not in text:
            with gi.open("a", encoding="utf-8") as f:
                f.write(f"\n# Maintenance Monkey runtime\n{line}\n")
            print(f"updated {gi}")
    else:
        gi.write_text(f"# Maintenance Monkey runtime\n{line}\n", encoding="utf-8")
        print(f"wrote {gi}")

    mm = root / ".mm"
    mm.mkdir(exist_ok=True)
    (mm / "jobs").mkdir(exist_ok=True)
    (mm / "logs").mkdir(exist_ok=True)
    print(f"init ok (default_branch={branch})")
    print("Next: edit mm.toml, then: python -m maintenance_monkey install-hooks")
    print("      python -m maintenance_monkey start")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = _root_from_args(args)
    print(f"project root: {root}")
    print(f"maintenance-monkey version: {__version__}")
    ok = True

    cfg_path = root / "mm.toml"
    if not cfg_path.is_file():
        print("FAIL: mm.toml missing (run init)")
        ok = False
    else:
        try:
            cfg = load_config(root)
            print(f"OK: mm.toml loaded (project={cfg.project.name})")
        except Exception as e:
            print(f"FAIL: mm.toml: {e}")
            ok = False
            return 1

    if not cfg.project.default_branch:
        cfg.project.default_branch = git_workflow.detect_default_branch(root)
    print(f"default_branch: {cfg.project.default_branch}")

    ur = root / cfg.user_report.path
    print(f"UserReport: {'OK ' + str(ur) if ur.is_file() else 'MISSING ' + str(ur)}")

    for name, path in (
        ("grok", cfg.dispatch.grok_bin),
        ("git", "git"),
        ("gh", "gh"),
    ):
        found = shutil.which(path) if not Path(path).is_file() else path
        if found:
            print(f"OK: {name} -> {found}")
        else:
            print(f"FAIL: {name} not found ({path})")
            ok = False

    # gh auth
    import subprocess

    r = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode == 0:
        print("OK: gh auth")
    else:
        print("FAIL: gh auth — run: gh auth login -h github.com -p https -w")
        print((r.stderr or r.stdout or "")[:300])
        ok = False

    if (root / ".git").exists() or (root / ".git").is_file():
        print("OK: git repository")
    else:
        print("WARN: not a git repository")

    print("doctor:", "PASS" if ok else "ISSUES FOUND")
    return 0 if ok else 1


def cmd_start(args: argparse.Namespace) -> int:
    cfg, state = _load(args)
    _setup_logging(cfg, args.verbose)
    if cfg.pidfile.is_file():
        try:
            old = int(cfg.pidfile.read_text().strip() or "0")
            os.kill(old, 0)
            print(f"already running pid={old}", file=sys.stderr)
            return 1
        except (OSError, ValueError):
            cfg.pidfile.unlink(missing_ok=True)
    Daemon(cfg, state).run()
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    cfg, _ = _load(args)
    if not cfg.pidfile.is_file():
        print("not running")
        return 0
    try:
        pid = int(cfg.pidfile.read_text().strip())
        os.kill(pid, 15)
        print(f"sent SIGTERM to {pid}")
        return 0
    except (OSError, ValueError) as e:
        print(f"stop failed: {e}")
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    cfg, state = _load(args)
    if getattr(args, "watch", False):
        return run_dashboard(cfg, state, interval=float(args.interval))
    print(f"project: {cfg.project.name}")
    print(f"root: {cfg.project.root}")
    print(f"default_branch: {cfg.project.default_branch}")
    running = cfg.pidfile.is_file()
    if running:
        try:
            pid = int(cfg.pidfile.read_text().strip())
            os.kill(pid, 0)
            print(f"daemon: running pid={pid}")
        except (OSError, ValueError):
            print("daemon: stopped (stale pidfile)")
    else:
        print("daemon: stopped")
    print("\nIncidents (recent):")
    for inc in state.list_incidents(10):
        print(f"  {inc.id} [{inc.source}] {inc.title[:70]}")
    print("\nJobs (recent):")
    for job in state.list_jobs(10):
        pr = f" {job.pr_url}" if job.pr_url else ""
        err = f" err={job.error[:40]}" if job.error else ""
        print(f"  {job.id} {job.status} branch={job.branch or '-'}{pr}{err}")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Live-updating terminal panel for the Pi desktop."""
    cfg, state = _load(args)
    return run_dashboard(cfg, state, interval=float(args.interval))


def cmd_user_report(args: argparse.Namespace) -> int:
    cfg, state = _load(args)
    _setup_logging(cfg, args.verbose)
    trigger = getattr(args, "trigger", None) or "manual"
    msgs = scan_user_report(cfg, state, trigger=trigger)
    for m in msgs:
        print(m)
    if getattr(args, "dispatch", False):
        runner = GrokRunner(cfg, state)
        for m in runner.process_queue():
            print(m)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    cfg, state = _load(args)
    text = " ".join(args.text).strip()
    if not text:
        print("empty report", file=sys.stderr)
        return 1
    fp = fingerprint_text("manual", text)
    _, job, msg = enqueue_incident(
        state,
        cfg,
        source="manual",
        fingerprint=fp,
        title=text[:100],
        body=f"# Manual report\n\n{text}\n",
    )
    print(msg)
    if args.dispatch and job:
        print(GrokRunner(cfg, state).run_job(job))
    return 0


def cmd_once(args: argparse.Namespace) -> int:
    cfg, state = _load(args)
    _setup_logging(cfg, args.verbose)
    for m in run_once(cfg, state):
        print(m)
    return 0


def cmd_job(args: argparse.Namespace) -> int:
    cfg, state = _load(args)
    sub = args.job_cmd
    if sub == "list":
        for job in state.list_jobs(args.limit):
            print(
                f"{job.id}\t{job.status}\t{job.fingerprint}\t{job.branch or ''}\t{job.pr_url or ''}"
            )
        return 0
    if sub == "show":
        job = state.get_job(args.job_id)
        if not job:
            print("not found")
            return 1
        inc = state.get_incident(job.incident_id)
        print(f"job: {job.id}")
        print(f"status: {job.status}")
        print(f"branch: {job.branch}")
        print(f"worktree: {job.worktree}")
        print(f"pr: {job.pr_url}")
        print(f"session: {job.session_id}")
        print(f"error: {job.error}")
        if inc:
            print(f"incident: {inc.title}")
            print(inc.body[:2000])
        return 0
    if sub == "retry":
        old = state.get_job(args.job_id)
        if not old:
            print("not found")
            return 1
        inc = state.get_incident(old.incident_id)
        if not inc:
            print("incident missing")
            return 1
        # clear open job lock by marking failed if needed
        if old.status in ("queued", "running", "pushing"):
            state.update_job(old.id, status="cancelled")
        new = state.create_job(inc)
        print(f"retry queued as {new.id}")
        if args.dispatch:
            print(GrokRunner(cfg, state).run_job(new))
        return 0
    print("unknown job command")
    return 1


def cmd_install_hooks(args: argparse.Namespace) -> int:
    cfg, _ = _load(args)
    root = cfg.project.root
    git_dir = root / ".git"
    if git_dir.is_file():
        # submodule/worktree: .git is a file pointing to real dir
        text = git_dir.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            git_dir = (root / text.split(":", 1)[1].strip()).resolve()
    hooks = git_dir / "hooks"
    if not hooks.is_dir():
        print(f"no git hooks dir at {hooks}", file=sys.stderr)
        return 1

    # Resolve how to invoke mm
    mm_pkg = Path(__file__).resolve().parent
    repo_root = mm_pkg.parent
    py = sys.executable
    env_pythonpath = str(repo_root)

    def write_hook(name: str, body: str) -> None:
        path = hooks / name
        if path.exists() and not args.force:
            existing = path.read_text(encoding="utf-8", errors="replace")
            if "maintenance_monkey" in existing or "Maintenance Monkey" in existing:
                print(f"hook {name} already installed")
                return
            # backup
            bak = path.with_suffix(path.suffix + f".bak.{int(time.time())}")
            shutil.copy2(path, bak)
            print(f"backed up existing {name} -> {bak.name}")
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
        print(f"installed {path}")

    pre_push = f"""#!/usr/bin/env bash
# Maintenance Monkey pre-push — scan UserReport if it is in the push
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
export PYTHONPATH="{env_pythonpath}${{PYTHONPATH:+:$PYTHONPATH}}"
UR_PATH="UserReport.md"
if [[ -f "$ROOT/mm.toml" ]]; then
  # best-effort path from config
  :
fi
# Determine if UserReport is among commits being pushed
touched=0
while read -r local_ref local_sha remote_ref remote_sha; do
  if [[ "$local_sha" =~ ^0+$ ]]; then
    continue
  fi
  if [[ "$remote_sha" =~ ^0+$ ]]; then
    range="$local_sha"
  else
    range="$remote_sha..$local_sha"
  fi
  if git diff --name-only "$range" 2>/dev/null | grep -qx "$UR_PATH" \\
    || git diff --name-only "$range" 2>/dev/null | grep -q "UserReport.md"; then
    touched=1
  fi
done
if [[ "$touched" -eq 1 ]]; then
  echo "[maintenance-monkey] UserReport changed in push — scanning..."
  "{py}" -m maintenance_monkey user-report scan --cwd "$ROOT" --trigger push || true
fi
exit 0
"""

    if cfg.hooks.install_pre_push:
        write_hook("pre-push", pre_push)

    if cfg.hooks.install_post_commit:
        post_commit = f"""#!/usr/bin/env bash
# Maintenance Monkey post-commit — scan if UserReport was in the commit
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
export PYTHONPATH="{env_pythonpath}${{PYTHONPATH:+:$PYTHONPATH}}"
if git diff-tree --no-commit-id --name-only -r HEAD | grep -q "UserReport.md"; then
  echo "[maintenance-monkey] UserReport committed — scanning..."
  "{py}" -m maintenance_monkey user-report scan --cwd "$ROOT" --trigger commit || true
fi
exit 0
"""
        write_hook("post-commit", post_commit)

    print("hooks installed")
    return 0


def cmd_install_systemd(args: argparse.Namespace) -> int:
    cfg, _ = _load(args)
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in cfg.project.name)
    unit_path = unit_dir / f"maintenance-monkey-{safe}.service"
    py = sys.executable
    mm_root = Path(__file__).resolve().parent.parent
    content = f"""[Unit]
Description=Maintenance Monkey for {cfg.project.name}
After=network-online.target

[Service]
Type=simple
WorkingDirectory={cfg.project.root}
Environment=PYTHONPATH={mm_root}
ExecStart={py} -m maintenance_monkey start --cwd {cfg.project.root}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""
    unit_path.write_text(content, encoding="utf-8")
    print(f"wrote {unit_path}")
    print("Enable with:")
    print(f"  systemctl --user daemon-reload")
    print(f"  systemctl --user enable --now maintenance-monkey-{safe}.service")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cwd", default=None, help="Project root (default: cwd)")
    common.add_argument("-v", "--verbose", action="store_true")

    p = argparse.ArgumentParser(
        prog="maintenance_monkey",
        description="Maintenance Monkey — watch projects and dispatch Grok fix jobs",
        parents=[common],
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="Initialize mm.toml, UserReport, .mm/", parents=[common])
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("doctor", help="Check config and tools", parents=[common])
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("start", help="Run daemon", parents=[common])
    s.set_defaults(func=cmd_start)

    s = sub.add_parser("stop", help="Stop daemon", parents=[common])
    s.set_defaults(func=cmd_stop)

    s = sub.add_parser("status", help="Show incidents and jobs", parents=[common])
    s.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help="Live dashboard (same as 'dashboard')",
    )
    s.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Refresh seconds when using --watch (default 2)",
    )
    s.set_defaults(func=cmd_status)

    s = sub.add_parser(
        "dashboard",
        help="Live status terminal for Pi desktop / dashboard",
        parents=[common],
    )
    s.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Refresh seconds (default 2)",
    )
    s.set_defaults(func=cmd_dashboard)

    s = sub.add_parser("user-report", help="UserReport commands", parents=[common])
    ur = s.add_subparsers(dest="ur_cmd", required=True)
    sc = ur.add_parser(
        "scan", help="Scan UserReport and enqueue open items", parents=[common]
    )
    sc.add_argument("--trigger", default="manual")
    sc.add_argument("--dispatch", action="store_true", help="Also run queued jobs")
    sc.set_defaults(func=cmd_user_report)

    s = sub.add_parser("report", help="File a manual incident", parents=[common])
    s.add_argument("text", nargs="+")
    s.add_argument("--dispatch", action="store_true")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("once", help="Single scan + process queue pass", parents=[common])
    s.set_defaults(func=cmd_once)

    s = sub.add_parser("job", help="Job management", parents=[common])
    js = s.add_subparsers(dest="job_cmd", required=True)
    jlist = js.add_parser("list", parents=[common])
    jlist.add_argument("--limit", type=int, default=50)
    jlist.set_defaults(func=cmd_job)
    jshow = js.add_parser("show", parents=[common])
    jshow.add_argument("job_id")
    jshow.set_defaults(func=cmd_job)
    jretry = js.add_parser("retry", parents=[common])
    jretry.add_argument("job_id")
    jretry.add_argument("--dispatch", action="store_true")
    jretry.set_defaults(func=cmd_job)

    s = sub.add_parser(
        "install-hooks", help="Install git pre-push hook", parents=[common]
    )
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_install_hooks)

    s = sub.add_parser(
        "install-systemd", help="Write user systemd unit", parents=[common]
    )
    s.set_defaults(func=cmd_install_systemd)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

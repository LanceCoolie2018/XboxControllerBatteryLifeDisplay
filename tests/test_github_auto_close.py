"""Tests for GitHub issue ready-for-review / dismiss / task-complete close."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from maintenance_monkey.config import Config, DispatchConfig, GitHubIssuesConfig, ProjectConfig
from maintenance_monkey.sensors import github_issues as gi
from maintenance_monkey.state import Incident


def _cfg(**kwargs: object) -> Config:
    gi_cfg = GitHubIssuesConfig(
        enabled=bool(kwargs.get("enabled", True)),
        repo=str(kwargs.get("repo", "owner/repo")),
        mark_ready_on_done=bool(kwargs.get("mark_ready_on_done", True)),
        ready_label=str(kwargs.get("ready_label", "mm-ready-for-review")),
        close_on_task_complete=bool(kwargs.get("close_on_task_complete", True)),
        auto_close_on_done=bool(kwargs.get("auto_close_on_done", False)),
        dismiss_labels=list(
            kwargs.get(
                "dismiss_labels",
                ["invalid", "wontfix", "false-report", "mm-dismissed"],
            )
        ),
    )
    return Config(
        project=ProjectConfig(name="t", default_branch="master"),
        github_issues=gi_cfg,
        dispatch=DispatchConfig(work_branch="AssIsstant"),
    )


class TestLifecycleHelpers(unittest.TestCase):
    def test_ready_and_dismiss_detection(self) -> None:
        cfg = _cfg()
        self.assertTrue(
            gi.issue_is_ready_for_review(cfg, ["customer-report", "mm-ready-for-review"])
        )
        self.assertFalse(gi.issue_is_ready_for_review(cfg, ["customer-report"]))
        self.assertTrue(gi.issue_is_dismissed(cfg, ["invalid"]))
        self.assertTrue(gi.issue_is_dismissed(cfg, ["false-report"]))
        self.assertFalse(gi.issue_is_dismissed(cfg, ["customer-report"]))

    def test_build_ready_comment(self) -> None:
        c = gi.build_ready_comment(job_id="j1", pr_url="http://pr", summary="done")
        self.assertIn("j1", c)
        self.assertIn("http://pr", c)
        self.assertIn("ready for review", c.lower())
        self.assertIn("open", c.lower())

    def test_build_close_comments(self) -> None:
        c = gi.build_close_comment(job_id="j1", reason="task_complete")
        self.assertIn("task complete", c.lower())
        d = gi.build_close_comment(job_id="d", reason="dismiss", summary="not real")
        self.assertIn("false", d.lower())
        self.assertIn("not real", d)

    def test_legacy_auto_close_disabled(self) -> None:
        cfg = _cfg(auto_close_on_done=False)
        ok, msg = gi.close_issue_after_fix(cfg, 5, job_id="j")
        self.assertFalse(ok)
        self.assertIn("disabled", msg)

    def test_mark_ready_success(self) -> None:
        cfg = _cfg()
        with patch.object(gi, "_gh_available", return_value=True), patch.object(
            gi, "ensure_label"
        ), patch.object(gi, "_run_gh", return_value=(0, "ok", "")) as run:
            ok, msg = gi.mark_issue_ready_for_review(
                cfg, 19, job_id="abc", pr_url="http://pr"
            )
            self.assertTrue(ok)
            self.assertIn("ready", msg.lower())
            # comment + edit (and maybe remove needs-triage retry)
            self.assertGreaterEqual(run.call_count, 2)
            cmds = [" ".join(c[0][0][:3]) for c in run.call_args_list]
            self.assertTrue(any("issue comment" in x for x in cmds))
            self.assertTrue(any("issue edit" in x for x in cmds))

    def test_mark_ready_disabled(self) -> None:
        cfg = _cfg(mark_ready_on_done=False)
        ok, msg = gi.mark_issue_ready_for_review(cfg, 19, job_id="j")
        self.assertFalse(ok)
        self.assertIn("disabled", msg)

    def test_close_on_task_complete(self) -> None:
        cfg = _cfg()
        with patch.object(gi, "_gh_available", return_value=True), patch.object(
            gi, "ensure_label"
        ), patch.object(gi, "_run_gh", return_value=(0, "Closed", "")) as run:
            ok, msg = gi.close_issue(cfg, 19, job_id="abc", reason="task_complete")
            self.assertTrue(ok)
            self.assertIn("closed", msg.lower())
            close_calls = [
                c[0][0] for c in run.call_args_list if c[0][0][:2] == ["issue", "close"]
            ]
            self.assertEqual(len(close_calls), 1)
            self.assertEqual(close_calls[0][:3], ["issue", "close", "19"])

    def test_already_closed_treated_ok(self) -> None:
        cfg = _cfg()
        with patch.object(gi, "_gh_available", return_value=True), patch.object(
            gi, "ensure_label"
        ), patch.object(
            gi, "_run_gh", return_value=(1, "", "issue is already closed")
        ):
            ok, msg = gi.close_issue(cfg, 19, job_id="abc")
            self.assertTrue(ok)
            self.assertIn("already closed", msg.lower())

    def test_mark_ready_for_incident(self) -> None:
        cfg = _cfg()
        inc = Incident(
            id="i",
            source="github_issue",
            fingerprint="github-issue:19",
            title="GitHub #19: x",
            body="",
            status="open",
            created_at=0.0,
            meta={"issue_number": 19},
        )
        with patch.object(
            gi,
            "mark_issue_ready_for_review",
            return_value=(True, "marked GitHub issue #19 mm-ready-for-review"),
        ) as mocked:
            msg = gi.mark_ready_for_incident(cfg, inc, job_id="job1", pr_url="http://p")
            self.assertIn("19", msg)
            mocked.assert_called_once()

    def test_mark_ready_non_github(self) -> None:
        cfg = _cfg()
        inc = Incident(
            id="i",
            source="user_report",
            fingerprint="x",
            title="t",
            body="",
            status="open",
            created_at=0.0,
            meta={},
        )
        self.assertEqual(gi.mark_ready_for_incident(cfg, inc, job_id="j"), "")

    def test_dismiss_clears_jobs(self) -> None:
        cfg = _cfg()
        state = MagicMock()
        job = MagicMock()
        job.id = "j1"
        job.fingerprint = "github-issue:19"
        job.status = "done"
        job.meta = {}
        state.list_jobs.return_value = [job]
        with patch.object(
            gi, "close_issue", return_value=(True, "closed GitHub issue #19 (dismiss)")
        ):
            msgs = gi.dismiss_issue(cfg, state, 19, reason="not a bug")
        self.assertTrue(any("closed" in m.lower() for m in msgs))
        state.update_job.assert_called()
        kwargs = state.update_job.call_args
        self.assertEqual(kwargs[0][0], "j1")
        self.assertEqual(kwargs[1]["status"], "archived")

    def test_is_issue_open(self) -> None:
        cfg = _cfg()
        with patch.object(gi, "_gh_available", return_value=True), patch.object(
            gi, "_run_gh", return_value=(0, "OPEN\n", "")
        ):
            self.assertTrue(gi.is_issue_open(cfg, 1))
        with patch.object(gi, "_gh_available", return_value=True), patch.object(
            gi, "_run_gh", return_value=(0, "closed\n", "")
        ):
            self.assertFalse(gi.is_issue_open(cfg, 1))

    def test_scan_skips_ready_and_dismissed(self) -> None:
        cfg = _cfg()
        state = MagicMock()
        ready = gi.GhIssue(
            number=1,
            title="a",
            body="",
            html_url="u",
            labels=["customer-report", "mm-ready-for-review"],
            state="open",
            updated_at="",
        )
        bad = gi.GhIssue(
            number=2,
            title="b",
            body="",
            html_url="u",
            labels=["customer-report", "invalid"],
            state="open",
            updated_at="",
        )
        with patch.object(
            gi, "fetch_open_issues", return_value=([ready, bad], "fetched 2")
        ), patch.object(gi, "enqueue_incident") as enq:
            # enqueue is imported inside scan from pipeline — patch module path
            pass
        with patch.object(
            gi, "fetch_open_issues", return_value=([ready, bad], "fetched 2")
        ), patch(
            "maintenance_monkey.sensors.github_issues.enqueue_incident"
        ) as enq:
            msgs = gi.scan_github_issues(cfg, state, trigger="test")
        enq.assert_not_called()
        self.assertTrue(any("ready" in m.lower() for m in msgs))
        self.assertTrue(any("dismissed" in m.lower() for m in msgs))


if __name__ == "__main__":
    unittest.main()

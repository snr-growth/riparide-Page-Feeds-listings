# -*- coding: utf-8 -*-
"""Unit tests for railway_service.py.

No live Railway account is reachable from this environment, so these tests
cover everything that can be verified without one: the auto-run scheduling
decision, that a failed subprocess never crashes the service or corrupts
state, the token check on the manual trigger endpoint, and that the file
server serves exactly what's on disk (including a 404 before the first
run has ever produced anything, and no crash on a still-in-progress run).
"""
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from unittest import mock

import railway_service as svc


class ShouldAutoRunTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_before_the_configured_day_does_not_run(self):
        os.environ["RAILWAY_RUN_DAY"] = "5"
        os.environ["RAILWAY_RUN_HOUR"] = "3"
        now = datetime(2026, 9, 4, 23, 0, tzinfo=timezone.utc)  # day before the configured day
        self.assertFalse(svc.should_auto_run(now, {}))

    def test_on_the_day_but_before_the_hour_does_not_run(self):
        os.environ["RAILWAY_RUN_DAY"] = "1"
        os.environ["RAILWAY_RUN_HOUR"] = "3"
        now = datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc)
        self.assertFalse(svc.should_auto_run(now, {}))

    def test_on_or_after_the_scheduled_time_runs_once(self):
        os.environ["RAILWAY_RUN_DAY"] = "1"
        os.environ["RAILWAY_RUN_HOUR"] = "3"
        now = datetime(2026, 9, 1, 3, 30, tzinfo=timezone.utc)
        self.assertTrue(svc.should_auto_run(now, {}))

    def test_does_not_run_twice_in_the_same_month(self):
        os.environ["RAILWAY_RUN_DAY"] = "1"
        os.environ["RAILWAY_RUN_HOUR"] = "3"
        now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
        state = {"last_run_month": "2026-09"}
        self.assertFalse(svc.should_auto_run(now, state))

    def test_runs_again_the_following_month(self):
        os.environ["RAILWAY_RUN_DAY"] = "1"
        os.environ["RAILWAY_RUN_HOUR"] = "3"
        now = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)
        state = {"last_run_month": "2026-09"}
        self.assertTrue(svc.should_auto_run(now, state))


class RunPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_state_file = svc.STATE_FILE
        svc.STATE_FILE = os.path.join(self.tmp, "state.json")
        svc._run_in_progress = False

    def tearDown(self):
        svc.STATE_FILE = self._orig_state_file
        svc._run_in_progress = False
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_failed_subprocess_is_recorded_not_raised(self):
        with mock.patch("subprocess.run") as m:
            m.return_value = mock.Mock(returncode=1)
            ok = svc.run_pipeline(reason="test")
        self.assertFalse(ok)
        state = svc.load_state()
        self.assertFalse(state["last_run_ok"])
        self.assertEqual(state["last_run_reason"], "test")

    def test_a_crash_before_the_subprocess_returns_is_recorded_not_raised(self):
        # e.g. the interpreter itself can't be found, or the timeout fires -
        # this must never take the always-on HTTP server down with it.
        with mock.patch("subprocess.run", side_effect=OSError("no such file")):
            ok = svc.run_pipeline(reason="test")
        self.assertFalse(ok)
        state = svc.load_state()
        self.assertFalse(state["last_run_ok"])

    def test_a_successful_run_is_recorded(self):
        with mock.patch("subprocess.run") as m:
            m.return_value = mock.Mock(returncode=0)
            ok = svc.run_pipeline(reason="test")
        self.assertTrue(ok)
        self.assertTrue(svc.load_state()["last_run_ok"])

    def test_a_run_already_in_progress_is_not_started_twice(self):
        svc._run_in_progress = True
        with mock.patch("subprocess.run") as m:
            ok = svc.run_pipeline(reason="test")
        m.assert_not_called()
        self.assertFalse(ok)


class HTTPServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.tmp, "output")
        self.report_dir = os.path.join(self.tmp, "reports")
        os.makedirs(self.output_dir)
        os.makedirs(self.report_dir)

        import config as cfg
        self._orig = (cfg.OUTPUT_DIR, cfg.REPORT_DIR)
        cfg.OUTPUT_DIR, cfg.REPORT_DIR = self.output_dir, self.report_dir

        self._orig_state_file = svc.STATE_FILE
        svc.STATE_FILE = os.path.join(self.tmp, "state.json")

        self._orig_token = os.environ.get("RUN_TRIGGER_TOKEN")
        os.environ["RUN_TRIGGER_TOKEN"] = "test-secret"

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), svc.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        import config as cfg
        cfg.OUTPUT_DIR, cfg.REPORT_DIR = self._orig
        svc.STATE_FILE = self._orig_state_file
        if self._orig_token is None:
            os.environ.pop("RUN_TRIGGER_TOKEN", None)
        else:
            os.environ["RUN_TRIGGER_TOKEN"] = self._orig_token
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _get(self, path):
        return urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, path), timeout=5)

    def test_healthz(self):
        with self._get("/healthz") as r:
            self.assertEqual(r.status, 200)

    def test_csv_not_yet_generated_is_a_clean_404_not_a_crash(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/riparide-page-feed-core.csv")
        self.assertEqual(ctx.exception.code, 404)

    def test_a_404_is_never_cacheable(self):
        # Reproduces a real issue found live behind Railway's edge proxy: a
        # "not generated yet" 404 with no cache directive at all kept being
        # returned after the file had already started existing. Every
        # response needs an explicit no-store, not just the success path.
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/riparide-page-feed-core.csv")
        self.assertEqual(ctx.exception.headers["Cache-Control"], "no-store")

    def test_csv_is_served_once_written(self):
        with open(os.path.join(self.output_dir, "riparide-page-feed-core.csv"), "w") as f:
            f.write("Page URL,Custom label\nhttps://x,PAGE_LISTING\n")
        with self._get("/riparide-page-feed-core.csv") as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers["Content-Type"], "text/csv; charset=utf-8")
            self.assertIn(b"Page URL,Custom label", r.read())

    def test_xlsx_is_served_with_the_right_content_type(self):
        with open(os.path.join(self.report_dir, "riparide-page-feed-report.xlsx"), "wb") as f:
            f.write(b"fake xlsx bytes")
        with self._get("/riparide-page-feed-report.xlsx") as r:
            self.assertEqual(r.status, 200)
            self.assertIn("spreadsheetml", r.headers["Content-Type"])

    def test_head_request_is_supported_not_a_501(self):
        # Found via a live process smoke test, not a unit test: the default
        # BaseHTTPRequestHandler returns 501 for HEAD unless do_HEAD is
        # defined, and HEAD-before-GET is common client behaviour that a
        # GET-only test would never catch.
        with open(os.path.join(self.output_dir, "riparide-page-feed-core.csv"), "w") as f:
            f.write("Page URL,Custom label\nhttps://x,PAGE_LISTING\n")
        req = urllib.request.Request(
            "http://127.0.0.1:%d/riparide-page-feed-core.csv" % self.port, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers["Content-Type"], "text/csv; charset=utf-8")
            self.assertEqual(r.read(), b"")

    def test_run_endpoint_rejects_a_missing_token(self):
        req = urllib.request.Request(
            "http://127.0.0.1:%d/run" % self.port, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 403)

    def test_run_endpoint_rejects_a_wrong_token(self):
        req = urllib.request.Request(
            "http://127.0.0.1:%d/run?token=wrong" % self.port, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 403)

    def test_run_endpoint_with_a_body_does_not_hang_or_crash(self):
        # BaseHTTPRequestHandler doesn't read a POST body on its own; an
        # unread body left on a would-be-reused connection corrupts the
        # next request on it. This isn't easy to observe through urlopen
        # (which doesn't reuse connections by default), so this test only
        # confirms the drain code path itself doesn't hang or error.
        body = b'{"unused": "payload"}'
        req = urllib.request.Request(
            "http://127.0.0.1:%d/run?token=wrong" % self.port, data=body, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 403)

    def test_run_endpoint_with_a_malformed_content_length_does_not_crash(self):
        req = urllib.request.Request(
            "http://127.0.0.1:%d/run?token=wrong" % self.port, method="POST")
        req.add_header("Content-Length", "not-a-number")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 403)

    def test_run_endpoint_accepts_the_right_token_and_returns_immediately(self):
        with mock.patch.object(svc, "run_pipeline") as m:
            req = urllib.request.Request(
                "http://127.0.0.1:%d/run?token=test-secret" % self.port, method="POST")
            with urllib.request.urlopen(req, timeout=5) as r:
                self.assertEqual(r.status, 202)
        # runs in a background thread; give it a moment to have been invoked
        import time
        for _ in range(20):
            if m.called:
                break
            time.sleep(0.05)
        self.assertTrue(m.called)


class EphemeralStateWarningTests(unittest.TestCase):
    """Reproduces, as a regression test, the exact mistake made once
    already during this migration's own build: running without
    FEED_DATA_DIR/FEED_REPORT_DIR set silently falls back to config.py's
    ephemeral relative-path defaults instead of the mounted volume. The
    service starts up looking completely healthy either way - only a log
    line distinguishes "persisting correctly" from "about to lose
    everything on the next restart."
    """

    def setUp(self):
        self._env = dict(os.environ)
        for var in ("FEED_DATA_DIR", "FEED_REPORT_DIR", "RUN_TRIGGER_TOKEN"):
            os.environ.pop(var, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_warns_when_none_of_the_variables_are_set(self):
        messages = []
        with mock.patch.object(svc, "log", messages.append):
            svc._warn_if_state_looks_ephemeral()
        joined = "\n".join(messages)
        self.assertIn("FEED_DATA_DIR", joined)
        self.assertIn("FEED_REPORT_DIR", joined)
        self.assertIn("RUN_TRIGGER_TOKEN", joined)

    def test_no_warning_once_everything_is_configured(self):
        os.environ["FEED_DATA_DIR"] = "/data"
        os.environ["FEED_REPORT_DIR"] = "/data/reports"
        os.environ["RUN_TRIGGER_TOKEN"] = "secret"
        messages = []
        with mock.patch.object(svc, "log", messages.append):
            svc._warn_if_state_looks_ephemeral()
        self.assertEqual(messages, [])


if __name__ == "__main__":
    unittest.main()

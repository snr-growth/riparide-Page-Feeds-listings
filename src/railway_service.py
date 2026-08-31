# -*- coding: utf-8 -*-
"""Always-on Railway service: serves the feed files at stable URLs and
triggers the monthly refresh internally, on the same one-service-one-volume
process Railway requires.

Railway does not support sharing a volume between two services (confirmed
against Railway's own community docs, August 2026), so the "one service
writes, another serves" split GitHub Actions + a separate host gave us for
free has to become one process here: a single service, a single volume,
an HTTP server for the current files, and an internal scheduler that
invokes the exact same `src/run.py` the GitHub Actions workflow already
runs - unchanged, not reimplemented, so every processing step (fetch,
label, enrich, validate, write, report, sheets, email) behaves identically
on either platform.

Environment variables (see railway.json / README for the full list):
  FEED_DATA_DIR         volume mount path, e.g. /data (config.py already
                        reads this; everything else nests under it)
  FEED_REPORT_DIR       report path, e.g. /data/reports (config.py's
                        default of "reports" is NOT under FEED_DATA_DIR,
                        so this needs setting explicitly on Railway)
  PORT                  injected by Railway; falls back to 8080 locally
  RUN_TRIGGER_TOKEN     required to authorize POST /run
  RAILWAY_RUN_DAY       day-of-month to auto-run (default 1, matches the
                        GitHub Actions "0 3 1 * *" schedule)
  RAILWAY_RUN_HOUR      UTC hour to auto-run (default 3)

A failed run is never able to remove or overwrite a previously-good file:
that guarantee already lives in run.py itself (the CSVs/xlsx are only
written after validate() passes), so this service adds no extra logic for
it - it just never deletes anything on disk itself.
"""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402

RUN_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.py")
STATE_FILE = os.path.join(cfg.DATA_DIR, "railway-service-state.json")

SERVED_FILES = {
    "/riparide-page-feed-core.csv": lambda: os.path.join(cfg.OUTPUT_DIR, cfg.CORE_CSV),
    "/riparide-page-feed-adventures.csv": lambda: os.path.join(cfg.OUTPUT_DIR, cfg.ADVENTURES_CSV),
    "/riparide-page-feed-report.xlsx": lambda: os.path.join(cfg.REPORT_DIR, cfg.REPORT_XLSX),
}

CONTENT_TYPES = {".csv": "text/csv; charset=utf-8",
                  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

_lock = threading.Lock()
_run_in_progress = False


def log(msg):
    print("[railway_service] %s" % msg, flush=True)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def run_pipeline(extra_args=None, reason="scheduled"):
    """Run src/run.py as a fresh subprocess - the same command GitHub
    Actions invokes, so every processing step behaves identically. Runs
    with the current interpreter so Railway's own Python/deps are used.
    Never raises: a failure is recorded in state, not thrown, so it can
    never take the HTTP server down with it.
    """
    global _run_in_progress
    with _lock:
        if _run_in_progress:
            log("run already in progress, ignoring trigger (%s)" % reason)
            return False
        _run_in_progress = True

    state = load_state()
    started = datetime.now(timezone.utc)
    log("starting pipeline run (%s)" % reason)
    try:
        args = [sys.executable, RUN_SCRIPT] + (extra_args or [])
        result = subprocess.run(args, cwd=os.path.dirname(RUN_SCRIPT), timeout=60 * 80)
        ok = result.returncode == 0
        log("pipeline run finished, exit code %d" % result.returncode)
    except Exception as e:
        ok = False
        log("pipeline run crashed before completing: %s: %s" % (type(e).__name__, e))
    finally:
        with _lock:
            _run_in_progress = False

    state["last_run_at"] = started.strftime("%Y-%m-%dT%H:%M:%SZ")
    state["last_run_month"] = started.strftime("%Y-%m")
    state["last_run_ok"] = ok
    state["last_run_reason"] = reason
    save_state(state)
    return ok


def should_auto_run(now, state):
    """True once per calendar month, on or after the configured day/hour -
    mirrors the "0 3 1 * *" GitHub Actions schedule, but checked from an
    always-on loop rather than a platform-native cron trigger (Railway's
    own cron-schedule services are one-shot and cannot also serve HTTP
    traffic between runs, see the module docstring)."""
    run_day = int(os.environ.get("RAILWAY_RUN_DAY", "1"))
    run_hour = int(os.environ.get("RAILWAY_RUN_HOUR", "3"))
    if now.day < run_day or (now.day == run_day and now.hour < run_hour):
        return False
    this_month = now.strftime("%Y-%m")
    return state.get("last_run_month") != this_month


def scheduler_loop(poll_seconds=1800, stop_event=None):
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        try:
            state = load_state()
            now = datetime.now(timezone.utc)
            if should_auto_run(now, state):
                run_pipeline(reason="scheduled")
        except Exception as e:
            log("scheduler tick failed (will retry next tick): %s: %s" % (type(e).__name__, e))
        stop_event.wait(poll_seconds)


class Handler(BaseHTTPRequestHandler):
    server_version = "riparide-page-feed/1.0"

    def log_message(self, fmt, *args):
        log("%s - %s" % (self.address_string(), fmt % args))

    def _send_json(self, status, payload, write_body=True):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _handle_get_or_head(self, write_body):
        path = urlparse(self.path).path
        if path == "/healthz":
            self._send_json(200, {"status": "ok"}, write_body)
            return
        if path == "/":
            state = load_state()
            self._send_json(200, {
                "service": "riparide-page-feed",
                "last_run": state,
                "files": list(SERVED_FILES.keys()),
            }, write_body)
            return
        if path in SERVED_FILES:
            file_path = SERVED_FILES[path]()
            if not os.path.exists(file_path):
                self._send_json(404, {"error": "not generated yet"}, write_body)
                return
            ext = os.path.splitext(file_path)[1]
            size = os.path.getsize(file_path)
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if write_body:
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
            return
        self._send_json(404, {"error": "not found"}, write_body)

    def do_GET(self):
        self._handle_get_or_head(write_body=True)

    def do_HEAD(self):
        # A HEAD probe before the real GET is common HTTP client behaviour
        # (and plausible from Google Ads' own feed fetcher) - returning the
        # default 501 for it is exactly the kind of thing that only shows up
        # once something real hits the URL, not in a GET-only test.
        self._handle_get_or_head(write_body=False)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/run":
            self._send_json(404, {"error": "not found"})
            return
        qs = parse_qs(urlparse(self.path).query)
        token = (qs.get("token") or [""])[0]
        expected = os.environ.get("RUN_TRIGGER_TOKEN", "")
        if not expected or token != expected:
            self._send_json(403, {"error": "invalid or missing token"})
            return
        full_status = (qs.get("full_status") or ["false"])[0] == "true"
        extra = ["--full-status"] if full_status else []
        t = threading.Thread(target=run_pipeline, args=(extra, "manual"), daemon=True)
        t.start()
        self._send_json(202, {"status": "run started"})


def main():
    port = int(os.environ.get("PORT", "8080"))
    stop_event = threading.Event()
    t = threading.Thread(target=scheduler_loop, args=(1800, stop_event), daemon=True)
    t.start()
    log("scheduler thread started (checks every 30 minutes)")

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log("serving on port %d" % port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.shutdown()


if __name__ == "__main__":
    main()

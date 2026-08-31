# -*- coding: utf-8 -*-
"""Write the two upload-ready CSV files.

Google requires exactly two columns, Page URL and Custom label, with multiple
labels on one row separated by semicolons. A URL must never appear twice.
"""
import csv
import os

import config as cfg


def write_feed(rows, feed_name, filename, out_dir=None):
    """Write one feed to CSV. Returns (path, row_count).

    Written to a temp file and atomically renamed into place, not written
    directly to `path` - the railway_service.py file server can be serving
    this exact path over HTTP concurrently with a run writing it, and a
    direct write would let a request land mid-write and serve a truncated
    CSV. This never mattered under GitHub Actions, where nothing read the
    file until the whole process had already exited.
    """
    out_dir = out_dir or cfg.OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    tmp = path + ".tmp"

    selected = [r for r in rows if r["feed"] == feed_name]

    seen = set()
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cfg.CSV_HEADER)
        written = 0
        for r in selected:
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            w.writerow([r["url"], r["label"]])
            written += 1
    os.replace(tmp, path)
    return path, written


def write_all(rows, out_dir=None):
    """Write both feeds. Returns {feed: (path, count)}."""
    return {
        cfg.FEED_CORE: write_feed(rows, cfg.FEED_CORE, cfg.CORE_CSV, out_dir),
        cfg.FEED_ADVENTURES: write_feed(rows, cfg.FEED_ADVENTURES, cfg.ADVENTURES_CSV, out_dir),
    }

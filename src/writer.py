# -*- coding: utf-8 -*-
"""Write the two upload-ready CSV files.

Google requires exactly two columns, Page URL and Custom label, with multiple
labels on one row separated by semicolons. A URL must never appear twice.
"""
import csv
import os

import config as cfg


def write_feed(rows, feed_name, filename, out_dir=None):
    """Write one feed to CSV. Returns (path, row_count)."""
    out_dir = out_dir or cfg.OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)

    selected = [r for r in rows if r["feed"] == feed_name]

    seen = set()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cfg.CSV_HEADER)
        written = 0
        for r in selected:
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            w.writerow([r["url"], r["label"]])
            written += 1
    return path, written


def write_all(rows, out_dir=None):
    """Write both feeds. Returns {feed: (path, count)}."""
    return {
        cfg.FEED_CORE: write_feed(rows, cfg.FEED_CORE, cfg.CORE_CSV, out_dir),
        cfg.FEED_ADVENTURES: write_feed(rows, cfg.FEED_ADVENTURES, cfg.ADVENTURES_CSV, out_dir),
    }

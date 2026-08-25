# -*- coding: utf-8 -*-
"""Snapshot storage and the month-to-month comparison.

The snapshot is the whole point of the system: without last month's URL list
there is nothing to compare against, so the diff cannot be produced. It is
written only after a run has succeeded.
"""
import json
import os
import shutil
from datetime import datetime, timezone

import config as cfg


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_snapshot(path=None):
    """Return the stored snapshot, or None on the very first run."""
    path = path or cfg.SNAPSHOT_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
    except Exception as e:
        raise ValueError("snapshot at %s is unreadable: %s" % (path, e))
    if "urls_by_group" not in snap:
        raise ValueError("snapshot at %s is missing urls_by_group" % path)
    return snap


def save_snapshot(urls_by_group, path=None, keep_backup=True):
    """Write the snapshot atomically, keeping one previous copy."""
    path = path or cfg.SNAPSHOT_FILE
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if keep_backup and os.path.exists(path):
        shutil.copy2(path, path + ".previous")
    payload = {
        "taken_at": _now(),
        "total": sum(len(v) for v in urls_by_group.values()),
        "urls_by_group": {k: sorted(v) for k, v in urls_by_group.items()},
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=0)
    os.replace(tmp, path)
    return payload


def flatten(urls_by_group):
    """{group: [url]} -> {url: group}. First group seen wins on a repeat."""
    out = {}
    for group, urls in urls_by_group.items():
        for u in urls:
            out.setdefault(u, group)
    return out


def diff(previous, current):
    """Compare two {group: [url]} maps.

    Returns a dict with added, removed and unchanged URL lists, plus the group
    each added URL belongs to. On the first run (previous is None) every URL
    counts as added, which is correct: nothing has been checked before.
    """
    cur = flatten(current)
    prev = flatten(previous) if previous else {}

    added = [u for u in cur if u not in prev]
    removed = [u for u in prev if u not in cur]
    unchanged = [u for u in cur if u in prev]

    return {
        "first_run": previous is None,
        "added": sorted(added),
        "removed": sorted(removed),
        "unchanged_count": len(unchanged),
        "group_of": cur,
        "previous_total": len(prev),
        "current_total": len(cur),
    }

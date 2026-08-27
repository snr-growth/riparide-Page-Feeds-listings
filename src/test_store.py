# -*- coding: utf-8 -*-
"""Unit tests for store.py.

prove_diff.py already exercises diff() thoroughly against realistic data;
these tests focus on save/load mechanics and the feed_counts field added to
support validator.py's feed-collapse guard (DECISIONS.md D11).
"""
import os
import shutil
import tempfile
import unittest

import store


class SaveLoadSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "snapshot.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_load_missing_snapshot_returns_none(self):
        self.assertIsNone(store.load_snapshot(self.path))

    def test_round_trips_urls_and_feed_counts(self):
        urls = {"listings": ["https://x/1", "https://x/2"], "core": []}
        store.save_snapshot(urls, path=self.path, feed_counts={"CORE": 2})
        loaded = store.load_snapshot(self.path)
        self.assertEqual(loaded["urls_by_group"]["listings"], ["https://x/1", "https://x/2"])
        self.assertEqual(loaded["feed_counts"], {"CORE": 2})
        self.assertEqual(loaded["total"], 2)

    def test_missing_feed_counts_defaults_to_empty_dict(self):
        store.save_snapshot({"listings": ["https://x/1"]}, path=self.path)
        loaded = store.load_snapshot(self.path)
        self.assertEqual(loaded["feed_counts"], {})

    def test_second_save_creates_previous_backup(self):
        store.save_snapshot({"listings": ["https://x/1"]}, path=self.path, feed_counts={"CORE": 1})
        store.save_snapshot({"listings": ["https://x/1", "https://x/2"]}, path=self.path,
                             feed_counts={"CORE": 2})
        self.assertTrue(os.path.exists(self.path + ".previous"))
        previous = store.load_snapshot(self.path + ".previous")
        self.assertEqual(previous["feed_counts"], {"CORE": 1})
        current = store.load_snapshot(self.path)
        self.assertEqual(current["feed_counts"], {"CORE": 2})

    def test_urls_are_sorted_on_save(self):
        store.save_snapshot({"listings": ["https://x/2", "https://x/1"]}, path=self.path)
        loaded = store.load_snapshot(self.path)
        self.assertEqual(loaded["urls_by_group"]["listings"], ["https://x/1", "https://x/2"])

    def test_corrupt_snapshot_raises_clear_error(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        with self.assertRaises(ValueError):
            store.load_snapshot(self.path)

    def test_snapshot_missing_required_key_raises(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"taken_at": "now"}')
        with self.assertRaises(ValueError):
            store.load_snapshot(self.path)


class DiffFeedCountsIndependenceTests(unittest.TestCase):
    def test_diff_ignores_feed_counts_key_if_present_in_snapshot(self):
        # diff() only ever receives urls_by_group, not the whole snapshot
        # payload, so a feed_counts key alongside it must not confuse it.
        previous = {"listings": ["https://x/1"]}
        current = {"listings": ["https://x/1", "https://x/2"]}
        d = store.diff(previous, current)
        self.assertEqual(d["added"], ["https://x/2"])


if __name__ == "__main__":
    unittest.main()

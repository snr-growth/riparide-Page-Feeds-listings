# -*- coding: utf-8 -*-
"""Full pipeline integration test for run.py.

Every other test file exercises one module in isolation. This is the one
place that proves run.main() actually completes end to end in exactly the
state this project is in right now: no GOOGLE_SERVICE_ACCOUNT_JSON/
GOOGLE_SHEETS_SPREADSHEET_ID and no email secrets configured yet (both are
still pending client-side setup, see DECISIONS.md D14). It answers directly
whether a run still succeeds and still produces the client-shared format
(the two CSVs and the .xlsx report - the same file the workflow commits
back into the repo every month) when the Google-Ads-facing Sheet can't be
reached at all.

No network call happens anywhere in this test, including the robots.txt/
AdsBot check in step 6b, which runs unconditionally and is not gated by
--skip-status: fetcher.get is monkeypatched exactly like test_fetcher.py
already does, so this is deterministic and safe to run in CI with no live
dependency on riparide.com or Google.
"""
import json
import os
import shutil
import tempfile
import unittest

import config as cfg
import fetcher
import run

SAMPLE_SNAPSHOT = {
    "urls_by_group": {
        "listings": [
            "https://www.riparide.com/listings/1-pebble-point",
            "https://www.riparide.com/listings/2-river-cottage",
        ],
        "stories": [],
        "adventures": [
            "https://www.riparide.com/adventures/1-vic-high-country",
        ],
        "destinations": [],
        "collections": [],
        "core": [],
    }
}

ROBOTS_TXT = "User-agent: *\nDisallow: /admin\n"


def _row(url, page_type):
    return {"url": url, "page_type": page_type}


class SelectStatusCheckTargetsTests(unittest.TestCase):
    """Regression coverage for the gap found on the first live production
    run: with full_status=True on a site bigger than cfg.MAX_STATUS_CHECKS,
    facet URLs (appended last by build_rows()) were silently truncated away
    by the per-run cap before it ever reached them, because the full_status
    branch checked "every row, in row order" instead of prioritising facet
    URLs the way the non-full_status branch already did (DECISIONS.md D9).
    """

    def setUp(self):
        self.facets = [_row("https://x/listings?country=AU", "PAGE_FACET_TYPE"),
                       _row("https://x/listings?country=NZ", "PAGE_FACET_TYPE")]
        self.listings = [_row("https://x/listings/%d" % i, "PAGE_LISTING")
                          for i in range(5)]
        self.rows = self.listings + self.facets  # facets appended last, like build_rows() does

    def test_full_status_puts_facet_urls_first_regardless_of_row_order(self):
        targets = run.select_status_check_targets(self.rows, added_urls=[], full_status=True)
        self.assertEqual(targets[:2], [r["url"] for r in self.facets])
        self.assertEqual(len(targets), 7)

    def test_full_status_with_a_tight_cap_still_keeps_every_facet_url(self):
        targets = run.select_status_check_targets(self.rows, added_urls=[], full_status=True)
        capped = targets[:2]  # simulates cfg.MAX_STATUS_CHECKS smaller than the row count
        self.assertEqual(set(capped), {r["url"] for r in self.facets})

    def test_incremental_mode_still_includes_facet_urls_even_when_not_added(self):
        added = [self.listings[0]["url"]]  # only one listing is "new" this run
        targets = run.select_status_check_targets(self.rows, added_urls=added, full_status=False)
        for facet in self.facets:
            self.assertIn(facet["url"], targets)
        self.assertIn(added[0], targets)
        self.assertNotIn(self.listings[1]["url"], targets)

    def test_no_duplicates_when_a_facet_url_is_also_in_added(self):
        added = [self.facets[0]["url"]]
        targets = run.select_status_check_targets(self.rows, added_urls=added, full_status=False)
        self.assertEqual(targets.count(self.facets[0]["url"]), 1)

    def test_search_rows_are_prioritised_like_facets(self):
        search = _row("https://x/listings?country=AU&state=VIC&type=accommodation", "PAGE_SEARCH")
        targets = run.select_status_check_targets(self.rows + [search], added_urls=[],
                                                  full_status=False)
        self.assertEqual(targets[:3], [r["url"] for r in self.facets] + [search["url"]])


class BuildRowsSearchTests(unittest.TestCase):
    def test_region_hub_in_sitemap_produces_its_region_search_row(self):
        rows = run.build_rows({"destinations": ["https://www.riparide.com/au/nsw/blue-mountains"]})
        urls = {r["url"] for r in rows if r["page_type"] == "PAGE_SEARCH"}
        self.assertIn("https://www.riparide.com/listings?country=AU&regions%5B%5D=blue-mountains"
                      "&state=NSW&type=accommodation", urls)
        self.assertEqual(len(urls), len([r for r in rows if r["page_type"] == "PAGE_SEARCH"]))


class ApplySearchMinimumTests(unittest.TestCase):
    """D20: a search/facet page can return 200 yet show 0 stays."""

    def setUp(self):
        self.rows = [_row("https://x/listings?a", "PAGE_SEARCH"),
                     _row("https://x/listings?b", "PAGE_FACET_TYPE"),
                     _row("https://x/listings?c", "PAGE_SEARCH"),
                     _row("https://x/listings?d", "PAGE_SEARCH"),
                     _row("https://x/au/vic/grampians", "PAGE_REGION")]

    def test_below_minimum_dropped_at_minimum_kept_none_kept(self):
        totals = {"https://x/listings?a": 0, "https://x/listings?b": 5,
                  "https://x/listings?c": 6, "https://x/listings?d": None}
        kept, rep = run.apply_search_minimum(self.rows, totals, 6)
        self.assertEqual([r["url"] for r in kept],
                         ["https://x/listings?c", "https://x/listings?d",
                          "https://x/au/vic/grampians"])
        self.assertEqual((rep["counted"], rep["dropped"], rep["dropped_zero"]), (3, 2, 1))
        self.assertEqual(rep["unknown"], ["https://x/listings?d"])

    def test_other_page_types_never_dropped_even_if_counted(self):
        kept, rep = run.apply_search_minimum(self.rows, {"https://x/au/vic/grampians": 0}, 6)
        self.assertEqual(len(kept), len(self.rows))
        self.assertEqual(rep["dropped"], 0)


class SearchCountRunTests(unittest.TestCase):
    """run.main() wiring of the search-count step, all network mocked."""

    SEARCH_ALL_VIC = "https://www.riparide.com/listings?country=AU&state=VIC&type=accommodation"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.snapshot_in = os.path.join(self.tmp, "offline-snapshot.json")
        with open(self.snapshot_in, "w", encoding="utf-8") as f:
            json.dump(SAMPLE_SNAPSHOT, f)
        self._orig_cfg = {k: getattr(cfg, k) for k in
                          ("DATA_DIR", "SNAPSHOT_FILE", "OUTPUT_DIR", "REPORT_DIR")}
        cfg.DATA_DIR = self.tmp
        cfg.SNAPSHOT_FILE = os.path.join(self.tmp, "snapshot.json")
        cfg.OUTPUT_DIR = os.path.join(self.tmp, "output")
        cfg.REPORT_DIR = os.path.join(self.tmp, "reports")
        self._orig = (fetcher.get, fetcher.status_check, fetcher.search_totals)
        fetcher.get = lambda url, retries=None: ROBOTS_TXT
        fetcher.status_check = lambda urls, log=print: {u: 200 for u in urls}
        self.counted = []

        def fake_totals(urls, log=print):
            urls = list(urls)
            self.counted.extend(urls)
            out = {u: 50 for u in urls}
            out[self.SEARCH_ALL_VIC] = 0
            out[urls[0] if urls[0] != self.SEARCH_ALL_VIC else urls[1]] = None
            return out
        fetcher.search_totals = fake_totals

    def tearDown(self):
        for key, value in self._orig_cfg.items():
            setattr(cfg, key, value)
        fetcher.get, fetcher.status_check, fetcher.search_totals = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _core_urls(self):
        import csv
        with open(os.path.join(cfg.OUTPUT_DIR, cfg.CORE_CSV), encoding="utf-8") as f:
            return {row[0] for row in csv.reader(f)}

    def test_zero_result_search_dropped_and_unknown_kept(self):
        rc = run.main(["--offline-snapshot", self.snapshot_in, "--skip-location",
                       "--skip-catalog", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertTrue(self.counted)
        self.assertTrue(all("/listings?" in u for u in self.counted))
        urls = self._core_urls()
        self.assertNotIn(self.SEARCH_ALL_VIC, urls)
        unknown = self.counted[0] if self.counted[0] != self.SEARCH_ALL_VIC else self.counted[1]
        self.assertIn(unknown, urls)

    def test_skip_status_skips_counting(self):
        rc = run.main(["--offline-snapshot", self.snapshot_in, "--skip-location",
                       "--skip-catalog", "--skip-status", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.counted, [])
        self.assertIn(self.SEARCH_ALL_VIC, self._core_urls())


class FullRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.snapshot_in = os.path.join(self.tmp, "offline-snapshot.json")
        with open(self.snapshot_in, "w", encoding="utf-8") as f:
            json.dump(SAMPLE_SNAPSHOT, f)

        self._orig_cfg = {
            "DATA_DIR": cfg.DATA_DIR,
            "SNAPSHOT_FILE": cfg.SNAPSHOT_FILE,
            "OUTPUT_DIR": cfg.OUTPUT_DIR,
            "REPORT_DIR": cfg.REPORT_DIR,
        }
        cfg.DATA_DIR = self.tmp
        cfg.SNAPSHOT_FILE = os.path.join(self.tmp, "snapshot.json")
        cfg.OUTPUT_DIR = os.path.join(self.tmp, "output")
        cfg.REPORT_DIR = os.path.join(self.tmp, "reports")

        # The one network call not covered by --skip-status/--skip-location:
        # the robots.txt/AdsBot check (step 6b) runs every time, no flag skips it.
        self._orig_get = fetcher.get
        fetcher.get = lambda url, retries=None: ROBOTS_TXT

        # Confirms this test is exercising the actual "not configured" path,
        # not silently passing because a real secret leaked in from the shell.
        self.assertFalse(cfg.google_sheets_configured())
        self.assertFalse(cfg.email_configured())

    def tearDown(self):
        for key, value in self._orig_cfg.items():
            setattr(cfg, key, value)
        fetcher.get = self._orig_get
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_run_writes_client_shared_format_with_no_sheets_or_email_configured(self):
        rc = run.main(["--offline-snapshot", self.snapshot_in,
                       "--skip-location", "--skip-status"])
        self.assertEqual(rc, 0,
            "a run must still succeed when Sheets/email are simply unconfigured, "
            "not treated as a failure (see run.py's sheets_failed logic)")

        core_path = os.path.join(cfg.OUTPUT_DIR, cfg.CORE_CSV)
        adv_path = os.path.join(cfg.OUTPUT_DIR, cfg.ADVENTURES_CSV)
        xlsx_path = os.path.join(cfg.REPORT_DIR, cfg.REPORT_XLSX)

        self.assertTrue(os.path.exists(core_path))
        self.assertTrue(os.path.exists(adv_path))
        self.assertTrue(os.path.exists(xlsx_path),
            "the .xlsx (the 'sheet' this repo actually commits and updates "
            "every run, independent of the live Google Sheet) must still be written")
        self.assertGreater(os.path.getsize(xlsx_path), 0)

        self.assertTrue(os.path.exists(cfg.SNAPSHOT_FILE))
        with open(cfg.SNAPSHOT_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertIn("feed_counts", saved)
        self.assertGreater(sum(saved["feed_counts"].values()), 0)

    def test_dry_run_completes_without_persisting_anything(self):
        rc = run.main(["--offline-snapshot", self.snapshot_in,
                       "--skip-location", "--skip-status", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(cfg.SNAPSHOT_FILE))


if __name__ == "__main__":
    unittest.main()

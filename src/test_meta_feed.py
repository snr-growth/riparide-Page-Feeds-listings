# -*- coding: utf-8 -*-
"""Tests for meta_feed.py. No network: fetch and totals are stubbed."""
import csv
import io
import json
import os
import shutil
import tempfile
import unittest

import meta_feed as mf

B = "https://www.riparide.com"
HEADER = ["id", "title", "link", "location", "custom_label_4", "applink.ios_url"]

CORE = [
    ("Page URL", "Custom label"),
    (B + "/au/vic/grampians", "PAGE_REGION;GEO_AU;GEO_VIC;REG_GRAMPIANS"),
    (B + "/au/vic/grampians/venus-baths", "PAGE_REGION;GEO_AU;GEO_VIC;REG_GRAMPIANS;LANDMARK_X"),
    (B + "/au/nsw/north-coast", "PAGE_REGION;GEO_AU;GEO_NSW;REG_NORTH_COAST_NSW"),
    (B + "/listings/1-a", "PAGE_LISTING;GEO_AU;GEO_VIC;REG_GRAMPIANS;TYPE_CABIN"),
    (B + "/listings/2-b", "PAGE_LISTING;GEO_AU;GEO_VIC;REG_GRAMPIANS;TYPE_BEACH_HOUSE"),
    (B + "/listings/3-c", "PAGE_LISTING;GEO_AU;GEO_VIC;REG_GRAMPIANS;TYPE_CABIN;INT_PET_FRIENDLY"),
    (B + "/stories/7-s", "PAGE_STORY;GEO_AU;GEO_VIC;REG_GRAMPIANS;TYPE_CABIN"),
    (B + "/listings/9-n", "PAGE_LISTING;GEO_AU;GEO_NSW;REG_NORTH_COAST_NSW;TYPE_HOUSE"),
]


def url(state, region=None, sub=None, pet=False):
    return mf.search_url(state, region, sub, pet)


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)


def feed_text(rows, bom=True):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADER)
    for r in rows:
        w.writerow(r)
    return ("﻿" if bom else "") + buf.getvalue()


def item(id_, link, cl4=""):
    return [id_, "Title, with comma", link, "Rye, VIC", cl4, link]


class JoinAndMappingTests(unittest.TestCase):
    def test_feed_key(self):
        self.assertEqual(mf.feed_key("listing_106"), ("listings", "106"))
        self.assertEqual(mf.feed_key("story_47"), ("stories", "47"))
        self.assertIsNone(mf.feed_key("adventure_3"))
        self.assertIsNone(mf.feed_key("listing_x"))

    def test_page_key(self):
        self.assertEqual(mf.page_key(B + "/listings/106-slug"), ("listings", "106"))
        self.assertEqual(mf.page_key(B + "/stories/47-slug"), ("stories", "47"))
        self.assertIsNone(mf.page_key(B + "/listings/1060x"))
        self.assertIsNone(mf.page_key(B + "/au/vic/grampians"))

    def test_hub_vs_landmark(self):
        self.assertEqual(mf.hub_slug(B + "/au/vic/grampians"), ("VIC", "grampians"))
        self.assertIsNone(mf.hub_slug(B + "/au/vic/grampians/venus-baths"))
        self.assertIsNone(mf.hub_slug(B + "/us/ca/north-coast"))

    def test_load_labels_maps_hubs_not_landmarks(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "core.csv")
            write_csv(p, CORE)
            labels, hubs = mf.load_labels(p)
        finally:
            shutil.rmtree(d)
        self.assertEqual(hubs, {("VIC", "REG_GRAMPIANS"): "grampians",
                                ("NSW", "REG_NORTH_COAST_NSW"): "north-coast"})
        self.assertIn("TYPE_CABIN", labels[("listings", "1")])
        self.assertIn(("stories", "7"), labels)

    def test_pet_collection_match(self):
        self.assertTrue(mf._PET_COLLECTION.search("Latest Stories|Pet Friendly Escapes"))
        self.assertFalse(mf._PET_COLLECTION.search("Carpeted Cabins|petite"))

    def test_stay_type_only_site_filters(self):
        self.assertEqual(mf.stay_type({"TYPE_CABIN"}), "cabin")
        self.assertEqual(mf.stay_type({"TYPE_TINY_HOUSE"}), "tiny-house")
        self.assertIsNone(mf.stay_type({"TYPE_BEACH_HOUSE"}))
        self.assertIsNone(mf.stay_type({"TYPE_HOTEL"}))


class LadderTests(unittest.TestCase):
    def pick(self, counts, state="VIC", region="grampians", sub="cabin", pet=False, joined=True, m=6):
        return mf.choose(mf.candidates(state, region, sub, pet, joined), counts, m)

    def test_search_url_shape(self):
        self.assertEqual(
            url("VIC", "grampians", "cabin"),
            B + "/listings?country=AU&regions%5B%5D=grampians&state=VIC"
                "&subcategories%5B%5D=cabin&type=accommodation")
        self.assertIn("petFriendly=true", url("VIC", pet=True))

    def test_non_pet_rungs_in_order(self):
        all_ok = {u: 100 for _, u in mf.candidates("VIC", "grampians", "cabin", False)}
        self.assertEqual([r for r, _ in mf.candidates("VIC", "grampians", "cabin", False)],
                         ["region+type", "region", "state+type", "state"])
        self.assertEqual(self.pick(all_ok)[0], "region+type")
        c = dict(all_ok, **{url("VIC", "grampians", "cabin"): 4})
        self.assertEqual(self.pick(c)[0], "region")
        c[url("VIC", "grampians")] = 5
        self.assertEqual(self.pick(c)[0], "state+type")
        c[url("VIC", sub="cabin")] = None
        self.assertEqual(self.pick(c), ("state", url("VIC")))

    def test_pet_rungs_in_order(self):
        cands = mf.candidates("VIC", "grampians", "cabin", True)
        self.assertEqual([r for r, _ in cands], mf.PET_RUNGS)
        counts = {u: 100 for _, u in cands}
        for rung in mf.PET_RUNGS:
            self.assertEqual(self.pick(counts, pet=True)[0], rung)
            counts[dict(cands)[rung]] = 0

    def test_non_filter_type_skips_type_rungs(self):
        cands = mf.candidates("VIC", "grampians", None, True)
        self.assertEqual([r for r, _ in cands], ["region+pet", "region", "state+pet", "state"])
        self.assertEqual([r for r, _ in mf.candidates("VIC", "grampians", None, False)],
                         ["region", "state"])

    def test_unknown_region_skips_region_rungs(self):
        self.assertEqual([r for r, _ in mf.candidates("VIC", None, "cabin", False)],
                         ["state+type", "state"])

    def test_unjoined_goes_to_state(self):
        self.assertEqual(mf.candidates("NSW", "x", "cabin", True, joined=False),
                         [("state", url("NSW"))])

    def test_unknown_counts_never_win(self):
        cands = mf.candidates("VIC", "grampians", "cabin", False)
        counts = {u: None for _, u in cands}
        self.assertEqual(self.pick(counts), (None, None))
        counts[url("VIC")] = 3   # known but below min: last resort
        self.assertEqual(self.pick(counts), ("state (below min)", url("VIC")))

    def test_min_results_boundary(self):
        c = {url("VIC", "grampians", "cabin"): 6}
        self.assertEqual(self.pick(c)[0], "region+type")
        self.assertEqual(self.pick(c, m=7), (None, None))


class PetParserTests(unittest.TestCase):
    # Shape taken from a live page, 18 Nov 2026 (trimmed).
    HTML = ('x{"result":{"__typename":"Listing","id":"5396","title":"A"}},'
            '{"result":{"__typename":"Story","id":"1817","title":"G","url":"/stories/1817-g",'
            '"featuredListingImage":{"__typename":"PromoImage"},'
            '"featuredListing":{"__typename":"Listing","id":"4262","title":"G"}}},'
            '{"result":{"__typename":"Story","id":"645","url":"/stories/645-y"}}'
            '"pageInfo":{"__typename":"PageInfo","endCursor":"MjQ","hasNextPage":true},"totalCount":30')

    def test_parse_results(self):
        self.assertEqual(mf.parse_results(self.HTML), [
            {"type": "Listing", "id": "5396", "listing_id": "5396"},
            {"type": "Story", "id": "1817", "listing_id": "4262"},
            {"type": "Story", "id": "645", "listing_id": None}])
        self.assertEqual(mf.parse_results(""), [])

    @staticmethod
    def page(ids, total):
        nodes = ",".join('{"result":{"__typename":"Listing","id":"%s"}}' % i for i in ids)
        return '%s "totalCount":%d' % (nodes, total)

    def harvest(self, pages, regions):
        seen = []

        def fetch(u):
            seen.append(u)
            return pages.get(u, self.page([], 0))
        out = mf.harvest_pet(regions, fetch=fetch, log=lambda *_: None, sleep=lambda *_: None)
        return out, seen

    def test_state_with_one_page_needs_no_split(self):
        pages = {url("VIC", pet=True): self.page(["1", "2"], 2)}
        out, seen = self.harvest(pages, {"VIC": ["grampians"]})
        self.assertEqual(seen, [url("VIC", pet=True)])
        self.assertEqual(out["VIC"]["listings"], {"1", "2"})
        self.assertEqual((out["VIC"]["stays"], out["VIC"]["total"]), (2, 2))

    def test_splits_by_region_then_subcategory(self):
        pages = {
            url("VIC", pet=True): self.page(["1"], 40),
            url("VIC", "grampians", pet=True): self.page(["2"], 1),        # complete
            url("VIC", "high-country", pet=True): self.page(["3"], 30),    # needs split
            url("VIC", "high-country", "cabin", True): self.page(["4", "5"], 2),
        }
        out, seen = self.harvest(pages, {"VIC": ["grampians", "high-country"]})
        self.assertEqual(out["VIC"]["listings"], {"1", "2", "3", "4", "5"})
        self.assertEqual(out["VIC"]["total"], 40)
        self.assertNotIn(url("VIC", "grampians", "cabin", True), seen)
        self.assertIn(url("VIC", "high-country", "tiny-house", True), seen)
        self.assertEqual(out["VIC"]["searches"], 3 + len(mf.cfg.SUBCATS))

    def test_story_cards_map_to_story_and_featured_listing(self):
        pages = {url("NSW", pet=True): self.HTML.replace('"totalCount":30', '"totalCount":3')}
        out, _ = self.harvest(pages, {"NSW": []})
        self.assertEqual(out["NSW"]["stories"], {"1817", "645"})
        self.assertEqual(out["NSW"]["listings"], {"5396", "4262"})
        self.assertEqual(out["NSW"]["stays"], 3)

    def test_harvest_failure_never_raises_and_keeps_what_was_found(self):
        def fetch(u):
            if "regions" in u:
                raise mf.fetcher.FetchError("down")
            return self.page(["1"], 50)
        out = mf.harvest_pet({"VIC": ["grampians"], "NSW": []}, fetch=fetch,
                             log=lambda *_: None, sleep=lambda *_: None)
        self.assertIn("down", out["VIC"]["error"])
        self.assertEqual(out["VIC"]["listings"], {"1"})
        self.assertIsNone(out["NSW"]["error"])


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.rows = [item("listing_1", B + "/listings/1-a")]

    def test_ok(self):
        new = [list(self.rows[0])]
        new[0][2] = new[0][5] = url("VIC")
        mf.validate(HEADER, self.rows, new)

    def test_original_link_is_allowed(self):
        mf.validate(HEADER, self.rows, [list(self.rows[0])])

    def test_rejects(self):
        def bad(i, v):
            new = [list(self.rows[0])]
            new[0][2] = new[0][5] = url("VIC")
            new[0][i] = v
            with self.assertRaises(ValueError):
                mf.validate(HEADER, self.rows, new)
        bad(0, "listing_2")                    # id changed
        bad(1, "other")                        # non-link column changed
        bad(5, B + "/listings/1-a")            # applink not swapped
        bad(2, B + "/listings?country=AU")     # no state= (but then applink differs too)
        with self.assertRaises(ValueError):
            mf.validate(HEADER, self.rows, [])


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.core = os.path.join(self.tmp, "core.csv")
        write_csv(self.core, CORE)
        self.out = os.path.join(self.tmp, "meta")
        self.feeds = {
            ("listings", "VIC"): feed_text([
                item("listing_1", B + "/listings/1-a"),     # cabin, grampians
                item("listing_2", B + "/listings/2-b"),     # beach house: no type filter
                item("listing_3", B + "/listings/3-c"),     # pet via INT_PET_FRIENDLY
                item("listing_8", B + "/listings/8-new"),   # not in PMax labels
                item("listing_4", B + "/listings/4-d"),     # pet via harvest (unjoined)
            ]),
            ("listings", "NSW"): feed_text([item("listing_9", B + "/listings/9-n")], bom=False),
            ("stories", "VIC"): feed_text([item("story_7", B + "/stories/7-s", "Coastal|Pet Friendly Escapes")]),
            ("stories", "NSW"): feed_text([item("story_99", B + "/stories/99-z")]),
        }
        self.counts = {
            url("VIC", "grampians", "cabin"): 10,
            url("VIC", "grampians"): 51,
            url("VIC", "grampians", "cabin", True): 2,
            url("VIC", "grampians", None, True): 10,
            url("VIC"): 1752, url("VIC", pet=True): 640,
            url("NSW", "north-coast", "house"): 30, url("NSW"): 1339,
        }
        self.pet_html = ('{"result":{"__typename":"Listing","id":"4"}}'
                         '"pageInfo":{"endCursor":"MjQ","hasNextPage":false},"totalCount":1')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fetch(self, u):
        if "public_api" in u:
            kind = "listings" if "/listings.csv" in u else "stories"
            return self.feeds[(kind, u.rsplit("=", 1)[1])]
        if "petFriendly=true" in u:
            return self.pet_html
        raise mf.fetcher.FetchError(u)

    def totals(self, urls, log=None):
        return {u: self.counts.get(u) for u in urls}

    def build(self, **kw):
        kw.setdefault("fetch", self.fetch)
        kw.setdefault("totals", self.totals)
        return mf.build(out_dir=self.out, core_csv=self.core, log=lambda *_: None,
                        min_results=6, **kw)

    def read(self, name):
        with open(os.path.join(self.out, name), encoding="utf-8") as f:
            return list(csv.reader(f))

    def test_end_to_end(self):
        rep = self.build(skip_pet=False)
        self.assertTrue(rep["ok"])
        rows = self.read("meta-listings-vic.csv")
        self.assertEqual(rows[0], HEADER)
        links = {r[0]: r[2] for r in rows[1:]}
        self.assertEqual(links["listing_1"], url("VIC", "grampians", "cabin"))
        self.assertEqual(links["listing_2"], url("VIC", "grampians"))
        self.assertEqual(links["listing_3"], url("VIC", "grampians", None, True))
        self.assertEqual(links["listing_8"], url("VIC"))
        self.assertEqual(links["listing_4"], url("VIC"))   # unjoined, pet only matters with labels
        for r in rows[1:]:
            self.assertEqual(r[5], r[2])                  # applink swapped too
            self.assertEqual(r[1], "Title, with comma")   # other columns untouched
        story = self.read("meta-stories-vic.csv")[1]
        self.assertEqual(story[2], url("VIC", "grampians", None, True))  # Pet in custom_label_4
        self.assertEqual(self.read("meta-listings-nsw.csv")[1][2], url("NSW", "north-coast", "house"))
        self.assertEqual(self.read("meta-stories-nsw.csv")[1][2], url("NSW"))
        f = rep["feeds"]["meta-listings-vic.csv"]
        self.assertEqual(f["rows"], 5)
        self.assertEqual(f["unjoined"], 2)
        self.assertEqual(f["pet_identified"], 2)
        self.assertEqual(f["rungs"]["region+type"], 1)
        with open(os.path.join(self.out, mf.REPORT_JSON)) as fh:
            self.assertEqual(json.load(fh)["min_results"], 6)
        self.assertEqual(rep["pet"]["VIC"]["site_pet_total"], 1)
        self.assertEqual(rep["pet"]["VIC"]["coverage"], 1.0)

    def test_pet_is_off_by_default(self):
        # Client decision 19 Nov 2026: no pet-friendly landing pages.
        fetched = []
        def fetch(u):
            fetched.append(u)
            return self.fetch(u)
        rep = self.build(fetch=fetch)
        self.assertFalse(rep["pet"]["enabled"])
        self.assertFalse(any("petFriendly" in u for u in fetched))
        links = {r[0]: r[2] for r in self.read("meta-listings-vic.csv")[1:]}
        self.assertEqual(links["listing_3"], url("VIC", "grampians", "cabin"))  # INT_PET_FRIENDLY ignored
        self.assertEqual(self.read("meta-stories-vic.csv")[1][2], url("VIC", "grampians", "cabin"))
        for name, f in rep["feeds"].items():
            self.assertEqual(f["pet_identified"], 0, name)
            self.assertFalse(any("pet" in k for k in f["rungs"]), name)

    def test_unknown_state_count_keeps_original_link(self):
        self.counts = {}
        old = mf.MAX_ORIGINAL_RATIO
        mf.MAX_ORIGINAL_RATIO = 1.0
        try:
            rep = self.build(skip_pet=True)
        finally:
            mf.MAX_ORIGINAL_RATIO = old
        rows = self.read("meta-listings-vic.csv")
        self.assertEqual(rows[1][2], B + "/listings/1-a")
        self.assertEqual(rep["feeds"]["meta-listings-vic.csv"]["original_link_kept"], 5)

    def test_mostly_unknown_counts_keep_previous_file(self):
        self.build(skip_pet=True)
        before = self.read("meta-listings-vic.csv")
        self.counts = {}
        rep = self.build(skip_pet=True)
        self.assertFalse(rep["ok"])
        self.assertEqual(self.read("meta-listings-vic.csv"), before)
        self.assertTrue(rep["feeds"]["meta-listings-vic.csv"]["kept_previous"])

    def test_one_failed_feed_keeps_its_previous_file(self):
        self.build(skip_pet=True)
        before = self.read("meta-stories-vic.csv")
        del self.feeds[("stories", "VIC")]
        rep = self.build(skip_pet=True)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["feeds"]["meta-stories-vic.csv"]["status"], "failed")
        self.assertTrue(rep["feeds"]["meta-stories-vic.csv"]["kept_previous"])
        self.assertEqual(self.read("meta-stories-vic.csv"), before)
        self.assertEqual(rep["feeds"]["meta-listings-vic.csv"]["status"], "ok")

    def test_bad_link_fails_validation_and_keeps_file(self):
        self.build(skip_pet=True)
        before = self.read("meta-listings-nsw.csv")
        self.counts[url("NSW", "north-coast", "house")] = None
        orig = mf.search_url

        def broken(state, region=None, sub=None, pet=False):
            return orig(state, region, sub, pet).replace("state=", "s=")
        mf.search_url = broken
        try:
            self.counts = {broken(*k): v for k, v in [(("NSW",), 1339)]}
            rep = self.build(skip_pet=True)
        finally:
            mf.search_url = orig
        self.assertEqual(rep["feeds"]["meta-listings-nsw.csv"]["status"], "failed")
        self.assertEqual(self.read("meta-listings-nsw.csv"), before)

    def test_empty_input_feed_is_a_failure(self):
        self.feeds[("stories", "NSW")] = feed_text([])
        rep = self.build(skip_pet=True)
        self.assertEqual(rep["feeds"]["meta-stories-nsw.csv"]["status"], "failed")
        self.assertFalse(os.path.exists(os.path.join(self.out, "meta-stories-nsw.csv")))

    def test_counts_seen_while_harvesting_pet_are_not_fetched_again(self):
        asked = []

        def totals(urls, log=None):
            asked.extend(urls)
            return self.totals(urls)
        self.build(totals=totals)
        self.assertIn(url("VIC", "grampians"), asked)
        self.assertNotIn(url("VIC", pet=True), asked)

    def test_missing_core_csv_fails(self):
        rep = mf.build(out_dir=self.out, core_csv=os.path.join(self.tmp, "nope.csv"),
                       fetch=self.fetch, totals=self.totals, log=lambda *_: None)
        self.assertFalse(rep["ok"])
        self.assertIn("core CSV missing", rep["error"])

    def test_every_feed_failing_fails_the_build(self):
        def fetch(u):
            raise mf.fetcher.FetchError(u)
        rep = self.build(fetch=fetch)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["error"], "every feed failed")

    def test_pet_harvest_failure_does_not_fail_build(self):
        def fetch(u):
            if "petFriendly" in u:
                raise mf.fetcher.FetchError("blocked")
            return self.fetch(u)
        rep = self.build(fetch=fetch, skip_pet=False)
        self.assertTrue(rep["ok"])
        self.assertIn("blocked", rep["pet"]["VIC"]["error"])

    def test_cli_offline(self):
        feeds_dir = os.path.join(self.tmp, "feeds")
        os.makedirs(feeds_dir)
        for (kind, market), text in self.feeds.items():
            with open(os.path.join(feeds_dir, "%s_%s.csv" % (kind, market)), "w", encoding="utf-8") as f:
                f.write(text)
        counts = os.path.join(self.tmp, "counts.json")
        with open(counts, "w") as f:
            json.dump({u: {"code": 200, "total": n} for u, n in self.counts.items()}, f)
        rc = mf.main(["--out", self.out, "--core", self.core, "--offline-feeds", feeds_dir,
                      "--counts-json", counts, "--skip-pet"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.read("meta-listings-vic.csv")[1][2], url("VIC", "grampians", "cabin"))


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Unit tests for labeller.py.

Run from the src/ directory: python -m unittest test_labeller -v
(or `python -m unittest discover -p "test_*.py"` to run the whole suite).
"""
import unittest

import config as cfg
import labeller


class StayTypeTests(unittest.TestCase):
    def test_matches_known_subcategory(self):
        self.assertEqual(labeller.stay_type_from("1793-the-mudbrick-cottage"), "TYPE_COTTAGE")

    def test_longest_match_wins_over_substring(self):
        # "treehouse" must not be shadowed by "house", and "luxury-house" by "house".
        self.assertEqual(labeller.stay_type_from("100-forest-treehouse"), "TYPE_TREEHOUSE")
        self.assertEqual(labeller.stay_type_from("200-a-luxury-house-retreat"), "TYPE_LUXURY_HOUSE")

    def test_no_match_returns_empty(self):
        self.assertEqual(labeller.stay_type_from("100-mystery-listing"), "")


class IntentTests(unittest.TestCase):
    def test_single_intent(self):
        self.assertEqual(labeller.intents_from("romantic-hideaway"), ["INT_ROMANTIC"])

    def test_getaway_keyword_present(self):
        # Regression guard for the missing-getaway gap found against the SNR
        # spec (romantic, getaways, off-grid, pet-friendly all beat PMax 2x+).
        self.assertIn("INT_GETAWAY", labeller.intents_from("weekend-getaway-cabin"))
        self.assertIn("INT_GETAWAY", labeller.intents_from("mountain-getaways-retreat"))
        self.assertIn("INT_GETAWAY", cfg.SEARCH_HEAD_INTENTS)

    def test_getaway_does_not_false_positive_on_escape(self):
        self.assertNotIn("INT_GETAWAY", labeller.intents_from("dreamy-escape-above-lake"))

    def test_capped_at_two(self):
        ints = labeller.intents_from("romantic-honeymoon-pet-friendly-hot-tub-luxury-getaway")
        self.assertEqual(len(ints), 2)

    def test_no_intent_returns_empty_list(self):
        self.assertEqual(labeller.intents_from("plain-cabin"), [])


class RegionLabelTests(unittest.TestCase):
    def test_unambiguous_slug(self):
        self.assertEqual(labeller.region_label("yarra-valley", "GEO_AU", "GEO_VIC"), "REG_YARRA_VALLEY")

    def test_ambiguous_slug_gets_state_suffix(self):
        self.assertEqual(labeller.region_label("north-coast", "GEO_AU", "GEO_NSW"), "REG_NORTH_COAST_NSW")

    def test_ambiguous_slug_gets_country_suffix_when_no_state(self):
        # Only VIC/NSW/WA/OR have a state suffix; a country with no matching
        # state code (e.g. NZ) falls back to the country suffix instead.
        self.assertEqual(labeller.region_label("north-coast", "GEO_NZ", ""), "REG_NORTH_COAST_NZ")


class RegionCollisionTests(unittest.TestCase):
    def test_collision_detected_across_hubs(self):
        rows = [
            {"page_type": "PAGE_REGION", "region": "REG_SAME", "url": "https://x/a"},
            {"page_type": "PAGE_REGION", "region": "REG_SAME", "url": "https://x/b"},
            {"page_type": "PAGE_REGION", "region": "REG_OTHER", "url": "https://x/c"},
        ]
        collisions = labeller.find_region_collisions(rows)
        self.assertEqual(set(collisions), {"REG_SAME"})
        self.assertEqual(sorted(collisions["REG_SAME"]), ["https://x/a", "https://x/b"])

    def test_no_collision_when_unique(self):
        rows = [{"page_type": "PAGE_REGION", "region": "REG_A", "url": "https://x/a"},
                {"page_type": "PAGE_REGION", "region": "REG_B", "url": "https://x/b"}]
        self.assertEqual(labeller.find_region_collisions(rows), {})


class LabelUrlTests(unittest.TestCase):
    def test_core_page_excluded(self):
        row = labeller.label_url(cfg.BASE + "/about", "core")
        self.assertEqual(row["page_type"], "PAGE_CORE")
        self.assertEqual(labeller.feed_of(row), cfg.FEED_EXCLUDE)

    def test_adventure_page(self):
        row = labeller.label_url(cfg.BASE + "/adventures/500-romantic-picnic-tour", "adventures")
        self.assertEqual(row["page_type"], "PAGE_ADVENTURE")
        self.assertEqual(row["boundary"], "ADV_HOLD")
        self.assertEqual(row["intent1"], "INT_ROMANTIC")
        self.assertEqual(labeller.feed_of(row), cfg.FEED_ADVENTURES)

    def test_listing_page(self):
        row = labeller.label_url(cfg.BASE + "/listings/1793-the-mudbrick-cottage", "listings")
        self.assertEqual(row["page_type"], "PAGE_LISTING")
        self.assertEqual(row["stay"], "TYPE_COTTAGE")
        self.assertEqual(row["boundary"], "PMAX_LONGTAIL")

    def test_listing_with_search_head_intent(self):
        row = labeller.label_url(cfg.BASE + "/listings/1-romantic-cabin", "listings")
        self.assertEqual(row["boundary"], "SEARCH_HEAD")

    def test_country_page(self):
        row = labeller.label_url(cfg.BASE + "/au", "destinations")
        self.assertEqual(row["page_type"], "PAGE_COUNTRY")
        self.assertEqual(row["country"], "GEO_AU")

    def test_state_page(self):
        row = labeller.label_url(cfg.BASE + "/au/vic", "destinations")
        self.assertEqual(row["page_type"], "PAGE_STATE")
        self.assertEqual(row["state"], "GEO_VIC")

    def test_us_state_gets_hold_boundary(self):
        row = labeller.label_url(cfg.BASE + "/us/oregon", "destinations")
        self.assertEqual(row["boundary"], "US_HOLD")

    def test_nz_gets_review_boundary(self):
        row = labeller.label_url(cfg.BASE + "/nz", "destinations")
        self.assertEqual(row["boundary"], "NZ_REVIEW")

    def test_region_page(self):
        row = labeller.label_url(cfg.BASE + "/au/vic/yarra-valley", "destinations")
        self.assertEqual(row["page_type"], "PAGE_REGION")
        self.assertEqual(row["region"], "REG_YARRA_VALLEY")

    def test_ambiguous_region_page(self):
        row = labeller.label_url(cfg.BASE + "/au/nsw/north-coast", "destinations")
        self.assertEqual(row["region"], "REG_NORTH_COAST_NSW")
        row2 = labeller.label_url(cfg.BASE + "/us/oregon/north-coast", "destinations")
        self.assertEqual(row2["region"], "REG_NORTH_COAST_OR")
        self.assertNotEqual(row["region"], row2["region"])

    def test_collection_hub(self):
        row = labeller.label_url(cfg.BASE + "/au/collections", "collections")
        self.assertEqual(row["page_type"], "PAGE_COLLECTION_HUB")

    def test_collection_with_poi_region(self):
        row = labeller.label_url(cfg.BASE + "/au/nsw/collections/byron-bay", "collections")
        self.assertEqual(row["page_type"], "PAGE_COLLECTION")
        self.assertEqual(row["region"], "REG_NORTH_COAST_NSW")
        self.assertIn("point of interest", row["notes"])


class FacetRowTests(unittest.TestCase):
    def setUp(self):
        self.rows = labeller.build_facet_rows()

    def test_count_matches_scopes_times_subcats(self):
        self.assertEqual(len(self.rows), len(cfg.FACET_SCOPES) * len(cfg.SUBCATS))

    def test_params_are_alphabetical_and_no_state_when_none(self):
        for r in self.rows:
            q = r["url"].split("?", 1)[1]
            names = [p.split("=", 1)[0].replace("%5B%5D", "") for p in q.split("&")]
            self.assertEqual(names, sorted(names))
            if "state=" not in q:
                self.assertNotIn("state", names)

    def test_search_head_type_gets_search_head_boundary(self):
        matches = [r for r in self.rows if r["stay"] == "TYPE_TINY_HOUSE"]
        self.assertTrue(matches)
        for r in matches:
            if r["boundary"] not in ("NZ_REVIEW", "US_HOLD"):
                self.assertEqual(r["boundary"], "SEARCH_HEAD")

    def test_all_facet_rows_are_page_facet_type(self):
        self.assertTrue(all(r["page_type"] == "PAGE_FACET_TYPE" for r in self.rows))


class LabelStringTests(unittest.TestCase):
    def test_blanks_are_skipped_and_order_preserved(self):
        row = labeller._row(cfg.BASE + "/x", "PAGE_LISTING", "GEO_AU", "", "", "TYPE_COTTAGE",
                             "", "", "PMAX_LONGTAIL")
        self.assertEqual(labeller.label_string(row), "PAGE_LISTING;GEO_AU;TYPE_COTTAGE;PMAX_LONGTAIL")

    def test_no_double_semicolons_possible(self):
        row = labeller._row(cfg.BASE + "/x", "PAGE_CORE")
        self.assertEqual(labeller.label_string(row), "PAGE_CORE")
        self.assertNotIn(";;", labeller.label_string(row))


if __name__ == "__main__":
    unittest.main()

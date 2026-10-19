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


class RegionSlugTests(unittest.TestCase):
    def test_macrons_are_folded_not_dropped(self):
        self.assertEqual(labeller.region_slug("Taupō"), "taupo")
        self.assertEqual(labeller.region_slug("Manawatū-Whanganui"), "manawatu-whanganui")

    def test_apostrophe_is_removed_not_hyphenated(self):
        self.assertEqual(labeller.region_slug("Hawke's Bay"), "hawkes-bay")
        self.assertEqual(labeller.region_slug("Hawke’s Bay"), "hawkes-bay")

    def test_listing_title_spelling_maps_to_hub_spelling(self):
        self.assertEqual(labeller.region_slug("Tairāwhiti Gisborne"), "tairawhiti-eastland")

    def test_listing_labels_equal_hub_labels(self):
        hubs = {"hawkes-bay": "Hawke's Bay", "taupo": "Taupō",
                "manawatu-whanganui": "Manawatū-Whanganui",
                "tairawhiti-eastland": "Tairāwhiti Gisborne"}
        for hub_slug, title_name in hubs.items():
            self.assertEqual(
                labeller.region_label(labeller.region_slug(title_name), "GEO_NZ", ""),
                labeller.region_label(hub_slug, "GEO_NZ", ""))

    def test_every_alias_targets_a_real_hub_slug_and_title_wording_resolves(self):
        cases = {"Northland & Bay of Islands": "northland", "Waikato": "hamilton-waikato",
                 "The Coromandel": "coromandel", "Mt Hood & River Gorge": "hood-gorge"}
        for name, hub in cases.items():
            self.assertEqual(labeller.region_slug(name), hub)

    def test_plain_names_unchanged(self):
        self.assertEqual(labeller.region_slug("Bay of Plenty"), "bay-of-plenty")


class CollectionTagTests(unittest.TestCase):
    def _label(self, path):
        return labeller.label_string(labeller.label_url(cfg.BASE + path, "collections"))

    def test_beach_houses_collection_is_beach_house_not_house(self):
        for path in ("/au/vic/collections/top-stays-beach-houses",
                     "/au/nsw/collections/top-stays-beach-houses-7a16fe70-6a37-4312-8fc3-b4ba2226e76e"):
            self.assertIn("TYPE_BEACH_HOUSE", self._label(path))
            self.assertNotIn("TYPE_HOUSE;", self._label(path))

    def test_plain_house_still_house(self):
        self.assertEqual(labeller.stay_type_from("100-quiet-house-in-the-forest"), "TYPE_HOUSE")

    def test_bare_extra_wording_not_matched_in_slug(self):
        self.assertEqual(labeller.stay_type_from("12-cavendish-retreat"), "")

    def test_outdoor_baths_soak_and_stars_get_intents(self):
        self.assertIn("INT_OUTDOOR_BATH", self._label("/au/nsw/collections/outdoor-baths-nsw"))
        self.assertIn("INT_OUTDOOR_BATH", self._label(
            "/au/nsw/collections/soak-it-up-ba05795a-cc0d-48a6-916e-e247b3f02b6c"))
        self.assertIn("INT_STARGAZING", self._label("/au/vic/collections/under-the-stars"))

    def test_new_intents_do_not_displace_search_head_intents(self):
        ints = labeller.intents_from("romantic-outdoor-baths-under-the-stars")
        self.assertEqual(ints, ["INT_ROMANTIC", "INT_OUTDOOR_BATH"])
        self.assertEqual(labeller.intents_from("dog-friendly-romantic-under-the-stars")[:2],
                         ["INT_ROMANTIC", "INT_PET_FRIENDLY"])

    def test_new_intents_are_not_search_head(self):
        self.assertIn("PMAX_LONGTAIL", self._label("/au/vic/collections/under-the-stars"))


class SearchRowTests(unittest.TestCase):
    def setUp(self):
        hub = labeller.label_url(cfg.BASE + "/au/nsw/blue-mountains", "destinations")
        nz = labeller.label_url(cfg.BASE + "/nz/taupo", "destinations")
        self.rows = labeller.build_search_rows([hub, nz])
        self.by_url = {r["url"]: r for r in self.rows}

    def test_blue_mountains_region_search_exists(self):
        u = cfg.BASE + "/listings?country=AU&regions%5B%5D=blue-mountains&state=NSW&type=accommodation"
        self.assertIn(u, self.by_url)
        r = self.by_url[u]
        self.assertEqual((r["region"], r["state"], r["boundary"]),
                         ("REG_BLUE_MOUNTAINS", "GEO_NSW", "PMAX_LONGTAIL"))

    def test_all_vic_search_exists(self):
        u = cfg.BASE + "/listings?country=AU&state=VIC&type=accommodation"
        self.assertEqual(self.by_url[u]["state"], "GEO_VIC")

    def test_pet_friendly_with_and_without_geography(self):
        r = self.by_url[cfg.BASE + "/listings?country=AU&petFriendly=true&state=VIC&type=accommodation"]
        self.assertEqual((r["intent1"], r["boundary"]), ("INT_PET_FRIENDLY", "SEARCH_HEAD"))
        bare = self.by_url[cfg.BASE + "/listings?petFriendly=true&type=accommodation"]
        self.assertEqual(bare["country"], "")

    def test_nz_region_search_has_no_state_and_review_boundary(self):
        r = self.by_url[cfg.BASE + "/listings?country=NZ&regions%5B%5D=taupo&type=accommodation"]
        self.assertEqual((r["state"], r["boundary"]), ("", "NZ_REVIEW"))

    def test_us_pet_search_is_held(self):
        r = self.by_url[cfg.BASE + "/listings?country=US&petFriendly=true&state=WA&type=accommodation"]
        self.assertEqual(r["boundary"], "US_HOLD")

    def test_all_params_alphabetical_and_urls_unique(self):
        from urllib.parse import urlsplit
        self.assertEqual(len(self.by_url), len(self.rows))
        for u in self.by_url:
            names = [p.split("=")[0] for p in urlsplit(u).query.split("&")]
            self.assertEqual(names, sorted(names), u)

    def test_page_type_and_validator_accepts(self):
        import validator
        self.assertTrue(all(r["page_type"] == "PAGE_SEARCH" for r in self.rows))
        vrows = [{"url": r["url"], "label": labeller.label_string(r), "feed": "CORE"} for r in self.rows]
        ok, results = validator.validate(vrows)
        self.assertTrue(ok, validator.format_results(results))


if __name__ == "__main__":
    unittest.main()

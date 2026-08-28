# -*- coding: utf-8 -*-
"""Unit tests for enricher.py's title parser.

The four example titles here are copied verbatim from the module's own
docstring, which records them as verified against the live site.
"""
import unittest

import enricher


class ParseTitleTests(unittest.TestCase):
    def test_glamping_listing_au_vic(self):
        out = enricher.parse_title(
            "Pebble Point - Glamping for Rent in Princetown, Great Ocean Road, VIC, AU")
        self.assertEqual(out["country"], "GEO_AU")
        self.assertEqual(out["state"], "GEO_VIC")
        self.assertEqual(out["region"], "REG_GREAT_OCEAN_ROAD")
        self.assertEqual(out["stay"], "TYPE_GLAMPING")

    def test_cabin_listing_nz_no_state(self):
        out = enricher.parse_title(
            "Hobbit Tree House in Waikino - Cabin for Rent in Waikino, The Coromandel, NZ")
        self.assertEqual(out["country"], "GEO_NZ")
        self.assertEqual(out["state"], "")
        self.assertEqual(out["region"], "REG_THE_COROMANDEL")
        self.assertEqual(out["stay"], "TYPE_CABIN")

    def test_cabin_listing_us_wa(self):
        out = enricher.parse_title(
            "The Hideout - Cabin for Rent in Deming, North Cascades, WA, US")
        self.assertEqual(out["country"], "GEO_US")
        self.assertEqual(out["state"], "GEO_WA")
        self.assertEqual(out["region"], "REG_NORTH_CASCADES")
        self.assertEqual(out["stay"], "TYPE_CABIN")

    def test_adventure_title_has_no_stay_type_but_has_location(self):
        out = enricher.parse_title(
            "The Willows - Adventure by Chris in Anglers Rest, High Country, VIC, AU")
        self.assertEqual(out["country"], "GEO_AU")
        self.assertEqual(out["state"], "GEO_VIC")
        self.assertEqual(out["region"], "REG_HIGH_COUNTRY")
        self.assertNotIn("stay", out)

    def test_a_frame_stay_type_not_split_on_its_own_dash(self):
        out = enricher.parse_title("Forest Retreat - A-Frame for Rent in Warburton, Yarra Valley, VIC, AU")
        self.assertEqual(out.get("stay"), "TYPE_A_FRAME")

    def test_multiple_separators_stay_type_is_segment_before_for_rent(self):
        out = enricher.parse_title(
            "The Hideout - Hot Tub - Pets Ok - Cabin for Rent in Deming, North Cascades, WA, US")
        self.assertEqual(out.get("stay"), "TYPE_CABIN")

    def test_extra_stay_wording_maps_to_configured_label(self):
        out = enricher.parse_title("Bayview - Beach House for Rent in Sorrento, Mornington Peninsula, VIC, AU")
        self.assertEqual(out.get("stay"), "TYPE_BEACH_HOUSE")

    def test_unmapped_stay_wording_is_recorded_not_guessed(self):
        out = enricher.parse_title("Mystery Stay - Space Pod for Rent in Nowhere, Somewhere, VIC, AU")
        self.assertNotIn("stay", out)
        self.assertEqual(out.get("stay_wording_unmapped"), "Space Pod")

    def test_no_location_in_title_returns_empty(self):
        self.assertEqual(enricher.parse_title("Riparide | Unique stays across Australia"), {})

    def test_empty_title_returns_empty(self):
        self.assertEqual(enricher.parse_title(""), {})
        self.assertEqual(enricher.parse_title(None), {})

    def test_unrecognised_country_token_returns_empty(self):
        # "UK" is not one of the three markets riparide operates in.
        self.assertEqual(enricher.parse_title("A House for Rent in London, UK"), {})

    def test_riparide_suffix_and_html_entities_are_stripped(self):
        out = enricher.parse_title(
            "Pebble Point - Glamping for Rent in Princetown, Great Ocean Road, VIC, AU | Riparide")
        self.assertEqual(out["stay"], "TYPE_GLAMPING")

    def test_own_name_containing_in_does_not_get_read_as_the_region(self):
        # The listing's own name has " in " in it; the real location comes
        # after the LAST " in ", not the first.
        out = enricher.parse_title(
            "Cozy Cabin in Brownsbay - Cabin for Rent in Byron Bay, Northern Rivers, NSW, AU")
        self.assertEqual(out["region"], "REG_NORTHERN_RIVERS")

    def test_postcode_as_its_own_comma_segment_is_dropped(self):
        out = enricher.parse_title(
            "Karekare Cabin in the Heart of West Coast - Cabin for Rent in "
            "Karekare, Waiheke Island, 1971, NZ")
        self.assertEqual(out["region"], "REG_WAIHEKE_ISLAND")

    def test_trailing_postcode_on_the_region_itself_is_trimmed(self):
        out = enricher.parse_title(
            "Bach at North Cove - Cabin for Rent in North Cove 0920, Auckland, NZ")
        self.assertEqual(out["region"], "REG_AUCKLAND")


class CleanRegionTests(unittest.TestCase):
    """clean_region() is the last line of defence: even if the title split
    lands in the wrong place, a candidate that cannot be a real place name
    is refused rather than shipped as a wrong label.
    """

    def test_normal_region_name_passes_through(self):
        self.assertEqual(enricher.clean_region("Great Ocean Road"), "Great Ocean Road")

    def test_a_bare_number_is_refused(self):
        self.assertEqual(enricher.clean_region("1971"), "")

    def test_a_trailing_postcode_is_trimmed_not_refused(self):
        self.assertEqual(enricher.clean_region("North Cove 0920"), "North Cove")

    def test_a_candidate_containing_in_is_refused(self):
        self.assertEqual(
            enricher.clean_region("the trees. With a sensational view. - House for Rent in Sydney"),
            "")

    def test_a_candidate_over_five_words_is_refused(self):
        self.assertEqual(enricher.clean_region("one two three four five six"), "")

    def test_blank_input_is_refused(self):
        self.assertEqual(enricher.clean_region(""), "")
        self.assertEqual(enricher.clean_region(None), "")


if __name__ == "__main__":
    unittest.main()

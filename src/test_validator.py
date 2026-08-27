# -*- coding: utf-8 -*-
"""Unit tests for validator.py — each QA rule from the feed spec, isolated."""
import unittest

import config as cfg
import validator


def _rows(*specs):
    """specs = [(url, label), ...]. feed defaults to CORE."""
    return [{"url": u, "label": l, "feed": cfg.FEED_CORE} for u, l in specs]


GOOD_ROW = (cfg.BASE + "/listings/1-x", "PAGE_LISTING;GEO_AU;PMAX_LONGTAIL")


class CleanFeedTests(unittest.TestCase):
    def test_clean_feed_passes_everything(self):
        rows = _rows(GOOD_ROW, (cfg.BASE + "/listings/2-y", "PAGE_LISTING;PMAX_LONGTAIL"))
        passed, checks = validator.validate(rows)
        self.assertTrue(passed)
        self.assertTrue(all(c["passed"] for c in checks))


class DuplicateUrlTests(unittest.TestCase):
    def test_duplicate_url_fails(self):
        rows = _rows(GOOD_ROW, GOOD_ROW)
        passed, checks = validator.validate(rows)
        self.assertFalse(passed)
        dupe_check = next(c for c in checks if c["check"] == "Duplicate URLs across both feeds")
        self.assertFalse(dupe_check["passed"])


class EmptyLabelTests(unittest.TestCase):
    def test_blank_label_fails(self):
        rows = _rows((cfg.BASE + "/listings/1-x", ""))
        passed, checks = validator.validate(rows)
        self.assertFalse(passed)


class LabelCountTests(unittest.TestCase):
    def test_over_twenty_labels_fails(self):
        too_many = ";".join("LABEL_%d" % i for i in range(cfg.MAX_LABELS_PER_URL + 1))
        rows = _rows((cfg.BASE + "/listings/1-x", too_many))
        passed, checks = validator.validate(rows)
        self.assertFalse(passed)

    def test_exactly_twenty_labels_passes(self):
        exactly = ";".join("LABEL_%d" % i for i in range(cfg.MAX_LABELS_PER_URL))
        rows = _rows((cfg.BASE + "/listings/1-x", exactly))
        passed, checks = validator.validate(rows)
        self.assertTrue(passed)


class TrackingParamTests(unittest.TestCase):
    def test_utm_param_fails(self):
        rows = _rows((cfg.BASE + "/listings/1-x?utm_source=ads", "PAGE_LISTING"))
        passed, checks = validator.validate(rows)
        self.assertFalse(passed)

    def test_gclid_fails(self):
        rows = _rows((cfg.BASE + "/listings/1-x?gclid=abc", "PAGE_LISTING"))
        passed, _ = validator.validate(rows)
        self.assertFalse(passed)

    def test_functional_param_is_fine(self):
        rows = _rows((cfg.BASE + "/listings?country=AU&state=VIC&subcategories%5B%5D=cabin&type=accommodation",
                      "PAGE_FACET_TYPE"))
        passed, _ = validator.validate(rows)
        self.assertTrue(passed)


class DomainTests(unittest.TestCase):
    def test_offsite_url_fails(self):
        rows = _rows(("https://not-riparide.com/listings/1-x", "PAGE_LISTING"))
        passed, _ = validator.validate(rows)
        self.assertFalse(passed)


class FacetOrderTests(unittest.TestCase):
    def test_canonical_order_passes(self):
        rows = _rows((cfg.BASE + "/listings?country=AU&state=VIC&subcategories%5B%5D=cabin&type=accommodation",
                      "PAGE_FACET_TYPE"))
        passed, _ = validator.validate(rows)
        self.assertTrue(passed)

    def test_wrong_order_fails(self):
        # type before subcategories: not alphabetical, exactly the redirect trap the spec warns about.
        rows = _rows((cfg.BASE + "/listings?type=accommodation&subcategories%5B%5D=cabin&country=AU&state=VIC",
                      "PAGE_FACET_TYPE"))
        passed, checks = validator.validate(rows)
        self.assertFalse(passed)
        order_check = next(c for c in checks
                           if c["check"] == "Facet URLs with parameters out of canonical order")
        self.assertFalse(order_check["passed"])


class StatusCheckTests(unittest.TestCase):
    def test_non_200_status_in_output_fails(self):
        rows = _rows(GOOD_ROW)
        passed, checks = validator.validate(rows, status_by_url={GOOD_ROW[0]: 404})
        self.assertFalse(passed)

    def test_zero_status_is_treated_as_unknown_not_dead(self):
        rows = _rows(GOOD_ROW)
        passed, _ = validator.validate(rows, status_by_url={GOOD_ROW[0]: 0})
        self.assertTrue(passed)


class LabelCharsetTests(unittest.TestCase):
    def test_lowercase_or_symbol_in_label_fails(self):
        rows = _rows((cfg.BASE + "/listings/1-x", "page_listing"))
        passed, _ = validator.validate(rows)
        self.assertFalse(passed)


class SeparatorTests(unittest.TestCase):
    def test_double_semicolon_fails(self):
        rows = _rows((cfg.BASE + "/listings/1-x", "PAGE_LISTING;;PMAX_LONGTAIL"))
        passed, _ = validator.validate(rows)
        self.assertFalse(passed)

    def test_leading_semicolon_fails(self):
        rows = _rows((cfg.BASE + "/listings/1-x", ";PAGE_LISTING"))
        passed, _ = validator.validate(rows)
        self.assertFalse(passed)

    def test_trailing_semicolon_fails(self):
        rows = _rows((cfg.BASE + "/listings/1-x", "PAGE_LISTING;"))
        passed, _ = validator.validate(rows)
        self.assertFalse(passed)


class FeedCollapseTests(unittest.TestCase):
    def test_no_previous_counts_passes(self):
        rows = _rows(GOOD_ROW)
        passed, _ = validator.validate(rows, previous_counts=None)
        self.assertTrue(passed)

    def test_collapse_below_ratio_fails(self):
        # Simulates every URL failing its status check (e.g. the site is
        # unreachable): last month had 100 core rows, this run has 1.
        rows = _rows(GOOD_ROW)
        passed, checks = validator.validate(rows, previous_counts={cfg.FEED_CORE: 100})
        self.assertFalse(passed)
        collapse_check = next(c for c in checks
                              if c["check"] == "Feed size has not collapsed versus last run")
        self.assertFalse(collapse_check["passed"])

    def test_small_natural_change_passes(self):
        rows = _rows(GOOD_ROW, (cfg.BASE + "/listings/2-y", "PAGE_LISTING"))
        passed, _ = validator.validate(rows, previous_counts={cfg.FEED_CORE: 2})
        self.assertTrue(passed)

    def test_zero_previous_count_is_ignored(self):
        # A feed that had 0 rows last time (e.g. Adventures before it existed)
        # can't "collapse" further — nothing to divide by.
        rows = _rows(GOOD_ROW)
        passed, _ = validator.validate(rows, previous_counts={cfg.FEED_ADVENTURES: 0})
        self.assertTrue(passed)


if __name__ == "__main__":
    unittest.main()

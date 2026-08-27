# -*- coding: utf-8 -*-
"""Unit tests for attributes.py — the optional supplied-attributes merge."""
import csv
import io
import os
import shutil
import tempfile
import unittest

import attributes
import labeller


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


class LoadMissingFileTests(unittest.TestCase):
    def test_missing_file_is_not_an_error(self):
        by_id, report = attributes.load(path="/no/such/file.csv")
        self.assertEqual(by_id, {})
        self.assertFalse(report["present"])
        self.assertIn("file not found", report["problems"][0])


class ColumnAliasTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "attrs.csv")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_recognises_alternate_header_spellings(self):
        _write_csv(self.path, ["Listing ID", "Country Code", "Province", "Property Type", "Status"],
                    [["97", "AU", "VIC", "cabin", "active"]])
        by_id, report = attributes.load(path=self.path)
        self.assertEqual(report["columns"]["country"], "Country Code")
        self.assertEqual(report["columns"]["state"], "Province")
        self.assertIn("97", by_id)
        self.assertEqual(by_id["97"]["country"], "GEO_AU")
        self.assertEqual(by_id["97"]["state"], "GEO_VIC")
        self.assertEqual(by_id["97"]["stay"], "TYPE_CABIN")

    def test_no_id_column_is_reported(self):
        _write_csv(self.path, ["Country"], [["AU"]])
        by_id, report = attributes.load(path=self.path)
        self.assertEqual(by_id, {})
        self.assertTrue(any("no id column" in p for p in report["problems"]))

    def test_id_tolerates_slug_prefix(self):
        _write_csv(self.path, ["id", "country"], [["97-pebble-point", "AU"]])
        by_id, _ = attributes.load(path=self.path)
        self.assertIn("97", by_id)

    def test_non_numeric_id_is_skipped(self):
        _write_csv(self.path, ["id", "country"], [["not-a-number", "AU"]])
        by_id, report = attributes.load(path=self.path)
        self.assertEqual(by_id, {})
        self.assertEqual(report["rows"], 1)
        self.assertEqual(report["usable"], 0)

    def test_inactive_rows_are_skipped(self):
        _write_csv(self.path, ["id", "country", "active"],
                    [["1", "AU", "yes"], ["2", "AU", "archived"]])
        by_id, report = attributes.load(path=self.path)
        self.assertIn("1", by_id)
        self.assertNotIn("2", by_id)
        self.assertEqual(report["inactive"], 1)

    def test_region_slug_uses_labeller_ambiguous_handling(self):
        _write_csv(self.path, ["id", "country", "state", "region"],
                    [["1", "AU", "NSW", "North Coast"]])
        by_id, _ = attributes.load(path=self.path)
        self.assertEqual(by_id["1"]["region"], "REG_NORTH_COAST_NSW")

    def test_amenities_map_to_intent_labels(self):
        _write_csv(self.path, ["id", "amenities"], [["1", "Hot tub, pet friendly on request"]])
        by_id, _ = attributes.load(path=self.path)
        self.assertIn("INT_HOT_TUB", by_id["1"]["intents"])
        self.assertIn("INT_PET_FRIENDLY", by_id["1"]["intents"])


class ApplyTests(unittest.TestCase):
    def _row(self, url, page_type="PAGE_LISTING"):
        return labeller._row(url, page_type)

    def test_fills_blank_location_only(self):
        row = self._row("https://www.riparide.com/listings/1-x")
        by_id = {"1": {"country": "GEO_AU", "state": "GEO_VIC", "region": "REG_YARRA_VALLEY"}}
        summary = attributes.apply([row], by_id)
        self.assertEqual(row["country"], "GEO_AU")
        self.assertEqual(row["region"], "REG_YARRA_VALLEY")
        self.assertEqual(summary["rows_filled"], 1)

    def test_does_not_override_existing_value(self):
        row = self._row("https://www.riparide.com/listings/1-x")
        row["country"] = "GEO_NZ"
        by_id = {"1": {"country": "GEO_AU"}}
        attributes.apply([row], by_id)
        self.assertEqual(row["country"], "GEO_NZ")

    def test_boundary_recomputed_for_us(self):
        row = self._row("https://www.riparide.com/listings/1-x")
        by_id = {"1": {"country": "GEO_US"}}
        attributes.apply([row], by_id)
        self.assertEqual(row["boundary"], "US_HOLD")

    def test_no_matching_id_leaves_row_untouched(self):
        row = self._row("https://www.riparide.com/listings/999-unknown")
        summary = attributes.apply([row], {"1": {"country": "GEO_AU"}})
        self.assertEqual(row["country"], "")
        self.assertEqual(summary["rows_filled"], 0)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Unit tests for catalog.py, the stories feed merge.

The fixture uses the product field names from the client's own API sample
(get_products.json: product_id "story_774", url, category, region,
pet_friendly). The live CSV's header has not been seen from this
environment, which is why unrecognised headers must fail soft.
"""
import unittest

import catalog
import config as cfg
import fetcher
import labeller

FEED = (
    "product_id,product_type,url,title,market,city,region,category,pet_friendly,amenities\n"
    "story_774,Story,https://www.riparide.com/stories/774-immersed-in-the-rainforest,"
    "Immersed in the Rainforest,VIC,Lorne,Great Ocean Road,Tiny house,false,\"BBQ, Heating\"\n"
    "story_142,Story,https://www.riparide.com/stories/142-autumn-leaves,Autumn Leaves,"
    "VIC,Porepunkah,High Country,Cabin,true,\"Hot tub, Fireplace\"\n"
    "story_9,Story,https://www.riparide.com/stories/9-odd-one,Odd One,VIC,X,High Country,"
    "Space pod,false,\n"
)


def _story(url, **kw):
    r = labeller.label_url(url, "stories")
    r.update(kw)
    return r


class StayFromCategoryTests(unittest.TestCase):
    def test_api_wordings_map_to_facet_labels(self):
        self.assertEqual(catalog.stay_from_category("Tiny house"), "TYPE_TINY_HOUSE")
        self.assertEqual(catalog.stay_from_category("Eco house"), "TYPE_ECO_HOUSE")
        self.assertEqual(catalog.stay_from_category("A-Frame"), "TYPE_A_FRAME")
        self.assertEqual(catalog.stay_from_category("Beach house"), "TYPE_BEACH_HOUSE")

    def test_unknown_wording_is_blank_not_guessed(self):
        self.assertEqual(catalog.stay_from_category("Space pod"), "")
        self.assertEqual(catalog.stay_from_category(""), "")


class ParseTests(unittest.TestCase):
    def test_parses_api_shaped_csv(self):
        by_id, rep = catalog.parse(FEED, "VIC")
        self.assertEqual(rep["rows"], 3)
        self.assertEqual(by_id["774"]["stay"], "TYPE_TINY_HOUSE")
        self.assertEqual(by_id["774"]["region"], "REG_GREAT_OCEAN_ROAD")
        self.assertEqual((by_id["774"]["country"], by_id["774"]["state"]), ("GEO_AU", "GEO_VIC"))
        self.assertEqual(by_id["142"]["intents"], ["INT_PET_FRIENDLY", "INT_HOT_TUB"])
        self.assertNotIn("intents", by_id["774"])

    def test_unmapped_category_is_reported(self):
        by_id, rep = catalog.parse(FEED, "VIC")
        self.assertNotIn("stay", by_id["9"])
        self.assertEqual(rep["unmapped_categories"], {"Space pod": 1})

    def test_id_from_product_id_when_no_url_column(self):
        by_id, _ = catalog.parse("product_id,category\nstory_55,Cabin\n", "NSW")
        self.assertEqual(by_id["55"]["stay"], "TYPE_CABIN")
        self.assertEqual(by_id["55"]["state"], "GEO_NSW")

    def test_header_without_id_is_a_problem_not_a_crash(self):
        by_id, rep = catalog.parse("name,colour\na,b\n", "VIC")
        self.assertEqual(by_id, {})
        self.assertIn("no story url or id column", rep["problems"][0])

    def test_header_without_any_useful_column_is_a_problem(self):
        by_id, rep = catalog.parse("url,title\nhttps://www.riparide.com/stories/1-x,X\n", "VIC")
        self.assertEqual(by_id, {})
        self.assertIn("no category", rep["problems"][0])

    def test_html_block_page_is_a_problem_not_a_crash(self):
        by_id, rep = catalog.parse("<html><body>Access denied</body></html>", "VIC")
        self.assertEqual(by_id, {})
        self.assertTrue(rep["problems"])


# The live feed's exact header (GitHub runner, 19 Oct 2026), with rows shaped
# like the real ones seen there.
LIVE_HEADER = ("id,title,description,availability,condition,product_type,price,price_in_dollars,"
               "link,image_link,portrait_image_link,video_link,brand,location,additional_image_link,"
               "custom_label_0,custom_label_1,custom_label_4,sale_price,sale_price_effective_date,"
               "applink.ios_url,applink.ios_app_store_id,applink.ios_app_name")


def _live_row(sid, slug, location, labels):
    return ('story_%s,T,"A long, multi-line\ndescription, with commas",in stock,new,Story,150.0 AUD,'
            '150.0,https://www.riparide.com/stories/%s-%s,,,,Authentic explorer,"%s",,'
            'authentic_explorer,attractive,%s,,,https://www.riparide.com/stories/%s-%s,6471192765,Riparide'
            % (sid, sid, slug, location, labels, sid, slug))


LIVE_FEED = "\n".join([
    LIVE_HEADER,
    _live_row("62", "summer-heights", "Howqua, High Country, Victoria ",
              "Space Out|Cozy Cabins|Pet Friendly Escapes|Soak It Up|By the Fireside"),
    _live_row("47", "the-willows", "Anglers Rest, Victoria", "Latest Stories"),
    _live_row("111", "hidden-valley", "Grose Vale Hawkesbury, Blue Mountains, New South Wales",
              "Romantic Retreats|Outdoor Baths"),
]) + "\n"


class LiveShapeTests(unittest.TestCase):
    def setUp(self):
        self.by_id, self.rep = catalog.parse(LIVE_FEED, "VIC")

    def test_live_header_is_recognised(self):
        self.assertEqual(self.rep["problems"], [])
        self.assertEqual(self.rep["usable"], 3)
        self.assertEqual(self.rep["columns"]["collections"], "custom_label_4")
        self.assertEqual(self.rep["columns"]["url"], "link")

    def test_collections_give_intents(self):
        self.assertEqual(self.by_id["62"]["intents"], ["INT_PET_FRIENDLY", "INT_OUTDOOR_BATH"])
        self.assertEqual(self.by_id["111"]["intents"], ["INT_ROMANTIC", "INT_OUTDOOR_BATH"])
        self.assertNotIn("intents", self.by_id["47"])

    def test_region_from_three_part_location_only(self):
        self.assertEqual(self.by_id["62"]["region"], "REG_HIGH_COUNTRY")
        self.assertNotIn("region", self.by_id["47"])           # "Town, State" has no region

    def test_no_stay_type_from_this_feed(self):
        self.assertTrue(all("stay" not in r for r in self.by_id.values()))


class LoadTests(unittest.TestCase):
    def setUp(self):
        self._orig = fetcher.get

    def tearDown(self):
        fetcher.get = self._orig

    def test_fetch_failure_is_reported_and_other_markets_still_load(self):
        def fake(url, retries=None):
            if "market=NSW" in url:
                raise fetcher.FetchError("HTTP 404")
            return FEED
        fetcher.get = fake
        by_id, rep = catalog.load(log=lambda *a: None)
        self.assertIn("774", by_id)
        self.assertEqual(rep["markets"], ["VIC"])
        self.assertTrue(any("NSW: could not fetch" in p for p in rep["problems"]))

    def test_requests_the_documented_path_per_market(self):
        seen = []
        fetcher.get = lambda url, retries=None: seen.append(url) or FEED
        catalog.load(log=lambda *a: None)
        self.assertEqual(seen, [cfg.BASE + "/public_api/stories.csv?market=%s" % m
                                for m in cfg.CATALOG_MARKETS])


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.by_id, _ = catalog.parse(FEED, "VIC")

    def test_category_replaces_slug_guess_and_fills_blank(self):
        a = _story("https://www.riparide.com/stories/774-immersed-in-the-rainforest")
        self.assertEqual(a["stay"], "")
        catalog.apply([a], self.by_id, log=lambda *a: None)
        self.assertEqual(a["stay"], "TYPE_TINY_HOUSE")

    def test_location_from_page_is_kept(self):
        a = _story("https://www.riparide.com/stories/774-immersed-in-the-rainforest",
                   country="GEO_AU", state="GEO_VIC", region="REG_OTWAYS")
        catalog.apply([a], self.by_id, log=lambda *a: None)
        self.assertEqual(a["region"], "REG_OTWAYS")

    def test_location_fills_blank(self):
        a = _story("https://www.riparide.com/stories/774-immersed-in-the-rainforest")
        catalog.apply([a], self.by_id, log=lambda *a: None)
        self.assertEqual((a["country"], a["state"], a["region"]),
                         ("GEO_AU", "GEO_VIC", "REG_GREAT_OCEAN_ROAD"))

    def test_pet_friendly_story_moves_to_search_head(self):
        a = _story("https://www.riparide.com/stories/142-autumn-leaves",
                   country="GEO_AU", state="GEO_VIC")
        self.assertEqual(a["boundary"], "PMAX_LONGTAIL")
        s = catalog.apply([a], self.by_id, log=lambda *a: None)
        self.assertEqual((a["intent1"], a["intent2"]), ("INT_PET_FRIENDLY", "INT_HOT_TUB"))
        self.assertEqual(a["boundary"], "SEARCH_HEAD")
        self.assertEqual(s["now_search_head"], 1)

    def test_existing_intents_are_not_displaced(self):
        a = _story("https://www.riparide.com/stories/142-a-romantic-luxury-escape")
        self.assertEqual((a["intent1"], a["intent2"]), ("INT_ROMANTIC", "INT_LUXURY"))
        catalog.apply([a], self.by_id, log=lambda *a: None)
        self.assertEqual((a["intent1"], a["intent2"]), ("INT_ROMANTIC", "INT_LUXURY"))

    def test_story_id_never_matches_a_listing(self):
        listing = labeller.label_url("https://www.riparide.com/listings/774-some-house", "listings")
        catalog.apply([listing], self.by_id, log=lambda *a: None)
        self.assertEqual(listing["stay"], "TYPE_HOUSE")
        self.assertEqual(listing["intent1"], "")

    def test_nz_story_stays_held(self):
        a = _story("https://www.riparide.com/stories/142-autumn-leaves", country="GEO_NZ")
        catalog.apply([a], self.by_id, log=lambda *a: None)
        self.assertEqual(a["boundary"], "NZ_REVIEW")

    def test_unmatched_story_is_left_alone(self):
        a = _story("https://www.riparide.com/stories/99999-nothing")
        before = dict(a)
        s = catalog.apply([a], self.by_id, log=lambda *a: None)
        self.assertEqual(a, before)
        self.assertEqual(s["matched"], 0)


if __name__ == "__main__":
    unittest.main()

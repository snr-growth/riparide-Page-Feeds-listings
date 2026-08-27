# -*- coding: utf-8 -*-
"""Unit tests for fetcher.py's robots.txt / AdsBot parsing.

check_adsbot_access() itself is network-dependent; these tests exercise the
parsing and matching logic by monkeypatching fetcher.get so no network call
is made and the tests are deterministic regardless of where they run.
"""
import unittest

import fetcher


class ParseRobotsTests(unittest.TestCase):
    def test_single_group(self):
        text = "User-agent: *\nDisallow: /admin\n"
        groups = fetcher.parse_robots(text)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["agents"], {"*"})
        self.assertEqual(groups[0]["rules"], [("disallow", "/admin")])

    def test_multiple_user_agents_share_one_block(self):
        text = (
            "User-agent: AdsBot-Google\n"
            "User-agent: AdsBot-Google-Mobile\n"
            "Disallow: /checkout\n"
        )
        groups = fetcher.parse_robots(text)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["agents"], {"adsbot-google", "adsbot-google-mobile"})

    def test_separate_groups_when_rules_precede_next_user_agent(self):
        text = (
            "User-agent: *\n"
            "Disallow: /admin\n"
            "\n"
            "User-agent: AdsBot-Google\n"
            "Disallow: /checkout\n"
        )
        groups = fetcher.parse_robots(text)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["agents"], {"*"})
        self.assertEqual(groups[1]["agents"], {"adsbot-google"})

    def test_comments_and_blank_lines_ignored(self):
        text = "# full site robots\nUser-agent: *\n# block admin\nDisallow: /admin\n\n"
        groups = fetcher.parse_robots(text)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["rules"], [("disallow", "/admin")])

    def test_allow_rules_are_captured_too(self):
        text = "User-agent: *\nDisallow: /\nAllow: /listings\n"
        groups = fetcher.parse_robots(text)
        self.assertIn(("allow", "/listings"), groups[0]["rules"])


class CheckAdsbotAccessTests(unittest.TestCase):
    def setUp(self):
        self._real_get = fetcher.get

    def tearDown(self):
        fetcher.get = self._real_get

    def test_no_adsbot_group_is_not_a_block(self):
        fetcher.get = lambda url, retries=None: "User-agent: *\nDisallow: /admin\n"
        report = fetcher.check_adsbot_access(["/listings", "/stories"])
        self.assertTrue(report["fetched"])
        self.assertFalse(report["adsbot_group_found"])
        self.assertEqual(report["blocked"], [])

    def test_adsbot_blanket_disallow_blocks_everything(self):
        fetcher.get = lambda url, retries=None: "User-agent: AdsBot-Google\nDisallow: /\n"
        report = fetcher.check_adsbot_access(["/listings", "/stories"])
        self.assertTrue(report["adsbot_group_found"])
        self.assertEqual({p for p, d in report["blocked"]}, {"/listings", "/stories"})

    def test_adsbot_partial_disallow_only_blocks_matching_prefix(self):
        fetcher.get = lambda url, retries=None: "User-agent: AdsBot-Google\nDisallow: /stories\n"
        report = fetcher.check_adsbot_access(["/listings", "/stories"])
        blocked_paths = {p for p, d in report["blocked"]}
        self.assertEqual(blocked_paths, {"/stories"})

    def test_adsbot_explicitly_allowed_is_not_blocked(self):
        fetcher.get = lambda url, retries=None: "User-agent: AdsBot-Google\nDisallow:\n"
        report = fetcher.check_adsbot_access(["/listings"])
        self.assertEqual(report["blocked"], [])

    def test_fetch_failure_is_reported_not_raised(self):
        def boom(url, retries=None):
            raise fetcher.FetchError("simulated network failure")
        fetcher.get = boom
        report = fetcher.check_adsbot_access(["/listings"])
        self.assertFalse(report["fetched"])
        self.assertIn("simulated network failure", report["note"])


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Regression test for the bug that took down the first real
workflow_dispatch run of monthly-refresh.yml: GitHub Actions sets an unset
repository secret's env var to "" (present, empty), not absent. config.py
imported `int(os.environ.get("SMTP_PORT", "587"))`, so with SMTP_PORT
unset-as-secret-but-present-as-"" the default never fired and int("")
raised ValueError at import time, before the reachability check the run
was actually meant to test ever got a chance to run.
"""
import os
import unittest
from unittest import mock

import config


class IntEnvTests(unittest.TestCase):
    def test_missing_var_uses_default(self):
        os.environ.pop("_FEED_TEST_PORT", None)
        self.assertEqual(config._int_env("_FEED_TEST_PORT", "587"), 587)

    def test_blank_var_uses_default(self):
        # The exact GitHub Actions case: the key exists, but empty.
        with mock.patch.dict(os.environ, {"_FEED_TEST_PORT": ""}):
            self.assertEqual(config._int_env("_FEED_TEST_PORT", "587"), 587)

    def test_real_value_is_used(self):
        with mock.patch.dict(os.environ, {"_FEED_TEST_PORT": "2525"}):
            self.assertEqual(config._int_env("_FEED_TEST_PORT", "587"), 2525)


if __name__ == "__main__":
    unittest.main()

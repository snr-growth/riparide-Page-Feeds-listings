# -*- coding: utf-8 -*-
"""Unit tests for emailer.py, network fully mocked."""
import io
import unittest
import urllib.error
from unittest import mock

import config as cfg
import emailer


class SendTests(unittest.TestCase):
    def setUp(self):
        self._orig = (cfg.EMAIL_FROM, cfg.EMAIL_TO, cfg.RESEND_API_KEY,
                      cfg.SMTP_HOST, cfg.SMTP_USER, cfg.SMTP_PASSWORD)
        cfg.EMAIL_FROM = "Riparide <riparide@send.example.com>"
        cfg.EMAIL_TO = ["client@example.com"]
        cfg.RESEND_API_KEY = "re_test_key"
        cfg.SMTP_HOST = cfg.SMTP_USER = cfg.SMTP_PASSWORD = ""

    def tearDown(self):
        (cfg.EMAIL_FROM, cfg.EMAIL_TO, cfg.RESEND_API_KEY,
         cfg.SMTP_HOST, cfg.SMTP_USER, cfg.SMTP_PASSWORD) = self._orig

    def test_not_configured_reports_exactly_whats_missing(self):
        cfg.RESEND_API_KEY = ""
        sent, detail = emailer.send("subject", "body", [], log=lambda *a: None)
        self.assertFalse(sent)
        self.assertIn("RESEND_API_KEY or SMTP_HOST", detail)

    def test_resend_success(self):
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value.__enter__.return_value = mock.Mock()
            sent, detail = emailer.send("subject", "body", [], log=lambda *a: None)
        self.assertTrue(sent)
        self.assertIn("sent over the email API", detail)
        req = m.call_args[0][0]
        self.assertTrue(req.has_header("User-agent"))

    def test_resend_request_never_uses_the_default_urllib_user_agent(self):
        # Cloudflare fronts api.resend.com and blocks the default
        # "Python-urllib/3.x" signature outright (error code 1010) before
        # Resend's own app ever sees the request - reproduced against the
        # real API. A request built without an explicit User-Agent would
        # silently regress back into that block.
        with mock.patch("urllib.request.urlopen") as m:
            m.return_value.__enter__.return_value = mock.Mock()
            emailer.send("subject", "body", [], log=lambda *a: None)
        req = m.call_args[0][0]
        self.assertNotIn("urllib", req.get_header("User-agent", "").lower())

    def test_resend_failure_surfaces_the_response_body_not_just_the_status(self):
        # Reproduces a real production failure: Resend returns 403 with a
        # JSON body explaining why (e.g. an unverified sending domain), and
        # that reason is exactly what's needed to fix it - a bare "HTTP
        # Error 403: Forbidden" with the body discarded leaves no way to
        # tell what's wrong without re-reading raw run logs.
        body = b'{"statusCode":403,"message":"The riparide.com domain is not verified"}'
        err = urllib.error.HTTPError(
            url="https://api.resend.com/emails", code=403, msg="Forbidden",
            hdrs=None, fp=io.BytesIO(body))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            sent, detail = emailer.send("subject", "body", [], log=lambda *a: None)
        self.assertFalse(sent)
        self.assertIn("403", detail)
        self.assertIn("not verified", detail)


if __name__ == "__main__":
    unittest.main()

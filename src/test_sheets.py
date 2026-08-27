# -*- coding: utf-8 -*-
"""Unit tests for sheets.py.

No real network or Google credentials are used: sheets._urlopen is
monkeypatched throughout, following the same pattern test_fetcher.py uses
for fetcher.get. A throwaway RSA key (via cryptography, already a
google-auth dependency) stands in for a real service-account key so the
JWT signing path is exercised for real, not just imported.
"""
import base64
import json
import unittest
import urllib.error

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes

import config as cfg
import sheets

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM = _KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("ascii")

FAKE_SERVICE_ACCOUNT_INFO = {
    "type": "service_account",
    "project_id": "test-project",
    "private_key_id": "testkeyid123",
    "private_key": _PEM,
    "client_email": "test-svc@test-project.iam.gserviceaccount.com",
    "client_id": "12345",
}


def _b64url_json_decode(segment):
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


class FakeResponse:
    """Minimal stand-in for the object urllib.request.urlopen()'s context
    manager yields: .read() and usable via `with`."""
    def __init__(self, body, status=200):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class RecordingTransport:
    """Records every request handed to it and answers from a canned queue."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, req, timeout=30):
        self.calls.append(req)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class SignJwtTests(unittest.TestCase):
    def test_produces_a_well_formed_and_verifiable_jwt(self):
        jwt = sheets._sign_jwt(FAKE_SERVICE_ACCOUNT_INFO)
        parts = jwt.split(".")
        self.assertEqual(len(parts), 3)

        header = _b64url_json_decode(parts[0])
        claims = _b64url_json_decode(parts[1])
        self.assertEqual(header["alg"], "RS256")
        self.assertEqual(header["kid"], "testkeyid123")
        self.assertEqual(claims["iss"], FAKE_SERVICE_ACCOUNT_INFO["client_email"])
        self.assertEqual(claims["scope"], sheets.SCOPE)
        self.assertEqual(claims["aud"], sheets.TOKEN_URL)
        self.assertLess(claims["iat"], claims["exp"])

        signing_input = (parts[0] + "." + parts[1]).encode("ascii")
        signature = base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
        _KEY.public_key().verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())

    def test_tampered_signature_fails_independent_verification(self):
        jwt = sheets._sign_jwt(FAKE_SERVICE_ACCOUNT_INFO)
        parts = jwt.split(".")
        signing_input = (parts[0] + "." + parts[1]).encode("ascii")
        signature = base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
        with self.assertRaises(Exception):
            _KEY.public_key().verify(signature, signing_input + b"tampered",
                                     padding.PKCS1v15(), hashes.SHA256())


class GetAccessTokenTests(unittest.TestCase):
    def setUp(self):
        self._real = sheets._urlopen

    def tearDown(self):
        sheets._urlopen = self._real

    def test_success_returns_token(self):
        transport = RecordingTransport([FakeResponse({"access_token": "abc123", "expires_in": 3600})])
        sheets._urlopen = transport
        token = sheets._get_access_token(FAKE_SERVICE_ACCOUNT_INFO)
        self.assertEqual(token, "abc123")
        self.assertEqual(transport.calls[0].full_url, sheets.TOKEN_URL)

    def test_http_error_raises_sheets_error(self):
        err = urllib.error.HTTPError(sheets.TOKEN_URL, 400, "Bad Request", {},
                                     FakeResponse(b'{"error":"invalid_grant"}'))
        sheets._urlopen = RecordingTransport([err])
        with self.assertRaises(sheets.SheetsError):
            sheets._get_access_token(FAKE_SERVICE_ACCOUNT_INFO)


class CallTests(unittest.TestCase):
    def setUp(self):
        self._real = sheets._urlopen

    def tearDown(self):
        sheets._urlopen = self._real

    def test_retries_on_retryable_status_then_succeeds(self):
        err = urllib.error.HTTPError("https://x", 503, "Unavailable", {}, FakeResponse(b"{}"))
        sheets._urlopen = RecordingTransport([err, FakeResponse({"ok": True})])
        result = sheets._call("GET", "https://x", "tok")
        self.assertEqual(result, {"ok": True})

    def test_non_retryable_status_raises_immediately(self):
        err = urllib.error.HTTPError("https://x", 403, "Forbidden", {},
                                     FakeResponse(b'{"error":"permission denied"}'))
        transport = RecordingTransport([err])
        sheets._urlopen = transport
        with self.assertRaises(sheets.SheetsError):
            sheets._call("GET", "https://x", "tok")
        self.assertEqual(len(transport.calls), 1)

    def test_exhausts_retries_then_raises(self):
        err = urllib.error.HTTPError("https://x", 500, "Server Error", {}, FakeResponse(b"{}"))
        transport = RecordingTransport([err, err, err])
        sheets._urlopen = transport
        with self.assertRaises(sheets.SheetsError):
            sheets._call("GET", "https://x", "tok")
        self.assertEqual(len(transport.calls), sheets.RETRIES + 1)

    def test_empty_response_body_returns_empty_dict(self):
        sheets._urlopen = RecordingTransport([FakeResponse(b"")])
        self.assertEqual(sheets._call("POST", "https://x", "tok"), {})


class EnsureTabsTests(unittest.TestCase):
    def setUp(self):
        self._real = sheets._urlopen

    def tearDown(self):
        sheets._urlopen = self._real

    def test_creates_only_missing_tabs_and_pins_core_to_index_zero(self):
        get_response = FakeResponse({"sheets": [{"properties": {"title": "Sheet1", "sheetId": 0}}]})
        add_response = FakeResponse({"replies": [
            {"addSheet": {"properties": {"title": "Page Feed - Core", "sheetId": 111}}},
            {"addSheet": {"properties": {"title": "Page Feed - Adventures", "sheetId": 222}}},
        ]})
        pin_response = FakeResponse({})
        transport = RecordingTransport([get_response, add_response, pin_response])
        sheets._urlopen = transport

        sheets._ensure_tabs("SID", "tok", ["Page Feed - Core", "Page Feed - Adventures"])

        self.assertEqual(len(transport.calls), 3)
        add_body = json.loads(transport.calls[1].data.decode("utf-8"))
        added_titles = [r["addSheet"]["properties"]["title"] for r in add_body["requests"]]
        self.assertEqual(set(added_titles), {"Page Feed - Core", "Page Feed - Adventures"})

        pin_body = json.loads(transport.calls[2].data.decode("utf-8"))
        pin_req = pin_body["requests"][0]["updateSheetProperties"]
        self.assertEqual(pin_req["properties"]["sheetId"], 111)
        self.assertEqual(pin_req["properties"]["index"], 0)

    def test_existing_tabs_are_not_recreated(self):
        get_response = FakeResponse({"sheets": [
            {"properties": {"title": "Page Feed - Core", "sheetId": 5}},
            {"properties": {"title": "Page Feed - Adventures", "sheetId": 6}},
            {"properties": {"title": "Sheet1", "sheetId": 0}},
        ]})
        pin_response = FakeResponse({})
        transport = RecordingTransport([get_response, pin_response])
        sheets._urlopen = transport

        sheets._ensure_tabs("SID", "tok", ["Page Feed - Core", "Page Feed - Adventures"])

        # Only the GET and the index-pin batchUpdate - no addSheet call at all.
        self.assertEqual(len(transport.calls), 2)
        pin_body = json.loads(transport.calls[1].data.decode("utf-8"))
        self.assertEqual(pin_body["requests"][0]["updateSheetProperties"]["properties"]["sheetId"], 5)

    def test_core_already_first_is_still_explicitly_repinned(self):
        # Defensive: someone could have manually reordered tabs since last
        # run. Re-pinning every run (even when already correct) is what
        # keeps that from silently breaking Ads' ingestion.
        get_response = FakeResponse({"sheets": [
            {"properties": {"title": "Page Feed - Core", "sheetId": 5, "index": 0}},
            {"properties": {"title": "Page Feed - Adventures", "sheetId": 6, "index": 1}},
        ]})
        pin_response = FakeResponse({})
        transport = RecordingTransport([get_response, pin_response])
        sheets._urlopen = transport
        sheets._ensure_tabs("SID", "tok", ["Page Feed - Core", "Page Feed - Adventures"])
        self.assertIn("updateSheetProperties", transport.calls[1].data.decode("utf-8"))


class WriteTabTests(unittest.TestCase):
    def setUp(self):
        self._real = sheets._urlopen

    def tearDown(self):
        sheets._urlopen = self._real

    def test_clears_then_writes_header_and_rows(self):
        transport = RecordingTransport([FakeResponse({}), FakeResponse({})])
        sheets._urlopen = transport
        rows = [{"url": "https://x/1", "label": "PAGE_LISTING"},
                {"url": "https://x/2", "label": "PAGE_STORY"}]

        count = sheets._write_tab("SID", "tok", "Page Feed - Core", rows)

        self.assertEqual(count, 2)
        self.assertEqual(len(transport.calls), 2)
        self.assertTrue(transport.calls[0].full_url.endswith(":clear"))
        self.assertIn("Page%20Feed%20-%20Core", transport.calls[0].full_url)

        update_body = json.loads(transport.calls[1].data.decode("utf-8"))
        self.assertEqual(update_body["values"][0], list(cfg.CSV_HEADER))
        self.assertEqual(update_body["values"][1], ["https://x/1", "PAGE_LISTING"])
        self.assertEqual(update_body["values"][2], ["https://x/2", "PAGE_STORY"])

    def test_empty_feed_still_writes_header_only(self):
        transport = RecordingTransport([FakeResponse({}), FakeResponse({})])
        sheets._urlopen = transport
        count = sheets._write_tab("SID", "tok", "Page Feed - Adventures", [])
        self.assertEqual(count, 0)
        update_body = json.loads(transport.calls[1].data.decode("utf-8"))
        self.assertEqual(update_body["values"], [list(cfg.CSV_HEADER)])


class UpdateFeedSheetsTests(unittest.TestCase):
    def setUp(self):
        self._real_urlopen = sheets._urlopen
        self._real_json = cfg.GOOGLE_SERVICE_ACCOUNT_JSON
        self._real_id = cfg.GOOGLE_SHEETS_SPREADSHEET_ID

    def tearDown(self):
        sheets._urlopen = self._real_urlopen
        cfg.GOOGLE_SERVICE_ACCOUNT_JSON = self._real_json
        cfg.GOOGLE_SHEETS_SPREADSHEET_ID = self._real_id

    def test_not_configured_returns_cleanly_without_network(self):
        cfg.GOOGLE_SERVICE_ACCOUNT_JSON = ""
        cfg.GOOGLE_SHEETS_SPREADSHEET_ID = ""
        calls = []
        sheets._urlopen = lambda req, timeout=30: calls.append(req) or FakeResponse({})
        report = sheets.update_feed_sheets([])
        self.assertFalse(report["configured"])
        self.assertFalse(report["ok"])
        self.assertEqual(calls, [])

    def test_invalid_json_credential_is_reported_not_raised(self):
        cfg.GOOGLE_SERVICE_ACCOUNT_JSON = "{not valid json"
        cfg.GOOGLE_SHEETS_SPREADSHEET_ID = "SID"
        report = sheets.update_feed_sheets([])
        self.assertTrue(report["configured"])
        self.assertFalse(report["ok"])
        self.assertIn("not valid JSON", report["error"])

    def test_full_success_path_writes_both_tabs(self):
        cfg.GOOGLE_SERVICE_ACCOUNT_JSON = json.dumps(FAKE_SERVICE_ACCOUNT_INFO)
        cfg.GOOGLE_SHEETS_SPREADSHEET_ID = "SID"

        token_resp = FakeResponse({"access_token": "tok", "expires_in": 3600})
        get_sheets_resp = FakeResponse({"sheets": [
            {"properties": {"title": cfg.SHEET_TAB_CORE, "sheetId": 5}},
            {"properties": {"title": cfg.SHEET_TAB_ADVENTURES, "sheetId": 6}},
        ]})
        pin_resp = FakeResponse({})
        clear1, write1 = FakeResponse({}), FakeResponse({})
        clear2, write2 = FakeResponse({}), FakeResponse({})
        sheets._urlopen = RecordingTransport(
            [token_resp, get_sheets_resp, pin_resp, clear1, write1, clear2, write2])

        out_rows = [
            {"url": "https://x/1", "label": "PAGE_LISTING;PMAX_LONGTAIL", "feed": cfg.FEED_CORE},
            {"url": "https://x/2", "label": "PAGE_ADVENTURE;ADV_HOLD", "feed": cfg.FEED_ADVENTURES},
        ]
        report = sheets.update_feed_sheets(out_rows)

        self.assertTrue(report["configured"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["updated"][cfg.SHEET_TAB_CORE], 1)
        self.assertEqual(report["updated"][cfg.SHEET_TAB_ADVENTURES], 1)

    def test_api_failure_after_auth_is_reported_not_raised(self):
        cfg.GOOGLE_SERVICE_ACCOUNT_JSON = json.dumps(FAKE_SERVICE_ACCOUNT_INFO)
        cfg.GOOGLE_SHEETS_SPREADSHEET_ID = "SID"
        token_resp = FakeResponse({"access_token": "tok", "expires_in": 3600})
        err = urllib.error.HTTPError("https://x", 403, "Forbidden", {},
                                     FakeResponse(b'{"error":"The caller does not have permission"}'))
        sheets._urlopen = RecordingTransport([token_resp, err])

        report = sheets.update_feed_sheets([{"url": "https://x/1", "label": "L", "feed": cfg.FEED_CORE}])

        self.assertTrue(report["configured"])
        self.assertFalse(report["ok"])
        self.assertIn("403", report["error"])


if __name__ == "__main__":
    unittest.main()

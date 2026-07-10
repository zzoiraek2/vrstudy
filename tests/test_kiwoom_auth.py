from __future__ import annotations

import unittest
from datetime import datetime, timezone

from vrstudy.kiwoom_api import KST, KiwoomToken, is_token_valid_for_credentials
from vrstudy.kiwoom_credentials import KiwoomCredentials


class KiwoomTokenValidityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.credentials = KiwoomCredentials(
            investment_type="live",
            account_number="12345678",
            app_key="app-key",
            app_secret="app-secret",
        )

    def _token(self, expires_dt: str) -> KiwoomToken:
        return KiwoomToken(
            token="token",
            expires_dt=expires_dt,
            host="https://api.kiwoom.com",
            investment_type=self.credentials.investment_type,
            account_number=self.credentials.account_number,
        )

    def test_expired_token_is_invalid_in_kst(self) -> None:
        now = datetime(2026, 7, 10, 18, 30, tzinfo=KST)

        valid = is_token_valid_for_credentials(
            self._token("20260710182900"), self.credentials, now=now
        )

        self.assertFalse(valid)

    def test_token_inside_refresh_buffer_is_invalid(self) -> None:
        now = datetime(2026, 7, 10, 18, 30, tzinfo=KST)

        valid = is_token_valid_for_credentials(
            self._token("20260710183900"), self.credentials, now=now
        )

        self.assertFalse(valid)

    def test_future_token_outside_refresh_buffer_is_valid(self) -> None:
        now = datetime(2026, 7, 10, 18, 30, tzinfo=KST)

        valid = is_token_valid_for_credentials(
            self._token("20260710190000"), self.credentials, now=now
        )

        self.assertTrue(valid)

    def test_naive_now_is_treated_as_kst(self) -> None:
        now = datetime(2026, 7, 10, 18, 30)

        valid = is_token_valid_for_credentials(
            self._token("20260710190000"), self.credentials, now=now
        )

        self.assertTrue(valid)

    def test_aware_iso_expiry_is_compared_in_kst(self) -> None:
        now = datetime(2026, 7, 10, 18, 30, tzinfo=KST)
        expiry_utc = datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc)

        valid = is_token_valid_for_credentials(
            self._token(expiry_utc.isoformat()), self.credentials, now=now
        )

        self.assertTrue(valid)


if __name__ == "__main__":
    unittest.main()

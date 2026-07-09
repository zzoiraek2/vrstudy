from __future__ import annotations

import json
import os
import tempfile
import unittest

from vrstudy_web.accounts import (
    authenticate,
    authenticate_remember_token,
    change_password,
    issue_remember_token,
    users_path,
)
from vrstudy_web.security import hash_password


class AccountSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_data_dir = os.environ.get("VRSTUDY_DATA_DIR")
        os.environ["VRSTUDY_DATA_DIR"] = self.temp_dir.name
        records = {
            "users": [
                {
                    "username": "testuser",
                    "password_hash": hash_password("old-password"),
                    "role": "user",
                }
            ]
        }
        path = users_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(records), encoding="utf-8")

    def tearDown(self) -> None:
        if self.previous_data_dir is None:
            os.environ.pop("VRSTUDY_DATA_DIR", None)
        else:
            os.environ["VRSTUDY_DATA_DIR"] = self.previous_data_dir
        self.temp_dir.cleanup()

    def test_change_password_revokes_remember_token(self) -> None:
        remember_cookie = issue_remember_token("testuser")

        self.assertIsNotNone(remember_cookie)
        self.assertIsNotNone(authenticate_remember_token(remember_cookie))
        self.assertTrue(change_password("testuser", "old-password", "new-password"))
        self.assertIsNone(authenticate("testuser", "old-password"))
        self.assertIsNotNone(authenticate("testuser", "new-password"))
        self.assertIsNone(authenticate_remember_token(remember_cookie))

    def test_change_password_rejects_wrong_current_password(self) -> None:
        self.assertFalse(change_password("testuser", "wrong-password", "new-password"))
        self.assertIsNotNone(authenticate("testuser", "old-password"))
        self.assertIsNone(authenticate("testuser", "new-password"))


if __name__ == "__main__":
    unittest.main()

import unittest

from vrstudy_web.data import _filter_vr_sell_order_rows, _vr_match_buy_order_count


def _row(side: str, level_no: int) -> dict:
    return {
        "side": side,
        "level_no": level_no,
        "quantity": 4,
        "price": float(level_no),
    }


class VrOrderRowsTest(unittest.TestCase):
    def test_match_buy_limits_sell_rows_to_buy_row_count(self):
        rows = [_row("buy", index) for index in range(1, 4)]
        rows.extend(_row("sell", index) for index in range(1, 8))

        filtered = _filter_vr_sell_order_rows(rows, "match_buy", None)

        self.assertEqual([row["side"] for row in filtered], ["buy"] * 3 + ["sell"] * 3)
        self.assertEqual([row["level_no"] for row in filtered if row["side"] == "sell"], [1, 2, 3])

    def test_manual_sell_row_count_caps_at_available_sells(self):
        rows = [_row("buy", index) for index in range(1, 3)]
        rows.extend(_row("sell", index) for index in range(1, 5))

        filtered = _filter_vr_sell_order_rows(rows, "manual", 99)

        self.assertEqual(len([row for row in filtered if row["side"] == "buy"]), 2)
        self.assertEqual(len([row for row in filtered if row["side"] == "sell"]), 4)

    def test_match_buy_expected_count_accepts_uppercase_level_rows(self):
        rows = [_row("BUY", index) for index in range(1, 5)]
        rows.extend(_row("SELL", index) for index in range(1, 20))

        self.assertEqual(_vr_match_buy_order_count(rows), 8)


if __name__ == "__main__":
    unittest.main()

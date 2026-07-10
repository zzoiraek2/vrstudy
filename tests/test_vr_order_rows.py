import unittest
from datetime import date, datetime

import duckdb

from vrstudy_web import data
from vrstudy_web.data import (
    _build_vr_period_preview,
    _filter_vr_sell_order_rows,
    _summarize_vr_dividends,
    _vr_match_buy_order_count,
)


def _row(side: str, level_no: int) -> dict:
    return {
        "side": side,
        "level_no": level_no,
        "quantity": 4,
        "price": float(level_no),
    }


def _api_order(symbol: str, side: str, qty: int, price: float = 10.0) -> dict:
    return {
        "stk_cd": symbol,
        "slby_tp": "2" if side == "buy" else "1",
        "cntr_qty": f"{qty:012d}",
        "cntr_uv": f"{price:.4f}",
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

    def test_vr_period_preview_projects_from_latest_result_holding(self):
        preview = _build_vr_period_preview(
            "TQQQ",
            {"result_list": []},
            {"result_list": [{"stk_cd": "TQQQ", "poss_qty": "000000000065"}]},
            {"result_list": [_api_order("TQQQ", "buy", 2)]},
            65,
        )

        self.assertEqual(preview["base_holding_qty"], 65)
        self.assertEqual(preview["buy_qty"], 2)
        self.assertEqual(preview["sell_qty"], 0)
        self.assertEqual(preview["period_end_holding_qty"], 67)

    def test_vr_dividend_summary_uses_foreign_settlement_amount(self):
        summary = _summarize_vr_dividends(
            [
                {"stk_cd": "TQQQ", "deal_dt": "20260701", "fc_exct_amt": "1.25", "crnc_code": "USD"},
                {"stk_cd": "SOXL", "deal_dt": "20260701", "fc_exct_amt": "99.00", "crnc_code": "USD"},
            ],
            "TQQQ",
        )

        self.assertEqual(summary["status"], "applied")
        self.assertEqual(summary["amount"], 1.25)
        self.assertEqual(len(summary["rows"]), 1)

    def test_order_execution_record_uses_kst_now(self):
        con = duckdb.connect(":memory:")
        fixed_now = datetime(2026, 7, 10, 18, 30, 21)
        old_now = data._kst_now_naive
        data._kst_now_naive = lambda: fixed_now
        try:
            data._record_order_execution(
                con,
                "vr",
                "VR-SOXL",
                date(2026, 7, 10),
                {
                    "symbol": "SOXL",
                    "side": "buy",
                    "side_label": "매수",
                    "order_type": "지정가",
                    "price": 63.48,
                    "quantity": 1,
                    "stex_tp": "NA",
                    "trde_tp": "00",
                },
                "sent",
                {"ord_no": "000015393"},
                "test",
            )
            row = con.execute("SELECT created_at FROM web_order_executions").fetchone()
        finally:
            data._kst_now_naive = old_now
            con.close()

        self.assertEqual(row[0], fixed_now)


if __name__ == "__main__":
    unittest.main()

import unittest

from vrstudy.telegram import TelegramSettings
from vrstudy_web import data


class ScheduleTelegramTest(unittest.TestCase):
    def test_schedule_attempts_remaining_today(self):
        schedule = {"last_attempt_date": data._schedule_today()}

        self.assertEqual(data._with_schedule_runtime_fields(schedule)["today_attempts_remaining"], 0)
        self.assertEqual(data._with_schedule_runtime_fields({})["today_attempts_remaining"], 1)

    def test_structured_order_result_telegram_sections(self):
        captured: list[str] = []
        old_load = data.load_telegram_settings
        old_send = data.send_telegram_message
        data.load_telegram_settings = lambda path: TelegramSettings(
            bot_token="token",
            chat_id="chat",
            send_api_order_result=True,
        )
        data.send_telegram_message = lambda settings, text: captured.append(text) or {"ok": True}
        try:
            result = {
                "ok": False,
                "order_datetime": "2026-07-09 15:55:02",
                "order_plan_result": {
                    "status": "success",
                    "buy_count": 10,
                    "sell_count": 2,
                },
                "order_attempt_result": {
                    "status": "failed",
                    "message": "키움 주문 거절",
                },
                "order_executions": [],
            }

            data._send_api_order_result_telegram("user", "infinite", "profile", result)
        finally:
            data.load_telegram_settings = old_load
            data.send_telegram_message = old_send

        self.assertTrue(captured)
        self.assertIn("1. 주문표 생성 결과: 성공", captured[0])
        self.assertIn("- 매수 10건, 매도 2건", captured[0])
        self.assertIn("2. 주문시도결과: 실패", captured[0])
        self.assertIn("- 키움 주문 거절", captured[0])


if __name__ == "__main__":
    unittest.main()

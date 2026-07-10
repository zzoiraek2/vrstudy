import unittest
from datetime import datetime, timedelta, timezone

from vrstudy.telegram import TelegramSettings
from vrstudy_web import data


class ScheduleTelegramTest(unittest.TestCase):
    def test_schedule_attempts_remaining_today(self):
        schedule = {"last_attempt_date": data._schedule_today()}

        self.assertEqual(data._with_schedule_runtime_fields(schedule)["today_attempts_remaining"], 0)
        self.assertEqual(data._with_schedule_runtime_fields({})["today_attempts_remaining"], 1)

    def test_schedule_due_state_catches_up_only_within_window(self):
        kst = timezone(timedelta(hours=9))
        schedule = {"time": "15:55"}

        self.assertEqual(
            data._schedule_due_state(schedule, datetime(2026, 7, 9, 15, 54, tzinfo=kst))["status"],
            "pending",
        )
        self.assertEqual(
            data._schedule_due_state(schedule, datetime(2026, 7, 9, 16, 10, tzinfo=kst))["status"],
            "due",
        )
        self.assertEqual(
            data._schedule_due_state(schedule, datetime(2026, 7, 9, 17, 1, tzinfo=kst))["status"],
            "missed",
        )

    def test_vr_schedule_missed_marks_without_order_execution(self):
        kst = timezone(timedelta(hours=9))
        saved: list[dict] = []
        sent: list[str] = []
        executed: list[str] = []
        old_profiles = data.vr_profiles
        old_read = data._read_vr_schedule
        old_write = data._write_vr_schedule
        old_execute = data.execute_vr_web_orders
        old_load = data.load_telegram_settings
        old_send = data.send_telegram_message
        data.vr_profiles = lambda username: [{"name": "VR-SOXL"}]
        data._read_vr_schedule = lambda username, profile_name: {
            "enabled": True,
            "time": "15:55",
            "weekdays": [3],
            "last_attempt_date": "",
        }
        data._write_vr_schedule = lambda username, profile_name, schedule: saved.append(dict(schedule)) or dict(schedule)
        data.execute_vr_web_orders = lambda username, profile_name: executed.append(profile_name) or {"ok": True}
        data.load_telegram_settings = lambda path: TelegramSettings(bot_token="token", chat_id="chat")
        data.send_telegram_message = lambda settings, text: sent.append(text) or {"ok": True}
        try:
            result = data.run_due_vr_schedules(
                ["user"],
                datetime(2026, 7, 9, 17, 1, tzinfo=kst),
            )
        finally:
            data.vr_profiles = old_profiles
            data._read_vr_schedule = old_read
            data._write_vr_schedule = old_write
            data.execute_vr_web_orders = old_execute
            data.load_telegram_settings = old_load
            data.send_telegram_message = old_send

        self.assertFalse(executed)
        self.assertTrue(result)
        self.assertTrue(result[0]["missed"])
        self.assertEqual(saved[-1]["last_status"], "missed")
        self.assertTrue(sent)
        self.assertIn("VR-SOXL", sent[0])

    def test_vr_schedule_generate_mode_uses_generate_workflow(self):
        kst = timezone(timedelta(hours=9))
        executed: list[str] = []
        generated: list[str] = []
        old_profiles = data.vr_profiles
        old_read = data._read_vr_schedule
        old_write = data._write_vr_schedule
        old_execute = data.execute_vr_web_orders
        old_generate = data.execute_vr_schedule_generate_and_orders
        data.vr_profiles = lambda username: [{"name": "VR-SOXL"}]
        data._read_vr_schedule = lambda username, profile_name: {
            "enabled": True,
            "time": "15:55",
            "mode": "generate_and_orders",
            "weekdays": [3],
            "last_attempt_date": "",
        }
        data._write_vr_schedule = lambda username, profile_name, schedule: dict(schedule)
        data.execute_vr_web_orders = lambda username, profile_name: executed.append(profile_name) or {"ok": True}
        data.execute_vr_schedule_generate_and_orders = (
            lambda username, profile_name: generated.append(profile_name) or {"ok": True}
        )
        try:
            result = data.run_due_vr_schedules(
                ["user"],
                datetime(2026, 7, 9, 16, 10, tzinfo=kst),
            )
        finally:
            data.vr_profiles = old_profiles
            data._read_vr_schedule = old_read
            data._write_vr_schedule = old_write
            data.execute_vr_web_orders = old_execute
            data.execute_vr_schedule_generate_and_orders = old_generate

        self.assertFalse(executed)
        self.assertEqual(generated, ["VR-SOXL"])
        self.assertTrue(result[0]["ok"])
        self.assertEqual(result[0]["schedule_mode"], "generate_and_orders")

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
                "order_datetime": "2026-07-09T15:55:02+09:00",
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
        self.assertIn("2026-07-09 15:55:02", captured[0])
        self.assertNotIn("2026-07-09T15:55:02+09:00", captured[0])
        self.assertIn("1. 주문표 생성 결과: 성공", captured[0])
        self.assertIn("- 매수 10건, 매도 2건", captured[0])
        self.assertIn("2. 주문시도결과: 실패", captured[0])
        self.assertIn("- 키움 주문 거절", captured[0])


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from vrstudy.telegram import TelegramSettings
from vrstudy_web.app import VrScheduleRequest
from vrstudy_web import data


class ScheduleTelegramTest(unittest.TestCase):
    def test_schedule_attempts_remaining_today(self):
        schedule = {"last_attempt_date": data._schedule_today()}

        self.assertEqual(data._with_schedule_runtime_fields(schedule)["today_attempts_remaining"], 0)
        self.assertEqual(data._with_schedule_runtime_fields({})["today_attempts_remaining"], 1)

    def test_vr_schedule_request_preserves_mode(self):
        payload = VrScheduleRequest(
            enabled=True,
            time="15:55",
            mode="generate_and_orders",
            weekdays=[0, 1, 2],
        )

        self.assertEqual(payload.model_dump()["mode"], "generate_and_orders")

    def test_vr_schedule_accepts_generate_only_mode(self):
        payload = VrScheduleRequest(
            enabled=True,
            time="15:55",
            mode="generate_only",
            weekdays=[0, 1, 2],
        )

        self.assertEqual(payload.model_dump()["mode"], "generate_only")
        self.assertEqual(data._validate_vr_schedule_mode("generate_only"), "generate_only")

    def test_vr_schedule_accepts_generate_or_orders_mode(self):
        payload = VrScheduleRequest(
            enabled=True,
            time="15:55",
            mode="generate_or_orders",
            weekdays=[0, 1, 2],
        )

        self.assertEqual(payload.model_dump()["mode"], "generate_or_orders")
        self.assertEqual(
            data._validate_vr_schedule_mode("generate_or_orders"),
            "generate_or_orders",
        )

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

    def test_saving_past_schedule_time_skips_today(self):
        kst = timezone(timedelta(hours=9))
        schedule = {
            "enabled": True,
            "time": "09:30",
            "weekdays": [3],
            "last_attempt_date": "",
        }

        self.assertTrue(
            data._schedule_saved_after_today_time(
                schedule,
                datetime(2026, 7, 9, 17, 1, tzinfo=kst),
            )
        )
        saved = data._mark_schedule_saved_for_next_run(
            schedule,
            datetime(2026, 7, 9, 17, 1, tzinfo=kst),
        )

        self.assertEqual(saved["last_attempt_date"], "2026-07-09")
        self.assertEqual(saved["last_status"], "saved")
        self.assertIn("다음 실행일", saved["last_message"])

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

    def test_vr_schedule_generate_only_does_not_execute_orders(self):
        kst = timezone(timedelta(hours=9))
        executed: list[str] = []
        generated: list[str] = []
        old_profiles = data.vr_profiles
        old_read = data._read_vr_schedule
        old_write = data._write_vr_schedule
        old_execute = data.execute_vr_web_orders
        old_generate = data.execute_vr_schedule_generate_only
        data.vr_profiles = lambda username: [{"name": "VR-TQQQ"}]
        data._read_vr_schedule = lambda username, profile_name: {
            "enabled": True,
            "time": "15:55",
            "mode": "generate_only",
            "weekdays": [3],
            "last_attempt_date": "",
        }
        data._write_vr_schedule = lambda username, profile_name, schedule: dict(schedule)
        data.execute_vr_web_orders = (
            lambda username, profile_name: executed.append(profile_name) or {"ok": True}
        )
        data.execute_vr_schedule_generate_only = (
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
            data.execute_vr_schedule_generate_only = old_generate

        self.assertFalse(executed)
        self.assertEqual(generated, ["VR-TQQQ"])
        self.assertTrue(result[0]["ok"])
        self.assertEqual(result[0]["schedule_mode"], "generate_only")

    def test_vr_generate_or_orders_runs_exactly_one_action(self):
        profile = SimpleNamespace(name="VR-TQQQ")
        for has_current_basis, expected_action in (
            (False, "generate_only"),
            (True, "orders_only"),
        ):
            generated: list[str] = []
            executed: list[str] = []
            with self.subTest(has_current_basis=has_current_basis):
                with (
                    patch.object(data, "_read_profile_file", return_value={}),
                    patch.object(data, "_profile_from_data", return_value=profile),
                    patch.object(data, "_vr_order_basis_for_today", return_value={}),
                    patch.object(
                        data,
                        "_vr_basis_covers_day",
                        return_value=has_current_basis,
                    ),
                    patch.object(
                        data,
                        "execute_vr_schedule_generate_only",
                        side_effect=lambda username, profile_name: generated.append(profile_name)
                        or {"ok": True},
                    ),
                    patch.object(
                        data,
                        "execute_vr_web_orders",
                        side_effect=lambda username, profile_name: executed.append(profile_name)
                        or {"ok": True},
                    ),
                ):
                    result = data.execute_vr_schedule_generate_or_orders(
                        "user", "VR-TQQQ"
                    )

                self.assertEqual(result["schedule_mode"], "generate_or_orders")
                self.assertEqual(result["schedule_action"], expected_action)
                self.assertEqual(len(generated) + len(executed), 1)
                self.assertEqual(bool(generated), not has_current_basis)
                self.assertEqual(bool(executed), has_current_basis)

    def test_vr_schedule_dispatches_generate_or_orders_mode(self):
        kst = timezone(timedelta(hours=9))
        called: list[str] = []
        with (
            patch.object(data, "vr_profiles", return_value=[{"name": "VR-TQQQ"}]),
            patch.object(
                data,
                "_read_vr_schedule",
                return_value={
                    "enabled": True,
                    "time": "15:55",
                    "mode": "generate_or_orders",
                    "weekdays": [3],
                    "last_attempt_date": "",
                },
            ),
            patch.object(data, "_write_vr_schedule", side_effect=lambda *args: dict(args[-1])),
            patch.object(
                data,
                "execute_vr_schedule_generate_or_orders",
                side_effect=lambda username, profile_name: called.append(profile_name)
                or {"ok": True, "schedule_action": "generate_only"},
            ),
        ):
            result = data.run_due_vr_schedules(
                ["user"],
                datetime(2026, 7, 9, 16, 10, tzinfo=kst),
            )

        self.assertEqual(called, ["VR-TQQQ"])
        self.assertEqual(result[0]["schedule_mode"], "generate_or_orders")
        self.assertEqual(result[0]["schedule_action"], "generate_only")

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

    def test_vr_order_result_telegram_includes_fills_before_order_result(self):
        captured: list[str] = []
        old_load = data.load_telegram_settings
        old_send = data.send_telegram_message
        data.load_telegram_settings = lambda path: TelegramSettings(
            bot_token="token",
            chat_id="chat",
            send_api_order_result=True,
            order_row_limit=2,
        )
        data.send_telegram_message = lambda settings, text: captured.append(text) or {"ok": True}
        try:
            result = {
                "ok": True,
                "schedule_mode": "generate_and_orders",
                "order_datetime": "2026-07-20T15:55:02+09:00",
                "order_plan_result": {
                    "status": "success",
                    "message": "주문표 생성 완료",
                },
                "dividend_result": {
                    "status": "success",
                    "amount": 12.34,
                    "message": "12.34 USD",
                },
                "fills": [
                    {
                        "display_date": "2026-07-17",
                        "side": "buy",
                        "side_label": "매수",
                        "price": 55.25,
                        "quantity": 2,
                    },
                    {
                        "display_date": "2026-07-18",
                        "side": "sell",
                        "side_label": "매도",
                        "price": 61.5,
                        "quantity": 1,
                    },
                    {
                        "display_date": "2026-07-19",
                        "side": "buy",
                        "side_label": "매수",
                        "price": 54.0,
                        "quantity": 3,
                    },
                ],
                "deducted": [
                    {
                        "side": "buy",
                        "price": 55.25,
                        "quantity": 2,
                        "deducted_quantity": 2,
                    },
                    {
                        "side": "sell",
                        "price": 61.5,
                        "quantity": 1,
                        "deducted_quantity": 1,
                    },
                ],
                "order_attempt_result": {
                    "status": "success",
                    "message": "VR 주문실행 완료",
                },
                "order_executions": [],
            }

            data._send_api_order_result_telegram("user", "vr", "VR-TQQQ", result)
        finally:
            data.load_telegram_settings = old_load
            data.send_telegram_message = old_send

        self.assertTrue(captured)
        message = captured[0]
        section_titles = [
            "1. 주문표 생성: 성공",
            "2. 배당금: 12.34 USD",
            "3. 체결내역: 3건",
            "4. 주문결과: 성공",
        ]
        positions = [message.index(title) for title in section_titles]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("- 체결요약: 매수 2건/5주, 매도 1건/1주", message)
        self.assertIn("- 2026-07-17 매수 55.25 / 2주", message)
        self.assertIn("- 체결내역 외 1건", message)
        self.assertIn("- 주문차감: 매수 1건/2주, 매도 1건/1주", message)

    def test_vr_orders_only_telegram_uses_four_sections_without_fills(self):
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
            data._send_api_order_result_telegram(
                "user",
                "vr",
                "VR-TQQQ",
                {
                    "ok": True,
                    "message": "기존 주문표 주문실행 완료",
                    "fills": [],
                    "deducted": [],
                    "order_executions": [],
                },
            )
        finally:
            data.load_telegram_settings = old_load
            data.send_telegram_message = old_send

        self.assertTrue(captured)
        message = captured[0]
        self.assertIn("1. 주문표 생성: 미실시", message)
        self.assertIn("2. 배당금: 해당없음", message)
        self.assertIn("3. 체결내역: 없음", message)
        self.assertIn("- 주문차감: 없음", message)
        self.assertIn("4. 주문결과: 성공", message)


if __name__ == "__main__":
    unittest.main()

import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from helpers import config, config_data
from xiaogpt_voice.cli import main
from xiaogpt_voice.config import AppConfig, prepare_voice, save_config
from xiaogpt_voice.setup import initialize, select_device


class SettingsTests(unittest.TestCase):
    def test_secret_fields_are_not_in_config_repr(self):
        value = repr(config())
        self.assertNotIn("test-key-not-real", value)
        self.assertNotIn("own-test-account", value)

    def test_unknown_hardware_requires_explicit_actions(self):
        data = config_data()
        data["device"]["hardware"] = "CUSTOM"
        with self.assertRaises(ValueError):
            AppConfig.from_dict(data)
        data["device"].update(text_action=[7, 3], wake_action=[7, 4])
        self.assertEqual(AppConfig.from_dict(data).device.wake_action, (7, 4))

    def test_invalid_actions_intervals_or_provider_are_rejected(self):
        for update in ({"poll_interval_seconds": 0.01}, {"deepseek": {"api_key": "test", "base_url": "https://example.com"}},
                       {"voice": {"trigger_words": []}}, {"schema_version": 1}):
            data = config_data()
            data.update(update)
            with self.assertRaises(ValueError):
                AppConfig.from_dict(data)

    def test_files_preserve_user_prompt_and_replacement_has_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            voice = prepare_voice(root)
            (voice / "system_prompt.txt").write_text("自己的提示词", encoding="utf-8")
            prepare_voice(root)
            self.assertEqual((voice / "system_prompt.txt").read_text(encoding="utf-8"), "自己的提示词")
            data = config_data()
            save_config(root, data)
            with self.assertRaises(ValueError):
                save_config(root, data)
            data["device"]["name"] = "new name"
            save_config(root, data, replace=True)
            backups = list((root / "backups").glob("*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text())["device"]["name"], "音箱")

    def test_doctor_checks_without_exposing_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            save_config(root, config_data())
            (root / ".mi.token").write_text(json.dumps({"userId": "test", "deviceId": "test", "passToken": "test"}))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(["--data-dir", str(root), "doctor"])
            self.assertEqual(status, 0)
            self.assertNotIn("test-key-not-real", output.getvalue())
            self.assertNotIn("own-test-account", output.getvalue())


class SetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_setup_uses_own_device_and_never_saves_password(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            answers = iter(["new-user", "test-city"])
            secrets = iter(["private-password", "test-key"])

            async def discovery(root, account, password, otp):
                self.assertEqual((account, password), ("new-user", "private-password"))
                (root / ".mi.token").write_text(json.dumps({"userId": "own-user"}))
                return "own-user", [{"hardware": "S12A", "miotDID": "own-speaker"}]

            class Assistant:
                last_search_status, last_error = "ok", None

                def __init__(self, key, root):
                    self.key = key

                async def ask(self, text):
                    return "联网成功"

            await initialize(root, read=lambda _: next(answers), secret=lambda _: next(secrets),
                             discovery=discovery, assistant_class=Assistant)
            raw = (root / "config.json").read_text()
            data = json.loads(raw)
            self.assertNotIn("private-password", raw)
            self.assertEqual(data["device"]["miot_did"], "own-speaker")
            self.assertEqual(data["xiaomi"]["account"], "own-user")
            self.assertEqual(AppConfig.load(root).api_key, "test-key")

    async def test_failed_search_does_not_save_runnable_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            answers = iter(["user", ""])
            secrets = iter(["password", "test-key"])

            async def discovery(*args):
                return "user", [{"hardware": "S12A", "miotDID": "speaker"}]

            class Assistant:
                last_search_status, last_error = "failed", "HTTP_402"

                def __init__(self, *args, **kwargs):
                    pass

                async def ask(self, text):
                    return "余额不足"

            with self.assertRaises(ValueError):
                await initialize(root, read=lambda _: next(answers), secret=lambda _: next(secrets),
                                 discovery=discovery, assistant_class=Assistant)
            self.assertFalse((root / "config.json").exists())

    async def test_device_selection_handles_invalid_input_and_missing_device(self):
        with self.assertRaises(ValueError):
            select_device([])
        devices = [{"hardware": "S12A", "miotDID": "one"}, {"hardware": "S12A", "miotDID": "two"}]
        answers = iter(["invalid", "3", "2"])
        self.assertEqual(select_device(devices, lambda _: next(answers))["miot_did"], "two")

    async def test_existing_config_requires_explicit_replace(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            save_config(root, config_data())
            with self.assertRaises(ValueError):
                await initialize(root)

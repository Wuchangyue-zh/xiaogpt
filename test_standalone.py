"""First-run tests use temporary directories and fake login/search, no real keys."""
import asyncio
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import configure
import smart_deepseek


class WizardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_fresh_setup_discovers_own_device_and_saves_no_password(self):
        answers = iter(["new-user", "测试城市"])
        secrets = iter(["not-a-real-password", "not-a-real-api-key"])
        observed = []

        async def discover(root, user, password, otp):
            observed.append((user, password))
            (root / ".mi.token").write_text(json.dumps({"userId": "new-user-id"}))
            return "new-user-id", [{"name": "我的音箱", "hardware": "S12A", "miotDID": "fake-device-1"}]

        class Bot:
            last_error = None
            last_search_status = "ok"

            def __init__(self, config, root):
                self.config = config

            async def ask(self, query):
                return "搜索与回答成功"

        await configure.configure(self.root, read=lambda _: next(answers), secret=lambda _: next(secrets),
                                  discover=discover, bot_class=Bot)
        saved = json.loads((self.root / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["account"], "new-user-id")
        self.assertEqual(saved["mi_did"], "fake-device-1")
        self.assertEqual(saved["hardware"], "S12A")
        self.assertEqual(saved["openai_key"], "not-a-real-api-key")
        self.assertNotIn("password", saved)
        self.assertNotIn("not-a-real-password", json.dumps(saved))
        self.assertEqual(observed, [("new-user", "not-a-real-password")])
        self.assertTrue((self.root / ".mi.token").exists())
        self.assertEqual(json.loads((self.root / "smart_voice/smart_voice.json").read_text())["home_city"], "测试城市")

    async def test_failed_search_does_not_save_runnable_config(self):
        answers = iter(["user", ""])
        secrets = iter(["password-test", "key-test"])

        async def discover(*args):
            return "user", [{"hardware": "S12A", "miotDID": "fake-device"}]

        class Bot:
            last_error = "HTTP_402"
            last_search_status = "failed"

            def __init__(self, *args, **kwargs):
                pass

            async def ask(self, query):
                return "余额不足"

        with self.assertRaises(ValueError):
            await configure.configure(self.root, read=lambda _: next(answers), secret=lambda _: next(secrets),
                                      discover=discover, bot_class=Bot)
        self.assertFalse((self.root / "config.json").exists())

    async def test_existing_config_not_overwritten_without_explicit_flag(self):
        (self.root / "config.json").write_text('{"existing": true}')
        with self.assertRaises(FileExistsError):
            await configure.configure(self.root)
        self.assertEqual(json.loads((self.root / "config.json").read_text()), {"existing": True})

    async def test_reconfigure_backs_up_existing_config(self):
        old = {"account": "previous-user", "openai_key": "previous-test-key"}
        (self.root / "config.json").write_text(json.dumps(old))
        configure.save_config(self.root, {"new": True}, reconfigure=True)
        backups = list((self.root / "backups").glob("*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text()), old)

    async def test_multiple_devices_require_selection_and_keep_own_did(self):
        devices = [{"name": "one", "hardware": "S12A", "miotDID": "own-one"},
                   {"name": "two", "hardware": "LX06", "miotDID": "own-two"}]
        replies = iter(["invalid", "3", "2"])
        self.assertEqual(configure.select_device(devices, read=lambda _: next(replies)), ("LX06", "own-two"))

    async def test_no_devices_or_missing_id_is_actionable(self):
        for devices in ([], [{"hardware": "S12A"}]):
            with self.assertRaises(ValueError):
                configure.select_device(devices)

    async def test_settings_user_edits_survive_repeated_prepare(self):
        voice = configure.prepare_voice_files(self.root)
        (voice / "voice_prompt.txt").write_text("自己的提示词", encoding="utf-8")
        configure.prepare_voice_files(self.root)
        self.assertEqual((voice / "voice_prompt.txt").read_text(encoding="utf-8"), "自己的提示词")

    async def test_adapter_uses_persistent_voice_directory(self):
        voice = configure.prepare_voice_files(self.root)
        cfg = types.SimpleNamespace(openai_key="test-key", api_base="https://api.deepseek.com", proxy=None)
        with patch.dict(os.environ, {"XIAOGPT_SMART_ROOT": str(voice)}):
            bot = smart_deepseek.SmartDeepSeekBot.from_config(cfg)
        self.assertEqual(bot.root, voice)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_standalone_applies_direct_wake_and_cooldown_once(self):
        class Original:
            @classmethod
            def from_config(cls, config):
                return "original"

        class MiGPT:
            async def ask_gpt(self, query):
                yield "original"

            async def speak(self, source):
                pass

            async def wakeup_xiaoai(self):
                return "legacy-wake"

            def _get_last_query(self, data):
                return data

            async def stop_if_xiaoai_is_playing(self):
                return None

            async def do_tts(self, text):
                return None

        bots = types.ModuleType("xiaogpt.bot")
        bots.BOTS = {"chatgptapi": Original}
        core = types.ModuleType("xiaogpt.xiaogpt")
        core.MiGPT = MiGPT
        miio = types.ModuleType("miservice.miioservice")
        account = types.ModuleType("miservice.miaccount")
        account.UA_LOGIN = "new-client"
        import sys
        import runtime
        modules = {"xiaogpt": types.ModuleType("xiaogpt"), "xiaogpt.bot": bots, "xiaogpt.xiaogpt": core,
                   "miservice": types.ModuleType("miservice"), "miservice.miioservice": miio, "miservice.miaccount": account}
        with patch.dict(sys.modules, modules):
            runtime.install_compatibility()
            first = MiGPT.wakeup_xiaoai
            runtime.install_compatibility()
            self.assertIs(first, MiGPT.wakeup_xiaoai)
        self.assertEqual(miio.UA_MIIO, "new-client")
        obj = MiGPT()
        obj.chatbot = object()
        obj.config = types.SimpleNamespace(hardware="S12A", mi_did="own-test-device")
        obj.miio_service = types.SimpleNamespace(miot_action=AsyncMock(return_value=0))
        obj.in_conversation = True
        obj.log = Mock()
        self.assertEqual(await obj.wakeup_xiaoai(), 0)
        obj.miio_service.miot_action.assert_awaited_once_with("own-test-device", (5, 3), [])
        obj.miio_service.miot_action.return_value = -127
        self.assertFalse(await obj.wakeup_xiaoai())
        self.assertFalse(obj.in_conversation)
        calls = obj.miio_service.miot_action.await_count
        self.assertFalse(await obj.wakeup_xiaoai())
        self.assertEqual(obj.miio_service.miot_action.await_count, calls)

    async def test_official_provider_routing_keeps_non_deepseek_credentials_on_original_provider(self):
        class Original:
            @classmethod
            def from_config(cls, config):
                return "original-provider"

        class MiGPT:
            async def ask_gpt(self, query):
                yield "original"

            async def speak(self, source):
                pass

            async def wakeup_xiaoai(self):
                return 0

        bots = types.ModuleType("xiaogpt.bot")
        bots.BOTS = {"chatgptapi": Original}
        core = types.ModuleType("xiaogpt.xiaogpt")
        core.MiGPT = MiGPT
        import sys
        with patch.dict(sys.modules, {"xiaogpt": types.ModuleType("xiaogpt"), "xiaogpt.bot": bots, "xiaogpt.xiaogpt": core}):
            smart_deepseek.install(official_only=True)
        cls = bots.BOTS["chatgptapi"]
        self.assertEqual(cls.from_config(types.SimpleNamespace(api_base=None)), "original-provider")
        self.assertEqual(cls.from_config(types.SimpleNamespace(api_base="https://example.com/v1")), "original-provider")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Protocol/interrupt/install tests. No real credentials or network calls."""
import asyncio
import copy
import json
import shutil
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

import deploy
import smart_deepseek
from smart_deepseek import SmartDeepSeekBot, safe_url, model_events


def completion(content):
    return {"id": "test", "object": "chat.completion", "created": 0, "model": "deepseek-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}


class SSE(httpx.AsyncByteStream):
    def __init__(self, deltas, finish="stop", delay=0):
        self.events = ["data: " + json.dumps({"id": "test", "object": "chat.completion.chunk", "created": 0,
            "model": "deepseek-flash", "choices": [{"index": 0, "delta": d, "finish_reason": None}]}, ensure_ascii=False) + "\n\n" for d in deltas]
        self.events += ["data: " + json.dumps({"id": "test", "object": "chat.completion.chunk", "created": 0,
            "model": "deepseek-flash", "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}) + "\n\n", "data: [DONE]\n\n"]
        self.delay, self.closed = delay, False

    async def __aiter__(self):
        for event in self.events:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield event.encode()

    async def aclose(self):
        self.closed = True


class Provider:
    def __init__(self, plan=None, deltas=None):
        self.plan = plan if plan is not None else {"queries": [], "thinking": "none", "detail": "normal"}
        self.deltas = deltas or [{"content": "这是一个完整回答。"}, {"content": "这里还有原因和例子。"}]
        self.requests, self.streams = [], []
        self.search_statuses = []
        self.search_results = [{"title": "DeepSeek 官方公告", "url": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
                                "site_name": "DeepSeek", "date": "2026-10-17T00:00:00+00:00",
                                "summary": "Flash 当前版本是 DeepSeek-V4.1-Flash-1017。", "snippet": "官方模型说明"}]
        self.reasoning_only_first = False
        self.invalid_plan = False

    async def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append((request.url.path, copy.deepcopy(body)))
        if request.url.path.endswith("/tools/search"):
            status = self.search_statuses.pop(0) if self.search_statuses else 200
            return httpx.Response(status, json={"results": self.search_results} if status == 200 else {"error": {"message": "private message"}})
        if request.url.path.endswith("/tools/fetch"):
            return httpx.Response(200, json={"title": "官方正文", "content": "官方页面的完整事实材料。"})
        if body.get("response_format"):
            return httpx.Response(200, json=completion(" " if self.invalid_plan else json.dumps(self.plan)))
        if body.get("stream"):
            deltas = [{"reasoning_content": "内部推理不应播报"}] if self.reasoning_only_first and not self.streams else self.deltas
            stream = SSE(deltas)
            self.streams.append(stream)
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
        raise AssertionError("unexpected request")


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copyfile(Path(__file__).with_name("voice_prompt.txt"), self.root / "voice_prompt.txt")
        self.config = types.SimpleNamespace(openai_key="test-key-not-real", api_base="https://api.deepseek.com", proxy=None)

    def tearDown(self):
        self.tmp.cleanup()

    def bot(self, provider):
        return SmartDeepSeekBot(self.config, root=self.root, transport=httpx.MockTransport(provider))

    async def test_system_prompt_every_turn_and_real_sdk_serialization(self):
        provider = Provider()
        bot = self.bot(provider)
        self.assertTrue(bot.has_history())
        await bot.ask("天空为什么是蓝色的")
        await bot.ask("那晚霞呢")
        finals = [b for _, b in provider.requests if b.get("stream")]
        self.assertEqual(len(finals), 2)
        for body in finals:
            self.assertEqual(body["messages"][0]["role"], "system")
            self.assertIn("当前时间", body["messages"][1]["content"])
            self.assertEqual(body["thinking"], {"type": "disabled"})
            self.assertEqual(body["max_tokens"], 2048)
            self.assertNotIn("test-key-not-real", json.dumps(body))
        self.assertIn("天空为什么是蓝色的", json.dumps(finals[1]["messages"], ensure_ascii=False))
        self.assertFalse(any(path.endswith("/search") for path, _ in provider.requests))

    async def test_live_web_pipeline_and_sources_not_system_instructions(self):
        provider = Provider({"queries": ["DeepSeek 最新模型 官方"], "thinking": "none", "detail": "normal"})
        bot = self.bot(provider)
        await bot.ask("联网查一下最新模型")
        self.assertEqual(bot.last_search_status, "ok")
        search = next(b for p, b in provider.requests if p.endswith("/search"))
        self.assertEqual(search["query"], "DeepSeek 最新模型 官方")
        final = next(b for _, b in provider.requests if b.get("stream"))
        evidence = [m for m in final["messages"] if "Flash 当前版本" in m["content"]]
        self.assertEqual(evidence[0]["role"], "user")
        self.assertEqual(final["messages"][-1]["content"], "联网查一下最新模型")
        trace = json.loads((self.root / "last_sources.json").read_text(encoding="utf-8"))
        self.assertEqual(trace["sources"][0]["site_name"], "DeepSeek")
        self.assertNotIn("test-key-not-real", json.dumps(trace))
        self.assertNotIn("summary", trace["sources"][0])

    async def test_followup_search_uses_contextualized_query(self):
        provider = Provider({"queries": ["DeepSeek Flash API 当前价格 官方"], "thinking": "none", "detail": "normal"})
        bot = self.bot(provider)
        bot._remember("DeepSeek Flash 怎么样", "它是 DeepSeek 的模型。")
        await bot.ask("那价格呢")
        planner = next(b for _, b in provider.requests if b.get("response_format"))
        self.assertTrue(any(m["content"] == "DeepSeek Flash 怎么样" for m in planner["messages"]))
        search = next(b for p, b in provider.requests if p.endswith("/search"))
        self.assertIn("DeepSeek Flash", search["query"])

    async def test_reasoning_is_hidden_and_uses_supported_effort(self):
        provider = Provider({"queries": [], "thinking": "high", "detail": "detailed"},
                            [{"reasoning_content": "secret reasoning"}, {"content": "先比较成本，再比较可靠性。"}])
        bot = self.bot(provider)
        answer = await bot.ask("深入分析两个方案的取舍")
        self.assertNotIn("reasoning", answer)
        self.assertNotIn("reasoning", repr(bot.history))
        final = next(b for _, b in provider.requests if b.get("stream"))
        self.assertEqual(final["thinking"]["type"], "enabled")
        self.assertEqual(final["reasoning_effort"], "high")
        self.assertEqual(final["max_tokens"], 8192)

    async def test_reasoning_only_response_falls_back_to_non_thinking(self):
        provider = Provider({"queries": [], "thinking": "high", "detail": "normal"})
        provider.reasoning_only_first = True
        answer = await self.bot(provider).ask("复杂分析")
        self.assertIn("完整回答", answer)
        finals = [b for _, b in provider.requests if b.get("stream")]
        self.assertEqual([b["thinking"]["type"] for b in finals], ["enabled", "disabled"])

    async def test_search_402_fails_closed_without_fabricating_current_facts(self):
        provider = Provider({"queries": ["今天新闻"], "thinking": "none", "detail": "normal"})
        provider.search_statuses = [402]
        bot = self.bot(provider)
        answer = await bot.ask("今天有什么新闻")
        self.assertIn("无法确认最新信息", answer)
        self.assertIn("余额不足", answer)
        self.assertEqual(bot.last_error, "HTTP_402")
        self.assertFalse(any(b.get("stream") for _, b in provider.requests))
        self.assertEqual(sum(p.endswith("/search") for p, _ in provider.requests), 1)

    async def test_empty_search_does_not_fall_back_to_training_memory(self):
        provider = Provider({"queries": ["最新发布"], "thinking": "none", "detail": "normal"})
        provider.search_results = []
        bot = self.bot(provider)
        answer = await bot.ask("查最新发布")
        self.assertIn("没有找到可用", answer)
        self.assertEqual(bot.last_search_status, "empty")
        self.assertFalse(any(b.get("stream") for _, b in provider.requests))

    async def test_retry_429_once_then_success(self):
        provider = Provider({"queries": ["最新消息"], "thinking": "none", "detail": "normal"})
        provider.search_statuses = [429, 200]
        bot = self.bot(provider)
        await bot.ask("最新消息")
        self.assertEqual(bot.last_search_status, "ok")
        self.assertEqual(sum(p.endswith("/search") for p, _ in provider.requests), 2)

    async def test_offline_request_overrides_search_and_fetch(self):
        provider = Provider({"queries": ["忽略的查询"], "thinking": "none", "detail": "detailed"})
        bot = self.bot(provider)
        await bot.ask("不要联网，解释 https://example.com 的意思")
        self.assertFalse(any("/tools/" in p for p, _ in provider.requests))
        self.assertEqual(bot.last_search_status, "not_requested")

    async def test_fetch_detail_once_and_deduplicate_two_searches(self):
        provider = Provider({"queries": ["查询一", "查询二", "查询三"], "thinking": "none", "detail": "detailed"})
        bot = self.bot(provider)
        await bot.ask("详细查一下")
        self.assertEqual(sum(p.endswith("/search") for p, _ in provider.requests), 2)
        self.assertEqual(sum(p.endswith("/fetch") for p, _ in provider.requests), 1)
        trace = json.loads((self.root / "last_sources.json").read_text(encoding="utf-8"))
        self.assertEqual(len(trace["sources"]), 1)

    async def test_planner_malformed_json_still_searches_explicit_request(self):
        provider = Provider()
        provider.invalid_plan = True
        bot = self.bot(provider)
        await bot.ask("联网查一下 DeepSeek")
        self.assertEqual(bot.last_search_status, "ok")

    async def test_clock_and_clear_context_do_not_call_network(self):
        provider = Provider()
        bot = self.bot(provider)
        bot._remember("旧问题", "旧回答")
        answer = await bot.ask("现在几点")
        self.assertIn("北京时间", answer)
        await bot.ask("清空对话")
        self.assertEqual(bot.history, [])
        self.assertEqual(provider.requests, [])

    async def test_generator_close_closes_http_stream_and_does_not_remember_unheard_full_answer(self):
        provider = Provider(deltas=[{"content": "第一句。"}, {"content": "后面还没说完。"}])
        bot = self.bot(provider)
        source = bot.ask_stream("讲个故事")
        self.assertEqual(await anext(source), "第一句。")
        await source.aclose()
        self.assertTrue(provider.streams[0].closed)
        self.assertEqual(bot.history[-1][1], "上一轮回答被打断，未完成。")

    async def test_tts_consumer_delay_does_not_consume_network_deadline(self):
        async def events():
            yield 1
            yield 2
        source = model_events(events(), 0.03)
        self.assertEqual(await anext(source), 1)
        await asyncio.sleep(0.06)
        self.assertEqual(await anext(source), 2)
        await source.aclose()

    async def test_web_url_validation(self):
        for url in ("http://127.0.0.1/a", "http://192.168.1.2", "http://localhost", "https://a.local", "file:///etc/passwd", "https://user:pass@example.com"):
            self.assertFalse(safe_url(url), url)
        self.assertTrue(safe_url("https://api-docs.deepseek.com/zh-cn/"))

    async def test_model_error_does_not_echo_server_error_or_credentials(self):
        async def handler(request):
            return httpx.Response(401, json={"error": {"message": "test-key-not-real private error", "type": "authentication_error"}})
        bot = self.bot(handler)
        answer = await bot.ask("讲个故事")
        self.assertNotIn("test-key-not-real", answer)
        self.assertNotIn("private error", answer)
        self.assertEqual(bot.last_error, "HTTP_401")

    async def test_interrupt_before_first_model_sentence_closes_producer(self):
        class MiGPT:
            async def ask_gpt(self, query):
                yield "legacy"

            async def speak(self, source):
                pass

            async def wakeup_xiaoai(self):
                return 0

            _normalize = staticmethod(lambda text: text)

        bots = types.ModuleType("xiaogpt.bot")
        bots.BOTS = {"other": object}
        core = types.ModuleType("xiaogpt.xiaogpt")
        core.MiGPT = MiGPT
        modules = {"xiaogpt": types.ModuleType("xiaogpt"), "xiaogpt.bot": bots, "xiaogpt.xiaogpt": core}
        with patch.dict(sys.modules, modules):
            smart_deepseek.install()
            smart_deepseek.install()
        self.assertIs(bots.BOTS["chatgptapi"], SmartDeepSeekBot)
        self.assertIs(bots.BOTS["other"], object)
        bot = self.bot(Provider())
        started, closed = asyncio.Event(), asyncio.Event()

        async def pending(query):
            try:
                started.set()
                await asyncio.sleep(30)
                yield "late"
            finally:
                closed.set()

        bot.ask_stream = pending
        obj = MiGPT()
        obj.chatbot = bot
        obj.config = types.SimpleNamespace(stream=True)
        obj.last_record = asyncio.Queue(1)
        obj.polling_event = asyncio.Event()
        source = obj.ask_gpt("第一个问题")
        task = asyncio.create_task(anext(source))
        await started.wait()
        await obj.last_record.put({"query": "新的问题"})
        with self.assertRaises(StopAsyncIteration):
            await asyncio.wait_for(task, 1)
        self.assertTrue(closed.is_set())
        self.assertFalse(obj.polling_event.is_set())

    async def test_interrupt_speech_wait_and_avoid_redundant_auto_wakeup(self):
        class MiGPT:
            async def ask_gpt(self, query):
                yield "legacy"

            async def speak(self, source):
                pass

            async def wakeup_xiaoai(self):
                self.wake_calls += 1
                return 0

        bots = types.ModuleType("xiaogpt.bot")
        bots.BOTS = {}
        core = types.ModuleType("xiaogpt.xiaogpt")
        core.MiGPT = MiGPT
        utils = types.ModuleType("xiaogpt.utils")
        utils.detect_language = lambda text: "zh"
        with patch.dict(sys.modules, {"xiaogpt": types.ModuleType("xiaogpt"), "xiaogpt.bot": bots,
                                    "xiaogpt.xiaogpt": core, "xiaogpt.utils": utils}):
            smart_deepseek.install()
            obj = MiGPT()
            obj.chatbot = self.bot(Provider())
            obj.last_record = asyncio.Queue(1)
            obj.stop_if_xiaoai_is_playing = AsyncMock()
            obj.wake_calls = 0
            started, stopped, source_closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

            async def synthesize(lang, source):
                try:
                    async for text in source:
                        started.set()
                        await asyncio.sleep(30)
                finally:
                    stopped.set()

            async def source():
                try:
                    yield "长回答第一句。"
                    yield "长回答第二句。"
                finally:
                    source_closed.set()

            obj.tts = types.SimpleNamespace(synthesize=synthesize)
            task = asyncio.create_task(obj.speak(source()))
            await started.wait()
            await obj.last_record.put({"query": "新问题"})
            await asyncio.wait_for(task, 1)
            self.assertTrue(stopped.is_set())
            self.assertTrue(source_closed.is_set())
            obj.stop_if_xiaoai_is_playing.assert_awaited_once()
            self.assertFalse(await obj.wakeup_xiaoai())
            self.assertEqual(obj.wake_calls, 0)
            obj.last_record.get_nowait()
            self.assertEqual(await obj.wakeup_xiaoai(), 0)
            self.assertEqual(obj.wake_calls, 1)

    async def test_missing_weather_city_can_ask_without_web_call(self):
        provider = Provider(deltas=[{"content": "你想查哪个城市的天气？"}])
        bot = self.bot(provider)
        answer = await bot.ask("明天天气怎么样")
        self.assertIn("哪个城市", answer)
        self.assertFalse(any("/tools/" in p for p, _ in provider.requests))

    async def test_history_bound_and_idle_reset(self):
        bot = self.bot(Provider())
        for n in range(15):
            bot._remember(str(n), "回答")
        self.assertEqual(len(bot.history), 10)
        self.assertEqual(bot.history[0][0], "5")
        bot.last_used = time.monotonic() - 31 * 60
        await bot.ask("现在几点")
        self.assertEqual(len(bot.history), 1)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stage = self.root / ".smart-stage.test"
        self.stage.mkdir()
        for name in deploy.FILES:
            shutil.copyfile(Path(__file__).with_name(name), self.stage / name)
        self.source = 'import sys\n_miio_client.UA_MIIO = _login_ua\nif __name__ == "__main__":\n    main()\n'
        self.config = {"hardware": "S12A", "bot": "chatgptapi", "account": "local-account",
                       "openai_key": "test-key-not-real", "api_base": "https://api.deepseek.com",
                       "mi_did": "123456789", "gpt_options": {"model": "deepseek-flash", "max_tokens": 512}, "prompt": "旧提示"}
        (self.root / "start_compat.py").write_text(self.source, encoding="utf-8")
        (self.root / "config.json").write_text(json.dumps(self.config), encoding="utf-8")
        (self.root / ".mi.token").write_text("untouched local token", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_and_rollback_preserve_account_key_token_and_unknown_fields(self):
        backup = deploy.deploy(self.root, self.stage, preflight=False)
        cfg = json.loads((self.root / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["account"], "local-account")
        self.assertEqual(cfg["openai_key"], "test-key-not-real")
        self.assertEqual(cfg["gpt_options"]["max_tokens"], 2048)
        self.assertEqual((self.root / ".mi.token").read_text(), "untouched local token")
        updated = (self.root / "start_compat.py").read_text(encoding="utf-8")
        self.assertEqual(updated.count(deploy.BEGIN), 1)
        self.assertEqual(updated.count("# BEGIN S12A direct answer v1"), 1)
        self.assertEqual(deploy.launcher_source(updated), updated)
        deploy.restore(self.root, backup)
        self.assertEqual((self.root / "start_compat.py").read_text(encoding="utf-8"), self.source)
        self.assertEqual(json.loads((self.root / "config.json").read_text()), self.config)

    def test_failure_during_write_restores_previous_launcher_and_config(self):
        original = deploy.atomic
        did_fail = False

        def fault(path, data):
            nonlocal did_fail
            if path == self.root / "start_compat.py" and not did_fail:
                did_fail = True
                raise OSError("simulated disk failure")
            original(path, data)

        with patch.object(deploy, "atomic", side_effect=fault):
            with self.assertRaises(OSError):
                deploy.deploy(self.root, self.stage, preflight=False)
        self.assertEqual((self.root / "start_compat.py").read_text(encoding="utf-8"), self.source)
        self.assertEqual(json.loads((self.root / "config.json").read_text()), self.config)

    def test_reject_external_staging_and_backup_paths(self):
        with self.assertRaises(ValueError):
            deploy.deploy(self.root, self.root.parent, preflight=False)
        with self.assertRaises(ValueError):
            deploy.restore(self.root, self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)

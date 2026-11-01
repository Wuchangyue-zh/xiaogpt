import asyncio
import unittest
from unittest.mock import AsyncMock

from helpers import config
from xiaogpt_voice.app import VoiceApplication
from xiaogpt_voice.xiaomi import Utterance


class Gateway:
    def __init__(self):
        self.calls = []
        self.wake_ok = True
        self.started = asyncio.Event()

    async def latest(self):
        await asyncio.Event().wait()

    async def interrupt(self, stamp):
        self.calls.append(("cut", stamp))

    async def wake(self):
        self.calls.append(("wake",))
        return self.wake_ok

    async def say(self, text):
        self.calls.append(("say", text))

    async def wait_speech(self, text):
        if text == "长回答第一句。":
            self.started.set()
            await asyncio.sleep(60)


class Assistant:
    def __init__(self):
        self.queries = []
        self.closed = []

    async def ask_stream(self, query):
        self.queries.append(query)
        try:
            if query == "长问题":
                yield "长回答第一句。"
                yield "不该继续播报的第二句。"
            else:
                yield "新的完整回答。"
        finally:
            self.closed.append(query)


class ApplicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.gateway, self.assistant = Gateway(), Assistant()
        self.app = VoiceApplication(config(), self.gateway, self.assistant)
        self.app.last_timestamp = 0

    async def asyncTearDown(self):
        await self.app._cancel_response()

    async def test_trigger_stripped_and_native_response_cut_once(self):
        await self.app.handle(Utterance(1, "请问，天空为什么蓝？"))
        await self.app.response
        self.assertEqual(self.assistant.queries, ["天空为什么蓝"])
        self.assertEqual(self.gateway.calls.count(("cut", 1)), 1)
        self.assertIn(("say", "新的完整回答。"), self.gateway.calls)

    async def test_native_command_is_not_intercepted(self):
        await self.app.handle(Utterance(1, "现在几点"))
        self.assertEqual(self.gateway.calls, [])
        self.assertEqual(self.assistant.queries, [])

    async def test_continuous_start_interrupts_before_waking_and_accepts_prefix(self):
        await self.app.handle(Utterance(1, "请问开始持续对话"))
        self.assertTrue(self.app.continuous)
        self.assertEqual(self.gateway.calls, [("cut", 1), ("wake",)])
        await self.app.handle(Utterance(2, "那价格呢"))
        await self.app.response
        self.assertEqual(self.assistant.queries, ["那价格呢"])

    async def test_failed_wake_returns_to_single_question_mode(self):
        self.gateway.wake_ok = False
        await self.app.handle(Utterance(1, "开始连续对话"))
        self.assertFalse(self.app.continuous)
        await self.app.handle(Utterance(2, "普通问题"))
        self.assertEqual(self.assistant.queries, [])

    async def test_new_question_cancels_wait_and_closes_old_generator(self):
        await self.app.handle(Utterance(1, "请问长问题"))
        await self.gateway.started.wait()
        await asyncio.wait_for(self.app.handle(Utterance(2, "请问新问题")), timeout=1)
        await self.app.response
        self.assertIn("长问题", self.assistant.closed)
        self.assertNotIn(("say", "不该继续播报的第二句。"), self.gateway.calls)
        self.assertEqual(self.assistant.queries, ["长问题", "新问题"])

    async def test_native_barge_in_cancels_model_but_preserves_native_answer(self):
        await self.app.handle(Utterance(1, "请问长问题"))
        await self.gateway.started.wait()
        await self.app.handle(Utterance(2, "播放音乐"))
        self.assertNotIn(("cut", 2), self.gateway.calls)
        self.assertIsNone(self.app.response)

    async def test_end_continuous_cancels_response_without_rewaking(self):
        self.app.continuous = True
        await self.app.handle(Utterance(1, "长问题"))
        await self.gateway.started.wait()
        await self.app.handle(Utterance(2, "请问结束持续对话"))
        self.assertFalse(self.app.continuous)
        self.assertIsNone(self.app.response)
        self.assertNotIn(("wake",), self.gateway.calls)

    async def test_queue_deduplicates_and_keeps_latest_pending_utterance(self):
        self.app.submit(Utterance(1, "first"))
        self.app.submit(Utterance(1, "duplicate"))
        self.app.submit(Utterance(2, "latest"))
        self.assertEqual(self.app.pending.qsize(), 1)
        self.assertEqual(self.app.pending.get_nowait().text, "latest")

    async def test_empty_trigger_prompts_without_calling_model(self):
        await self.app.handle(Utterance(1, "请问？"))
        await self.app.response
        self.assertIn(("say", "你想问什么？"), self.gateway.calls)
        self.assertEqual(self.assistant.queries, [])

    async def test_scheduler_follows_up_and_shuts_down_cleanly(self):
        self.app.continuous = True
        server = asyncio.create_task(self.app.serve())
        self.app.submit(Utterance(1, "请问短问题"))
        for _ in range(100):
            if ("wake",) in self.gateway.calls:
                break
            await asyncio.sleep(0.005)
        self.assertIn(("wake",), self.gateway.calls)
        server.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await server
        self.assertIsNone(self.app.response)

"""Event-driven conversation scheduling and interruption ownership."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from .config import AppConfig
from .xiaomi import Utterance

LOG = logging.getLogger("xiaogpt_voice")


def normalize(text: str) -> str:
    return text.strip().strip("，,。.!！？?：: ")


class VoiceApplication:
    def __init__(self, config: AppConfig, gateway, assistant):
        self.config, self.gateway, self.assistant = config, gateway, assistant
        self.continuous = False
        self.pending = asyncio.Queue(maxsize=1)
        self.response = None
        self.last_timestamp = int(time.time() * 1000)

    def submit(self, record: Utterance):
        if record.timestamp <= self.last_timestamp:
            return
        self.last_timestamp = record.timestamp
        if self.pending.full():
            self.pending.get_nowait()
        self.pending.put_nowait(record)

    async def _poll(self):
        failures = 0
        while True:
            try:
                record = await self.gateway.latest()
                if record:
                    self.submit(record)
                failures = 0
            except Exception as exc:
                failures += 1
                LOG.warning("读取对话暂不可用（%s），稍后重试", type(exc).__name__)
            await asyncio.sleep(min(30, max(self.config.poll_interval, 2 ** min(failures, 5) if failures else 0)))

    async def _cancel_response(self):
        if self.response is not None:
            self.response.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                try:
                    await self.response
                except Exception as exc:
                    LOG.warning("上一轮回答未完成（%s）", type(exc).__name__)
            self.response = None

    async def _respond(self, query):
        async with contextlib.aclosing(self.assistant.ask_stream(query)) as answers:
            async for sentence in answers:
                if sentence.strip():
                    await self._speak(sentence)

    async def _speak(self, sentence):
        LOG.info("助手：%s", sentence)
        await self.gateway.say(sentence)
        await self.gateway.wait_speech(sentence)

    async def handle(self, record: Utterance):
        text = normalize(record.text)
        await self._cancel_response()
        query = None
        for word in self.config.trigger_words:
            if text.startswith(word):
                query = normalize(text[len(word):])
                break
        command = query if query is not None else text
        if command in self.config.start_phrases:
            await self.gateway.interrupt(record.timestamp)
            self.continuous = await self.gateway.wake()
            LOG.info("%s", "连续对话已开始" if self.continuous else "请逐次语音唤醒提问")
            return
        if command in self.config.end_phrases:
            self.continuous = False
            await self.gateway.interrupt(record.timestamp)
            LOG.info("连续对话已结束")
            return
        if query is None and self.continuous and text not in ("小爱同学", "小爱"):
            query = text
        if query is None:
            return  # Leave ordinary native XiaoAI commands alone.
        await self.gateway.interrupt(record.timestamp)
        if not query:
            self.response = asyncio.create_task(self._speak("你想问什么？"))
            return
        LOG.info("用户：%s", query)
        self.response = asyncio.create_task(self._respond(query))

    async def serve(self):
        poller = asyncio.create_task(self._poll())
        incoming = asyncio.create_task(self.pending.get())
        LOG.info("监听已启动，用“小爱同学，%s……”提问", self.config.trigger_words[0])
        try:
            while True:
                tasks = {incoming}
                if self.response is not None:
                    tasks.add(self.response)
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if incoming in done:
                    await self.handle(incoming.result())
                    incoming = asyncio.create_task(self.pending.get())
                elif self.response is not None and self.response in done:
                    try:
                        await self.response
                    except Exception as exc:
                        LOG.warning("回答未完成（%s）", type(exc).__name__)
                    self.response = None
                    if self.continuous and self.pending.empty() and not incoming.done():
                        self.continuous = await self.gateway.wake()
        finally:
            poller.cancel()
            incoming.cancel()
            await self._cancel_response()
            await asyncio.gather(poller, incoming, return_exceptions=True)

"""Xiaomi cloud transport, authentication, playback and device actions."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig

LOG = logging.getLogger("xiaogpt_voice")
CONVERSATION_URL = "https://userprofile.mina.mi.com/device_profile/v2/conversation"
SILENT_TEXT = "¿ʞо ∩оʎ ǝɹɐ"


class XiaomiError(Exception):
    """A sanitized transport error, safe to show without account/token values."""


@dataclass(frozen=True)
class Utterance:
    timestamp: int
    text: str


def parse_latest(payload: dict) -> Utterance | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise XiaomiError("对话接口没有返回有效数据")
    records = data.get("records") or []
    valid = []
    for item in records:
        if isinstance(item, dict) and isinstance(item.get("query"), str):
            try:
                stamp = int(item["time"])
            except (KeyError, TypeError, ValueError):
                continue
            if stamp > 0 and item["query"].strip():
                valid.append(Utterance(stamp, item["query"].strip()))
    return max(valid, key=lambda row: row.timestamp) if valid else None


def identity_from(token: dict | None) -> dict:
    keys = ("deviceId", "userId", "passToken")
    return {k: token[k] for k in keys} if isinstance(token, dict) and all(token.get(k) for k in keys) else {}


def account_client(session, user: str, password: str, token_path: Path, otp=None):
    from miservice import MiAccount
    import miservice.miioservice as miio
    from miservice.miaccount import UA_LOGIN

    miio.UA_MIIO = UA_LOGIN
    logging.getLogger("miservice").disabled = True

    class SessionAccount(MiAccount):
        async def login(self, sid):
            if self.token is None:
                saved = await self.token_store.load_token() if self.token_store else None
                self.token = saved or dict(self.identity) or None
            self.identity = identity_from(self.token) or self.identity
            ok = await super().login(sid)
            self.identity = identity_from(self.token) or self.identity
            return ok

    kwargs = {"otp_callback": otp} if otp else {}
    account = SessionAccount(session, user, password, str(token_path), **kwargs)
    try:
        cached = json.loads(token_path.read_text()) if token_path.is_file() else {}
    except (ValueError, OSError):
        cached = {}
    account.identity = identity_from(cached)
    return account


async def discover(root: Path, user: str, password: str, otp):
    from aiohttp import ClientSession, ClientTimeout
    from miservice import MiNAService

    async with ClientSession(timeout=ClientTimeout(total=30)) as session:
        account = account_client(session, user, password, root / ".mi.token", otp)
        devices = await MiNAService(account).device_list()
        return str((account.token or {}).get("userId") or user), devices or []


class XiaomiGateway:
    def __init__(self, config: AppConfig, root: Path):
        self.config, self.root = config, root
        self.session = self.account = self.mina = self.miio = None
        self.device_id = ""
        self.wake_after = 0.0
        self.refresh_after = 0.0
        self.interrupt_stamp = None

    async def open(self):
        from aiohttp import ClientSession, ClientTimeout
        from miservice import MiNAService, MiIOService

        self.session = ClientSession(timeout=ClientTimeout(total=20))
        self.account = account_client(self.session, self.config.account, "", self.root / ".mi.token")
        self.mina, self.miio = MiNAService(self.account), MiIOService(self.account)
        try:
            devices = await self.mina.device_list()
            target = next((d for d in devices or [] if str(d.get("miotDID")) == self.config.device.miot_did), None)
            if not target or not target.get("deviceID"):
                raise XiaomiError("账号下未找到所配置的音箱，请重新运行 init --replace")
            self.device_id = target["deviceID"]
        except BaseException:
            await self.close()
            raise

    async def close(self):
        if self.session is not None:
            await self.session.close()
            self.session = None

    def _cookies(self):
        token = self.account.token or {}
        service = token.get("micoapi") or []
        if len(service) != 2 or not token.get("userId"):
            raise XiaomiError("小米登录缓存不可用，请重新运行 init --replace --login-again")
        return {"deviceId": self.device_id, "serviceToken": service[1], "userId": str(token["userId"])}

    async def latest(self) -> Utterance | None:
        for attempt in range(2):
            try:
                async with self.session.get(CONVERSATION_URL, params={"source": "dialogu", "hardware": self.config.device.hardware,
                    "timestamp": str(int(time.time() * 1000)), "limit": "2"}, cookies=self._cookies()) as response:
                    if response.status != 200:
                        raise XiaomiError("对话接口 HTTP " + str(response.status))
                    payload = await response.json(content_type=None)
                return parse_latest(payload)
            except (XiaomiError, ValueError):
                if attempt or time.monotonic() < self.refresh_after:
                    raise XiaomiError("暂时无法读取对话，请检查小米登录状态") from None
                self.refresh_after = time.monotonic() + 60
                if not await self.account.login("micoapi"):
                    raise XiaomiError("小米会话刷新失败，请重新登录") from None

    async def interrupt(self, stamp: int):
        if self.interrupt_stamp == stamp:
            return
        self.interrupt_stamp = stamp
        try:
            result = await asyncio.wait_for(self.miio.miot_action(self.config.device.miot_did,
                self.config.device.text_action, [SILENT_TEXT]), timeout=8)
            if result != 0:
                raise XiaomiError("静音动作未接受")
            LOG.info("原声已打断")
        except Exception as exc:
            LOG.warning("静音打断未完成（%s），尝试暂停", type(exc).__name__)
            try:
                await asyncio.wait_for(self.mina.player_pause(self.device_id), timeout=5)
            except Exception:
                LOG.warning("暂停请求未完成")

    async def wake(self) -> bool:
        if time.monotonic() < self.wake_after:
            return False
        try:
            result = await asyncio.wait_for(self.miio.miot_action(self.config.device.miot_did,
                self.config.device.wake_action, []), timeout=8)
            if result != 0:
                raise XiaomiError("唤醒动作未接受")
            LOG.info("已唤醒，等待下一句")
            return True
        except Exception as exc:
            match = re.search(r'"wait_second"\s*:\s*(\d+)', str(exc))
            self.wake_after = time.monotonic() + (max(30, int(match.group(1))) if match else 60)
            LOG.warning("自动唤醒未完成，已进入冷却（%s）", type(exc).__name__)
            return False

    async def say(self, text: str):
        ok = await self.mina.text_to_speech(self.device_id, text)
        if ok is False:
            raise XiaomiError("音箱未接受播报请求")

    async def wait_speech(self, text: str):
        # The device does not consistently report TTS playback as media playback.
        # A cancellable duration estimate avoids overlapping sentence playback.
        count = len(re.sub(r'[「」『』《》“”\'"()（）]', "", text))
        await asyncio.sleep(max(0.3, count / 4.5))
        for _ in range(10):
            status = await self.mina.player_get_status(self.device_id)
            if (status or {}).get("status") != 1:
                return
            await asyncio.sleep(1)

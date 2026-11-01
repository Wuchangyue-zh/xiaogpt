import asyncio
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from helpers import config
from xiaogpt_voice.xiaomi import XiaomiGateway, XiaomiError, Utterance, parse_latest, identity_from, account_client


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_conversation_parser_accepts_encoded_data_and_selects_latest(self):
        data = {"data": json.dumps({"records": [{"time": 3, "query": "new"}, {"time": 1, "query": "old"}, {"query": "bad"}]})}
        self.assertEqual(parse_latest(data), Utterance(3, "new"))
        self.assertIsNone(parse_latest({"data": {"records": []}}))
        with self.assertRaises(XiaomiError):
            parse_latest({"code": 401})

    async def test_identity_keeps_only_refresh_fields(self):
        self.assertEqual(identity_from({"userId": "a"}), {})
        self.assertEqual(identity_from({"userId": "a", "deviceId": "b", "passToken": "c", "micoapi": [1, 2]}),
                         {"userId": "a", "deviceId": "b", "passToken": "c"})

    async def test_silent_cut_deduplicates_without_status_roundtrip(self):
        gateway = XiaomiGateway(config(), Path("."))
        gateway.miio = SimpleNamespace(miot_action=AsyncMock(return_value=0))
        gateway.mina = SimpleNamespace(player_pause=AsyncMock())
        await gateway.interrupt(1)
        await gateway.interrupt(1)
        gateway.miio.miot_action.assert_awaited_once()
        gateway.mina.player_pause.assert_not_awaited()

    async def test_cut_failure_uses_pause_but_cancellation_propagates(self):
        gateway = XiaomiGateway(config(), Path("."))
        gateway.miio = SimpleNamespace(miot_action=AsyncMock(return_value=-1))
        gateway.mina = SimpleNamespace(player_pause=AsyncMock())
        await gateway.interrupt(1)
        gateway.mina.player_pause.assert_awaited_once()
        gateway.miio.miot_action.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await gateway.interrupt(2)

    async def test_direct_wake_empty_arguments_and_error_cooldown(self):
        gateway = XiaomiGateway(config(), Path("."))
        gateway.miio = SimpleNamespace(miot_action=AsyncMock(return_value=0))
        self.assertTrue(await gateway.wake())
        gateway.miio.miot_action.assert_awaited_once_with("own-test-device", (5, 3), [])
        gateway.miio.miot_action.side_effect = Exception('{"code":-127,"wait_second":30}')
        self.assertFalse(await gateway.wake())
        count = gateway.miio.miot_action.await_count
        self.assertFalse(await gateway.wake())
        self.assertEqual(gateway.miio.miot_action.await_count, count)

    async def test_conversation_cookies_follow_live_session_and_refresh(self):
        class Response:
            def __init__(self, payload):
                self.status, self.payload = 200, payload

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def json(self, **kwargs):
                return self.payload

        gateway = XiaomiGateway(config(), Path("."))
        gateway.device_id = "mina-id"
        tokens = []
        payloads = iter([{"code": 401}, {"data": json.dumps({"records": [{"time": 3, "query": "question"}]})}])

        def get(url, **kwargs):
            tokens.append(kwargs["cookies"]["serviceToken"])
            return Response(next(payloads))

        async def login(sid):
            gateway.account.token["micoapi"] = ["security", "new-token"]
            return True

        gateway.account = SimpleNamespace(token={"userId": "user", "micoapi": ["security", "old-token"]}, login=login)
        gateway.session = SimpleNamespace(get=get)
        self.assertEqual(await gateway.latest(), Utterance(3, "question"))
        self.assertEqual(tokens, ["old-token", "new-token"])

    @unittest.skipUnless(importlib.util.find_spec("miservice"), "MiService integration runs in the built image")
    async def test_expired_service_token_recovers_without_saved_password(self):
        from miservice import MiAccount

        class Response:
            def __init__(self, status):
                self.status = status

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def text(self):
                return "expired"

            async def json(self, **kwargs):
                return {"code": 0, "data": []}

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".mi.token"
            path.write_text(json.dumps({"userId": "user", "deviceId": "device", "passToken": "saved-pass", "micoapi": ["s", "old"]}))
            statuses, sent, identities = iter([401, 200]), [], []

            def request(method, url, **kwargs):
                sent.append(kwargs["cookies"]["serviceToken"])
                return Response(next(statuses))

            async def service_login(account, *args):
                identities.append(account.token.get("passToken"))
                return {"code": 0, "userId": "user", "passToken": "saved-pass", "location": "https://example.com", "nonce": "n", "ssecurity": "s"}

            account = account_client(SimpleNamespace(request=request), "user", "", path)
            with patch.object(MiAccount, "_serviceLogin", service_login), patch.object(MiAccount, "_securityTokenService", AsyncMock(return_value="new")):
                await account.mi_request("micoapi", "https://example.com", None, {})
            self.assertEqual(sent, ["old", "new"])
            self.assertEqual(identities, ["saved-pass"])

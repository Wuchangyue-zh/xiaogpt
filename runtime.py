"""Standalone entry point for the source-built image; legacy install.sh remains separate."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path


def install_compatibility():
    import miservice.miioservice as miio
    from miservice.miaccount import UA_LOGIN
    from xiaogpt.xiaogpt import MiGPT
    from direct_answer_patch import BLOCK
    from smart_deepseek import install

    miio.UA_MIIO = UA_LOGIN
    if getattr(MiGPT, "_standalone_compat_installed", False):
        return
    original_wake = MiGPT.wakeup_xiaoai

    async def guarded_wake(self):
        remaining = getattr(self, "_wakeup_cooldown_until", 0) - time.monotonic()
        if remaining > 0:
            self.in_conversation = False
            self.log.warning("自动唤醒冷却中，请逐次语音唤醒提问。")
            return False
        try:
            if self.config.hardware != "S12A":
                return await original_wake(self)
            code = await self.miio_service.miot_action(str(self.config.mi_did), (5, 3), [])
            if code != 0:
                raise RuntimeError(json.dumps({"code": code}))
            self.log.info("自动唤醒请求已接受")
            return code
        except Exception as exc:
            self.in_conversation = False
            match = re.search(r'"wait_second"\s*:\s*(\d+)', str(exc))
            wait = max(30, int(match.group(1))) if match else 60
            self._wakeup_cooldown_until = time.monotonic() + wait
            self.log.warning("自动唤醒未成功，已退出连续对话；冷却 %d 秒。", wait)
            return False

    MiGPT.wakeup_xiaoai = guarded_wake
    # Reuse the same tested, idempotent native-response interruption patch used
    # by the legacy upgrade path; its code is a repository-owned constant.
    exec(BLOCK, {"MiGPT": MiGPT, "asyncio": asyncio})
    install(official_only=True)
    MiGPT._standalone_compat_installed = True


def main():
    config_dir = Path(os.environ.get("XIAOGPT_CONFIG_DIR", "/config"))
    os.environ.setdefault("XIAOGPT_MI_TOKEN_PATH", str(config_dir / ".mi.token"))
    os.environ.setdefault("XIAOGPT_SMART_ROOT", str(config_dir / "smart_voice"))
    install_compatibility()
    from xiaogpt.cli import main as cli_main

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        cli_main()
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()


if __name__ == "__main__":
    main()

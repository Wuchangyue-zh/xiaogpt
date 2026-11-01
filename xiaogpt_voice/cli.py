"""Public command line: init, run and doctor."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__
from .app import VoiceApplication
from .config import AppConfig, data_directory, prepare_voice
from .llm import DeepSeekAssistant, clock_context, load_settings
from .xiaomi import XiaomiGateway, XiaomiError, identity_from


async def run(root: Path):
    config = AppConfig.load(root)
    voice = prepare_voice(root)
    assistant = DeepSeekAssistant(config.api_key, root=voice, base_url=config.base_url)
    gateway = XiaomiGateway(config, root)
    try:
        await gateway.open()
        await VoiceApplication(config, gateway, assistant).serve()
    finally:
        await gateway.close()


def logging_setup():
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    zone = timezone(timedelta(hours=8))
    formatter.converter = lambda timestamp: datetime.fromtimestamp(timestamp, zone).timetuple()
    handler.setFormatter(formatter)
    logger = logging.getLogger("xiaogpt_voice")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logging.getLogger("miservice").disabled = True


def main(argv=None):
    parser = argparse.ArgumentParser(description="XiaoGPT Voice · 小爱音箱 DeepSeek 语音助手")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", type=Path, default=None, help="个人数据目录，默认 ./data 或 XIAOGPT_DATA_DIR")
    sub = parser.add_subparsers(dest="action")
    init = sub.add_parser("init", help="登录小米、选择音箱并验证 DeepSeek")
    init.add_argument("--replace", action="store_true", help="备份并重新配置")
    init.add_argument("--login-again", action="store_true", help="备份缓存并重新登录小米")
    sub.add_parser("run", help="启动语音服务")
    sub.add_parser("doctor", help="检查本地配置，不调用收费接口")
    args = parser.parse_args(argv)
    root = (args.data_dir or data_directory()).resolve()
    logging_setup()
    try:
        if args.action == "init":
            if not sys.stdin.isatty():
                raise ValueError("初始化需要交互终端，请直接运行 docker compose run --rm -i speaker init。")
            from .setup import initialize
            asyncio.run(initialize(root, replace=args.replace, login_again=args.login_again))
        elif args.action == "doctor":
            config = AppConfig.load(root)
            settings = load_settings(prepare_voice(root))
            if not (root / ".mi.token").is_file():
                raise ValueError("小米登录缓存缺失，请运行 init --replace --login-again。")
            if not identity_from(json.loads((root / ".mi.token").read_text())):
                raise ValueError("小米登录缓存不完整，请运行 init --replace --login-again。")
            print("配置校验通过，hardware=" + config.device.hardware + "，model=" + settings["model"])
            print("小米登录缓存：存在")
            print("服务器当前时间：" + clock_context())
        else:
            asyncio.run(run(root))
    except KeyboardInterrupt:
        return 0
    except (ValueError, XiaomiError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print("操作未完成（" + type(exc).__name__ + "），请检查登录状态、网络及日志。", file=sys.stderr)
        return 1
    return 0

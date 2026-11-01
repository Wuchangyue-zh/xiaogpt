"""First-run configuration wizard. Login credentials stay on the user's server."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from smart_deepseek import SmartDeepSeekBot

APP = Path(__file__).resolve().parent


def atomic_json(path: Path, data):
    temp = path.with_name(path.name + ".setup-tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(path)


def prepare_voice_files(config_dir: Path, app_dir: Path = APP) -> Path:
    config_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    voice = config_dir / "smart_voice"
    voice.mkdir(mode=0o700, exist_ok=True)
    for name in ("voice_prompt.txt", "smart_voice.json"):
        target = voice / name
        if not target.exists():
            shutil.copyfile(app_dir / name, target)
            target.chmod(0o600)
    return voice


def select_device(devices, read=input):
    if not devices:
        raise ValueError("当前账号没有可用音箱；请先在小爱音箱 App 绑定设备，并核对账号。")
    for index, device in enumerate(devices, 1):
        print(f'{index}. {device.get("name", "音箱")}  hardware={device.get("hardware", "未知")}  DID={device.get("miotDID", "缺失")}')
    if len(devices) == 1:
        selected = devices[0]
        print("已选择唯一设备。")
    else:
        while True:
            answer = read("选择设备编号：").strip()
            if answer.isdigit() and 1 <= int(answer) <= len(devices):
                selected = devices[int(answer) - 1]
                break
            print("请输入列表中的编号。")
    hardware = str(selected.get("hardware") or "").upper()
    did = str(selected.get("miotDID") or "").strip()
    if not hardware or not did:
        raise ValueError("小米接口没有返回设备 hardware 或 miotDID，未生成配置。")
    return hardware, did


def make_config(user_id, hardware, did, key):
    return {"hardware": hardware, "mi_did": str(did), "account": str(user_id),
            "openai_key": key, "api_base": "https://api.deepseek.com", "bot": "chatgptapi",
            "gpt_options": {"model": "deepseek-flash", "max_tokens": 2048,
                            "extra_body": {"thinking": {"type": "disabled"}}},
            "tts": "mi", "use_command": False, "mute_xiaoai": True, "stream": True,
            "keyword": ["请问"], "start_conversation": "开始持续对话",
            "end_conversation": "结束持续对话", "verbose": False}


def save_config(config_dir: Path, config: dict, *, reconfigure=False):
    path = config_dir / "config.json"
    if path.exists():
        if not reconfigure:
            raise FileExistsError("已有配置；修改时请明确使用 --reconfigure。")
        backups = config_dir / "backups"
        backups.mkdir(mode=0o700, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = backups / ("config-" + stamp + ".json")
        shutil.copyfile(path, backup)
        backup.chmod(0o600)
    atomic_json(path, config)


async def discover_devices(config_dir, user, password, otp):
    from aiohttp import ClientSession, ClientTimeout
    import miservice.miioservice as miio
    from miservice.miaccount import UA_LOGIN
    from miservice import MiNAService
    from xiaogpt.xiaogpt import MiAccount

    miio.UA_MIIO = UA_LOGIN
    async with ClientSession(timeout=ClientTimeout(total=30)) as session:
        account = MiAccount(session, user, password, str(config_dir / ".mi.token"), otp_callback=otp)
        devices = await MiNAService(account).device_list()
        user_id = str((account.token or {}).get("userId") or user)
        return user_id, devices


async def configure(config_dir: Path, *, reconfigure=False, read=input,
                    secret=getpass.getpass, discover=discover_devices, bot_class=SmartDeepSeekBot):
    path = config_dir / "config.json"
    if path.exists() and not reconfigure:
        raise FileExistsError("已有配置；不会覆盖。修改时请先停服务，再运行 configure.py --reconfigure。")
    config_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    cached_user = existing.get("account", "")
    token = config_dir / ".mi.token"
    if token.exists() and not cached_user:
        cached_user = str(json.loads(token.read_text()).get("userId") or "")
    if cached_user and token.exists():
        print("发现已有小米登录缓存，将尝试复用；失效时可能需要重新验证。")
        user, password = cached_user, ""
    else:
        user = read("绑定音箱的小米账号（手机号/邮箱/小米 ID）：").strip() or cached_user
        password = secret("小米账号密码（输入不显示，不写入配置）：")
        if not user or not password:
            raise ValueError("账号或密码为空，未生成配置。")

    async def otp(method):
        return await asyncio.to_thread(secret, "手机或邮箱验证码（输入不显示）：")

    print("正在登录小米并读取设备……")
    user_id, devices = await discover(config_dir, user, password, otp)
    hardware, did = select_device(devices, read=read)
    from xiaogpt.config import HARDWARE_COMMAND_DICT
    if hardware not in HARDWARE_COMMAND_DICT:
        raise ValueError("该 hardware 尚无上游指令映射，请先核对设备兼容性，未生成配置。")
    voice = prepare_voice_files(config_dir)
    settings_path = voice / "smart_voice.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    city = read("常住城市（可留空，不会根据服务器地址猜测）：").strip()
    if city:
        settings["home_city"] = city
        atomic_json(settings_path, settings)
    key = secret("DeepSeek API Key（输入不显示；已有密钥时留空沿用）：").strip() or existing.get("openai_key", "")
    if not key:
        raise ValueError("API Key 为空，未生成配置。")
    config = make_config(user_id, hardware, did, key)
    config["prompt"] = (voice / "voice_prompt.txt").read_text(encoding="utf-8")
    print("正在测试官方搜索和模型回答，会消耗少量 API 余额……")
    bot = bot_class(SimpleNamespace(**config), root=voice)
    answer = await bot.ask("联网查询 DeepSeek 官方目前提供的 API 模型，简短回答。")
    if bot.last_error or bot.last_search_status != "ok" or not answer.strip():
        raise ValueError("联网验证未通过，未保存运行配置。请核对 Key、余额及网络后重试。")
    save_config(config_dir, config, reconfigure=reconfigure)
    print("配置已保存。账号密码和验证码未写入配置；密钥和登录令牌仅保存在本机 data 目录。")


def main():
    parser = argparse.ArgumentParser(description="首次小米登录、音箱选择与 DeepSeek 配置")
    parser.add_argument("--config-dir", default=os.environ.get("XIAOGPT_CONFIG_DIR", "/config"))
    parser.add_argument("--reconfigure", action="store_true")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit("需要交互终端。请运行 docker compose run --rm -i --entrypoint python speaker configure.py")
    os.umask(0o077)
    logging.getLogger("miservice").disabled = True
    try:
        asyncio.run(configure(Path(args.config_dir), reconfigure=args.reconfigure))
    except (ValueError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:
        print("初始化未完成，错误类型：" + type(exc).__name__ + "。请核对登录、验证码和网络后重试。", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

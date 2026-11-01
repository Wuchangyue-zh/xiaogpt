"""Interactive setup for a user's own account, speaker and API key."""
from __future__ import annotations

import getpass
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import prepare_voice, save_config, write_json, write_private
from .llm import DeepSeekAssistant
from .xiaomi import discover


def select_device(devices, read=input):
    if not devices:
        raise ValueError("账号下没有音箱，请先用小爱音箱 App 绑定，并核对登录账号。")
    for index, device in enumerate(devices, 1):
        print(f'{index}. {device.get("name", "音箱")}  {device.get("hardware", "未知型号")}  DID={device.get("miotDID", "缺失")}')
    selected = devices[0]
    if len(devices) > 1:
        while True:
            answer = read("选择音箱编号：").strip()
            if answer.isdigit() and 1 <= int(answer) <= len(devices):
                selected = devices[int(answer) - 1]
                break
            print("请输入列表中的编号。")
    hardware, did = str(selected.get("hardware") or "").upper(), str(selected.get("miotDID") or "")
    if hardware not in ("S12A", "S12"):
        raise ValueError("此型号尚无自动配置模板。请按 README 自定义设备动作后使用。")
    if not did:
        raise ValueError("接口未返回设备 miotDID，未生成配置。")
    return {"name": str(selected.get("name") or "小爱音箱"), "hardware": hardware, "miot_did": did,
            "text_action": [5, 1], "wake_action": [5, 3]}


async def initialize(root: Path, *, replace=False, login_again=False, read=input,
                     secret=getpass.getpass, discovery=discover, assistant_class=DeepSeekAssistant):
    path = root / "config.json"
    if path.exists() and not replace:
        raise ValueError("配置已存在；修改请运行 init --replace，成功后会备份旧配置。")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    token_path = root / ".mi.token"
    if login_again and token_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        write_private(root / "backups" / ("mi-token-" + stamp + ".json"), token_path.read_bytes())
        token_path.unlink()
    account = str((existing.get("xiaomi") or {}).get("account") or "")
    if token_path.exists():
        token = json.loads(token_path.read_text())
        account = str(token.get("userId") or account)
    if account and token_path.exists():
        password = ""
        print("将尝试复用本机的小米登录缓存。")
    else:
        account = read("绑定音箱的小米账号（手机号/邮箱/小米 ID）：").strip() or account
        password = secret("小米账号密码（隐藏输入，不保存）：")
        if not account or not password:
            raise ValueError("账号或密码为空，初始化已取消。")

    async def otp(method):
        return secret("手机或邮箱验证码（隐藏输入）：")

    print("正在读取账号下的音箱……")
    user_id, devices = await discovery(root, account, password, otp)
    device = select_device(devices, read)
    voice = prepare_voice(root)
    settings_path = voice / "assistant.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    city = read("常住城市（可留空）：").strip()
    if city:
        settings["home_city"] = city
        write_json(settings_path, settings)
    key = secret("DeepSeek API Key（隐藏输入，留空沿用已有密钥）：").strip()
    key = key or (existing.get("deepseek") or {}).get("api_key", "")
    if not key:
        raise ValueError("API Key 为空，未保存运行配置。")
    config = {"schema_version": 2, "device": device, "xiaomi": {"account": str(user_id)},
              "deepseek": {"api_key": key, "base_url": "https://api.deepseek.com"},
              "voice": {"trigger_words": ["请问"], "start_phrases": ["开始持续对话", "开始连续对话"],
                        "end_phrases": ["结束持续对话", "结束连续对话"]}, "poll_interval_seconds": 1.2}
    print("正在测试官方搜索和模型回答，会消耗少量 API 余额……")
    assistant = assistant_class(key, root=voice)
    answer = await assistant.ask("联网查询 DeepSeek 官方目前提供的 API 模型，简短回答。")
    if assistant.last_error or assistant.last_search_status != "ok" or not answer.strip():
        raise ValueError("联网验证未通过，未保存运行配置；请核对 Key、余额和网络。")
    print(answer)
    save_config(root, config, replace=replace)
    print("初始化完成。账号密码和验证码未保存，个人配置只保存在本机 data 目录。")

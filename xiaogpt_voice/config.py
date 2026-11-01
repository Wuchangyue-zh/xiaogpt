"""Validated application configuration and private local storage."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULTS = Path(__file__).resolve().parent / "defaults"


def data_directory() -> Path:
    return Path(os.environ.get("XIAOGPT_DATA_DIR", "./data")).expanduser().resolve()


def write_private(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    temp.chmod(0o600)
    temp.replace(path)


def write_json(path: Path, data):
    write_private(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def prepare_voice(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / "voice"
    target.mkdir(exist_ok=True, mode=0o700)
    for name in ("assistant.json", "system_prompt.txt"):
        if not (target / name).exists():
            write_private(target / name, (DEFAULTS / name).read_bytes())
    return target


@dataclass(frozen=True)
class Device:
    hardware: str
    miot_did: str
    name: str = "小爱音箱"
    text_action: tuple[int, int] = (5, 1)
    wake_action: tuple[int, int] = (5, 3)


@dataclass(frozen=True)
class AppConfig:
    device: Device
    account: str = field(repr=False)
    api_key: str = field(repr=False)
    trigger_words: tuple[str, ...] = ("请问",)
    start_phrases: tuple[str, ...] = ("开始持续对话", "开始连续对话")
    end_phrases: tuple[str, ...] = ("结束持续对话", "结束连续对话")
    poll_interval: float = 1.2
    base_url: str = "https://api.deepseek.com"

    @classmethod
    def from_dict(cls, data: dict):
        if not isinstance(data, dict) or data.get("schema_version") != 2:
            raise ValueError("配置格式不正确，请运行 init 配置向导。")
        for section in ("device", "xiaomi", "deepseek", "voice"):
            if not isinstance(data.get(section, {}), dict):
                raise ValueError("配置项必须是对象：" + section)
        device = data.get("device") or {}
        hardware = str(device.get("hardware") or "").upper()
        did = str(device.get("miot_did") or "").strip()
        if not hardware or not did:
            raise ValueError("配置缺少设备 hardware 或 miot_did。")
        if hardware not in ("S12A", "S12") and not all(k in device for k in ("text_action", "wake_action")):
            raise ValueError("此型号需要自行指定 text_action 与 wake_action。")

        def action(name, default):
            value = device.get(name, default)
            if not isinstance(value, (list, tuple)) or len(value) != 2 or any(type(n) is not int or n < 1 for n in value):
                raise ValueError("设备动作应是两个正整数：" + name)
            return tuple(value)

        account = str((data.get("xiaomi") or {}).get("account") or "").strip()
        deepseek = data.get("deepseek") or {}
        if not isinstance(deepseek.get("api_key", ""), str):
            raise ValueError("API Key 必须是字符串。")
        key = deepseek.get("api_key", "").strip()
        if not account or not key:
            raise ValueError("配置缺少小米账号或 DeepSeek API Key。")
        base = deepseek.get("base_url", "https://api.deepseek.com")
        if not isinstance(base, str):
            raise ValueError("base_url 必须是字符串。")
        base = base.rstrip("/")
        if base not in ("https://api.deepseek.com", "https://api.deepseek.com/v1"):
            raise ValueError("当前仅对接 DeepSeek 官方 API。")
        voice = data.get("voice") or {}

        def words(name, default):
            value = voice.get(name, default)
            if not isinstance(value, (list, tuple)) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
                raise ValueError("语音词列表不能为空：" + name)
            return tuple(v.strip() for v in value)

        interval = data.get("poll_interval_seconds", 1.2)
        if type(interval) not in (int, float) or not 0.8 <= interval <= 10:
            raise ValueError("poll_interval_seconds 应在 0.8 到 10 之间。")
        return cls(Device(hardware, did, str(device.get("name") or "小爱音箱"),
                          action("text_action", (5, 1)), action("wake_action", (5, 3))),
                   account, key, words("trigger_words", ("请问",)),
                   words("start_phrases", ("开始持续对话", "开始连续对话")),
                   words("end_phrases", ("结束持续对话", "结束连续对话")), float(interval), base)

    @classmethod
    def load(cls, root: Path):
        path = root / "config.json"
        if not path.is_file():
            raise ValueError("尚未配置，请先运行 docker compose run --rm -i speaker init。")
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8-sig")))


def save_config(root: Path, data: dict, *, replace=False):
    AppConfig.from_dict(data)
    path = root / "config.json"
    if path.exists():
        if not replace:
            raise ValueError("配置已存在；重配请加 --replace，原文件会先备份。")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        write_private(root / "backups" / ("config-" + stamp + ".json"), path.read_bytes())
    write_json(path, data)

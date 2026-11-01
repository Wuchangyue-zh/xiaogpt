"""Transactional installer; run inside the already pinned XiaoGPT image."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from direct_answer_patch import patched_source as add_native_cut

FILES = ("smart_deepseek.py", "smart_voice.json", "voice_prompt.txt")
BEGIN = "# BEGIN smart voice v1"
END = "# END smart voice v1"
HOOK = '''# BEGIN smart voice v1
sys.path.insert(0, "/config/smart_voice")
from smart_deepseek import install as _install_smart_voice
_install_smart_voice()
# END smart voice v1
'''


def atomic(path: Path, data: bytes):
    temp = path.with_name(path.name + ".smart-tmp")
    temp.write_bytes(data)
    temp.chmod(0o600)
    temp.replace(path)


def launcher_source(source: str) -> str:
    if "_miio_client.UA_MIIO = _login_ua" not in source:
        raise ValueError("未找到已验证的 MiIO 登录修复；未修改，请反馈此提示")
    updated = add_native_cut(source)
    if BEGIN in updated:
        if updated.count(BEGIN) != 1 or updated.count(END) != 1:
            raise ValueError("启动器增强标记不完整")
        start, end = updated.index(BEGIN), updated.index(END) + len(END)
        return updated[:start] + HOOK.rstrip() + updated[end:]
    anchor = 'if __name__ == "__main__":'
    if updated.count(anchor) != 1:
        raise ValueError("启动器入口与预期不同")
    return updated.replace(anchor, HOOK + "\n" + anchor, 1)


def snapshot(root: Path) -> Path:
    folder = root / "smart_voice_backups"
    folder.mkdir(mode=0o700, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]
    dest = folder / name
    dest.mkdir(mode=0o700)
    for name in ("config.json", "start_compat.py"):
        atomic(dest / name, (root / name).read_bytes())
    active = root / "smart_voice"
    if active.exists():
        (dest / "smart_voice").mkdir(mode=0o700)
        for name in (*FILES, "last_sources.json"):
            if (active / name).is_file():
                atomic(dest / "smart_voice" / name, (active / name).read_bytes())
    return dest


def restore(root: Path, backup: Path):
    allowed = (root / "smart_voice_backups").resolve()
    backup = backup.resolve()
    if backup.parent != allowed or not (backup / "start_compat.py").is_file() or not (backup / "config.json").is_file():
        raise ValueError("备份路径无效，未执行恢复")
    if (backup / "smart_voice").is_dir():
        (root / "smart_voice").mkdir(mode=0o700, exist_ok=True)
        for name in (*FILES, "last_sources.json"):
            path = backup / "smart_voice" / name
            if path.is_file():
                atomic(root / "smart_voice" / name, path.read_bytes())
    atomic(root / "config.json", (backup / "config.json").read_bytes())
    atomic(root / "start_compat.py", (backup / "start_compat.py").read_bytes())


def deploy(root: Path, stage: Path, *, preflight=True):
    root, stage = root.resolve(), stage.resolve()
    if stage.parent != root or not stage.name.startswith(".smart-stage."):
        raise ValueError("安装暂存目录不在指定配置目录中")
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    if config.get("hardware") != "S12A" or config.get("bot") != "chatgptapi":
        raise ValueError("此安装包仅适用于当前 S12A / chatgptapi 部署")
    source = (root / "start_compat.py").read_text(encoding="utf-8")
    updated = launcher_source(source)
    compile(updated, "start_compat.py", "exec")
    if preflight:
        # Validate against the real installed SDK, Xiaomi service and MiGPT class,
        # loading the new module from staging before changing any live files.
        sys.path.insert(0, str(stage))
        dry = updated.replace('"/config/smart_voice"', json.dumps(str(stage)))
        exec(compile(dry, "compat_preflight", "exec"), {"__name__": "compat_preflight"})
        import smart_deepseek
        smart_deepseek.SmartDeepSeekBot(SimpleConfig(config), root=stage)
    for name in FILES:
        if not (stage / name).is_file():
            raise ValueError("安装文件缺失：" + name)
    prompt = (stage / "voice_prompt.txt").read_text(encoding="utf-8-sig")
    config["prompt"] = prompt
    config["mute_xiaoai"] = True
    config["stream"] = True
    config["verbose"] = False
    options = dict(config.get("gpt_options") or {})
    options["max_tokens"] = 2048
    config["gpt_options"] = options
    backup = snapshot(root)
    try:
        active = root / "smart_voice"
        active.mkdir(mode=0o700, exist_ok=True)
        for name in (*FILES, "last_sources.json"):
            if (stage / name).is_file():
                atomic(active / name, (stage / name).read_bytes())
        atomic(root / "config.json", json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8"))
        atomic(root / "start_compat.py", updated.encode("utf-8"))
        atomic(root / ".smart_voice_latest_backup", backup.name.encode("ascii"))
    except BaseException:
        restore(root, backup)
        raise
    print("安装验证通过；备份目录：smart_voice_backups/" + backup.name)
    return backup


class SimpleConfig:
    def __init__(self, data):
        self.__dict__.update(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["install", "rollback"])
    parser.add_argument("--root", default="/config")
    parser.add_argument("--stage")
    args = parser.parse_args()
    root = Path(args.root)
    if args.action == "install":
        deploy(root, Path(args.stage or Path(__file__).parent))
    else:
        name = (root / ".smart_voice_latest_backup").read_text(encoding="ascii").strip()
        restore(root, root / "smart_voice_backups" / name)
        print("已恢复安装前的启动器和配置。")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, ImportError) as exc:
        # Do not print exception bodies: they may include config or credential data.
        raise SystemExit("安装未完成，错误类型：" + type(exc).__name__) from None

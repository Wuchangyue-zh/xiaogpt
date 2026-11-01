import inspect
import json
import shutil
from pathlib import Path

MARKER = "# BEGIN S12A direct answer v1"
BLOCK = '''# BEGIN S12A direct answer v1
_answer_original_query = MiGPT._get_last_query
_answer_original_stop = MiGPT.stop_if_xiaoai_is_playing
_answer_original_tts = MiGPT.do_tts

def _answer_track_query(self, data):
    record = _answer_original_query(self, data)
    if record:
        self._answer_record = record
    return record

async def _answer_stop_native(self):
    record = getattr(self, "_answer_record", None)
    query = (record or {}).get("query", "").strip()
    controls = (self.config.start_conversation, self.config.end_conversation)
    if (self.config.hardware != "S12A" or not record
            or query in controls or not self.need_ask_gpt(record)):
        return await _answer_original_stop(self)
    if not hasattr(self, "_answer_lock"):
        self._answer_lock = asyncio.Lock()
    async with self._answer_lock:
        stamp = record["time"]
        if getattr(self, "_answer_cut_stamp", None) == stamp:
            return
        self._answer_cut_stamp = stamp
        try:
            code = await asyncio.wait_for(
                self.miio_service.miot_action(
                    str(self.config.mi_did), (5, 1), ["¿ʞо ∩оʎ ǝɹɐ"]
                ), timeout=8,
            )
            if code != 0:
                raise RuntimeError("code=" + str(code))
        except Exception as exc:
            self.log.warning("原声打断失败（%s），继续尝试普通暂停。", type(exc).__name__)
            try:
                await asyncio.wait_for(_answer_original_stop(self), timeout=5)
            except Exception:
                self.log.warning("普通暂停未成功，继续生成大模型回答。")
        else:
            self.log.info("已发送原声静音打断")

async def _answer_quiet_tts(self, value):
    if value == f"正在问{self.chatbot.name}请耐心等待":
        return
    return await _answer_original_tts(self, value)

MiGPT._get_last_query = _answer_track_query
MiGPT.stop_if_xiaoai_is_playing = _answer_stop_native
MiGPT.do_tts = _answer_quiet_tts
# END S12A direct answer v1
'''


def patched_source(source):
    if MARKER in source:
        return source
    anchor = 'if __name__ == "__main__":'
    if source.count(anchor) != 1 or "_miio_client.UA_MIIO = _login_ua" not in source:
        raise SystemExit("启动器与预期不同，未修改；请反馈此提示。")
    return source.replace(anchor, BLOCK + "\n" + anchor, 1)


def main():
    from xiaogpt.xiaogpt import MiGPT

    config = json.loads(Path("/config/config.json").read_text())
    if config.get("hardware") != "S12A" or not config.get("mute_xiaoai"):
        raise SystemExit("硬件或静音配置与预期不同，未修改。")
    if "正在问" not in inspect.getsource(MiGPT.run_forever):
        raise SystemExit("程序版本与预期不同，未修改。")
    path = Path("/config/start_compat.py")
    source = path.read_text(encoding="utf-8")
    updated = patched_source(source)
    exec(compile(updated, str(path), "exec"), {"__name__": "compat_preflight"})
    if updated != source:
        backup = path.with_name("start_compat.py.before-direct-answer")
        if not backup.exists():
            shutil.copy2(path, backup)
        temp = path.with_name("start_compat.py.tmp")
        temp.write_text(updated, encoding="utf-8")
        temp.chmod(0o600)
        temp.replace(path)
    print("验证通过：原声打断和等待提示已调整，原配置保留。")


if __name__ == "__main__":
    main()

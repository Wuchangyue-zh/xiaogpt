from xiaogpt_voice.config import AppConfig


def config_data():
    return {"schema_version": 2, "device": {"hardware": "S12A", "miot_did": "own-test-device", "name": "音箱"},
            "xiaomi": {"account": "own-test-account"}, "deepseek": {"api_key": "test-key-not-real"},
            "voice": {"trigger_words": ["请问"]}, "poll_interval_seconds": 1.2}


def config():
    return AppConfig.from_dict(config_data())

from comms_platform.integrations.ollama import truncate_chat_reply


def test_truncate_chat_reply_keeps_short_text():
    assert truncate_chat_reply("Hello there.", 1800) == "Hello there."


def test_truncate_chat_reply_limits_long_text():
    long_text = "word " * 500
    trimmed = truncate_chat_reply(long_text.strip(), 100)
    assert len(trimmed) <= 100
    assert trimmed.endswith("...")

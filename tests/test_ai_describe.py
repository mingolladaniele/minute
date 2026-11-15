from minute.ai import describe

DS = "https://api.deepseek.com"


def test_rejected_key_opens_settings():
    assert describe("the API key was rejected (Authentication Fails, request_id abc123)", DS) == (
        "DeepSeek rejected the API key.", "settings")


def test_missing_key_opens_settings():
    assert describe("no API key: add one in Settings", DS) == ("No API key is set.", "settings")


def test_forbidden_model_opens_settings():
    assert describe("the API key isn't allowed to use this model", DS)[1] == "settings"


def test_server_error_keeps_retry():
    assert describe("the AI service is down (upstream timeout)", DS) == ("The AI service is down.", "retry")


def test_unknown_host_named():
    assert describe("the API key was rejected", "https://llm.example.org/v1")[0] == "llm.example.org rejected the API key."


def test_local_model_named():
    assert describe("the API key was rejected", "http://localhost:11434/v1")[0] == "The local model rejected the API key."


def test_network_error_keeps_address():
    assert describe("cannot reach https://api.deepseek.com: timed out", DS) == (
        "Cannot reach https://api.deepseek.com: timed out.", "retry")

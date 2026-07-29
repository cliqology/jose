from jose.config import Settings


def test_collector_hardening_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.collector_user_agent == "JOSE-Collector/1.0"
    assert settings.collector_max_redirects == 5
    assert settings.collector_max_response_bytes == 20 * 1024 * 1024

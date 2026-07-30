from jose.services.error_sanitizer import sanitize_error_text


def test_redacts_secret_query_string_params():
    text = "GET https://ats.example.com/jobs?token=abc123&page=2 -> 403 Forbidden"

    result = sanitize_error_text(text)

    assert "abc123" not in result
    assert "token=[redacted]" in result
    assert "page=2" in result


def test_redacts_authorization_header_with_scheme():
    text = "Request failed with headers Authorization: Bearer sk-live-abcdef123456 and Accept: */*"

    result = sanitize_error_text(text)

    assert "sk-live-abcdef123456" not in result
    assert "Authorization: Bearer [redacted]" in result
    assert "Accept: */*" in result


def test_redacts_authorization_header_without_scheme():
    text = "Authorization: abc123xyz"

    result = sanitize_error_text(text)

    assert "abc123xyz" not in result
    assert result == "Authorization: [redacted]"


def test_redacts_cookie_header():
    text = "Cookie: session_id=abc123; csrf=xyz789"

    result = sanitize_error_text(text)

    assert "abc123" not in result
    assert "xyz789" not in result
    assert result == "Cookie: [redacted]"


def test_redacts_userinfo_in_url():
    text = "Connection refused: https://user:s3cr3t@internal.example.com/api"

    result = sanitize_error_text(text)

    assert "s3cr3t" not in result
    assert "https://[redacted]@internal.example.com/api" in result


def test_leaves_non_secret_text_unchanged():
    text = "ConnectionError: timed out after 30s contacting https://boards.example.com/jobs?page=2"

    assert sanitize_error_text(text) == text

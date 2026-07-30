import re

_SECRET_QUERY_KEYS = (
    "access_token",
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "pwd",
    "auth",
    "key",
    "session",
    "signature",
    "sig",
    "credential",
)

_QUERY_PARAM_PATTERN = re.compile(
    r"(?i)\b((?:[a-zA-Z0-9]+_)?(?:"
    + "|".join(_SECRET_QUERY_KEYS)
    + r")(?:_[a-zA-Z0-9]+)?)="
    r"[^&\s\"']+"
)
_AUTH_HEADER_PATTERN = re.compile(r"(?i)\b(authorization:\s*)(?:\S+\s+)?\S+")
_COOKIE_HEADER_PATTERN = re.compile(r"(?i)\b(cookie:\s*)\S.*")
_USERINFO_URL_PATTERN = re.compile(r"(?i)(https?://)[^\s/@]+@")


def sanitize_error_text(text: str) -> str:
    """Redact common secret shapes from error text before it is persisted.

    Covers secret-looking query-string params, Authorization/Cookie header
    values, and userinfo embedded in URLs. Applied once, at the point an
    error is first recorded, so callers never need to sanitize themselves.
    """
    sanitized = _QUERY_PARAM_PATTERN.sub(lambda m: f"{m.group(1)}=[redacted]", text)
    sanitized = _AUTH_HEADER_PATTERN.sub(r"\1[redacted]", sanitized)
    sanitized = _COOKIE_HEADER_PATTERN.sub(r"\1[redacted]", sanitized)
    sanitized = _USERINFO_URL_PATTERN.sub(r"\1[redacted]@", sanitized)
    return sanitized

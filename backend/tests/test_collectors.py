from jose.collectors.registry import detect_adapter, match_known_ats_host
from jose.collectors.utils import canonicalize_url, job_fingerprint, normalize_title


def test_detect_adapter() -> None:
    assert detect_adapter("https://jobs.ashbyhq.com/pear") == "ashby"
    assert detect_adapter("https://boards.greenhouse.io/example") == "greenhouse"
    assert detect_adapter("https://jobs.lever.co/example") == "lever"
    assert detect_adapter("https://example.com/careers") == "jsonld"


def test_match_known_ats_host() -> None:
    assert match_known_ats_host("boards.greenhouse.io") == "greenhouse"
    assert match_known_ats_host("job-boards.greenhouse.io") == "greenhouse"
    assert match_known_ats_host("JOBS.LEVER.CO") == "lever"
    assert match_known_ats_host("jobs.ashbyhq.com") == "ashby"
    assert match_known_ats_host("example.com") is None


def test_url_canonicalization_removes_tracking() -> None:
    value = canonicalize_url("https://Example.com/job/1?utm_source=test&ref=abc#apply")
    assert value == "https://example.com/job/1?ref=abc"


def test_fingerprint_is_stable() -> None:
    first = job_fingerprint(
        "ACME, Inc.", "Chief Operating Officer", "Remote", "https://x/jobs/1", "1"
    )
    second = job_fingerprint(
        "acme inc", "Chief  Operating Officer", "remote", "https://x/jobs/1", "1"
    )
    assert first == second


def test_normalize_title() -> None:
    assert normalize_title("  SVP, Commercial Operations ") == "svp commercial operations"


def test_parse_datetime_accepts_epoch_milliseconds() -> None:
    from jose.collectors.utils import parse_datetime

    parsed = parse_datetime(1785157200000)
    assert parsed is not None
    assert parsed.tzinfo is not None

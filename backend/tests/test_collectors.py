import pytest

from jose.collectors.registry import detect_adapter, match_known_ats_host
from jose.collectors.utils import (
    COMPANY_ALIAS_THRESHOLD,
    FUZZY_MATCH_THRESHOLD,
    TITLE_MATCH_THRESHOLD,
    canonicalize_url,
    fuzzy_match_score,
    job_fingerprint,
    material_hash,
    normalize_title,
)


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


def test_fuzzy_match_score_company_alias_clears_threshold():
    scores = fuzzy_match_score(
        "OpenAI",
        "Software Engineer",
        "San Francisco, CA",
        "OpenAI, Inc.",
        "Software Engineer",
        "San Francisco, CA",
    )
    assert scores["company"] >= COMPANY_ALIAS_THRESHOLD
    assert scores["composite"] >= FUZZY_MATCH_THRESHOLD


def test_fuzzy_match_score_location_wording_clears_threshold():
    scores = fuzzy_match_score(
        "Acme", "Software Engineer", "San Francisco, CA",
        "Acme", "Software Engineer", "SF, CA, US",
    )
    assert scores["composite"] >= FUZZY_MATCH_THRESHOLD


def test_fuzzy_match_score_different_role_stays_below_threshold():
    scores = fuzzy_match_score(
        "Acme", "Backend Engineer", "San Francisco, CA",
        "Acme", "Enterprise Sales Director", "San Francisco, CA",
    )
    assert scores["composite"] < FUZZY_MATCH_THRESHOLD


@pytest.mark.parametrize(
    ("title_a", "title_b"),
    [
        ("Product Manager", "Product Marketing Manager"),
        ("Research Scientist", "Research Engineer"),
        ("Account Executive", "Account Manager"),
    ],
)
def test_fuzzy_match_score_distinct_roles_fail_title_prefilter(title_a, title_b):
    """Same company and location alone put the composite over FUZZY_MATCH_THRESHOLD.

    These are clearly different jobs, so only the title prefilter keeps them out
    of the review queue.
    """
    scores = fuzzy_match_score(
        "Acme", title_a, "San Francisco, CA",
        "Acme", title_b, "San Francisco, CA",
    )
    assert scores["composite"] >= FUZZY_MATCH_THRESHOLD
    assert scores["title"] < TITLE_MATCH_THRESHOLD


@pytest.mark.parametrize(
    ("title_a", "title_b"),
    [
        ("Senior Software Engineer", "Sr. Software Engineer"),
        ("Software Engineer", "Software Engineer II"),
    ],
)
def test_fuzzy_match_score_same_role_retitling_clears_title_prefilter(title_a, title_b):
    scores = fuzzy_match_score(
        "Acme", title_a, "San Francisco, CA",
        "Acme", title_b, "San Francisco, CA",
    )
    assert scores["title"] >= TITLE_MATCH_THRESHOLD
    assert scores["composite"] >= FUZZY_MATCH_THRESHOLD


def test_fuzzy_match_score_unrelated_company_fails_prefilter():
    scores = fuzzy_match_score(
        "Acme Robotics", "Software Engineer", "San Francisco, CA",
        "Zephyr Logistics", "Warehouse Associate", "Austin, TX",
    )
    assert scores["company"] < COMPANY_ALIAS_THRESHOLD


def _snapshot(**overrides):
    base = {
        "title": "Software Engineer",
        "location": "San Francisco, CA",
        "remote_type": None,
        "employment_type": "full_time",
        "compensation_min": 150000,
        "compensation_max": 200000,
        "currency": "USD",
        "department": "Engineering",
        "application_url": "https://acme.example.com/apply/1",
        "description_text": None,
        "description_html": "<p>Build great things.</p>",
    }
    base.update(overrides)
    return base


def test_material_hash_ignores_description_markup_only_changes():
    base = _snapshot()
    reformatted = _snapshot(description_html="<div><p>Build   great things.</p></div>")

    assert material_hash(base) == material_hash(reformatted)


def test_material_hash_changes_on_compensation_change():
    base = _snapshot()
    changed = _snapshot(compensation_min=160000)

    assert material_hash(base) != material_hash(changed)


def test_material_hash_changes_on_description_text_change():
    base = _snapshot()
    changed = _snapshot(description_html="<p>Build great things, remotely.</p>")

    assert material_hash(base) != material_hash(changed)

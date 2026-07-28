import pytest
from pydantic import ValidationError

from jose.collectors.base import CollectedJob


def test_collected_job_rejects_bad_field_type() -> None:
    with pytest.raises(ValidationError):
        CollectedJob(
            company_name="Acme",
            title="Engineer",
            application_url="https://acme.example/jobs/1",
            compensation_min={"not": "a number"},
        )


def test_collected_job_leaves_omitted_optional_fields_none() -> None:
    job = CollectedJob(
        company_name="Acme",
        title="Engineer",
        application_url="https://acme.example/jobs/1",
    )
    assert job.location is None
    assert job.compensation_min is None
    assert job.raw_payload == {}


def test_collected_job_ignores_unknown_fields() -> None:
    job = CollectedJob(
        company_name="Acme",
        title="Engineer",
        application_url="https://acme.example/jobs/1",
        totally_unexpected_field="surprise",
    )
    assert not hasattr(job, "totally_unexpected_field")


def test_collected_job_is_frozen() -> None:
    job = CollectedJob(
        company_name="Acme", title="Engineer", application_url="https://acme.example/jobs/1"
    )
    with pytest.raises(ValidationError):
        job.title = "Changed"

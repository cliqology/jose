# Cloud Infrastructure

This directory intentionally contains provider-neutral documentation during Phase 0/1.

Do not commit provider credentials or generated state files.

The initial cloud deployment requires:

- Managed PostgreSQL
- Web container
- API container
- Worker container
- Scheduled HTTPS request to the API queue endpoint
- Secret management
- HTTPS

Provider-specific deployment files should be added under a named subdirectory only after the host is selected, for example:

```text
infra/cloud/render/
infra/cloud/fly/
infra/cloud/railway/
infra/cloud/aws/
```

# JOSE — Product Requirements Document

**Product name:** JOSE
**Working expansion:** Job Opportunity Search Engine
**Document version:** 1.0
**Product owner:** Scott Hoffman
**Initial user:** Scott Hoffman
**Initial market:** Executive and senior operating job seekers
**Status:** Draft for development
**Primary development tools:** Claude Code, OpenAI Codex and Warp
**Initial deployment:** Local development with an early cloud deployment path
**Ultimate deployment:** Cloud-hosted application with scheduled background processing and human-approved application execution

---

## 1. Product Summary

JOSE is an AI-assisted job discovery, evaluation, application and follow-up platform designed for senior executives and operators.

JOSE will:

1. Continuously collect jobs from selected VC portfolio job boards, company career pages, applicant tracking systems, newsletters and other approved sources.
2. Identify new, changed, removed and reposted jobs.
3. Score each position against the user's professional background and current job-search preferences.
4. Present the strongest opportunities in a daily review dashboard.
5. Allow the user to approve, reject, watch or investigate each job.
6. Prepare tailored, factually accurate application materials.
7. Assist with completing application forms.
8. Require human approval before final submission.
9. Identify legitimate hiring-team and warm-introduction opportunities.
10. Draft—but not automatically send—outreach and follow-up messages.
11. Track applications, communications, interviews and outcomes.
12. Improve recommendations based on explicit user feedback and actual results.

JOSE is not intended to be a mass-application bot. It is intended to operate as a personal executive job-search team: researcher, analyst, application strategist, coordinator and follow-up assistant.

---

## 2. Problem Statement

Senior job searches are fragmented across:

- VC portfolio job boards
- Company career pages
- Applicant tracking systems
- Recruiter newsletters
- Talent networks
- Personal contacts
- Email conversations
- LinkedIn research
- Spreadsheets
- Résumé variants
- Application portals
- Follow-up reminders

Job seekers must repeatedly perform the same work:

- Visit dozens of sites
- Determine which positions are new
- Read lengthy job descriptions
- Assess whether titles accurately reflect responsibility
- Tailor résumés
- Complete repetitive application fields
- Track submissions
- Identify hiring contacts
- Remember when to follow up

Generic job alerts also perform poorly for senior candidates because title matching alone does not capture scope, company stage, commercialization responsibility, operating complexity or executive fit.

JOSE will centralize and automate the repetitive portions of this process while retaining human judgment for consequential actions.

---

## 3. Product Vision

JOSE should feel like a highly organized executive recruiter who:

- Knows the user's actual career history
- Understands what the user wants next
- Reviews the market every day
- Does not recommend obviously junior or irrelevant jobs
- Explains every recommendation
- Never invents accomplishments
- Prepares credible application materials
- Keeps track of every loose end
- Never submits or sends anything consequential without approval

The long-term vision is a cloud-hosted product that could support additional executive candidates while keeping each user's facts, materials, preferences and communications strictly separated.

---

## 4. Product Principles

### 4.1 Human-controlled

JOSE may recommend, draft and prepare. The user must approve:

- An application target
- Material résumé changes
- Custom application answers
- Final application submission
- External outreach
- Follow-up messages

### 4.2 Evidence-based

JOSE may only make claims supported by the user's verified Candidate Truth Bank.

Every tailored résumé bullet, application answer and outreach claim must be traceable to one or more approved facts.

### 4.3 Selective rather than high-volume

JOSE should optimize for:

- Relevance
- Credibility
- Response rate
- Interview rate
- Quality of opportunity

It should not optimize for the number of applications submitted.

### 4.4 Explainable

Every recommendation must explain:

- Why the job fits
- Which parts of the user's background support the fit
- Which requirements are not proven
- Potential concerns
- The recommended application strategy

### 4.5 Low-cost

JOSE should minimize infrastructure and AI expenses by:

- Using deterministic filters before AI evaluation
- Processing jobs in scheduled batches
- Avoiding persistent AI agents
- Caching unchanged results
- Not rescoring unchanged jobs
- Generating application materials only after approval
- Using lower-cost models for classification
- Reserving stronger models for approved opportunities

### 4.6 Cloud-ready from the beginning

JOSE will be developed locally but will not depend on:

- Mac-specific file paths
- SQLite-only database behavior
- Local-only schedulers
- Hard-coded credentials
- Local browser profiles
- Files stored only on one computer

All application components will be containerized and configured through environment variables.

FastAPI officially supports container-based deployment, allowing the same application image to run locally, on a single server or through a managed container service.

---

## 5. Initial User Profile

The initial JOSE user is Scott Hoffman.

### 5.1 Core positioning

Two-time-exited commercial founder-operator with approximately 25 years of experience building and scaling businesses across media, data, advertising technology, SaaS and AI-enabled products.

### 5.2 Priority roles

Initial target roles include:

- Chief Operating Officer
- President
- General Manager
- Business Unit General Manager
- Chief Commercial Officer
- Chief Business Officer
- Managing Director
- SVP Operations
- SVP Commercial Operations
- Head of Commercialization
- Operating Partner
- Portfolio Operations leader

### 5.3 Priority company characteristics

Initial preferences include:

- Approximately 15–150 employees
- Early growth through scale-up stages
- VC-backed, PE-backed or founder-led companies
- SaaS
- Data and analytics
- Media
- Streaming
- MarTech
- AdTech
- AI-enabled B2B software
- Roles involving commercialization, GTM, enterprise sales, operating cadence, margin, forecasting, hiring, partnerships or organizational scale

These preferences must be editable and must not be permanently hard-coded.

---

## 6. Goals

### 6.1 Primary goals

JOSE must:

1. Find relevant opportunities that the user might otherwise miss.
2. Reduce daily job-search research time.
3. Improve the quality and consistency of applications.
4. Prevent duplicate applications and missed follow-ups.
5. Adapt to changing search preferences.
6. Maintain factual integrity.
7. Operate automatically from the cloud.
8. Keep the user in control of external actions.
9. Remain inexpensive for a single user.
10. Create an architecture that can eventually support multiple users.

### 6.2 Success metrics

The initial product will track:

- Number of sources successfully checked
- Number of jobs discovered
- Number of new jobs discovered
- Number of duplicate jobs eliminated
- Percentage of recommendations approved
- Percentage of recommendations marked "incorrect"
- Average number of strong recommendations per day
- Applications completed
- Application completion time
- Recruiter response rate
- Screening-interview rate
- Hiring-manager interview rate
- Outreach response rate
- Follow-ups completed on time
- Cost per reviewed job
- Cost per approved job
- Cost per completed application
- System and collector error rate

---

## 7. Non-Goals

The initial product will not:

- Submit applications without user approval
- Automatically send LinkedIn messages
- Automatically send connection requests
- Scrape private LinkedIn data
- Circumvent CAPTCHA, MFA or security controls
- Invent missing résumé facts
- Answer sensitive demographic questions without saved user instructions
- Automatically negotiate compensation
- Pretend to be the user in live conversations
- Mass-apply to hundreds of jobs
- Purchase contact information
- Send unsolicited bulk email
- Support multiple paying users during the initial phases

---

## 8. Core User Journey

### 8.1 Daily discovery

1. JOSE runs its scheduled collection process.
2. Enabled sources are checked.
3. New jobs are normalized and deduplicated.
4. Existing jobs are checked for changes.
5. Hard filters remove obvious mismatches.
6. Remaining jobs receive an AI-assisted evaluation.
7. The dashboard and daily digest are updated.

### 8.2 Opportunity review

The user opens the Daily Review screen and sees:

- Strong Matches
- Worth Reviewing
- Stretch Opportunities
- Changed Jobs
- Applications Requiring Action
- Follow-ups Due

The user can:

- Approve
- Reject
- Watch
- Request more research
- Mark the score as incorrect
- Change the search profile
- Mark the role as already reviewed or already applied to

### 8.3 Application preparation

After approval:

1. JOSE selects the appropriate base résumé.
2. It maps job requirements to verified candidate facts.
3. It proposes résumé changes.
4. It drafts application answers.
5. It recommends whether a cover letter or executive note is warranted.
6. It prepares an application packet.
7. The user reviews and approves the materials.

### 8.4 Application execution

After material approval:

1. JOSE opens or creates an application session.
2. It fills supported fields.
3. It uploads approved documents.
4. It uses saved answers where confidence is high.
5. It pauses when a question is unfamiliar, sensitive or ambiguous.
6. It presents a final submission summary.
7. The user approves final submission.
8. JOSE records the submission and confirmation.

### 8.5 Follow-up

After submission:

1. JOSE creates follow-up tasks.
2. It identifies relevant contacts from approved sources.
3. It drafts appropriate messages.
4. The user approves and sends each message.
5. JOSE records the interaction and monitors Gmail for relevant responses.

---

## 9. Functional Requirements

### 9.1 Source Registry

JOSE must maintain a configurable registry of job sources.

Each source record must include:

- Source name
- Source URL
- Source category
- Portfolio firm, when applicable
- Collection adapter
- Collection frequency
- Enabled status
- Last attempt
- Last successful run
- Number of jobs found
- Error status
- Error details
- Authentication requirements
- Priority
- Notes

Initial sources will be imported from `VC_Job_Search_Resources.xlsx`.

Source categories include:

- VC portfolio board
- Company career page
- ATS job board
- Newsletter
- Talent network
- User-added source

The user must be able to add, edit, disable and test a source without changing code.

### 9.2 Job Collection

JOSE must support reusable collection adapters.

Initial adapter categories:

- Greenhouse
- Lever
- Ashby
- Structured VC job board
- JSON-LD job posting
- Generic HTML page
- Sitemap or feed
- Newsletter email
- Browser-assisted source

Every adapter must produce the same normalized job schema.

A collection failure must never be interpreted as "zero jobs." JOSE must record and surface the error.

Each collector must have automated tests using saved fixtures.

### 9.3 Job Normalization

Every job must include, when available:

- Company
- Title
- Normalized title
- Description
- Department
- Function
- Location
- Remote status
- Employment type
- Compensation minimum
- Compensation maximum
- Currency
- Equity information
- Application URL
- Original source URL
- Source VC
- ATS type
- External job ID
- Date published
- First seen
- Last seen
- Last changed
- Status
- Description hash

Unknown fields must remain null rather than being guessed.

### 9.4 Deduplication

JOSE must identify jobs appearing across multiple sources.

Deduplication should consider:

- ATS job ID
- Canonical application URL
- Normalized company name
- Normalized title
- Location
- Description similarity
- Publication timing

One canonical job record may have multiple source records.

The dashboard should show every source that surfaced the job.

### 9.5 Change Detection

JOSE must detect:

- New job
- Description changed
- Compensation changed
- Location changed
- Remote status changed
- Job removed
- Job reposted
- Application URL changed

The user must be able to review meaningful changes.

Minor formatting changes should not create unnecessary alerts.

### 9.6 Search Profiles

The user must be able to maintain multiple active search profiles.

Profile fields include:

- Profile name
- Included titles
- Excluded titles
- Minimum seniority
- Included functions
- Excluded functions
- Preferred industries
- Excluded industries
- Preferred company stages
- Preferred company size
- Minimum compensation
- Location preferences
- Remote requirements
- Hybrid locations
- Relocation willingness
- Travel tolerance
- Maximum job age
- Full-time, fractional or advisory preference
- Preferred funding types
- Required responsibilities
- Nice-to-have responsibilities
- Excluded responsibilities
- Minimum recommendation score
- Maximum daily recommendations

Search profiles must be editable through the interface.

Changes should apply to future evaluations and optionally trigger rescoring of existing active jobs.

### 9.7 Rule-Based Filtering

Before using an AI model, JOSE must apply deterministic rules.

Examples:

- Excluded title
- Insufficient seniority
- Internship or entry-level classification
- Unacceptable location
- Excluded industry
- Job too old
- Compensation below threshold
- Wrong employment type
- Previously rejected job
- Duplicate application
- Company on exclusion list

The system must record which rules were applied.

The user must be able to override a rule for an individual job.

### 9.8 AI Relevance Evaluation

AI evaluation will occur only after rule-based filtering.

Evaluation inputs:

- Normalized job description
- Active search profile
- Candidate Truth Bank
- Relevant résumé summary
- Company information
- Prior feedback on similar jobs

Required output:

- Total score from 0–100
- Recommendation category
- Confidence score
- Role and seniority score
- Functional match score
- Industry match score
- Company-stage match score
- Location and compensation score
- Candidate evidence
- Missing or unproven requirements
- Concerns
- Suggested positioning
- Recommended résumé foundation
- Recommended next action

Recommendation categories:

- Strong Apply
- Review
- Stretch
- Watch
- Archive

The system must not treat an AI score as a final decision.

### 9.9 Candidate Truth Bank

JOSE must maintain a structured set of verified candidate facts.

Each fact must include:

- Fact ID
- Category
- Employer or company
- Date range
- Approved wording
- Short version
- Detailed version
- Quantitative values
- Supporting source
- Verification status
- Sensitivity level
- Permitted use
- Last reviewed date

Fact categories include:

- Employment history
- Acquisitions and exits
- Revenue and growth
- Team leadership
- Hiring
- GTM
- Enterprise sales
- Operations
- Forecasting
- Margin improvement
- Partnerships
- Product commercialization
- AI experience
- Board and investor experience
- Education
- Geographic and travel information

Generated claims must reference supporting fact IDs.

Unsupported claims must be blocked.

### 9.10 Résumé Management

JOSE must initially support three approved base résumés:

1. COO / President / GM
2. Commercial and GTM Operator
3. Operations, Scale and Transformation

Each résumé version must include:

- Version ID
- Purpose
- File
- Structured sections
- Approved bullets
- Supporting fact IDs
- Creation date
- Approval status
- Change history

For each approved job, JOSE will propose:

- Executive-summary changes
- Bullet reordering
- Bullet revisions
- Keyword alignment
- Skills emphasis
- Optional bullet removal
- Optional bullet addition

The interface must show:

- Original text
- Proposed text
- Reason for change
- Supporting facts
- Confidence
- Approve or reject control

JOSE must never change:

- Employer names
- Employment dates
- Formal titles
- Exit values
- Quantitative claims

unless the user explicitly approves the change.

### 9.11 Application Packet

Each approved job will receive an Application Packet containing:

- Job snapshot
- Fit analysis
- Requirement-to-evidence matrix
- Approved résumé
- Cover letter or executive note, when appropriate
- Application answers
- Suggested outreach strategy
- Known concerns
- Missing information
- Application URL
- Submission checklist

Application Packets must be versioned and retained.

### 9.12 Application Answer Library

JOSE must maintain approved responses for frequently asked questions.

Categories include:

- Interest in company
- Interest in position
- Reason for job search
- Operating experience
- Startup experience
- Exit experience
- GTM experience
- AI experience
- Team size
- Compensation
- Location
- Travel
- Start date
- Work authorization
- Relocation

Each answer can have:

- Short version
- Standard version
- Detailed version
- Editable placeholders
- Supporting facts
- Approval status
- Questions for which it may be used

Sensitive answers must be marked as requiring explicit confirmation.

### 9.13 Browser-Assisted Applications

JOSE will use Playwright for supported browser automation.

Playwright supports local and CI browser execution and provides official guidance for containerized browser environments.

The application system must:

- Open the application URL
- Identify the ATS
- Start an isolated browser session
- Fill known fields
- Upload approved documents
- Use approved standard answers
- Capture screenshots or a structured activity log
- Pause on unsupported questions
- Pause on CAPTCHA
- Pause on MFA
- Pause on legal declarations
- Pause on demographic questions
- Pause when confidence falls below the configured threshold
- Display a final review
- Require user approval before submission
- Record submission evidence

Browser credentials and cookies must be encrypted and isolated.

### 9.14 Local and Cloud Browser Modes

JOSE must support two browser-execution modes.

**Local assisted mode**

- Browser opens on the user's computer.
- The user can observe and take control.
- Best suited for initial development.
- Useful for CAPTCHA and unusual forms.

**Cloud assisted mode**

- Browser runs in an isolated cloud worker.
- The user receives a secure application-session link.
- The session may be viewed or manually controlled when intervention is needed.
- The cloud worker must have a strict time limit.
- The session must be destroyed after completion.
- Stored browser state must be minimized.

The cloud browser worker will be developed after local application workflows are stable.

### 9.15 Application CRM

JOSE must track the complete application lifecycle.

Statuses:

- Discovered
- Recommended
- Reviewing
- Approved
- Rejected
- Watching
- Research Requested
- Materials Preparing
- Materials Ready
- Awaiting User Answers
- Ready to Apply
- Application in Progress
- Ready to Submit
- Applied
- Follow-up Due
- Recruiter Response
- Interviewing
- Paused
- Employer Rejected
- Withdrawn
- Offer
- Closed

Each application record must include:

- Job
- Search profile
- Score
- Approval date
- Résumé used
- Application packet
- Submission date
- Confirmation
- Custom answers
- Contacts
- Outreach
- Follow-ups
- Responses
- Interview stages
- Outcome
- Notes

### 9.16 Contacts and Relationship Intelligence

JOSE may search approved connected sources such as Gmail and Google Contacts for:

- Existing company contacts
- Previous email conversations
- Recruiter correspondence
- Former colleagues
- VC talent contacts
- Portfolio-company relationships

JOSE must show why a contact is relevant.

JOSE must not automatically message contacts.

Potential contact records include:

- Name
- Email
- Company
- Title
- Relationship source
- Last interaction
- Relationship strength
- Relevant job
- Recommended outreach type

### 9.17 Outreach and Follow-Up

JOSE must draft:

- Warm introduction requests
- Recruiter notes
- Hiring-manager notes
- VC talent-partner outreach
- Application follow-ups
- Interview thank-you messages
- Close-the-loop messages

Every outgoing message must require approval.

Gmail integration should initially create drafts rather than send messages.

Follow-up timing must be configurable.

### 9.18 Daily Digest

JOSE will generate a daily digest containing:

- Strong new matches
- Additional jobs worth reviewing
- Changed jobs
- Source failures
- Applications awaiting approval
- Applications awaiting submission
- Follow-ups due
- Recent employer responses
- Upcoming interviews

The digest may initially appear in the application and as a Gmail draft or email.

The user must be able to change frequency or disable the digest.

### 9.19 Feedback and Learning

The user can provide structured feedback:

- Score too high
- Score too low
- Too junior
- Too senior
- Wrong function
- Wrong industry
- Wrong stage
- Wrong location
- Compensation issue
- Company not interesting
- Role description misleading
- Stronger than expected
- Already known
- Other

JOSE may recommend search-profile changes after repeated patterns.

JOSE must not automatically change important search parameters without approval.

---

## 10. User Interface

### 10.1 Primary Navigation

- Home
- Daily Review
- Jobs
- Applications
- Follow-ups
- Contacts
- Search Profiles
- Résumés
- Candidate Facts
- Sources
- System Health
- Settings

### 10.2 Home Dashboard

The dashboard should show:

- Strong matches today
- Jobs awaiting review
- Application packets awaiting approval
- Applications ready to submit
- Follow-ups due
- Interviews scheduled
- Source problems
- Weekly funnel summary

### 10.3 Job Detail Page

The job page should show:

- Company
- Title
- Location
- Compensation
- Publication date
- Sources
- Full job description
- Fit score
- Score breakdown
- Supporting candidate evidence
- Unproven requirements
- Concerns
- Company notes
- Existing contacts
- Recommended action
- Approval controls

### 10.4 Settings Experience

The user must be able to update search preferences without editing configuration files.

Each parameter change must include:

- Previous value
- New value
- Date changed
- Optional reason
- Whether active jobs should be rescored

---

## 11. Technical Architecture

### 11.1 Architecture Overview

```
 JOSE Web Application
 │
 FastAPI Backend
 │
 ┌────────────────┼────────────────┐
 │ │ │
 PostgreSQL Object Storage Task Records
 │ │
 └────────────── Worker ───────────┘
 │
 ┌──────────────┼──────────────┐
 │ │ │
 Collectors AI Services Browser Worker
 │ │ │
 Job Sources Model APIs Playwright
```

### 11.2 Recommended Stack

**Backend**

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic migrations

**Web interface**

Recommended initial choice:

- Next.js
- TypeScript
- Server-rendered pages where practical
- Component library with accessible defaults

A simpler server-rendered FastAPI interface may be used during initial prototyping, but the API and frontend must remain separated.

**Database**

- PostgreSQL from the beginning
- Local PostgreSQL through Docker Compose
- Managed PostgreSQL in the cloud
- Supabase is a suitable initial managed option because it currently offers a Free plan and supports later paid upgrades.

SQLite should not be the primary database because using PostgreSQL from the start avoids a later database migration.

**Object storage**

Local development:

- Docker-mounted local storage

Cloud:

- S3-compatible object storage

Stored items include:

- Résumés
- Cover letters
- Application packets
- Screenshots
- Submission confirmations
- Source fixtures

**Background jobs**

JOSE will use database-backed tasks during initial phases.

Each task includes:

- Task type
- Payload
- Priority
- Status
- Attempts
- Scheduled time
- Started time
- Completed time
- Error
- Worker ID

This avoids introducing Redis or a complex queue during the MVP.

A dedicated worker process will poll and claim tasks.

Redis or a managed queue may be introduced later if volume requires it.

**Scheduling**

Local development:

- Manual CLI command
- Optional macOS `launchd`

Initial cloud scheduling:

- GitHub Actions scheduled workflow or cloud-provider scheduler

GitHub Actions supports scheduled workflows and manual workflow dispatch. Scheduled executions may occasionally be delayed during periods of high load, so the database must track expected and completed runs rather than assume perfect timing.

Later cloud scheduling:

- Managed cron or scheduled container job
- Scheduler creates tasks rather than performing all work itself

**Browser automation**

- Playwright
- Separate browser worker
- Separate container image
- Version pinned in the project and container
- Isolated sessions
- No shared browser state between users

Playwright recommends matching the project's Playwright version to the version used by the Docker environment.

**Authentication**

Initial local development:

- Development user fixture
- Authentication bypass allowed only in development

Cloud:

- Email-based authentication
- Session expiration
- Multi-factor authentication option
- Role-based access controls prepared for future administrative users

**AI provider layer**

JOSE must not be tightly coupled to one model provider.

Create an internal interface such as:

```
evaluate_job()
tailor_resume()
draft_application_answer()
draft_outreach()
summarize_company()
```

Each function should support:

- Model provider
- Model name
- Temperature
- Token limit
- Prompt version
- Cost
- Latency
- Structured output
- Retry behavior

Initial providers may include OpenAI and Anthropic.

---

## 12. Repository Structure

```
jose/
├── apps/
│   ├── web/
│   └── api/
├── services/
│   ├── worker/
│   ├── collectors/
│   ├── ai/
│   └── browser/
├── packages/
│   ├── database/
│   ├── schemas/
│   ├── prompts/
│   └── shared/
├── migrations/
├── fixtures/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── end_to_end/
├── infra/
│   ├── docker/
│   ├── local/
│   └── cloud/
├── scripts/
├── docs/
├── .github/
│   └── workflows/
├── docker-compose.yml
├── CLAUDE.md
├── AGENTS.md
├── README.md
└── .env.example
```

---

## 13. Cloud Portability Requirements

JOSE must meet these requirements from the first commit:

1. Every runtime component has a Dockerfile.
2. Local development runs through Docker Compose.
3. All configuration uses environment variables.
4. Database schema changes use migrations.
5. Files are accessed through a storage interface.
6. Scheduled tasks can be invoked through CLI commands or HTTP endpoints.
7. Workers do not depend on a local user session.
8. Job runs are idempotent.
9. Tasks can safely retry.
10. Secrets are never committed.
11. Logs are structured.
12. Health-check endpoints are available.
13. Development, staging and production environments are separated.
14. AI providers are abstracted.
15. Application URLs and source adapters are configurable.
16. The web application does not directly execute long-running collection jobs.
17. Browser automation runs in a separate process or container.
18. The system can run with one combined worker initially and split workers later.

---

## 14. Data Model

Primary entities:

- User
- UserPreference
- SearchProfile
- Source
- SourceRun
- Company
- Job
- JobSource
- JobVersion
- JobEvaluation
- EvaluationFeedback
- CandidateFact
- Résumé
- RésuméVersion
- ApplicationPacket
- Application
- ApplicationAnswer
- Contact
- ContactRelationship
- OutreachMessage
- FollowUp
- Interview
- Task
- AIRequest
- SystemEvent
- AuditLog

Every user-owned record must include `user_id`, even while JOSE has only one user. This prevents a difficult multi-user conversion later.

---

## 15. Security and Privacy

JOSE will store sensitive professional and communication data.

Requirements:

- Encryption in transit
- Managed-database encryption at rest
- Secrets stored outside the repository
- Least-privilege API permissions
- OAuth tokens encrypted
- Refresh tokens protected
- Audit logging
- User-level data separation
- Automatic session expiration
- Backups
- Restore testing
- Data export
- Data deletion
- Browser-session isolation
- Short-lived browser workers
- No credentials stored in logs
- No job-description text included in error-reporting tools unless explicitly allowed
- No résumé or email content used for model training where the selected API configuration provides an opt-out or no-training mode

---

## 16. AI Guardrails

JOSE must enforce:

### 16.1 No unsupported facts

Generated career claims must reference Candidate Fact IDs.

### 16.2 No silent assumptions

Unknown information must be marked as unknown.

### 16.3 Structured outputs

Job evaluations and résumé changes must use validated structured schemas.

### 16.4 Confidence thresholds

Low-confidence outputs require user review.

### 16.5 Prompt versioning

Every AI-generated artifact must retain:

- Prompt version
- Model
- Timestamp
- Input references
- Output
- Cost
- User decision

### 16.6 Sensitive questions

JOSE must not autonomously answer questions concerning:

- Demographics
- Disability
- Veteran status
- Criminal history
- Work authorization
- Compensation
- Relocation
- Legal declarations
- Conflicts of interest

unless an approved answer exists and the user has authorized its use.

---

## 17. Cost Requirements

### 17.1 MVP cost target

Target infrastructure cost:

- Local development: approximately $0 beyond existing development subscriptions
- Initial cloud hosting: $0–$20 per month
- AI API usage: separately metered and capped
- Browser automation: executed only when needed

These are product cost targets, not guarantees.

### 17.2 Cost controls

JOSE must provide:

- Monthly AI budget
- Daily AI budget
- Per-feature model selection
- Maximum jobs scored per run
- Token logging
- Cached evaluation reuse
- Alerts at 50%, 75% and 90% of budget
- Hard-stop option
- Model fallback
- User-visible estimated cost before bulk rescoring

### 17.3 Cost-saving order of operations

```
Collect
  ↓
Normalize
  ↓
Deduplicate
  ↓
Apply free rules
  ↓
Reuse cached results
  ↓
Use inexpensive AI classification
  ↓
Use stronger AI only for approved jobs
```

---

## 18. Development Phases

### Phase 0 — Product and Engineering Foundation

**Objective**

Establish the cloud-ready codebase and development environment.

**Deliverables**

- GitHub repository
- CLAUDE.md
- AGENTS.md
- Docker Compose
- PostgreSQL
- FastAPI service
- Initial web application
- Worker service
- Database migrations
- Development authentication
- Environment configuration
- Logging
- Testing framework
- CI workflow
- Health checks
- Initial cloud architecture documentation

**Acceptance criteria**

- One command starts the full local environment.
- Database migrations run automatically or through one documented command.
- API, web and worker services communicate successfully.
- Tests run in CI.
- No application secret is committed.
- The same backend container can run locally or on a container host.

### Phase 1 — Source Registry and Job Discovery

**Objective**

Collect and normalize jobs from the existing spreadsheet sources.

**Deliverables**

- Spreadsheet importer
- Source Registry interface
- Source test function
- Initial Greenhouse adapter
- Initial Lever adapter
- Initial Ashby adapter
- Generic structured-page adapter
- Source-run logging
- Job normalization
- Deduplication
- Change detection
- Source Health screen
- Manual collection command
- Scheduled cloud collection workflow

**Acceptance criteria**

- Existing spreadsheet sources are imported.
- Enabled sources can be run from the dashboard.
- New jobs are stored.
- Duplicate jobs are merged.
- Removed and changed jobs are detected.
- Source errors are visible.
- A scheduled cloud job can run collection without Scott's Mac.

### Phase 2 — Search Profiles, Scoring and Daily Review

**Objective**

Turn collected jobs into useful recommendations.

**Deliverables**

- Search Profile interface
- Hard-filter engine
- Candidate summary
- AI evaluation service
- Score breakdown
- Daily Review screen
- Approve, reject, watch and research actions
- Feedback reasons
- Daily digest
- AI usage and cost tracking
- Cached evaluations

**Acceptance criteria**

- Search parameters can be changed without code.
- Jobs are filtered before AI evaluation.
- Every scored job includes an explanation.
- Every candidate claim references verified evidence.
- Approved and rejected jobs retain decision history.
- Daily review runs from the cloud.
- The user can cap daily AI spending.

### Phase 3 — Candidate Truth Bank and Résumé Tailoring

**Objective**

Create factual, job-specific application materials.

**Deliverables**

- Candidate Truth Bank
- Fact import from résumé
- Fact verification interface
- Three base résumé versions
- Résumé parser
- Requirement-to-evidence mapping
- Résumé tailoring agent
- Before-and-after comparison
- Fact-reference validation
- Application Answer Library
- Application Packet
- PDF and DOCX export

**Acceptance criteria**

- No generated claim can be approved without supporting facts.
- Résumé changes are individually reviewable.
- Employer names, dates and metrics are protected.
- Approved application packets are versioned.
- Documents can be generated from the cloud.

### Phase 4 — Application CRM and Local Browser Assistant

**Objective**

Track applications and reduce repetitive form completion.

**Deliverables**

- Application CRM
- Application statuses
- Local Playwright runner
- Greenhouse application workflow
- Lever application workflow
- Ashby application workflow
- Standard-field mapping
- Document upload
- Answer-library integration
- Intervention queue
- Final review screen
- Submission confirmation capture
- Duplicate-application prevention

**Acceptance criteria**

- JOSE can open and fill supported applications.
- Unknown questions cause a pause.
- Sensitive questions cause a pause.
- CAPTCHA and MFA cause a pause.
- The user must approve final submission.
- Completed applications update the CRM.

### Phase 5 — Cloud Browser Execution

**Objective**

Allow application assistance to run without relying on the user's computer.

**Deliverables**

- Isolated cloud browser worker
- Browser-task queue
- Short-lived browser containers
- Secure browser-session access
- Manual takeover mode
- Session expiration
- Browser-state encryption
- Screenshot and activity log
- Automatic cleanup
- Resource and cost limits

**Acceptance criteria**

- A cloud worker can complete a supported application session.
- The user can securely review or take control.
- Sessions are isolated.
- Browser resources are destroyed after completion.
- Final submission still requires user approval.
- Cloud browser spending is capped.

### Phase 6 — Gmail, Contacts and Follow-Up

**Objective**

Coordinate legitimate outreach and prevent missed follow-ups.

**Deliverables**

- Gmail connection
- Google Contacts connection
- Existing-relationship search
- Recruiter-response detection
- Outreach drafts
- Follow-up rules
- Gmail draft creation
- Follow-up dashboard
- Interview thank-you workflow
- Communication history

**Acceptance criteria**

- JOSE can identify relevant existing correspondence.
- Messages are created as drafts.
- No email is sent without approval.
- Follow-up tasks appear on the correct date.
- Replies update the associated application.

### Phase 7 — Optimization and Outcome Learning

**Objective**

Improve JOSE using actual application outcomes.

**Deliverables**

- Funnel analytics
- Source-performance reporting
- Recommendation-quality reporting
- Score-versus-outcome analysis
- Résumé-version performance
- Outreach-performance reporting
- Search-profile recommendations
- Prompt testing
- Model cost comparisons
- Collector reliability dashboard

**Acceptance criteria**

- JOSE can show which sources produce interviews.
- JOSE can show which scores correlate with responses.
- Search changes are proposed, not silently applied.
- AI costs are visible by feature.
- Poor-performing sources can be disabled.

### Phase 8 — Optional Multi-User Productization

**Objective**

Prepare JOSE for use by other executive candidates.

**Deliverables**

- Production authentication
- Tenant isolation
- User onboarding
- Résumé onboarding workflow
- Subscription and usage limits
- Administrative console
- User data export and deletion
- Terms and privacy materials
- Provider usage controls
- Production monitoring
- Support workflow

This phase is explicitly outside the initial personal-product scope.

---

## 19. Testing Strategy

JOSE requires:

**Unit tests**

- Title normalization
- Deduplication
- Search filters
- Score calculations
- Fact validation
- Status transitions
- Follow-up calculations

**Collector tests**

- Saved HTML and JSON fixtures
- Missing fields
- Changed markup
- Pagination
- Rate limits
- Invalid URLs
- Empty results
- Authentication failure

**Integration tests**

- Collector to database
- Scoring to dashboard
- Approval to Application Packet
- Application to follow-up
- Gmail draft creation

**Browser tests**

- Greenhouse fixture
- Lever fixture
- Ashby fixture
- Unknown question
- File upload
- CAPTCHA pause
- Final-submit approval

**AI evaluation tests**

Use a fixed test set containing:

- Strong matches
- Weak matches
- Misleading titles
- Senior titles with junior scope
- Adjacent industries
- Missing requirements
- Duplicate descriptions

Changes to prompts or models must be evaluated against the fixed test set.

---

## 20. Operational Requirements

JOSE must provide:

- Source-run logs
- Worker logs
- Error tracking
- Failed-task retry
- Dead-letter task status
- Database backups
- Restore documentation
- Health checks
- Usage reporting
- AI cost reporting
- Browser cost reporting
- Manual rerun
- Run cancellation
- Source disable control
- Maintenance mode

---

## 21. Initial Command-Line Interface

Development commands should include:

```
jose dev
jose test
jose migrate
jose import-sources
jose collect
jose collect --source <source-id>
jose score
jose daily
jose worker
jose browser-worker
jose seed
jose backup
```

These commands should work through Warp and inside the relevant Docker containers.

---

## 22. Definition of MVP

The MVP is complete when JOSE can:

1. Run from a cloud environment.
2. Import and manage the existing source spreadsheet.
3. Collect jobs from the primary VC and ATS sources.
4. Detect new and changed jobs.
5. Deduplicate jobs.
6. Apply configurable rules.
7. Score credible jobs against Scott's background.
8. Explain every recommendation.
9. Display a cloud-hosted Daily Review dashboard.
10. Allow jobs to be approved, rejected or watched.
11. Track decisions.
12. Create a daily digest.
13. Track system and AI costs.

Application tailoring and browser-assisted submission are not required for the initial discovery MVP, but the architecture must already accommodate them.

---

## 23. Key Risks

**Source instability**

Job boards may change markup or block automated access.

Mitigation: Adapter isolation, source health tracking, fixtures, browser fallback and rapid adapter testing.

**AI hallucination**

Models may invent experience or overstate fit.

Mitigation: Candidate Truth Bank, fact references, structured output and human approval.

**Application-form inconsistency**

Application forms vary widely.

Mitigation: ATS-specific adapters, intervention queue and final human review.

**Cloud-browser cost**

Remote browser sessions can consume significant resources.

Mitigation: Short-lived workers, job-specific execution, strict timeouts and local-assisted fallback.

**Excessive recommendations**

The system may create noise instead of saving time.

Mitigation: Daily recommendation caps, strong hard filters and feedback-based tuning.

**Over-automation**

The system could produce generic or inappropriate outreach.

Mitigation: Draft-only communication and explicit approval.

**Platform restrictions**

Some sites may prohibit or technically restrict automated activity.

Mitigation: Source-by-source rules, conservative automation, no bypassing controls and the ability to disable automation for a source.

---

## 24. Product Decisions Already Made

- Product name is JOSE.
- JOSE is cloud-ready from the beginning.
- PostgreSQL will be used rather than SQLite.
- Components will be containerized.
- The first user is Scott.
- JOSE will be selective rather than high-volume.
- Applications require user approval.
- External messages require user approval.
- Candidate claims require verified facts.
- AI scoring occurs only after deterministic filtering.
- Browser automation will be separated from the main web application.
- The AI provider will be replaceable.
- The system will be built with Claude Code and Codex through Warp.
- n8n is not required for the MVP.
- Cloud discovery and scoring will be delivered before cloud browser execution.

---

## 25. Outstanding Product Decisions

The following decisions can be made during implementation without changing the core PRD:

- Exact initial cloud container host
- Next.js versus a simpler initial web interface
- Supabase versus another managed PostgreSQL provider
- Gmail digest versus in-application digest only
- Initial AI model assignments
- Exact follow-up timing
- Whether résumé source files are DOCX, structured JSON or both
- Whether remote browser takeover uses a web viewer or local handoff
- Which five sources receive the first production-quality adapters

---

## 26. Recommended First Build Milestone

The first milestone should produce:

- Running Docker Compose environment
- PostgreSQL database
- FastAPI backend
- Basic web interface
- Source Registry
- Spreadsheet import
- One working ATS adapter
- Job table
- Source-run logging
- Manual collection
- Basic deduplication
- Automated tests
- GitHub Actions CI
- A cloud deployment of the same containers

This milestone proves the central architectural decision: JOSE can be developed locally and run from the cloud without maintaining two separate versions.

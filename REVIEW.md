# Code review

This review covers the starter implementation, before fixes. Findings are ranked by expected business impact. The first finding is the priority fix for Part 2; its decisive lines are `app/routers/introductions.py:19-20`, where caller-supplied member IDs are used without checking either member's club, followed by `:23-25`, where all returned attributes become response text.

## 1. Cross-club introduction exposes restricted member data

- **Location:** `app/routers/introductions.py:19-25`
- **Category:** Data Isolation / Security
- **Severity:** Critical
- **Description:** Any authenticated member can supply arbitrary member IDs, including IDs from another club, and the endpoint returns those members' attribute text. It also includes `restricted=True` attributes, so a Riverside member can receive an Oakhurst member's private health information; the token check in `get_current_member` proves only that the caller is a member somewhere and does not authorize either requested ID.
- **Recommended fix:** Resolve both members under the caller's `club_id` and reject missing or cross-club IDs before loading attributes. Filter restricted attributes from introduction input and output, apply a confidence threshold, and return an insufficient-basis response when no eligible attributes remain.

### Literal request/response trace

Run against the unmodified FastAPI route using `DATABASE_URL=sqlite:// .venv/bin/python -m scripts.review_trace`. This is an in-process ASGI HTTP request with an isolated SQLite database containing one Riverside caller and one Oakhurst member with a restricted health attribute; it does not alter the repository's seed data. The runner executes synchronous FastAPI callables directly because worker-thread scheduling hangs in this environment.

```http
GET /introductions/1/2?reason=business
X-Member-Token: riverside-member-1

HTTP 200
{"reason_text": "Because  and recently diagnosed with a chronic condition — a good business match."}
```

The response above is the literal body returned by the running app, not an expected result. The empty text before `and` is another sign that the endpoint has no grounding or eligibility check.

## 2. Knowledge search crosses club boundaries

- **Location:** `app/routers/knowledge.py:19-20, 28-35`
- **Category:** Data Isolation
- **Severity:** Critical
- **Description:** The route verifies that the caller belongs to the club named in the URL, but the similarity query searches `KnowledgeChunk` rows from every club. Consequently, a valid Riverside query can return Oakhurst policy text and disclose another club's knowledge; the nearby URL authorization check does not constrain the database result set.
- **Recommended fix:** Add `KnowledgeChunk.club_id == member.club_id` to the similarity query before ordering and limiting, and test that even a query closest to another club's chunk returns only the caller's club.

## 3. Caller controls the payment amount

- **Location:** `app/routers/bookings.py:20-29, 33-41`; `app/schemas.py:4-5`
- **Category:** Data Integrity / Security
- **Severity:** Critical
- **Description:** The booking lookup proves ownership, but `confirm_payment` charges `payload.amount_cents` without comparing it to the booking's stored `amount_cents`. A member can submit a small positive amount for an expensive booking and still cause its status to become `confirmed`; the schema checks only that the amount is an integer.
- **Recommended fix:** Derive the charge amount from the server-side booking, reject unexpected client amounts if the request retains that field, and confirm only after a successful charge for the stored amount.

## 4. Payment retries can create duplicate charges

- **Location:** `app/routers/bookings.py:20-41`; `app/services/session_flow.py:31-54`; `app/models.py:91-99`
- **Category:** Data Integrity
- **Severity:** Critical
- **Description:** The direct payment endpoint can charge an already confirmed booking again, and the session flow charges before persisting a durable attempt or idempotency key. A retry after a crash at `session_flow.py:38-39` can therefore charge a second time while the database still shows an awaiting-confirmation session; `PaymentAttempt.idempotency_key` exists but is never used in either flow.
- **Recommended fix:** Use a stable booking or session payment key with provider-side idempotency, persist and reconcile an attempt around ambiguous outcomes, and make already successful confirmations return the prior result. Lock or atomically claim the payment transition so concurrent requests cannot both charge.

## 5. Restricted attributes feed matching scores

- **Location:** `app/services/matching_service.py:9-12, 33-40`; `scripts/seed.py:193-195`; `app/services/embedding_pipeline.py:9-13`
- **Category:** Security / Data Integrity
- **Severity:** High
- **Description:** `build_member_profile_text` includes every attribute, including restricted health information, in the text used for ranking and stored profile embeddings. Even if the query-side text were filtered later, the seeded and refreshed candidate embeddings would still encode restricted attributes, affecting who is recommended.
- **Recommended fix:** Exclude `restricted=True` attributes in the shared profile builder, rebuild existing profile embeddings from eligible data, and test both the requesting member's query vector and candidate vectors against restricted-only examples.

## Verification limits

The live trace above exercises the first finding through FastAPI's ASGI interface with isolated SQLite data, not the seeded PostgreSQL database. After PostgreSQL access became available, the existing test suite passed (`7 passed`) using an explicit `postgresql+psycopg` test URL; its default `psycopg2` URL still selects an uninstalled driver. Findings 2–5 are supported by code-path analysis rather than live endpoint traces.

The existing, uncommitted `.env.example` edit contains what appears to be an Airtable personal access token. Keep that value out of commits and submission artifacts; if it is a real token, revoke or rotate it. This review did not change the file or reproduce the token.

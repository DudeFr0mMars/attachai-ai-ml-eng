# Code review

This review describes the starter implementation before fixes. Findings are ranked by expected business impact; the knowledge leak is first because any member could retrieve another club's knowledge without knowing member IDs, and the query returned up to five chunks at once. All five findings have since been addressed within the agreed scope; the historical traces remain as evidence.

## 1. Knowledge search crosses club boundaries — fixed in Part 2

- **Location:** `app/routers/knowledge.py:19-20, 24-29` (current code; the missing filter was between the query and ordering calls in the starter revision)
- **Category:** Data Isolation
- **Severity:** Critical
- **Description:** The route verifies that the caller belongs to the club named in the URL, but the similarity query searched `KnowledgeChunk` rows from every club. Consequently, a valid Riverside query returned Oakhurst policy text; the nearby URL authorization check did not constrain the database result set.
- **Recommended fix:** Add `KnowledgeChunk.club_id == member.club_id` to the similarity query before ordering and limiting, and test that even a query closest to another club's chunk returns only the caller's club. This is now implemented and verified by the regression test and seeded-database traces.

### Literal seeded-database trace before and after

Both responses were returned by `DATABASE_URL=postgresql+psycopg://kindred:kindred@localhost:5432/kindred .venv/bin/python -m scripts.knowledge_trace` through FastAPI's in-process HTTP test client against the seeded PostgreSQL database. The request is read-only; full output is in `TERMINAL_LOG.md`.

```http
GET /clubs/riverside/knowledge/query?q=guest%20fees
X-Member-Token: riverside-member-1

Before — HTTP 200
[{"chunk_id": 17, "club_id": "riverside", "title": "Guest fees", "body": "Riverside guest fees are $50 per visit, waived for members' immediate family."}, {"chunk_id": 22, "club_id": "oakhurst", "title": "Dress code", "body": "Oakhurst requires collared shirts in all dining areas, no exceptions."}, {"chunk_id": 18, "club_id": "riverside", "title": "Dress code", "body": "Riverside's dress code is smart casual after 6pm, resort wear during the day."}, {"chunk_id": 23, "club_id": "oakhurst", "title": "Opening hours", "body": "Oakhurst is open 6am to midnight, the pool closes at 9pm."}, {"chunk_id": 20, "club_id": "riverside", "title": "Cancellation policy", "body": "Riverside bookings can be cancelled up to 24 hours ahead for a full refund."}]

After — HTTP 200
[{"chunk_id": 17, "club_id": "riverside", "title": "Guest fees", "body": "Riverside guest fees are $50 per visit, waived for members' immediate family."}, {"chunk_id": 18, "club_id": "riverside", "title": "Dress code", "body": "Riverside's dress code is smart casual after 6pm, resort wear during the day."}, {"chunk_id": 20, "club_id": "riverside", "title": "Cancellation policy", "body": "Riverside bookings can be cancelled up to 24 hours ahead for a full refund."}, {"chunk_id": 19, "club_id": "riverside", "title": "Opening hours", "body": "Riverside is open 7am to 11pm daily, kitchen closes at 10pm."}]
```

These are the literal response bodies from the running app, also preserved in `TERMINAL_LOG.md`.

## 2. Cross-club introduction exposes restricted member data — fixed

- **Location:** `app/routers/introductions.py:19-25`
- **Category:** Data Isolation / Security
- **Severity:** Critical
- **Description:** Any authenticated member can supply arbitrary member IDs, including IDs from another club, and the endpoint returns those members' attribute text. It also includes `restricted=True` attributes, so a Riverside member can receive an Oakhurst member's private health information; the token check in `get_current_member` proves only that the caller is a member somewhere and does not authorize either requested ID.
- **Recommended fix:** Resolve both members under the caller's `club_id` and reject missing or cross-club IDs before loading attributes. Filter restricted attributes from introduction input and output, apply a confidence threshold, and return an insufficient-basis response when no eligible attributes remain.

The pre-fix isolated reproduction and post-fix seeded-PostgreSQL HTTP 404 response are in `TERMINAL_LOG.md`. The seeded trace also verifies a restricted-only same-club member yields insufficient basis. Focused PostgreSQL tests cover both cross-club ID positions, restricted attributes, low-confidence attributes, and valid same-club introductions.

## 3. Caller controls the payment amount — fixed for existing bookings

- **Location:** `app/routers/bookings.py:20-29, 33-41`; `app/schemas.py:4-5`
- **Category:** Data Integrity / Security
- **Severity:** Critical
- **Description:** The booking lookup proves ownership, but `confirm_payment` charges `payload.amount_cents` without comparing it to the booking's stored `amount_cents`. A member can submit a small positive amount for an expensive booking and still cause its status to become `confirmed`; the schema checks only that the amount is an integer.
- **Recommended fix:** Derive the charge amount from the server-side booking, reject unexpected client amounts if the request retains that field, and confirm only after a successful charge for the stored amount.

The direct confirmation route now checks the submitted amount against `Booking.amount_cents` before both new charges and confirmed replays, then uses the stored amount for the attempt and provider call. Regression tests cover zero, tiny, and other mismatched amounts. The session flow creates a new booking from a caller-provided amount and has no server-side price/quote; per the user's scope decision, that separate pricing policy was not invented here.

## 4. Payment retries can create duplicate charges — fixed with reconciliation limit

- **Location:** `app/routers/bookings.py:20-41`; `app/services/session_flow.py:31-54`; `app/models.py:91-99`
- **Category:** Data Integrity
- **Severity:** Critical
- **Description:** The direct payment endpoint can charge an already confirmed booking again, and the session flow charges before persisting a durable attempt or idempotency key. A retry after a crash at `session_flow.py:38-39` can therefore charge a second time while the database still shows an awaiting-confirmation session; `PaymentAttempt.idempotency_key` exists but is never used in either flow.
- **Recommended fix:** Use a stable booking or session payment key with provider-side idempotency, persist and reconcile an attempt around ambiguous outcomes, and make already successful confirmations return the prior result. Lock or atomically claim the payment transition so concurrent requests cannot both charge.

Both paths now commit an initiated attempt before the first charge, keyed by booking or session ID, and reuse the recorded result on replay. A pending attempt uses lookup, not another charge. The mock provider's keyed outcome survives requests in one process but not process-state loss; when it cannot resolve a durable pending attempt, the API returns HTTP 504 for reconciliation without charging again. Thus duplicate-charge prevention is tested, while automatic recovery after lost provider state is not claimed.

## 5. Restricted attributes feed matching scores — fixed

- **Location:** `app/services/matching_service.py:9-12, 33-40`; `scripts/seed.py:193-195`; `app/services/embedding_pipeline.py:9-13`
- **Category:** Security / Data Integrity
- **Severity:** High
- **Description:** `build_member_profile_text` includes every attribute, including restricted health information, in the text used for ranking and stored profile embeddings. Even if the query-side text were filtered later, the seeded and refreshed candidate embeddings would still encode restricted attributes, affecting who is recommended.
- **Recommended fix:** Exclude `restricted=True` attributes in the shared profile builder and ensure both score vectors derive from eligible text. Ranking now recomputes both sides from filtered attributes, so legacy stored embeddings cannot influence scores; future refreshes also use the filtered builder. Regression tests cover restricted-only candidate data and legacy vectors.

## Verification limits

The Part 2 knowledge trace uses the seeded PostgreSQL database, and the new regression test failed before the filter and passed afterward. The *historical pre-fix* introduction reproduction used isolated SQLite data; it is not proof of behavior on the seed. The replacement post-fix trace runs read-only against seeded PostgreSQL and checks cross-club rejection, restricted-only introduction output, and matching score (`0.0`) for that seeded member. The introduction and matching regression suite passed (`9 passed`) against PostgreSQL, including a legacy restricted-only embedding case. Payment regressions failed before the fixes and the full PostgreSQL test suite passed afterward (`29 passed`); payment confirmation was not run against the production seed because it would mutate bookings. The mock-provider recovery caveat above remains. Part 3 extraction and its real `eval/golden_set.json` evaluation have not been run yet.

The existing, uncommitted `.env.example` edit contains what appears to be an Airtable personal access token. Keep that value out of commits and submission artifacts; if it is a real token, revoke or rotate it. This review did not change the file or reproduce the token.

# Design notes

These notes distinguish current code from planned work. Update the pending answers from the implementation and actual eval before submission.

## Part 2 — multi-turn session flow

In `app/services/session_flow.py:31-54`, `advance_turn` calls `payment_mock_client.charge` at line 36 before saving a booking or `PaymentAttempt`; the simulated crash at lines 38-39 leaves the session awaiting confirmation even though the provider recorded a charge. A retry can charge again, so the fix should claim the payment transition and use a stable provider idempotency key, then reconcile an ambiguous result before allowing another charge; `app/models.py:96` already provides an `idempotency_key` field, but the current payment client does not accept one. This session-flow issue remains open; the selected Part 2 fix addresses the cross-club knowledge leak.

## Part 2 — knowledge isolation fix

`app/routers/knowledge.py` first verifies that the URL club matches the authenticated member's club, then filters `KnowledgeChunk.club_id == member.club_id` in SQL before cosine-distance ordering and `limit(5)`. Filtering after the limit was rejected: an Oakhurst chunk could occupy one of the five slots and displace a valid Riverside result even if removed from the final response. The regression test places a more similar Oakhurst chunk in the database and asserts that the response contains only the Riverside chunk; the seeded-database before/after trace is in `TERMINAL_LOG.md`.

## Part 3 — structured extraction pipeline

**Status:** Pending. No extraction endpoint, real LLM call, or eval run has been implemented yet.

### Idempotency

**Exact processed-message key in code:** Pending implementation. The existing schema has `MemberAttribute.source_message_id`, but the current code has no extraction pipeline or processed-message check; the final note must state the exact key expression used, including how messages yielding zero attributes are treated. The idempotency check must prevent duplicate rows on repeat requests and be verified with a second run in `TERMINAL_LOG.md`.

### Restricted attributes and matching

**Actual check and location:** `build_member_profile_text` in `app/services/matching_service.py` filters `MemberAttribute.restricted.is_(False)` together with the member and club IDs before joining text. `rank_candidates` calls that builder for both the requesting member and each candidate and embeds those filtered strings at request time; it deliberately does not score from stored `profile_embedding` values because existing vectors may contain restricted data. `refresh_member_embedding` uses the same builder for future stored vectors, and the introduction endpoint independently applies `MemberAttribute.restricted.is_(False)` before composing `reason_text`. Restricted rows remain in the database with their flag; they are excluded from these member-facing paths. Part 3 must preserve this check when it writes new attributes and refreshes vectors.

### Retry strategy and batch failures

**Implemented retry strategy:** Pending implementation. The required behavior is to retry transient LLM rate limits and 5xx responses with bounded backoff, then record a permanent failure for only that message while continuing the batch; the final note must name the actual retry settings and show what happens when message 3 of 5 fails and message 4 succeeds.

Payment idempotency being developed for issue 4 uses stable payment-operation keys; Part 3 extraction idempotency needs its own processed-message key. They share the principle of safe retries, but a payment key does not establish whether a message's attributes were extracted, and the LLM retry strategy remains pending until Part 3 is implemented.

### Authorization, eval, and threshold

**Authorization:** Pending implementation. Only an admin or service role of the requested club may trigger extraction, and message IDs must resolve within that club.

**Eval:** Pending real API run. The eval must compare kind, exact restricted flag, and at least one expected keyword for each `eval/golden_set.json` record, print each result and an overall score, and exit nonzero below a justified threshold. Record the selected threshold, rationale, observed score, and exit code after the run.

### Non-obvious choices

The review bug trace uses an isolated SQLite database and the real FastAPI route because the seeded PostgreSQL container was initially inaccessible from the restricted shell; this preserved seed data while producing a literal response. Once database access was available, the existing PostgreSQL test suite passed, but the review trace itself remains an isolated reproduction. For Part 3, document decisions such as the processed-message key, handling zero-result extraction, and embedding refresh only after the implementation is settled.

## Closing question

**What was deliberately left out, and what would one more day add?** Pending final implementation and eval. Answer this with concrete tradeoffs from the completed work; the optional Part 4 tasks should be described as attempted or not attempted based on what actually happened.

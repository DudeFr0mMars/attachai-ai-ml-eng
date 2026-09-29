# Review session — 2026-09-29

This record tracks the visible back-and-forth for the review request. It is not a claim that the Part 3 extraction conversation or its required correction has happened yet.

## User request

> Read '/home/varun/attachai-ai-ml-eng/README.md' and '/home/varun/attachai-ai-ml-eng/AI_ML Engineer Assignment.pdf'. Highlight the instructions that have to be always followed. Perform an analysis of the repo and create the REVIEW.md file asked. Also create the .ai-converastions/ folder to trackl this back and forth

## Assistant response and course of work

1. I said I would read both documents, inspect the repository, create the review and conversation folder, and identify standing instructions.
2. The PDF's requested folder is spelled `.ai-conversations/`; the user's message spells `.ai-converastions/`. I chose to create the canonical folder for assignment compliance and a pointer in the user-spelled folder.
3. Initial `pdftotext` was unavailable. I installed `pypdf` into `/tmp/aion-pdf` and read all five pages without changing project dependencies.
4. The test suite stopped before tests could run because its default URL selects missing `psycopg2`. With the installed `psycopg` driver selected, no PostgreSQL server was reachable. Docker startup failed in this environment.
5. I switched to an isolated SQLite database and sent an in-process ASGI HTTP request through the actual FastAPI route. The response contained a cross-club restricted health attribute. The exact request and response are in `REVIEW.md`; `scripts/review_trace.py` reproduces them.

At the end of the initial review, no user correction or follow-up had occurred. Future Part 3 work should append real prompts, outputs, and any genuine correction instead of fabricating one.

## Follow-up: trace and submission records

The user reported that the seed was done and Docker was up, then asked to run `review_trace.py` once and inspect the logs. The trace returned HTTP 200 with the same cross-club restricted health text; I explained that the script uses isolated SQLite data and does not exercise the seeded PostgreSQL database. Docker's database log showed readiness and `docker compose ps` showed a healthy container.

The user then asked to add and maintain `TERMINAL_LOG.md` and `DESIGN_NOTES.md`, including the assignment's required sections. I added actual setup verification, the baseline test run, and the existing bug trace, while marking fix, extraction, eval, bonus, and final-run outputs as pending. A read-only database check found 2 clubs, 14 members, 9 messages, 9 attributes, and 8 knowledge chunks; the existing seven tests passed against `kindred_test` when database access was available.

## Part 2 follow-up: selected knowledge leak

The user chose the cross-club knowledge leak for Task 2 and specified adding `club_id` to the filter. I captured a read-only request against the seeded PostgreSQL database before changing the route; its five results included two Oakhurst chunks for a Riverside token. A new regression test failed before the fix because the Oakhurst chunk ranked first.

I added `KnowledgeChunk.club_id == member.club_id` before similarity ordering and the result limit. The same seeded request then returned only Riverside chunks, and the full suite passed with eight tests. I moved this issue to the top of `REVIEW.md` to match the selected Part 2 fix and recorded the literal traces in `TERMINAL_LOG.md`.

## Issue 2 correction: matching also needs the restricted check

The user asked to fix issues 2, 4, and 3 in that order and emphasized the eventual Part 3 idempotency and restricted-data notes. My first issue 2 patch checked introduction text only; the user corrected the scope: matching must also exclude restricted attributes, including data already embedded. I added the shared `restricted IS FALSE` profile filter and made ranking recompute both vectors from eligible attributes so legacy stored vectors cannot affect scores. The new matching tests failed before this correction and passed afterward; the focused introduction and matching run returned nine passing tests.

## Issues 4 and 3: payment replay and stored booking amount

The first payment regression run produced four failures: duplicate direct charge/attempt behavior, a timeout replay charge, a simulated session-crash replay charge, and a confirmed session being reopened. The initial stable-key implementation passed those cases, but a read-only review identified that the mock provider's outcome cache is process-local. I changed both routes to commit an initiated `PaymentAttempt` before calling the provider and made existing pending attempts lookup-only. The user chose to fix underpayment for existing bookings only because session bookings have no independent server-side quote. The direct route now compares the submitted amount with the stored booking amount and charges the stored value. The completed suite passed 29 tests. A lost provider outcome still requires reconciliation (HTTP 504), but does not cause a second charge.

The user selected OpenAI with `OPENAI_API_KEY` for Part 3 and asked to update required Markdown files and commit these fixes before beginning extraction work. No real extraction API call or eval has yet been recorded.

# Repository working guide

## Purpose and authoritative sources

This is the HROne Employee Attendance & Analytics API assignment, contract v2.0.
The goal is to review and repair the starter, implement the entire API, prove
index use, and explain the implementation. Exact fields, status codes, business
rules, concurrency behavior, and performance are evaluated automatically.

Read these sources before implementation, in this order:

1. `PROBLEM_STATEMENT.docx`: scope, environment, evaluation, and submission.
2. `openapi.yaml`: authoritative HTTP contract, schemas, and rules R1-R10.
3. `DATA_MODEL.md`: authoritative MongoDB storage contract and legacy defaults.
4. `app/main.py`: existing implementation to review, not a source of expected behavior.
5. `REVIEW.md`, `DECISIONS.md`, `README.md`, `requirements.txt`,
   `sample_seed.py`, and both files in `sample_data/`.

This guide summarizes those sources; it does not replace them. Consult the
endpoint descriptions as well as schemas: important requirements exist only in
prose. Record consequential ambiguities and the reasoning used to resolve them.
Do not change the supplied contract or fixtures to accommodate an implementation.

## Agreed two-part workflow and documentation checkpoint

The user has chosen two development parts. Explanation is produced continuously
alongside both parts, rather than deferred to a separate final documentation phase.

1. **Part 1: review and fix.** Review the starter's helpers and five existing
   endpoints, repair their behavior, add the shared infrastructure needed for
   those repairs, and verify them. Repair existing work-hour and overtime helpers
   even though their consumers are implemented in Part 2. Record findings and
   fixes in `REVIEW.md` as they happen.
2. **Part 2: implement.** Add the seven missing endpoints, their pipelines,
   concurrency controls, indexes, and verification. The MongoDB explain endpoint
   is an implementation deliverable within this part. Capture the reasoning for
   `DECISIONS.md` while making these choices.

Part 2 is delivered in three reviewed groups: (1) punch-out and corrections,
(2) employee monthly and department summaries, (3) leaderboard, trends and admin
explain. Complete, verify and demonstrate each group, then review user feedback
before starting the next. Run the full MongoDB 6/7, workers 1/2, UTC/IST matrix
before each group review. Concurrent corrections return 409 immediately on a
stale write; do not automatically retry. Trends use $densify after grouping logs.

The user wants the complete failure inventory first, followed by planning
questions one at a time. Record each answer and its reasoning in `WORK_LOG.md`.
Complete the Part 1 plan together, then carry out all agreed Part 1 repairs as
one development effort. Questions should address real design choices or desired
explanation depth; required contract behavior is already fixed by the sources.

Apply this documentation checkpoint on every meaningful development change:

- At the start of a session, read `WORK_LOG.md` alongside this guide to recover
  the current part, completed work, pending questions, and next action.
- For a starter defect, update `REVIEW.md` with its original location, concrete
  failing example, and actual fix. Mark reviewed but unfixed items explicitly as
  pending; do not describe a proposed fix as already implemented.
- For a design choice, record why it was made and the relevant alternative in
  `WORK_LOG.md`; update the corresponding `DECISIONS.md` answer once implemented.
  Keep lengthy working notes in the log so the final decisions stay 150-200 words.
- Record verification commands and observed results, including failures and
  checks not yet run. Distinguish static review evidence from executed tests.
- Update `README.md` when setup, running instructions, or limitations change.
- Before ending a development session or moving between parts, reconcile the
  code with these documents and update the log's current state and next action.
  If documentation is already current, record that the checkpoint was checked.

This is a persistent instruction checkpoint, not an installed executable Git or
editor hook. Follow it without needing the user to repeat the documentation request.
Use `WORK_LOG.md` for continuity; keep submission documents focused on the final
implementation.

### User preference: evidence before defect claims

The user explicitly requires real runtime testing and does not want assumptions
presented as facts. Test the unchanged starter through actual HTTP requests and
real MongoDB where applicable before describing an observed failure as reproduced.
Static findings remain review candidates until tested. Mocks, source inspection,
and isolated function checks must not be represented as end-to-end evidence.
Record the exact input, expected contract behavior, observed result, environment,
and verification command. Separate reproduced defects, behavior verified correct,
untested candidates, and unresolved ambiguities. Preserve this preference across
sessions. Part 1 repairs are implemented; consult WORK_LOG.md for verification state and the next action.

## Repository map and initial state

- `app/main.py`: all application code; initially five incomplete or defective
  endpoint implementations and seven missing endpoints.
- `app/__init__.py`: empty package marker.
- `requirements.txt`: FastAPI, Uvicorn, PyMongo, Pydantic v2, and python-dotenv.
- `sample_data/employees.json`: six employees across Engineering, Sales, and
  Support, including a July mid-month joiner and an overnight shift employee.
- `sample_data/attendance_logs.json`: nine logs showing full days, lateness,
  overtime, an open record, a half day, absence, leave, an overnight shift,
  correction history, and a legacy record.
- `sample_seed.py`: loads Extended JSON with timezone-aware datetimes; deletes
  all existing documents in both target collections before inserting samples.
- `REVIEW.md` and `DECISIONS.md`: initially unfilled templates.
- `README.md`: setup and submission instructions; references an `.env.example`
  that is absent from the supplied kit.
- No tests or test configuration are supplied initially.

Local audit support added during Part 1: `tests/test_starter_contract.py`,
`requirements-dev.txt`, `RUNTIME_AUDIT.md`, and `WORK_LOG.md`. Consult the audit
report for executed evidence and the log for current progress; they are working
documents and do not supersede the supplied contract.

Part 2 Group 1 adds `tests/test_group_one_writes.py`, shared fixtures in
`tests/conftest.py`, and `tests/run_runtime_matrix.py`. Forced race tests require
separate test-only MongoDB instances on ports 27038/27039 with test commands
enabled; never enable their failpoints on the manual development server.
Group 2 adds `tests/test_group_two_analytics.py` for monthly/department summaries,
calendar/rounding rules, stored-value behavior and 100000-log lookup plans.
Group 3 adds `tests/test_group_three_analytics.py` for ranks, dense daily ranges,
moving windows, real explain HTTP, and live/explain query equivalence. All twelve
endpoints are implemented; consult WORK_LOG.md for final verification state.

Additional browser verification: `tests/run_browser_walkthrough.py` uses actual
Playwright Chromium Swagger interactions in desktop/mobile viewports, disposable
UUID databases and temporary API processes. Install `requirements-browser.txt`
and the matching Chromium build. It is standalone, outside pytest discovery;
keep screenshots/traces/raw responses in a temporary directory, outside Git.

Treat the samples as examples of document shapes, not sufficient correctness
coverage. Initial-state observations above may become outdated after changes.

## Runtime and implementation boundaries

- Use Python 3.11+, FastAPI, and PyMongo or Motor. MongoDB 6.0+ must work; the
  grader uses MongoDB 7.0. Avoid features that require newer server versions.
- Keep all application code in `app/main.py`. Organize models, helpers, query
  builders, lifecycle setup, and handlers clearly within that file. Separate
  test files are acceptable; do not split the service into additional modules.
- Start from the repository root with:

  ```sh
  uvicorn app.main:app --port 8000
  ```

- Be ready within 20 seconds when MongoDB is available. `GET /health` must ping
  MongoDB and return 200 with `{"status": "ok"}` only when it answers; otherwise
  return 503. Bound database connection waits appropriately.
- Read `MONGO_URI` and `MONGO_DB` from environment variables. A local `.env` is
  allowed, but existing environment variables take precedence.
- Create required indexes idempotently at application startup. The grader seeds
  the database first and supplies only the default `_id` indexes.
- Application startup must preserve seeded documents. Do not seed, clear,
  migrate away, or replace the grader's data.
- The running service may access MongoDB only; do not add external service calls.
- Keep dependencies explicit in `requirements.txt`. Avoid unnecessary frameworks,
  features, authentication, frontend work, or infrastructure outside the brief.

## Data, time, and validation

- Use only `employees` and `attendance_logs` as the required stored collections.
  Preserve field names and BSON types described in `DATA_MODEL.md`.
- Employee identity is the client-supplied, unique, immutable `emp_code`.
  Attendance identity is `(emp_code, date)`. MongoDB `_id` is internal; never
  expose it or add an attendance `id`, and never identify an API resource with it.
- MongoDB instants are UTC BSON datetimes. API instants are integer epoch
  milliseconds, including `created_at`, punches, `history[].at`, and the nested
  punch values in `history[].changes.*.from` and `.to`.
- Choose a consistent UTC handling policy. PyMongo defaults to naive UTC
  datetimes; never interpret those as the host's local time or mix them with
  aware datetimes in arithmetic.
- Timestamp inputs must be actual integers from `100000000000` through
  `4102444800000`, inclusive. Reject seconds-looking values, floats, strings,
  booleans, and out-of-range inputs with 422. Do not let Pydantic coercion hide
  invalid input. Nullable response timestamps do not make request timestamps
  nullable; distinguish an omitted optional field from an explicit null.
- Truncate instants to whole seconds before calculations; store and return the
  truncated values. Use an explicit timezone instead of host-local defaults.
- Store calendar dates as `YYYY-MM-DD` strings, months as `YYYY-MM`, and shift
  times as `HH:MM` strings. Validate actual calendar values and exact formats.
- Employee creation validates `emp_code` as `EMP` plus 4-6 digits, name length
  1-100, department length 1-50, email pattern and maximum length 120, shift
  formats, and `joined_on`. Shift start and end must differ. Defaults are
  `09:30` and `18:30`. `created_at` comes from the server.
- Department matching is exact and case-sensitive. Apply supplied filters
  deliberately rather than dropping them through truthiness checks.
- Ignore client-supplied derived fields: `work_hours`, `late_minutes`,
  `overtime_minutes`, and `half_day`. Never persist them from request input.
- Missing `history` means `[]`; missing `half_day` means false; missing late or
  overtime minutes means 0. Handle missing absence/leave punch times as null.
- Expected client failures must produce 404, 409, or 422 as specified, with a
  FastAPI-compatible `detail` envelope, rather than uncaught 500 errors.

## Business rules to preserve

| Rule | Required behavior |
|---|---|
| R1 | Shifts and attendance dates use IST, UTC+05:30. Normally use the IST punch-in date. For an overnight shift (`shift_end <= shift_start`), a punch-in strictly earlier than `shift_end` belongs to the previous date; that shift ends the next calendar day. Truncate timestamps before calculating. |
| R2 | Late only when elapsed time after shift start is strictly greater than 600 seconds. Then floor the full elapsed minutes since shift start, without subtracting grace. For a 09:30 shift: 09:40:00 -> 0, 09:40:01 -> 10, 10:15:59 -> 45. |
| R3 | Floor elapsed minutes after the correct shift end; count overtime only when that result is at least 30, otherwise 0. |
| R4 | Work hours are elapsed seconds / 3600 rounded to two decimals half-up; null until punch-out. |
| R5 | After punch-out, half day means rounded work hours < 4.50; present-day contribution is 0.5. |
| R6 | `PRESENT`, `WFH`, and `ON_DUTY` are presence statuses; `ABSENT` and `LEAVE` are not. |
| R7 | Monthly working days are Monday-Friday, starting no earlier than `joined_on`; no holiday calendar. Monthly present days exclude weekends, but late and overtime totals include weekend logs. |
| R8 | Report numbers with two decimals half-up; rates use four decimals half-up. |
| R9 | Headcount includes employees who joined on or before the period end, including employees with no logs. For trends, eligibility is evaluated separately for each day. |
| R10 | Page starts at 1. Page size defaults to 20, must be 1-100. Total counts the entire filtered set. |

Use explicit decimal half-up arithmetic where needed. Python `round()` and
MongoDB `$round` do not by themselves implement the required tie behavior.
Analytics must read stored derived values, even when seeded values differ from
what recalculating punch times would produce. Recompute only on writes that
require it.

## Endpoint obligations

| Endpoint | Required behavior beyond the shared rules |
|---|---|
| `GET /health` | MongoDB-backed readiness, 200 or 503. |
| `POST /employees` | 201 on creation; database-enforced unique code; duplicate creates return 409; invalid input returns 422. |
| `GET /employees` | Optional department filter; `emp_code` ascending; database pagination and filtered total. |
| `POST /attendance/punch-in` | Optional `punched_at` defaults to now; status defaults to `PRESENT` and accepts presence statuses only. Unknown employee -> 404; existing attendance day -> 409; creation -> 201. Initialize open-record fields and empty history. |
| `GET /attendance` | Optional employee, inclusive date bounds, and status filters; reversed bounds -> 422. Sort by date descending then employee code ascending; paginate in MongoDB. |
| `POST /attendance/punch-out` | Select the most recent record whose punch-in is at or before the supplied/default instant, including across midnight. Unknown employee or no qualifying punch-in -> 404; selected record already closed -> 409. Punch-out must be strictly after punch-in and no more than 24 hours later, otherwise 422. Compute R3-R5; success -> 200. |
| `PATCH /attendance/{emp_code}/{date}` | Correct an existing record; rules and audit behavior below; success -> 200. |
| `GET /analytics/employees/{emp_code}/monthly` | Required month; unknown employee -> 404. Aggregate working/present/leave days, late counts and minutes, overtime minutes, and attendance percentage. Percentage is null when working days is zero. |
| `GET /analytics/departments/summary` | Required month, optional department. Include eligible employees with no logs; omit zero-headcount departments; sort by department ascending. Mean work hours is across presence-status records with non-null hours, not an average of employee averages; null when none qualify. Include the exact required present, late, leave, and on-duty fields. |
| `GET /analytics/leaderboard/late` | Required month; limit defaults to 10, range 1-50; optional department. Only positive total lateness; ignore orphan logs. Rank within the requested department when filtered. Competition ranks 1,2,2,4; include every rank <= limit; sort totals descending then employee codes ascending. |
| `GET /analytics/departments/{department}/trend` | Required query names `from` and `to`, inclusive. Unknown department -> 404; reversed or over-92-day ranges -> 422. One row per calendar day, even when the entire range has no logs. Daily headcount reflects joining dates. Presence includes weekends and half days. Rates are null on weekends or with zero headcount; a working day with eligible employees but no logs has rate 0.0. |
| `GET /admin/explain/{endpoint}` | Explain one of the five supported operations with the real query/pipeline and `executionStats`; details below. |

Read `openapi.yaml` for exact response fields and validation requirements before
implementing each endpoint. Do not substitute superficially similar summaries.

### Corrections and audit history

- Only `status`, `punch_in`, and `punch_out` are editable. Omitted fields stay
  unchanged. `reason` is required, length 5-200; `regularized_by` is required,
  length 1-50. This assignment does not require authentication for the actor.
- Setting `ABSENT` or `LEAVE` clears both punches, hours, and presence-derived
  values. Supplying either punch field with that status is 422.
- A presence status requires a punch-in in the final record. Its R1 attendance
  date must remain the addressed date. Any punch-out must be strictly later and
  within 24 hours. No-op corrections return 422.
- Recompute all derived fields from the final record and employee shift.
  Append exactly one history entry per successful correction, with server time,
  actor, reason, and only fields that actually changed, including derived fields.
- Store nested punch before/after values as BSON datetimes; serialize them as
  epoch milliseconds or null. Preserve all earlier history entries.
- Ordinary punch-in and punch-out do not append audit entries.

## Concurrency and database execution

- Enforce employee uniqueness with a unique `emp_code` index and attendance
  uniqueness with a unique compound `(emp_code, date)` index. Catch duplicate-key
  conflicts and return 409; check-then-insert alone is insufficient.
- Parallel duplicate employee creations and punch-ins must yield exactly one
  201 and 409 for the others.
- Parallel punch-outs must yield exactly one 200. Select the contract's most
  recent qualifying record, not merely the latest open record; do not fall back
  to an older open record because the most recent one is already closed.
- Use atomic conditional updates or equivalent database concurrency controls
  for punch-out and corrections. Process-local locks are not sufficient.
  Concurrent corrections must preserve both accepted changes and history, or
  return 409 for a conflicting writer; never silently overwrite stale data.
- Execute analytics as MongoDB aggregation pipelines. Do not fetch source logs
  and aggregate, rank, fill gaps, or calculate moving windows in Python.
- For trends, the moving average uses non-null daily rates from the current row
  and up to six preceding calendar rows inside the requested range. It is not
  seven working days and does not include rows before `from`. Round to four
  decimals half-up; return null when no non-null rates exist in the window.
- Design indexes from actual filters, sorts, joins, and punch-out selection.
  Support approximately 100,000 attendance records. Do not materialize whole
  matching collections for listing; use database sort, skip, limit, and count.
- Keep query/pipeline construction reusable within `app/main.py` so explain and
  live handlers execute equivalent operations, including filters, pagination,
  sort, and any hints. Explain must not show a simpler substitute query.

### Explain contract

Supported names: `attendance_list`, `employee_monthly`, `department_summary`,
`late_leaderboard`, and `department_trend`.

Accept the corresponding endpoint's query parameters; monthly employee explain
uses `emp_code` and `month`, and trend explain uses `department`, `from`, `to`.
Missing required parameters and unsupported names return 422. Return
`{"endpoint": ..., "collection": ..., "explain": ...}` containing the raw
MongoDB explain document as JSON, using `executionStats` verbosity. Verify
`IXSCAN` and absence of `COLLSCAN`, including cross-collection lookup plans,
against representative large data.

## Verification and documentation workflow

1. Inventory starter defects against the contract. Track original function/line
   locations and concrete failing inputs so `REVIEW.md` stays accurate after
   edits. Distinguish defects from missing endpoints and legitimate behavior.
2. Implement shared validation, UTC/IST conversion, serialization, rounding,
   indexes, and concurrency controls before building on them.
3. Repair the existing endpoints and add the missing ones, using small,
   explainable functions and shared query builders.
4. Add meaningful tests using an isolated disposable test database. Run real
   MongoDB integration tests for aggregations, indexes, and races; mocks alone
   cannot establish those guarantees. Never use the candidate's or grader's
   seeded database for destructive fixtures or benchmarks.
5. Cover boundary timestamps, truncation, exact grace/overtime boundaries,
   half-up ties, half-day thresholds, overnight and month/year boundaries,
   invalid dates and types, required fields, nulls, pagination, filters, unknown
   resources, and legacy missing fields.
6. Cover no-log employees, an entirely empty trend range, joining during/after
   a period, zero working days/headcount, open logs, all statuses, missing
   weekdays, weekend logs, unequal per-employee record counts, orphan logs,
   leaderboard ties at the cutoff, and shortened moving-average windows.
7. Exercise simultaneous duplicate creates, punch-ins, punch-outs, corrections,
   and interactions between corrections and punch-out. Assert response codes,
   final document state, and retained history.
8. Verify startup, MongoDB outage readiness, environment precedence, stored BSON
   types, exact API serialization including nested history, and explain behavior
   on a representative approximately 100k-record dataset.
9. Fill `REVIEW.md` with every actual starter defect, a concrete way to observe
   it, and its implemented fix. Include examined behavior that was correct.
   Do not claim an unimplemented fix or unexecuted test as completed.
10. Keep `DECISIONS.md` about 150-200 words total, in plain language: indexes and
    one rejected option; the exact punch-in race; ties at the limit; no-log
    headcount; and one proposed change for 100x data. Describe actual code.
11. Keep `README.md` short, with working setup/run instructions and any remaining
    limitations. Correct the missing `.env.example` reference when setup is
    updated. Report what was tested and any checks that could not be run.

## Data safety and submission

- Run `sample_seed.py` only against an explicitly disposable development
  database: it calls `delete_many({})` on both collections.
- Do not commit `.env`, credentials, virtual environments, Dockerfiles, or data
  dumps. The supplied small fixtures are reference inputs, not generated dumps.
- Required deliverables are `app/main.py`, `requirements.txt`, `REVIEW.md`,
  `DECISIONS.md`, and a short `README.md` in a public Git repository. Do not
  publish, push, or submit without the user's authorization.
- The assignment expects individual work and a live walkthrough. Make choices
  understandable to the candidate and document their reasoning; avoid opaque
  generated code the candidate cannot explain or modify.
- Evaluation weights: review 10%; CRUD/rules/concurrency 30%; analytics 30%;
  MongoDB usage/speed 15%; decisions/code quality 15%. Prioritize correctness,
  concurrency, database execution, and honest evidence of validation.

# REVIEW.md

Part 1 review and repairs, 2026-10-11. All 40 baseline findings below are repaired.
Original locations refer to the supplied 162-line `app/main.py`.
Expected behavior comes from `openapi.yaml` and `DATA_MODEL.md`. Findings were
reproduced through real Uvicorn HTTP requests, real MongoDB inspection/profiling,
or direct execution of the actual helper functions, as labeled below.

See `RUNTIME_AUDIT.md` for environment, commands, counts, scope, and limitations.
The executable checks are in `tests/test_starter_contract.py`.

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `health`, line 74 | Reports readiness without checking MongoDB. | HTTP: prove MongoDB ping fails against an unavailable local port, then `/health` still returns 200 and `status: ok`; required 503. | Live MongoDB ping, 503 on failure, bounded connection waits and retrying readiness. |
| 2 | Client/startup, lines 22-27 | Required database uniqueness guarantees are absent. | MongoDB: `employees.list_indexes()` shows only `_id_`; repeated real HTTP races also store duplicate employee codes and duplicate attendance natural keys. | Six named indexes created idempotently at startup; unique employee and attendance natural keys. |
| 3 | `EmployeeIn`, line 54 | Does not validate employee-code format. | HTTP: `BAD`, `EMP123`, and `EMP1234567` each return 201 instead of 422. | Employee code validated as EMP plus 4-6 digits. |
| 4 | `EmployeeIn`, line 55 | Does not validate name length. | HTTP: empty and 101-character names each return 201 instead of 422. | Name length constrained to 1-100. |
| 5 | `EmployeeIn`, line 56 | Does not validate email format or maximum length. | HTTP: `invalid` and a 122-character email each return 201 instead of 422. | Contract email pattern and maximum length 120 enforced. |
| 6 | `EmployeeIn`, line 57 | Does not validate department length. | HTTP: empty and 51-character departments each return 201 instead of 422. | Department length constrained to 1-50. |
| 7 | `EmployeeIn`, lines 58-59 | Accepts invalid or noncanonical shift times. | HTTP: `25:00`, `18:99`, and `9:30` each return 201 instead of 422. | Exact valid 24-hour HH:MM pattern enforced. |
| 8 | `EmployeeIn`, lines 58-59 | Allows equal shift start and end. | HTTP: both `09:30` returns 201 instead of 422. | Model validator rejects equal shift times. |
| 9 | `EmployeeIn`, line 60 | Does not validate calendar date or format. | HTTP: `2026-02-30` and `2026-7-1` each return 201 instead of 422. | Exact date format validated, then parsed as a real calendar date. |
| 10 | `create_employee`, line 82 | Stores host-local clock time as a naive datetime that MongoDB interprets as UTC. | HTTP plus MongoDB, server `TZ=Asia/Kolkata`: stored creation instant is 5h30m ahead of the measured UTC request interval. The UTC-host control passes. | Aware UTC server clock, truncated to seconds. |
| 11 | Employee responses, lines 85, 96 | `created_at` is serialized as an ISO string, not integer epoch milliseconds. | HTTP: employee creation returns a string such as `2026-10-11T10:13:59...`; listing also returns ISO strings. | Shared employee serializer emits integer epoch milliseconds. |
| 12 | `create_employee`, lines 79-83 | Check-then-insert is unsafe under concurrency. | HTTP plus MongoDB: five rounds of 24 identical requests store 1, 5, 6, 5, 6 employees respectively; four rounds violate the one-creation guarantee. | Direct insert protected by the unique code index; duplicate-key conflicts return 409. |
| 13 | `list_employees`, line 93 | Page offset is one page too far. | HTTP: page 1, size 2 returns `EMP0003`, `EMP0004`, instead of `EMP0001`, `EMP0002`. | Offset is (page - 1) times page_size. |
| 14 | `list_employees`, line 94 | Total ignores department filter. | HTTP: Sales filter reports total 6, although the seeded Sales department has 2 employees. | Count uses the exact department filter. |
| 15 | `list_employees`, line 95 | Does not sort by employee code. | HTTP: reverse fixture insertion order; returned codes within a two-item page are descending rather than ascending. | MongoDB sorts employee codes ascending before pagination. |
| 16 | Listing parameters, lines 89, 130-131 | Pagination bounds are not validated. | HTTP: page 0, size 0, size 101 and negative values do not return 422. Employee page -1 and size -1 return 500; attendance negative values return 200. | Both list endpoints constrain page >= 1 and size 1-100. |
| 17 | `PunchInIn`, line 65 | Coerces invalid timestamp types. | HTTP: integral float `1800000000000.0`, string `"1800000000000"`, and boolean `true` each create a record instead of returning 422. A fractional float is correctly rejected. | Strict integer timestamp type excludes floats, strings and booleans. |
| 18 | `PunchInIn`, line 65 | Does not enforce epoch-millisecond bounds. | HTTP: seconds-looking `1783312500`, -1, `99999999999`, and `4102444800001` each create a record instead of returning 422. | Inclusive schema bounds enforced before conversion. |
| 19 | `PunchInIn` / `punch_in`, lines 65, 102 | Explicit null and zero incorrectly fall back to now. | HTTP: both inputs return 201 and store the current time; contract requires 422. | Omission is tracked separately; supplied null and zero are rejected. |
| 20 | `punch_in`, line 102 | Huge timestamps raise an unhandled conversion error. | HTTP: `10**30` returns 500 instead of 422. | Bounds validation prevents invalid datetime conversion. |
| 21 | `PunchInIn`, line 66 | Accepts non-presence or unknown statuses. | HTTP: `ABSENT`, `LEAVE`, `UNKNOWN`, and lowercase `present` each return 201 instead of 422. | Punch-in status restricted to PRESENT, WFH and ON_DUTY. |
| 22 | `punch_in`, lines 101, 113 | Dereferences a missing employee. | HTTP: valid timestamp with `EMP9999` returns 500 instead of 404. | Missing employee explicitly returns 404. |
| 23 | `punch_in`, line 102 | Converts timestamps to naive host-local values, corrupting stored instants on an IST host. | HTTP plus MongoDB, `TZ=Asia/Kolkata`: a 04:00 UTC input is stored as 09:30 UTC. | Epoch conversion produces aware UTC instants. |
| 24 | `punch_in`, line 103 | Attendance date depends on the host timezone rather than IST. | HTTP, UTC host: July 15 20:00 UTC belongs to July 16 IST, but response date is July 15. | Attendance date computed explicitly in IST. |
| 25 | `punch_in`, line 103 | Overnight attendance-day exception is absent. | HTTP: July 15 05:40 IST for a 22:00-06:00 shift returns July 15; required July 14. | Early overnight punches use the previous attendance date; exact shift-end boundary remains current date. |
| 26 | `punch_in`, lines 102, 110 | Punch instants are not truncated to whole seconds. | HTTP plus MongoDB: input 09:40:00.900 IST is stored with microsecond 900000; required zero. | Whole-second epoch conversion precedes all calculations and storage. |
| 27 | `compute_late_minutes`, lines 35-37 | Shift start uses the input datetime's timezone/date rather than the correct IST shift anchor. | HTTP, UTC host: 10:05 IST for a 09:30 shift gives 0 instead of 35 late minutes. Helper execution: 01:00 IST for a 22:00 overnight shift gives 0 instead of 180. | Lateness uses the full shift context and attendance-date IST anchor. |
| 28 | `compute_late_minutes`, lines 36-37 | Floors minutes before checking the grace boundary. | Actual helper and HTTP on an IST host: 09:40:01 versus 09:30 gives 0 instead of 10. | Grace comparison uses seconds > 600 before flooring elapsed minutes. |
| 29 | `compute_work_hours`, line 41 | Uses float/banker's rounding instead of decimal half-up. | Actual helper: 450 seconds is 0.125 hours; returns 0.12 instead of 0.13. | Integer elapsed seconds and Decimal half-up rounding. |
| 30 | `compute_overtime`, line 47 | Missing 30-minute minimum. | Actual helper: 18:50 IST versus 18:30 shift end returns 20 instead of 0. | Floored overtime counted only when at least 30 minutes. |
| 31 | `compute_overtime`, line 46 | Overnight shift end is anchored to the wrong calendar day. | Actual helper: 06:40 on July 16 for a July 15 overnight shift returns 1480 instead of 40 minutes. | Full shift context anchors overnight end on the next calendar day. |
| 32 | Client / `compute_overtime`, lines 22, 46-47 | Default naive database datetimes are incompatible with the helper's aware shift end. | Actual helper with PyMongo-default-shaped naive UTC input raises `TypeError`. This is a helper compatibility observation; the punch-out HTTP endpoint does not exist yet. | Client reads aware UTC; helpers also normalize naive UTC input explicitly. |
| 33 | Attendance responses, lines 121, 150 | Punch and history timestamps are serialized as strings. | HTTP: punch-in response has an ISO-string punch; seeded corrected attendance returns strings for history time and nested punch `from`/`to`. | Recursive serializer emits integer milliseconds for punches and nested history instants. |
| 34 | Attendance responses, lines 119, 149 | Exposes an attendance `id` derived from MongoDB `_id`. | HTTP: both punch-in and attendance listing include an `id`; attendance identity must be `(emp_code, date)`. | Response fields are whitelisted; no attendance id or MongoDB _id. |
| 35 | `punch_in`, lines 104-118 | Check-then-insert allows duplicate employee/date records. | HTTP plus MongoDB: five rounds of 24 requests store 2, 3, 4, 2, 3 records respectively; each round violates uniqueness. | Direct insert protected by the unique employee/date index; duplicate-key conflicts return 409. |
| 36 | `list_attendance`, lines 127-129 | Dates, reversed bounds, and status filters are not validated. | HTTP: impossible date, `bad`, reversed bounds, empty date, noncanonical date, unknown status, and empty status each return 200 instead of 422. | Calendar validation, enum validation and reversed-bound checks precede queries. |
| 37 | `list_attendance`, line 134 | Empty employee filter is silently discarded. | HTTP: `emp_code=` returns total 9, although no employee code matches the supplied empty string; required filtered total 0. | Filters distinguish None from supplied strings, including empty values. |
| 38 | `list_attendance`, lines 144-147 | Fetches all matches and sorts/paginates in Python. | HTTP plus MongoDB profiler: page size 20 returns 20 items but transfers 100000 records through the cursor; plan is `COLLSCAN`. | Count and sorted pagination execute in MongoDB using reusable query and hint builders. |
| 39 | `list_attendance`, line 145 | Missing employee-code tie-breaker. | HTTP after reverse employee-code insertion: July 6 records return codes 5, 3, 1 instead of 1, 3, 5. | MongoDB sorts by date descending, then employee code ascending. |
| 40 | `list_attendance`, lines 144-150 | Does not supply missing legacy defaults. | HTTP: sample legacy record omits `history` and `half_day`. Removing documented optional minute fields in the disposable fixture also leaves them absent in the response instead of 0. | Serializer supplies all documented legacy defaults without rewriting stored records. |

## Examined behavior that passed its baseline runtime check

- Required employee fields are rejected when missing, via Pydantic's existing behavior.
- Sequential duplicate employee creation and sequential duplicate punch-in return 409.
  Baseline concurrent workflows reproduced duplicates; repaired race checks require one 201 and 23 conflicts.
- All three presence statuses and both inclusive timestamp bounds are accepted.
- Nonintegral float timestamps return 422; the repaired model now also rejects integral floats, strings, and booleans.
- Employee creation uses the default shift times, ignores client `created_at`, and excludes `_id` from the response.
- Client-supplied derived values are ignored on punch-in, and the inserted history is empty.
- Attendance filtered totals, inclusive date filtering in the tested fixtures, and first-page date ordering work for the covered inputs; the repaired implementation performs pagination and tie ordering in MongoDB.
- Helper checks at exactly 09:40:00, at 10:15:59, and at exactly 30 minutes overtime pass.
- On a UTC host, employee creation stores the correct UTC instant; the IST-host variant reproduces corruption.
- Health returns the required body when MongoDB is available; the repaired outage behavior returns 503.

## Scope and remaining checks

The seven originally absent endpoints are Part 2 deliverables, not additional
defects in an existing implementation. All seven are now implemented across
the three groups; the final eight-configuration matrix and manual walkthrough
passed, as recorded below.
This audit does not prove that no further defects exist.
See `RUNTIME_AUDIT.md` for untested cases and helper-test interpretation. The
missing `.env.example` is a setup-documentation issue outside `app/main.py`.

## Repair verification

The first repaired run passed all 101 original checks against real MongoDB 7.
The expanded matrix and its exact environments are recorded in `RUNTIME_AUDIT.md`.
The historical Part 1 overtime/work-hour checks were direct helper execution.
Group 1 now also exercises these helpers through real HTTP punch-out and
corrections, including a 450-second half-up tie, overtime thresholds, the
rounded 4.50-hour half-day threshold, and overnight/year/leap-day transitions.
No mock results are presented as HTTP or MongoDB evidence.

## Part 2 Group 1 implementation

The previously missing punch-out and correction handlers were implemented in
Group 1; the monthly and department summaries follow in Group 2. Punch-out selects
by the latest qualifying punch time, rejects an already closed selected record,
and preserves prior history and stored lateness. Corrections validate the final
state, recompute all derived fields, and atomically append only actual changes.
Both writes match the originally read stored fields and history length; stale
writes return 409, including a change followed by restoration of the old fields.
A seventh index supports employee/punch-time selection. The combined suite
passed all 268 checks at Group 1 completion in eight MongoDB 6/7, workers 1/2,
UTC/IST configurations: 2144 executions, zero failures/errors/skips. See the Group 1
section of `RUNTIME_AUDIT.md` for exact evidence and remaining scope.

## Part 2 Group 2 implementation

Employee monthly and department summaries now execute reusable MongoDB
aggregations. Monthly calendars honor joining dates, presence counts only
weekdays and uses stored half-day flags; late/overtime and leave metrics include
weekend records. Department headcount starts with eligible employees, including
those with no logs. The mean uses qualifying record hours and counts, rather
than employee means. Orphan logs do not enter department totals. Decimal128
expressions implement half-up rounding; calendar month validation returns 422.
Two employee eligibility indexes bring the total to nine non-default indexes.
The combined suite passed 388 checks in each of eight MongoDB 6/7, workers 1/2,
UTC/IST configurations: 3104 executions, zero failures/errors/skips. Exact live
monthly and department pipelines use IXSCAN with no COLLSCAN on 100000 logs,
including attendance lookup. The live demonstration also passed all fifteen
HTTP checks and preserved every existing document. Leaderboard, trend and admin
explain were subsequently implemented in Group 3, described below.

## Part 2 Group 3 implementation

Leaderboard ranks positive stored monthly totals with MongoDB $rank, applies
the rank cutoff and orders tied employee codes afterward. Department filtering
precedes ranking; orphan logs are ignored. Trend groups stored daily totals,
seeds a zero-value first-day row, densifies explicit numeric calendar-day bounds,
and looks up eligible headcount for each date. A seven-calendar-row MongoDB
window averages non-null, rounded rates. No Python ranking, gap filling or
moving windows are used. All five explain names share real builders and hints;
the attendance find includes filters, projection, sort, skip and limit.

Initial runtime tests found malformed trend dates returning 500: Query aliases
in default arguments lost date validators. Moving aliases into Annotated
metadata restores 422, verified for both live and explain from/to parameters.
This is a new implementation defect repaired during Group 3, not an additional
original starter defect. Nine existing indexes suffice in the observed plans.
The final combined suite passed 512 checks in each of eight MongoDB 6/7,
workers 1/2, UTC/IST configurations: 4096 executions, zero failures/errors/skips.
This includes 124 Group 3 checks, real explain HTTP on 100000 logs, profiler
equivalence and indexed lookup plans with zero collection scans. A 22-request
manual walkthrough passed and preserved every employee and attendance BSON
document, including earlier audit history. All twelve endpoints are implemented
and verified; no original starter repair remains pending. See RUNTIME_AUDIT.md.

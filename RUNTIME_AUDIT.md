# Part 1 runtime baseline

Current result: Part 1 repairs and all twelve endpoints are complete. The final
suite passed 512 checks in each of eight configurations (4096 executions,
zero failures/errors/skips). This document retains chronological evidence;
see “Group 3 final matrix and completed API” for the latest results.

Recorded 2026-10-11. Tested the unchanged starter through actual localhost HTTP
requests to Uvicorn and a dedicated MongoDB container. No app or database mocks
were used. Direct execution of helpers is explicitly separated from HTTP checks.

## Environment and source

- Python 3.11.13; MongoDB 7.0.43, ARM64, Docker image `mongo:7`.
- FastAPI 0.143.0; Uvicorn 0.54.0; PyMongo 4.18.3; Pydantic 2.14.0.
- Test tools: pytest 9.1.1 and httpx 0.28.1.
- HTTP server timezone: UTC for ordinary cases; additional real server processes
  use `TZ=Asia/Kolkata` to test dependence on the host timezone.
- MongoDB listens only on `127.0.0.1:27028`. Each run uses a newly generated
  `candidate_kit_runtime_audit_<uuid>` database, which is removed afterwards.
- Both collections are seeded before startup. Fixtures use the supplied six
  employees and nine logs, with isolated changes for individual cases.
- The scale case uses 1000 additional employees and 100 days, producing exactly
  100000 validly shaped attendance records with distinct natural keys.
- `app/main.py` SHA-256:
  `10f13dd7eb6514739cbb187ef4c7560e110665f076b5b09171b295559468b411`.
  Application code was not modified during this audit.

## Baseline result

Final full run: **101 checks; 83 failed, 18 passed; zero fixture/setup errors**.
Failures mean the starter did not meet that check's expectation; they are not
83 independent bugs. `REVIEW.md` groups the findings into actionable entries.

- 92 HTTP/database checks: 77 failed and 15 passed.
- 9 actual-helper execution checks: 6 failed and 3 passed. Work-hours and overtime
  helper results are not punch-out HTTP evidence because that endpoint is absent.
- Full run took 5.21 seconds on this machine, including setup and teardown.
- A sandboxed attempt initially failed to open local sockets; those infrastructure
  errors are excluded. The completed runs used approved localhost socket access.

## Selected observed results

| Input / experiment | Contract expectation | Actual result |
|---|---|---|
| MongoDB unreachable, `/health` | 503 | 200, `status: ok`; separate real MongoDB ping failed |
| Employee code `BAD` | 422 | 201 |
| Employee joined date `2026-02-30` | 422 | 201 |
| Employee list page 1, size 2 | First two employee codes | Codes 3 and 4 |
| Sales employee filter | Total 2 | Total 6 |
| Employee page -1 | 422 | 500 |
| Punch-in for unknown `EMP9999` | 404 | 500 |
| Punch timestamp `10**30` | 422 | 500 |
| Integral float/string timestamp | 422 | 201 and stored attendance |
| Boolean `true` timestamp | 422 | 201 and a 1970 punch instant |
| Explicit null or zero timestamp | 422 | 201 using now |
| July 15 20:00 UTC punch | Attendance date July 16 IST | July 15 on UTC host |
| Overnight July 15 05:40 IST punch | Attendance date July 14 | July 15 on UTC host |
| 10:05 IST punch, 09:30 shift, UTC host | Late minutes 35 | 0 |
| 09:40:01 IST punch, 09:30 shift, IST host | Late minutes 10 | 0 |
| Punch instant containing 900 milliseconds | Stored whole seconds | BSON datetime retains 900000 microseconds |
| IST host, 04:00 UTC input instant | Stored 04:00 UTC | Stored 09:30 UTC |
| IST host, employee creation | Stored current UTC instant | Stored instant is 5h30m ahead |
| Seeded corrected record | Integer history/punch instants | ISO strings, including nested before/after punches |
| Legacy attendance record | Empty history, false half day | Both fields absent |
| Missing late/overtime minute fields | 0 | Fields absent |
| `emp_code=` attendance filter | No matches | Returns all 9 sample logs |
| 450 seconds worked, actual helper | 0.13 hours | 0.12 |
| 20 minutes after shift end, actual helper | 0 overtime | 20 |
| Overnight out 06:40 next day, actual helper | 40 overtime | 1480 |
| Naive UTC input to overtime helper | Consistent datetime arithmetic needed | `TypeError`: naive/aware subtraction |
| 100000 logs, request page size 20 | Database pagination | HTTP returns 20; MongoDB cursor transfers all 100000, with `COLLSCAN` |

The scale request took approximately 0.377 seconds in the final run. This does
not establish a general latency limit or measured memory usage; the demonstrated
defect is fetching the full matching collection instead of paginating in MongoDB.

## Concurrency evidence

Each round sends 24 identical requests from synchronized client threads to the
real server, then counts real stored documents. Five separate rounds per workflow
reset the disposable fixtures between rounds.

| Workflow | Successful creations / stored duplicates per round | Required |
|---|---|---|
| Employee creation | 1, 5, 6, 5, 6 | Exactly 1 each round |
| Punch-in | 2, 3, 4, 2, 3 | Exactly 1 each round |

The remaining responses in those rounds were 409. No artificial database delays,
server failpoints, or mocked interleavings were injected. Counts vary with
scheduling; an individual passing round does not establish concurrency safety.

## Reproduction

Install test dependencies in a Python 3.11+ virtual environment. The test suite
does not use the user's `MONGO_URI` or `MONGO_DB`; it targets localhost port 27028
and creates its own temporary database. Run serially, without pytest-xdist.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
docker run --rm -d --name candidate-kit-runtime-tests -p 127.0.0.1:27028:27017 mongo:7
.venv/bin/python -m pytest tests/test_starter_contract.py -q --tb=short
docker stop candidate-kit-runtime-tests
```

The suite launches and stops Uvicorn itself on available localhost ports.
At baseline capture, exit status 1 was expected against the defective starter.
The current suite includes repair regressions and explicit full-shift helper context;
these commands now verify the repaired application. The final recorded run
also used `--junitxml=/private/tmp/candidate-kit-runtime.65zAgB/audit.xml`; that
local XML contains individual test results and assertion evidence, without being
a required submission artifact.

## Limits at baseline capture

- Tests cover specified cases, not every possible input. Further defects may be
  discovered during repairs and broader boundary testing.
- MongoDB 6.0 compatibility, multiple Uvicorn workers, `.env` precedence against
  conflicting environment variables, and exhaustive calendar/shift boundaries
  have not been runtime-tested in this audit.
- The original missing `.env.example` reference was established by filesystem
  inspection. After the audit, README setup was corrected to use explicit local
  environment variables; application behavior remains unchanged.
- Naive-input helper compatibility needs a deliberate policy: choosing an aware
  MongoDB client and normalizing callers is also valid. The observed helper
  exception must not be presented as a failure in a nonexistent punch-out endpoint.
- The seven missing endpoints, half-day writes, corrections, new analytics, and
  explain behavior will be tested during Part 2.
- No application fixes had been made at baseline capture. The following repair
  verification records subsequent changes without replacing this evidence.


## Part 1 repair verification, 2026-10-11

All 40 grouped baseline findings are repaired in `app/main.py`; the seven missing
endpoints remain Part 2. The original evidence above remains historical.

- Approved choices: aware UTC internally and on MongoDB reads, explicit IST
  business calculations, synchronous PyMongo/handlers, and closing the identified
  verification gaps before finishing Part 1.
- Application SHA-256: `d20bbb2e91426f3ce1da9338629fc4adba970d7afbe3bb3f3dee8798b0f7617f`.
- First repaired run: 101/101 original expectations passed, 9.74 seconds,
  MongoDB 7.0.43, one worker, UTC host. Original helper expectations were retained;
  lateness/overtime calls now provide full shift and attendance-date context.
- Extended suite: 141 checks per configuration, comprising 120 HTTP/database
  checks and 21 direct helper checks. No mocks. Runtime/dependency versions match
  the baseline; MongoDB 6 is 6.0.28 and MongoDB 7 is 7.0.43.
- Command: `.venv/bin/python tests/run_part_one_matrix.py`. It sets
  `TEST_MONGO_URI`, `TEST_WORKERS`, and `TEST_SERVER_TZ` and runs pytest with JUnit
  output for each configuration. Ports 27028/27029 are dedicated Docker MongoDB
  7/6 instances; databases are disposable and preseeded before service startup.
- Result: **1128 checks across eight configurations; zero failures, errors or
  skips**. These are repetitions of 141 checks, not 1128 distinct scenarios.

| Configuration | Checks | Failures | Errors | Seconds (JUnit) |
|---|---|---|---|---|
| mongo6-workers1-Asia-Kolkata | 141 | 0 | 0 | 23.938 |
| mongo6-workers1-UTC | 141 | 0 | 0 | 23.089 |
| mongo6-workers2-Asia-Kolkata | 141 | 0 | 0 | 28.566 |
| mongo6-workers2-UTC | 141 | 0 | 0 | 26.610 |
| mongo7-workers1-Asia-Kolkata | 141 | 0 | 0 | 23.025 |
| mongo7-workers1-UTC | 141 | 0 | 0 | 23.210 |
| mongo7-workers2-Asia-Kolkata | 141 | 0 | 0 | 28.187 |
| mongo7-workers2-UTC | 141 | 0 | 0 | 28.784 |

Observed repair evidence:

- Five 24-request employee races and five 24-request punch-in races per
  configuration: exactly one 201, twenty-three 409s and one stored document in
  every round. Total: 80 rounds and 1920 concurrent requests across the matrix.
- Live MongoDB stop/start: readiness changes 200 -> 503 -> 200, writes fail with
  503 during outage, and existing documents survive recovery. Also started the
  API with MongoDB absent and only default indexes retained; it served 503, then
  built unique indexes and became ready after MongoDB returned. Each case owns
  a separate container, leaving the main test database available.
- Restarting the API preserves documents and index definitions. Preexisting
  duplicate employee codes keep readiness at 503 without deleting either record;
  after the test explicitly removes its duplicate, index retry restores 200.
- Conflicting `.env` URI/database settings lose to the explicit environment:
  creation succeeds in the requested database despite the `.env` unavailable URI.
- An overnight August 1 05:59:59.999 IST punch is stored at whole seconds under
  July 31, with 479 late minutes; exactly 06:00 belongs to August 1 with 0 late
  minutes. January/year and leap-day rollover, grace/truncation boundaries and
  half-up work-hour ties also pass. The 4.50-hour threshold is helper evidence;
  half-day writes await Part 2.
- Each scale case has 100000 logs. The live 20-item page returns filtered total
  100000 while the MongoDB profiler shows at most 20 records transferred by the
  query/getmore cursor and an IXSCAN plan. Real executionStats explanations of
  the shared live builder output, with skip/limit/sort/hint, show IXSCAN without
  COLLSCAN or a blocking SORT for five representative filter combinations.
  Count-pipeline explanations also show no COLLSCAN. No broader latency or
  memory guarantee is inferred from these checks.
- Strict timestamp inputs, actual calendar dates, exact/empty filters, very large
  page offsets, BSON UTC instants, integer API/nested history timestamps, legacy
  null/default values and preserved stored derived values pass.

One expanded test run initially had 134 passes and one harness failure: its
recovery database name exceeded MongoDB's 63-character limit. The identifier was
shortened; the corrected 135-check run passed before the final 141-check matrix.
This setup error is not counted as an application defect.

JUnit files were retained locally in `/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-part1-matrix-rr414s4b`.
Tests remove their HTTP processes, databases and recovery containers. The two
matrix MongoDB containers are stopped and removed after verification.

Remaining scope: Part 2 endpoints, their concurrency/analytics/explain behavior,
and their additional indexes have not been implemented or tested. Direct database
explanations above are not evidence for a nonexistent admin explain HTTP endpoint.
This matrix establishes the covered cases; it does not prove every possible
input or production performance at larger scale.

## Part 2 Group 1: punch-out and corrections

Implemented the two missing write handlers, guarded MongoDB updates, and the
employee/punch-time/date index. Shared test fixtures moved to tests/conftest.py;
application and database calls remain real, without mocks or in-app timing hooks.
The test suite now contains 268 checks: 141 retained Part 1 checks and 127 Group 1
checks. Of these, 21 are isolated helper checks and 247 exercise HTTP/MongoDB.

Concrete Group 1 inputs and observed behavior:

- EMP0001, 2026-07-15: punch-in 09:30 IST and punch-out 18:30 IST -> 200,
  work_hours 9.0, overtime_minutes 0, half_day false, no new history. Submitted
  derived fields are ignored, and existing stored lateness is preserved.
- A 450-second interval -> 0.13 hours half-up. 16181 seconds -> 4.49 and half day;
  16182 seconds -> 4.50 and full day. Overtime at 18:59:59 -> 0; at 19:00:00 -> 30.
  Exactly 24 hours is accepted; 24 hours plus one second is rejected with 422.
- Overnight 22:00 -> next-day 06:40 -> 8.67 hours and 40 overtime minutes,
  including December/January and leap-day transitions. Milliseconds are truncated.
- The most recent qualifying record is chosen by punch time. A closed selected
  record returns 409 while an older open record stays open; future records are
  excluded. Before the only punch-in -> 404; equality after truncation -> 422.
- Null, booleans, floats, strings, invalid bounds and huge timestamps -> 422.
  Missing employee/record -> 404; invalid path dates and missing correction
  metadata -> 422. Exact metadata length limits are accepted.
- Corrections from presence to ABSENT/LEAVE clear punches and derived values,
  and audit only changed fields. Absence with supplied punches -> 422. Presence
  without a final punch-in -> 422. Overnight corrections retain the addressed
  date. No-op corrections and an invalid final interval/date -> 422 without writes.
- Changes at 09:40:00.999, 09:40:01 and 10:15:59 yield 0, 10 and 45 late minutes.
  All derived values are recomputed. Older audit entries are retained exactly;
  nested before/after punches are BSON datetimes in MongoDB and integers in HTTP.
- Five natural 24-request punch-out races and five correction races per
  configuration check response codes, final state and every accepted history
  entry. Forced stale reads cover overlapping/separate correction fields and
  correction versus punch-out: one 200, one 409. Fields changed then restored
  still reject the waiting stale writer because history length changed.
- A separate database contains 1000 employees and 100000 logs with only default
  indexes before startup. Startup preserves both counts and builds the indexes;
  the shared live punch-out query's executionStats shows IXSCAN, no COLLSCAN or
  blocking SORT, one key and one document examined. Actual HTTP closes only the
  selected record. This is direct MongoDB explain evidence; the admin HTTP
  explain endpoint remains pending in Group 3.

Initial Group 1 run had 98 passes and five harness mistakes (wrong fixture dates
and an employee with an already closed log incorrectly expected to have no log).
Corrected those inputs; the next run passed all 120 checks then present in 8.63s.
Seven further status/metadata checks were added for the final 127-check Group 1
suite. Part 1 regression separately passed all 141 in 26.81s. Neither harness
errors nor these limited first runs are presented as full-matrix results.

Final verification command: `.venv/bin/python tests/run_runtime_matrix.py`.
MongoDB 7.0.43 and 6.0.28; Python 3.11.13; actual Uvicorn workers 1/2 and
UTC/Asia-Kolkata hosts. Tests use separately owned loopback ports 27038/27039.
Result: **2144 executions, zero failures/errors/skips** (268 per configuration;
1976 HTTP/MongoDB executions and 168 isolated helper executions).

| Configuration | Checks | Failures | Errors | Seconds | 100k preseed startup seconds |
|---|---|---|---|---|---|
| mongo7-workers1-UTC | 268 | 0 | 0 | 37.248 | 0.671 |
| mongo7-workers1-Asia-Kolkata | 268 | 0 | 0 | 33.275 | 0.766 |
| mongo7-workers2-UTC | 268 | 0 | 0 | 36.667 | 0.755 |
| mongo7-workers2-Asia-Kolkata | 268 | 0 | 0 | 39.183 | 1.236 |
| mongo6-workers1-UTC | 268 | 0 | 0 | 32.638 | 0.561 |
| mongo6-workers1-Asia-Kolkata | 268 | 0 | 0 | 33.524 | 0.554 |
| mongo6-workers2-UTC | 268 | 0 | 0 | 38.148 | 0.766 |
| mongo6-workers2-Asia-Kolkata | 268 | 0 | 0 | 36.546 | 0.757 |

Every punch-out scale plan examined one key and one document. Startup with only
_id indexes and 100000 preseeded records took 0.554-1.236 seconds across these
runs, below the 20-second readiness limit. Natural Group 1 races total 80 rounds
and 1920 concurrent requests; 48 additional forced interleavings verify stale
writers and retained history. Part 1's 80 insert-race rounds also remain passing.
These are repetitions of covered scenarios, not a claim about all possible races
or larger production workloads. JUnit/log/JSON artifacts: `/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-runtime-matrix-7jpnxzp6`.

Manual demonstration: restarted only this project's API at port 8001, retaining
its database and existing documents. Ten HTTP checks passed. EMP0099's October
12 record was punched out at 18:30 IST, then arrival was corrected to 10:00 and
status to WFH. Final values: 8.5 hours, 30 late minutes, zero overtime, full day,
two history entries. Duplicate closure -> 409; no-op and changed attendance date
-> 422; unknown employee -> 404. BSON punches and nested audit values are dates;
API values are integers. All other employee/attendance documents remained
unchanged. Evidence: `/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-group1-walkthrough.json`.

Remaining scope: employee monthly, department summary, late leaderboard,
department trend and admin explain are pending. No analytics, densify/window,
leaderboard or admin explain HTTP guarantee is claimed yet. Group 1 is ready for
the agreed user review before Group 2.

Cleanup verified: test databases removed, server failpoints off, both test-only
MongoDB containers stopped and removed. Manual MongoDB/API remain running;
health and Swagger docs respond successfully with both new routes present.

## Part 2 Group 2: employee monthly and department summaries

Both new handlers execute reusable MongoDB aggregations rooted in employees.
Monthly calendars and metric arithmetic execute in MongoDB. Attendance lookups
aggregate before returning at most one totals document per employee; source logs
are not fetched or aggregated in Python. All metrics use stored derived values.
Two employee eligibility indexes were added; nine non-default indexes now exist.

The new real HTTP/MongoDB suite has 120 checks. Concrete verified cases:

- Supplied July 2026 data: EMP0001 -> working 23, present 2, percentage 8.70;
  mid-month EMP0002 -> working 15, present 1, percentage 6.67. EMP0003 -> leave 1,
  late count 1, late minutes 35 and overtime 40. EMP0004 contributes 0.5 present;
  open EMP0006 contributes 1 present. Response fields match the supplied schemas.
- Department fixture results: Engineering headcount 2, present 3, average 9.04;
  Sales headcount 2, present 1.5, average 6.29, late 35 and leave 1; Support
  headcount 2, present 2, average 8.75 (the open record has no qualifying hours).
- Weekday/month calendars cover all twelve 2026 months with join dates at the
  first, middle and last day, plus leap years, December/January, weekend joining,
  and valid years 0001/9999. Post-month joiners have zero working days and null
  percentages and are excluded from monthly department headcount.
- People with no logs remain in eligible department headcount with zero totals
  and null work-hour means. Departments with only future joiners are omitted.
  Empty employee collections and orphan logs produce an empty summary. Filters
  are exact and case-sensitive, including an explicitly empty department filter.
- Every status is tested on weekdays/weekends with stored half-day flags. Only
  presence-status weekdays contribute present days; weekend late/overtime,
  LEAVE and ON_DUTY counts still apply. No-record weekdays do not become present.
- Hours 2+8+8+8 over four records -> mean 6.50, not the erroneous employee-mean
  value 5.00. Non-presence records and null hours are excluded; zero hours and
  qualifying weekend records are included. Mean ties 2.675, 0.005, 4.495 and
  9.035 round to 2.68, 0.01, 4.50 and 9.04. Half-day presence / 16 working days
  gives percentage 3.125 -> 3.13. R8 interpretation: percentages use two places;
  the future fractional trend rates will use four.
- Logs missing history, half-day, minutes and punches retain their legacy
  defaults. A stored 9.99 work-hours value remains authoritative even with
  punches spanning one hour. Analytics do not modify documents. A preceding
  correction is immediately reflected in both summaries without recalculation
  from punches or rewriting other records.
- Inclusive month boundaries use attendance dates, so a July 31 overnight shift
  with August 1 punch-out belongs to July. Records outside the month are excluded.
  Working-day denominators start at joined_on, while log metrics use the month
  and employee filters stated by the contract; no additional pre-join log filter
  is invented. A seeded pre-join log can count toward present days even when
  working days is zero; percentage stays null.
- Missing/invalid month (2026-7, 2026-13, 0000-01, impossible formats) -> 422.
  Unknown employee -> 404. An optional department with no matches -> empty items.
- On 1000 employees and 100000 logs, the exact live monthly, unfiltered department
  and filtered department pipelines show IXSCAN and no COLLSCAN. All attendance
  lookup stages report collectionScans 0 and the employee/date unique index.
  March lookups examine 31 / 31000 / 15500 logs respectively. Profiler checks
  show only 1 / 2 / 1 final summary rows transferred from the employees cursor.
  This is direct executionStats evidence; admin explain HTTP awaits Group 3.

Initial MongoDB 7 run: 81 passed in 3.24s, then expanded the suite. MongoDB 6
expanded run: 120 passed in 3.60s, zero failures. No new application defect was
reported from these runs. Final combined matrix results follow below.

Final command: `.venv/bin/python tests/run_runtime_matrix.py`. Python 3.11.13,
MongoDB 7.0.43/6.0.28; workers 1/2, UTC/Asia-Kolkata host timezones. Each
configuration passes **388 checks**: 367 HTTP/MongoDB and 21 isolated helpers.
Total **3104 executions**, zero failures/errors/skips (2936 HTTP/MongoDB,
168 direct helpers). These repeat covered scenarios across environments.

| Configuration | Checks | Failures | Errors | Seconds | Monthly HTTP seconds | Department HTTP seconds |
|---|---|---|---|---|---|---|
| mongo7-workers1-UTC | 388 | 0 | 0 | 34.001 | 0.004 | 0.128 |
| mongo7-workers1-Asia-Kolkata | 388 | 0 | 0 | 34.267 | 0.004 | 0.128 |
| mongo7-workers2-UTC | 388 | 0 | 0 | 41.582 | 0.004 | 0.132 |
| mongo7-workers2-Asia-Kolkata | 388 | 0 | 0 | 38.598 | 0.004 | 0.135 |
| mongo6-workers1-UTC | 388 | 0 | 0 | 33.900 | 0.004 | 0.136 |
| mongo6-workers1-Asia-Kolkata | 388 | 0 | 0 | 34.338 | 0.004 | 0.132 |
| mongo6-workers2-UTC | 388 | 0 | 0 | 39.153 | 0.003 | 0.134 |
| mongo6-workers2-Asia-Kolkata | 388 | 0 | 0 | 40.137 | 0.005 | 0.139 |

Every root/lookup plan passed IXSCAN/no-COLLSCAN checks; every lookup reports
zero collection scans and examines only the matching employee/month records.
Observed HTTP times on the local 100000-log fixture: monthly 0.003-0.005s,
unfiltered department 0.128-0.139s, filtered department 0.063-0.079s. These are
local measurements, not production latency guarantees. Preseed startup still
preserves 1000 employees/100000 logs and takes 0.561-1.182s with all nine indexes.
Earlier readiness/outage/recovery, validation, BSON and concurrent write tests
remain passing. JUnit/log/JSON evidence: `/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-runtime-matrix-iv2l842r`.

Manual walkthrough: restarted only our API, PID 59908, on port 8001;
retained database attendance_manual_dev_888d4e68 without reseeding. Fifteen
actual HTTP checks passed. Verified supplied July employee summaries, department
means/headcounts, exact filters, unknown employee 404, invalid/missing month 422,
August no-log headcount, and EMP0099's corrected October record: 22 working
days, 1 present day, 30 late minutes, attendance percentage 4.55. The Testing
department returns headcount 1 and mean 8.50 hours. Every employee/attendance
BSON document matched its pre-restart snapshot; only the two new employee indexes
were added. Swagger includes both routes. Evidence:
`/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-group2-walkthrough.json`.

Remaining scope at Group 2 completion was late leaderboard, department trend
and admin explain. The direct aggregation explanations above do not claim admin
HTTP evidence; that endpoint's executed checks are recorded in Group 3 below.

Cleanup verified: audit databases removed, failpoints off, both Group 2 test-only
MongoDB containers stopped and removed. Manual MongoDB/API remain running and
healthy; final live requests to both analytics routes returned 200.

## Part 2 Group 3: leaderboard, trend and admin explain

All twelve contract endpoints are implemented in app/main.py. Nine non-default
indexes support the current operations; no extra Group 3 indexes were needed
in initial executed plans. Group 3 adds 124 real HTTP/MongoDB checks. The final
combined suite has 512 checks per configuration (491 HTTP/MongoDB, 21 isolated
helpers). Final eight-configuration results and the preservation-checked manual
walkthrough appear in the final section below.

Concrete executed Group 3 evidence:

- July fixture leaderboard returns EMP0003, Neha Iyer, Sales, total late 35,
  late_count 1, rank 1. Scores 100/80/80/40 yield competition ranks 1/2/2/4.
  Limits 2 or 3 return the first three people; a limit of 1 with 60 top ties
  returns all 60 in employee-code order. Department filtering precedes ranking.
- Stored lateness on all statuses and weekends counts; zero/missing minutes,
  no-log employees and orphan logs do not enter rankings. Inclusive month filters
  use attendance dates, including overnight logs. Employee identity/name and
  department come from the employee collection; joining-date headcount rules
  are not invented for the leaderboard.
- Trends return exactly the inclusive daily range, even for all-empty ranges,
  weekend-only ranges, one day, 92 days, leap days, year rollover and valid
  calendar years 0001/9999. Bounds are integer calendar days relative to January
  1, 1970; grouping and $densify execute in MongoDB. Real stored logs at both
  calendar extremes also pass on MongoDB 7 in the first combined run.
- Daily headcount changes on joining dates and includes employees without logs.
  Presence statuses and stored half-day flags count on weekends as well as
  weekdays. No/zero headcount and weekends have null rates; eligible empty
  weekdays have 0.0. Pre-join logs are not filtered by a rule absent from the
  contract; their zero-denominator rate remains null. Orphans and employees in
  other departments do not affect metrics. Exact department names with spaces,
  Unicode, dollar signs and encoded slashes work.
- Moving windows contain the current and six preceding calendar rows within
  the requested range; earlier logs are excluded and null rates are ignored.
  July 13's window contains July 7-13, not seven working days. A shortened first
  window includes only its first row. Entirely null windows remain null.
- With 32 employees, one present record gives 1/32 = 0.03125 -> rate 0.0313.
  Mean(0.0313, 0.0) = 0.01565 -> moving average 0.0157, proving half-up and the
  contract's average of reported daily rates. Half a present day gives 0.0156.
- Read-after-correction tests show updated rankings and trends immediately,
  without rewriting other documents or recalculating stored fields from punches.
- Unknown department -> 404. Missing/wrong query names, malformed dates, reversed
  or 93-day ranges -> 422. Leaderboard invalid/missing month and out-of-range
  limit -> 422. Live/admin from/to aliases retain real calendar validation.
- All five admin names return the endpoint, actual collection and raw explain
  with executionStats. Missing operation-specific parameters and unsupported
  names -> 422. Shared filters, projection, sort, pagination, limit/rank cutoff
  and hints match live profiler commands exactly. Giant positive page offsets
  are capped at BSON int64 maximum in the shared operation and return zero rows.
  All raw BSON operands are preserved using relaxed Extended JSON, rather than
  dropping plan fields. Explain reports the main operation even without a
  matching resource; live resource existence checks are outside the main plan.
- On 1000 employees and 100000 logs, seven actual explain HTTP requests exercise
  attendance listing, monthly, department all/filtered, leaderboard all/filtered
  and department trend. All contain IXSCAN and no COLLSCAN, including attendance
  and per-day employee headcount lookups. All lookup collectionScans values are 0.
  The live March trend has 31 rows, daily headcount/presence 500, weekday rates 1
  and weekend rates null. Ten top tied employees have rank 1 despite limit 2,
  including department-filtered results.

Development failures and actual fixes:

- Initial new MongoDB 7 run: 94 passed, five failed (3.77s). Two real handler
  defects returned 500 for from=2026-02-30 / 2026-7-06. Query aliases in default
  values lost custom date validators; moving Query into Annotated metadata
  fixes both live and admin aliases. The expanded regressions assert 422 for
  impossible dates, wrong formats and years on both from/to.
- Three harness mistakes: wrong sample name and stale profiler captures from
  prior requests when the current list returned no items. Corrected fixture name
  and isolated captures. One diagnostic edit briefly caused an IndentationError
  in a temporary server; corrected and compiled, then removed its audit DB.
  The manual service was unaffected.
- Corrected MongoDB 7 run: 99 passed in 3.70s. Expanded MongoDB 6 run: 122 passed
  in 3.76s. Two stored-log calendar-extreme checks bring Group 3 coverage to 124.
- First combined 512-check run: 511 passed, one harness failure (41.06s). The
  earlier Group 2 profiler case included Group 3 entries left in system.profile,
  counting 11 rows for its one-row operation. Clearing captures before every
  Group 2 measured operation fixes isolation without weakening assertions.
  This failed run is not counted toward final compatibility verification.


## Group 3 final matrix and completed API

Command: `.venv/bin/python tests/run_runtime_matrix.py`.
Real MongoDB 7.0.43/6.0.28, detached Uvicorn workers 1/2, application TZ UTC/IST.
All eight configurations completed after the profiler-isolation fix:

| Configuration | Passed | Failures/errors/skips | Seconds |
|---|---:|---:|---:|
| mongo7-workers1-UTC | 512 | 0/0/0 | 39.334 |
| mongo7-workers1-Asia-Kolkata | 512 | 0/0/0 | 41.317 |
| mongo7-workers2-UTC | 512 | 0/0/0 | 47.151 |
| mongo7-workers2-Asia-Kolkata | 512 | 0/0/0 | 49.139 |
| mongo6-workers1-UTC | 512 | 0/0/0 | 45.500 |
| mongo6-workers1-Asia-Kolkata | 512 | 0/0/0 | 44.702 |
| mongo6-workers2-UTC | 512 | 0/0/0 | 46.687 |
| mongo6-workers2-Asia-Kolkata | 512 | 0/0/0 | 52.203 |

Total: **4096 executions, zero failures/errors/skips**. Each configuration has
141 starter checks, 127 Group 1 checks, 120 Group 2 checks and 124 Group 3 checks.
Of the 512, 491 exercise real HTTP/MongoDB and 21 are explicitly isolated helper
checks: 3928 HTTP/MongoDB and 168 helper executions across the matrix. Retained
write races, startup/outage recovery, timestamp/BSON, filters and pagination
checks also pass; helper evidence is not counted as HTTP evidence.

ExecutionStats on the representative 1000-employee/100000-log fixture verifies
seven actual admin HTTP requests: all five operations, plus filtered department
summary and leaderboard. Every root plan contains IXSCAN and no COLLSCAN;
attendance and daily employee-eligibility lookups report indexesUsed and zero
collectionScans. Profiler captures prove the shared live/admin operation has the
same pipeline or find filters, projection, sort, page offset/limit and hint.
Tests assert real results as well as plans: 31 dense trend days, correct daily
headcount and rates, and every rank-1 cutoff tie. Nine non-default indexes suffice
on both tested MongoDB versions; no additional index or dependency was added.

Observed explain HTTP durations on this local fixture (seconds): attendance
0.003-0.005; monthly 0.004-0.008; department all 0.141-0.240 / filtered
0.068-0.114; leaderboard all 0.067-0.092 / filtered 0.037-0.047; trend
0.077-0.152. Preseeded startup preserved counts and completed in 0.612-1.349s.
These observations describe this executed fixture, not larger-scale guarantees.

Final JSON/log/JUnit evidence directory:
`/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-runtime-matrix-napeogq_`.

Manual demonstration command:
`.venv/bin/python /tmp/candidate-kit-group3-walkthrough.py`.
Verified the old project's PID/working directory, restarted only that API with
its existing URI/database, and saved the new PID 73940 in session metadata.
All 22 HTTP assertions passed: July/October rankings and exact department
filters, joining-date headcount, empty daily ranges, rates/windows, 404/422
validation, all five raw explain names and the generated twelve-endpoint schema.
The prior EMP0099 correction appears in October's leaderboard and Testing trend.
Exact BSON snapshots show every employee and attendance document unchanged,
including its two prior audit entries. Index counts remain employees 5 and
attendance 6 including _id. No reseeding occurred.

Manual request/response evidence:
`/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-group3-walkthrough.json`.
The app remains available at http://127.0.0.1:8001/docs with its manual MongoDB.

Cleanup checked before stopping test servers: no audit databases remained and
failCommand was off on both ports 27038/27039. Stopped and confirmed removal of
only candidate-kit-group3-mongo7/mongo6. Manual MongoDB is running; final health,
docs, leaderboard, trend and admin explain requests return 200. All twelve
contract endpoints are implemented. Required submission documents are reconciled;
publication/submission has not been performed.

Final user walkthrough: 13 fresh HTTP checks against the retained development
app passed (health, existing attendance, monthly/department/leaderboard/trend,
422/404 examples and all five explain operations). Every plan contains IXSCAN
and no COLLSCAN; exact employee/attendance BSON snapshots remain unchanged.
Evidence: `/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-final-review-walkthrough.json`.

## Publication preparation: clean checkout

Exported the explicit 24-file staged Git tree to a temporary clean checkout,
created a fresh Python 3.11 environment and installed only requirements.txt.
Installation and pip check passed. A separate UUID database on local MongoDB 7
was used for 19 real HTTP checks: all twelve operations, strict timestamp/date
validation, generated schema, and all five indexed executionStats plans.
Startup returned healthy in 2.575s; documents and nine non-default indexes had
the required shapes. The test server was stopped and only that UUID database
was dropped; the manual database was not used for test writes.

Fresh install versions: FastAPI 0.143.0, Uvicorn 0.54.0, PyMongo 4.18.3,
Pydantic 2.14.1. This is a smoke check on the newer Pydantic patch, not a rerun
of the eight-configuration matrix recorded above. Pip reported that modern
PyMongo does not define the legacy srv extra; installation still installed
dnspython and passed dependency checks. Requirements were left unchanged.
Git's whitespace check found one trailing blank line in tests/conftest.py;
removed that blank line without changing test behavior.

Commands: export via git checkout-index; python3.11 -m venv; pip install
-r requirements.txt; pip check; .venv/bin/python /tmp/candidate-kit-publish-smoke.py.
Evidence: `/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-clean-checkout-g2oea6nj/smoke-evidence.json`.
Credential-pattern scan of the publish manifest, including DOCX XML, found no
matches. Local .env files, environments, caches, logs and generated dumps are
excluded. This does not claim exhaustive detection of every possible secret.

## Public repository publication

On 2026-10-12, published the user's authorized 24-file project as
[iworkforpurpose/hrone-attendance-api](https://github.com/iworkforpurpose/hrone-attendance-api).
The local project has its own Git repository; unrelated home-directory history
is excluded. Implementation commit: 0d553777e02fc6fcc6dc5b6ffddd60f25fbddd7d.

GitHub API confirms public visibility, private=false and main as the default
branch. An anonymous HTTPS clone with credentials/prompts disabled succeeded;
its HEAD matched the pushed commit and every tracked file matched byte-for-byte.
The exact 24-file manifest excludes environments, secrets, caches, Dockerfiles
and generated dumps. README now provides the repository link and clone setup.
Publishing was authorized; evaluator submission remains explicitly deferred.

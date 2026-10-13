# Development continuity log

## Current state

- Agreed workflow: Part 1 is review and fix; Part 2 is implementation.
- Documentation is maintained during both parts using the checkpoint in `AGENTS.md`.
- Active state: Part 1 and all three Part 2 groups are implemented and verified;
  the additional desktop/mobile Playwright Swagger walkthrough passed.
  The public GitHub repository is published. Evaluator submission is deferred.
- Manual testing runtime: API http://127.0.0.1:8001 (PID 73940), MongoDB container
  candidate-kit-dev-mongo at port 27028, database attendance_manual_dev_888d4e68.
  Both are deliberately running for the user; see manual session entry below.
- Completed: all supplied files read, 40 starter findings repaired, persistent
  documentation checkpoint maintained, approved UTC/synchronous architecture implemented,
  writes/audit concurrency, all analytics and five admin explain operations verified.
- Verification: 512 checks passed in each of eight real MongoDB 6/7 × workers
  1/2 × UTC/IST configurations (4096 executions; zero failures/errors/skips).
  Additional browser verification: 46 scenarios per Chromium viewport, 92
  executions total; all twelve endpoints and five explain names passed.
  See RUNTIME_AUDIT.md for original baseline and repaired evidence.
- Repository: https://github.com/iworkforpurpose/hrone-attendance-api (public,
  main branch; local project repository tracks origin/main).
- Next action: review the browser results with the user; submit only when
  explicitly requested. Submission remains deferred.
- Planning decisions: immediate 409 on stale corrections; $densify trends; three review groups; full eight-configuration matrix before every group review. No pending Group 3 questions.
- User preference: real runtime evidence is required; do not present assumptions
  or static review candidates as runtime-confirmed defects. Keep test evidence
  and remaining uncertainties explicit in all documentation and reports.

## Initial review observations

These are observations from the original starter, not implemented fixes or test results.
Use them to start the detailed `REVIEW.md` inventory during Part 1.

- Startup creates no indexes; `/health` returns success without a MongoDB ping.
- Input models and query parameters omit required contract validation.
- Timestamp storage and responses need explicit UTC/IST handling, truncation,
  and epoch-millisecond serialization, including nested correction history later.
- `compute_late_minutes` floors minutes before testing grace; 09:40:01 against
  a 09:30 shift returns 0 instead of 10. Overnight attendance dates are unhandled.
- Work hours use Python rounding; overtime lacks the 30-minute threshold,
  overnight end-date handling, and consistent aware datetime arithmetic.
- Employee creation and punch-in use check-then-insert without unique indexes.
- Employee listing skips the wrong offset, counts unfiltered records, and lacks
  the required ordering. Attendance listing loads and sorts all matching logs in
  Python, omits the employee-code tie-breaker, and exposes an attendance `id`.
- Attendance responses do not consistently supply missing legacy defaults.
- README setup refers to a missing `.env.example`; the sample seed script
  deletes both collections' contents and requires a disposable development database.

## How to maintain this log

For each meaningful change, append a concise entry with the part, affected files,
change and reason, verification command/result, documentation updated, and open
questions. Keep the current-state section accurate for the next session. Transfer
completed review findings to `REVIEW.md` and implemented decision explanations to
`DECISIONS.md`; avoid duplicating their entire contents here.

## 2026-10-11: Part 1 runtime evidence

- User explicitly requested real runtime facts and persistence of that preference;
  added the instruction to `AGENTS.md` and this log.
- Created `.venv` with Python 3.11.13 and installed application/test dependencies.
  Added `requirements-dev.txt` and `.gitignore` to keep setup reproducible and
  generated environments, caches, and local environment files out of version control.
- Ran MongoDB 7.0.43 in a dedicated `mongo:7` container bound to localhost port
  27028. Generated unique disposable databases; fixtures and profiling touched
  those databases only. No application code or supplied fixtures were changed.
- Added `tests/test_starter_contract.py`: actual Uvicorn processes, HTTP requests,
  BSON document inspection, concurrency rounds, timezone variants, and a
  100000-record MongoDB profiler check. No app/database mocks were used.
- Command: `.venv/bin/python -m pytest tests/test_starter_contract.py -q --tb=no
  --junitxml=/private/tmp/candidate-kit-runtime.65zAgB/audit.xml`.
- Final result: 83 failures, 18 passes in 5.21s; 92 HTTP/database checks and 9
  separately identified helper checks. Recorded runtime findings and passing
  behavior in `REVIEW.md`, with environment and evidence in `RUNTIME_AUDIT.md`.
- An initial sandboxed attempt could not access localhost sockets and is not
  counted as application evidence. Successful tests ran with approved socket access.
- While validating the harness, isolated client connections between cases so an
  intentional 500 could not contaminate the next case through a stale connection.
- Found additional concrete cases beyond the initial overview: accepted explicit
  null/zero, boolean timestamps, huge timestamp 500, negative-pagination 500,
  incorrect stored UTC instants on an IST host, missing minute defaults, ignored
  empty employee filters, and ISO strings inside nested history.
- `DECISIONS.md` remains a template because no implementation choices have yet
  been applied to the app. The documentation checkpoint is current.
- Updated README with test instructions, the audit's unfinished implementation
  status, and explicit local environment variables instead of the missing
  `.env.example` copy step. No service behavior was changed.
- Cleanup: test-created databases and HTTP processes were removed by the suite;
  the temporary MongoDB container was stopped and automatically removed. Verified
  the unchanged application hash and the report's counts against the JUnit XML.

## 2026-10-11: Part 1 planning discussion

- User requested listing all failures, then questions one by one to plan all Part 1
  fixes before completing Part 1 together. Persisted this preference in `AGENTS.md`.
- Inventory IDs remain those in `REVIEW.md`; overlapping symptoms may share a
  repair. Helper-only evidence and datetime compatibility observations remain labeled.
- Proposed repair sequence: shared time/validation/serialization foundations,
  database readiness and uniqueness, existing endpoint repairs, then complete
  regression verification and documentation reconciliation.
- First proposed design choice: aware UTC internally and in the MongoDB client;
  IST for business calendar/shift calculations; epoch milliseconds at the API.
  Awaiting discussion; application code is unchanged.

## 2026-10-11: Approved Part 1 plan

- User selected aware UTC throughout Python and MongoDB reads, synchronous PyMongo with synchronous handlers, and closing all known verification gaps in Part 1.
- Implement six indexes supporting uniqueness and existing list filters/sorts. Direct inserts plus duplicate-key handling replace check-then-insert races.
- Startup and retrying readiness preserve seeded documents. MongoDB failure produces 503; recovery retries index creation.
- Shared shift context, strict validation, recursive timestamp serialization, and database pagination underpin all five existing endpoints. Seven missing endpoints remain Part 2.
- Verification and documentation reconciliation are pending; no proposed repair is yet marked verified.

## Part 1 first repair verification

- Implemented shared UTC/IST shift helpers, strict validation, response serializers, six indexes, retrying readiness, synchronous handlers, direct insert conflict handling, and reusable MongoDB listing builders in `app/main.py`.
- First real MongoDB 7 run: `.venv/bin/python -m pytest tests/test_starter_contract.py -q --tb=short --junitxml=/tmp/candidate-kit-part1-first.xml`: 101 passed in 9.74s. No mocks. The nine helper tests now supply full shift/date context; assertions retain the original expected contract outcomes.
- Extended verification is in progress. MongoDB 6/7 and multiworker results are not yet claimed.

- Expanded verification initially returned 134 passes and one harness error: the recovery test generated a 69-character database name exceeding MongoDB's 63-character limit. Shortened test-only identifiers and reran; this was not an application failure.

## Part 1 completion and documentation checkpoint

- Repaired every existing endpoint and the work-hour/overtime helpers; all 40
  baseline inventory entries in REVIEW.md now state actual fixes. Part 2 remains
  explicitly missing, with no proposed implementation described as completed.
- Final verification command: `.venv/bin/python tests/run_part_one_matrix.py`.
  MongoDB 7.0.43/6.0.28; workers 1/2; UTC/Asia-Kolkata; 141 passed per configuration,
  1128 total test executions, zero failures/errors/skips. Of these, 960 are
  HTTP/database checks and 168 are helper executions, kept distinct in the report.
- Verified actual outage/recovery, startup while unavailable, startup preservation
  and idempotence, conflicting .env precedence, existing duplicate-data preservation,
  time/calendar boundaries, strict validation, legacy and nested serialization,
  eighty concurrency rounds, and 100000-record indexed pagination/executionStats.
- Updated README setup/current scope/testing, REVIEW actual repairs, DECISIONS
  implemented index/race choices (182 words, Part 2 answers pending), AGENTS
  current-state pointer, and RUNTIME_AUDIT historical/final evidence. Checkpoint
  checked and reconciled with application code. Requirements did not need changes.
- JUnit artifacts: `/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-part1-matrix-rr414s4b`.
- No supplied contract/fixture edits, seeding of a user database, publishing, or
  application code outside app/main.py. Cleanup of test-owned runtime resources
  is checked before ending the session.
- Cleanup confirmed: no audit databases or recovery containers remained; stopped
  both test-owned `--rm` MongoDB containers and confirmed their removal.

## Manual testing session

- User requested running the app for hands-on testing. Port 8000 is occupied by another project, so this app listens on http://127.0.0.1:8001.
- Started MongoDB 7 container `candidate-kit-dev-mongo` at `mongodb://127.0.0.1:27028`. Explicitly created fresh disposable database `attendance_manual_dev_888d4e68` and ran `sample_seed.py` only against that database: six employees and nine attendance logs.
- Started detached Uvicorn with `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001`, PID 36113; MONGO_URI/MONGO_DB supplied explicitly, no .env required. Log: `/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-dev-api.log`; session metadata: `/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-dev-session.json`.
- Actual HTTP checks: /health 200 with status ok; /employees 200, total 6; /attendance 200, total 9; /docs 200. Service and MongoDB deliberately remain running for the user.
- Stop this API using its recorded PID; stop/start only `candidate-kit-dev-mongo` to retain manual-test data. Application code and submission documents remain current; documentation checkpoint checked. Part 2 remains pending.

## Executed manual walkthrough

- User explicitly asked to execute the walkthrough. Ran 17 real HTTP checks against http://127.0.0.1:8001, database `attendance_manual_dev_888d4e68`; all status and response assertions passed. Full exact request/response evidence: `/var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-manual-walkthrough.json`.
- Created EMP0099 (Test User, testuser@example.com, Testing, joined_on 2026-10-01); observed 201, default 09:30/18:30 shifts, integer created_at. Repeat returned 409. Testing filter found this employee; lowercase testing returned zero.
- Punched EMP0099 in with epoch 1791777600000 (2026-10-12 09:30 IST); observed 201, date 2026-10-12, late_minutes 0, punch_out/work_hours null, overtime 0, half_day false, history []. Repeat returned 409. Exact attendance filters returned that single record.
- Invalid employee code BAD, zero/null punch timestamps, ABSENT punch-in status, page 0 on both listings, impossible date 2026-02-30, and reversed bounds all returned 422 with detail. Unknown EMP9999 returned 404.
- Real MongoDB inspection confirmed exactly one new employee and one new attendance natural key, a BSON datetime equal to 2026-10-12 04:00 UTC truncated to seconds, empty history, and unchanged preexisting documents. Counts increased by one in each collection.
- Left the new records and both services running for the user to inspect. No application changes; documentation checkpoint checked. Part 2 remains pending.

## Part 2 planning started

- User asked what to plan next. Reread punch-out/correction, analytics/explain endpoint prose and stored-value/audit requirements. No API changes.
- Proposed order: punch-out and corrections; employee monthly and department summary; late leaderboard and department trend; admin explain/index verification. Build shared query/pipeline builders alongside each handler so explain remains equivalent. Maintain documentation throughout.
- First question presented through the question tool: immediate 409 on conflicting corrections (recommended: visible conflict, simpler verification) versus bounded automatic retries for non-overlapping edits (both may succeed, overlapping edits still conflict, additional interaction tests). This is an implementation choice; contract behavior and punch-out single-winner requirement are fixed. No response or agreement recorded yet.
- Planned evidence: real HTTP/MongoDB rules, simultaneous writes and retained history, no-log employees, tie cutoffs, empty daily ranges, half-up rounding, MongoDB 6/7, and executionStats on approximately 100000 logs. Documentation checkpoint checked; implementation and these checks remain pending.

## Part 2 approved decisions and implementation start

- User selected immediate 409 for concurrent corrections, gap filling with $densify, separate reviews for writes / summaries / leaderboard-trends-explain, and the full MongoDB 6/7 × workers 1/2 × UTC/IST matrix before each review.
- User requested implementing the plan. This session implements Group 1 only, as the agreed review boundary; the other five endpoints remain future groups.
- Use conditional single-document updates matching original fields and history length. This avoids a storage revision field or replica-set requirement, preserves accepted audit entries, and rejects stale writes. No process-local write locks or automatic retry.
- Add attendance employee/punch-time/date index. Other new analytics indexes wait until their consumers are implemented.
- Tests use separately owned MongoDB containers on ports 27038/27039 and disposable databases. Manual database attendance_manual_dev_888d4e68 is preserved. Controlled concurrency timing affects test containers only.
- Implementation and verification pending at this checkpoint.

## Group 1 implementation and first verification

- Added punch-out selection and guarded closure, plus final-state correction validation, derived-value recomputation and atomic history append in app/main.py. Added employee/punch-time/date index; seven non-default indexes now exist across the two collections. No storage revision field or transactions are required.
- Extracted shared real HTTP/MongoDB fixtures into tests/conftest.py without replacing database or application calls with mocks. Added Group 1 boundary, legacy, metadata, concurrency and 100000-record preseed startup/index checks.
- First Group 1 run: 98 passed, five failed because test inputs referenced wrong fixture dates or expected no record for an employee who already had a closed log. Corrected test inputs; these were harness mistakes, not application defects.
- Second Group 1 run: 120 passed in 8.63s on MongoDB 7. Full Part 1 regression: 141 passed in 26.81s. Subsequently added seven presence/status/metadata boundary checks; their verification is in the full matrix now running.
- Forced stale-write tests use server findAndModify failpoints on test-only ports 27038/27039. They demonstrate 409 without losing history for overlapping fields, separate fields, correction/closure interactions, and fields changed then restored. Application code has no test timing hooks.
- Added tests/run_runtime_matrix.py for all implemented tests and eight agreed configurations, with JUnit, log and JSON evidence. Full matrix is pending. README, REVIEW and DECISIONS reflect implemented Group 1 scope; final result reconciliation and manual demonstration remain next.

## Group 1 completion and documentation checkpoint

- Final command: .venv/bin/python tests/run_runtime_matrix.py. All 268 checks passed in each of eight MongoDB 7.0.43/6.0.28 × workers 1/2 × UTC/IST configurations: 2144 executions, zero failures/errors/skips. Per configuration, 247 HTTP/MongoDB and 21 isolated helper checks. New Group 1 coverage is 127 checks.
- Seven non-default indexes created idempotently. On a 100000-log database preseeded before startup with only _id indexes, health became ready in 0.554-1.236s and preserved document counts. Punch-out executionStats showed IXSCAN, no COLLSCAN or blocking SORT, one key/document examined. This does not claim the unimplemented admin explain endpoint.
- Across the matrix, Group 1 natural races ran 80 rounds with 1920 concurrent requests, plus 48 forced interleavings. Every punch-out round had exactly one 200; successful corrections retained every accepted history entry; stale reads and change-then-restore cases returned 409.
- Evidence directory: /var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-runtime-matrix-7jpnxzp6. README, REVIEW, DECISIONS (189 words), RUNTIME_AUDIT and AGENTS reconciled with actual implementation and results. No dependency changes were needed.
- Verified the recorded old PID and cwd, restarted only our development API; new PID 54496. URI/database unchanged; no reseeding. Executed ten real HTTP checks and raw BSON/preservation assertions, all passed. EMP0099 2026-10-12 is now WFH, arrival 10:00 IST, exit 18:30, hours 8.5, late 30, overtime 0, half_day false, history length 2. Every other existing document was preserved.
- Manual evidence: /var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-group1-walkthrough.json. Session metadata updated; API and candidate-kit-dev-mongo deliberately remain running for user inspection.
- Group 1 ready for the agreed review. Group 2 and Group 3 remain pending; do not start the next group before reviewing user feedback. Test-resource cleanup is checked separately below. Documentation checkpoint checked.

- Cleanup verified: no audit databases remained on either test server; failpoints were off. Stopped and confirmed removal of candidate-kit-group1-mongo7/mongo6 only. Manual container and API remain running; final health, docs and generated schema checks pass. Documentation checkpoint checked again after cleanup.

## Group 2 authorization and implementation start

- User reviewed the next step and said “sure continue,” authorizing Group 2. Group 1 review boundary is satisfied. Group 3 remains a later reviewed group.
- Build both analytics as reusable MongoDB aggregation pipelines rooted in employees. Employee-root lookup preserves no-log headcount and ignores orphan logs; log subpipelines aggregate before returning data, avoiding raw-log arrays or Python aggregation. Department mean uses summed hours and qualifying record counts, not employee means.
- MongoDB computes monthly weekdays and present-day contributions. Working days honor joined_on; log metrics filter by employee and month, with weekday restriction only for present_days as stated in R7. Do not invent a pre-joining log filter. All statuses contribute their stored lateness/overtime and explicit leave counts as specified.
- R8 interpretation: attendance_pct is a percentage (0-100), rounded to two decimals; four decimals applies to the fractional attendance_rate and moving averages in future trends. Record this distinction because R8 uses the general word rates. Decimal128 aggregation arithmetic implements half-up, including averages.
- Add employee joined_on/department/emp_code and department/joined_on/emp_code indexes for eligible employee scans and filtered summaries. Reuse attendance employee/date uniqueness index for month-range lookups. Current index choices must be verified with executionStats including lookup plans on 100000 logs.
- Test-only servers: candidate-kit-group2-mongo7/mongo6 on ports 27038/27039, enabling test commands only there for retained Group 1 race checks. Manual DB and service stay untouched until a preservation-checked restart for the demonstration.
- Implementation, new tests and full matrix pending; previous Group 1 results remain historical evidence.

## Group 2 pipelines and initial runtime evidence

- Implemented strict calendar month validation and both endpoints in app/main.py. Shared log subpipelines aggregate at most one totals record per employee; MongoDB counts monthly eligible weekdays, presence-status weekdays with stored half-day contributions, leave, lateness and overtime. All returned summary arithmetic stays in MongoDB.
- Department pipelines start with eligible employees (including no-log people), then group employee totals by department. Summing qualifying decimal hours and record counts gives a record-weighted mean; non-presence or null-hour records are excluded. Calendar-day filters, not punch-out timestamps, define the reporting month.
- Decimal128 half-up expressions use floor(x*10^places+0.5) on non-negative reported values, rather than half-even $round. Attendance percentages use two places; trends will use four for fractional rates. No supplied contract or fixture edits.
- Nine non-default indexes now exist: the prior seven plus employee joined_on/department/code and department/joined_on/code. Updated the startup index-count test; existing behavior assertions are retained. No requirements changes.
- First new suite command: TEST_MONGO_URI=mongodb://127.0.0.1:27038 .venv/bin/python -m pytest tests/test_group_two_analytics.py -q --tb=short --junitxml=/tmp/candidate-kit-group2-first.xml. Observed 81 passed in 3.24s on MongoDB 7.0.43. Actual 100000-log explanations show IXSCAN and no COLLSCAN, including attendance lookup, and profiler captures only final summary rows sent to the HTTP handler.
- Expanded coverage with all twelve months and three joining-day positions, zero working days with logs, overnight month-end storage, read-after-correction behavior, and a real percentage half-up tie (3.125 -> 3.13). Final matrix remains pending.
- MongoDB lookup/index and decimal behavior were checked against official documentation, then verified with executed plans and boundary cases. Prefer runtime evidence over assuming planner behavior: https://www.mongodb.com/docs/manual/reference/operator/aggregation/lookup/.

- Expanded MongoDB 6 verification command: TEST_MONGO_URI=mongodb://127.0.0.1:27039 .venv/bin/python -m pytest tests/test_group_two_analytics.py -q --tb=short --junitxml=/tmp/candidate-kit-group2-mongo6.xml. Observed 120 passed in 3.60s.
- Started full tests/run_runtime_matrix.py (388 checks per configuration). Updated README/current scope, REVIEW/implemented analytics, DECISIONS/headcount and indexes (196 words), AGENTS/test map, and RUNTIME_AUDIT/concrete cases. Full matrix, demonstration and cleanup remain pending at this checkpoint.

## Group 2 completion and documentation checkpoint

- Final tests/run_runtime_matrix.py result: 388 passed in each of eight MongoDB 7.0.43/6.0.28 × workers 1/2 × UTC/IST configurations. Total 3104 executions, zero failures/errors/skips. Per configuration: 367 HTTP/MongoDB and 21 direct helper checks; new Group 2 coverage: 120 checks.
- Every exact live monthly, full department and filtered department aggregation passed IXSCAN/no-COLLSCAN checks, including attendance lookup. Each lookup uses attendance_employee_date_unique and reports zero collection scans. The March fixture examines 31 / 31000 / 15500 matching logs. Profiler verifies only 1 / 2 / 1 final rows are transferred.
- Local 100000-log HTTP observations: monthly 0.003-0.005s; department all 0.128-0.139s; filtered 0.063-0.079s. These are local fixture results, not general performance guarantees. Preseed startup with nine non-default indexes remains below 20s (0.561-1.182s), preserving both collection counts.
- Evidence directory: /var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-runtime-matrix-iv2l842r.
- Restarted only the verified project API; new PID 59908, same URI/database. Fifteen manual HTTP assertions passed plus exact BSON document snapshot preservation. Both analytics routes appear in Swagger. EMP0099 October analytics reflects the existing correction: working 22, present 1, late 30, percentage 4.55; Testing mean 8.5, headcount 1. No seeded or walkthrough documents changed.
- Walkthrough evidence: /var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-group2-walkthrough.json. Service and manual MongoDB deliberately remain running for the user.
- README, REVIEW, DECISIONS (196 words), AGENTS and RUNTIME_AUDIT reconciled with code and executed evidence. Dependencies and supplied contracts/fixtures unchanged. Group 3 remains pending until the agreed group review. Documentation checkpoint checked; cleanup follows.

- Cleanup verified: both test servers had no audit databases and failpoints were off. Stopped and confirmed removal of candidate-kit-group2-mongo7/mongo6 only. Manual MongoDB and API remain running; final health/docs and both live analytics routes return 200. Documentation checkpoint checked after cleanup.

## Group 3 authorization and implementation start

- User said “alright, let's proceed for next step,” satisfying the Group 2 review boundary and authorizing Group 3.
- Leaderboard aggregates positive stored lateness per known employee/month, ranks by total only with $rank, applies rank <= limit, and sorts ties by emp_code afterward. Department filter is applied before ranking. Reuse current employee and attendance indexes, subject to actual executionStats.
- Trend starts with department employees, looks up per-day stored attendance totals, groups by day, adds zero-value first-day anchors, then applies $densify with explicit exclusive upper bound. Numeric calendar-day ordinals avoid Python datetime overflow at years 0001/9999. No Python gap filling, ranking or moving windows.
- Daily headcount is a separate indexed employee lookup with joined_on <= that day. Presence includes weekends and stored half days. Consistent with Group 2, no extra pre-joining log filter is invented; eligibility controls the denominator. Window averages use the reported (already rounded) daily attendance_rate over the current and preceding six calendar rows inside the range.
- Admin explain runs executionStats with the same builders/hints/filter/sort/pagination as handlers. Monthly and trend require their identifying query parameters; explain reports the main query plan rather than enforcing live resource existence prechecks (its contract declares 200/422). Preserve raw BSON explain values as relaxed Extended JSON when plain JSON has no equivalent type.
- Shared find operation caps pagination offsets at signed BSON int64 maximum, an unreachable offset for any valid collection, avoiding huge-page BSON overflow while live and explain remain equivalent. The original filter still drives total counts.
- No new indexes are proposed yet; nine existing indexes match these lookups. Runtime evidence decides if additional indexes are needed. Manual runtime stays unchanged until verification and preservation-checked restart. Test-only Group 3 MongoDB containers use ports 27038/27039.
- Implementation and verification pending; no proposed behavior is recorded as completed.

## Group 3 implementation and initial runtime evidence

- Added leaderboard rank/filter/sort pipeline, seeded $densify daily trend with indexed daily eligibility lookup and seven-row decimal moving window, and raw executionStats explain HTTP for all five names. Nine existing indexes suffice in initial executed plans; no extra indexes yet. Shared page_find_operation keeps live and explained listing operations equivalent, including enormous page offsets. Trend path converter supports departments containing encoded slashes; exact matching remains unchanged.
- First Group 3 suite on real MongoDB 7: 94 passed, five failed in 3.77s. Two failures were actual new API defects: from=2026-02-30 and from=2026-7-06 returned 500 because calendar validators were lost when Query aliases were placed in defaults. Moved Query aliases into Annotated metadata, preserving AfterValidator validation for live and explain from/to.
- Three failures were harness mistakes: wrong supplied employee name (actual Neha Iyer) and profiler entries retained from preceding cases with no item query. Corrected name and reset profiler collection before captures.
- A diagnostic edit accidentally indented the route definition and prevented one temporary server from importing; immediately corrected and compiled. Its failed-start audit database was removed. The running manual API was unaffected. Diagnostic HTTP connections are isolated after intentional 500s, as in the main harness.
- Second Group 3 run: 99 passed in 3.70s. Included all endpoint rules, extreme calendar bounds, competition ties, raw explain equivalence, and seven explain HTTP calls over 100000 logs, including all cross-collection lookups with zero collection scans.
- Added explicit alias-validation regressions, mixed daily joining/headcount, overnight month boundary, read-after-correction, extra admin range/page validation and raw-plan semantics without matching resources. MongoDB 6 verification and full matrix pending.

- Expanded real MongoDB 6 run: 122 passed in 3.76s, including live/admin malformed date regressions and shared pipeline/profiler equality. Added two extreme-calendar cases with actual stored logs for final coverage of 124 Group 3 checks.
- Started tests/run_runtime_matrix.py: final combined suite has 512 checks per configuration. DECISIONS now covers all five implemented answers; final results, demonstration and cleanup remain pending.

- First combined 512-check configuration: 511 passed, one harness failure in Group 2's profiler scale check (41.06s). Group 3 profiler captures persisted across files; Group 2's first capture summed 11 returned rows instead of its single monthly summary. Reset the profiler collection before each Group 2 operation, preserving the original <=1/2/1 transfer assertions. This was test-isolation contamination, not an application aggregation failure. Restart the full matrix; no failed configuration is counted as final verification.

## Group 3 completion and final documentation checkpoint

- Final command: .venv/bin/python tests/run_runtime_matrix.py. All 512 checks passed in every MongoDB 7.0.43/6.0.28 × workers 1/2 × UTC/IST configuration: 4096 executions, zero failures/errors/skips. Per configuration, 491 real HTTP/MongoDB and 21 isolated helper checks. Group 3 adds 124 checks; all earlier tests remain included.
- Actual admin executionStats HTTP checks cover all five names and filtered summary/leaderboard on 100000 logs. Root and lookup plans use indexes with no COLLSCAN; lookup collectionScans are zero. Profiler confirms live/explain equivalence. Nine existing non-default indexes suffice; no dependency changes.
- Trend calendar extremes with stored logs, strict alias dates, empty/joining ranges, half-up windows and leaderboard cutoff ties pass on both versions. Read-after-correction reflects stored values without rewriting documents. Shared integer-offset pagination handles giant pages in live and explain.
- Evidence directory: /var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-runtime-matrix-napeogq_. RUNTIME_AUDIT records the eight results, 56 scale explain HTTP operations and observed local timing ranges; no larger-scale performance guarantee is claimed.
- Manual command: .venv/bin/python /tmp/candidate-kit-group3-walkthrough.py. Verified old project PID/cwd, restarted only our API; new PID 73940, same URI/database, no reseeding. All 22 HTTP assertions passed and all employee/attendance BSON snapshots were unchanged, including EMP0099's two-entry history. All twelve routes appear in Swagger; all five manual explain operations contain IXSCAN/no COLLSCAN.
- Manual evidence: /var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-group3-walkthrough.json. API http://127.0.0.1:8001/docs and candidate-kit-dev-mongo deliberately remain running.
- Cleanup verified no audit databases and failCommand off on both test servers. Stopped and confirmed removal of only candidate-kit-group3-mongo7/mongo6. Final manual health/docs/leaderboard/trend/explain return 200.
- Reconciled README, REVIEW, DECISIONS (200 words), RUNTIME_AUDIT and this log; AGENTS already identifies all twelve implemented endpoints and the documentation checkpoint. Supplied contracts, fixtures and requirements remain unchanged. Part 1 and Part 2 are complete and ready for user review/walkthrough. No publication or submission was performed. Documentation checkpoint checked.
- Final documentation read-through confirmed DECISIONS is exactly 200 words and all required files exist. Updated historical scope labels and the audit's current-result pointer so earlier pending notes are not mistaken for today's state. Documentation checkpoint checked after cleanup.

## Final implementation walkthrough

- User said “sure do it,” requesting the implementation walkthrough proposed after Group 3. No publishing or submission authorization was inferred.
- Reread main.py, DECISIONS and current state. Ran 13 fresh real HTTP checks against the retained app: health, EMP0099 attendance, October monthly/department/leaderboard, seven-day Testing trend, impossible date 422, unknown employee 404 and all five executionStats operations. All passed; every plan contained IXSCAN and no COLLSCAN. Exact BSON snapshots confirm no employee or attendance document changed.
- Verified actual walkthrough numbers: October working days 22, present 1, percentage 4.55; hours 8.5, late 30, no overtime, two audit entries. Testing headcount 1; trend rates 1/0/0/0/0/null/null and moving averages 1/.5/.3333/.25/.2/.2/.2.
- Request/response evidence: /var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-final-review-walkthrough.json. API and manual MongoDB remain running. No application changes or repeated full regression run were needed.
- Walkthrough explains starter repairs, identity/storage/time validation, punch flows, database concurrency, employee-root analytics, ranks/densify/windows, shared explain builders and evidence. Documentation checkpoint checked; next action is user questions or requested submission preparation.

## Public repository publication authorized

- User explicitly requested public Git repository publication and explicitly deferred submission. Publishing is authorized; submitting a link to the evaluator is not.
- GitHub CLI's active account is iworkforpurpose. Existing project folder inherited a home-directory Git repository, so initialized a separate main-branch repository inside candidate_kit; no home-directory files or history are included.
- Offered hrone-attendance-api (recommended) or candidate-kit as an optional repository-name preference. Use the stated recommended default if no preference arrives after a reasonable response interval.
- Prepared an explicit 24-file publish manifest covering required deliverables, supplied contracts/fixtures, verification tests and project documentation. No .env, virtual environment, caches, Dockerfiles or generated dumps are included. Added local-cache/log ignore entries; checked manifest text and DOCX XML for common credential/private-key/authenticated-MongoDB-URI patterns, with no findings.
- Publication, clean-checkout smoke verification and remote visibility/content verification remain pending. Application code and prior full runtime results are unchanged. Documentation checkpoint checked.
- Clean staged checkout verification completed: fresh requirements-only installation and pip check passed, followed by 19 real HTTP smoke checks in 2.575s startup. Fresh install selected Pydantic 2.14.1; this smoke check does not replace the earlier full matrix with 2.14.0. All twelve operations and five explain plans passed. Only the newly created UUID smoke database was dropped; temporary API stopped, manual data preserved.
- Git diff --cached --check initially found one extra blank line at EOF in tests/conftest.py. Removed it and repeated the check successfully; test behavior is unchanged.
- No naming preference arrived during preparation; using the offered default iworkforpurpose/hrone-attendance-api. That repository name returned 404 before creation. Publishing the reviewed 24-file manifest is the next action; evaluator submission remains deferred.

## Public repository published

- Created https://github.com/iworkforpurpose/hrone-attendance-api under the active iworkforpurpose account with public visibility, then pushed main. Root implementation commit: 0d553777e02fc6fcc6dc5b6ffddd60f25fbddd7d. Local main tracks origin/main; unrelated home-directory Git history was not included.
- GitHub API confirms private=false, visibility=public and default_branch=main. An anonymous HTTPS clone with prompting/credential helpers disabled succeeded; its HEAD matched the local commit and all 24 tracked files matched byte-for-byte. No .env, virtual environment, caches, Dockerfile or generated dump is tracked.
- Added the public repository link and clone commands to README. Recorded clean-checkout smoke verification and publication evidence in RUNTIME_AUDIT. Required deliverables and documentation are present. Documentation checkpoint checked; publish this final documentation update and verify the remote HEAD.
- The evaluator link has not been submitted and no submission message was sent. User explicitly deferred submission; do not infer submission authorization from publishing.

## Browser verification authorized

- User asked whether Playwright testing had been performed. Answered accurately that earlier evidence was httpx/Uvicorn/real MongoDB and helper tests, not browser automation. User then said “you should consider doing that,” authorizing the additional browser walkthrough.
- Use real Chromium to open Swagger, expand each operation, click Try it out, fill parameters/request JSON and click Execute. Verify both actual network responses and rendered response JSON. No page.request API calls, fetch evaluation, response mocks or API routing substitutions are browser endpoint evidence.
- Create UUID disposable databases on loopback MongoDB and separate temporary API processes. Browser writes must never target the retained manual database. Keep screenshots, Playwright traces and raw request/response JSON outside Git. Exercise all twelve endpoints, five explain names, validation/conflicts, analytics edge examples and desktop/mobile viewports.
- Add optional requirements-browser.txt and a standalone browser runner so the existing 512-check HTTP matrix remains unchanged. Application code is unchanged. Browser execution and final documentation reconciliation are pending.
- Initial setup probe ran before the matching Chromium installation completed and could not launch; waited for installation. First runner then failed its exact title locator because Swagger includes “2.0.0 OAS 3.1” in the heading's accessible name. Changed the locator to the actual level-1 heading with a title prefix. These are setup/harness failures, not API defects; disposable database cleanup was confirmed in the runner report.
- Second runner reached Swagger but counted Try it out before React finished expanding the operation, then waited for an Execute button that was not enabled. Added visibility assertions before counting controls and after enabling execution, plus removal verification when clearing old responses. This is a browser-harness timing fix; no API request or application defect was involved.
- Third runner correctly observed health 200, employee 201 and duplicate employee 409. Swagger displays the error code as “409 Undocumented,” so an exact cell-text assertion failed despite the correct HTTP response. Assert the status prefix while retaining exact network-status and rendered-JSON checks. The badge comes from generated Swagger response-schema coverage; supplied openapi.yaml remains the authoritative contract. No application change was required.

## Playwright browser walkthrough completed

- Final command: .venv/bin/python tests/run_browser_walkthrough.py. Playwright 1.63.0, Chromium 153.0.8010.12, MongoDB 7.0.43, desktop 1440×1000 and mobile viewport 390×844. Both complete flows passed: 46 scenarios each, 92 browser-driven HTTP executions, zero final failures and no unhandled page JavaScript errors.
- Every request was initiated through Swagger Try it out / form filling / Execute. All twelve endpoint operations had successful responses in both profiles; all five explain names had real indexed executionStats. Rendered response JSON matched actual network JSON for every case. No API request context, injected fetch, network interception/mocking or application changes were used.
- Covered employee creation/duplicates/validation/pagination/exact filters; punches/truncation/unknowns/duplicates/interval checks; legacy and nested history serialization; corrections/no-op/absence constraints/recomputation/history retention; monthly/no-log department summary; leaderboard cutoff ties; dense/empty/weekend trends and moving averages; overnight assignment/overtime; explain missing/malformed parameters.
- Evidence directory: /var/folders/kv/8x_b9m997wx09dpfwv80n6ww0000gn/T/candidate-kit-playwright-ay_b4swe. Contains summary.json with every request/status/response, 94 PNG screenshots and two trace.zip files. Visually inspected desktop trend and mobile correction screenshots. Chromium mobile viewport is emulation, not a physical phone; Firefox/WebKit and browser concurrency/100k scenarios were not run. Earlier HTTP matrix retains those API race/scale guarantees.
- All browser UUID databases removed and temporary API processes stopped. Confirmed no candidate_kit_browser_ databases remain. Retained manual API is healthy; database still has 7 employees/10 attendance logs and EMP0099's unchanged WFH/8.5h/30-minute/two-history record. No manual database was used for browser writes.
- Application code, runtime requirements, supplied contracts and fixtures remain unchanged. New optional requirements-browser.txt and standalone tests/run_browser_walkthrough.py keep browser artifacts outside Git and the HTTP suite unchanged. README, AGENTS and RUNTIME_AUDIT updated. Documentation checkpoint checked; push the verified runner/documentation under existing publication authorization, without submitting anything to the evaluator.
- Static collection check: .venv/bin/python -m pytest tests --collect-only -q still collects exactly 512 tests. This confirms runner discovery isolation, not a fresh runtime matrix pass. Git verifies application/runtime-contract/fixture files unchanged; changed/new publish files pass credential-pattern and whitespace checks, and DECISIONS remains 200 words. Documentation checkpoint checked before commit/push.

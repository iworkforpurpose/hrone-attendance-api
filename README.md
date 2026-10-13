# Employee Attendance API

[Public repository](https://github.com/iworkforpurpose/hrone-attendance-api)

Python 3.11+, FastAPI and synchronous PyMongo; MongoDB 6.0+ (grader: 7.0).
The HTTP and storage contracts are `openapi.yaml` and `DATA_MODEL.md`.
All application code is in `app/main.py`.

## Setup and run

```sh
git clone https://github.com/iworkforpurpose/hrone-attendance-api.git
cd hrone-attendance-api
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export MONGO_URI=mongodb://localhost:27017
export MONGO_DB=attendance_dev
uvicorn app.main:app --port 8000
```

A local `.env` is optional; existing environment variables take precedence.
Startup creates indexes and preserves existing documents. `/health` returns 200
only after indexes are ready and MongoDB answers a current ping, otherwise 503.
The service retries after database outages. Existing duplicate natural keys must
be resolved before unique indexes can build; startup preserves those records.

Optional sample loading: run `python sample_seed.py` against an explicitly
**disposable database**. It deletes both collections before inserting fixtures.

## Current scope

Part 1 repairs the five starter endpoints and shared time/rounding helpers.
Part 2 Group 1 adds punch-out and audited corrections. Concurrent stale writes
return 409; reread the record before explicitly resubmitting a correction.
All twelve contract endpoints are implemented. Analytics run in MongoDB from
stored derived values. Leaderboard limits apply to competition ranks, including
every cutoff tie. Trends fill every requested calendar day and calculate the
seven-row moving average inside the requested range.
`REVIEW.md` records the 40 baseline findings and implemented repairs;
`RUNTIME_AUDIT.md` retains baseline evidence and repair verification.
`DECISIONS.md` records all five implementation choices.
Continuity and documentation checkpoints are in `WORK_LOG.md` and `AGENTS.md`.

## Real runtime verification

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
docker run --rm -d --name candidate-kit-group3-mongo7 -p 127.0.0.1:27038:27017 mongo:7 --setParameter enableTestCommands=1
docker run --rm -d --name candidate-kit-group3-mongo6 -p 127.0.0.1:27039:27017 mongo:6 --setParameter enableTestCommands=1
.venv/bin/python tests/run_runtime_matrix.py
docker stop candidate-kit-group3-mongo7 candidate-kit-group3-mongo6
```

Verified: 512 checks pass in each of eight configurations,
4096 executions with zero failures/errors/skips. The suite has 491 HTTP/MongoDB
checks and 21 direct helper checks per configuration. Final evidence is in
`RUNTIME_AUDIT.md`. The matrix uses versions 6/7, workers 1/2 and UTC/IST hosts.
All five explain operations show IXSCAN and no COLLSCAN on 100000 logs,
including cross-collection lookups; live/explain commands are equivalent.
Tests create and remove their own databases and HTTP processes. Recovery
checks also create and remove a separate Docker container. Run serially.
A single configuration can be tested with:

```sh
TEST_MONGO_URI=mongodb://127.0.0.1:27038 .venv/bin/python -m pytest tests -q --tb=short
```

Test settings are `TEST_MONGO_URI` (loopback only; default port 27028),
`TEST_WORKERS` (default 1), and `TEST_SERVER_TZ` (default UTC). Tests do not target
the configured application database. Group 1's forced race tests require the
test-only ports 27038/27039 and `enableTestCommands=1`; run serially and keep
these servers separate from manual testing. The earlier Part 1 runner still
uses ports 27028/27029 and runs only `test_starter_contract.py`.

For actual Swagger browser interaction, with loopback MongoDB available:

```sh
.venv/bin/python -m pip install -r requirements-browser.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/run_browser_walkthrough.py
```

The standalone runner clicks Try it out/Execute for each endpoint, verifies
rendered JSON against real network responses, and uses disposable UUID databases.
Desktop/mobile Chromium runs save screenshots, traces and summary.json to a
temporary evidence directory. Add `--headed` to watch or `--viewport desktop`
for one layout; `--mongo-uri` selects an unauthenticated loopback test server.
It does not target the manual application database or change the HTTP matrix.
Verified 46 scenarios per viewport, 92 browser-driven executions total, with
zero final failures or unhandled JavaScript errors. All twelve endpoints and
five explain names passed; browser evidence is recorded in RUNTIME_AUDIT.md.

## Explain and reporting

`GET /admin/explain/{endpoint}` supports attendance_list, employee_monthly,
department_summary, late_leaderboard and department_trend. Pass the named
operation's parameters (trend uses `department`, `from`, `to`; employee monthly
uses `emp_code`, `month`). The response preserves raw `executionStats` output;
BSON-only values use relaxed Extended JSON. Explain validates parameters and
reports the main operation even when no matching resource exists.
Attendance explain uses the actual find filters, projection, sorting, pagination
and hint; the list's separate filtered count is not the explained operation.
Percentage fields use two decimals half-up; fractional trend rates and moving
averages use four. The trend's inclusive range is limited to 92 calendar days.

Required submission files: `app/main.py`, `requirements.txt`, `REVIEW.md`,
`DECISIONS.md`, and `README.md`. Do not include `.env`, secrets, environments,
Dockerfiles, or generated dumps. Publishing requires the user's authorization.

# Employee Attendance API

[Public repository](https://github.com/iworkforpurpose/hrone-attendance-api).
Python 3.11+, FastAPI, PyMongo and MongoDB 6.0+; all application code is in
[app/main.py](app/main.py). Contracts: [openapi.yaml](openapi.yaml) and
[DATA_MODEL.md](DATA_MODEL.md).

From a clone of the repository, with MongoDB running:

```sh
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export MONGO_URI=mongodb://localhost:27017
export MONGO_DB=attendance_dev
uvicorn app.main:app --port 8000
```

Swagger: http://127.0.0.1:8000/docs. An optional `.env` never overrides existing
environment variables. Startup creates indexes idempotently and preserves data.
`/health` pings MongoDB and returns 200 when ready, otherwise 503. Existing
duplicate natural keys prevent readiness until resolved; startup preserves them.
`sample_seed.py` deletes both collections: use only a disposable database.

All twelve endpoints are implemented. Analytics use stored metrics and MongoDB
pipelines; stale attendance writes return 409. Leaderboard limits include every
competition-rank cutoff tie; trends fill calendar gaps and use a seven-day window.
Percentage fields round half-up to two decimals; fractional rates use four.
The five admin explain operations share live builders and return executionStats;
BSON-only values use relaxed Extended JSON. Attendance explain covers its main
find operation, including pagination, rather than its separate filtered count.

Verification: 512 checks × eight MongoDB 6/7, workers 1/2, UTC/IST configurations
= 4096 executions, zero failures/errors/skips. Plans use IXSCAN without COLLSCAN
on 100000 logs, including lookups. An additional 92 Playwright Swagger checks
passed in desktop/mobile Chromium. Tests use separate UUID databases.

Work proceeded in two parts: review and repair the starter, then implement the
missing endpoints. Explanations and decisions were documented during both parts.
Documentation files are in the repository root:

- [REVIEW.md](REVIEW.md): original defects, failing examples and implemented fixes.
- [DECISIONS.md](DECISIONS.md): indexes, write races, ranking ties, headcount and scaling choices.
- [RUNTIME_AUDIT.md](RUNTIME_AUDIT.md): executed tests, results, browser evidence and [reproduction commands](RUNTIME_AUDIT.md#reproducing-verification).
- [WORK_LOG.md](WORK_LOG.md): development sequence, detailed reasoning and verification checkpoints.
- [AGENTS.md](AGENTS.md): repository rules and the ongoing documentation workflow.

Optional browser dependencies are in `requirements-browser.txt`; runtime
dependencies remain separate in `requirements.txt`.
The evaluator's hidden tests have not been run.

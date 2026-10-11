"""Shared real HTTP/MongoDB fixtures; disposable audit databases only."""
import importlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from bson import json_util
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

ROOT = Path(__file__).resolve().parents[1]
URI = os.getenv("TEST_MONGO_URI", "mongodb://127.0.0.1:27028")
assert URI.startswith("mongodb://127.0.0.1:"), "Tests require an explicit loopback database"
WORKERS = int(os.getenv("TEST_WORKERS", "1"))
SERVER_TZ = os.getenv("TEST_SERVER_TZ", "UTC")
IST = timezone(timedelta(hours=5, minutes=30))


def millis(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def employee(code="EMP0099", **changes):
    return {
        "emp_code": code, "name": "Audit Employee", "email": "audit@example.com",
        "department": "Engineering", "shift_start": "09:30", "shift_end": "18:30",
        "joined_on": "2026-01-01", **changes,
    }


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def launch_server(uri, database, server_tz=None, expect_ready=True, cwd=ROOT):
    server_tz = SERVER_TZ if server_tz is None else server_tz
    port = available_port()
    env = {**os.environ, "MONGO_URI": uri, "MONGO_DB": database, "TZ": server_tz}
    log = tempfile.TemporaryFile(mode="w+")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "error", "--workers", str(WORKERS)],
        cwd=cwd, env=env, stdout=log, stderr=log,
    )
    http = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log.seek(0)
            raise RuntimeError(log.read())
        try:
            response = http.get("/health")
            if not expect_ready or response.status_code == 200:
                return process, log, http
            time.sleep(0.05)
        except httpx.TransportError:
            time.sleep(0.05)
    process.terminate()
    process.wait(timeout=5)
    http.close()
    log.seek(0)
    raise RuntimeError(f"Server did not start within 20s: {log.read()}")


def stop_server(process, log, http):
    http.close()
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    log.close()


@pytest.fixture(scope="session")
def live_app():
    client = MongoClient(URI, tz_aware=True, serverSelectionTimeoutMS=2000)
    client.admin.command("ping")
    database = "candidate_kit_runtime_audit_" + uuid4().hex
    db = client[database]
    # Seed both collections before startup, matching the grader's environment.
    for name in ("employees", "attendance_logs"):
        db[name].insert_many(json_util.loads((ROOT / "sample_data" / f"{name}.json").read_text()))
    process, log, http = launch_server(URI, database)
    print(f"\nRuntime: Python {sys.version.split()[0]}, MongoDB {client.server_info()['version']}; DB {database}")
    try:
        yield {"db": db, "http": http, "database": database}
    finally:
        stop_server(process, log, http)
        assert database.startswith("candidate_kit_runtime_audit_")
        client.drop_database(database)
        client.close()


@pytest.fixture
def db(live_app):
    database = live_app["db"]
    assert database.name.startswith("candidate_kit_runtime_audit_")
    for name in ("employees", "attendance_logs"):
        database[name].delete_many({})
        database[name].insert_many(json_util.loads((ROOT / "sample_data" / f"{name}.json").read_text()))
    return database


@pytest.fixture
def http(live_app, db):
    # Isolate connections between cases, including cases that provoke a 500.
    with httpx.Client(base_url=live_app["http"].base_url, timeout=10, trust_env=False) as client:
        yield client


@pytest.fixture(scope="session")
def helpers(live_app):
    previous = {key: os.environ.get(key) for key in ("MONGO_URI", "MONGO_DB")}
    os.environ.update(MONGO_URI=URI, MONGO_DB=live_app["database"])
    module = importlib.import_module("app.main")
    try:
        yield module
    finally:
        module.client.close()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

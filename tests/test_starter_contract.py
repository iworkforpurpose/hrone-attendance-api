"""Part 1 contract audit: real Uvicorn HTTP traffic and a real disposable MongoDB.

Run serially with: .venv/bin/python -m pytest tests/test_starter_contract.py -ra
Requires MongoDB 6+ on localhost:27028 by default; never targets the user's MONGO_URI/MONGO_DB.
Tests preserve baseline expectations and extend them with repair regressions.
Docker is required for the independently owned outage/recovery container.
The helper tests execute the actual imported functions, labeled separately from HTTP tests.
"""
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

from conftest import (ROOT, URI, WORKERS, SERVER_TZ, IST, millis, employee, available_port, launch_server, stop_server)


def test_health_with_available_database(http):
    response = http.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_with_unreachable_database():
    # Keep the selected unused port reserved so no MongoDB can be listening there.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        unavailable = f"mongodb://127.0.0.1:{reserved.getsockname()[1]}"
        probe = MongoClient(unavailable, serverSelectionTimeoutMS=300)
        try:
            with pytest.raises(ServerSelectionTimeoutError):
                probe.admin.command("ping")
        finally:
            probe.close()
        process, log, http = launch_server(unavailable, "candidate_kit_runtime_audit_outage", expect_ready=False)
        try:
            response = http.get("/health")
            assert response.status_code == 503, response.text
        finally:
            stop_server(process, log, http)


def test_required_unique_indexes_created_at_startup(db):
    for collection, fields in (("employees", [("emp_code", 1)]),
                               ("attendance_logs", [("emp_code", 1), ("date", 1)])):
        indexes = list(db[collection].list_indexes())
        assert any(list(index["key"].items()) == fields and index.get("unique")
                   for index in indexes), indexes


@pytest.mark.parametrize("changes", [
    {"emp_code": "BAD"}, {"emp_code": "EMP123"}, {"emp_code": "EMP1234567"},
    {"name": ""}, {"name": "a" * 101}, {"email": "invalid"},
    {"email": "a" * 110 + "@example.com"}, {"department": ""},
    {"department": "a" * 51}, {"shift_start": "25:00"}, {"shift_end": "18:99"},
    {"shift_start": "9:30"}, {"shift_end": "09:30"},
    {"joined_on": "2026-02-30"}, {"joined_on": "2026-7-1"},
], ids=["bad-code", "short-code", "long-code", "empty-name", "long-name", "bad-email",
        "long-email", "empty-department", "long-department", "bad-start", "bad-end",
        "short-time", "equal-shifts", "impossible-date", "noncanonical-date"])
def test_employee_input_validation(http, changes):
    response = http.post("/employees", json=employee(**changes))
    assert response.status_code == 422, f"input={changes}; status={response.status_code}; body={response.text}"


def test_employee_created_at_is_integer_epoch_milliseconds(http):
    response = http.post("/employees", json=employee())
    assert response.status_code == 201, response.text
    value = response.json()["created_at"]
    assert type(value) is int, f"created_at={value!r}"


def test_employee_creation_stores_correct_utc_instant(http, db):
    before = datetime.now(timezone.utc)
    response = http.post("/employees", json=employee())
    after = datetime.now(timezone.utc)
    assert response.status_code == 201
    stored = db.employees.find_one({"emp_code": "EMP0099"})["created_at"]
    assert before - timedelta(seconds=1) <= stored <= after


def test_sequential_duplicate_employee_is_conflict(http):
    response = http.post("/employees", json=employee("EMP0001"))
    assert response.status_code == 409, response.text


def test_employee_first_page(http):
    response = http.get("/employees", params={"page": 1, "page_size": 2})
    actual = [item["emp_code"] for item in response.json()["items"]]
    assert actual == ["EMP0001", "EMP0002"], actual


def test_employee_total_respects_department(http):
    body = http.get("/employees", params={"department": "Sales"}).json()
    assert body["total"] == 2, body


def test_employee_listing_is_sorted(http, db):
    original = list(db.employees.find())
    db.employees.delete_many({})
    db.employees.insert_many(original[::-1])
    body = http.get("/employees", params={"page_size": 2}).json()
    codes = [item["emp_code"] for item in body["items"]]
    assert codes == sorted(codes), codes


@pytest.mark.parametrize("endpoint", ["/employees", "/attendance"])
@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101},
                                   {"page": -1}, {"page_size": -1}])
def test_pagination_validation(http, endpoint, params):
    response = http.get(endpoint, params=params)
    assert response.status_code == 422, f"status={response.status_code}; body={response.text}"


@pytest.mark.parametrize("timestamp", [None, 0, 1783312500, 1800000000000.0,
    "1800000000000", True, -1, 99999999999, 4102444800001, 10**30],
    ids=["null", "zero", "seconds", "float", "string", "boolean", "negative",
         "below-minimum", "above-maximum", "huge"])
def test_punch_timestamp_validation(http, timestamp):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0001", "punched_at": timestamp})
    assert response.status_code == 422, f"timestamp={timestamp!r}; status={response.status_code}; body={response.text}"


@pytest.mark.parametrize("status", ["ABSENT", "LEAVE", "UNKNOWN", "present"])
def test_punch_in_presence_status_validation(http, status):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0001", "status": status,
        "punched_at": millis("2026-07-15T04:00:00+00:00")})
    assert response.status_code == 422, f"status={response.status_code}; body={response.text}"


def test_unknown_employee_punch_in(http):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP9999",
        "punched_at": millis("2026-07-15T04:00:00+00:00")})
    assert response.status_code == 404, f"status={response.status_code}; body={response.text}"


def test_punch_in_attendance_date_uses_ist(http):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0001",
        "punched_at": millis("2026-07-15T20:00:00+00:00")})
    assert response.status_code == 201, response.text
    assert response.json()["date"] == "2026-07-16", response.json()


def test_overnight_punch_in_attendance_date(http):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0005",
        "punched_at": millis("2026-07-15T05:40:00+05:30")})
    assert response.status_code == 201, response.text
    assert response.json()["date"] == "2026-07-14", response.json()


def test_normal_punch_in_lateness_uses_ist(http):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0001",
        "punched_at": millis("2026-07-15T10:05:00+05:30")})
    assert response.status_code == 201, response.text
    assert response.json()["late_minutes"] == 35, response.json()


def test_punch_in_is_truncated_in_database(http, db):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0001",
        "punched_at": millis("2026-07-15T09:40:00.900+05:30")})
    assert response.status_code == 201, response.text
    stored = db.attendance_logs.find_one({"emp_code": "EMP0001", "date": "2026-07-15"})
    assert stored["punch_in"].microsecond == 0, stored["punch_in"]


def test_punch_in_timestamp_is_integer_and_has_no_id(http):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0001",
        "punched_at": millis("2026-07-15T04:00:00+00:00")})
    assert response.status_code == 201
    body = response.json()
    assert type(body["punch_in"]) is int, body
    assert "id" not in body and "_id" not in body, body


def test_attendance_does_not_expose_id(http):
    body = http.get("/attendance", params={"page_size": 1}).json()
    assert all("id" not in item and "_id" not in item for item in body["items"]), body


def test_attendance_date_tie_order(http, db):
    logs = list(db.attendance_logs.find())
    db.attendance_logs.delete_many({})
    db.attendance_logs.insert_many(sorted(logs, key=lambda log: log["emp_code"], reverse=True))
    body = http.get("/attendance", params={"date_from": "2026-07-06", "date_to": "2026-07-06"}).json()
    codes = [item["emp_code"] for item in body["items"]]
    assert codes == ["EMP0001", "EMP0003", "EMP0005"], codes


def test_attendance_legacy_defaults(http):
    body = http.get("/attendance", params={"emp_code": "EMP0002"}).json()
    record = body["items"][0]
    assert record.get("history") == [] and record.get("half_day") is False, record


def test_nested_history_timestamps_are_integer_milliseconds(http):
    body = http.get("/attendance", params={"emp_code": "EMP0001", "date_from": "2026-07-07",
                                         "date_to": "2026-07-07"}).json()
    history = body["items"][0]["history"][0]
    assert type(history["at"]) is int, history
    for value in history["changes"]["punch_in"].values():
        assert type(value) is int, history


@pytest.mark.parametrize("params", [{"date_from": "2026-02-30"}, {"date_to": "bad"},
    {"date_from": "2026-07-09", "date_to": "2026-07-01"}, {"status": "UNKNOWN"},
    {"date_from": ""}, {"date_from": "2026-7-1"}, {"status": ""}])
def test_attendance_filter_validation(http, params):
    response = http.get("/attendance", params=params)
    assert response.status_code == 422, f"params={params}; status={response.status_code}; body={response.text}"


def test_attendance_filtered_total_and_pagination(http):
    body = http.get("/attendance", params={"emp_code": "EMP0001", "page_size": 1}).json()
    assert body["total"] == 2 and len(body["items"]) == 1, body
    assert body["items"][0]["date"] == "2026-07-07", body


def test_punch_in_ignores_client_derived_values(http, db):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0001",
        "punched_at": millis("2026-07-15T04:00:00+00:00"), "work_hours": 99,
        "late_minutes": 999, "overtime_minutes": 999, "half_day": True})
    assert response.status_code == 201, response.text
    stored = db.attendance_logs.find_one({"emp_code": "EMP0001", "date": "2026-07-15"})
    assert stored["work_hours"] is None and stored["late_minutes"] == 0
    assert stored["overtime_minutes"] == 0 and stored["half_day"] is False
    assert stored["history"] == []


def concurrent_posts(http, endpoint, payload, count=24):
    barrier = threading.Barrier(count)
    def send(_):
        barrier.wait(timeout=10)
        return http.post(endpoint, json=payload).status_code
    with ThreadPoolExecutor(max_workers=count) as executor:
        return Counter(executor.map(send, range(count)))


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_employee_creation(http, db, attempt):
    outcomes = concurrent_posts(http, "/employees", employee("EMP0088"))
    stored_count = db.employees.count_documents({"emp_code": "EMP0088"})
    assert outcomes == {201: 1, 409: 23} and stored_count == 1, f"HTTP={dict(outcomes)}; stored={stored_count}"


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_punch_in(http, db, attempt):
    payload = {"emp_code": "EMP0001", "punched_at": millis("2026-07-15T04:00:00+00:00")}
    outcomes = concurrent_posts(http, "/attendance/punch-in", payload)
    stored_count = db.attendance_logs.count_documents({"emp_code": "EMP0001", "date": "2026-07-15"})
    assert outcomes == {201: 1, 409: 23} and stored_count == 1, f"HTTP={dict(outcomes)}; stored={stored_count}"


@pytest.mark.parametrize("time_of_day, expected", [("09:40:00", 0), ("09:40:01", 10),
                                                 ("10:15:59", 45)])
def test_helper_late_grace_boundary(helpers, time_of_day, expected):
    punch = datetime.fromisoformat(f"2026-07-15T{time_of_day}+05:30")
    actual = helpers.compute_late_minutes(punch, "09:30", "18:30", "2026-07-15")
    assert actual == expected, f"punch={punch}; actual={actual}; expected={expected}"


def test_helper_overnight_lateness(helpers):
    punch = datetime.fromisoformat("2026-07-15T01:00:00+05:30")
    assert helpers.compute_late_minutes(punch, "22:00", "06:00", "2026-07-14") == 180


def test_helper_work_hours_half_up(helpers):
    start = datetime.fromisoformat("2026-07-15T09:30:00+05:30")
    # 0.125 hours = exactly 450 seconds; half-up yields 0.13.
    actual = helpers.compute_work_hours(start, start + timedelta(seconds=450))
    assert actual == 0.13, f"actual={actual}; expected=0.13"


@pytest.mark.parametrize("out, expected", [("2026-07-15T18:50:00+05:30", 0),
                                           ("2026-07-15T19:00:00+05:30", 30)])
def test_helper_overtime_threshold(helpers, out, expected):
    actual = helpers.compute_overtime(datetime.fromisoformat(out), "09:30", "18:30", "2026-07-15")
    assert actual == expected, f"actual={actual}; expected={expected}"


def test_helper_overnight_overtime(helpers):
    actual = helpers.compute_overtime(datetime.fromisoformat("2026-07-16T06:40:00+05:30"),
                                      "22:00", "06:00", "2026-07-15")
    assert actual == 40, f"actual={actual}; expected=40"


def test_helper_overtime_accepts_pymongo_default_naive_utc(helpers):
    # PyMongo's documented default representation for 18:50 IST.
    actual = helpers.compute_overtime(datetime(2026, 7, 15, 13, 20), "09:30", "18:30", "2026-07-15")
    assert actual == 0


@pytest.fixture
def ist_server(live_app, db):
    server = launch_server(URI, live_app["database"], server_tz="Asia/Kolkata")
    try:
        yield server[2]
    finally:
        stop_server(*server)


def test_employee_stored_instant_on_ist_host(ist_server, db):
    before = datetime.now(timezone.utc)
    response = ist_server.post("/employees", json=employee())
    after = datetime.now(timezone.utc)
    assert response.status_code == 201
    stored = db.employees.find_one({"emp_code": "EMP0099"})["created_at"]
    assert before - timedelta(seconds=1) <= stored <= after, f"UTC interval={before}..{after}; stored={stored}"


def test_punch_stored_instant_on_ist_host(ist_server, db):
    expected = datetime.fromisoformat("2026-07-15T04:00:00+00:00")
    response = ist_server.post("/attendance/punch-in", json={"emp_code": "EMP0001",
        "punched_at": int(expected.timestamp() * 1000)})
    assert response.status_code == 201
    stored = db.attendance_logs.find_one({"emp_code": "EMP0001", "date": "2026-07-15"})["punch_in"]
    assert stored == expected, f"stored={stored}; expected={expected}"


def test_late_grace_boundary_through_http_on_ist_host(ist_server):
    response = ist_server.post("/attendance/punch-in", json={"emp_code": "EMP0001",
        "punched_at": millis("2026-07-15T09:40:01+05:30")})
    assert response.status_code == 201
    assert response.json()["late_minutes"] == 10, response.json()


def test_attendance_pagination_fetches_only_requested_page(http, db, helpers):
    db.attendance_logs.delete_many({})
    codes = [f"EMP{100000 + index}" for index in range(1000)]
    db.employees.insert_many([{**employee(code), "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
                              for code in codes])
    start = datetime(2026, 1, 1, 4, tzinfo=timezone.utc)
    for day in range(100):
        punch = start + timedelta(days=day)
        db.attendance_logs.insert_many([
            {"emp_code": code, "date": punch.date().isoformat(), "status": "PRESENT",
             "punch_in": punch, "punch_out": punch + timedelta(hours=8), "work_hours": 8.0,
             "late_minutes": 0, "overtime_minutes": 0, "half_day": False, "history": []}
            for code in codes
        ])
    assert db.attendance_logs.count_documents({}) == 100000
    # Profile only this disposable DB, then inspect actual cursor traffic.
    db.command("profile", 2)
    started = time.monotonic()
    try:
        response = http.get("/attendance", params={"page": 1, "page_size": 20})
        elapsed = time.monotonic() - started
    finally:
        db.command("profile", 0)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 100000 and len(body["items"]) == 20, body
    cursor_reads = list(db["system.profile"].find({"ns": db.name + ".attendance_logs",
                                                  "op": {"$in": ["query", "getmore"]}}))
    transferred = sum(entry.get("nreturned", 0) for entry in cursor_reads)
    plans = sorted({entry.get("planSummary", "unknown") for entry in cursor_reads})
    assert cursor_reads and all("IXSCAN" in entry.get("planSummary", "") for entry in cursor_reads), plans
    assert transferred <= 20, (f"HTTP returned 20 items; MongoDB cursor returned {transferred}; "
                               f"plans={plans}; request seconds={elapsed:.3f}")

    # Explain the same builder output, including live sort, pagination and hint.
    for filters in ({}, {"status": "PRESENT"}, {"emp_code": "EMP100000"},
                    {"emp_code": "EMP100000", "status": "PRESENT"},
                    {"date_from": "2026-02-01", "date_to": "2026-03-01"}):
        query, sort, hint = helpers.attendance_list_query(**filters)
        explanation = db.command("explain", {"find": "attendance_logs", "filter": query,
            "sort": dict(sort), "skip": 20, "limit": 20, "hint": hint}, verbosity="executionStats")
        stages = str(explanation["queryPlanner"]["winningPlan"])
        assert "IXSCAN" in stages and "COLLSCAN" not in stages and "'SORT'" not in stages, explanation
        count_explain = db.command("explain", {"aggregate": "attendance_logs",
            "pipeline": [{"$match": query}, {"$group": {"_id": None, "n": {"$sum": 1}}}],
            "cursor": {}, "hint": hint}, verbosity="executionStats")
        assert "COLLSCAN" not in str(count_explain), count_explain


def test_sequential_duplicate_punch_in_is_conflict(http):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0001",
        "punched_at": millis("2026-07-06T04:00:00+00:00")})
    assert response.status_code == 409, response.text


def test_employee_creation_uses_default_shifts_and_ignores_created_at(http, db):
    payload = employee()
    payload.pop("shift_start")
    payload.pop("shift_end")
    payload["created_at"] = 100000000000
    response = http.post("/employees", json=payload)
    assert response.status_code == 201
    stored = db.employees.find_one({"emp_code": "EMP0099"})
    assert stored["shift_start"] == "09:30" and stored["shift_end"] == "18:30"
    assert stored["created_at"].year == datetime.now(timezone.utc).year
    assert "_id" not in response.json()


def test_attendance_empty_employee_filter_is_applied(http):
    body = http.get("/attendance", params={"emp_code": ""}).json()
    assert body["total"] == 0 and body["items"] == [], body


def test_attendance_missing_minute_defaults(http, db):
    db.attendance_logs.update_one({"emp_code": "EMP0002"}, {"$unset": {"late_minutes": "", "overtime_minutes": ""}})
    body = http.get("/attendance", params={"emp_code": "EMP0002"}).json()
    record = body["items"][0]
    assert record.get("late_minutes") == 0 and record.get("overtime_minutes") == 0, record


@pytest.mark.parametrize("timestamp", [100000000000, 4102444800000])
def test_valid_timestamp_bounds_are_accepted(http, timestamp):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0001", "punched_at": timestamp})
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("status", ["PRESENT", "WFH", "ON_DUTY"])
def test_valid_presence_statuses_are_accepted(http, status):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0001", "status": status,
        "punched_at": millis("2026-07-15T04:00:00+00:00")})
    assert response.status_code == 201 and response.json()["status"] == status, response.text


def test_missing_required_employee_fields_are_rejected(http):
    response = http.post("/employees", json={"emp_code": "EMP0099"})
    assert response.status_code == 422, response.text


def test_noninteger_fractional_timestamp_is_rejected(http):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0001", "punched_at": 1800000000000.5})
    assert response.status_code == 422, response.text

# Additional Part 1 regressions agreed during planning.
@pytest.mark.parametrize("iso, day, late", [
    ("2027-01-01T00:01:00+05:30", "2026-12-31", 121),
    ("2026-08-01T05:59:59.999+05:30", "2026-07-31", 479),
    ("2026-08-01T06:00:00+05:30", "2026-08-01", 0),
    ("2028-03-01T01:00:00+05:30", "2028-02-29", 180),
    ("2026-07-15T22:10:00.999+05:30", "2026-07-15", 0),
    ("2026-07-15T22:10:01+05:30", "2026-07-15", 10),
])
def test_overnight_calendar_boundaries(http, db, iso, day, late):
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0005", "punched_at": millis(iso)})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["date"] == day and body["late_minutes"] == late, body
    assert body["punch_in"] == millis(iso) // 1000 * 1000
    assert db.attendance_logs.find_one({"emp_code": "EMP0005", "date": day})["punch_in"].microsecond == 0


@pytest.mark.parametrize("seconds, expected", [(449, .12), (450, .13), (451, .13),
    (16181, 4.49), (16182, 4.50), (16200, 4.50)])
def test_helper_work_hours_threshold_and_ties(helpers, seconds, expected):
    start = datetime(2026, 7, 15, 4, tzinfo=timezone.utc)
    assert helpers.compute_work_hours(start, start + timedelta(seconds=seconds)) == expected


@pytest.mark.parametrize("seconds, expected", [(1799, 0), (1800, 30), (1859, 30), (1860, 31), (-1, 0)])
def test_helper_overtime_seconds_boundaries(helpers, seconds, expected):
    end = datetime.fromisoformat("2026-07-15T18:30:00+05:30")
    assert helpers.compute_overtime(end + timedelta(seconds=seconds, microseconds=999000),
                                    "09:30", "18:30", "2026-07-15") == expected


def test_helper_truncates_both_instants_and_accepts_mixed_utc(helpers):
    start = datetime(2026, 7, 15, 4, microsecond=900000)  # naive UTC
    end = datetime(2026, 7, 15, 4, 7, 30, 100000, tzinfo=timezone.utc)
    assert helpers.compute_work_hours(start, end) == .13


def test_punch_in_omitted_timestamp_uses_utc_now(http, db):
    before = datetime.now(timezone.utc).replace(microsecond=0)
    response = http.post("/attendance/punch-in", json={"emp_code": "EMP0001"})
    after = datetime.now(timezone.utc)
    assert response.status_code == 201, response.text
    stored = db.attendance_logs.find_one({"emp_code": "EMP0001", "date": response.json()["date"]})
    assert before <= stored["punch_in"] <= after
    assert stored["punch_in"].microsecond == 0
    assert response.json()["status"] == "PRESENT"


@pytest.mark.parametrize("endpoint", ["/employees", "/attendance"])
def test_huge_page_is_empty_without_bson_overflow(http, endpoint):
    response = http.get(endpoint, params={"page": str(10**50)})
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [] and response.json()["total"] > 0


@pytest.mark.parametrize("department, total", [("Sales", 2), ("sales", 0), ("", 0)])
def test_employee_department_is_exact_even_when_empty(http, department, total):
    response = http.get("/employees", params={"department": department})
    assert response.status_code == 200 and response.json()["total"] == total


@pytest.mark.parametrize("status", ["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"])
def test_attendance_status_filter_is_applied(http, db, status):
    response = http.get("/attendance", params={"status": status})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == db.attendance_logs.count_documents({"status": status})
    assert all(item["status"] == status for item in body["items"])


def test_serialization_preserves_stored_derived_fields_and_null_history(http, db):
    db.attendance_logs.update_one({"emp_code": "EMP0001", "date": "2026-07-07"},
        {"$set": {"work_hours": 123.45, "late_minutes": 777, "overtime_minutes": 888,
                  "half_day": True, "history.0.changes.punch_out": {"from": None,
                      "to": datetime(2026, 7, 7, 13, tzinfo=timezone.utc)}}})
    response = http.get("/attendance", params={"emp_code": "EMP0001", "date_from": "2026-07-07",
                                               "date_to": "2026-07-07"})
    body = response.json()["items"][0]
    assert (body["work_hours"], body["late_minutes"], body["overtime_minutes"], body["half_day"]) == (123.45, 777, 888, True)
    assert body["history"][0]["changes"]["punch_out"] == {"from": None, "to": millis("2026-07-07T13:00:00+00:00")}


def test_absence_missing_punches_are_null(http, db):
    db.attendance_logs.update_one({"status": "ABSENT"}, {"$unset": {"punch_in": "", "punch_out": "", "work_hours": ""}})
    body = http.get("/attendance", params={"status": "ABSENT"}).json()["items"][0]
    assert body["punch_in"] is None and body["punch_out"] is None and body["work_hours"] is None


def test_startup_restart_preserves_documents_and_indexes(live_app, db):
    before = {name: list(db[name].find().sort("_id", 1)) for name in ("employees", "attendance_logs")}
    indexes = {name: list(db[name].list_indexes()) for name in before}
    extra_server = launch_server(URI, live_app["database"])
    try:
        assert extra_server[2].get("/health").status_code == 200
        assert {name: list(db[name].find().sort("_id", 1)) for name in before} == before
        assert {name: list(db[name].list_indexes()) for name in before} == indexes
        assert len(indexes["employees"]) == 5 and len(indexes["attendance_logs"]) == 6
    finally:
        stop_server(*extra_server)


def test_environment_overrides_conflicting_dotenv(live_app, db, tmp_path):
    import shutil
    (tmp_path / "app").mkdir()
    shutil.copy(ROOT / "app" / "main.py", tmp_path / "app" / "main.py")
    (tmp_path / "app" / "__init__.py").write_text("")
    wrong_database = "candidate_kit_runtime_audit_dotenv_" + uuid4().hex[:16]
    (tmp_path / ".env").write_text(f"MONGO_URI=mongodb://127.0.0.1:1\nMONGO_DB={wrong_database}\n")
    server = launch_server(URI, live_app["database"], cwd=tmp_path)
    try:
        response = server[2].post("/employees", json=employee("EMP0077"))
        assert response.status_code == 201, response.text
        assert db.employees.count_documents({"emp_code": "EMP0077"}) == 1
        assert wrong_database not in db.client.list_database_names()
    finally:
        stop_server(*server)


def test_real_database_outage_then_recovery(tmp_path):
    # Own a separate container so the main audit database and unrelated services
    # cannot be interrupted. Stop/start preserves its actual stored documents.
    port = available_port()
    name = "candidate-kit-recovery-" + uuid4().hex
    with MongoClient(URI, serverSelectionTimeoutMS=1000) as version_probe:
        major = version_probe.server_info()["version"].split(".")[0]
    subprocess.run(["docker", "run", "-d", "--name", name, "-p",
                    f"127.0.0.1:{port}:27017", f"mongo:{major}"], check=True, capture_output=True)
    mongo = MongoClient(f"mongodb://127.0.0.1:{port}", serverSelectionTimeoutMS=1000, tz_aware=True)
    database = "candidate_kit_runtime_audit_recovery_" + uuid4().hex[:16]
    server = None
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                mongo.admin.command("ping")
                break
            except ServerSelectionTimeoutError:
                assert time.monotonic() < deadline
        mongo[database].employees.insert_one({**employee("EMP0077"), "created_at": datetime.now(timezone.utc)})
        server = launch_server(f"mongodb://127.0.0.1:{port}", database)
        http = server[2]
        assert http.get("/health").status_code == 200
        subprocess.run(["docker", "stop", "--time", "1", name], check=True, capture_output=True)
        started = time.monotonic()
        assert http.get("/health").status_code == 503
        assert time.monotonic() - started < 5
        assert http.post("/employees", json=employee()).status_code == 503
        subprocess.run(["docker", "start", name], check=True, capture_output=True)
        deadline = time.monotonic() + 20
        while http.get("/health").status_code != 200:
            assert time.monotonic() < deadline
            time.sleep(.1)
        assert http.get("/employees").json()["total"] == 1
        assert http.post("/employees", json=employee("EMP0077")).status_code == 409
        assert http.post("/employees", json=employee()).status_code == 201
        # Also boot while MongoDB is absent, with only default indexes left.
        stop_server(*server)
        server = None
        mongo[database].employees.drop_indexes()
        mongo[database].attendance_logs.drop_indexes()
        subprocess.run(["docker", "stop", "--time", "1", name], check=True, capture_output=True)
        server = launch_server(f"mongodb://127.0.0.1:{port}", database, expect_ready=False)
        assert server[2].get("/health").status_code == 503
        assert server[2].get("/employees").status_code == 503
        subprocess.run(["docker", "start", name], check=True, capture_output=True)
        deadline = time.monotonic() + 20
        while server[2].get("/health").status_code != 200:
            assert time.monotonic() < deadline
            time.sleep(.1)
        assert server[2].get("/employees").json()["total"] == 2
        assert any(index.get("unique") for index in mongo[database].employees.list_indexes())
    finally:
        if server is not None:
            stop_server(*server)
        mongo.close()
        subprocess.run(["docker", "rm", "-f", "-v", name], check=True, capture_output=True)


def test_startup_duplicate_data_is_preserved_and_not_ready(db):
    mongo = db.client
    database = "candidate_kit_runtime_audit_dupes_" + uuid4().hex[:16]
    isolated = mongo[database]
    documents = [{**employee("EMP0077"), "created_at": datetime.now(timezone.utc)} for _ in range(2)]
    isolated.employees.insert_many(documents)
    server = None
    try:
        server = launch_server(URI, database, expect_ready=False)
        assert server[2].get("/health").status_code == 503
        assert server[2].post("/employees", json=employee()).status_code == 503
        assert isolated.employees.count_documents({}) == 2
        isolated.employees.delete_one({"_id": documents[1]["_id"]})
        deadline = time.monotonic() + 10
        while server[2].get("/health").status_code != 200:
            assert time.monotonic() < deadline
            time.sleep(.1)
        assert isolated.employees.count_documents({}) == 1
    finally:
        if server is not None:
            stop_server(*server)
        mongo.drop_database(database)


@pytest.mark.parametrize("changes", [{"joined_on": "2028-02-29"}, {"name": "a" * 100},
    {"department": "a" * 50}, {"email": "a" * 108 + "@example.com"},
    {"emp_code": "EMP123456", "shift_start": "23:59", "shift_end": "00:00"}])
def test_employee_valid_boundary_inputs(http, changes):
    response = http.post("/employees", json=employee(**changes))
    assert response.status_code == 201, response.text

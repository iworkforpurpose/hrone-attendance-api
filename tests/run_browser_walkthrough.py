"""Exercise actual Swagger controls in Chromium against disposable real MongoDB.

Run: .venv/bin/python tests/run_browser_walkthrough.py
No browser request API, fetch injection, network mocks or application test hooks.
"""
import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import tempfile
import traceback
from urllib.parse import urlparse
from uuid import uuid4

from bson import json_util
from playwright.sync_api import expect, sync_playwright
from pymongo import MongoClient

from conftest import ROOT, employee, launch_server, millis, stop_server


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def fields(actual, expected):
    for key, value in expected.items():
        require(actual.get(key) == value, f"{key}: expected {value!r}; got {actual.get(key)!r}")


def seed(database):
    for name in ("employees", "attendance_logs"):
        database[name].insert_many(json_util.loads((ROOT / "sample_data" / f"{name}.json").read_text()))
    # Independent ranking fixtures; API creation is exercised separately below.
    for code, score in (("EMP0200", 100), ("EMP0201", 80), ("EMP0202", 80)):
        database.employees.insert_one({**employee(code, department="Browser Ties", joined_on="2026-10-01"),
                                       "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc)})
        database.attendance_logs.insert_one({"emp_code": code, "date": "2026-10-12", "status": "PRESENT",
            "punch_in": datetime(2026, 10, 12, 4, tzinfo=timezone.utc), "punch_out": None,
            "work_hours": None, "late_minutes": score, "overtime_minutes": 0, "half_day": False, "history": []})


class Swagger:
    def __init__(self, page, base_url, artifacts, report):
        self.page, self.base_url = page, base_url
        self.artifacts, self.report = artifacts, report
        page.goto(base_url + "/docs")
        expect(page.locator(".opblock")).to_have_count(12)
        expect(page.get_by_role("heading", level=1,
                                name=re.compile(r"^Employee Attendance & Analytics API"))).to_be_visible()
        page.screenshot(path=str(artifacts / "00-swagger.png"))

    def call(self, name, method, path, expected=200, parameters=None, body=None):
        parameters = parameters or {}
        operation = self.page.locator(f".opblock.opblock-{method.lower()}").filter(
            has=self.page.locator(f'.opblock-summary-path[data-path="{path}"]'))
        expect(operation).to_have_count(1)
        if "is-open" not in operation.get_attribute("class"):
            operation.locator(".opblock-summary-control").click()
        expect(operation.get_by_role("button", name=re.compile(r"^(Try it out|Cancel)$"))).to_be_visible()
        trial = operation.get_by_role("button", name="Try it out", exact=True)
        if trial.count():
            trial.click()
        expect(operation.get_by_role("button", name="Execute", exact=True)).to_be_visible()
        clear = operation.get_by_role("button", name="Clear", exact=True)
        if clear.count():
            clear.click()
            expect(operation.locator(".live-responses-table")).to_have_count(0)
        for row in operation.locator("tr[data-param-name]").all():
            key = row.get_attribute("data-param-name")
            control = row.locator("input, select").first
            value = str(parameters[key]) if key in parameters else ""
            if control.evaluate("node => node.tagName") == "SELECT":
                if key in parameters or control.locator('option[value=""]').count():
                    control.select_option(value)
            else:
                control.fill(value)
        if body is not None:
            operation.locator("textarea").fill(json.dumps(body))
        with self.page.expect_response(lambda response: response.url.startswith(self.base_url + "/")
                                       and response.request.method == method, timeout=15000) as pending:
            operation.get_by_role("button", name="Execute", exact=True).click()
        response = pending.value
        actual = response.json()
        rendered = operation.locator(".live-responses-table .response-col_description .highlight-code pre").first
        expect(rendered).not_to_be_empty()
        code = operation.locator(".live-responses-table tbody .response-col_status").first
        # FastAPI's generated docs append an "Undocumented" badge for errors
        # whose response schema is not declared; the actual HTTP code is exact.
        expect(code).to_have_text(re.compile(rf"^{expected}(?:\s|$)"))
        require(response.status == expected, f"{name}: expected HTTP {expected}; got {response.status}: {actual}")
        require(json.loads(rendered.inner_text()) == actual, f"{name}: displayed JSON differs from network response")
        entry = {"name": name, "method": method, "operation": path, "parameters": parameters,
                 "request_body": body, "actual_url": response.url, "network_request_body": response.request.post_data,
                 "expected_status": expected, "observed_status": response.status, "response": actual,
                 "rendered_json_matches": True}
        self.report["checks"].append(entry)
        number = len(self.report["checks"])
        filename = f"{number:02d}-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}.png"
        rendered.scroll_into_view_if_needed()
        self.page.screenshot(path=str(self.artifacts / filename))
        entry["screenshot"] = filename
        print(f"{self.report['viewport']} {number:02d}: {method} {path} -> {response.status} ({name})", flush=True)
        return actual


def walkthrough(ui, database):
    call = ui.call
    code = "EMP0100"
    first = employee(code, name="Browser Employee", department="Browser", joined_on="2026-10-01")
    pin = millis("2026-10-12T10:00:00+05:30")
    pout = millis("2026-10-12T18:30:00+05:30")
    patch_path = "/attendance/{emp_code}/{date}"
    monthly_path = "/analytics/employees/{emp_code}/monthly"
    trend_path = "/analytics/departments/{department}/trend"
    explain_path = "/admin/explain/{endpoint}"

    fields(call("MongoDB readiness", "GET", "/health"), {"status": "ok"})
    created = call("Create employee", "POST", "/employees", 201, body=first)
    fields(created, {"emp_code": code, "shift_start": "09:30", "shift_end": "18:30"})
    require(isinstance(created["created_at"], int) and "_id" not in created, "Employee serialization")
    call("Duplicate employee", "POST", "/employees", 409, body=first)
    call("Invalid employee code", "POST", "/employees", 422, body={**first, "emp_code": "BAD"})
    call("Create employee with no logs", "POST", "/employees", 201,
         body=employee("EMP0101", department="Browser", joined_on="2026-10-01"))
    listed = call("Filtered first employee page", "GET", "/employees",
                  parameters={"department": "Browser", "page": 1, "page_size": 1})
    require(listed["total"] == 2 and [x["emp_code"] for x in listed["items"]] == [code], "First filtered page")
    listed = call("Filtered second employee page", "GET", "/employees",
                  parameters={"department": "Browser", "page": 2, "page_size": 1})
    require(listed["total"] == 2 and listed["items"][0]["emp_code"] == "EMP0101", "Second filtered page")
    fields(call("Exact department case", "GET", "/employees", parameters={"department": "browser"}),
           {"items": [], "total": 0})

    opened = call("Punch in and truncate milliseconds", "POST", "/attendance/punch-in", 201,
                  body={"emp_code": code, "punched_at": pin + 900})
    fields(opened, {"date": "2026-10-12", "punch_in": pin, "work_hours": None, "late_minutes": 30, "history": []})
    call("Duplicate punch in", "POST", "/attendance/punch-in", 409, body={"emp_code": code, "punched_at": pin})
    call("String timestamp rejected", "POST", "/attendance/punch-in", 422,
         body={"emp_code": code, "punched_at": str(pin)})
    call("Null timestamp rejected", "POST", "/attendance/punch-in", 422,
         body={"emp_code": code, "punched_at": None})
    call("Unknown employee punch in", "POST", "/attendance/punch-in", 404,
         body={"emp_code": "EMP9999", "punched_at": pin})
    listed = call("Filtered attendance page", "GET", "/attendance", parameters={"emp_code": code,
                  "date_from": "2026-10-12", "date_to": "2026-10-12", "status": "PRESENT", "page_size": 1})
    require(listed["total"] == 1 and listed["items"] == [opened], "Attendance filters and serialization")
    legacy = call("Legacy attendance defaults", "GET", "/attendance", parameters={"emp_code": "EMP0002"})
    fields(legacy["items"][0], {"history": [], "half_day": False})
    history = call("Seeded nested history serialization", "GET", "/attendance", parameters={"emp_code": "EMP0001"})
    changes = history["items"][0]["history"][0]
    require(isinstance(changes["at"], int) and isinstance(changes["changes"]["punch_in"]["from"], int), "Nested epoch times")
    call("Impossible attendance date", "GET", "/attendance", 422, parameters={"date_from": "2026-02-30"})
    call("Reversed attendance range", "GET", "/attendance", 422,
         parameters={"date_from": "2026-10-13", "date_to": "2026-10-12"})

    call("Punch out equal to punch in", "POST", "/attendance/punch-out", 422,
         body={"emp_code": code, "punched_at": pin})
    call("No qualifying punch in", "POST", "/attendance/punch-out", 404,
         body={"emp_code": "EMP0101", "punched_at": pout})
    closed = call("Punch out", "POST", "/attendance/punch-out", body={"emp_code": code, "punched_at": pout})
    fields(closed, {"work_hours": 8.5, "late_minutes": 30, "overtime_minutes": 0, "half_day": False, "history": []})
    call("Duplicate punch out", "POST", "/attendance/punch-out", 409, body={"emp_code": code, "punched_at": pout})
    parameters = {"emp_code": code, "date": "2026-10-12"}
    correction = {"status": "WFH", "reason": "Browser attendance correction", "regularized_by": "browser.runner"}
    changed = call("Audited WFH correction", "PATCH", patch_path, parameters=parameters, body=correction)
    require(changed["status"] == "WFH" and len(changed["history"]) == 1, "One audit entry")
    require(set(changed["history"][0]["changes"]) == {"status"}, "Only changed fields audited")
    call("No-op correction", "PATCH", patch_path, 422, parameters=parameters, body=correction)
    call("Absence cannot carry punches", "PATCH", patch_path, 422, parameters=parameters,
         body={**correction, "status": "ABSENT", "punch_in": pin})
    changed = call("Punch correction recomputes metrics", "PATCH", patch_path, parameters=parameters,
                   body={"punch_in": pin + 900000, "reason": "Correct arrival by fifteen minutes", "regularized_by": "browser.runner"})
    fields(changed, {"work_hours": 8.25, "late_minutes": 45, "punch_in": pin + 900000})
    require(len(changed["history"]) == 2, "Both histories retained")
    fields(changed["history"][1]["changes"]["punch_in"], {"from": pin, "to": pin + 900000})
    call("Unknown correction record", "PATCH", patch_path, 404,
         parameters={"emp_code": code, "date": "2026-10-13"}, body=correction)

    month = call("Monthly summary after correction", "GET", monthly_path, parameters={"emp_code": code, "month": "2026-10"})
    fields(month, {"working_days": 22, "present_days": 1.0, "late_count": 1, "total_late_minutes": 45, "attendance_pct": 4.55})
    call("Unknown monthly employee", "GET", monthly_path, 404, parameters={"emp_code": "EMP9999", "month": "2026-10"})
    summary = call("Department includes no-log employee", "GET", "/analytics/departments/summary",
                   parameters={"month": "2026-10", "department": "Browser"})
    fields(summary["items"][0], {"headcount": 2, "present_days": 1.0, "avg_work_hours": 8.25, "total_late_minutes": 45})
    leaders = call("Filtered late leaderboard", "GET", "/analytics/leaderboard/late",
                   parameters={"month": "2026-10", "department": "Browser", "limit": 1})
    require(len(leaders["items"]) == 1 and leaders["items"][0]["emp_code"] == code, "Filtered ranking")
    ties = call("Every competition-rank cutoff tie", "GET", "/analytics/leaderboard/late",
                parameters={"month": "2026-10", "department": "Browser Ties", "limit": 2})
    require([x["rank"] for x in ties["items"]] == [1, 2, 2], "Competition rank cutoff")
    require([x["emp_code"] for x in ties["items"]] == ["EMP0200", "EMP0201", "EMP0202"], "Tie ordering")
    trend = call("Dense trend and moving averages", "GET", trend_path,
                 parameters={"department": "Browser", "from": "2026-10-12", "to": "2026-10-18"})["items"]
    require(len(trend) == 7 and all(x["headcount"] == 2 for x in trend), "Dense daily headcount")
    require([x["attendance_rate"] for x in trend] == [.5, 0, 0, 0, 0, None, None], "Weekday/weekend rates")
    require([x["moving_avg_7d"] for x in trend] == [.5, .25, .1667, .125, .1, .1, .1], "Calendar moving averages")
    empty = call("Entirely empty trend range", "GET", trend_path,
                 parameters={"department": "Browser", "from": "2026-10-19", "to": "2026-10-25"})["items"]
    require(len(empty) == 7 and all(x["present_count"] == 0 and x["moving_avg_7d"] == 0 for x in empty), "Empty daily rows")
    call("Impossible trend date", "GET", trend_path, 422,
         parameters={"department": "Browser", "from": "2026-02-30", "to": "2026-03-01"})
    call("Unknown department", "GET", trend_path, 404,
         parameters={"department": "Unknown", "from": "2026-10-12", "to": "2026-10-18"})

    night = employee("EMP0102", department="Browser Night", shift_start="22:00", shift_end="06:00", joined_on="2026-10-01")
    call("Create overnight employee", "POST", "/employees", 201, body=night)
    opened = call("Overnight previous attendance date", "POST", "/attendance/punch-in", 201,
                  body={"emp_code": "EMP0102", "punched_at": millis("2026-10-13T05:40:00+05:30")})
    fields(opened, {"date": "2026-10-12"})
    closed = call("Overnight exit and overtime", "POST", "/attendance/punch-out",
                  body={"emp_code": "EMP0102", "punched_at": millis("2026-10-13T06:40:00+05:30")})
    fields(closed, {"work_hours": 1.0, "overtime_minutes": 40, "half_day": True})

    operations = {
        "attendance_list": {"emp_code": code, "status": "WFH", "page": 1, "page_size": 1},
        "employee_monthly": {"emp_code": code, "month": "2026-10"},
        "department_summary": {"department": "Browser", "month": "2026-10"},
        "late_leaderboard": {"department": "Browser Ties", "month": "2026-10", "limit": 2},
        "department_trend": {"department": "Browser", "from": "2026-10-12", "to": "2026-10-18"},
    }
    for endpoint, query in operations.items():
        plan = call("Explain " + endpoint, "GET", explain_path, parameters={"endpoint": endpoint, **query})
        fields(plan, {"endpoint": endpoint, "collection": "attendance_logs" if endpoint == "attendance_list" else "employees"})
        require('"executionStats"' in json.dumps(plan) and '"IXSCAN"' in json.dumps(plan)
                and '"COLLSCAN"' not in json.dumps(plan), "Real indexed executionStats")
    call("Missing explain month", "GET", explain_path, 422, parameters={"endpoint": "department_summary"})
    call("Invalid explain trend date", "GET", explain_path, 422,
         parameters={"endpoint": "department_trend", "department": "Browser", "from": "2026-02-30", "to": "2026-03-01"})
    stored = database.attendance_logs.find_one({"emp_code": code, "date": "2026-10-12"})
    require(isinstance(stored["punch_in"], datetime) and len(stored["history"]) == 2, "Stored BSON and retained audit")
    require(isinstance(stored["history"][1]["changes"]["punch_in"]["from"], datetime), "Nested BSON history")
    require(len(list(database.employees.list_indexes())) == 5 and len(list(database.attendance_logs.list_indexes())) == 6,
            "Nine non-default startup indexes")
    successful = {(x["method"], x["operation"]) for x in ui.report["checks"] if x["observed_status"] < 300}
    require(len(successful) == 12, "Every endpoint has a successful browser execution")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", default=os.getenv("TEST_MONGO_URI", "mongodb://127.0.0.1:27028"))
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--viewport", choices=("desktop", "mobile", "both"), default="both")
    args = parser.parse_args()
    uri = urlparse(args.mongo_uri)
    require(uri.scheme == "mongodb" and uri.hostname == "127.0.0.1" and not uri.username,
            "Browser tests require an unauthenticated loopback disposable MongoDB server")
    artifacts = args.artifacts or Path(tempfile.mkdtemp(prefix="candidate-kit-playwright-"))
    artifacts.mkdir(parents=True, exist_ok=True)
    result = {"playwright_version": version("playwright"), "artifacts": str(artifacts), "profiles": []}
    print("Browser evidence:", artifacts, flush=True)
    client = MongoClient(args.mongo_uri, tz_aware=True, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    result["mongo_version"] = client.server_info()["version"]
    profiles = {"desktop": {"width": 1440, "height": 1000}, "mobile": {"width": 390, "height": 844}}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not args.headed)
            result["browser_version"] = browser.version
            try:
                for name, viewport in profiles.items():
                    if args.viewport != "both" and args.viewport != name:
                        continue
                    database_name = "candidate_kit_browser_" + uuid4().hex
                    require(database_name not in client.list_database_names(), "Database must be newly created")
                    database = client[database_name]
                    profile = {"viewport": name, "dimensions": viewport, "database": database_name,
                               "checks": [], "page_errors": [], "passed": False}
                    result["profiles"].append(profile)
                    target = artifacts / name
                    target.mkdir()
                    process = log = http = context = page = None
                    try:
                        seed(database)
                        process, log, http = launch_server(args.mongo_uri, database_name)
                        context = browser.new_context(viewport=viewport, is_mobile=name == "mobile", has_touch=name == "mobile")
                        context.set_default_timeout(15000)
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                        page = context.new_page()
                        page.on("pageerror", lambda error: profile["page_errors"].append(str(error)))
                        walkthrough(Swagger(page, str(http.base_url).rstrip("/"), target, profile), database)
                        require(not profile["page_errors"], "Unhandled browser JavaScript errors")
                        profile["passed"] = True
                    except Exception:
                        profile["failure"] = traceback.format_exc()
                        if page is not None:
                            page.screenshot(path=str(target / "failure.png"))
                        raise
                    finally:
                        if context is not None:
                            context.tracing.stop(path=str(target / "trace.zip"))
                            context.close()
                        if process is not None:
                            stop_server(process, log, http)
                        client.drop_database(database_name)
                        profile["database_removed"] = database_name not in client.list_database_names()
                        require(profile["database_removed"], "Disposable database cleanup")
                        (artifacts / "summary.json").write_text(json.dumps(result, indent=2))
            finally:
                browser.close()
    finally:
        client.close()
        (artifacts / "summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"passed": all(p["passed"] for p in result["profiles"]),
                      "browser_checks": sum(len(p["checks"]) for p in result["profiles"]),
                      "profiles": len(result["profiles"]), "artifacts": str(artifacts)}, indent=2))


if __name__ == "__main__":
    main()

"""Employee Attendance API, contract v2.0: employee and attendance operations.

Run from the repository root: uvicorn app.main:app --port 8000
"""
import asyncio
import calendar
import json
import logging
import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Literal

from bson.decimal128 import Decimal128
from bson import json_util
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, StrictInt, AfterValidator, model_validator
from pymongo import ASCENDING, DESCENDING, IndexModel, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

load_dotenv(override=False)
UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
client = MongoClient(
    os.getenv("MONGO_URI", "mongodb://localhost:27017"),
    tz_aware=True, tzinfo=UTC, serverSelectionTimeoutMS=1000,
    connectTimeoutMS=1000, socketTimeoutMS=10000,
)
db = client[os.getenv("MONGO_DB", "attendance_db")]
logger = logging.getLogger(__name__)
ready = threading.Event()
stop_monitor = threading.Event()


# Lifecycle: readiness includes both connectivity and database guarantees.
def create_indexes():
    db.employees.create_indexes([
        IndexModel([("emp_code", ASCENDING)], unique=True, name="employee_code_unique"),
        IndexModel([("department", ASCENDING), ("emp_code", ASCENDING)], name="employee_department_code"),
        IndexModel([("joined_on", ASCENDING), ("department", ASCENDING), ("emp_code", ASCENDING)], name="employee_joined_department_code"),
        IndexModel([("department", ASCENDING), ("joined_on", ASCENDING), ("emp_code", ASCENDING)], name="employee_department_joined_code"),
    ])
    db.attendance_logs.create_indexes([
        IndexModel([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="attendance_employee_date_unique"),
        IndexModel([("date", DESCENDING), ("emp_code", ASCENDING)], name="attendance_date_code"),
        IndexModel([("status", ASCENDING), ("date", DESCENDING), ("emp_code", ASCENDING)], name="attendance_status_date_code"),
        IndexModel([("emp_code", ASCENDING), ("status", ASCENDING), ("date", DESCENDING)], name="attendance_employee_status_date"),
        IndexModel([("emp_code", ASCENDING), ("punch_in", DESCENDING), ("date", DESCENDING)], name="attendance_employee_punch_date"),
    ])


def check_database():
    try:
        client.admin.command("ping")
        if not ready.is_set():
            create_indexes()
        ready.set()
    except PyMongoError as exc:
        ready.clear()
        # Invalid preexisting data is preserved. In particular, never deduplicate
        # records just to make a unique index build succeed.
        logger.warning("MongoDB readiness failed: %s", type(exc).__name__)


def monitor_database():
    while not stop_monitor.wait(1):
        check_database()


@asynccontextmanager
async def lifespan(app):
    stop_monitor.clear()
    await asyncio.to_thread(check_database)
    monitor = threading.Thread(target=monitor_database, name="mongo-readiness", daemon=True)
    monitor.start()
    try:
        yield
    finally:
        stop_monitor.set()
        await asyncio.to_thread(monitor.join, 12)
        client.close()
        ready.clear()


app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0", lifespan=lifespan)


def require_database():
    if not ready.is_set():
        raise HTTPException(503, "MongoDB is not ready")


@app.exception_handler(PyMongoError)
async def database_error(request, exc):
    from fastapi.responses import JSONResponse
    ready.clear()
    logger.warning("MongoDB request failed: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "MongoDB is unavailable"})


# Time helpers: BSON defaults to naive UTC outside our configured client.
def utc_seconds(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0)


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def from_millis(value: int) -> datetime:
    return EPOCH + timedelta(seconds=value // 1000)


def epoch_millis(value: datetime) -> int:
    return (utc_seconds(value) - EPOCH) // timedelta(milliseconds=1)


def attendance_date(punch_in: datetime, shift_start: str, shift_end: str) -> str:
    local = utc_seconds(punch_in).astimezone(IST)
    day = local.date()
    if shift_end <= shift_start and local.time() < time.fromisoformat(shift_end):
        day -= timedelta(days=1)
    return day.isoformat()


def shift_bounds(date_str: str, shift_start: str, shift_end: str):
    day = date.fromisoformat(date_str)
    start = datetime.combine(day, time.fromisoformat(shift_start), IST)
    end_day = day + timedelta(days=shift_end <= shift_start)
    end = datetime.combine(end_day, time.fromisoformat(shift_end), IST)
    return start.astimezone(UTC), end.astimezone(UTC)


def compute_late_minutes(punch_in: datetime, shift_start: str, shift_end: str, date_str: str) -> int:
    start, _ = shift_bounds(date_str, shift_start, shift_end)
    seconds = int((utc_seconds(punch_in) - start).total_seconds())
    return seconds // 60 if seconds > 600 else 0


def half_up(value: Decimal, places: int = 2) -> float:
    return float(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = int((utc_seconds(punch_out) - utc_seconds(punch_in)).total_seconds())
    return half_up(Decimal(seconds) / Decimal(3600))


def compute_overtime(punch_out: datetime, shift_start: str, shift_end: str, date_str: str) -> int:
    _, end = shift_bounds(date_str, shift_start, shift_end)
    minutes = int((utc_seconds(punch_out) - end).total_seconds()) // 60
    return minutes if minutes >= 30 else 0


# Validation keeps optional omission distinct from explicit null.
def calendar_date(value: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Expected YYYY-MM-DD")
    date.fromisoformat(value)
    return value


DateString = Annotated[str, AfterValidator(calendar_date)]


def calendar_month(value: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value):
        raise ValueError("Expected YYYY-MM")
    date.fromisoformat(value + "-01")
    return value


MonthString = Annotated[str, AfterValidator(calendar_month)]
ShiftString = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
EpochMillis = Annotated[StrictInt, Field(ge=100000000000, le=4102444800000)]
Status = Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]
PresenceStatus = Literal["PRESENT", "WFH", "ON_DUTY"]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
LeaderboardLimit = Annotated[int, Query(ge=1, le=50)]


class EmployeeIn(BaseModel):
    emp_code: str = Field(pattern=r"^EMP[0-9]{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str = Field(min_length=1, max_length=50)
    shift_start: ShiftString = "09:30"
    shift_end: ShiftString = "18:30"
    joined_on: DateString

    @model_validator(mode="after")
    def different_shifts(self):
        if self.shift_start == self.shift_end:
            raise ValueError("Shift start and end must differ")
        return self


class PunchInIn(BaseModel):
    emp_code: str
    # Default is an internal sentinel only: supplied null is validated and rejected.
    punched_at: EpochMillis = None
    status: PresenceStatus = "PRESENT"


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: EpochMillis = None


class RegularizeIn(BaseModel):
    status: Status = None
    punch_in: EpochMillis = None
    punch_out: EpochMillis = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)


# API serialization is independent of BSON and never recomputes stored metrics.
def serialize_instants(value):
    if isinstance(value, datetime):
        return epoch_millis(value)
    if isinstance(value, dict):
        return {key: serialize_instants(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize_instants(item) for item in value]
    return value


EMPLOYEE_FIELDS = ("emp_code", "name", "email", "department", "shift_start", "shift_end", "joined_on", "created_at")
ATTENDANCE_DEFAULTS = {"punch_in": None, "punch_out": None, "work_hours": None,
                       "late_minutes": 0, "overtime_minutes": 0, "half_day": False, "history": []}


def employee_response(doc):
    return serialize_instants({key: doc[key] for key in EMPLOYEE_FIELDS})


def attendance_response(doc):
    result = {key: doc[key] for key in ("emp_code", "date", "status")}
    result.update({key: doc.get(key, default) for key, default in ATTENDANCE_DEFAULTS.items()})
    return serialize_instants(result)


# Attendance writes guard the original stored shape, not response defaults.
PRESENCE_STATUSES = {"PRESENT", "WFH", "ON_DUTY"}
MUTABLE_FIELDS = ("status", "punch_in", "punch_out", "work_hours", "late_minutes", "overtime_minutes", "half_day")


def validate_punch_interval(punch_in, punch_out):
    seconds = int((utc_seconds(punch_out) - utc_seconds(punch_in)).total_seconds())
    if not 0 < seconds <= 86400:
        raise HTTPException(422, "Punch-out must be after punch-in and within 24 hours")


def recompute_attendance(record, employee):
    final = {field: record.get(field, ATTENDANCE_DEFAULTS.get(field)) for field in MUTABLE_FIELDS}
    if final["status"] not in PRESENCE_STATUSES:
        final.update(punch_in=None, punch_out=None, work_hours=None,
                     late_minutes=0, overtime_minutes=0, half_day=False)
        return final
    if final["punch_in"] is None:
        raise HTTPException(422, "Presence status requires a punch-in")
    final["punch_in"] = utc_seconds(final["punch_in"])
    if attendance_date(final["punch_in"], employee["shift_start"], employee["shift_end"]) != record["date"]:
        raise HTTPException(422, "Punch-in must remain on the addressed attendance date")
    final["late_minutes"] = compute_late_minutes(
        final["punch_in"], employee["shift_start"], employee["shift_end"], record["date"])
    if final["punch_out"] is None:
        final.update(work_hours=None, overtime_minutes=0, half_day=False)
    else:
        final["punch_out"] = utc_seconds(final["punch_out"])
        validate_punch_interval(final["punch_in"], final["punch_out"])
        final["work_hours"] = compute_work_hours(final["punch_in"], final["punch_out"])
        final["overtime_minutes"] = compute_overtime(
            final["punch_out"], employee["shift_start"], employee["shift_end"], record["date"])
        final["half_day"] = final["work_hours"] < 4.50
    return final


def original_record_filter(record):
    query = {"emp_code": record["emp_code"], "date": record["date"]}
    for field in MUTABLE_FIELDS:
        if field not in record:
            query[field] = {"$exists": False}
        else:
            query[field] = {"$eq": record[field], "$exists": True}
    # Every successful correction appends an entry. Its length therefore guards
    # edits that change fields and later restore their previous values (ABA).
    query["$expr"] = {"$eq": [{"$size": {"$ifNull": ["$history", []]}}, len(record.get("history", []))]}
    return query


def update_attendance(record, fields, history_entry=None):
    update = {"$set": fields}
    if history_entry is not None:
        update["$push"] = {"history": history_entry}
    result = db.attendance_logs.find_one_and_update(
        original_record_filter(record), update, return_document=ReturnDocument.AFTER,
        hint="attendance_employee_date_unique")
    if result is None:
        raise HTTPException(409, "Attendance changed concurrently; reread and resubmit")
    return attendance_response(result)


# Reusable query, sort and hint builders for live listings and Part 2 explain.
def employee_list_query(department=None):
    query = {} if department is None else {"department": department}
    hint = "employee_code_unique" if department is None else "employee_department_code"
    return query, [("emp_code", ASCENDING)], hint


def attendance_list_query(emp_code=None, date_from=None, date_to=None, status=None):
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")
    query = {}
    if emp_code is not None:
        query["emp_code"] = emp_code
    if date_from is not None or date_to is not None:
        query["date"] = {}
        if date_from is not None:
            query["date"]["$gte"] = date_from
        if date_to is not None:
            query["date"]["$lte"] = date_to
    if status is not None:
        query["status"] = status
    if emp_code is not None:
        hint = "attendance_employee_date_unique" if status is None else "attendance_employee_status_date"
    else:
        hint = "attendance_date_code" if status is None else "attendance_status_date_code"
    return query, [("date", DESCENDING), ("emp_code", ASCENDING)], hint


def punch_out_query(emp_code, instant):
    # Also normalize legacy BSON milliseconds for selection: instants in this
    # whole second are equal under R1, so the interval check rejects equality.
    return ({"emp_code": emp_code, "punch_in": {"$lt": instant + timedelta(seconds=1)}},
            [("punch_in", DESCENDING), ("date", DESCENDING)], "attendance_employee_punch_date")


def page_find_operation(collection_name, query, sort, hint, page, page_size):
    # Larger offsets are unreachable by a BSON-sized collection, but cannot be
    # encoded as command integers. Share this bound with both live and explain.
    skip = min((page - 1) * page_size, 2**63 - 1)
    return {"find": collection_name, "filter": query, "projection": {"_id": 0},
            "sort": dict(sort), "skip": skip, "limit": page_size, "hint": hint}


def database_page(collection, query, sort, hint, page, page_size, serializer):
    total = collection.count_documents(query, hint=hint)
    operation = page_find_operation(collection.name, query, sort, hint, page, page_size)
    items = []
    if operation["skip"] < total:
        cursor = collection.find(operation["filter"], operation["projection"]).hint(operation["hint"]).sort(
            list(operation["sort"].items())).skip(operation["skip"]).limit(operation["limit"])
        items = [serializer(doc) for doc in cursor]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/health")
def health():
    try:
        client.admin.command("ping")
    except PyMongoError:
        ready.clear()
        raise HTTPException(503, "MongoDB is unavailable")
    require_database()
    return {"status": "ok"}


@app.post("/employees", status_code=201, dependencies=[Depends(require_database)])
def create_employee(body: EmployeeIn):
    doc = {**body.model_dump(), "created_at": now_utc()}
    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "emp_code already exists")
    return employee_response(doc)


@app.get("/employees", dependencies=[Depends(require_database)])
def list_employees(department: str | None = None, page: Page = 1, page_size: PageSize = 20):
    query, sort, hint = employee_list_query(department)
    return database_page(db.employees, query, sort, hint, page, page_size, employee_response)


@app.post("/attendance/punch-in", status_code=201, dependencies=[Depends(require_database)])
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(404, "Employee not found")
    ts = now_utc() if "punched_at" not in body.model_fields_set else from_millis(body.punched_at)
    day = attendance_date(ts, emp["shift_start"], emp["shift_end"])
    doc = {"emp_code": body.emp_code, "date": day, "status": body.status,
           "punch_in": ts, "punch_out": None, "work_hours": None,
           "late_minutes": compute_late_minutes(ts, emp["shift_start"], emp["shift_end"], day),
           "overtime_minutes": 0, "half_day": False, "history": []}
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Already punched in for this date")
    return attendance_response(doc)


@app.get("/attendance", dependencies=[Depends(require_database)])
def list_attendance(
    emp_code: str | None = None, date_from: DateString | None = None,
    date_to: DateString | None = None, status: Status | None = None,
    page: Page = 1, page_size: PageSize = 20,
):
    query, sort, hint = attendance_list_query(emp_code, date_from, date_to, status)
    return database_page(db.attendance_logs, query, sort, hint, page, page_size, attendance_response)


@app.post("/attendance/punch-out", dependencies=[Depends(require_database)])
def punch_out(body: PunchOutIn):
    employee = db.employees.find_one({"emp_code": body.emp_code})
    if employee is None:
        raise HTTPException(404, "Employee not found")
    instant = now_utc() if "punched_at" not in body.model_fields_set else from_millis(body.punched_at)
    query, sort, hint = punch_out_query(body.emp_code, instant)
    record = db.attendance_logs.find_one(query, sort=sort, hint=hint)
    if record is None:
        raise HTTPException(404, "No qualifying punch-in found")
    if record.get("punch_out") is not None:
        raise HTTPException(409, "Already punched out")
    start = utc_seconds(record["punch_in"])
    validate_punch_interval(start, instant)
    hours = compute_work_hours(start, instant)
    fields = {"punch_in": start, "punch_out": instant, "work_hours": hours,
              "overtime_minutes": compute_overtime(instant, employee["shift_start"], employee["shift_end"], record["date"]),
              "half_day": hours < 4.50}
    return update_attendance(record, fields)


@app.patch("/attendance/{emp_code}/{date}", dependencies=[Depends(require_database)])
def regularize_attendance(emp_code: str, date: DateString, body: RegularizeIn):
    employee = db.employees.find_one({"emp_code": emp_code})
    if employee is None:
        raise HTTPException(404, "Employee not found")
    record = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if record is None:
        raise HTTPException(404, "Attendance not found")
    supplied = body.model_fields_set
    proposed = dict(record)
    if "status" in supplied:
        proposed["status"] = body.status
    if proposed["status"] in {"ABSENT", "LEAVE"} and supplied & {"punch_in", "punch_out"}:
        raise HTTPException(422, "Absence or leave cannot include punch fields")
    for field in ("punch_in", "punch_out"):
        if field in supplied:
            proposed[field] = from_millis(getattr(body, field))
    final = recompute_attendance(proposed, employee)
    changes = {field: {"from": record.get(field, ATTENDANCE_DEFAULTS.get(field)), "to": final[field]}
               for field in MUTABLE_FIELDS
               if record.get(field, ATTENDANCE_DEFAULTS.get(field)) != final[field]}
    if not changes:
        raise HTTPException(422, "Correction changes nothing")
    entry = {"at": now_utc(), "by": body.regularized_by, "reason": body.reason, "changes": changes}
    return update_attendance(record, final, entry)


# MongoDB analytics builders; handlers and future explain share these operations.
def month_bounds(month):
    year, number = map(int, month.split("-"))
    days = calendar.monthrange(year, number)[1]
    return month + "-01", f"{month}-{days:02d}", days


def mongo_half_up(value, places=2):
    # Reported metrics are non-negative. Decimal128 avoids binary half ties;
    # floor(x * factor + 0.5) implements half-up, whereas $round is half-even.
    factor = 10 ** places
    return {"$toDouble": {"$divide": [{"$floor": {"$add": [
        {"$multiply": [{"$toDecimal": value}, factor]}, Decimal128("0.5")]}}, factor]}}


def mongo_calendar_day(value):
    return {"$dateFromString": {"dateString": value, "format": "%Y-%m-%d", "timezone": "+05:30"}}


def mongo_weekday(value):
    return {"$not": [{"$in": [{"$dayOfWeek": {"date": value, "timezone": "+05:30"}}, [1, 7]]}]}


MONTHLY_METRICS = ("present_days", "leave_count", "late_count", "total_late_minutes",
                   "total_overtime_minutes", "on_duty_count", "hours_sum", "hours_count")


def monthly_logs_lookup(month):
    first, last, _ = month_bounds(month)
    presence = {"$in": ["$status", sorted(PRESENCE_STATUSES)]}
    present_day = {"$and": [presence, mongo_weekday(mongo_calendar_day("$date"))]}
    late = {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}
    hours_record = {"$and": [presence, {"$ne": [{"$ifNull": ["$work_hours", None]}, None]}]}
    return {"$lookup": {
        "from": "attendance_logs", "localField": "emp_code", "foreignField": "emp_code",
        "pipeline": [
            {"$match": {"date": {"$gte": first, "$lte": last}}},
            {"$group": {
                "_id": None,
                "present_days": {"$sum": {"$cond": [present_day,
                    {"$cond": [{"$ifNull": ["$half_day", False]}, 0.5, 1]}, 0]}},
                "leave_count": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
                "late_count": {"$sum": {"$cond": [late, 1, 0]}},
                "total_late_minutes": {"$sum": {"$cond": [late, "$late_minutes", 0]}},
                "total_overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}},
                "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$status", "ON_DUTY"]}, 1, 0]}},
                "hours_sum": {"$sum": {"$cond": [hours_record, {"$toDecimal": "$work_hours"}, Decimal128("0")]}},
                "hours_count": {"$sum": {"$cond": [hours_record, 1, 0]}},
            }},
        ], "as": "monthly_logs",
    }}


def monthly_metrics_stage():
    # Lookup returns at most one aggregate per employee, including no-log cases.
    return {"$set": {"metrics": {"$ifNull": [
        {"$arrayElemAt": ["$monthly_logs", 0]}, {field: 0 for field in MONTHLY_METRICS}]}}}


def employee_monthly_pipeline(emp_code, month):
    first, _, days = month_bounds(month)
    calendar_days = {"$map": {"input": {"$range": [0, days]}, "as": "offset",
        "in": {"$dateAdd": {"startDate": mongo_calendar_day(first), "unit": "day",
                            "amount": "$$offset", "timezone": "+05:30"}}}}
    working_days = {"$size": {"$filter": {"input": calendar_days, "as": "day", "cond": {"$and": [
        mongo_weekday("$$day"), {"$gte": [
            {"$dateToString": {"date": "$$day", "format": "%Y-%m-%d", "timezone": "+05:30"}}, "$joined_on"]}]}}}}
    pipeline = [
        {"$match": {"emp_code": emp_code}}, monthly_logs_lookup(month), monthly_metrics_stage(),
        {"$set": {"working_days": working_days}},
        {"$project": {
            "_id": 0, "emp_code": 1, "month": {"$literal": month}, "working_days": 1,
            "present_days": mongo_half_up("$metrics.present_days"),
            "leave_days": "$metrics.leave_count", "late_count": "$metrics.late_count",
            "total_late_minutes": "$metrics.total_late_minutes", "total_overtime_minutes": "$metrics.total_overtime_minutes",
            "attendance_pct": {"$cond": [{"$gt": ["$working_days", 0]},
                mongo_half_up({"$multiply": [{"$divide": [{"$toDecimal": "$metrics.present_days"}, "$working_days"]}, 100]}), None]},
        }},
    ]
    return pipeline, "employee_code_unique"


def department_summary_pipeline(month, department=None):
    _, last, _ = month_bounds(month)
    query = {"joined_on": {"$lte": last}}
    if department is not None:
        query["department"] = department
    pipeline = [
        {"$match": query}, monthly_logs_lookup(month), monthly_metrics_stage(),
        {"$group": {"_id": "$department", "headcount": {"$sum": 1},
            **{field: {"$sum": "$metrics." + field} for field in MONTHLY_METRICS}}},
        {"$sort": {"_id": 1}},
        {"$project": {
            "_id": 0, "department": "$_id", "headcount": 1,
            "present_days": mongo_half_up("$present_days"),
            "avg_work_hours": {"$cond": [{"$gt": ["$hours_count", 0]},
                mongo_half_up({"$divide": ["$hours_sum", "$hours_count"]}), None]},
            "late_count": 1, "total_late_minutes": 1, "leave_count": 1, "on_duty_count": 1,
        }},
    ]
    hint = "employee_joined_department_code" if department is None else "employee_department_joined_code"
    return pipeline, hint


@app.get("/analytics/employees/{emp_code}/monthly", dependencies=[Depends(require_database)])
def employee_monthly(emp_code: str, month: MonthString):
    pipeline, hint = employee_monthly_pipeline(emp_code, month)
    result = next(db.employees.aggregate(pipeline, hint=hint), None)
    if result is None:
        raise HTTPException(404, "Employee not found")
    return result


@app.get("/analytics/departments/summary", dependencies=[Depends(require_database)])
def department_summary(month: MonthString, department: str | None = None):
    pipeline, hint = department_summary_pipeline(month, department)
    return {"month": month, "items": list(db.employees.aggregate(pipeline, hint=hint))}


def late_leaderboard_pipeline(month, limit=10, department=None):
    first, last, _ = month_bounds(month)
    query, _, hint = employee_list_query(department)
    pipeline = [
        {"$match": query},
        {"$lookup": {"from": "attendance_logs", "localField": "emp_code", "foreignField": "emp_code",
            "pipeline": [
                {"$match": {"date": {"$gte": first, "$lte": last}, "late_minutes": {"$gt": 0}}},
                {"$group": {"_id": None, "total_late_minutes": {"$sum": "$late_minutes"}, "late_count": {"$sum": 1}}},
            ], "as": "lateness"}},
        {"$unwind": "$lateness"},
        {"$set": {"total_late_minutes": "$lateness.total_late_minutes", "late_count": "$lateness.late_count"}},
        {"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}},
        {"$match": {"rank": {"$lte": limit}}},
        {"$sort": {"total_late_minutes": -1, "emp_code": 1}},
        {"$project": {"_id": 0, "rank": 1, "emp_code": 1, "name": 1, "department": 1,
                      "total_late_minutes": 1, "late_count": 1}},
    ]
    return pipeline, hint


def trend_bounds(date_from, date_to):
    first, last = date.fromisoformat(date_from), date.fromisoformat(date_to)
    if last < first or (last - first).days >= 92:
        raise HTTPException(422, "Trend range must be ordered and contain at most 92 calendar days")
    origin = date(1970, 1, 1)
    return (first - origin).days, (last - origin).days + 1


def department_trend_pipeline(department, date_from, date_to):
    first, end = trend_bounds(date_from, date_to)
    origin = mongo_calendar_day("1970-01-01")
    presence = {"$in": ["$status", sorted(PRESENCE_STATUSES)]}
    pipeline = [
        {"$match": {"department": department}},
        {"$lookup": {"from": "attendance_logs", "localField": "emp_code", "foreignField": "emp_code",
            "pipeline": [
                {"$match": {"date": {"$gte": date_from, "$lte": date_to}}},
                {"$group": {"_id": "$date",
                    "present_count": {"$sum": {"$cond": [presence,
                        {"$cond": [{"$ifNull": ["$half_day", False]}, 0.5, 1]}, 0]}},
                    "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
                }},
                {"$project": {"_id": 0, "day_number": {"$dateDiff": {"startDate": origin,
                    "endDate": mongo_calendar_day("$_id"), "unit": "day", "timezone": "+05:30"}},
                    "present_count": 1, "late_count": 1}},
            ], "as": "daily"}},
        # A known department supplies an anchor even when its entire range has
        # no logs. Multiple anchors are grouped away without changing metrics.
        {"$set": {"daily": {"$concatArrays": ["$daily", [
            {"day_number": first, "present_count": 0, "late_count": 0}]]}}},
        {"$unwind": "$daily"},
        {"$group": {"_id": "$daily.day_number", "present_count": {"$sum": "$daily.present_count"},
                    "late_count": {"$sum": "$daily.late_count"}}},
        {"$project": {"_id": 0, "day_number": "$_id", "present_count": 1, "late_count": 1}},
        {"$sort": {"day_number": 1}},
        {"$densify": {"field": "day_number", "range": {"step": 1, "bounds": [first, end]}}},
        {"$set": {"calendar_day": {"$dateAdd": {"startDate": origin, "unit": "day",
                    "amount": "$day_number", "timezone": "+05:30"}},
                  "present_count": {"$ifNull": ["$present_count", 0]}, "late_count": {"$ifNull": ["$late_count", 0]}}},
        {"$set": {"date": {"$dateToString": {"date": "$calendar_day", "format": "%Y-%m-%d", "timezone": "+05:30"}},
                  "is_working_day": mongo_weekday("$calendar_day")}},
        {"$lookup": {"from": "employees", "let": {"day": "$date"}, "pipeline": [
            {"$match": {"department": department, "$expr": {"$lte": ["$joined_on", "$$day"]}}},
            {"$count": "headcount"},
        ], "as": "eligible"}},
        {"$set": {"headcount": {"$ifNull": [{"$arrayElemAt": ["$eligible.headcount", 0]}, 0]}}},
        {"$set": {"attendance_rate": {"$cond": [
            {"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]},
            mongo_half_up({"$divide": [{"$toDecimal": "$present_count"}, "$headcount"]}, 4), None]}}},
        {"$setWindowFields": {"sortBy": {"day_number": 1}, "output": {"moving_avg": {
            "$avg": {"$toDecimal": "$attendance_rate"}, "window": {"documents": [-6, 0]}}}}},
        {"$sort": {"day_number": 1}},
        {"$project": {"_id": 0, "date": 1, "is_working_day": 1, "headcount": 1,
            "present_count": mongo_half_up("$present_count"), "late_count": 1,
            "attendance_rate": 1, "moving_avg_7d": mongo_half_up("$moving_avg", 4)}},
    ]
    return pipeline, "employee_department_code"


@app.get("/analytics/leaderboard/late", dependencies=[Depends(require_database)])
def late_leaderboard(month: MonthString, limit: LeaderboardLimit = 10, department: str | None = None):
    pipeline, hint = late_leaderboard_pipeline(month, limit, department)
    return {"month": month, "items": list(db.employees.aggregate(pipeline, hint=hint))}


@app.get("/analytics/departments/{department:path}/trend", dependencies=[Depends(require_database)])
def department_trend(department: str, date_from: Annotated[DateString, Query(alias="from")],
                     date_to: Annotated[DateString, Query(alias="to")]):
    pipeline, hint = department_trend_pipeline(department, date_from, date_to)
    if db.employees.find_one({"department": department}, {"_id": 0, "emp_code": 1}, hint=hint) is None:
        raise HTTPException(404, "Department not found")
    return {"department": department, "items": list(db.employees.aggregate(pipeline, hint=hint))}


ExplainEndpoint = Literal["attendance_list", "employee_monthly", "department_summary", "late_leaderboard", "department_trend"]


def require_explain_parameters(**parameters):
    missing = [name for name, value in parameters.items() if value is None]
    if missing:
        raise HTTPException(422, "Missing required parameters: " + ", ".join(missing))


@app.get("/admin/explain/{endpoint}", dependencies=[Depends(require_database)])
def explain_endpoint(
    endpoint: ExplainEndpoint, emp_code: str | None = None, month: MonthString | None = None,
    department: str | None = None, limit: LeaderboardLimit = 10,
    date_from: DateString | None = None, date_to: DateString | None = None, status: Status | None = None,
    trend_from: Annotated[DateString | None, Query(alias="from")] = None,
    trend_to: Annotated[DateString | None, Query(alias="to")] = None,
    page: Page = 1, page_size: PageSize = 20,
):
    collection = "employees"
    if endpoint == "attendance_list":
        collection = "attendance_logs"
        query, sort, hint = attendance_list_query(emp_code, date_from, date_to, status)
        operation = page_find_operation(collection, query, sort, hint, page, page_size)
    else:
        if endpoint == "department_trend":
            require_explain_parameters(department=department, **{"from": trend_from, "to": trend_to})
            pipeline, hint = department_trend_pipeline(department, trend_from, trend_to)
        else:
            require_explain_parameters(month=month)
            if endpoint == "employee_monthly":
                require_explain_parameters(emp_code=emp_code)
                pipeline, hint = employee_monthly_pipeline(emp_code, month)
            elif endpoint == "department_summary":
                pipeline, hint = department_summary_pipeline(month, department)
            else:
                pipeline, hint = late_leaderboard_pipeline(month, limit, department)
        operation = {"aggregate": collection, "pipeline": pipeline, "cursor": {}, "hint": hint}
    explanation = db.command("explain", operation, verbosity="executionStats")
    # Preserve the raw document, including BSON operands in its command/plan.
    return {"endpoint": endpoint, "collection": collection,
            "explain": json.loads(json_util.dumps(explanation, json_options=json_util.RELAXED_JSON_OPTIONS))}

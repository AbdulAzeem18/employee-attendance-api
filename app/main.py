"""
Employee Attendance & Analytics API - HROne Assignment
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from pymongo import MongoClient
import pymongo.errors

load_dotenv()

# IST is UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Enforce database uniqueness constraints and performance indexes
    db.employees.create_index("emp_code", unique=True)
    db.attendance_logs.create_index([("emp_code", 1), ("date", 1)], unique=True)
    db.attendance_logs.create_index("date")
    db.attendance_logs.create_index([("emp_code", 1), ("punch_out", 1)])
    yield


app = FastAPI(
    title="Employee Attendance & Analytics API",
    version="2.0.0",
    lifespan=lifespan,
)


# --------------------------------------------------------------------------- #
# Helpers & Business Logic (R1 - R10)
# --------------------------------------------------------------------------- #
def parse_epoch_ms_or_now(epoch_ms: Optional[int]) -> datetime:
    """Converts epoch milliseconds to UTC, truncated to whole seconds."""
    if epoch_ms is not None:
        return datetime.fromtimestamp(epoch_ms // 1000, tz=timezone.utc)
    return datetime.now(timezone.utc).replace(microsecond=0)


def compute_late_minutes(punch_in_utc: datetime, shift_start_str: str) -> int:
    """Computes late arrival in minutes against IST shift start (10m grace period)."""
    punch_in_ist = punch_in_utc.astimezone(IST)
    sh_h, sh_m = map(int, shift_start_str.split(":"))
    shift_start_dt = punch_in_ist.replace(hour=sh_h, minute=sh_m, second=0, microsecond=0)
    delta_seconds = (punch_in_ist - shift_start_dt).total_seconds()
    minutes_late = int(delta_seconds // 60)
    return max(0, minutes_late) if minutes_late > 10 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    """Computes total duration in hours using half-up rounding."""
    seconds = Decimal(str((punch_out - punch_in).total_seconds()))
    hours = (seconds / Decimal("3600")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(hours)


def compute_overtime(
    punch_out_utc: datetime, shift_start_str: str, shift_end_str: str, date_str: str
) -> int:
    """Handles standard and overnight shift end comparisons in IST with >=30m rule."""
    punch_out_ist = punch_out_utc.astimezone(IST)
    year, month, day = map(int, date_str.split("-"))
    sh_end_h, sh_end_m = map(int, shift_end_str.split(":"))
    sh_start_h, sh_start_m = map(int, shift_start_str.split(":"))

    base_end_dt = datetime(year, month, day, sh_end_h, sh_end_m, tzinfo=IST)
    # Check for overnight shift (ends next calendar day)
    if (sh_end_h < sh_start_h) or (sh_end_h == sh_start_h and sh_end_m <= sh_start_m):
        base_end_dt += timedelta(days=1)

    delta_minutes = max(0, int((punch_out_ist - base_end_dt).total_seconds() // 60))
    return delta_minutes if delta_minutes >= 30 else 0


# --------------------------------------------------------------------------- #
# Request Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None


class AttendancePatchIn(BaseModel):
    by: str
    reason: str
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/employees", status_code=status.HTTP_201_CREATED)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(status_code=409, detail="emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    try:
        db.employees.insert_one(doc)
    except pymongo.errors.DuplicateKeyError:
        raise HTTPException(status_code=409, detail="emp_code already exists")
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = 1, page_size: int = 20):
    q = {}
    if department:
        q["department"] = department
    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)
    items = list(db.employees.find(q, {"_id": 0}).skip(skip).limit(page_size))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=status.HTTP_201_CREATED)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    ts_utc = parse_epoch_ms_or_now(body.punched_at)
    ts_ist = ts_utc.astimezone(IST)
    d = ts_ist.strftime("%Y-%m-%d")

    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts_utc,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts_utc, emp.get("shift_start", "09:30")),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        res = db.attendance_logs.insert_one(doc)
    except pymongo.errors.DuplicateKeyError:
        raise HTTPException(status_code=409, detail="already punched in for this date")

    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    ts_utc = parse_epoch_ms_or_now(body.punched_at)

    log = db.attendance_logs.find_one({"emp_code": body.emp_code, "punch_out": None})
    if not log:
        raise HTTPException(status_code=400, detail="No active punch-in found for this employee")

    punch_in_utc = log["punch_in"]
    if punch_in_utc.tzinfo is None:
        punch_in_utc = punch_in_utc.replace(tzinfo=timezone.utc)

    if ts_utc < punch_in_utc:
        raise HTTPException(status_code=400, detail="punch_out cannot be earlier than punch_in")

    work_hours = compute_work_hours(punch_in_utc, ts_utc)
    overtime = compute_overtime(
        ts_utc,
        emp.get("shift_start", "09:30"),
        emp.get("shift_end", "18:30"),
        log["date"],
    )
    half_day = work_hours < 4.0

    db.attendance_logs.update_one(
        {"_id": log["_id"]},
        {
            "$set": {
                "punch_out": ts_utc,
                "work_hours": work_hours,
                "overtime_minutes": overtime,
                "half_day": half_day,
            }
        },
    )

    updated = db.attendance_logs.find_one({"_id": log["_id"]})
    updated["id"] = str(updated.pop("_id"))
    return updated


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status

    total = db.attendance_logs.count_documents(q)
    skip = (page - 1) * page_size

    cursor = db.attendance_logs.find(q).sort("date", -1).skip(skip).limit(page_size)
    items = []
    for d in cursor:
        d["id"] = str(d.pop("_id"))
        items.append(d)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.patch("/attendance/{emp_code}/{date}")
def update_attendance_log(emp_code: str, date: str, body: AttendancePatchIn):
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    log = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if not log:
        raise HTTPException(status_code=404, detail="Attendance log not found")

    changes = {}
    sets = {}

    if body.status is not None and body.status != log.get("status"):
        changes["status"] = {"from": log.get("status"), "to": body.status}
        sets["status"] = body.status

    new_in_utc = log.get("punch_in")
    if body.punch_in is not None:
        target_in = parse_epoch_ms_or_now(body.punch_in)
        old_in = log.get("punch_in")
        if old_in and old_in.tzinfo is None:
            old_in = old_in.replace(tzinfo=timezone.utc)
        if target_in != old_in:
            changes["punch_in"] = {"from": old_in, "to": target_in}
            sets["punch_in"] = target_in
            new_in_utc = target_in

            new_late = compute_late_minutes(target_in, emp.get("shift_start", "09:30"))
            if new_late != log.get("late_minutes"):
                changes["late_minutes"] = {"from": log.get("late_minutes"), "to": new_late}
                sets["late_minutes"] = new_late

    new_out_utc = log.get("punch_out")
    if body.punch_out is not None:
        target_out = parse_epoch_ms_or_now(body.punch_out)
        old_out = log.get("punch_out")
        if old_out and old_out.tzinfo is None:
            old_out = old_out.replace(tzinfo=timezone.utc)
        if target_out != old_out:
            changes["punch_out"] = {"from": old_out, "to": target_out}
            sets["punch_out"] = target_out
            new_out_utc = target_out

            new_ot = compute_overtime(
                target_out,
                emp.get("shift_start", "09:30"),
                emp.get("shift_end", "18:30"),
                date,
            )
            if new_ot != log.get("overtime_minutes"):
                changes["overtime_minutes"] = {"from": log.get("overtime_minutes"), "to": new_ot}
                sets["overtime_minutes"] = new_ot

    if new_in_utc and new_out_utc:
        if new_out_utc.tzinfo is None:
            new_out_utc = new_out_utc.replace(tzinfo=timezone.utc)
        if new_in_utc.tzinfo is None:
            new_in_utc = new_in_utc.replace(tzinfo=timezone.utc)

        new_hours = compute_work_hours(new_in_utc, new_out_utc)
        if new_hours != log.get("work_hours"):
            changes["work_hours"] = {"from": log.get("work_hours"), "to": new_hours}
            sets["work_hours"] = new_hours

        new_half_day = new_hours < 4.0
        if new_half_day != log.get("half_day"):
            changes["half_day"] = {"from": log.get("half_day"), "to": new_half_day}
            sets["half_day"] = new_half_day

    update_query = {}
    if sets:
        update_query["$set"] = sets

    if changes:
        history_entry = {
            "at": datetime.now(timezone.utc).replace(microsecond=0),
            "by": body.by,
            "reason": body.reason,
            "changes": changes,
        }
        update_query["$push"] = {"history": history_entry}

    if update_query:
        db.attendance_logs.update_one({"_id": log["_id"]}, update_query)

    updated = db.attendance_logs.find_one({"_id": log["_id"]})
    updated["id"] = str(updated.pop("_id"))
    return updated


# --------------------------------------------------------------------------- #
# Analytics Endpoints (MongoDB Aggregation Pipelines)
# --------------------------------------------------------------------------- #
@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly_analytics(emp_code: str, month: str):
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    try:
        parsed_month = datetime.strptime(month.strip(), "%B %Y")
        month_label = parsed_month.strftime("%B %Y")
        month_prefix = parsed_month.strftime("%Y-%m")
    except ValueError:
        try:
            parsed_month = datetime.strptime(month.strip(), "%Y-%m")
            month_label = parsed_month.strftime("%B %Y")
            month_prefix = parsed_month.strftime("%Y-%m")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid month format. Use 'October 2026' or '2026-10'.",
            )

    pipeline = [
        {"$match": {"emp_code": emp_code, "date": {"$regex": f"^{month_prefix}"}}},
        {
            "$group": {
                "_id": None,
                "days_present": {
                    "$sum": {"$cond": [{"$eq": ["$status", "PRESENT"]}, 1, 0]}
                },
                "days_wfh": {"$sum": {"$cond": [{"$eq": ["$status", "WFH"]}, 1, 0]}},
                "days_absent": {
                    "$sum": {"$cond": [{"$eq": ["$status", "ABSENT"]}, 1, 0]}
                },
                "days_leave": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
                "total_work_hours": {"$sum": {"$ifNull": ["$work_hours", 0]}},
                "total_overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}},
                "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
                "worked_days_count": {
                    "$sum": {
                        "$cond": [
                            {"$and": [{"$ne": ["$work_hours", None]}, {"$gt": ["$work_hours", 0]}]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
    ]

    res = list(db.attendance_logs.aggregate(pipeline))
    if not res:
        return {
            "emp_code": emp_code,
            "month": month_label,
            "days_present": 0,
            "days_wfh": 0,
            "days_absent": 0,
            "days_leave": 0,
            "total_work_hours": 0.0,
            "avg_work_hours": 0.0,
            "total_overtime_minutes": 0,
            "total_late_minutes": 0,
        }

    data = res[0]
    worked_count = data.get("worked_days_count", 0)
    avg_hours = (
        round(data["total_work_hours"] / worked_count, 2) if worked_count > 0 else 0.0
    )

    return {
        "emp_code": emp_code,
        "month": month_label,
        "days_present": data["days_present"],
        "days_wfh": data["days_wfh"],
        "days_absent": data["days_absent"],
        "days_leave": data["days_leave"],
        "total_work_hours": round(data["total_work_hours"], 2),
        "avg_work_hours": avg_hours,
        "total_overtime_minutes": data["total_overtime_minutes"],
        "total_late_minutes": data["total_late_minutes"],
    }


@app.get("/analytics/departments/summary")
def departments_summary(date: str):
    pipeline = [
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"emp": "$emp_code"},
                "pipeline": [
                    {"$match": {"$expr": {"$and": [{"$eq": ["$emp_code", "$$emp"]}, {"$eq": ["$date", date]}]}}}
                ],
                "as": "log",
            }
        },
        {"$unwind": {"path": "$log", "preserveNullAndEmptyArrays": True}},
        {
            "$group": {
                "_id": "$department",
                "headcount": {"$sum": 1},
                "present_count": {
                    "$sum": {"$cond": [{"$in": ["$log.status", ["PRESENT", "WFH"]]}, 1, 0]}
                },
                "total_work_hours": {"$sum": {"$ifNull": ["$log.work_hours", 0]}},
            }
        },
        {
            "$project": {
                "department": "$_id",
                "_id": 0,
                "headcount": 1,
                "present_count": 1,
                "attendance_rate": {
                    "$cond": [
                        {"$gt": ["$headcount", 0]},
                        {"$round": [{"$multiply": [{"$divide": ["$present_count", "$headcount"]}, 100]}, 2]},
                        0.0,
                    ]
                },
                "avg_work_hours": {
                    "$cond": [
                        {"$gt": ["$present_count", 0]},
                        {"$round": [{"$divide": ["$total_work_hours", "$present_count"]}, 2]},
                        0.0,
                    ]
                },
            }
        },
        {"$sort": {"department": 1}},
    ]
    return list(db.employees.aggregate(pipeline))


@app.get("/analytics/leaderboard/late")
def leaderboard_late(limit: int = 5):
    pipeline = [
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "emp",
            }
        },
        {"$unwind": "$emp"},
        {
            "$project": {
                "_id": 0,
                "emp_code": "$_id",
                "name": "$emp.name",
                "department": "$emp.department",
                "total_late_minutes": 1,
            }
        },
        {"$sort": {"total_late_minutes": -1, "emp_code": 1}},
        {"$limit": limit},
    ]
    return list(db.attendance_logs.aggregate(pipeline))


@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str, date_from: str, date_to: str):
    pipeline = [
        {"$match": {"department": department}},
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"emp": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$emp"]},
                                    {"$gte": ["$date", date_from]},
                                    {"$lte": ["$date", date_to]},
                                ]
                            }
                        }
                    }
                ],
                "as": "logs",
            }
        },
        {"$unwind": "$logs"},
        {
            "$group": {
                "_id": "$logs.date",
                "present_count": {
                    "$sum": {"$cond": [{"$in": ["$logs.status", ["PRESENT", "WFH"]]}, 1, 0]}
                },
                "total_work_hours": {"$sum": {"$ifNull": ["$logs.work_hours", 0]}},
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": "$_id",
                "present_count": 1,
                "avg_work_hours": {
                    "$cond": [
                        {"$gt": ["$present_count", 0]},
                        {"$round": [{"$divide": ["$total_work_hours", "$present_count"]}, 2]},
                        0.0,
                    ]
                },
            }
        },
        {"$sort": {"date": 1}},
    ]
    return list(db.employees.aggregate(pipeline))


@app.get("/admin/explain/{endpoint_name}")
def explain_query(endpoint_name: str):
    if endpoint_name == "departments-summary":
        pipeline = [
            {"$lookup": {"from": "attendance_logs", "localField": "emp_code", "foreignField": "emp_code", "as": "log"}},
            {"$group": {"_id": "$department", "count": {"$sum": 1}}},
        ]
        return db.command("explain", {"aggregate": "employees", "pipeline": pipeline, "cursor": {}}, verbosity="executionStats")
    elif endpoint_name == "leaderboard-late":
        pipeline = [
            {"$group": {"_id": "$emp_code", "total": {"$sum": "$late_minutes"}}},
            {"$sort": {"total": -1, "_id": 1}},
            {"$limit": 5},
        ]
        return db.command("explain", {"aggregate": "attendance_logs", "pipeline": pipeline, "cursor": {}}, verbosity="executionStats")
    else:
        return db.command("explain", {"find": "attendance_logs", "filter": {"date": "2026-07-06"}}, verbosity="executionStats")

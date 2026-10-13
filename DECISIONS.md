# Architectural & Design Decisions (DECISIONS.md)

## 1. Schema & Indexing Strategy

### MongoDB Indexes

**`employees` Collection**

- `{ emp_code: 1 }` (Unique): Ensures that each employee has a unique employee code and supports efficient employee lookups.

**`attendance_logs` Collection**

- `{ emp_code: 1, date: 1 }` (Unique Compound): Enforces one attendance record per employee per date and supports efficient employee-specific attendance queries.
- `{ date: 1 }`: Supports date-based filtering and attendance queries.
- `{ emp_code: 1, punch_out: 1 }`: Supports queries for attendance records where an employee has not yet punched out.

These indexes are created during application startup to improve query efficiency and enforce data integrity.

## 2. Aggregation Pipelines vs. Application Processing

| Use Case | Strategy Selected | Architectural Justification |
|---|---|---|
| Monthly Employee Summary | `$match` followed by `$group` and `$cond` | Calculates attendance totals in MongoDB, reducing the need to transfer individual attendance records to the application. |
| Department Summary | MongoDB aggregation pipeline | Calculates department-level headcount, attendance counts, attendance rate, and average work hours. |
| Late-Arrival Leaderboard | MongoDB aggregation pipeline | Aggregates late minutes and combines attendance data with employee information to produce a ranked result. |
| Department Attendance Trend | MongoDB aggregation pipeline | Groups attendance records by date to calculate daily attendance metrics. |

## 3. Concurrency & Audit Integrity

### Atomicity and Duplicate Prevention

A unique compound index on `(emp_code, date)` prevents multiple attendance records for the same employee on the same date. Duplicate-key errors are handled to return HTTP 409 Conflict for duplicate punch-in attempts.

### Punch-Out Handling

The punch-out operation checks for an active attendance record where the employee has not yet punched out. If no active punch-in is found, the API returns an HTTP 400 error.

### Audit Trail Architecture

The manual attendance correction endpoint maintains a history array containing:

- The timestamp of the correction.
- The operator identifier (`by`).
- The correction reason.
- Field-level changes, including the previous (`from`) and updated (`to`) values.

This history makes previous corrections traceable and helps explain how an attendance record was changed.

## 4. API Design & Error Handling

- FastAPI provides REST endpoints and interactive API documentation through Swagger UI.
- Pydantic models validate incoming request structures.
- HTTP status codes communicate outcomes, including successful requests, duplicate records, missing employees, and invalid operations.
- MongoDB performs filtering, sorting, pagination, and aggregation where appropriate to reduce unnecessary application-side processing.

## 5. Verification and Limitations

The API was tested locally using FastAPI Swagger UI and MongoDB Community Server.

Verified behaviors include employee registration, duplicate employee handling, punch-in and punch-out, duplicate punch-in rejection, attendance filtering, manual correction history, analytics endpoints, and MongoDB query-plan inspection.

Further testing is needed for overnight shifts, boundary timestamps, grace-period calculations, input validation edge cases, concurrency under simultaneous requests, and performance with larger datasets.

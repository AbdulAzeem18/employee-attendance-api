# Employee Attendance & Analytics API

A REST API built with **Python, FastAPI, and MongoDB** to manage employee attendance, punch-in/punch-out records, manual attendance corrections, and attendance analytics.

## Features

- Employee registration and listing
- Attendance punch-in and punch-out
- Attendance listing with filters and pagination
- Manual attendance corrections with an audit history
- Monthly employee attendance analytics
- Department attendance summaries and trends
- Late-arrival leaderboard
- MongoDB query-plan inspection

## Technology Stack

- Python 3.12
- FastAPI
- MongoDB 6.0+
- PyMongo
- Pydantic
- Uvicorn

## Local Setup

### 1. Create and activate a virtual environment

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 3. Configure MongoDB

Install and start MongoDB Community Server locally. Configure `MONGO_URI` and `MONGO_DB` in your local `.env` file.

Do not commit `.env` or any credentials to the repository.

### 4. Start the API

Run this command from the project directory:

```powershell
python -m uvicorn app.main:app --port 8000 --reload
```

### 5. Explore the API

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to view and test the interactive API documentation.

## Main Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/employees` | Register an employee |
| GET | `/employees` | List employees |
| POST | `/attendance/punch-in` | Record punch-in |
| POST | `/attendance/punch-out` | Record punch-out |
| GET | `/attendance` | List and filter attendance |
| PATCH | `/attendance/{emp_code}/{date}` | Correct attendance |
| GET | `/analytics/employees/{emp_code}/monthly` | Monthly employee analytics |
| GET | `/analytics/departments/summary` | Department summary |
| GET | `/analytics/leaderboard/late` | Late-arrival leaderboard |
| GET | `/analytics/departments/{department}/trend` | Department attendance trend |
| GET | `/admin/explain/{endpoint_name}` | Inspect a MongoDB query plan |

## Documentation

See `REVIEW.md` for code-review findings and `DECISIONS.md` for design decisions.

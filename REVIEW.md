# Code Review & Defect Analysis (REVIEW.md)

## 1. Summary of Identified Defects in Starter Code

| ID | Component / Endpoint | Defect Description | Severity | Fix Implemented |
|---|---|---|---|---|
| BUG-01 | `compute_late_minutes` | Incorrect timezone handling can lead to inaccurate late-arrival calculations when UTC timestamps are compared with local shift times. | High | Converted timestamps for IST-based shift comparisons and applied a 10-minute grace threshold. |
| BUG-02 | `compute_overtime` | Overnight shifts may be calculated incorrectly when the shift crosses midnight. | High | Added handling for overnight shifts by adjusting the expected shift end to the following day when necessary. |
| BUG-03 | Employee listing and pagination | Incorrect pagination offsets or filtered counts can return incomplete or misleading results. | Medium | Reviewed pagination and filtering logic to use a 1-based page number and calculate the offset using `(page - 1) * page_size`. |
| BUG-04 | `punch_in` | Concurrent or repeated punch-in requests may create duplicate attendance records for the same employee and date. | Critical | Added a compound unique index on `emp_code` and `date`, with duplicate-key handling that returns HTTP 409. |
| BUG-05 | `list_attendance` | Loading all matching attendance records into Python before sorting and pagination can consume excessive memory for large datasets. | High | Used MongoDB sorting, skipping, and limiting to process paginated results at the database level. |

## 2. Root Cause and Edge Case Analysis

### A. Timezone Handling

**Root cause:** Incoming timestamps are provided as epoch milliseconds. Comparing UTC timestamps directly with local shift times can produce incorrect late-arrival calculations.

**Resolution:** The implementation converts timestamps and uses a UTC+05:30 offset for IST-based date extraction and shift-time comparisons. A 10-minute grace threshold is applied when calculating late arrivals.

**Further verification:** Confirm the expected treatment of the grace period and test timestamps around midnight.

### B. Race Conditions in Attendance Logging

**Root cause:** A check-then-insert approach can allow concurrent requests to attempt to create attendance records for the same employee and date.

**Resolution:** A compound unique index on `(emp_code, date)` prevents duplicate records for the same employee and date. Duplicate-key errors are handled to return HTTP 409 Conflict.

### C. Overnight Shifts

**Root cause:** Shifts that cross midnight require the expected shift end to be interpreted as occurring on the following day.

**Resolution:** The implementation adjusts the expected end time for overnight shifts when the shift end is less than or equal to the shift start.

**Further verification:** Test overnight shifts, including punch-out times around midnight.

### D. Pagination and Query Efficiency

**Root cause:** Incorrect pagination offsets can skip records, while fetching all matching records before sorting and slicing can increase memory usage.

**Resolution:** Pagination uses the offset `(page - 1) * page_size`. Attendance listing delegates sorting, skipping, and limiting to MongoDB.

**Further verification:** Confirm employee-list pagination, filtered counts, and behavior with large datasets.

## 3. Verification Performed

The following behaviors were tested through the local FastAPI Swagger interface:

| Test | Observed Result |
|---|---|
| Health endpoint | HTTP 200 |
| Employee registration | HTTP 201 for a new employee |
| Duplicate employee registration | HTTP 409 |
| Attendance punch-in | HTTP 201 |
| Attendance punch-out | HTTP 200 |
| Duplicate punch-in for the same employee and date | HTTP 409 |
| Punch-out without an active punch-in | HTTP 400 |
| Attendance filtering and pagination | HTTP 200 |
| Monthly employee analytics | HTTP 200 with expected values for the test record |
| Department attendance summary | HTTP 200 |
| Late-arrival leaderboard | HTTP 200 |
| Department attendance trend | HTTP 200 |
| Manual attendance correction | HTTP 200 |
| Audit history after manual correction | Previous and subsequent correction details preserved |
| MongoDB explain endpoint | HTTP 200; the query plan showed an index scan |

## 4. Remaining Checks

- Verify the grace-period calculation against the required business rules.
- Test overnight shifts and date-boundary cases.
- Verify employee pagination and filtered result counts.
- Validate attendance statuses, timestamps, correction reasons, and pagination parameters.
- Compare the implementation with all business rules specified in `openapi.yaml`.
- Test analytics and query performance against a larger dataset.

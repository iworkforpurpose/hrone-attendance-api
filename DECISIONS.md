# Implementation decisions

1. **Indexes.** Employees: unique emp_code, department/emp_code, joined_on/department/emp_code, department/joined_on/emp_code. Attendance: unique emp_code/date, date/emp_code, status/date/emp_code, emp_code/status/date, emp_code/punch_in/date. These support list ordering, closure selection and indexed analytics lookups. A status-only index was rejected because it cannot supply listing order. Startup preserves seeded documents.

2. **Punch-in race.** Both requests read the employee and calculate the same IST date, then insert. MongoDB's compound unique index accepts one and rejects the other: 201 and 409 across processes. Closures and corrections conditionally match original fields and history length; stale writers get 409 without retry. Accepted corrections append history atomically, including protection against fields changed then restored.

3. **Ties.** MongoDB ranks totals only, producing 1,2,2,4. Filtering rank <= limit returns every tied employee, potentially more rows than limit. Employee code orders ties afterward. Department filtering precedes ranking.

4. **Headcount.** Department aggregation starts with employees joined by month end. Empty indexed log lookups keep employees with zero totals; grouping counts them and ignores orphan logs. Summed qualifying hours divided by record count gives the record-weighted mean. Trend headcount evaluates joining dates daily.

5. **100x data.** Proposed: benchmark workload-specific indexes and partitioning with executionStats before adding overhead. Current verification uses 100000 logs; larger-scale behavior is not claimed.

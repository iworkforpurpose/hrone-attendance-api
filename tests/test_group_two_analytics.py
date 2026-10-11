"""Real HTTP/MongoDB evidence for monthly and department analytics."""
import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import time

import pytest

from conftest import employee

MONTH = '2026-07'
MONTHLY = '/analytics/employees/EMP0001/monthly'
SUMMARY = '/analytics/departments/summary'


def clear(db):
    assert db.name.startswith('candidate_kit_runtime_audit_')
    db.employees.delete_many({})
    db.attendance_logs.delete_many({})


def add_employee(db, code='EMP0001', **changes):
    db.employees.insert_one({**employee(code, **changes), 'created_at': datetime(2026, 1, 1, tzinfo=timezone.utc)})


def add_log(db, code='EMP0001', day='2026-07-06', status='PRESENT', **changes):
    # Intentionally omit punches: analytics are defined over stored metrics.
    db.attendance_logs.insert_one({'emp_code': code, 'date': day, 'status': status,
        'work_hours': 8.0, 'late_minutes': 0, 'overtime_minutes': 0, 'half_day': False, **changes})


def monthly(http, code='EMP0001', month=MONTH):
    r = http.get(f'/analytics/employees/{code}/monthly', params={'month': month})
    assert r.status_code == 200, r.text
    return r.json()


def summary(http, month=MONTH, **filters):
    r = http.get(SUMMARY, params={'month': month, **filters})
    assert r.status_code == 200, r.text
    return r.json()


def empty_month(code='EMP0001', month=MONTH, working=23):
    return {'emp_code': code, 'month': month, 'working_days': working, 'present_days': 0.0,
        'leave_days': 0, 'late_count': 0, 'total_late_minutes': 0, 'total_overtime_minutes': 0,
        'attendance_pct': 0.0 if working else None}


def empty_department(name='Engineering', headcount=1):
    return {'department': name, 'headcount': headcount, 'present_days': 0.0,
        'avg_work_hours': None, 'late_count': 0, 'total_late_minutes': 0, 'leave_count': 0, 'on_duty_count': 0}


@pytest.mark.parametrize('path', [MONTHLY, SUMMARY])
@pytest.mark.parametrize('value', ['', '2026', '2026-7', '2026-00', '2026-13', '0000-01',
    '10000-01', '2026-07-01', '2026-07 ', ' 2026-07', '2026/07', 'abcd-07'])
def test_invalid_month_returns_422(http, path, value):
    r = http.get(path, params={'month': value})
    assert r.status_code == 422 and 'detail' in r.json(), r.text


@pytest.mark.parametrize('path', [MONTHLY, SUMMARY])
def test_month_is_required(http, path):
    r = http.get(path)
    assert r.status_code == 422, r.text


def test_unknown_employee_returns_404_and_unknown_department_empty(http):
    r = http.get('/analytics/employees/EMP9999/monthly', params={'month': MONTH})
    assert r.status_code == 404 and 'detail' in r.json()
    assert summary(http, department='Missing') == {'month': MONTH, 'items': []}


@pytest.mark.parametrize('code,expected', [
    ('EMP0001', {'working_days': 23, 'present_days': 2.0, 'attendance_pct': 8.70}),
    ('EMP0002', {'working_days': 15, 'present_days': 1.0, 'attendance_pct': 6.67}),
    ('EMP0003', {'working_days': 23, 'present_days': 1.0, 'leave_days': 1,
        'late_count': 1, 'total_late_minutes': 35, 'total_overtime_minutes': 40, 'attendance_pct': 4.35}),
    ('EMP0004', {'working_days': 23, 'present_days': .5, 'attendance_pct': 2.17}),
    ('EMP0005', {'working_days': 23, 'present_days': 1.0, 'total_overtime_minutes': 40, 'attendance_pct': 4.35}),
    ('EMP0006', {'working_days': 23, 'present_days': 1.0, 'attendance_pct': 4.35}),
])
def test_supplied_employee_monthly_shapes_and_values(http, code, expected):
    assert monthly(http, code) == {**empty_month(code), **expected}


def test_supplied_department_summary_shapes_and_values(http):
    assert summary(http) == {'month': MONTH, 'items': [
        {**empty_department('Engineering', 2), 'present_days': 3.0, 'avg_work_hours': 9.04},
        {**empty_department('Sales', 2), 'present_days': 1.5, 'avg_work_hours': 6.29,
         'late_count': 1, 'total_late_minutes': 35, 'leave_count': 1},
        {**empty_department('Support', 2), 'present_days': 2.0, 'avg_work_hours': 8.75},
    ]}


@pytest.mark.parametrize('joined,working', [('2026-01-01', 23), ('2026-07-01', 23),
    ('2026-07-13', 15), ('2026-07-11', 15), ('2026-07-31', 1),
    ('2026-08-01', 0), ('2027-01-01', 0)])
def test_working_days_and_no_log_employee_headcount(http, db, joined, working):
    clear(db)
    add_employee(db, joined_on=joined)
    assert monthly(http) == empty_month(working=working)
    expected = [empty_department()] if joined <= '2026-07-31' else []
    assert summary(http) == {'month': MONTH, 'items': expected}


@pytest.mark.parametrize('month,joined,working', [('2028-02', '2028-02-01', 21),
    ('2027-02', '2027-02-01', 20), ('2026-12', '2026-12-31', 1),
    ('2027-01', '2027-01-30', 0), ('2026-08', '2026-08-01', 21),
    ('0001-01', '0001-01-01', 23), ('9999-12', '9999-12-01', 23)])
def test_calendar_boundaries(http, db, month, joined, working):
    clear(db)
    add_employee(db, joined_on=joined)
    # Expected calendars verified by a standard-library independent oracle.
    first = date.fromisoformat(month + '-01')
    expected = sum(date(first.year, first.month, day).weekday() < 5 and
        date(first.year, first.month, day).isoformat() >= joined
        for day in range(1, calendar.monthrange(first.year, first.month)[1] + 1))
    assert expected == working
    assert monthly(http, month=month) == empty_month(month=month, working=working)
    assert summary(http, month=month)['items'] == [empty_department()]


@pytest.mark.parametrize('status', ['PRESENT', 'WFH', 'ON_DUTY', 'ABSENT', 'LEAVE'])
@pytest.mark.parametrize('weekend', [False, True])
@pytest.mark.parametrize('half', [False, True])
def test_status_weekend_and_stored_half_day_rules(http, db, status, weekend, half):
    clear(db)
    add_employee(db)
    day = '2026-07-11' if weekend else '2026-07-06'
    add_log(db, day=day, status=status, half_day=half, late_minutes=17, overtime_minutes=31)
    presence = status in ('PRESENT', 'WFH', 'ON_DUTY')
    present = (0.5 if half else 1.0) if presence and not weekend else 0.0
    pct = float((Decimal(str(present)) / 23 * 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
    assert monthly(http) == {**empty_month(), 'present_days': present, 'leave_days': int(status == 'LEAVE'),
        'late_count': 1, 'total_late_minutes': 17, 'total_overtime_minutes': 31, 'attendance_pct': pct}
    assert summary(http)['items'] == [{**empty_department(), 'present_days': present,
        'avg_work_hours': 8.0 if presence else None, 'late_count': 1,
        'total_late_minutes': 17, 'leave_count': int(status == 'LEAVE'), 'on_duty_count': int(status == 'ON_DUTY')}]


def test_analytics_ignore_punches_and_use_missing_legacy_defaults(http, db):
    clear(db)
    add_employee(db)
    db.attendance_logs.insert_many([
        {'emp_code': 'EMP0001', 'date': '2026-07-06', 'status': 'PRESENT', 'work_hours': 9.99,
         'punch_in': datetime(2026,7,6,4,tzinfo=timezone.utc), 'punch_out': datetime(2026,7,6,5,tzinfo=timezone.utc)},
        {'emp_code': 'EMP0001', 'date': '2026-07-07', 'status': 'WFH'},
        {'emp_code': 'EMP0001', 'date': '2026-07-08', 'status': 'LEAVE'},
        {'emp_code': 'EMP0001', 'date': '2026-07-09', 'status': 'ABSENT'},
    ])
    before = list(db.attendance_logs.find())
    assert monthly(http) == {**empty_month(), 'present_days': 2.0, 'leave_days': 1, 'attendance_pct': 8.70}
    assert summary(http)['items'] == [{**empty_department(), 'present_days': 2.0, 'avg_work_hours': 9.99, 'leave_count': 1}]
    assert list(db.attendance_logs.find()) == before


def test_department_mean_is_record_weighted_and_no_log_people_still_count(http, db):
    clear(db)
    for code in ('EMP0001', 'EMP0002', 'EMP0003'):
        add_employee(db, code)
    add_log(db, work_hours=2.0)
    for day in ('2026-07-07', '2026-07-08', '2026-07-09'):
        add_log(db, 'EMP0002', day, work_hours=8.0)
    # Average (2+8+8+8)/4 = 6.5; employee averages would wrongly produce 5.
    assert summary(http)['items'] == [{**empty_department(headcount=3), 'present_days': 4.0, 'avg_work_hours': 6.5}]


@pytest.mark.parametrize('hours,expected', [([2.67, 2.68], 2.68), ([0.0, .01], .01),
    ([4.49, 4.50], 4.50), ([9.03, 9.04], 9.04), ([2.0], 2.0)])
def test_department_mean_half_up_ties(http, db, hours, expected):
    clear(db)
    add_employee(db)
    for i, value in enumerate(hours):
        add_log(db, day=f'2026-07-{6+i:02d}', work_hours=value)
    assert summary(http)['items'][0]['avg_work_hours'] == expected


def test_work_hours_mean_excludes_absence_leave_and_null_but_includes_weekend_zero(http, db):
    clear(db)
    add_employee(db)
    add_log(db, day='2026-07-06', work_hours=None)
    add_log(db, day='2026-07-07', status='ABSENT', work_hours=99)
    add_log(db, day='2026-07-08', status='LEAVE', work_hours=99)
    add_log(db, day='2026-07-11', status='WFH', work_hours=0.0)
    add_log(db, day='2026-07-12', status='ON_DUTY', work_hours=8.0)
    assert summary(http)['items'] == [{**empty_department(), 'present_days': 1.0,
        'avg_work_hours': 4.0, 'leave_count': 1, 'on_duty_count': 1}]


def test_month_edges_missing_weekdays_prejoin_records_and_orphans(http, db):
    clear(db)
    add_employee(db, joined_on='2026-07-13')
    add_log(db, day='2026-06-30', late_minutes=999, overtime_minutes=999)
    add_log(db, day='2026-08-01', late_minutes=999, overtime_minutes=999)
    add_log(db, day='2026-07-01', work_hours=4.0, half_day=True, late_minutes=10, overtime_minutes=30)
    add_log(db, day='2026-07-31', work_hours=8.0, late_minutes=20, overtime_minutes=40)
    add_log(db, 'EMP9999', '2026-07-06', late_minutes=999, overtime_minutes=999)
    assert monthly(http) == {**empty_month(working=15), 'present_days': 1.5, 'attendance_pct': 10.0,
        'late_count': 2, 'total_late_minutes': 30, 'total_overtime_minutes': 70}
    assert summary(http)['items'] == [{**empty_department(), 'present_days': 1.5,
        'avg_work_hours': 6.0, 'late_count': 2, 'total_late_minutes': 30}]


def test_department_eligibility_exact_filter_order_and_zero_headcount_omission(http, db):
    clear(db)
    for code, department, joined in [('EMP0001','zeta','2026-01-01'),
        ('EMP0002','Alpha','2026-07-31'), ('EMP0003','alpha','2026-07-01'),
        ('EMP0004','Future','2026-08-01')]:
        add_employee(db, code, department=department, joined_on=joined)
    add_log(db, 'EMP0004')
    assert summary(http)['items'] == [empty_department(name) for name in ('Alpha','alpha','zeta')]
    assert summary(http, department='Alpha')['items'] == [empty_department('Alpha')]
    assert summary(http, department='ALPHA')['items'] == []
    assert summary(http, department='')['items'] == []
    assert summary(http, department='Future')['items'] == []


def test_entire_empty_collections_and_orphan_logs(http, db):
    clear(db)
    assert summary(http) == {'month': MONTH, 'items': []}
    add_log(db, 'EMP9999')
    assert summary(http) == {'month': MONTH, 'items': []}
    r = http.get(MONTHLY, params={'month': MONTH})
    assert r.status_code == 404


def test_percentage_half_up_tie_and_missing_weekdays_are_not_present(http, db):
    clear(db)
    # Joining July 10 leaves 16 working days. Half a day / 16 * 100 = 3.125.
    add_employee(db, joined_on='2026-07-10')
    add_log(db, day='2026-07-10', half_day=True)
    assert monthly(http) == {**empty_month(working=16), 'present_days': .5, 'attendance_pct': 3.13}


@pytest.mark.parametrize('month', [f'2026-{number:02d}' for number in range(1,13)])
@pytest.mark.parametrize('join_day', [1, 15, 'last'])
def test_every_month_full_partial_and_last_day_calendar(http, db, month, join_day):
    clear(db)
    first = date.fromisoformat(month+'-01')
    days = calendar.monthrange(first.year,first.month)[1]
    joined = f'{month}-{days if join_day=="last" else join_day:02d}'
    add_employee(db, joined_on=joined)
    expected = sum(date(first.year,first.month,day).weekday()<5 and
        f'{month}-{day:02d}'>=joined for day in range(1,days+1))
    assert monthly(http,month=month) == empty_month(month=month,working=expected)
    assert summary(http,month=month)['items'] == [empty_department()]


def test_zero_working_days_with_logs_keeps_null_percentage_and_excludes_future_headcount(http, db):
    clear(db)
    add_employee(db,joined_on='2026-08-01')
    add_log(db)
    assert monthly(http) == {**empty_month(working=0),'present_days':1.0}
    assert summary(http)['items'] == []


def test_month_filters_use_attendance_day_for_overnight_records(http, db):
    clear(db)
    add_employee(db,shift_start='22:00',shift_end='06:00')
    add_log(db,day='2026-07-31',work_hours=8.5,late_minutes=22,overtime_minutes=30,
        punch_in=datetime(2026,7,31,16,30,tzinfo=timezone.utc),
        punch_out=datetime(2026,8,1,1,tzinfo=timezone.utc))
    assert monthly(http) == {**empty_month(),'present_days':1.0,'attendance_pct':4.35,
        'late_count':1,'total_late_minutes':22,'total_overtime_minutes':30}
    assert monthly(http,month='2026-08') == empty_month(month='2026-08',working=21)
    assert summary(http)['items'][0]['avg_work_hours']==8.5


def test_read_only_analytics_reflect_new_corrections_without_rewriting_other_records(http, db):
    before={name:list(db[name].find().sort('_id',1)) for name in ('employees','attendance_logs')}
    r=http.patch('/attendance/EMP0004/2026-07-07',json={'status':'LEAVE',
        'reason':'Correct attendance before monthly reporting','regularized_by':'Audit Manager'})
    assert r.status_code==200,r.text
    corrected=db.attendance_logs.find_one({'emp_code':'EMP0004','date':'2026-07-07'})
    assert monthly(http,'EMP0004') == {**empty_month('EMP0004'),'leave_days':1}
    sales=summary(http,department='Sales')['items'][0]
    assert sales['present_days']==1.0 and sales['leave_count']==2 and sales['avg_work_hours']==9.08
    assert db.attendance_logs.find_one({'_id':corrected['_id']}) == corrected
    assert list(db.employees.find().sort('_id',1)) == before['employees']
    for old in before['attendance_logs']:
        if old['_id']!=corrected['_id']:
            assert db.attendance_logs.find_one({'_id':old['_id']})==old


def test_100k_pipelines_use_root_and_lookup_indexes_and_transfer_summaries_only(http, db, helpers, record_testsuite_property):
    clear(db)
    start = date(2026,1,1)
    codes = [f'EMP{100000+i}' for i in range(1000)]
    db.employees.insert_many([{**employee(code, department='Engineering' if i%2==0 else 'Sales'),
        'created_at': datetime(2026,1,1,tzinfo=timezone.utc)} for i,code in enumerate(codes)])
    for i in range(100):
        day = (start + timedelta(days=i)).isoformat()
        db.attendance_logs.insert_many([{'emp_code': code, 'date': day, 'status': 'PRESENT',
            'work_hours': 8.0, 'late_minutes': 10, 'overtime_minutes': 30} for code in codes])
    assert db.attendance_logs.count_documents({}) == 100000
    operations = [
        ('employee_monthly', *helpers.employee_monthly_pipeline(codes[0],'2026-03')),
        ('department_summary_all', *helpers.department_summary_pipeline('2026-03')),
        ('department_summary_filtered', *helpers.department_summary_pipeline('2026-03','Engineering')),
    ]
    for label,pipeline,hint in operations:
        explanation = db.command('explain', {'aggregate':'employees','pipeline':pipeline,
            'cursor':{},'hint':hint}, verbosity='executionStats')
        assert 'COLLSCAN' not in str(explanation), explanation
        assert 'IXSCAN' in str(explanation), explanation
        lookup = next(stage for stage in explanation['stages'] if '$lookup' in stage)
        assert lookup['collectionScans'] == 0 and 'attendance_employee_date_unique' in lookup['indexesUsed'], lookup
        record_testsuite_property(label+'_lookup_collection_scans',lookup['collectionScans'])
        record_testsuite_property(label+'_lookup_documents_examined',lookup['totalDocsExamined'])
        # The exact real pipeline's cursor returns only the final summary rows.
        db['system.profile'].drop()
        db.command('profile',2)
        before = time.monotonic()
        try:
            response = monthly(http,codes[0],'2026-03') if label=='employee_monthly' else summary(http,'2026-03',
                **({'department':'Engineering'} if label.endswith('filtered') else {}))
        finally:
            db.command('profile',0)
        elapsed = time.monotonic()-before
        if label=='employee_monthly':
            assert response == {**empty_month(codes[0],'2026-03',22), 'present_days':22.0,
                'attendance_pct':100.0,'late_count':31,'total_late_minutes':310,'total_overtime_minutes':930}
        else:
            names = ['Engineering'] if label.endswith('filtered') else ['Engineering','Sales']
            assert response['items'] == [{**empty_department(name,500), 'present_days':11000.0,
                'avg_work_hours':8.0,'late_count':15500,'total_late_minutes':155000} for name in names]
        cursor_reads = list(db['system.profile'].find({'ns':db.name+'.employees',
            'op':{'$in':['command','getmore']}, '$or':[{'command.aggregate':'employees'}, {'command.getMore':{'$exists':True}}]}))
        assert cursor_reads
        # Clear only the profiler's captured command entries between operations.
        transferred = sum(entry.get('nreturned',0) for entry in cursor_reads)
        assert transferred <= (1 if label!='department_summary_all' else 2), cursor_reads
        db['system.profile'].drop()
        record_testsuite_property(label+'_http_seconds',f'{elapsed:.3f}')

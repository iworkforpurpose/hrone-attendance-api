"""Real HTTP/MongoDB leaderboard, daily trend and executionStats evidence."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import time
from urllib.parse import quote

import pytest
from bson import json_util

from conftest import employee
from test_group_two_analytics import add_employee, add_log, clear

LEADER = '/analytics/leaderboard/late'
TREND = '/analytics/departments/Engineering/trend'
FROM = '2026-07-06'
TO = '2026-07-15'


def leaderboard(http, month='2026-07', **filters):
    r = http.get(LEADER, params={'month': month, **filters})
    assert r.status_code == 200, r.text
    return r.json()


def trend(http, department='Engineering', date_from=FROM, date_to=TO):
    r = http.get(f'/analytics/departments/{quote(department,safe="")}/trend', params={'from': date_from,'to':date_to})
    assert r.status_code == 200, r.text
    return r.json()


def explain(http, name, **params):
    r = http.get('/admin/explain/'+name, params=params)
    assert r.status_code == 200, r.text
    result = r.json()
    assert set(result) == {'endpoint','collection','explain'} and result['endpoint']==name
    assert result['explain']['ok']==1 and 'executionStats' in str(result['explain'])
    return result


def round4(value):
    return float(value.quantize(Decimal('.0001'),rounding=ROUND_HALF_UP)) if value is not None else None


def expected_rows(date_from, date_to, employees, logs):
    # Independent test-only oracle; the service performs this work in MongoDB.
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    rows=[]
    for offset in range((end-start).days+1):
        day=start+timedelta(days=offset)
        headcount=sum(joined<=day.isoformat() for joined in employees.values())
        daily=[log for log in logs if log['emp_code'] in employees and log['date']==day.isoformat()]
        present=sum(.5 if log.get('half_day',False) else 1.0 for log in daily if log['status'] in ('PRESENT','WFH','ON_DUTY'))
        late=sum(log.get('late_minutes',0)>0 for log in daily)
        rate=round4(Decimal(str(present))/headcount) if day.weekday()<5 and headcount else None
        rows.append({'date':day.isoformat(),'is_working_day':day.weekday()<5,'headcount':headcount,
            'present_count':present,'late_count':late,'attendance_rate':rate})
        window=[Decimal(str(row['attendance_rate'])) for row in rows[-7:] if row['attendance_rate'] is not None]
        rows[-1]['moving_avg_7d']=round4(sum(window)/len(window)) if window else None
    return rows


@pytest.mark.parametrize('path', [LEADER,'/admin/explain/late_leaderboard'])
@pytest.mark.parametrize('value', ['','2026-7','2026-13','0000-01','2026-07-01'])
def test_leaderboard_month_validation(http,path,value):
    r=http.get(path,params={'month':value})
    assert r.status_code==422 and 'detail' in r.json(),r.text


@pytest.mark.parametrize('path', [LEADER,'/admin/explain/late_leaderboard'])
@pytest.mark.parametrize('value', [0,-1,51,'bad',1.5])
def test_leaderboard_limit_validation(http,path,value):
    r=http.get(path,params={'month':'2026-07','limit':value})
    assert r.status_code==422,r.text


def test_supplied_leaderboard_and_trends(http,db):
    assert leaderboard(http)=={'month':'2026-07','items':[{'rank':1,'emp_code':'EMP0003','name':'Neha Iyer',
        'department':'Sales','total_late_minutes':35,'late_count':1}]}
    for department in ('Engineering','Sales','Support'):
        employees={doc['emp_code']:doc['joined_on'] for doc in db.employees.find({'department':department})}
        assert trend(http,department)['items']==expected_rows(FROM,TO,employees,list(db.attendance_logs.find()))


@pytest.mark.parametrize('limit,expected_ranks', [(1,[1]),(2,[1,2,2]),(3,[1,2,2]),(4,[1,2,2,4]),(50,[1,2,2,4])])
def test_competition_ranks_and_ties_at_cutoff(http,db,limit,expected_ranks):
    clear(db)
    for code,total in reversed([('EMP0001',100),('EMP0002',80),('EMP0003',80),('EMP0004',40)]):
        add_employee(db,code,name='Name '+code)
        add_log(db,code,late_minutes=total)
    items=leaderboard(http,limit=limit)['items']
    assert [r['rank'] for r in items]==expected_ranks
    assert [r['emp_code'] for r in items]==['EMP0001','EMP0002','EMP0003','EMP0004'][:len(expected_ranks)]
    assert all(set(r)=={'rank','emp_code','name','department','total_late_minutes','late_count'} for r in items)


def test_all_top_ties_are_returned_above_row_limit(http,db):
    clear(db)
    for i in range(60):
        code=f'EMP{1000+i:04d}'
        add_employee(db,code)
        add_log(db,code,late_minutes=10)
    items=leaderboard(http,limit=1)['items']
    assert len(items)==60 and all(r['rank']==1 for r in items)
    assert [r['emp_code'] for r in items]==sorted(r['emp_code'] for r in items)


def test_department_filter_precedes_ranking_and_is_exact(http,db):
    clear(db)
    for code,department,total in [('EMP0001','Sales',100),('EMP0002','Engineering',20),('EMP0003','Engineering',10)]:
        add_employee(db,code,department=department)
        add_log(db,code,late_minutes=total)
    rows=leaderboard(http,department='Engineering',limit=1)['items']
    assert len(rows)==1 and rows[0]['emp_code']=='EMP0002' and rows[0]['rank']==1
    assert leaderboard(http,department='engineering')['items']==[]
    assert leaderboard(http,department='')['items']==[]


def test_leaderboard_stored_totals_status_weekend_month_and_orphan_rules(http,db):
    clear(db)
    add_employee(db,joined_on='2027-01-01')
    add_employee(db,'EMP0002')
    add_employee(db,'EMP0003')
    for day,status,late in [('2026-07-01','PRESENT',10),('2026-07-11','WFH',20),
        ('2026-07-12','ON_DUTY',30),('2026-07-30','ABSENT',40),('2026-07-31','LEAVE',50)]:
        add_log(db,day=day,status=status,late_minutes=late)
    add_log(db,day='2026-06-30',late_minutes=999)
    add_log(db,day='2026-08-01',late_minutes=999)
    add_log(db,'EMP9999',late_minutes=999)
    add_log(db,'EMP0002',late_minutes=0)
    add_log(db,'EMP0003',late_minutes=0)
    db.attendance_logs.update_one({'emp_code':'EMP0003'},{'$unset':{'late_minutes':''}})
    rows=leaderboard(http)['items']
    assert len(rows)==1 and rows[0]['total_late_minutes']==150 and rows[0]['late_count']==5


def test_empty_leaderboard_and_missing_month(http,db):
    clear(db)
    assert leaderboard(http)['items']==[]
    add_employee(db)
    assert leaderboard(http)['items']==[]
    assert http.get(LEADER).status_code==422


@pytest.mark.parametrize('params', [{},{'from':FROM},{'to':TO},{'date_from':FROM,'date_to':TO},
    {'from':'2026-02-30','to':TO},{'from':'2026-7-06','to':TO},
    {'from':TO,'to':FROM},{'from':'2026-01-01','to':'2026-04-03'}])
def test_trend_range_validation(http,params):
    r=http.get(TREND,params=params)
    assert r.status_code==422 and 'detail' in r.json(),r.text


def test_unknown_department_returns_404_even_with_orphan_logs(http,db):
    r=http.get('/analytics/departments/Unknown/trend',params={'from':FROM,'to':TO})
    assert r.status_code==404
    clear(db)
    add_log(db,'EMP9999')
    r=http.get(TREND,params={'from':FROM,'to':TO})
    assert r.status_code==404


@pytest.mark.parametrize('first,last', [('2026-07-06','2026-07-15'),('2026-07-11','2026-07-12'),
    ('2026-07-06','2026-07-06'),('2026-01-01','2026-04-02'),
    ('2028-02-28','2028-03-01'),('2026-12-31','2027-01-02'),
    ('0001-01-01','0001-01-03'),('9999-12-29','9999-12-31')])
def test_empty_range_gap_filling_and_calendar_extremes(http,db,first,last):
    clear(db)
    add_employee(db,joined_on=first)
    rows=trend(http,date_from=first,date_to=last)['items']
    assert rows==expected_rows(first,last,{'EMP0001':first},[])


@pytest.mark.parametrize('first,last',[('0001-01-01','0001-01-03'),('9999-12-29','9999-12-31')])
def test_extreme_calendar_ranges_with_stored_logs(http,db,first,last):
    clear(db)
    add_employee(db,joined_on=first)
    add_log(db,day=first,late_minutes=17)
    assert trend(http,date_from=first,date_to=last)['items']==expected_rows(first,last,
        {'EMP0001':first},list(db.attendance_logs.find()))


@pytest.mark.parametrize('joined', ['2026-07-01','2026-07-08','2026-07-11','2026-07-15','2027-01-01'])
def test_daily_joining_eligibility_with_no_logs(http,db,joined):
    clear(db)
    add_employee(db,joined_on=joined)
    assert trend(http)['items']==expected_rows(FROM,TO,{'EMP0001':joined},[])


@pytest.mark.parametrize('status',['PRESENT','WFH','ON_DUTY','ABSENT','LEAVE'])
@pytest.mark.parametrize('half',[False,True])
def test_presence_and_lateness_on_weekends_and_weekdays(http,db,status,half):
    clear(db)
    add_employee(db)
    for day in ('2026-07-06','2026-07-11','2026-07-12'):
        add_log(db,day=day,status=status,half_day=half,late_minutes=17,work_hours=None)
    assert trend(http)['items']==expected_rows(FROM,TO,{'EMP0001':'2026-01-01'},list(db.attendance_logs.find()))


def test_moving_window_is_seven_calendar_rows_and_starts_inside_range(http,db):
    clear(db)
    add_employee(db)
    # Earlier rows must never enter the window. Weekend presence still has null rate.
    for day in ('2026-07-03','2026-07-06','2026-07-07','2026-07-11','2026-07-13'):
        add_log(db,day=day)
    rows=trend(http,date_to='2026-07-20')['items']
    assert rows==expected_rows(FROM,'2026-07-20',{'EMP0001':'2026-01-01'},list(db.attendance_logs.find()))
    assert rows[0]['moving_avg_7d']==1.0
    assert rows[7]['moving_avg_7d']==.4  # July 7-13: five non-null days, two present.
    assert rows[8]['moving_avg_7d']==.2  # July 8-14: five non-null days, one present.


def test_daily_rates_and_moving_average_use_half_up_and_reported_rates(http,db):
    clear(db)
    for i in range(32):
        add_employee(db,f'EMP{1000+i:04d}')
    add_log(db,'EMP1000',half_day=True)
    rows=trend(http,date_to='2026-07-07')['items']
    assert rows[0]['attendance_rate']==.0156  # .5 / 32 = .015625
    assert rows[1]['moving_avg_7d']==.0078
    # 1 / 32 = .03125 -> .0313, then mean(.0313,0) = .01565 -> .0157.
    db.attendance_logs.update_one({'emp_code':'EMP1000'},{'$set':{'half_day':False}})
    rows=trend(http,date_to='2026-07-07')['items']
    assert rows[0]['attendance_rate']==.0313 and rows[1]['moving_avg_7d']==.0157


def test_orphans_other_departments_legacy_defaults_and_prejoin_logs(http,db):
    clear(db)
    add_employee(db,joined_on='2026-07-08')
    add_employee(db,'EMP0002',department='Sales')
    db.attendance_logs.insert_one({'emp_code':'EMP0001','date':FROM,'status':'PRESENT'})
    add_log(db,'EMP9999')
    add_log(db,'EMP0002')
    expected=expected_rows(FROM,TO,{'EMP0001':'2026-07-08'},list(db.attendance_logs.find()))
    assert trend(http)['items']==expected
    assert expected[0]['present_count']==1 and expected[0]['headcount']==0 and expected[0]['attendance_rate'] is None


def test_mixed_daily_headcount_and_half_days_change_denominator(http,db):
    clear(db)
    for code,joined in [('EMP0001','2026-01-01'),('EMP0002','2026-07-08'),('EMP0003','2026-07-13'),('EMP0004','2027-01-01')]:
        add_employee(db,code,joined_on=joined)
    add_log(db,day='2026-07-06',half_day=True)
    add_log(db,'EMP0002',day='2026-07-08',status='ON_DUTY',half_day=True)
    add_log(db,'EMP0003',day='2026-07-13',status='WFH')
    employees={doc['emp_code']:doc['joined_on'] for doc in db.employees.find()}
    before=list(db.attendance_logs.find())
    rows=trend(http)['items']
    assert rows==expected_rows(FROM,TO,employees,before)
    assert rows[0]['headcount']==1 and rows[0]['attendance_rate']==.5
    assert rows[2]['headcount']==2 and rows[2]['attendance_rate']==.25
    assert rows[7]['headcount']==3 and rows[7]['attendance_rate']==.3333
    assert list(db.attendance_logs.find())==before


def test_overnight_month_boundary_uses_stored_attendance_day(http,db):
    clear(db)
    add_employee(db,shift_start='22:00',shift_end='06:00')
    add_log(db,day='2026-07-31',late_minutes=40,half_day=True,
        punch_in=datetime(2026,7,31,16,30,tzinfo=timezone.utc),punch_out=datetime(2026,8,1,1,tzinfo=timezone.utc))
    rows=trend(http,date_from='2026-07-31',date_to='2026-08-01')['items']
    assert rows[0]['present_count']==.5 and rows[0]['late_count']==1
    assert rows[1]['present_count']==0 and rows[1]['late_count']==0
    assert leaderboard(http)['items'][0]['total_late_minutes']==40
    assert leaderboard(http,'2026-08')['items']==[]


def test_leaderboard_and_trend_reflect_accepted_correction_and_are_read_only(http,db):
    corrected=http.patch('/attendance/EMP0003/2026-07-06',json={'status':'LEAVE',
        'reason':'Remove incorrectly recorded presence','regularized_by':'Audit Manager'})
    assert corrected.status_code==200,corrected.text
    before={name:list(db[name].find().sort('_id',1)) for name in ('employees','attendance_logs')}
    assert leaderboard(http)['items']==[]
    rows=trend(http,'Sales')['items']
    assert rows[0]['present_count']==0 and rows[0]['late_count']==0
    assert {name:list(db[name].find().sort('_id',1)) for name in before}==before


@pytest.mark.parametrize('department',['R&D North','भारत','Support/Remote','$Special'])
def test_exact_department_paths_support_special_names(http,db,department):
    clear(db)
    add_employee(db,department=department)
    assert trend(http,department)['items']==expected_rows(FROM,TO,{'EMP0001':'2026-01-01'},[])


@pytest.mark.parametrize('name,params', [('attendance_list',{}),('employee_monthly',{'emp_code':'EMP0001','month':'2026-07'}),
    ('department_summary',{'month':'2026-07'}),('late_leaderboard',{'month':'2026-07','limit':1}),
    ('department_trend',{'department':'Engineering','from':FROM,'to':TO})])
def test_explain_all_supported_operations_preserves_raw_stats(http,name,params):
    result=explain(http,name,**params)
    assert result['collection']==('attendance_logs' if name=='attendance_list' else 'employees')
    assert 'IXSCAN' in str(result['explain']) and 'COLLSCAN' not in str(result['explain'])


@pytest.mark.parametrize('name,params', [('bad',{}),('employee_monthly',{}),('employee_monthly',{'month':'2026-07'}),
    ('employee_monthly',{'emp_code':'EMP0001'}),('department_summary',{}),('late_leaderboard',{}),
    ('department_trend',{}),('department_trend',{'department':'Engineering','from':FROM}),
    ('department_trend',{'department':'Engineering','to':TO}),('department_trend',{'from':FROM,'to':TO}),
    ('department_trend',{'department':'Engineering','from':TO,'to':FROM}),
    ('attendance_list',{'page':0}),('attendance_list',{'page_size':101}),
    ('attendance_list',{'date_from':TO,'date_to':FROM}),('attendance_list',{'status':'BAD'}),
    ('employee_monthly',{'emp_code':'EMP0001','month':'2026-13'})])
def test_explain_validation_returns_422(http,name,params):
    r=http.get('/admin/explain/'+name,params=params)
    assert r.status_code==422 and 'detail' in r.json(),r.text


@pytest.mark.parametrize('path,base',[(TREND,{}),('/admin/explain/department_trend',{'department':'Engineering'})])
@pytest.mark.parametrize('field,value',[('from','2026-02-30'),('from','2026-7-06'),('to','2026-02-30'),
    ('to','2026-7-15'),('from','0000-01-01'),('to','10000-01-01')])
def test_trend_aliases_keep_calendar_validation_and_return_422(http,path,base,field,value):
    r=http.get(path,params={**base,'from':FROM,'to':TO,field:value})
    assert r.status_code==422 and 'detail' in r.json(),r.text


@pytest.mark.parametrize('params',[{'department':'Engineering','from':'2026-01-01','to':'2026-04-03'},
    {'department':'Engineering','from':TO,'to':FROM}])
def test_explain_trend_range_validation(http,params):
    assert http.get('/admin/explain/department_trend',params=params).status_code==422


@pytest.mark.parametrize('params',[{'date_from':'2026-02-30'},{'date_to':'2026-7-06'},
    {'page_size':0},{'page':-1}])
def test_attendance_explain_keeps_shared_validation(http,params):
    assert http.get('/admin/explain/attendance_list',params=params).status_code==422


@pytest.mark.parametrize('name,params',[('employee_monthly',{'emp_code':'EMP9999','month':'2026-07'}),
    ('department_trend',{'department':'Unknown','from':FROM,'to':TO})])
def test_explain_reports_valid_operations_even_without_matching_resources(http,name,params):
    result=explain(http,name,**params)
    assert result['collection']=='employees'


@pytest.mark.parametrize('params',[{'page':2,'page_size':2},{'emp_code':'EMP0001','status':'PRESENT','date_from':FROM,'date_to':TO},
    {'emp_code':''},{'page':10**30,'page_size':100}])
def test_attendance_explain_matches_real_find_filters_sort_pagination_and_hint(http,db,helpers,params):
    db['system.profile'].drop()
    db.command('profile',2)
    try:
        live=http.get('/attendance',params=params)
        assert live.status_code==200
    finally:
        db.command('profile',0)
    raw=json_util.loads(json.dumps(explain(http,'attendance_list',**params)['explain']))
    command=raw['command']
    # Standalone MongoDB explain nests the find command below "explain".
    operation=command.get('explain',command)
    query,sort,hint=helpers.attendance_list_query(params.get('emp_code'),params.get('date_from'),params.get('date_to'),params.get('status'))
    expected=helpers.page_find_operation('attendance_logs',query,sort,hint,params.get('page',1),params.get('page_size',20))
    for field,value in expected.items():
        assert operation[field]==value,(field,operation)
    reads=list(db['system.profile'].find({'command.find':'attendance_logs'}))
    if reads:
        for field in ('filter','projection','sort','hint','limit'):
            assert reads[-1]['command'][field]==expected[field]
        assert reads[-1]['command'].get('skip',0)==expected['skip']


@pytest.mark.parametrize('name,params,builder',[
    ('employee_monthly',{'emp_code':'EMP0002','month':'2026-07'},'employee_monthly_pipeline'),
    ('department_summary',{'month':'2026-07','department':'Sales'},'department_summary_pipeline'),
    ('late_leaderboard',{'month':'2026-07','department':'Sales','limit':2},'late_leaderboard_pipeline'),
    ('department_trend',{'department':'Support','from':FROM,'to':TO},'department_trend_pipeline'),
])
def test_aggregation_explain_matches_actual_live_pipeline_and_hint(http,db,helpers,name,params,builder):
    paths={'employee_monthly':'/analytics/employees/EMP0002/monthly','department_summary':'/analytics/departments/summary',
        'late_leaderboard':LEADER,'department_trend':'/analytics/departments/Support/trend'}
    db['system.profile'].drop()
    db.command('profile',2)
    try:
        r=http.get(paths[name],params=params)
        assert r.status_code==200,r.text
    finally:
        db.command('profile',0)
    reads=list(db['system.profile'].find({'command.aggregate':'employees'}))
    assert reads
    raw=json_util.loads(json.dumps(explain(http,name,**params)['explain']))
    operation=raw['command'].get('explain',raw['command'])
    assert operation['pipeline']==reads[-1]['command']['pipeline']
    assert operation['hint']==reads[-1]['command']['hint']


def test_100k_explain_http_for_all_operations_and_indexed_lookups(http,db,record_testsuite_property):
    clear(db)
    start=date(2026,1,1)
    codes=[f'EMP{100000+i}' for i in range(1000)]
    db.employees.insert_many([{**employee(code,department='Engineering' if i%2==0 else 'Sales'),
        'created_at':datetime(2026,1,1,tzinfo=timezone.utc)} for i,code in enumerate(codes)])
    for i in range(100):
        day=(start+timedelta(days=i)).isoformat()
        db.attendance_logs.insert_many([{'emp_code':code,'date':day,'status':'PRESENT','work_hours':8.0,
            'late_minutes':j%100+1,'overtime_minutes':30,'half_day':False} for j,code in enumerate(codes)])
    operations=[
        ('attendance_list',{'page':2,'page_size':20,'status':'PRESENT','date_from':'2026-03-01','date_to':'2026-03-31'}),
        ('employee_monthly',{'emp_code':codes[0],'month':'2026-03'}),
        ('department_summary',{'month':'2026-03'}),
        ('department_summary',{'month':'2026-03','department':'Engineering'}),
        ('late_leaderboard',{'month':'2026-03','limit':2}),
        ('late_leaderboard',{'month':'2026-03','limit':2,'department':'Engineering'}),
        ('department_trend',{'department':'Engineering','from':'2026-03-01','to':'2026-03-31'}),
    ]
    for number,(name,params) in enumerate(operations):
        before=time.monotonic()
        raw=explain(http,name,**params)['explain']
        elapsed=time.monotonic()-before
        assert 'IXSCAN' in str(raw) and 'COLLSCAN' not in str(raw),raw
        for stage in raw.get('stages',[]):
            if '$lookup' in stage:
                assert stage['collectionScans']==0 and stage['indexesUsed'],stage
                record_testsuite_property(f'explain_{number}_{name}_lookup_{stage["$lookup"]["as"]}_scans',stage['collectionScans'])
        record_testsuite_property(f'explain_{number}_{name}_seconds',f'{elapsed:.3f}')
    rows=trend(http,date_from='2026-03-01',date_to='2026-03-31')['items']
    assert len(rows)==31 and all(r['headcount']==500 and r['present_count']==500 for r in rows)
    assert all(r['attendance_rate']==(1.0 if r['is_working_day'] else None) for r in rows)
    leaders=leaderboard(http,'2026-03',limit=2)['items']
    assert len(leaders)==10 and all(r['rank']==1 and r['total_late_minutes']==3100 for r in leaders)
    filtered=leaderboard(http,'2026-03',limit=2,department='Engineering')['items']
    assert len(filtered)==10 and all(r['rank']==1 and r['total_late_minutes']==3069 for r in filtered)

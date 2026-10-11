"""Group 1: actual HTTP writes, stored BSON, races and startup/index evidence."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
import time
from uuid import uuid4

import pytest
from pymongo import MongoClient

from conftest import URI, employee, launch_server, millis, stop_server

DAY = '2026-07-15'
PIN = millis('2026-07-15T09:30:00+05:30')
POUT = millis('2026-07-15T18:30:00+05:30')
PATCH = {'reason': 'Correct recorded attendance', 'regularized_by': 'Audit Manager'}
PATH = f'/attendance/EMP0001/{DAY}'
INVALID_TIMES = [None, 0, True, '1800000000000', 1800000000000.0,
                 1800000000000.5, -1, 99999999999, 4102444800001, 10**30, {}, []]


def open_record(http, code='EMP0001', pin=PIN):
    r = http.post('/attendance/punch-in', json={'emp_code': code, 'punched_at': pin})
    assert r.status_code == 201, r.text
    return r.json()


def close_record(http):
    open_record(http)
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': POUT})
    assert r.status_code == 200, r.text
    return r.json()


def correct(http, **fields):
    return http.patch(PATH, json={**PATCH, **fields})


def test_punch_out_normal_and_ignored_derived_fields(http, db):
    opened = open_record(http)
    db.attendance_logs.update_one({'emp_code': 'EMP0001', 'date': DAY}, {'$set': {'late_minutes': 777}})
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': POUT + 999,
        'work_hours': 99, 'late_minutes': 99, 'overtime_minutes': 99, 'half_day': True})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result == {**opened, 'punch_out': POUT, 'work_hours': 9.0, 'late_minutes': 777}
    stored = db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': DAY})
    assert stored['punch_out'] == datetime(2026, 7, 15, 13, tzinfo=timezone.utc)
    assert stored['history'] == []
    assert set(stored) == set(result) | {'_id'}


@pytest.mark.parametrize('seconds,hours,half_day,overtime', [
    (450, .13, True, 0), (16181, 4.49, True, 0), (16182, 4.5, False, 0),
    (16200, 4.5, False, 0), (34199, 9.5, False, 0), (34200, 9.5, False, 30),
    (34259, 9.52, False, 30), (34260, 9.52, False, 31), (86400, 24.0, False, 900),
])
def test_punch_out_calculation_boundaries(http, seconds, hours, half_day, overtime):
    open_record(http)
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': PIN + seconds * 1000 + 999})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body['work_hours'], body['half_day'], body['overtime_minutes']) == (hours, half_day, overtime)
    assert body['punch_out'] == PIN + seconds * 1000


@pytest.mark.parametrize('iso,day', [('2026-07-15T22:00:00+05:30', '2026-07-15'),
    ('2026-12-31T22:00:00+05:30', '2026-12-31'), ('2028-02-29T22:00:00+05:30', '2028-02-29')])
def test_punch_out_overnight_and_calendar_rollover(http, iso, day):
    start = millis(iso)
    open_record(http, code='EMP0005', pin=start)
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0005', 'punched_at': start + (8 * 3600 + 40 * 60) * 1000})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body['date'], body['work_hours'], body['overtime_minutes'], body['half_day']) == (day, 8.67, 40, False)


@pytest.mark.parametrize('value', INVALID_TIMES)
def test_punch_out_strict_timestamp_validation(http, value):
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': value})
    assert r.status_code == 422 and 'detail' in r.json(), r.text


@pytest.mark.parametrize('field', ['punch_in', 'punch_out'])
@pytest.mark.parametrize('value', INVALID_TIMES)
def test_correction_strict_timestamp_validation(http, field, value):
    r = correct(http, **{field: value})
    assert r.status_code == 422 and 'detail' in r.json(), r.text


@pytest.mark.parametrize('employee_code,instant,expected', [('EMP9999', PIN, 404),
    ('EMP0004', PIN, 409), ('EMP0001', PIN - 1, 409), ('EMP0001', PIN, 422),
    ('EMP0001', PIN + 86401000, 422)])
def test_punch_out_resource_and_interval_errors(http, db, employee_code, instant, expected):
    open_record(http)
    before = list(db.attendance_logs.find())
    r = http.post('/attendance/punch-out', json={'emp_code': employee_code, 'punched_at': instant})
    assert r.status_code == expected, r.text
    assert list(db.attendance_logs.find()) == before


def test_punch_out_before_only_record_and_future_record_selection(http, db):
    db.attendance_logs.delete_many({'emp_code': 'EMP0001'})
    open_record(http)
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': PIN - 1})
    assert r.status_code == 404, r.text
    open_record(http, pin=PIN + 86400000)
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': POUT})
    assert r.status_code == 200 and r.json()['date'] == DAY
    assert db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': '2026-07-16'})['punch_out'] is None


def test_punch_out_does_not_fall_back_to_older_open_record(http, db):
    old = open_record(http)
    open_record(http, pin=PIN + 86400000)
    later = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': POUT + 86400000})
    assert later.status_code == 200
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': POUT + 86400000})
    assert r.status_code == 409, r.text
    assert db.attendance_logs.find_one({'emp_code': old['emp_code'], 'date': old['date']})['punch_out'] is None


def test_punch_out_selects_punch_time_not_attendance_date(http, db):
    db.attendance_logs.delete_many({'emp_code': 'EMP0001'})
    # A deliberately unusual seeded date order tests selection independently of
    # normal R1-generated records. Punch-out must sort by punch_in.
    for day, start in [('2026-07-15', PIN), ('2026-07-16', PIN - 3600000)]:
        db.attendance_logs.insert_one({'emp_code': 'EMP0001', 'date': day, 'status': 'PRESENT',
                                      'punch_in': datetime.fromtimestamp(start / 1000, timezone.utc)})
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': POUT})
    assert r.status_code == 200 and r.json()['date'] == DAY, r.text


def test_punch_out_omitted_timestamp_and_history_preserved(http, db):
    pin = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
    opened = open_record(http, pin=int(pin.timestamp() * 1000))
    key = {'emp_code': 'EMP0001', 'date': opened['date']}
    history = [{'at': pin, 'by': 'Earlier Actor', 'reason': 'Previous accepted correction', 'changes': {'status': {'from': 'WFH', 'to': 'PRESENT'}}}]
    db.attendance_logs.update_one(key, {'$set': {'history': history}})
    before = datetime.now(timezone.utc).replace(microsecond=0)
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001'})
    after = datetime.now(timezone.utc)
    assert r.status_code == 200, r.text
    stored = db.attendance_logs.find_one(key)
    assert before <= stored['punch_out'] <= after and stored['punch_out'].microsecond == 0
    assert stored['history'] == history and len(r.json()['history']) == 1


def test_punch_out_truncates_legacy_pin_and_handles_missing_fields(http, db):
    open_record(http)
    key = {'emp_code': 'EMP0001', 'date': DAY}
    db.attendance_logs.update_one(key, {'$set': {'punch_in': datetime(2026, 7, 15, 4, 0, 0, 900000, tzinfo=timezone.utc)},
                                      '$unset': {'punch_out': '', 'history': '', 'work_hours': '', 'half_day': ''}})
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': PIN + 999})
    assert r.status_code == 422, r.text
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': PIN + 450999})
    assert r.status_code == 200 and r.json()['work_hours'] == .13, r.text
    stored = db.attendance_logs.find_one(key)
    assert stored['punch_in'].microsecond == 0 and 'history' not in stored
    assert r.json()['history'] == []


@pytest.mark.parametrize('changes', [{'reason': 'tiny'}, {'reason': 'x' * 201},
    {'regularized_by': ''}, {'regularized_by': 'x' * 51}, {'reason': None},
    {'regularized_by': None}, {'status': None}, {'status': 'UNKNOWN'}])
def test_correction_metadata_and_status_validation(http, changes):
    r = correct(http, **changes)
    assert r.status_code == 422 and 'detail' in r.json(), r.text


@pytest.mark.parametrize('body', [{}, {'reason': PATCH['reason']}, {'regularized_by': 'Manager'}])
def test_correction_required_metadata(http, body):
    r = http.patch(PATH, json=body)
    assert r.status_code == 422, r.text


@pytest.mark.parametrize('path,expected', [('/attendance/EMP9999/2026-07-15', 404),
    ('/attendance/EMP0004/2026-07-15', 404), ('/attendance/EMP0001/2026-02-30', 422),
    ('/attendance/EMP0001/2026-7-15', 422)])
def test_correction_resource_and_path_validation(http, path, expected):
    r = http.patch(path, json={**PATCH, 'status': 'WFH'})
    assert r.status_code == expected, r.text


@pytest.mark.parametrize('status', ['ABSENT', 'LEAVE'])
def test_correction_absence_clears_punches_and_audits_all_changes(http, db, status):
    old = close_record(http)
    r = correct(http, status=status)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body['punch_in'], body['punch_out'], body['work_hours']) == (None, None, None)
    assert (body['late_minutes'], body['overtime_minutes'], body['half_day']) == (0, 0, False)
    changes = body['history'][0]['changes']
    assert set(changes) == {'status', 'punch_in', 'punch_out', 'work_hours'}
    for field in changes:
        assert changes[field] == {'from': old[field], 'to': body[field]}
    stored = db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': DAY})
    assert isinstance(stored['history'][0]['changes']['punch_in']['from'], datetime)
    assert isinstance(stored['history'][0]['changes']['punch_out']['from'], datetime)


@pytest.mark.parametrize('status', ['ABSENT', 'LEAVE'])
@pytest.mark.parametrize('field', ['punch_in', 'punch_out'])
def test_correction_absence_rejects_punch_fields(http, db, status, field):
    close_record(http)
    before = db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': DAY})
    r = correct(http, **{'status': status, field: PIN})
    assert r.status_code == 422, r.text
    assert db.attendance_logs.find_one({'_id': before['_id']}) == before


@pytest.mark.parametrize('pin,late,hours', [
    ('2026-07-15T09:40:00.999+05:30', 0, 8.83),
    ('2026-07-15T09:40:01+05:30', 10, 8.83),
    ('2026-07-15T10:15:59+05:30', 45, 8.23),
])
def test_correction_lateness_hours_and_truncation(http, db, pin, late, hours):
    close_record(http)
    before = datetime.now(timezone.utc).replace(microsecond=0)
    r = correct(http, punch_in=millis(pin))
    after = datetime.now(timezone.utc)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body['late_minutes'], body['work_hours'], body['punch_out']) == (late, hours, POUT)
    entry = body['history'][0]
    assert entry['by'] == PATCH['regularized_by'] and entry['reason'] == PATCH['reason']
    assert millis(before.isoformat()) <= entry['at'] <= millis(after.isoformat())
    stored = db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': DAY})
    assert stored['punch_in'].microsecond == 0 and stored['history'][0]['at'].microsecond == 0
    assert isinstance(stored['history'][0]['changes']['punch_in']['to'], datetime)


@pytest.mark.parametrize('seconds,hours,half_day,overtime', [(450, .13, True, 0),
    (16181, 4.49, True, 0), (16182, 4.5, False, 0), (34200, 9.5, False, 30)])
def test_correction_recomputes_out_derived_fields(http, seconds, hours, half_day, overtime):
    open_record(http)
    r = correct(http, punch_out=PIN + seconds * 1000)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body['work_hours'], body['half_day'], body['overtime_minutes']) == (hours, half_day, overtime)
    assert body['history'][0]['changes']['punch_out'] == {'from': None, 'to': PIN + seconds * 1000}


@pytest.mark.parametrize('status', ['PRESENT', 'WFH', 'ON_DUTY'])
def test_correction_absence_to_presence_requires_pin(http, db, status):
    path = '/attendance/EMP0003/2026-07-08'
    r = http.patch(path, json={**PATCH, 'status': status})
    assert r.status_code == 422, r.text
    pin = millis('2026-07-08T09:30:00+05:30')
    r = http.patch(path, json={**PATCH, 'status': status, 'punch_in': pin})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['punch_in'] == pin and body['punch_out'] is None and body['work_hours'] is None
    assert body['history'][0]['changes']['punch_in'] == {'from': None, 'to': pin}


@pytest.mark.parametrize('fields', [{'punch_in': PIN + 86400000}, {'punch_in': POUT},
    {'punch_out': PIN}, {'punch_out': PIN - 1000}, {'punch_out': PIN + 86401000}])
def test_correction_invalid_final_date_or_interval_preserves_record(http, db, fields):
    close_record(http)
    before = db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': DAY})
    r = correct(http, **fields)
    assert r.status_code == 422, r.text
    assert db.attendance_logs.find_one({'_id': before['_id']}) == before


def test_correction_overnight_date_and_overtime(http, db):
    start = millis('2026-07-15T22:00:00+05:30')
    open_record(http, code='EMP0005', pin=start)
    path = '/attendance/EMP0005/2026-07-15'
    r = http.patch(path, json={**PATCH, 'punch_in': millis('2026-07-16T01:00:00+05:30'),
        'punch_out': millis('2026-07-16T06:40:00+05:30')})
    assert r.status_code == 200, r.text
    assert (r.json()['date'], r.json()['late_minutes'], r.json()['work_hours'], r.json()['overtime_minutes']) == ('2026-07-15', 180, 5.67, 40)
    before = db.attendance_logs.find_one({'emp_code': 'EMP0005', 'date': DAY})
    r = http.patch(path, json={**PATCH, 'punch_in': millis('2026-07-16T06:00:00+05:30')})
    assert r.status_code == 422
    assert db.attendance_logs.find_one({'_id': before['_id']}) == before


@pytest.mark.parametrize('fields', [{}, {'status': 'PRESENT'}, {'punch_in': PIN + 999},
    {'work_hours': 1, 'late_minutes': 999, 'overtime_minutes': 999, 'half_day': True}])
def test_correction_noop_and_ignored_derived_fields(http, db, fields):
    close_record(http)
    before = db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': DAY})
    r = correct(http, **fields)
    assert r.status_code == 422, r.text
    assert db.attendance_logs.find_one({'_id': before['_id']}) == before


def test_correction_recomputes_inconsistent_stored_derived_values(http, db):
    close_record(http)
    db.attendance_logs.update_one({'emp_code': 'EMP0001', 'date': DAY}, {'$set': {'work_hours': 999, 'late_minutes': 999}})
    r = correct(http, status='WFH', work_hours=888, late_minutes=888)
    assert r.status_code == 200, r.text
    assert r.json()['work_hours'] == 9 and r.json()['late_minutes'] == 0
    changes = r.json()['history'][0]['changes']
    assert changes['work_hours'] == {'from': 999, 'to': 9}
    assert changes['late_minutes'] == {'from': 999, 'to': 0}


def test_correction_appends_preserves_legacy_defaults_and_nested_serialization(http, db):
    key = {'emp_code': 'EMP0002', 'date': '2026-07-14'}
    original = db.attendance_logs.find_one(key)
    assert 'history' not in original and 'half_day' not in original
    db.attendance_logs.update_one(key, {'$unset': {'late_minutes': '', 'overtime_minutes': ''}})
    path = '/attendance/EMP0002/2026-07-14'
    for status in ['WFH', 'ON_DUTY']:
        r = http.patch(path, json={**PATCH, 'status': status})
        assert r.status_code == 200, r.text
    result = r.json()
    assert len(result['history']) == 2
    assert result['history'][0]['changes']['status'] == {'from': 'PRESENT', 'to': 'WFH'}
    assert result['history'][1]['changes']['status'] == {'from': 'WFH', 'to': 'ON_DUTY'}
    assert 'half_day' not in result['history'][0]['changes']
    assert result['half_day'] is False and type(result['history'][0]['at']) is int


def test_correction_preserves_previous_history_exactly(http, db):
    key = {'emp_code': 'EMP0001', 'date': '2026-07-07'}
    original = db.attendance_logs.find_one(key)
    r = http.patch('/attendance/EMP0001/2026-07-07', json={**PATCH, 'status': 'WFH'})
    assert r.status_code == 200, r.text
    stored = db.attendance_logs.find_one(key)
    assert stored['history'][:-1] == original['history']
    nested = r.json()['history'][0]['changes']['punch_in']
    assert all(type(value) is int for value in nested.values())


@pytest.mark.parametrize('status', ['ABSENT', 'LEAVE'])
def test_absence_correction_clears_nonzero_derived_values_and_rejects_punch_without_status(http, db, status):
    open_record(http, pin=PIN + 3600000)
    closed = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': POUT + 3600000})
    assert closed.status_code == 200 and closed.json()['late_minutes'] == closed.json()['overtime_minutes'] == 60
    r = correct(http, status=status)
    assert r.status_code == 200, r.text
    changes = r.json()['history'][0]['changes']
    assert changes['late_minutes'] == changes['overtime_minutes'] == {'from': 60, 'to': 0}
    before = db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': DAY})
    r = correct(http, punch_in=PIN)
    assert r.status_code == 422, r.text
    assert db.attendance_logs.find_one({'_id': before['_id']}) == before


@pytest.mark.parametrize('status', ['PRESENT', 'WFH', 'ON_DUTY'])
def test_punch_out_and_correction_support_each_presence_status(http, status):
    r = http.post('/attendance/punch-in', json={'emp_code': 'EMP0001', 'punched_at': PIN, 'status': status})
    assert r.status_code == 201
    r = correct(http, punch_in=PIN + 600000)
    assert r.status_code == 200 and r.json()['work_hours'] is None
    assert r.json()['half_day'] is False and r.json()['overtime_minutes'] == 0
    r = http.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': POUT})
    assert r.status_code == 200, r.text
    assert r.json()['status'] == status and len(r.json()['history']) == 1
    assert r.json()['work_hours'] == 8.83


@pytest.mark.parametrize('reason,actor', [('12345', 'A'), ('x' * 200, 'x' * 50)])
def test_correction_accepts_exact_metadata_length_bounds(http, reason, actor):
    open_record(http)
    r = correct(http, status='WFH', reason=reason, regularized_by=actor)
    assert r.status_code == 200, r.text
    assert r.json()['history'][0]['reason'] == reason and r.json()['history'][0]['by'] == actor


def concurrent_requests(http, requests):
    barrier = threading.Barrier(len(requests))

    def send(request):
        method, path, body = request
        barrier.wait(timeout=10)
        return http.request(method, path, json=body)

    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        return list(pool.map(send, requests))


@pytest.mark.parametrize('round_number', range(5))
def test_parallel_punch_out_has_exactly_one_winner(http, db, round_number):
    open_record(http)
    requests = [('POST', '/attendance/punch-out', {'emp_code': 'EMP0001', 'punched_at': POUT})] * 24
    responses = concurrent_requests(http, requests)
    assert Counter(r.status_code for r in responses) == {200: 1, 409: 23}
    stored = db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': DAY})
    assert stored['punch_out'] == datetime.fromtimestamp(POUT / 1000, timezone.utc)
    assert stored['work_hours'] == 9 and stored['history'] == []


@pytest.mark.parametrize('round_number', range(5))
def test_parallel_corrections_keep_every_accepted_change_and_history(http, db, round_number):
    close_record(http)
    requests = [('PATCH', PATH, {**PATCH, 'regularized_by': f'Actor {i}',
        'punch_out': POUT + (i + 1) * 1000}) for i in range(24)]
    responses = concurrent_requests(http, requests)
    assert all(r.status_code in (200, 409) for r in responses)
    accepted = {f'Actor {i}' for i, r in enumerate(responses) if r.status_code == 200}
    assert accepted
    stored = db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': DAY})
    assert len(stored['history']) == len(accepted)
    assert {entry['by'] for entry in stored['history']} == accepted
    previous = datetime.fromtimestamp(POUT / 1000, timezone.utc)
    for entry in stored['history']:
        change = entry['changes']['punch_out']
        assert change['from'] == previous
        previous = change['to']
    assert stored['punch_out'] == previous


@pytest.fixture
def blocked_writes(db):
    # Failpoints are global server settings: refuse the manual development port.
    assert URI in ('mongodb://127.0.0.1:27038', 'mongodb://127.0.0.1:27039')
    admin = db.client.admin
    assert admin.command('getParameter', 1, enableTestCommands=1)['enableTestCommands']

    def configure(times=2, milliseconds=500):
        response = admin.command('configureFailPoint', 'failCommand', mode={'times': times},
            data={'failCommands': ['findAndModify'], 'blockConnection': True, 'blockTimeMS': milliseconds})
        return response['count']

    try:
        yield configure
    finally:
        admin.command('configureFailPoint', 'failCommand', mode='off')


@pytest.mark.parametrize('other_fields', [{'status': 'ON_DUTY'}, {'punch_out': POUT + 60000}])
def test_stale_correction_returns_409_for_overlapping_or_separate_fields(http, db, blocked_writes, other_fields):
    close_record(http)
    blocked_writes()
    requests = [('PATCH', PATH, {**PATCH, 'regularized_by': 'First', 'status': 'WFH'}),
                ('PATCH', PATH, {**PATCH, 'regularized_by': 'Second', **other_fields})]
    responses = concurrent_requests(http, requests)
    assert Counter(r.status_code for r in responses) == {200: 1, 409: 1}, [r.text for r in responses]
    stored = db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': DAY})
    assert len(stored['history']) == 1
    winner = next(r.json() for r in responses if r.status_code == 200)
    assert stored['history'][0]['by'] == winner['history'][0]['by']
    for field, change in stored['history'][0]['changes'].items():
        assert stored[field] == change['to']


@pytest.mark.parametrize('status', ['WFH', 'ABSENT'])
def test_correction_and_punch_out_never_overwrite_stale_state(http, db, blocked_writes, status):
    open_record(http)
    blocked_writes()
    responses = concurrent_requests(http, [
        ('PATCH', PATH, {**PATCH, 'status': status}),
        ('POST', '/attendance/punch-out', {'emp_code': 'EMP0001', 'punched_at': POUT}),
    ])
    assert Counter(r.status_code for r in responses) == {200: 1, 409: 1}, [r.text for r in responses]
    stored = db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': DAY})
    if responses[0].status_code == 200:
        assert stored['status'] == status and len(stored['history']) == 1
        assert stored['punch_out'] is None
        assert stored['punch_in'] is None if status == 'ABSENT' else stored['punch_in'] is not None
    else:
        assert stored['status'] == 'PRESENT' and stored['history'] == []
        assert stored['work_hours'] == 9
        # A fresh, explicit resubmission succeeds and keeps the closure unless
        # the chosen absence status intentionally clears it.
        retried = correct(http, status=status)
        assert retried.status_code == 200, retried.text
        assert len(retried.json()['history']) == 1
        assert retried.json()['punch_out'] == (None if status == 'ABSENT' else POUT)


@pytest.mark.parametrize('pending_kind', ['correction', 'punch_out'])
def test_history_length_rejects_state_changed_then_restored(http, db, blocked_writes, pending_kind):
    open_record(http)
    count = blocked_writes(times=1, milliseconds=1200)
    with ThreadPoolExecutor(max_workers=1) as pool:
        if pending_kind == 'correction':
            pending = pool.submit(correct, http, status='ON_DUTY')
        else:
            pending = pool.submit(http.post, '/attendance/punch-out',
                json={'emp_code': 'EMP0001', 'punched_at': POUT})
        db.client.admin.command('waitForFailPoint', 'failCommand', timesEntered=count + 1, maxTimeMS=5000)
        first = correct(http, status='WFH')
        second = correct(http, status='PRESENT')
        assert first.status_code == second.status_code == 200
        response = pending.result(timeout=5)
    assert response.status_code == 409, response.text
    stored = db.attendance_logs.find_one({'emp_code': 'EMP0001', 'date': DAY})
    assert stored['status'] == 'PRESENT' and stored['punch_out'] is None
    assert len(stored['history']) == 2
    assert [entry['changes']['status'] for entry in stored['history']] == [
        {'from': 'PRESENT', 'to': 'WFH'}, {'from': 'WFH', 'to': 'PRESENT'}]


def test_startup_indexes_on_preseeded_100k_and_punch_out_plan(live_app, helpers, record_testsuite_property):
    client = MongoClient(URI, tz_aware=True)
    name = 'candidate_kit_runtime_audit_scale_' + uuid4().hex[:16]
    database = client[name]
    server = None
    try:
        start = datetime(2026, 1, 1, 4, tzinfo=timezone.utc)
        codes = [f'EMP{100000 + i}' for i in range(1000)]
        database.employees.insert_many([{**employee(code), 'created_at': start} for code in codes])
        for day_number in range(100):
            pin = start + timedelta(days=day_number)
            database.attendance_logs.insert_many([{'emp_code': code, 'date': pin.date().isoformat(),
                'status': 'PRESENT', 'punch_in': pin, 'punch_out': None,
                'work_hours': None, 'late_minutes': 0, 'overtime_minutes': 0,
                'half_day': False, 'history': []} for code in codes])
        assert len(database.employees.index_information()) == len(database.attendance_logs.index_information()) == 1
        before = time.monotonic()
        server = launch_server(URI, name)
        elapsed = time.monotonic() - before
        assert elapsed < 20
        assert database.employees.count_documents({}) == 1000
        assert database.attendance_logs.count_documents({}) == 100000
        assert len(database.attendance_logs.index_information()) == 6
        instant = start + timedelta(days=99, hours=9)
        query, sort, hint = helpers.punch_out_query(codes[0], instant)
        explanation = database.command('explain', {'find': 'attendance_logs', 'filter': query,
            'sort': dict(sort), 'hint': hint, 'limit': 1}, verbosity='executionStats')
        plan = explanation['queryPlanner']['winningPlan']
        assert 'IXSCAN' in str(plan) and 'COLLSCAN' not in str(plan) and "'SORT'" not in str(plan), plan
        stats = explanation['executionStats']
        assert stats['nReturned'] == stats['totalDocsExamined'] == stats['totalKeysExamined'] == 1
        record_testsuite_property('preseeded_100k_startup_seconds', f'{elapsed:.3f}')
        record_testsuite_property('punch_out_keys_examined', stats['totalKeysExamined'])
        record_testsuite_property('punch_out_documents_examined', stats['totalDocsExamined'])
        print(f'\n100k preseed startup {elapsed:.3f}s; punch-out keys/docs examined 1/1')
        response = server[2].post('/attendance/punch-out', json={'emp_code': codes[0],
            'punched_at': int(instant.timestamp() * 1000)})
        assert response.status_code == 200, response.text
        assert response.json()['date'] == (start + timedelta(days=99)).date().isoformat()
        assert response.json()['work_hours'] == 9
        assert database.attendance_logs.count_documents({'punch_out': {'$ne': None}}) == 1
    finally:
        if server is not None:
            stop_server(*server)
        assert name.startswith('candidate_kit_runtime_audit_')
        client.drop_database(name)
        client.close()

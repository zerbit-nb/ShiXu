"""Reminder plans are deterministic, durable and independent of model calls."""
from datetime import datetime, timedelta
import pytest
from app.database import Database
from app.services.task_reminders import TaskReminders

NOW = datetime.fromisoformat('2026-11-09T10:00:00+08:00')


@pytest.fixture
def scheduler(tmp_path):
    db = Database(tmp_path/'db'); worker = TaskReminders(db)
    yield db, worker
    db.close()


def task(db, deadline, title='提交报告'):
    message = db.create_message(dict(source='manual',source_group='测试',sender=None,sent_at=NOW.isoformat(),raw_text=title,extraction_status='ready'))
    fields = dict(title=title,deadline=deadline,deadline_precision='date_only' if deadline and len(deadline)==10 else 'datetime' if deadline else 'unknown')
    draft = db.create_draft(message['id'],fields,[])
    return db.confirm_draft(draft['id'],fields)


def enable(worker, **changes):
    return worker.configure(dict(enabled=True,daily_enabled=False,daily_time='09:00',lead_minutes=60,
                                 quiet_enabled=False,quiet_start='22:00',quiet_end='08:00') | changes)


def test_default_off_due_time_and_persistent_dedup(scheduler):
    db,w=scheduler; item=task(db,'2026-11-09T11:00:00+08:00')
    w.tick(NOW); assert not w.claim('foreground',NOW)['events']
    enable(w); w.tick(NOW-timedelta(seconds=1)); assert not w.claim('foreground',NOW-timedelta(seconds=1))['events']
    result=w.claim('foreground',NOW); assert len(result['events'])==1
    assert result['events'][0]['tasks'][0]['id']==item['id']
    w.delivered(result['claim_id'],NOW)
    restarted=TaskReminders(db); assert not restarted.claim('system',NOW+timedelta(minutes=1))['events']


def test_foreground_and_native_cannot_claim_same_event_and_lease_recovers(scheduler):
    db,w=scheduler; task(db,'2026-11-09T11:00:00+08:00');enable(w)
    first=w.claim('foreground',NOW); assert first['events']
    assert not w.claim('system',NOW)['events']
    second=w.claim('system',NOW+timedelta(seconds=61)); assert second['events']
    assert second['claim_id']!=first['claim_id']


def test_date_only_and_unknown_use_digest_without_invented_time(scheduler):
    db,w=scheduler
    a=task(db,'2026-11-09');task(db,None);task(db,'2026-11-10')
    enable(w,daily_enabled=True)
    events=w.claim('foreground',NOW)['events']
    assert len(events)==1 and events[0]['kind']=='daily'
    assert [t['id'] for t in events[0]['tasks']]==[a['id']]
    assert db.get_task(a['id'])['deadline']=='2026-11-09'


@pytest.mark.parametrize('change',['complete','cancel','delete','reschedule'])
def test_old_notification_invalidated_before_delivery(scheduler,change):
    db,w=scheduler; item=task(db,'2026-11-09T11:00:00+08:00');enable(w)
    first=w.claim('foreground',NOW); assert first['events']
    if change=='delete':db.delete_task(item['id'])
    elif change=='reschedule':db.update_task(item['id'],{'deadline':'2026-11-10T11:00:00+08:00'})
    else:db.update_task(item['id'],{'status':'completed' if change=='complete' else 'cancelled'})
    assert not w.delivered(first['claim_id'],NOW)['events']
    assert not w.claim('system',NOW+timedelta(seconds=61))['events']


def test_snooze_does_not_change_deadline_and_can_cross_deadline(scheduler):
    db,w=scheduler; item=task(db,'2026-11-09T10:10:00+08:00');enable(w)
    first=w.claim('foreground',NOW);w.delivered(first['claim_id'],NOW)
    w.snooze(first['events'][0]['id'],60,NOW)
    assert not w.claim('system',NOW+timedelta(minutes=59))['events']
    assert w.claim('system',NOW+timedelta(minutes=60))['events']
    assert db.get_task(item['id'])['deadline']=='2026-11-09T10:10:00+08:00'


def test_quiet_hours_and_overdue_are_batched_on_resume(scheduler):
    db,w=scheduler;task(db,'2026-11-08T10:00:00+08:00');task(db,'2026-11-09')
    enable(w,daily_enabled=True,quiet_enabled=True,quiet_start='09:00',quiet_end='11:00')
    assert not w.claim('system',NOW)['events']
    result=w.claim('foreground',NOW+timedelta(hours=1))
    assert len(result['events'])==1 and len(result['events'][0]['tasks'])==2
    assert result['events'][0]['kind']=='daily'


def test_per_task_override_and_global_disable(scheduler):
    db,w=scheduler;item=task(db,'2026-11-09T11:00:00+08:00');enable(w)
    w.set_task(item['id'],'custom',15)
    assert not w.claim('foreground',NOW)['events']
    assert w.claim('foreground',NOW+timedelta(minutes=45))['events']
    w.configure(w.public() | {'enabled':False})
    assert not w.claim('system',NOW+timedelta(minutes=46))['events']


def test_daily_and_deadline_batch_does_not_repeat_task(scheduler):
    db,w=scheduler;item=task(db,'2026-11-09T11:00:00+08:00');enable(w,daily_enabled=True)
    claimed=w.claim('foreground',NOW)
    assert len(claimed['events'])==1
    result=w.delivered(claimed['claim_id'],NOW)
    assert len(result['events'])==1 and result['events'][0]['tasks'][0]['id']==item['id']
    w.acknowledge(result['events'][0]['id'])
    # The overlapping daily event must not reappear after the deadline event is dismissed.
    rows=db.conn.execute("SELECT * FROM reminder_events WHERE state='delivered'").fetchall()
    assert not rows


def test_reminder_api_is_strict_and_rejects_cross_origin(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(db_path=tmp_path/'db',config_path=tmp_path/'config')) as c:
        original=c.get('/api/reminders').json(); original.pop('error')
        assert original['enabled'] is False
        assert c.put('/api/reminders',json=original).status_code==403
        for changes in ({'lead_minutes':True},{'daily_time':'25:00'},{'quiet_enabled':True,'quiet_start':'08:00','quiet_end':'08:00'}):
            assert c.put('/api/reminders',json=original|changes,headers={'Origin':'http://testserver'}).status_code==422
        assert c.post('/api/reminders/claim',json={'channel':'system'}).status_code==403
        assert c.get('/api/reminders').json()['enabled'] is False

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.extraction import normalize_extraction
from app.services.reminders import annotate, matches_view
from tests.test_api import LocalModelStub


def test_drafts_tasks_and_originals_survive_restart(tmp_path):
    kwargs = dict(db_path=tmp_path / 'db.sqlite', config_path=tmp_path / 'config.json', llm=LocalModelStub())
    with TestClient(create_app(Settings(), **kwargs)) as client:
        result = client.post('/api/messages/extract', json={'messages':[{'raw_text':'通知'}]}).json()['results'][0]
        draft = result['drafts'][0]
        task = client.post(f"/api/drafts/{draft['id']}/confirm", json={'confirmed':True,'fields':draft['fields']}).json()
    with TestClient(create_app(Settings(), **kwargs)) as client:
        assert len(client.get('/api/drafts').json()['drafts']) == 1
        assert client.get(f"/api/tasks/{task['id']}").json()['title'] == '提交材料'
        assert client.get(f"/api/messages/{task['message_id']}").json()['raw_text'] == '通知'


def test_model_date_cannot_override_program_date():
    result = {'is_actionable':True,'tasks':[{'title':'提交报告','deadline_text':'明天 20:00','deadline_iso':'2099-01-01T00:00:00+08:00'}]}
    assert normalize_extraction(result, None)[0]['fields']['deadline'] is None
    assert normalize_extraction(result, datetime.fromisoformat('2026-10-10T09:00:00+08:00'))[0]['fields']['deadline'] == '2026-10-11T20:00:00+08:00'


@pytest.mark.parametrize('tasks', [[{'title':'有效'},{'title':' '}], [{'title':'有效','priority':'urgent'}], [{'title':'有效','unexpected':'field'}]])
def test_invalid_model_candidate_rejects_whole_response(tasks):
    with pytest.raises(ValueError):
        normalize_extraction({'is_actionable':True,'tasks':tasks},None)


def test_date_only_is_not_overdue_until_next_day():
    task = {'status':'pending','deadline':'2026-10-10'}
    now = datetime.fromisoformat('2026-10-10T23:59:00+08:00')
    assert annotate(task,now)['reminder'] == 'today'
    assert annotate(task,datetime.fromisoformat('2026-10-11T00:00:00+08:00'))['reminder'] == 'overdue'
    assert annotate({**task,'status':'completed'},now)['reminder'] is None
    assert annotate({**task,'status':'cancelled'},now)['reminder'] is None


def test_reminder_and_seven_calendar_days_boundaries():
    now = datetime.fromisoformat('2026-10-10T12:00:00+08:00')
    task = {'status':'pending','deadline':'2026-10-10T14:00:00+08:00'}
    assert annotate(task,now,hours=2)['reminder'] == 'soon'
    assert annotate({**task,'deadline':None},now)['reminder'] is None
    assert matches_view({**task,'deadline':'2026-10-16','reminder':None},'week',now)
    assert not matches_view({**task,'deadline':'2026-10-17','reminder':None},'week',now)


def test_local_model_config_rejects_external_url(tmp_path):
    with TestClient(create_app(Settings(),db_path=tmp_path/'db',config_path=tmp_path/'config',llm=LocalModelStub())) as client:
        response = client.put('/api/config',json={'llm_base_url':'https://example.com/v1','llm_model':'abc'})
        assert response.status_code == 422


def test_manual_create_keeps_original(tmp_path):
    with TestClient(create_app(Settings(),db_path=tmp_path/'db',config_path=tmp_path/'config',llm=LocalModelStub())) as client:
        result = client.post('/api/messages/manual',json={'raw_text':'原始材料通知','source_group':'课程群'}).json()
        assert result['message']['raw_text'] == '原始材料通知'
        assert result['drafts'][0]['status'] == 'pending'
        assert client.get('/api/tasks').json()['tasks'] == []

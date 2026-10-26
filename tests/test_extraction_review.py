from datetime import datetime

from app.services.extraction import normalize_extraction


def test_past_relative_deadline_is_preserved_with_review_warning():
    result={'is_actionable':True,'tasks':[{'title':'提交材料','deadline_text':'本周五20:00'}]}
    draft=normalize_extraction(result,datetime.fromisoformat('2026-10-10T12:00:00+08:00'))[0]
    assert draft['fields']['deadline']=='2026-10-09T20:00:00+08:00'
    assert any('早于消息发送时间' in w for w in draft['warnings'])


def test_uncertain_field_names_have_readable_labels():
    result={'is_actionable':True,'tasks':[{'title':'提交材料','uncertain_fields':['deadline_iso','submit_method']}]}
    warnings=normalize_extraction(result,None)[0]['warnings']
    assert '截止日期与时间需要核对。' in warnings
    assert '提交方式需要核对。' in warnings


def test_rewritten_deadline_cannot_remove_original_ambiguity():
    result={'is_actionable':True,'tasks':[{'title':'提交实验报告','deadline_text':'2026-10-14T20:00'}]}
    original='实验报告截止日期延长至2026年10月14日20:00，其他要求不变。'
    draft=normalize_extraction(result,None,original)[0]
    assert draft['fields']['deadline'] is None
    assert draft['fields']['deadline_text']==original
    assert draft['warnings']


def test_identical_candidates_in_one_response_do_not_make_two_drafts():
    task={'title':'提交问卷','deadline_text':'2026年10月12日'}
    drafts=normalize_extraction({'is_actionable':True,'tasks':[task,dict(task)]},None)
    assert len(drafts)==1
    assert any('重复' in w for w in drafts[0]['warnings'])


def test_quoted_date_does_not_remove_change_notice_context():
    result={'is_actionable':True,'tasks':[{'title':'提交实验报告','deadline_text':'2026年10月14日20:00'}]}
    original='实验报告截止日期延长至2026年10月14日20:00，其他要求不变。'
    draft=normalize_extraction(result,None,original)[0]
    assert draft['fields']['deadline'] is None
    assert any('变更' in w for w in draft['warnings'])


def test_selecting_one_date_cannot_hide_alternative_deadlines():
    result={'is_actionable':True,'tasks':[{'title':'提交材料','deadline_text':'2026年10月12日'}]}
    original='请于2026年10月12日或2026年10月14日提交材料，具体时间待定。'
    draft=normalize_extraction(result,None,original)[0]
    assert draft['fields']['deadline'] is None
    assert draft['warnings']

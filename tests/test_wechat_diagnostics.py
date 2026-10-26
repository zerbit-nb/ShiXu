from scripts.diagnose_wechat import status_summary


def test_report_status_uses_only_fixed_safe_fields():
    value={'state':'error','reason':'source_error','diagnostic':{'stage':'connect','type':'PermissionError','message':'secret path'},'account_alias':'secret-account','group_name':'secret-group','raw_text':'secret-message','token':'secret-token'}
    result=status_summary(value,{'source_error'})
    assert result=={'available':True,'state':'error','reason':'source_error','diagnostic':{'stage':'connect','type':'PermissionError'}}
    assert 'secret' not in str(result)


def test_report_rejects_unknown_upstream_strings():
    result=status_summary({'state':'private','reason':'token=private','diagnostic':{'stage':'path=private','type':'private'}},{'source_error'})
    assert result=={'available':True,'state':'unknown','reason':None,'diagnostic':{}}
    assert status_summary(None,set())=={'available':False,'error':'invalid_status'}

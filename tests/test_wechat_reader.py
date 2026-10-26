import pytest
from app.services.wechat_reader import query_page, SourceError, to_event, load_module

class Connection:
    def __init__(self, maximum): self.maximum=maximum
    def execute(self, query): return self
    def fetchone(self): return (self.maximum,)

class FakeReader:
    def __init__(self, data): self.data=data
    def _run_msg_query(self, group, build):
        return build([(Connection(max((r['local_id'] for r in rows),default=0)), shard) for shard, rows in self.data.items()])
    def _shard_maps(self,tables): return {}
    def _shard_rows(self,tables,sql,params,order_ext,per_shard_limit):
        shard=tables[0][1]
        return [dict(r,shard=shard) for r in self.data[shard] if r['local_id']>params[0]][:per_shard_limit]
    def _msg_row_to_dict(self,row,maps): return row

# Use table names as synthetic shard labels without loading Windows code.
def reader(data):
    value=FakeReader(data)
    tables=[(Connection(max((r['local_id'] for r in rows),default=0)), shard) for shard,rows in data.items()]
    value._run_msg_query=lambda group,build:build(tables)
    value._shard_label=lambda conn:next(shard for c,shard in tables if c is conn)
    return value

def test_pages_do_not_skip_more_than_500_or_equal_sort_seq():
    db=reader({'message_0.db':[dict(local_id=i,sort_seq=1,type='文本',content='same',create_time=None) for i in range(1,702)]})
    cur={'message_0.db':0}; seen=[]
    while True:
        rows,after=query_page(db,'group',cur)
        if not rows: break
        seen.extend(r['local_id'] for r in rows);cur=after
    assert seen==list(range(1,702))

def test_baseline_missing_shard_and_rewind():
    db=reader({'message_0.db':[dict(local_id=10)]})
    assert query_page(db,'group',None)==([],{'message_0.db':10})
    with pytest.raises(SourceError):query_page(db,'group',{'message_1.db':1})
    with pytest.raises(SourceError):query_page(db,'group',{'message_0.db':11})

def test_text_conversion_preserves_raw_unknown_time_and_nontext():
    row=dict(local_id=1,shard='message_0.db',type='文本',content='  原文\n',create_time=None,sender_username='')
    assert to_event(row)['content']=='  原文\n'
    assert to_event(row)['sent_at'] is None
    assert to_event(dict(row,type='图片',content='private'))['content']==''

def test_pinned_source_loads_without_package_initialization():
    import os
    if os.name!='nt':pytest.skip('Windows-only source module')
    pytest.importorskip('cryptography')
    module,quiet=load_module()
    assert hasattr(module,'WeChatDB')
    assert quiet.warning_count==0


def test_additive_shard_catches_up_without_resetting_existing_cursor():
    event=lambda n:dict(local_id=n,type='文本',content='same',create_time=None)
    db=reader({'message_0.db':[event(10),event(11)],'message_1.db':[event(n) for n in range(1,70)]})
    cur={'message_0.db':10};seen=[]
    while True:
        rows,after=query_page(db,'group',cur)
        assert len(rows)<=32
        if not rows:break
        seen.extend((r['shard'],r['local_id']) for r in rows);cur=after
    assert [n for shard,n in seen if shard=='message_0.db']==[11]
    assert [n for shard,n in seen if shard=='message_1.db']==list(range(1,70))
    assert cur=={'message_0.db':11,'message_1.db':69}
    assert len(seen)==len(set(seen))


def test_new_empty_shard_does_not_jump_checkpoint():
    event=dict(local_id=10,type='文本',content='existing',create_time=None)
    db=reader({'message_0.db':[event],'message_1.db':[]})
    before={'message_0.db':10}
    assert query_page(db,'group',before)==([],before)


def test_additive_shard_does_not_hide_missing_previous_shard():
    event=dict(local_id=1,type='文本',content='new',create_time=None)
    db=reader({'message_1.db':[event]})
    with pytest.raises(SourceError,match='source_shard_missing'):
        query_page(db,'group',{'message_0.db':10})


def test_real_upstream_cache_label_is_canonicalized():
    raw=dict(local_id=1,sort_seq=1,type='文本',content='test',create_time=None)
    db=reader({'message__message_0.db':[raw]})
    assert query_page(db,'group',None)==([],{'message_0.db':1})
    rows,after=query_page(db,'group',{'message_0.db':0})
    assert rows[0]['shard']=='message_0.db'
    assert after=={'message_0.db':1}

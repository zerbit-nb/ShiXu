"""Wire output must remain UTF-8 even on Windows cp936 console defaults."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.parametrize('suffix',['','🙂\n第二行'])
def test_worker_wire_encoding_is_independent_of_console_codepage(suffix):
    text='【接收测试】请于2026年10月18日20:00前核对测试清单。'+suffix
    code=r'''
from pathlib import Path
import scripts.wechat_worker as worker
class Reader:
    identity={'account':'a'*64,'group':'b'*64}
    def __init__(self,*args):pass
    def ensure(self):return True
    def read(self,cursors):
        return [dict(shard='message_0.db',local_id=1,kind='text',content=TEXT,sender=None,sent_at=None)],{'message_0.db':1}
    def close(self):pass
worker.Reader=Reader
worker.load_module=lambda:(None,None)
worker.install_io_guard=lambda private:None
worker.run(Path('.'))
'''
    code='TEXT='+ascii(text)+'\n'+code
    frames=[
        dict(type='configure',generation='test',profile={'group_name':'测试群','alias_hash':'c'*64,'paused':False}),
        dict(type='resume',cursors={'message_0.db':0}),
        dict(type='ack',cursors={'message_0.db':1}),
        dict(type='stop'),
    ]
    payload=''.join(json.dumps(f,ensure_ascii=False)+'\n' for f in frames).encode('utf-8')
    env={**os.environ,'PYTHONIOENCODING':'cp936:strict','PYTHONUTF8':'0'}
    result=subprocess.run([sys.executable,'-B','-c',code],input=payload,capture_output=True,
                          cwd=Path(__file__).resolve().parents[1],env=env,timeout=15)
    assert result.returncode==0,result.stderr.decode('ascii',errors='replace')
    messages=[json.loads(line) for line in result.stdout.splitlines()]
    assert [m['type'] for m in messages]==['hello','batch']
    assert messages[1]['rows'][0]['content']==text

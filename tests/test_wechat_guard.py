import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_worker_guard_blocks_network_process_and_external_writes(tmp_path):
    private=tmp_path/'private';private.mkdir()
    script="""
import socket,subprocess,sys
from pathlib import Path
from app.services.wechat_reader import install_io_guard
private=Path(sys.argv[1]).resolve()
install_io_guard(private)
(private/'allowed.txt').write_text('synthetic')
checks=0
for action in [lambda:(private.parent/'denied.txt').write_text('synthetic'),
               lambda:subprocess.Popen(['cmd','/c','echo not-allowed']),
               lambda:socket.create_connection(('127.0.0.1',1)),
               lambda:(private/'allowed.txt').rename(private.parent/'denied.txt')]:
    try:action()
    except PermissionError:checks+=1
assert checks==4
assert (private/'allowed.txt').exists()
"""
    result=subprocess.run([sys.executable,'-B','-c',script,str(private)],cwd=ROOT,capture_output=True,timeout=15,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,result.stderr.decode(errors='replace')
    assert not (tmp_path/'denied.txt').exists()

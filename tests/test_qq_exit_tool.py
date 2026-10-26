"""Standalone compatibility exit uses the existing scoped logout path."""
import sys
from types import SimpleNamespace
from scripts import exit_qq


def setup(tmp_path, monkeypatch, answer):
    image=tmp_path/'python/python.exe';image.parent.mkdir();image.touch()
    module=tmp_path/'app/services/qq_login.py';module.parent.mkdir(parents=True);module.touch()
    monkeypatch.setattr(sys,'executable',str(image))
    monkeypatch.setattr(sys,'argv',['exit_qq.py','--root',str(tmp_path)])
    monkeypatch.setattr('builtins.input',lambda _:answer)
    monkeypatch.setattr(exit_qq,'backend_stopped',lambda _:True)


def test_cancel_does_not_invoke_logout(tmp_path,monkeypatch,capsys):
    setup(tmp_path,monkeypatch,'no')
    from app.services.qq_login import QQLogin
    monkeypatch.setattr(QQLogin,'logout',lambda _: (_ for _ in ()).throw(AssertionError('must not stop')))
    assert exit_qq.main()==0
    assert '已取消' in capsys.readouterr().out


def test_confirm_reuses_logout_and_reports_only_confirmed_success(tmp_path,monkeypatch,capsys):
    setup(tmp_path,monkeypatch,'EXIT')
    from app.services.qq_login import QQLogin
    calls=[]
    async def logout(self):calls.append(self.bridge.root);return {'state':'exited'}
    monkeypatch.setattr(QQLogin,'logout',logout)
    assert exit_qq.main()==0 and calls==[tmp_path]
    assert '已确认 NapCat 退出' in capsys.readouterr().out


def test_failed_exit_is_not_success_and_does_not_leak_details(tmp_path,monkeypatch,capsys):
    setup(tmp_path,monkeypatch,'EXIT')
    from app.services.qq_login import QQLogin
    async def logout(self):raise RuntimeError('secret-private-token')
    monkeypatch.setattr(QQLogin,'logout',logout)
    assert exit_qq.main()==1
    output=capsys.readouterr().out
    assert '退出未确认' in output and 'secret' not in output


def test_untrusted_interpreter_never_stops_anything(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(sys,'argv',['exit_qq.py','--root',str(tmp_path)])
    monkeypatch.setattr('builtins.input',lambda _: (_ for _ in ()).throw(AssertionError('must not confirm')))
    assert exit_qq.main()==1


def test_running_backend_must_exit_before_offline_tool(tmp_path,monkeypatch,capsys):
    setup(tmp_path,monkeypatch,'EXIT')
    monkeypatch.setattr(exit_qq,'backend_stopped',lambda _:False)
    monkeypatch.setattr('builtins.input',lambda _: (_ for _ in ()).throw(AssertionError('must not confirm')))
    assert exit_qq.main()==1
    assert '先从托盘完整退出' in capsys.readouterr().out

"""Local Windows events for graceful shutdown; no HTTP shutdown endpoint."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import re
import sys
from uuid import uuid4
import httpx
from app.services.desktop import server_state


def kernel_api():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    definitions={
        'CreateEventW':([ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR],wintypes.HANDLE),
        'OpenEventW':([wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR],wintypes.HANDLE),
        'SetEvent':([wintypes.HANDLE],wintypes.BOOL),
        'WaitForSingleObject':([wintypes.HANDLE,wintypes.DWORD],wintypes.DWORD),
        'CloseHandle':([wintypes.HANDLE],wintypes.BOOL),
        'OpenProcess':([wintypes.DWORD,wintypes.BOOL,wintypes.DWORD],wintypes.HANDLE),
        'QueryFullProcessImageNameW':([wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)],wintypes.BOOL),
    }
    for name,(args,result) in definitions.items():
        function=getattr(kernel,name);function.argtypes=args;function.restype=result
    return kernel


class ControlSignals:
    def __init__(self,identity,create):
        if not re.fullmatch('[0-9a-f]{32}',identity):raise RuntimeError('后台退出控制标识无效。')
        self.identity=identity;self.kernel=kernel_api();self.handles={}
        try:
            for label in ('stop','success','failed'):
                name=r'Local\CampusFlowBackend-'+identity+'-'+label
                handle=(self.kernel.CreateEventW(None,True,False,name) if create
                        else self.kernel.OpenEventW(0x00100002,False,name))
                if not handle:raise RuntimeError('后台没有可用的退出通道。请在原控制台停止后重新启动桌面版。')
                self.handles[label]=handle
        except Exception:
            self.close();raise
    @classmethod
    def create(cls):return cls(uuid4().hex,True)
    @classmethod
    def open(cls,identity):return cls(identity,False)
    def _set(self,label):
        if not self.kernel.SetEvent(self.handles[label]):raise ctypes.WinError(ctypes.get_last_error())
    def _wait(self,label,milliseconds):
        result=self.kernel.WaitForSingleObject(self.handles[label],milliseconds)
        if result==0xFFFFFFFF:raise ctypes.WinError(ctypes.get_last_error())
        return result==0
    def request_stop(self):self._set('stop')
    def wait_stop(self,milliseconds):return self._wait('stop',milliseconds)
    def finish(self,success):self._set('success' if success else 'failed')
    def succeeded(self):return self._wait('success',0)
    def failed(self):return self._wait('failed',0)
    def close(self):
        for handle in self.handles.values():self.kernel.CloseHandle(handle)
        self.handles.clear()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


def trusted_backend_image(root,image):
    root=Path(root)
    # Windows venv redirectors run the base interpreter as a child process.
    allowed={root/'.venv/Scripts/python.exe',root/'.venv/Scripts/pythonw.exe',
             Path(sys.executable),Path(sys._base_executable)}
    return Path(image).resolve() in {p.resolve() for p in allowed}


def stop_backend(root,url='http://127.0.0.1:8000',timeout=45,require_verified=False):
    """Verify workspace, control generation and process, then wait for cleanup + exit."""
    root=Path(root)
    with httpx.Client(trust_env=False,timeout=3) as client:
        state=server_state(root,url,client)
        if state=='stopped':
            if require_verified:raise RuntimeError('上次退出未确认清理完成。请检查微信临时缓存，并通过原启动入口重新启动后台后重试。')
            return
        if state!='ready':raise RuntimeError('后台身份不匹配，未发送退出请求。')
        data=client.get(url+'/api/health').json()
        expected=hashlib.sha256(str((root/'config.local.json').resolve()).encode()).hexdigest()
        if data.get('application')!='CampusFlow' or data.get('instance')!=expected:
            raise RuntimeError('后台身份发生变化，未发送退出请求。')
        control=data.get('desktop_control') or {}
        pid=control.get('pid')
        if type(pid) is not int or pid<=0 or pid==os.getpid():
            raise RuntimeError('此后台不支持桌面退出。请在原控制台停止后重新启动桌面版。')
        with ControlSignals.open(control.get('identity','')) as signals:
            kernel=signals.kernel
            process=kernel.OpenProcess(0x00101000,False,pid)
            if not process:raise RuntimeError('无法验证后台进程，请重试；未强制停止任何进程。')
            try:
                size=wintypes.DWORD(32768);image=ctypes.create_unicode_buffer(size.value)
                if not kernel.QueryFullProcessImageNameW(process,0,image,ctypes.byref(size)):
                    raise RuntimeError('无法核对后台进程路径，未发送退出请求。')
                if not trusted_backend_image(root,image.value):
                    raise RuntimeError('后台进程路径不匹配，未发送退出请求。')
                if client.get(url+'/api/health').json().get('desktop_control')!=control:
                    raise RuntimeError('后台会话已变化，请重试。')
                signals.request_stop()
                result=kernel.WaitForSingleObject(process,int(timeout*1000))
                if result!=0:raise RuntimeError('后台退出超时。窗口已保留，请检查接收状态后重试。')
                if signals.failed() or not signals.succeeded():
                    raise RuntimeError('后台已停止，但未确认资源清理成功。请检查微信临时缓存后重新启动；本次退出未完成。')
                if server_state(root,url,client)!='stopped':
                    raise RuntimeError('后台端口仍有服务运行，窗口已保留，请检查后重试。')
            finally:kernel.CloseHandle(process)


class BackendStopper:
    """Keep a failed shutdown from becoming success just because its port closed."""
    def __init__(self,root):
        self.root=root;self.require_verified=False
    def __call__(self):
        try:stop_backend(self.root,require_verified=self.require_verified)
        except Exception:
            self.require_verified=True
            raise

"""Single child, bounded pipe, synchronous transactional commit on the app event loop."""
import asyncio
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from app.services import wechat_store as store

MAX_FRAME = 4*1024*1024
ROOT = Path(__file__).resolve().parents[2]
MESSAGES = {
    'not_configured':'请先设置微信号和目标群。',
    'busy':'另一个微信采集器正在运行。',
    'configure_while_running':'请先停止采集再修改配置。',
    'not_logged_in':'等待电脑微信登录。',
    'wechat_offline':'电脑微信已退出，等待恢复。',
    'account_changed':'当前微信账号不匹配，采集已停止。',
    'identity_changed':'账号或群标识变化，采集已停止。',
    'group_not_unique':'目标群不存在或有重名，请核对群名。',
    'source_rewound':'来源消息编号回退，已停止；请检查微信数据是否被恢复。',
    'source_shard_missing':'来源分片缺失，已停止；请检查微信数据是否完整。',
    'snapshot_warning':'来源快照不完整，正在有限重试。',
    'process_changed':'微信进程正在切换，等待重新验证。',
    'disk_budget_exceeded':'磁盘空间不足或数据超过读取上限。',
    'source_hash_mismatch':'读取模块校验失败，请恢复固定版本。',
    'missing_dependency':'微信读取依赖缺失，请安装 requirements-wechat.txt。',
    'database_error':'消息提交失败，读取位置未确认；排除数据库故障后重新启动采集。',
    'cleanup_failed':'实验工作进程或临时缓存清理失败，请检查本机进程和目录。',
    'source_timeout':'读取进程超时，已停止；请检查微信后重新启动采集。',
    'invalid_config':'微信配置不可读取，请重新设置。',
    'config_write_failed':'采集已停止，但暂停状态保存失败；请检查磁盘和权限。',
    'offline_retry_limit':'微信持续离线，采集已停止；登录后重新启动采集。',
    'source_shard_set_changed':'消息分片发生变化，已停止；需要重新核对分片与读取位置。',
    'database_root_not_found':'等待可用的微信数据目录，请确认电脑微信已登录。',
    'keys_incomplete':'微信数据库暂不可读，请确认登录状态和程序权限。',
    'contact_missing':'微信资料库不可用，请确认登录状态。',
    'profile_changed':'当前配置与既有接收绑定不一致，请检查账号及群配置。',
    'source_identity_reused':'来源消息标识对应的内容发生变化，已停止以保护已有记录。',
    'checkpoint_jump':'读取位置与本批消息不一致，采集已停止。',
    'stale_checkpoint':'读取位置发生冲突，采集已停止。',
    'source_error':'微信读取异常，采集已停止；请检查微信后重试。',
}

class MonitorError(ValueError):
    pass

class SavedConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    group_name:str=Field(default='',max_length=200)
    alias_hash:str=Field(default='',pattern=r'^([0-9a-f]{64})?$')
    paused:bool=True


def protect_directory(path):
    if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
        raise MonitorError('cleanup_failed')
    path.mkdir(parents=True,exist_ok=True)
    if os.name=='nt':
        user=os.environ.get('USERDOMAIN','')+'\\'+getpass.getuser()
        command=['icacls',str(path),'/inheritance:r','/grant:r',user+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F']
        result=subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
        if result.returncode:raise MonitorError('cleanup_failed')
    else:path.chmod(0o700)


def safe_cleanup(path,root):
    if path.parent.resolve()!=root.resolve() or not path.name.startswith('session-') or path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
        raise MonitorError('cleanup_failed')
    shutil.rmtree(path)


def pid_alive(pid):
    if type(pid) is not int or pid<=0:return True
    if os.name!='nt':
        try:os.kill(pid,0);return True
        except ProcessLookupError:return False
        except PermissionError:return True
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x00100000,False,pid)
    if not handle:return ctypes.get_last_error()!=87
    try:return kernel.WaitForSingleObject(handle,0)!=0
    finally:kernel.CloseHandle(handle)


def clean_stale_sessions(root):
    for path in root.glob('session-*'):
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
            raise MonitorError('cleanup_failed')
        try:owner=json.loads((path/'owner.json').read_text(encoding='utf-8'))
        except (ValueError,OSError):raise MonitorError('cleanup_failed') from None
        if pid_alive(owner.get('worker_pid')):raise MonitorError('busy')
        safe_cleanup(path,root)


class Lease:
    def __init__(self,path):
        self.file=path.open('a+b')
        self.file.seek(0,2)
        if self.file.tell()==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise MonitorError('busy') from None
    def close(self):self.file.close()


class WeChatMonitor:
    def __init__(self,db,path):
        self.db,self.path=db,Path(path)
        self.root=self.path.parent/'runtime/wechat-receiver'
        self.lock=asyncio.Lock();self.task=None;self.generation=None
        self.state='paused';self.reason=None;self.gap_possible=False;self.diagnostic=None
        self.private=None;self.lease=None;self.proc=None
        self.config=SavedConfig()
        try:
            if self.path.exists():self.config=SavedConfig.model_validate_json(self.path.read_text(encoding='utf-8'))
        except (ValueError,OSError):self.reason='invalid_config'
        # A server restart always requires explicit start, even after an unclean exit.
        self.config.paused=True
        self.spawn=self._spawn
    def public_config(self):
        return {'group_name':self.config.group_name,'has_account':bool(self.config.alias_hash),'paused':self.state not in {'starting','listening','waiting'}}
    def status(self):
        count=self.db.conn.execute('SELECT count(*) FROM wechat_receipts WHERE message_id IS NOT NULL').fetchone()[0]
        return {**self.public_config(),'state':self.state,'reason':self.reason,
                'message':MESSAGES.get(self.reason) if self.reason else None,
                'diagnostic':self.diagnostic,'received_count':count,'gap_possible':self.gap_possible,'auto_start':False}
    def _save(self):
        temp=self.path.with_suffix('.tmp')
        temp.write_text(self.config.model_dump_json(),encoding='utf-8');temp.replace(self.path)
    async def configure(self,group_name,account_alias):
        async with self.lock:
            if self.state=='stopping' or (self.task and not self.task.done()):raise MonitorError('configure_while_running')
            group_name,account_alias=group_name.strip(),account_alias.strip()
            if not group_name or not account_alias:raise MonitorError('not_configured')
            old=self.config
            self.config=SavedConfig(group_name=group_name,alias_hash=hashlib.sha256(account_alias.encode()).hexdigest())
            try:self._save()
            except OSError:
                self.config=old
                raise
            self.reason=None;self.state='paused'
            return self.public_config()
    async def start(self):
        async with self.lock:
            if self.state=='stopping' or (self.task and not self.task.done()):return self.status()
            if self.reason=='cleanup_failed':raise MonitorError('cleanup_failed')
            if not self.config.alias_hash or not self.config.group_name:raise MonitorError('not_configured')
            # No WeChat data exists here until after the protected ACL and lock succeed.
            await asyncio.to_thread(protect_directory,self.root)
            self.lease=Lease(self.root/'receiver.lock')
            try:
                clean_stale_sessions(self.root)
                self.private=self.root/('session-'+uuid4().hex);self.private.mkdir()
                (self.private/'owner.json').write_text(json.dumps({'worker_pid':None}),encoding='utf-8')
                self.config.paused=False;self._save()
                self.generation=uuid4().hex;self.state='starting';self.reason=None;self.diagnostic=None
                self.task=asyncio.create_task(self._run(self.generation,self.config.model_dump(),self.private))
            except Exception:
                self.config.paused=True
                self.lease.close();self.lease=None
                if self.private and self.private.exists():safe_cleanup(self.private,self.root)
                raise
            await asyncio.sleep(0)  # Ensure the child supervisor has entered its cleanup scope.
            return self.status()
    async def stop(self):
        async with self.lock:
            if self.state=='stopping':return self.status()
            self.config.paused=True
            persistence_failed=False
            try:
                if self.path.exists():self._save()
            except OSError:persistence_failed=True
            self.generation=None
            task=self.task
            if task and not task.done():self.state='stopping';task.cancel()
        if task and not task.done():
            try:await task
            except asyncio.CancelledError:pass
        async with self.lock:
            if self.reason!='cleanup_failed':
                self.state='error' if persistence_failed else 'paused'
                self.reason='config_write_failed' if persistence_failed else None
            return self.status()
    async def _spawn(self,private):
        return await asyncio.create_subprocess_exec(sys.executable,'-B','-m','scripts.wechat_worker',str(private),
            cwd=str(ROOT),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,limit=MAX_FRAME,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    async def _send(self,proc,value):
        proc.stdin.write((json.dumps(value,ensure_ascii=False)+'\n').encode('utf-8'));await proc.stdin.drain()
    async def _run(self,generation,profile,private):
        proc=None;scope=None;phase='spawn'
        try:
            launch=asyncio.create_task(self.spawn(private))
            try:proc=await asyncio.shield(launch)
            except asyncio.CancelledError:
                proc=await launch
                raise
            self.proc=proc
            (private/'owner.json').write_text(json.dumps({'worker_pid':proc.pid}),encoding='utf-8')
            await self._send(proc,dict(type='configure',generation=generation,profile=profile))
            while True:
                phase='read_frame'
                line=await asyncio.wait_for(proc.stdout.readline(),timeout=90)
                if not line or len(line)>MAX_FRAME:raise MonitorError('source_error')
                frame=json.loads(line)
                async with self.lock:
                    if generation!=self.generation:return
                    if frame.get('generation')!=generation:raise MonitorError('source_error')
                    kind=frame.get('type');phase='handle_frame'
                    if kind=='hello':
                        if scope is not None:raise MonitorError('source_error')
                        scope=store.bind(self.db,profile,frame['identity'])
                        await self._send(proc,dict(type='resume',cursors=store.checkpoint(self.db,scope)))
                    elif kind=='baseline':
                        if scope is None:raise MonitorError('source_error')
                        store.baseline(self.db,scope,frame['cursors'])
                        await self._send(proc,dict(type='ack',cursors=store.checkpoint(self.db,scope)))
                        self.state='listening';self.reason=None
                    elif kind=='batch':
                        if scope is None:raise MonitorError('source_error')
                        after=store.commit_batch(self.db,scope,profile,frame['before'],frame['rows'],frame['after'])
                        await self._send(proc,dict(type='ack',cursors=after))
                        self.state='listening';self.reason=None
                    elif kind=='status' and frame.get('state') in {'waiting','listening'}:
                        if frame['state']=='listening' and scope is None:raise MonitorError('source_error')
                        self.state=frame['state']
                        code=frame.get('reason')
                        self.reason=code if code in MESSAGES else ('source_error' if code else None)
                        self.gap_possible=self.gap_possible or self.state=='waiting'
                    elif kind=='error':
                        supplied=frame.get('diagnostic',{})
                        if supplied.get('stage') in {'load','connect','query','ack'} and supplied.get('type') in {'ValueError','TypeError','RuntimeError','PermissionError','FileNotFoundError','KeyError','AttributeError','ImportError','OSError'}:
                            self.diagnostic={'stage':supplied['stage'],'type':supplied['type']}
                        code=frame.get('reason')
                        raise MonitorError(code if code in MESSAGES else 'source_error')
                    else:raise MonitorError('source_error')
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            import sqlite3
            code=exc.args[0] if isinstance(exc,ValueError) and exc.args and isinstance(exc.args[0],str) else None
            self.reason=code if code in MESSAGES else ('database_error' if isinstance(exc,sqlite3.Error) else 'source_timeout' if isinstance(exc,TimeoutError) else 'source_error')
            self.state='error'
            if self.diagnostic is None:self.diagnostic={'stage':phase,'type':type(exc).__name__}
        finally:
            cleaned=True
            if proc is not None:
                try:
                    await self._send(proc,dict(type='stop'))
                    await asyncio.wait_for(proc.wait(),timeout=5)
                except Exception:
                    if proc.returncode is None:
                        try:
                            proc.kill()
                            await asyncio.wait_for(proc.wait(),timeout=5)
                        except Exception:cleaned=False
                try:proc.stdin.close()
                except Exception:pass
            if cleaned:
                for attempt in range(3):
                    try:
                        if private.exists():safe_cleanup(private,self.root)
                        break
                    except (OSError,MonitorError):
                        if attempt==2:cleaned=False
                        else:await asyncio.sleep(.2)
            if cleaned:
                if self.lease:self.lease.close();self.lease=None
            else:self.reason='cleanup_failed';self.state='error'
            self.proc=None;self.generation=None

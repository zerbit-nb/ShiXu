"""Isolated read adapter. Imported by the child only; never loads upstream __init__."""
from pathlib import Path
from datetime import datetime, timezone
import contextlib, hashlib, importlib.util, json, os, re, shutil, subprocess, sys, time, types
from app.services.wechat_store import MAX_BATCH, marks

SOURCE=Path(__file__).resolve().parents[2]/'third_party/wechat_db/db.py'
SOURCE_SHA='1b8958a0e9a3f8d6c2f8fe89acd72c14bb542c3c16635c31b52e05c0f19b247b'

class SourceError(ValueError):
    pass

class QuietLogger:
    def __init__(self): self.warning_count=0
    def debug(self,*a,**k): pass
    info=debug
    def warning(self,*a,**k): self.warning_count+=1
    error=warning

def inside(path,root):
    try: Path(path).resolve().relative_to(Path(root).resolve());return True
    except (ValueError,TypeError,OSError):return False

def load_module():
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest()!=SOURCE_SHA:
        raise SourceError('source_hash_mismatch')
    package=types.ModuleType('wechatauto');package.__path__=[]
    logger=types.ModuleType('wechatauto.logger');logger.wxlog=QuietLogger()
    sys.modules['wechatauto']=package;sys.modules['wechatauto.logger']=logger
    spec=importlib.util.spec_from_file_location('campusflow_wxdb',SOURCE)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module,logger.wxlog

def reader_class(module):
    class RestrictedDB(module.WeChatDB):
        def _collect_db_files(self):
            files = super()._collect_db_files()
            return [(r, p, z) for r, p, z in files if
                    r.replace('\\', '/') == 'contact/contact.db' or
                    re.fullmatch(r'message/message_\d+\.db', r.replace('\\', '/'))]
        def _load_or_extract_keys(self, master_key=None):
            # Use the upstream primary read-only extractor; no stored caches,
            # old-version master-key fallback, or automatic account switching.
            self._keys = self.extract_keys()
            self._keys = {r: k for r, k in self._keys.items() if self._key_works(r)}
            self.unkeyed = [r for r, _, _ in self._db_files if r not in self._keys]
        def _save_keys(self):
            pass
        def _stable_key_dirs(self):
            return []
        def _load_key_cache(self, path):
            return {}
        def _try_other_accounts(self):
            return False
        def _select_account_by_keys(self, candidates):
            return False
        def _auto_diagnose_key_failure(self, rel):
            pass
    return RestrictedDB


def allowed_command(command):
    expected = ['tasklist', '/FI', 'IMAGENAME eq Weixin.exe', '/FO', 'CSV', '/NH']
    return (list(command) == expected if isinstance(command, (tuple, list))
            else command == subprocess.list2cmdline(expected))


def install_io_guard(private):
    def audit(event, args):
        if event in {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'os.system'}:
            raise PermissionError('network_or_shell_disabled')
        if event == 'subprocess.Popen':
            command = args[1]
            if not allowed_command(command):
                raise PermissionError('unexpected_child_process')
        if event == 'open':
            path, mode, flags = args
            write = (any(ch in (mode or '') for ch in 'wax+') or
                     flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if write and not isinstance(path, int):
                if not inside(path, private):
                    raise PermissionError('write_outside_private_cache')
        if event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.rename'}:
            paths = args[:2] if event == 'os.rename' else args[:1]
            if any(not inside(p, private) for p in paths):
                raise PermissionError('filesystem_mutation_outside_private_cache')
    sys.addaudithook(audit)


def match_live_account(module, accounts):
    # Compare only the contact database first-page HMAC against keys in the
    # current running client. No cache, no message decryption, no mtime guess.
    probe = module.WeChatDB.__new__(module.WeChatDB)
    probe._db_files = []
    for i, account in enumerate(accounts):
        contact = Path(account) / 'db_storage' / 'contact' / 'contact.db'
        if contact.is_file():
            probe._db_files.append((str(i), str(contact), contact.stat().st_size))
    keys = probe.extract_keys()
    try:
        matches = [int(index) for index in keys]
        return matches
    finally:
        keys.clear()



def canonical_shard(value):
    match=re.fullmatch(r'(?:message__)?message_([0-9]+)[.]db',value or '')
    if not match:raise SourceError('invalid_shard_set')
    return 'message_'+match[1]+'.db'


def to_event(row):
    event={'shard':canonical_shard(row['shard']),'local_id':row['local_id'],'kind':'unsupported','content':'','sender':None,'sent_at':None}
    if row.get('type')=='文本' and isinstance(row.get('content'),str) and row['content'].strip():
        stamp=row.get('create_time')
        sent_at=datetime.fromtimestamp(stamp,timezone.utc).isoformat() if type(stamp) is int and 946684800<=stamp<=4102444800 else None
        event.update(kind='text',content=row['content'],sender=row.get('sender_username') or None,sent_at=sent_at)
    return event


def query_page(db,group,cursors):
    """Each shard's local_id, not a global sort_seq or a recent-message window."""
    if cursors is not None: marks(cursors)
    def build(tables):
        found={canonical_shard(db._shard_label(conn)) for conn,table in tables}
        if len(found)!=len(tables) or len(found)>32:
            raise SourceError('invalid_shard_set')
        if cursors is not None and not set(cursors)<=found:
            raise SourceError('source_shard_missing')
        # Additive shards catch up from local_id 0; never reset old cursors.
        # Missing shards and rewinds still fail closed. Commit/ACK stays transactional.
        maps=db._shard_maps(tables) if cursors is not None else None
        after=dict(cursors or {});events=[]
        quota=max(1,MAX_BATCH//max(len(tables),1))
        for conn,table in tables:
            shard=canonical_shard(db._shard_label(conn))
            maximum=conn.execute('SELECT coalesce(max(local_id),0) FROM '+table).fetchone()[0]
            if cursors is None:
                after[shard]=maximum;continue
            previous=cursors.get(shard,0)
            if maximum<previous: raise SourceError('source_rewound')
            rows=db._shard_rows([(conn,table)],'WHERE local_id > ?',(previous,),
                               order_ext='ORDER BY local_id ASC',per_shard_limit=quota)
            for row in rows:
                event=to_event(db._msg_row_to_dict(row,maps))
                if event['local_id']<=after.get(shard,0):raise SourceError('unordered_source')
                events.append(event);after[shard]=event['local_id']
        return events,after
    result=db._run_msg_query(group,build)
    if result is None:
        if cursors:raise SourceError('source_shard_missing')
        return [],{}
    return result


class Reader:
    def __init__(self,module,quiet,profile,cache):
        self.module,self.quiet,self.profile,self.cache=module,quiet,profile,cache
        self.db=None;self.validated=frozenset();self.identity=None;self.last_check=0
        self.pid_reader=module.WeChatDB.__new__(module.WeChatDB)
    def pids(self):return frozenset(self.pid_reader._find_weixin_pids())
    def close(self):
        if self.db is not None:self.db._keys.clear();self.db=None
    def ensure(self):
        pids=self.pids()
        if not pids:
            self.close();self.validated=frozenset();return False
        if self.db is None or pids!=self.validated or time.monotonic()-self.last_check>=30:
            self.close()
            if self.cache.exists():shutil.rmtree(self.cache)
            self.cache.mkdir()
            self.quiet.warning_count=0
            root=self.module.auto_detect_db_dir()
            if not root:raise SourceError('database_root_not_found')
            accounts=self.module._find_account_dirs(root)
            matching=match_live_account(self.module,accounts)
            if len(matching)!=1:raise SourceError('not_logged_in')
            account=Path(accounts[matching[0]]).name
            cls=reader_class(self.module)
            metadata=cls.__new__(cls);metadata.account_dir=str(Path(root)/account)
            size=sum(z for _,_,z in metadata._collect_db_files())
            if size>2*1024**3 or shutil.disk_usage(self.cache).free<size*4+512*1024**2:
                raise SourceError('disk_budget_exceeded')
            db=cls(db_dir=root,account=account,workdir=str(self.cache),keys_file=str(self.cache/'disabled-keys.json'))
            self.db=db
            if db.unkeyed:raise SourceError('keys_incomplete')
            contact=next((r for r,_,_ in db._db_files if r.replace('\\','/')=='contact/contact.db'),None)
            if not contact:raise SourceError('contact_missing')
            with contextlib.closing(db._open(contact)) as conn:
                row=conn.execute('SELECT alias FROM contact WHERE username=?',(db.wxid,)).fetchone()
                if not row or hashlib.sha256((row[0] or '').encode()).hexdigest()!=self.profile['alias_hash']:
                    raise SourceError('account_changed')
                groups=conn.execute("SELECT username FROM contact WHERE username LIKE '%@chatroom' AND (nick_name=? OR remark=?)",
                                    (self.profile['group_name'],self.profile['group_name'])).fetchall()
            if len(groups)!=1:raise SourceError('group_not_unique')
            group=groups[0][0]
            identity={'account':hashlib.sha256(account.encode()).hexdigest(),'group':hashlib.sha256(group.encode()).hexdigest()}
            if self.identity is not None and self.identity!=identity:raise SourceError('identity_changed')
            if self.pids()!=pids:raise SourceError('process_changed')
            if self.quiet.warning_count:raise SourceError('snapshot_warning')
            self.identity,self.group,self.validated,self.last_check=identity,group,pids,time.monotonic()
        return True
    def read(self,cursors):
        if self.db is None:raise SourceError('not_logged_in')
        self.quiet.warning_count=0
        # Upstream suppresses repeated warnings; rearm to reject every partial snapshot.
        self.db._warned_keys=set()
        value=query_page(self.db,self.group,cursors)
        if self.pids()!=self.validated:raise SourceError('process_changed')
        if self.quiet.warning_count:raise SourceError('snapshot_warning')
        if sum(p.stat().st_size for p in self.cache.rglob('*') if p.is_file())>8*1024**3:
            raise SourceError('disk_budget_exceeded')
        return value

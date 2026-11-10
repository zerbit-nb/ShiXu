"""Private stdin/stdout protocol. One <=32-row batch in flight, never a public webhook."""
import contextlib
import json
import os
from pathlib import Path
import queue
import sys
import threading
from datetime import datetime, timezone
from app.services.wechat_reader import Reader, SourceError, load_module, install_io_guard
from app.services.wechat_monitor import SavedConfig, MAX_FRAME
from app.services.wechat_groups import group_profiles


def run(private):
    # Use explicit UTF-8 bytes rather than the Windows console encoding.
    output=sys.stdout.buffer
    commands=queue.Queue(maxsize=1)
    # Raw reads avoid buffered stdin locks during interpreter shutdown.
    input_pipe=sys.stdin.buffer.raw
    def read_commands():
        try:
            while True:
                raw=input_pipe.readline(MAX_FRAME+1)
                if not raw:commands.put({'type':'stop'});return
                if len(raw)>MAX_FRAME:raise ValueError()
                value=json.loads(raw)
                commands.put(value)
                if value.get('type')=='stop':return
        except Exception:commands.put({'type':'stop'})
    threading.Thread(target=read_commands,daemon=True).start()
    initial=commands.get(timeout=90)
    if initial.get('type')!='configure':return
    generation=initial['generation']
    profile=SavedConfig.model_validate(initial['profile']).model_dump()
    def emit(kind,**value):
        raw=(json.dumps(dict(type=kind,generation=generation,**value),ensure_ascii=False)+'\n').encode('utf-8')
        if len(raw)>MAX_FRAME:raise SourceError('frame_too_large')
        output.write(raw);output.flush()
    def command(timeout):
        try:value=commands.get(timeout=timeout)
        except queue.Empty:return None
        if value.get('type')=='stop':raise SystemExit(0)
        return value
    reader=None;phase='load'
    with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink),contextlib.redirect_stderr(sink):
        try:
            module,quiet=load_module()
            install_io_guard(private)
            reader=Reader(module,quiet,profile,private/'cache')
            if initial.get('mode')=='groups':
                phase='connect'
                if not reader.ensure(discovery=True):raise SourceError('not_logged_in')
                emit('groups',groups=reader.available_groups)
                return
            cursors={};handshakes=set();retries=0;history_open=set()
            profiles=group_profiles(profile)
            while True:
                try:
                    phase='connect'
                    if not reader.ensure():
                        emit('status',state='waiting',reason='wechat_offline')
                        retries+=1
                        if retries>=30:raise SourceError('offline_retry_limit')
                        if command(5) is not None:raise SourceError('unexpected_command')
                        continue
                    activity=False
                    for group_id in profiles:
                        tagged={'group_id':group_id} if group_id else {}
                        if group_id not in handshakes:
                            identity=reader.identities[group_id] if group_id else reader.identity
                            emit('hello',identity=identity,**tagged)
                            reply=command(90)
                            if reply is None or reply.get('type')!='resume' or reply.get('group_id','')!=group_id:
                                raise SourceError('invalid_resume')
                            cursors[group_id]=reply['cursors'];handshakes.add(group_id)
                            if reply.get('history_since'):
                                history_open.add(group_id)
                                # Snapshot the live baseline BEFORE scanning history.
                                # Messages arriving during the scan are read after it.
                                _,boundary=reader.read(None,group_id=group_id) if group_id else reader.read(None)
                                until=datetime.now(timezone.utc).isoformat()
                                emit('history_started',until=until,**tagged)
                                history_cursors={};complete=False
                                for _ in range(313):
                                    rows,after=reader.history(history_cursors,boundary,reply['history_since'],until,group_id=group_id)
                                    if not rows:
                                        complete=True;break
                                    emit('history_batch',rows=rows,**tagged)
                                    ack=command(90)
                                    if ack is None or ack.get('type')!='history_ack' or ack.get('group_id','')!=group_id:
                                        raise SourceError('invalid_ack')
                                    history_cursors=after
                                emit('history_done',complete=complete,**tagged)
                                history_open.discard(group_id)
                                if cursors[group_id] is None:
                                    emit('baseline',cursors=boundary,**tagged)
                                    ack=command(90)
                                    if ack is None or ack.get('type')!='ack' or ack.get('cursors')!=boundary or ack.get('group_id','')!=group_id:
                                        raise SourceError('invalid_ack')
                                    cursors[group_id]=boundary
                        phase='query'
                        before=cursors[group_id]
                        rows,after=reader.read(before,group_id=group_id) if group_id else reader.read(before)
                        if before is None:
                            emit('baseline',cursors=after,**tagged)
                        elif rows:
                            emit('batch',before=before,rows=rows,after=after,**tagged)
                        else:continue
                        activity=True
                        phase='ack'
                        reply=command(90)
                        if reply is None or reply.get('type')!='ack' or reply.get('cursors')!=after or reply.get('group_id','')!=group_id:
                            raise SourceError('invalid_ack')
                        cursors[group_id]=after
                    if not activity:emit('status',state='listening',reason=None)
                    retries=0
                    if command(2) is not None:raise SourceError('unexpected_command')
                except SourceError as exc:
                    for pending_group in history_open:
                        emit('history_done',complete=False,**({'group_id':pending_group} if pending_group else {}))
                    history_open.clear()
                    reason=exc.args[0]
                    if reason not in {'process_changed','snapshot_warning','not_logged_in','database_root_not_found','keys_incomplete','contact_missing'}:
                        raise
                    reader.close();retries+=1
                    if retries>=30:raise
                    emit('status',state='waiting',reason=reason)
                    if command(5) is not None:raise SourceError('unexpected_command')
        except SystemExit:
            pass
        except ModuleNotFoundError:
            emit('error',reason='missing_dependency')
        except SourceError as exc:
            emit('error',reason=exc.args[0])
        except Exception as exc:
            emit('error',reason='source_error',diagnostic={'stage':phase,'type':type(exc).__name__})
        finally:
            if reader is not None:reader.close()


if __name__=='__main__':
    private=Path(sys.argv[1]).resolve()
    if private.parent.name!='wechat-receiver' or not private.name.startswith('session-') or not private.is_dir():
        raise SystemExit(2)
    run(private)

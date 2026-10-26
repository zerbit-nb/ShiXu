"""Private stdin/stdout protocol. One <=32-row batch in flight, never a public webhook."""
import contextlib
import json
import os
from pathlib import Path
import queue
import sys
import threading
from app.services.wechat_reader import Reader, SourceError, load_module, install_io_guard
from app.services.wechat_monitor import SavedConfig, MAX_FRAME


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
    def acknowledge(after):
        value=command(90)
        if value is None or value.get('type')!='ack' or value.get('cursors')!=after:
            raise SourceError('invalid_ack')
    reader=None;phase='load'
    with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink),contextlib.redirect_stderr(sink):
        try:
            module,quiet=load_module()
            install_io_guard(private)
            reader=Reader(module,quiet,profile,private/'cache')
            cursors=None;handshake=False;retries=0
            while True:
                try:
                    phase='connect'
                    if not reader.ensure():
                        emit('status',state='waiting',reason='wechat_offline')
                        retries+=1
                        if retries>=30:raise SourceError('offline_retry_limit')
                        if command(5) is not None:raise SourceError('unexpected_command')
                        continue
                    if not handshake:
                        emit('hello',identity=reader.identity)
                        reply=command(90)
                        if reply is None or reply.get('type')!='resume':raise SourceError('invalid_resume')
                        cursors=reply['cursors'];handshake=True
                    phase='query'
                    rows,after=reader.read(cursors)
                    if cursors is None:
                        emit('baseline',cursors=after);acknowledge(after);cursors=after
                    elif rows:
                        emit('batch',before=cursors,rows=rows,after=after)
                        acknowledge(after);cursors=after
                    else:emit('status',state='listening',reason=None)
                    retries=0
                    if command(2) is not None:raise SourceError('unexpected_command')
                except SourceError as exc:
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

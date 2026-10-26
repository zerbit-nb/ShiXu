"""Atomic management of explicitly reviewed completed tasks."""
from fastapi import APIRouter, HTTPException, Request
from app.database import utc_now
from app.schemas import CompletedTaskOperation
from app.services.task_changes import task_version

router = APIRouter()


@router.post('/api/completed-tasks/manage')
async def manage_completed(body: CompletedTaskOperation, request: Request):
    if not body.confirmed:
        raise HTTPException(422, '请先确认本次操作')
    ids = [task.id for task in body.tasks]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, '任务选择不能重复')
    db = request.app.state.db
    with db.conn:
        db.conn.execute('BEGIN IMMEDIATE')
        for target in body.tasks:
            task = db.get_task(target.id)
            if not task or task['status'] != 'completed' or task_version(task) != target.version:
                raise HTTPException(409, '所选任务已变化，请刷新后重新选择；本次未修改任何任务。')
        for target in body.tasks:
            if body.action == 'delete':
                db.conn.execute('DELETE FROM tasks WHERE id=?', (target.id,))
            else:
                db.conn.execute("UPDATE tasks SET status='pending', updated_at=? WHERE id=?", (utc_now(), target.id))
    return {'ok': True, 'affected': len(ids)}

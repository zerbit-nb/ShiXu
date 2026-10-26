from datetime import date, datetime, timedelta
from app.services.time_parser import TZ


def annotate(task, now=None, hours=24):
    now = now or datetime.now(TZ)
    result = {**task, 'reminder': None}
    value = task.get('deadline')
    if task['status'] != 'pending' or not value:
        return result
    if len(value) == 10:
        day = date.fromisoformat(value)
        result['reminder'] = 'overdue' if day < now.date() else ('today' if day == now.date() else None)
    else:
        deadline = datetime.fromisoformat(value).astimezone(TZ)
        if deadline < now:
            result['reminder'] = 'overdue'
        elif deadline <= now + timedelta(hours=hours):
            result['reminder'] = 'soon'
        elif deadline.date() == now.date():
            result['reminder'] = 'today'
    return result


def matches_view(task, view, now=None):
    today = (now or datetime.now(TZ)).date()
    value = task.get('deadline')
    if view == 'no_deadline':
        return task['status'] == 'pending' and not value
    if view in {'today', 'week', 'overdue'}:
        if task['status'] != 'pending' or not value:
            return False
        day = date.fromisoformat(value[:10])
        if view == 'today': return day == today
        if view == 'week': return today <= day < today + timedelta(days=7)
        return task['reminder'] == 'overdue'
    return True

from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Any

TZ = timezone(timedelta(hours=8), name='Asia/Shanghai')


def _iso(value: date | datetime) -> str:
    if isinstance(value, datetime):
        return value.astimezone(TZ).isoformat(timespec='seconds')
    return value.isoformat()


def parse_deadline(text: str | None, reference: datetime | None) -> dict[str, Any]:
    if not text:
        return {'deadline': None, 'warning': None}
    value = text.strip()
    ref = (reference.replace(tzinfo=TZ) if reference.tzinfo is None else reference.astimezone(TZ)) if reference else None
    if re.search(r'尽快|尽早|有空|今晚|上午|下午|晚上|中午|凌晨', value):
        return {'deadline': None, 'warning': '原文没有足够信息确定具体日期或时间，请确认。'}
    if re.search(r'明天|后天|本周|下周', value) and ref is None:
        return {'deadline': None, 'warning': '相对日期需要消息发送时间作为参照。'}
    if re.search(r'或|至|到|~|～|—', value):
        return {'deadline': None, 'warning': '原文包含多个可能的截止时间，请确认。'}
    target: date | datetime | None = None
    if ref and '后天' in value:
        target = ref + timedelta(days=2)
    elif ref and '明天' in value:
        target = ref + timedelta(days=1)
    elif ref and ('下周一' in value or '下星期一' in value):
        target = ref.date() + timedelta(days=(7 - ref.weekday()))
    elif ref and ('本周五' in value or '本星期五' in value):
        days = 4 - ref.weekday()
        target = ref.date() + timedelta(days=days)
    else:
        week = re.search(r'(本|下)(?:周|星期)([一二三四五六日天])', value)
        if week and ref:
            weekday = '一二三四五六日'.index(week[2].replace('天', '日'))
            target = ref.date() + timedelta(days=weekday-ref.weekday() + (7 if week[1] == '下' else 0))
        elif ref and '今天' in value:
            target = ref.date()
    if len(re.findall(r'\d{4}[年/-]\d{1,2}[月/-]\d{1,2}', value)) > 1:
        return {'deadline': None, 'warning': '原文有多个日期，请确认。'}
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日?', value)
    if m:
        try:
            target = date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return {'deadline': None, 'warning': '日期无效，请确认。'}
    else:
        m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', value)
        if m:
            try:
                target = date(int(m[1]), int(m[2]), int(m[3]))
            except ValueError:
                return {'deadline': None, 'warning': '日期无效，请确认。'}
    if target is None:
        return {'deadline': None, 'warning': '无法从原文确定截止日期，请补充。'}
    if len(re.findall(r'(\d{1,2})[:：](\d{2})', value)) > 1:
        return {'deadline': None, 'warning': '原文有多个时刻，请确认。'}
    tm = re.search(r'(\d{1,2})[:：](\d{2})', value)
    if not tm:
        tm = re.search(r'(\d{1,2})[点时](?:(\d{1,2})分)?', value)
    if tm:
        hour, minute = int(tm[1]), int(tm[2] or 0)
        if hour > 23 or minute > 59:
            return {'deadline': None, 'warning': '时间无效，请确认。'}
        base = target.date() if isinstance(target, datetime) else target
        return {'deadline': _iso(datetime.combine(base, time(hour, minute), TZ)), 'warning': None}
    if isinstance(target, datetime):
        return {'deadline': _iso(target.date()), 'warning': None}
    if not re.search(r'\d{4}', value) and ref is None:
        return {'deadline': None, 'warning': '缺少年份或消息发送时间，请确认。'}
    return {'deadline': _iso(target), 'warning': None}

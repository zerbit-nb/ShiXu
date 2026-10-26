from difflib import SequenceMatcher
import re
import unicodedata
from app.services.task_changes import task_version


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value or '').casefold() if c.isalnum())


def subject(title):
    return re.sub(r'^(?:请|按时|完成|提交|参加|报名|填写|申请|领取|上交)+', '', normalized(title))


def notification_topic(raw_text):
    match = re.search(r'(?m)^\s*关于([^：:。]{2,100})[：:]', raw_text or '')
    return normalized(match.group(1)) if match else ''


def change_notice(raw_text):
    return bool(re.search(r'延长|延期|推迟|取消|作废|无需再|不用再|(?:截止|期限|时间).{0,40}(?:调整|改为|变更)|(?:调整|变更).{0,20}(?:截止|期限|时间)', raw_text or ''))


def action_kind(title):
    value = normalized(title)
    for kind, pattern in [('submit', r'^(?:请|按时|完成)*(?:提交|上交|申报)'), ('attend', r'^(?:请|按时)*(?:参加|出席)'), ('register', r'^(?:请|按时)*(?:报名|申请)'), ('fill', r'^(?:请|按时)*(?:填写)'), ('collect', r'^(?:请|按时)*(?:领取)')]:
        if re.search(pattern, value):
            return kind
    return ''


def find_matches(fields, message, tasks, message_lookup=None):
    matches = []
    title = subject(fields['title'])
    courses = {normalized(v) for v in re.findall(r'《([^》]+)》', fields['title'] + message.get('raw_text', ''))}
    materials = {normalized(m) for m in fields.get('materials', []) if normalized(m)}
    topic = notification_topic(message.get('raw_text', ''))
    action = action_kind(fields['title'])
    for task in tasks:
        if task['status'] == 'cancelled':
            continue
        original = message_lookup(task['message_id']) if message_lookup else None
        other_topic = notification_topic((original or {}).get('raw_text', ''))
        other_action = action_kind(task['title'])
        if topic and other_topic and topic != other_topic:
            continue
        if action and other_action and action != other_action:
            continue
        other_courses = {normalized(v) for v in re.findall(r'《([^》]+)》', task['title'] + (original or {}).get('raw_text', ''))}
        if courses and other_courses and not courses & other_courses:
            continue
        shared_course = bool(courses & other_courses)
        other = subject(task['title'])
        similarity = SequenceMatcher(None, title, other, autojunk=False).ratio() if title and other else 0
        same_group = bool(message.get('source_group') and normalized(message['source_group']) == normalized(task.get('source_group')))
        same_deadline = bool(fields.get('deadline') and fields['deadline'] == task.get('deadline'))
        overlap = materials & {normalized(m) for m in task['materials']}
        source_conflict = bool(message.get('source_group') and task.get('source_group') and not same_group)
        topic_match = bool(topic and topic == other_topic and not source_conflict and overlap and action and action == other_action)
        contextual_match = False
        if shared_course:
            new_subject = subject(re.sub(r'《[^》]+》', '', fields['title']))
            old_subject = subject(re.sub(r'《[^》]+》', '', task['title']))
            contextual_match = new_subject == old_subject and len(new_subject) >= 4
        # Shared action verbs, group and date alone cannot identify the task.
        specific = min(len(title), len(other)) >= 4
        if not (topic_match or contextual_match or specific and (similarity >= .85 or (similarity >= .7 and overlap and (same_group or same_deadline)))
                or (title == other and title and overlap and (same_group or same_deadline))):
            continue
        reasons = ['原通知主题相同'] if topic_match else ['任务主题相同' if title == other else '任务主题相近']
        if contextual_match: reasons.append('原通知课程相同')
        if same_group: reasons.append('来源相同')
        if same_deadline: reasons.append('截止时间相同')
        if overlap: reasons.append('有相同材料')
        differences = []
        if fields.get('deadline') != task.get('deadline'): differences.append('截止时间不同')
        if normalized(message.get('source_group')) != normalized(task.get('source_group')): differences.append('来源不同')
        if fields.get('location') != task.get('location'): differences.append('地点不同')
        if fields.get('target_audience') != task.get('target_audience'): differences.append('面向对象不同')
        score = round(similarity * 70 + same_group * 10 + same_deadline * 10 + bool(overlap) * 10, 1)
        change_kind = 'cancel' if re.search(r'取消|作废|无需再|不用再', message.get('raw_text', '')) else ('deadline' if fields.get('deadline') != task.get('deadline') else 'duplicate')
        matches.append({'version': task_version(task), 'change_kind': change_kind, 'task': task, 'score': score, 'reasons': reasons, 'differences': differences})
    return sorted(matches, key=lambda m: (-m['score'], m['task']['id']))[:5]

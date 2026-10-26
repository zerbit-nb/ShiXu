from __future__ import annotations

from datetime import datetime, date
from typing import Any
import re
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import TaskFields
from app.services.time_parser import TZ, parse_deadline


class ExtractedTask(TaskFields):
    model_config = ConfigDict(extra='forbid')
    deadline_iso: str | None = None
    uncertain_fields: list[str] = Field(default_factory=list, max_length=30)
    reason: str | None = Field(default=None, max_length=1000)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    is_actionable: bool
    tasks: list[ExtractedTask] = Field(max_length=30)
    summary: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def consistent(self):
        if self.is_actionable != bool(self.tasks):
            raise ValueError('is_actionable 与任务数组不一致')
        return self


def normalize_extraction(result: dict[str, Any], sent_at: datetime | None, raw_text: str | None = None) -> list[dict[str, Any]]:
    result = ExtractionResult.model_validate(result).model_dump()
    if not result.get('is_actionable', True):
        return []
    drafts: list[dict[str, Any]] = []
    seen = []
    for raw in result.get('tasks', []):
        if raw in seen:
            drafts[seen.index(raw)]['warnings'].append('模型返回了完全重复的候选，已在本次提取中保留一条。')
            continue
        seen.append(raw)
        if not isinstance(raw, dict) or not str(raw.get('title', '')).strip():
            continue
        source_warning = None
        deadline_text = raw.get('deadline_text')
        if raw_text and deadline_text:
            compact = lambda value: ''.join(value.split())
            if compact(deadline_text) not in compact(raw_text):
                deadline_text = raw_text if len(result['tasks']) == 1 else None
                source_warning = '模型改写了期限表达，已按原文重新校验；请核对所属任务的截止时间。'
        if raw_text and len(result['tasks']) == 1:
            if re.search(r'延长|延期|变更|更改|调整|取消', raw_text) and re.search(r'截止|期限|日期|时间', raw_text):
                deadline_text = raw_text
                source_warning = '这是期限变更通知，请核对关联任务和新期限；系统不会自动覆盖已有待办。'
                parsed = {'deadline': None, 'warning': '变更通知的期限需要人工确认。'}
            elif len(re.findall(r'\d{4}[年/-]\d{1,2}[月/-]\d{1,2}', raw_text)) > 1:
                deadline_text = raw_text
                parsed = parse_deadline(raw_text, sent_at)
            else:
                parsed = parse_deadline(deadline_text, sent_at)
        else:
            parsed = parse_deadline(deadline_text, sent_at)


        iso = parsed['deadline']
        precision = 'datetime' if iso and 'T' in iso else ('date_only' if iso else 'unknown')
        fields = TaskFields(title=str(raw['title']).strip(), description=raw.get('description'), deadline=iso, deadline_precision=precision, deadline_text=deadline_text[:300] if deadline_text else None, location=raw.get('location'), target_audience=raw.get('target_audience'), materials=raw.get('materials') or [], format_requirement=raw.get('format_requirement'), submit_method=raw.get('submit_method'), priority=raw.get('priority', 'normal')).model_dump(mode='json')
        labels = {'title': '任务标题', 'description': '任务说明', 'deadline_iso': '截止日期与时间',
                  'deadline_text': '原文期限', 'location': '地点', 'target_audience': '面向对象',
                  'materials': '提交材料', 'format_requirement': '格式要求', 'submit_method': '提交方式',
                  'priority': '重要程度'}
        warnings = [f'{labels[field]}需要核对。' if field in labels else field
                    for field in (raw.get('uncertain_fields') or [])]
        if iso and sent_at:
            reference = sent_at.replace(tzinfo=TZ) if sent_at.tzinfo is None else sent_at.astimezone(TZ)
            expired = (datetime.fromisoformat(iso) < reference if 'T' in iso
                       else date.fromisoformat(iso) < reference.date())
            if expired:
                warnings.append('截止时间早于消息发送时间，请核对原文和发送时间；系统未自动改到下一周。')

        if source_warning: warnings.append(source_warning)
        if parsed['warning']: warnings.append(parsed['warning'])
        if raw.get('reason'): warnings.append(raw['reason'])
        if raw.get('deadline_iso') and not iso:
            warnings.append('模型给出的具体日期缺少可验证的原文依据，已留空。')
        drafts.append({'fields': fields, 'warnings': warnings, 'reason': raw.get('reason')})
    return drafts

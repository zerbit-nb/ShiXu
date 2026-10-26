from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageInput(BaseModel):
    raw_text: str = Field(min_length=1, max_length=20000)
    source: str = Field(default='manual', max_length=40)
    source_group: str | None = Field(default=None, max_length=200)
    sender: str | None = Field(default=None, max_length=100)
    sent_at: datetime | None = None

    @field_validator('raw_text')
    @classmethod
    def trim_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('原文不能为空')
        return value


class ExtractRequest(BaseModel):
    messages: list[MessageInput] = Field(min_length=1, max_length=20)


class TaskFields(BaseModel):
    model_config = ConfigDict(extra='ignore')
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    deadline: str | None = None
    deadline_precision: Literal['datetime', 'date_only', 'unknown'] = 'unknown'
    deadline_text: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    target_audience: str | None = Field(default=None, max_length=300)
    materials: list[str] = Field(default_factory=list, max_length=30)
    format_requirement: str | None = Field(default=None, max_length=300)
    submit_method: str | None = Field(default=None, max_length=300)
    priority: Literal['low', 'normal', 'high'] = 'normal'

    @field_validator('title')
    @classmethod
    def title_required(cls, value):
        if not value.strip():
            raise ValueError('任务标题不能为空')
        return value.strip()

    @field_validator('deadline')
    @classmethod
    def valid_deadline(cls, value):
        return normalize_deadline(value)


class ManualDraftInput(MessageInput):
    fields: TaskFields | None = None


class ConfirmRequest(BaseModel):
    duplicate_reviewed: bool = False
    confirmed: bool
    fields: TaskFields


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    deadline: str | None = None
    deadline_text: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    target_audience: str | None = Field(default=None, max_length=300)
    materials: list[str] | None = Field(default=None, max_length=30)
    format_requirement: str | None = Field(default=None, max_length=300)
    submit_method: str | None = Field(default=None, max_length=300)
    priority: Literal['low', 'normal', 'high'] | None = None

    @field_validator('title')
    @classmethod
    def title_required(cls, value):
        if value is None or not value.strip():
            raise ValueError('任务标题不能为空')
        return value.strip()

    @field_validator('deadline')
    @classmethod
    def valid_deadline(cls, value):
        return normalize_deadline(value)

    @field_validator('priority', 'materials')
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError('该字段不能为 null')
        return value


def normalize_deadline(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) == 10:
        return date.fromisoformat(value).isoformat()
    if 'T' not in value:
        raise ValueError('请提供 YYYY-MM-DD 或 ISO 8601 日期时间')
    dt = datetime.fromisoformat(value)
    tz = timezone(timedelta(hours=8))
    return dt.replace(tzinfo=tz).isoformat(timespec='seconds') if dt.tzinfo is None else dt.astimezone(tz).isoformat(timespec='seconds')


def jsonable(data: Any) -> Any:
    if isinstance(data, BaseModel):
        return data.model_dump(mode='json')
    return data


class CompletedTaskTarget(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=64, max_length=64)


class CompletedTaskOperation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['restore', 'delete']
    confirmed: bool
    tasks: list[CompletedTaskTarget] = Field(min_length=1, max_length=10000)

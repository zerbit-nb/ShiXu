"""Stable group selections shared by the local API and capture worker."""
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_GROUPS = 20
GROUP_ID = re.compile(r'^[A-Za-z0-9_-]{1,100}@chatroom$')


class WeChatGroup(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=GROUP_ID.pattern)
    name: str = Field(min_length=1, max_length=200)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('群名不能为空')
        return value


def group_profiles(profile):
    groups = profile.get('groups') or []
    if not groups:
        return {'': profile}
    return {g['id']: {'alias_hash': profile['alias_hash'], 'group_id': g['id'],
                      'group_name': g['name']} for g in groups}

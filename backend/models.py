from typing import Literal
from pydantic import BaseModel, Field, field_validator
from urllib.parse import urlparse


class ProblemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    difficulty: Literal['Easy', 'Medium', 'Hard']
    link: str = Field(min_length=1, max_length=2000)
    topic_tags: list[str] = Field(default_factory=list)

    @field_validator('name', 'link')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank')
        return value.strip()

    @field_validator('link')
    @classmethod
    def http_link(cls, value):
        parsed = urlparse(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('Use an HTTP or HTTPS problem URL')
        return value


class TopicCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    category: str = 'General'
    notes: str = ''
    link: str = ''

    @field_validator('name')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank')
        return value.strip()


class VersionCreate(BaseModel):
    code: str = Field(min_length=1, max_length=1000000)
    language: str = Field(min_length=1, max_length=40)
    commit_message: str = Field(min_length=1, max_length=500)
    what_is_good: str = ''
    what_is_bad: str = ''
    time_complexity: str = ''
    space_complexity: str = ''

    @field_validator('code', 'language', 'commit_message')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank')
        return value


class ReviewRequest(BaseModel):
    expected_stage: int = Field(ge=0, le=3)

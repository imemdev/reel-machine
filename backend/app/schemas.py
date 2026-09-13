from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)


class VideoCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=240)
    creator: str | None = Field(default=None, max_length=240)
    thumbnail_url: str | None = Field(default=None, max_length=2048)
    source_page_url: str | None = Field(default=None, max_length=2048)
    duration_ms: int | None = Field(default=None, ge=0)
    tags: list[str] = Field(default_factory=list, max_length=30)


class VideoUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=240)
    creator: str | None = Field(default=None, max_length=240)
    thumbnail_url: str | None = Field(default=None, max_length=2048)
    tags: list[str] | None = Field(default=None, max_length=30)


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_ids: list[str] = Field(min_length=1, max_length=50)
    action: Literal["process", "retry", "reprocess"]
    model_key: Literal["farukstt", "whisper_large_v3"]
    owner_asserted_tunisian: bool = False

    @field_validator("video_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("video_ids must not contain duplicates")
        return value


class VideoActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["done", "move_to_processed", "complete"]


class BatchStageActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_ids: list[str] = Field(min_length=1, max_length=50)
    action: Literal["done", "move_to_processed", "complete"]


class TranscriptSegmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=20_000)


class TranscriptUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_id: str = Field(min_length=1, max_length=120)
    segments: list[TranscriptSegmentRequest] = Field(min_length=1, max_length=10_000)


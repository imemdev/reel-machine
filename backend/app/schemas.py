from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)


class VideoCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    # Social extractors often use the full caption as the title.
    title: str | None = Field(default=None, max_length=20_000)
    creator: str | None = Field(default=None, max_length=240)
    thumbnail_url: str | None = Field(default=None, max_length=2048)
    source_page_url: str | None = Field(default=None, max_length=2048)
    duration_ms: int | None = Field(default=None, ge=0)
    tags: list[str] = Field(default_factory=list, max_length=30)


class VideoUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=20_000)
    creator: str | None = Field(default=None, max_length=240)
    thumbnail_url: str | None = Field(default=None, max_length=2048)
    tags: list[str] | None = Field(default=None, max_length=30)


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_ids: list[str] = Field(min_length=1, max_length=50)
    action: Literal["process", "retry", "reprocess"]
    model_key: Literal["farukstt"] = "farukstt"
    owner_asserted_tunisian: bool = True

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


class NoteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=20_000)
    script: str = Field(default="", max_length=200_000)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title must not be blank")
        return value.strip()


class NoteUpdateRequest(NoteCreateRequest):
    title: str = Field(default="Untitled note", min_length=1, max_length=240)
    done: bool = False


class MediaFolderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder: Literal["root", "videos", "audio"] = "root"


class MediaOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["video", "audio"]
    reveal: bool = False

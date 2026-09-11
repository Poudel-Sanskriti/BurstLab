from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Untitled experiment", max_length=80)
    count: int = Field(default=24, ge=1, le=100)
    rate: int = Field(default=12, ge=1, le=30)
    concurrency: int = Field(default=2, ge=2, le=5)
    delay_ms: int = Field(default=350, ge=0, le=1000)
    failure_percent: int = Field(default=20, ge=0, le=50)
    max_attempts: int = Field(default=3, ge=1, le=5)
    pattern: Literal["steady", "burst"] = "steady"
    payload: str = "https://example.com/burstlab"
    seed: int = Field(default=42, ge=0, le=999999)
    first_lane: Literal["direct", "queued"] = "direct"

    @field_validator("payload")
    @classmethod
    def check_payload(cls, value: str) -> str:
        if not value.strip() or len(value.encode("utf-8")) > 480:
            raise ValueError("Use 1–480 UTF-8 bytes of text.")
        return value


TERMINAL = {"succeeded", "failed", "rejected", "dead_letter", "cancelled", "unresolved"}

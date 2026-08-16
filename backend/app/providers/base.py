from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.retryable = retryable


class GenerateImageParams(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    model: str | None = None
    n: int = Field(default=1, ge=1, le=4)
    size: str = Field(default="1024x1024", max_length=32)
    quality: str | None = Field(default=None, max_length=32)
    response_format: str | None = Field(default="b64_json", max_length=32)
    extra_params: dict[str, Any] = Field(default_factory=dict)


class EditImageParams(GenerateImageParams):
    pass


@dataclass(frozen=True, slots=True)
class ImageInput:
    filename: str
    content: bytes
    content_type: str = "image/png"


class ProviderImage(BaseModel):
    b64_json: str | None = None
    url: str | None = None
    revised_prompt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderImageResponse(BaseModel):
    created: int | None = None
    images: list[ProviderImage]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelProvider(ABC):
    name: str
    default_model: str

    @abstractmethod
    async def generate_image(self, params: GenerateImageParams) -> ProviderImageResponse:
        raise NotImplementedError

    @abstractmethod
    async def edit_image(
        self, params: EditImageParams, images: list[ImageInput]
    ) -> ProviderImageResponse:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


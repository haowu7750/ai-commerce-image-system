from __future__ import annotations

import time

from app.providers.base import (
    EditImageParams,
    GenerateImageParams,
    ImageInput,
    ModelProvider,
    ProviderImage,
    ProviderImageResponse,
)


# Deterministic 1x1 PNG used only for local/demo tests.
MOCK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class MockImageProvider(ModelProvider):
    name = "mock"

    def __init__(self, model: str = "mock-image-v1") -> None:
        self.default_model = model

    async def generate_image(self, params: GenerateImageParams) -> ProviderImageResponse:
        return ProviderImageResponse(
            created=int(time.time()),
            images=[
                ProviderImage(
                    b64_json=MOCK_PNG_B64,
                    revised_prompt=params.prompt,
                    metadata={"mock": True, "sequence": index + 1},
                )
                for index in range(params.n)
            ],
            metadata={"provider": self.name, "model": params.model or self.default_model},
        )

    async def edit_image(
        self, params: EditImageParams, images: list[ImageInput]
    ) -> ProviderImageResponse:
        response = await self.generate_image(GenerateImageParams(**params.model_dump()))
        response.metadata.update({"operation": "edit", "input_count": len(images)})
        return response

    async def close(self) -> None:
        return None


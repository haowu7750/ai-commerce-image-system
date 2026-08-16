from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from app.providers.base import (
    EditImageParams,
    GenerateImageParams,
    ImageInput,
    ModelProvider,
    ProviderError,
    ProviderImage,
    ProviderImageResponse,
)


class ShulicodeImageProvider(ModelProvider):
    name = "shulicode"
    supported_model = "gpt-image-2"

    def __init__(
        self,
        *,
        api_key: SecretStr | str,
        base_url: str = "https://shulicode.xyz/v1",
        model: str = "gpt-image-2",
        timeout_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        if not key:
            raise ValueError("Shulicode API key is required")
        if model != self.supported_model:
            raise ValueError("ShulicodeImageProvider only supports gpt-image-2")
        self.default_model = model
        self._client = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout_seconds,
            transport=transport,
        )

    @staticmethod
    def _payload(params: GenerateImageParams) -> dict[str, Any]:
        payload = params.model_dump(exclude={"extra_params"}, exclude_none=True)
        payload["model"] = params.model or "gpt-image-2"
        payload.update(params.extra_params)
        return payload

    @staticmethod
    def _parse_response(payload: Any) -> ProviderImageResponse:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ProviderError(
                "IMAGE_PROVIDER_RESPONSE_INVALID",
                "Image provider returned an invalid response structure",
            )
        images: list[ProviderImage] = []
        for item in payload["data"]:
            if not isinstance(item, dict):
                continue
            b64_json = item.get("b64_json")
            url = item.get("url")
            if not b64_json and not url:
                continue
            known = {"b64_json", "url", "revised_prompt"}
            images.append(
                ProviderImage(
                    b64_json=b64_json,
                    url=url,
                    revised_prompt=item.get("revised_prompt"),
                    metadata={key: value for key, value in item.items() if key not in known},
                )
            )
        if not images:
            raise ProviderError(
                "IMAGE_PROVIDER_RESPONSE_EMPTY",
                "Image provider response did not contain an image",
            )
        metadata = {
            key: value
            for key, value in payload.items()
            if key not in {"data"}
        }
        return ProviderImageResponse(
            created=payload.get("created"), images=images, metadata=metadata
        )

    async def _post(self, path: str, **kwargs: Any) -> ProviderImageResponse:
        try:
            response = await self._client.post(path, **kwargs)
            response.raise_for_status()
            return self._parse_response(response.json())
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "IMAGE_PROVIDER_TIMEOUT", "Image provider request timed out", retryable=True
            ) from exc
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
            raise ProviderError(
                "IMAGE_PROVIDER_HTTP_ERROR",
                f"Image provider request failed with HTTP {exc.response.status_code}",
                retryable=retryable,
            ) from exc
        except (ValueError, TypeError) as exc:
            raise ProviderError(
                "IMAGE_PROVIDER_RESPONSE_INVALID",
                "Image provider returned unreadable JSON",
            ) from exc

    async def generate_image(self, params: GenerateImageParams) -> ProviderImageResponse:
        if params.model not in {None, self.supported_model}:
            raise ProviderError(
                "IMAGE_MODEL_UNSUPPORTED",
                "Shulicode image generation only supports gpt-image-2",
            )
        payload = self._payload(params)
        payload["model"] = params.model or self.default_model
        return await self._post("images/generations", json=payload)

    async def edit_image(
        self, params: EditImageParams, images: list[ImageInput]
    ) -> ProviderImageResponse:
        if params.model not in {None, self.supported_model}:
            raise ProviderError(
                "IMAGE_MODEL_UNSUPPORTED",
                "Shulicode image editing only supports gpt-image-2",
            )
        if not images:
            raise ValueError("at least one input image is required")
        payload = self._payload(params)
        payload["model"] = params.model or self.default_model
        files = [
            ("image", (image.filename, image.content, image.content_type))
            for image in images
        ]
        form = {
            key: str(value).lower() if isinstance(value, bool) else str(value)
            for key, value in payload.items()
            if not isinstance(value, (dict, list))
        }
        return await self._post("images/edits", data=form, files=files)

    async def close(self) -> None:
        await self._client.aclose()

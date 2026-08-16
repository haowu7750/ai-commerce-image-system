import json

import httpx
import pytest
from pydantic import SecretStr

from app.providers.base import EditImageParams, GenerateImageParams, ImageInput
from app.providers.shulicode import ShulicodeImageProvider
from app.models.commerce import Asset
from app.models.enums import AssetType
from app.providers.base import ProviderError
from app.services.image_generation import _asset_to_image_input


@pytest.mark.asyncio
async def test_shulicode_generation_parses_b64_without_real_network() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/images/generations"
        assert request.headers["Authorization"].startswith("Bearer ")
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-image-2"
        return httpx.Response(200, json={"created": 1, "data": [{"b64_json": "aGVsbG8="}]})

    provider = ShulicodeImageProvider(
        api_key=SecretStr("test-key-never-sent-to-a-real-service"),
        transport=httpx.MockTransport(handler),
    )
    try:
        response = await provider.generate_image(GenerateImageParams(prompt="test"))
        assert response.images[0].b64_json == "aGVsbG8="
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_shulicode_edit_uses_multipart_and_parses_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/images/edits"
        assert request.headers["Content-Type"].startswith("multipart/form-data")
        content = await request.aread()
        assert b'gpt-image-2' in content
        assert b'input.png' in content
        return httpx.Response(200, json={"data": [{"url": "https://example.invalid/result.png"}]})

    provider = ShulicodeImageProvider(
        api_key="test-key-never-sent-to-a-real-service",
        transport=httpx.MockTransport(handler),
    )
    try:
        response = await provider.edit_image(
            EditImageParams(prompt="remove background"),
            [ImageInput(filename="input.png", content=b"not-a-real-png")],
        )
        assert response.images[0].url == "https://example.invalid/result.png"
    finally:
        await provider.close()


def test_shulicode_rejects_unverified_model() -> None:
    with pytest.raises(ValueError, match="only supports gpt-image-2"):
        ShulicodeImageProvider(api_key="test-key", model="unverified-image-model")


def test_real_generation_reference_is_decoded_from_local_data_url() -> None:
    asset = Asset(
        project_id="project-id",
        uploaded_by_id="operator-id",
        asset_type=AssetType.PRODUCT_REFERENCE,
        file_url="data:image/png;base64,iVBORw0KGgo=",
        file_hash="sha256:test",
    )
    image = _asset_to_image_input(asset)
    assert image.content_type == "image/png"
    assert image.filename.endswith(".png")
    assert image.content.startswith(b"\x89PNG")


def test_real_generation_rejects_external_reference_url() -> None:
    asset = Asset(
        project_id="project-id",
        uploaded_by_id="operator-id",
        asset_type=AssetType.PRODUCT_REFERENCE,
        file_url="https://example.invalid/reference.png",
        file_hash="sha256:test",
    )
    with pytest.raises(ProviderError, match="重新上传"):
        _asset_to_image_input(asset)

import json
from unittest.mock import MagicMock, patch

import pytest

from packages.ai_providers.gemini_provider import GeminiProvider


def make_provider():
    with patch(
        "packages.ai_providers.gemini_provider.genai.Client"
    ) as client_class:
        provider = GeminiProvider(api_key="test-key", model="test-model")
        provider.client = client_class.return_value
    return provider


def test_generate_text_returns_response_text():
    provider = make_provider()
    response = MagicMock()
    response.text = "  Hello from Gemini  "
    provider.client.models.generate_content.return_value = response

    result = provider.generate_text("Say hello")

    assert result == "Hello from Gemini"
    provider.client.models.generate_content.assert_called_once()


def test_generate_text_rejects_empty_prompt():
    provider = make_provider()

    with pytest.raises(ValueError, match="Prompt cannot be empty"):
        provider.generate_text("   ")


def test_generate_text_rejects_empty_response():
    provider = make_provider()
    response = MagicMock()
    response.text = ""
    provider.client.models.generate_content.return_value = response

    with pytest.raises(ValueError, match="empty response"):
        provider.generate_text("Say hello")


def test_generate_json_returns_dictionary():
    provider = make_provider()
    response = MagicMock()
    response.text = json.dumps({"action": "analyze", "approved": False})
    provider.client.models.generate_content.return_value = response

    result = provider.generate_json("Return an action")

    assert result == {"action": "analyze", "approved": False}


def test_generate_json_rejects_invalid_json():
    provider = make_provider()
    response = MagicMock()
    response.text = "not valid json"
    provider.client.models.generate_content.return_value = response

    with pytest.raises(ValueError, match="invalid JSON"):
        provider.generate_json("Return JSON")


def test_generate_json_rejects_non_object_json():
    provider = make_provider()
    response = MagicMock()
    response.text = json.dumps(["one", "two"])
    provider.client.models.generate_content.return_value = response

    with pytest.raises(ValueError, match="JSON object"):
        provider.generate_json("Return a JSON object")


def test_provider_rejects_missing_api_key():
    with patch(
        "packages.ai_providers.gemini_provider.settings.gemini_api_key",
        "",
    ):
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            GeminiProvider()

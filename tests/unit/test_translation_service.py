"""Unit tests for TranslationService — language resolution and LLM translation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.translation_service import (
    LANGUAGE_ALIASES,
    SUPPORTED_LANGUAGES,
    resolve_language_code,
    translate_metadata,
    translate_script,
)


SETTINGS_PATCH = "app.services.translation_service.get_settings"


# ── Helpers ──────────────────────────────────────────────────────


def _make_settings(**overrides):
    """Create a mock Settings with translation-related defaults."""
    defaults = {
        "openai_api_key": "sk-test-key",
        "openai_model": "gpt-4o",
        "anthropic_api_key": "sk-ant-test-key",
        "anthropic_model": "claude-sonnet-4-20250514",
    }
    defaults.update(overrides)
    settings = MagicMock()
    for key, value in defaults.items():
        setattr(settings, key, value)
    return settings


def _mock_openai_response(content: str) -> MagicMock:
    """Build a mock OpenAI chat completion response."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=content))]
    return mock_response


def _mock_anthropic_response(text: str) -> MagicMock:
    """Build a mock Anthropic messages response."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=text)]
    return mock_response


# ── TestSupportedLanguages ───────────────────────────────────────


class TestSupportedLanguages:
    """SUPPORTED_LANGUAGES dict validation."""

    def test_has_at_least_10_entries(self):
        assert len(SUPPORTED_LANGUAGES) >= 10

    def test_has_15_entries(self):
        assert len(SUPPORTED_LANGUAGES) == 15

    def test_english_is_present(self):
        assert "en" in SUPPORTED_LANGUAGES
        assert SUPPORTED_LANGUAGES["en"] == "English"

    def test_spanish_is_present(self):
        assert "es" in SUPPORTED_LANGUAGES
        assert SUPPORTED_LANGUAGES["es"] == "Spanish"

    def test_all_keys_are_two_letter_codes(self):
        for code in SUPPORTED_LANGUAGES:
            assert len(code) == 2, f"Language code '{code}' is not 2 characters"
            assert code == code.lower(), f"Language code '{code}' is not lowercase"

    def test_all_values_are_nonempty_strings(self):
        for code, name in SUPPORTED_LANGUAGES.items():
            assert isinstance(name, str)
            assert len(name) > 0, f"Language name for '{code}' is empty"


# ── TestLanguageAliases ──────────────────────────────────────────


class TestLanguageAliases:
    """LANGUAGE_ALIASES maps full names to valid SUPPORTED_LANGUAGES keys."""

    def test_all_aliases_map_to_supported_languages(self):
        for alias, code in LANGUAGE_ALIASES.items():
            assert code in SUPPORTED_LANGUAGES, (
                f"Alias '{alias}' maps to '{code}' which is not in SUPPORTED_LANGUAGES"
            )

    def test_all_aliases_are_lowercase(self):
        for alias in LANGUAGE_ALIASES:
            assert alias == alias.lower(), f"Alias '{alias}' is not lowercase"

    def test_english_alias(self):
        assert LANGUAGE_ALIASES["english"] == "en"

    def test_spanish_alias(self):
        assert LANGUAGE_ALIASES["spanish"] == "es"

    def test_hindi_alias(self):
        assert LANGUAGE_ALIASES["hindi"] == "hi"

    def test_has_at_least_10_aliases(self):
        assert len(LANGUAGE_ALIASES) >= 10


# ── TestResolveLanguageCode ──────────────────────────────────────


class TestResolveLanguageCode:
    """resolve_language_code resolves codes and names to standard codes."""

    def test_direct_code_es(self):
        assert resolve_language_code("es") == "es"

    def test_direct_code_en(self):
        assert resolve_language_code("en") == "en"

    def test_direct_code_ja(self):
        assert resolve_language_code("ja") == "ja"

    def test_full_name_spanish(self):
        assert resolve_language_code("spanish") == "es"

    def test_full_name_french(self):
        assert resolve_language_code("french") == "fr"

    def test_full_name_hindi(self):
        assert resolve_language_code("hindi") == "hi"

    def test_case_insensitive_SPANISH(self):
        assert resolve_language_code("SPANISH") == "es"

    def test_case_insensitive_Es(self):
        assert resolve_language_code("Es") == "es"

    def test_whitespace_stripped(self):
        assert resolve_language_code("  es  ") == "es"

    def test_unknown_code_returns_none(self):
        assert resolve_language_code("xyz") is None

    def test_unknown_name_returns_none(self):
        assert resolve_language_code("klingon") is None

    def test_empty_string_returns_none(self):
        assert resolve_language_code("") is None


# ── TestTranslateScript ─────────────────────────────────────────


class TestTranslateScript:
    """translate_script sends script to LLM for translation."""

    @pytest.mark.asyncio
    async def test_english_returns_original(self):
        """No API call when target is English."""
        result = await translate_script("Hello world", "en")
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_english_returns_original_without_settings(self):
        """English short-circuit should not even touch settings."""
        result = await translate_script("Some script text", "en")
        assert result == "Some script text"

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_openai_provider_calls_openai(self, mock_gs):
        mock_gs.return_value = _make_settings()
        with patch("openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                return_value=_mock_openai_response("Texto traducido")
            )
            result = await translate_script("Hello world", "es", provider="openai")
            assert result == "Texto traducido"
            mock_client_cls.return_value.chat.completions.create.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_openai_uses_correct_model(self, mock_gs):
        mock_gs.return_value = _make_settings(openai_model="gpt-4o-mini")
        with patch("openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                return_value=_mock_openai_response("Translated")
            )
            await translate_script("Hello", "fr", provider="openai")
            call_kwargs = mock_client_cls.return_value.chat.completions.create.call_args[1]
            assert call_kwargs["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_openai_system_prompt_contains_language_name(self, mock_gs):
        mock_gs.return_value = _make_settings()
        with patch("openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                return_value=_mock_openai_response("Traduit")
            )
            await translate_script("Hello", "fr", provider="openai")
            call_kwargs = mock_client_cls.return_value.chat.completions.create.call_args[1]
            messages = call_kwargs["messages"]
            system_msg = messages[0]["content"]
            assert "French" in system_msg

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_openai_temperature_is_low(self, mock_gs):
        mock_gs.return_value = _make_settings()
        with patch("openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                return_value=_mock_openai_response("Translated")
            )
            await translate_script("Hello", "de", provider="openai")
            call_kwargs = mock_client_cls.return_value.chat.completions.create.call_args[1]
            assert call_kwargs["temperature"] == 0.3

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_anthropic_provider_calls_anthropic(self, mock_gs):
        mock_gs.return_value = _make_settings()
        with patch("anthropic.AsyncAnthropic") as mock_client_cls:
            mock_client_cls.return_value.messages.create = AsyncMock(
                return_value=_mock_anthropic_response("Ubersetzter Text")
            )
            result = await translate_script("Hello", "de", provider="anthropic")
            assert result == "Ubersetzter Text"
            mock_client_cls.return_value.messages.create.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_anthropic_uses_correct_model(self, mock_gs):
        mock_gs.return_value = _make_settings(anthropic_model="claude-haiku-35")
        with patch("anthropic.AsyncAnthropic") as mock_client_cls:
            mock_client_cls.return_value.messages.create = AsyncMock(
                return_value=_mock_anthropic_response("Translated")
            )
            await translate_script("Hello", "ja", provider="anthropic")
            call_kwargs = mock_client_cls.return_value.messages.create.call_args[1]
            assert call_kwargs["model"] == "claude-haiku-35"

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_result_is_stripped(self, mock_gs):
        mock_gs.return_value = _make_settings()
        with patch("openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                return_value=_mock_openai_response("  Translated with spaces  ")
            )
            result = await translate_script("Hello", "es")
            assert result == "Translated with spaces"


# ── TestTranslateMetadata ────────────────────────────────────────


class TestTranslateMetadata:
    """translate_metadata translates title, description, tags."""

    @pytest.mark.asyncio
    async def test_english_returns_original(self):
        result = await translate_metadata(
            title="My Title",
            description="My Desc",
            tags=["tag1", "tag2"],
            target_language="en",
        )
        assert result["title"] == "My Title"
        assert result["description"] == "My Desc"
        assert result["tags"] == ["tag1", "tag2"]

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_parses_title_description_tags_format(self, mock_gs):
        mock_gs.return_value = _make_settings()
        raw_response = (
            "TITLE: Titulo Traducido\n"
            "DESCRIPTION: Descripcion traducida\n"
            "TAGS: etiqueta1, etiqueta2, etiqueta3"
        )
        with patch("openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                return_value=_mock_openai_response(raw_response)
            )
            result = await translate_metadata(
                title="Original Title",
                description="Original Desc",
                tags=["tag1"],
                target_language="es",
            )
            assert result["title"] == "Titulo Traducido"
            assert result["description"] == "Descripcion traducida"
            assert result["tags"] == ["etiqueta1", "etiqueta2", "etiqueta3"]

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_partial_response_preserves_originals(self, mock_gs):
        """If LLM only returns TITLE:, description and tags should keep originals."""
        mock_gs.return_value = _make_settings()
        raw_response = "TITLE: Translated Title Only"
        with patch("openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                return_value=_mock_openai_response(raw_response)
            )
            result = await translate_metadata(
                title="Original",
                description="Original Desc",
                tags=["orig_tag"],
                target_language="fr",
            )
            assert result["title"] == "Translated Title Only"
            assert result["description"] == "Original Desc"
            assert result["tags"] == ["orig_tag"]

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_anthropic_provider_for_metadata(self, mock_gs):
        mock_gs.return_value = _make_settings()
        raw_response = (
            "TITLE: Titre\n"
            "DESCRIPTION: Description en francais\n"
            "TAGS: mot1, mot2"
        )
        with patch("anthropic.AsyncAnthropic") as mock_client_cls:
            mock_client_cls.return_value.messages.create = AsyncMock(
                return_value=_mock_anthropic_response(raw_response)
            )
            result = await translate_metadata(
                title="Title",
                description="Description",
                tags=["word1"],
                target_language="fr",
                provider="anthropic",
            )
            assert result["title"] == "Titre"
            assert result["description"] == "Description en francais"

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_tags_split_and_stripped(self, mock_gs):
        mock_gs.return_value = _make_settings()
        raw_response = "TITLE: T\nDESCRIPTION: D\nTAGS:  a , b ,  c  , , "
        with patch("openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                return_value=_mock_openai_response(raw_response)
            )
            result = await translate_metadata(
                title="Original",
                description="Desc",
                tags=["x"],
                target_language="de",
            )
            # Empty strings after split+strip should be filtered out
            assert "" not in result["tags"]
            assert result["tags"] == ["a", "b", "c"]

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_unknown_language_code_uses_code_as_name(self, mock_gs):
        """If target_language is not in SUPPORTED_LANGUAGES, the code itself is used."""
        mock_gs.return_value = _make_settings()
        with patch("openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                return_value=_mock_openai_response("Translated")
            )
            result = await translate_script("Hello", "xx", provider="openai")
            assert result == "Translated"
            # The system prompt should use "xx" since it's not in SUPPORTED_LANGUAGES
            call_kwargs = mock_client_cls.return_value.chat.completions.create.call_args[1]
            messages = call_kwargs["messages"]
            system_msg = messages[0]["content"]
            assert "xx" in system_msg

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_metadata_returns_dict_with_correct_keys(self, mock_gs):
        mock_gs.return_value = _make_settings()
        raw_response = "TITLE: T\nDESCRIPTION: D\nTAGS: t1, t2"
        with patch("openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                return_value=_mock_openai_response(raw_response)
            )
            result = await translate_metadata(
                title="Title",
                description="Desc",
                tags=["tag"],
                target_language="ko",
            )
            assert set(result.keys()) == {"title", "description", "tags"}
            assert isinstance(result["tags"], list)

    @pytest.mark.asyncio
    @patch(SETTINGS_PATCH)
    async def test_openai_api_key_passed_to_client(self, mock_gs):
        mock_gs.return_value = _make_settings(openai_api_key="my-secret-key")
        with patch("openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                return_value=_mock_openai_response("Translated")
            )
            await translate_script("Hello", "it", provider="openai")
            mock_client_cls.assert_called_once_with(api_key="my-secret-key")

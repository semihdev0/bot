"""Wrapper for Anthropic Claude API for generating chat responses."""

from __future__ import annotations

import anthropic
import structlog

from src.comm100.ai.prompt_builder import PromptBuilder
from src.comm100.api.models import Comm100Message
from src.comm100.config.models import AnthropicCredentials, ClaudeConfig
from src.comm100.exceptions import ClaudeApiError
from src.utils.retry import retry

logger = structlog.get_logger()

FALLBACK_RESPONSE = (
    "Anlik olarak teknik bir sorun yasiyoruz. "
    "Kisa sure icerisinde size yardimci olacagiz. "
    "Lutfen bekleyiniz."
)


class ClaudeClient:
    """Generates chat responses using Claude API."""

    def __init__(
        self,
        credentials: AnthropicCredentials,
        config: ClaudeConfig,
        prompt_builder: PromptBuilder,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=credentials.api_key)
        self._config = config
        self._prompt_builder = prompt_builder

    @retry(max_attempts=2, retryable=(anthropic.APITimeoutError, anthropic.APIConnectionError))
    async def generate_response(
        self,
        conversation: list[Comm100Message],
        visitor_name: str = "",
    ) -> str:
        system_prompt = self._prompt_builder.build_system_prompt(
            visitor_name=visitor_name
        )
        messages = self._prompt_builder.build_messages(
            conversation, max_messages=self._config.max_context_messages
        )

        if not messages:
            return FALLBACK_RESPONSE

        try:
            response = await self._client.messages.create(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                system=system_prompt,
                messages=messages,
            )
            text = response.content[0].text.strip()
            logger.info(
                "claude_response_generated",
                tokens_in=response.usage.input_tokens,
                tokens_out=response.usage.output_tokens,
                length=len(text),
            )
            return text

        except (anthropic.APITimeoutError, anthropic.APIConnectionError):
            raise
        except anthropic.APIError as e:
            logger.error("claude_api_error", error=str(e))
            raise ClaudeApiError(str(e)) from e

    async def generate_response_safe(
        self,
        conversation: list[Comm100Message],
        visitor_name: str = "",
    ) -> str:
        try:
            return await self.generate_response(conversation, visitor_name)
        except Exception as e:
            logger.error("claude_fallback", error=str(e))
            return FALLBACK_RESPONSE

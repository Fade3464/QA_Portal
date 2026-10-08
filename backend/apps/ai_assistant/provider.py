"""Model-neutral chat-completion port; OpenAI compatible adapter for llama.cpp/OpenAI/Gemini.

Tool implementations know nothing about the serving model or remote provider.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from django.conf import settings


class AIProviderError(Exception):
    pass


@dataclass(frozen=True)
class Completion:
    message: dict
    finish_reason: str | None


class OpenAICompatibleProvider:
    def __init__(self):
        self.base_url = settings.AI_LLM_BASE_URL.rstrip('/')
        url = urlsplit(self.base_url)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise AIProviderError('AI_LLM_BASE_URL is invalid.')
        if url.scheme == 'http' and not settings.AI_LLM_ALLOW_HTTP:
            raise AIProviderError('Plain HTTP is disabled; use HTTPS or explicitly allow private transport.')
        if settings.AI_LLM_PROVIDER in {'openai', 'gemini_openai_compatible'} and not settings.AI_EXTERNAL_DATA_EGRESS_ALLOWED:
            raise AIProviderError('External AI provider data egress has not been authorized.')
        if not settings.AI_LLM_MODEL:
            raise AIProviderError('AI_LLM_MODEL is not configured.')

    def complete(self, messages, tools):
        key = settings.AI_LLM_API_KEY
        if settings.AI_LLM_API_KEY_FILE:
            try:
                key = Path(settings.AI_LLM_API_KEY_FILE).read_text(encoding='utf-8').strip()
            except OSError as exc:
                raise AIProviderError('AI provider credentials unavailable.') from exc
        if not key:
            raise AIProviderError('AI provider credentials not configured.')
        payload = {
            'model': settings.AI_LLM_MODEL,
            'messages': messages,
            'tools': tools,
            'tool_choice': 'auto',
            'temperature': 0,
            'max_tokens': settings.AI_LLM_MAX_OUTPUT_TOKENS,
            'stream': False,
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(settings.AI_LLM_TIMEOUT_SECONDS, connect=8.0),
                              follow_redirects=False, trust_env=False) as client:
                response = client.post(f'{self.base_url}/chat/completions',
                                       json=payload, headers={'Authorization': f'Bearer {key}'})
                response.raise_for_status()
                data = response.json()
            message = data['choices'][0]['message']
            if not isinstance(message, dict):
                raise ValueError('Unexpected completion message')
            return Completion(message=message, finish_reason=data['choices'][0].get('finish_reason'))
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError('AI inference service unavailable or returned an invalid response.') from exc


def get_provider():
    # Other native transports can implement complete(messages, tools) without changing tools/services.
    if settings.AI_LLM_PROVIDER not in {'openai_compatible', 'openai', 'gemini_openai_compatible'}:
        raise AIProviderError('Unsupported AI provider configuration.')
    return OpenAICompatibleProvider()

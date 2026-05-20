"""
core/llm.py - Thin LLM client over OpenAI / Anthropic.

Persona agents call this to decide their next action. The provider is chosen
from settings; chat_json() tolerates models that wrap JSON in prose or fences.
"""

import json
import re


class LLMError(Exception):
    pass


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response."""
    if not text:
        raise LLMError("Empty LLM response")
    # strip ```json ... ``` fences
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise LLMError(f"No JSON object in response: {text[:200]}")
        candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise LLMError(f"Malformed JSON from LLM: {e}") from e


class LLMClient:
    def __init__(self, provider: str, api_key: str, model: str):
        self.provider = provider
        self.api_key = api_key
        self.model = model

    @classmethod
    def from_settings(cls, settings, provider=None, api_key=None, model=None):
        provider = provider or settings.active_provider()
        if not provider:
            raise LLMError("No AI provider configured — set an OpenAI or Anthropic API key.")
        api_key = api_key or settings.api_key_for(provider)
        if not api_key:
            raise LLMError(f"No API key for provider '{provider}'.")
        model = model or settings.model_for(provider)
        return cls(provider, api_key, model)

    def chat(self, system: str, user: str, max_tokens: int = 900, temperature: float = 0.4) -> str:
        if self.provider == "openai":
            return self._openai(system, user, max_tokens, temperature)
        return self._anthropic(system, user, max_tokens, temperature)

    def chat_json(self, system: str, user: str, max_tokens: int = 900, temperature: float = 0.4) -> dict:
        return _extract_json(self.chat(system, user, max_tokens, temperature))

    def _openai(self, system, user, max_tokens, temperature) -> str:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMError("openai package not installed") from e
        try:
            resp = OpenAI(api_key=self.api_key).chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            raise LLMError(f"OpenAI call failed: {e}") from e

    def _anthropic(self, system, user, max_tokens, temperature) -> str:
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise LLMError("anthropic package not installed") from e
        try:
            resp = Anthropic(api_key=self.api_key).messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(block.text for block in resp.content if block.type == "text")
        except Exception as e:
            raise LLMError(f"Anthropic call failed: {e}") from e

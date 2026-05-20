"""
core/config.py - Configuration for Persona Swarm.
"""

import os
from dataclasses import dataclass, field
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    ai_provider: str = field(default_factory=lambda: os.getenv("AI_PROVIDER", "anthropic"))
    openai_api_key: Optional[str] = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    anthropic_api_key: Optional[str] = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    )

    max_pages: int = int(os.getenv("MAX_PAGES", "20"))
    crawl_timeout_ms: int = int(os.getenv("CRAWL_TIMEOUT_MS", "30000"))
    max_steps_per_persona: int = int(os.getenv("MAX_STEPS_PER_PERSONA", "15"))
    headless: bool = _env_bool("HEADLESS", True)

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key) and "sk-your" not in (self.openai_api_key or "")

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key) and "sk-ant-your" not in (self.anthropic_api_key or "")

    @property
    def has_ai(self) -> bool:
        return self.has_openai or self.has_anthropic

    def active_provider(self) -> Optional[str]:
        """Provider to actually use, honoring AI_PROVIDER preference then availability."""
        if self.ai_provider == "openai" and self.has_openai:
            return "openai"
        if self.ai_provider == "anthropic" and self.has_anthropic:
            return "anthropic"
        if self.has_anthropic:
            return "anthropic"
        if self.has_openai:
            return "openai"
        return None

    def api_key_for(self, provider: str) -> Optional[str]:
        return self.openai_api_key if provider == "openai" else self.anthropic_api_key

    def model_for(self, provider: str) -> str:
        return self.openai_model if provider == "openai" else self.anthropic_model


settings = Settings()

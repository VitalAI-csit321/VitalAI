"""LLM provider abstraction.
Every part of the codebase that needs an LLM calls `get_llm()`.
"""

from functools import lru_cache
from typing import cast

from langchain_core.language_models import BaseLanguageModel

from app.config import settings


@lru_cache(maxsize=1)
def get_llm() -> BaseLanguageModel:
    provider = settings.llm_provider.lower()

    if provider == "ollama":
        from langchain_community.llms import Ollama

        return cast(
            BaseLanguageModel,
            Ollama(
                model=settings.llm_model,
                base_url=settings.ollama_base_url,
                temperature=settings.llm_temperature,
                num_predict=settings.llm_max_tokens,
                timeout=settings.llm_timeout_seconds,
            ),
        )

    if provider == "bedrock":
        from langchain_aws import ChatBedrock

        return cast(
            BaseLanguageModel,
            ChatBedrock(
                model=settings.bedrock_model_id,
                region=settings.aws_region,
            ),
        )

    raise ValueError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Use 'ollama' or 'bedrock'.")

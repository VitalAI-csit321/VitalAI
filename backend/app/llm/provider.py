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
        from langchain_aws import ChatBedrockConverse
        from langchain_core.output_parsers import StrOutputParser

        # Converse is Bedrock's model-agnostic chat API, the same for every model.
        # The parser makes ainvoke() return text, as Ollama's does: the model can
        # answer with a list of content blocks, and every caller puts the result
        # into text such as a patient email.
        return cast(
            BaseLanguageModel,
            ChatBedrockConverse(
                model=settings.bedrock_model_id,
                region_name=settings.aws_region,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
                timeout=settings.llm_timeout_seconds,
            )
            | StrOutputParser(),
        )

    raise ValueError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Use 'ollama' or 'bedrock'.")

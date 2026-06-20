from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from openai import AsyncOpenAI

from .config import Settings


T = TypeVar("T")


def should_retry(exc: Exception) -> bool:
    text = str(exc).lower()
    permanent = ["400", "401", "403", "404", "invalid", "unauthorized", "forbidden"]
    transient = ["429", "timeout", "timed out", "rate limit", "502", "503", "504", "server error"]
    if any(marker in text for marker in permanent):
        return False
    if any(marker in text for marker in transient):
        return True
    return any(marker in exc.__class__.__name__.lower() for marker in ["timeout", "network", "connection"])


async def with_retries(factory: Callable[[], Awaitable[T]], max_retries: int) -> T:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await factory()
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries or not should_retry(exc):
                raise
            backoff = min(8.0, 1.6**attempt) + random.uniform(0, 0.35)
            await asyncio.sleep(backoff)
    raise RuntimeError(f"unreachable retry state: {last_error}")


class SiliconFlow:
    def __init__(self, settings: Settings):
        if not settings.chat_api_key:
            raise ValueError("Missing chat API key. Configure cc-switch or ROUNDTABLE_CHAT_API_KEY.")
        if not settings.embed_api_key:
            raise ValueError("Missing embedding API key. Configure SILICONFLOW_API_KEY or ROUNDTABLE_EMBED_API_KEY.")
        self.settings = settings
        self.chat_client = AsyncOpenAI(api_key=settings.chat_api_key, base_url=settings.chat_base_url)
        self.embed_client = AsyncOpenAI(api_key=settings.embed_api_key, base_url=settings.embed_base_url)
        self.semaphore = asyncio.Semaphore(settings.concurrency)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        async def call():
            async with self.semaphore:
                kwargs = {
                    "model": self.settings.embed_model,
                    "input": texts,
                }
                if self.settings.embed_dimensions is not None:
                    kwargs["dimensions"] = self.settings.embed_dimensions
                return await self.embed_client.embeddings.create(**kwargs)

        response = await with_retries(call, self.settings.max_retries)
        ordered = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in ordered]

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        async def call():
            async with self.semaphore:
                if self.settings.chat_wire_api == "responses":
                    return await self.chat_client.responses.create(
                        model=self.settings.chat_model,
                        input=messages,
                        max_output_tokens=max_tokens or self.settings.max_tokens,
                    )
                return await self.chat_client.chat.completions.create(
                        model=self.settings.chat_model,
                        messages=messages,
                        temperature=self.settings.temperature if temperature is None else temperature,
                        max_tokens=self.settings.max_tokens if max_tokens is None else max_tokens,
                    )

        response = await with_retries(call, self.settings.max_retries)
        if self.settings.chat_wire_api == "responses":
            return extract_response_text(response)
        if not response.choices:
            return ""
        return response.choices[0].message.content or ""


def extract_response_text(response: object) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text

    if hasattr(response, "model_dump"):
        data = response.model_dump()
    elif isinstance(response, dict):
        data = response
    else:
        data = {}

    parts: list[str] = []
    for item in data.get("output", []) if isinstance(data, dict) else []:
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)

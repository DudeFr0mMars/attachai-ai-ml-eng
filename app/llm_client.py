"""Part 3 LLM contract, real OpenAI client, and a free test double."""

import json
import random
import time
from typing import Literal, Protocol, TypedDict

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings


class ExtractedAttribute(TypedDict):
    kind: str  # need | offer | context | interest
    text: str
    confidence: float
    restricted: bool


class LLMClient(Protocol):
    def extract_attributes(self, message_text: str) -> list[ExtractedAttribute]:
        """Extract structured attributes from one raw member message."""
        ...


class FakeLLMClient:
    """Trivial test double — does not call any real API."""

    def __init__(self, canned_response: list[ExtractedAttribute] | None = None) -> None:
        self.canned_response = canned_response or []
        self.calls: list[str] = []

    def extract_attributes(self, message_text: str) -> list[ExtractedAttribute]:
        self.calls.append(message_text)
        return self.canned_response


class _AttributeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["need", "offer", "context", "interest"]
    text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    restricted: bool


class _ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attributes: list[_AttributeModel]


SCHEMA = {
    "type": "object",
    "properties": {
        "attributes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["need", "offer", "context", "interest"]},
                    "text": {"type": "string"},
                    "confidence": {"type": "number"},
                    "restricted": {"type": "boolean"},
                },
                "required": ["kind", "text", "confidence", "restricted"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["attributes"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Extract durable, explicit facts from one private-club member message as structured attributes.
Return zero or more concise standalone attributes; do not infer unstated facts. Use kind=need for a request or search, offer for experience/resources the speaker can provide, interest for a shared activity, and context for background or personal circumstances. Future/uncertain plans should have low confidence. Confidence is 0–1 and measures support in the message, not importance.
Set restricted=true for every attribute involving health, medical/clinical history, therapy, mental health, diagnoses, or psychometric information. A medical or psychometric fact must never be restated in a non-restricted attribute. If a sentence contains a separable ordinary preference, it may be a separate non-restricted attribute only if its text reveals no restricted fact. Do not include identifying details not needed for the attribute.
Examples: a member seeking investors has a need; an experienced angel investor offering help has an offer; a weekly running partner request is an interest; mentioning therapy is restricted context. Return an empty array for messages with no supported durable attribute."""


class ExtractionError(Exception):
    pass


class OpenAILLMClient:
    def __init__(self, *, model: str | None = None, max_attempts: int = 3) -> None:
        self.model = model or settings.openai_model
        self.max_attempts = max_attempts

    def extract_attributes(self, message_text: str) -> list[ExtractedAttribute]:
        api_key = settings.openai_api_key
        if not api_key:
            raise ExtractionError("OPENAI_API_KEY is not configured")

        request = {
            "model": self.model,
            "input": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message_text},
            ],
            "text": {"format": {"type": "json_schema", "name": "member_attributes", "strict": True, "schema": SCHEMA}},
            "store": False,
        }
        for attempt in range(self.max_attempts):
            try:
                response = httpx.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=request,
                    timeout=30,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt + 1 == self.max_attempts:
                    raise ExtractionError("OpenAI transport failure after retries") from exc
            else:
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    if attempt + 1 == self.max_attempts:
                        raise ExtractionError(f"OpenAI transient HTTP {response.status_code} after retries")
                elif response.is_error:
                    raise ExtractionError(f"OpenAI HTTP {response.status_code}")
                else:
                    try:
                        payload = response.json()
                        if payload.get("status") != "completed":
                            raise ValueError("response was not completed")
                        texts = [
                            part["text"]
                            for item in payload["output"]
                            for part in item.get("content", [])
                            if part.get("type") == "output_text"
                        ]
                        if len(texts) != 1:
                            raise ValueError("expected one structured output text")
                        result = _ExtractionResult.model_validate(json.loads(texts[0]))
                        return [ExtractedAttribute(**attribute.model_dump()) for attribute in result.attributes]
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ExtractionError("invalid structured OpenAI response") from exc

            # Bounded exponential backoff with jitter, capped at four seconds.
            time.sleep(min(4.0, 0.5 * 2**attempt) + random.uniform(0, 0.25))

        raise ExtractionError("OpenAI retries exhausted")


def get_llm_client() -> LLMClient:
    return OpenAILLMClient()

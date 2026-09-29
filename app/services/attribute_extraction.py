"""Structured member-attribute extraction through the real OpenAI Responses API."""

import json
import random
import re
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings


class ExtractedAttribute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["need", "offer", "context", "interest"]
    text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    restricted: bool


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attributes: list[ExtractedAttribute]


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

# Fail closed for explicit sensitive terms, including when the model incorrectly
# marks an attribute from a mixed message non-restricted.
SENSITIVE_TERMS = re.compile(
    r"\b(?:health|medical|clinical|diagnos\w*|therap\w*|psych\w*|anxiety|depression|"
    r"mental\s+health|chronic\s+condition|illness|disease|disability|medicat\w*)\b",
    re.IGNORECASE,
)


def enforce_restricted(message: str, attributes: list[ExtractedAttribute]) -> list[ExtractedAttribute]:
    if SENSITIVE_TERMS.search(message):
        return [attribute.model_copy(update={"restricted": True}) for attribute in attributes]
    return [
        attribute.model_copy(update={"restricted": True})
        if SENSITIVE_TERMS.search(attribute.text) else attribute
        for attribute in attributes
    ]


class ExtractionError(Exception):
    pass


class OpenAIAttributeExtractor:
    def __init__(self, *, model: str | None = None, max_attempts: int = 3) -> None:
        self.model = model or settings.openai_model
        self.max_attempts = max_attempts

    def extract(self, message: str) -> list[ExtractedAttribute]:
        api_key = settings.openai_api_key
        if not api_key:
            raise ExtractionError("OPENAI_API_KEY is not configured")

        request = {
            "model": self.model,
            "input": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
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
                        result = ExtractionResult.model_validate(json.loads(texts[0]))
                        return enforce_restricted(message, result.attributes)
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ExtractionError("invalid structured OpenAI response") from exc

            # Bounded exponential backoff with jitter, capped at four seconds.
            time.sleep(min(4.0, 0.5 * 2**attempt) + random.uniform(0, 0.25))

        raise ExtractionError("OpenAI retries exhausted")


def get_attribute_extractor() -> OpenAIAttributeExtractor:
    return OpenAIAttributeExtractor()

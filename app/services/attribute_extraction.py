"""Privacy enforcement after extraction and before database persistence."""

import re

from app.llm_client import ExtractedAttribute


# Fail closed for explicit sensitive terms, including when the model incorrectly
# marks an attribute from a mixed message non-restricted.
SENSITIVE_TERMS = re.compile(
    r"\b(?:health|medical|clinical|diagnos\w*|therap\w*|psych\w*|anxiety|depression|"
    r"mental\s+health|chronic\s+condition|illness|disease|disability|medicat\w*)\b",
    re.IGNORECASE,
)


def enforce_restricted(message: str, attributes: list[ExtractedAttribute]) -> list[ExtractedAttribute]:
    if SENSITIVE_TERMS.search(message):
        return [ExtractedAttribute(**{**attribute, "restricted": True}) for attribute in attributes]
    return [
        ExtractedAttribute(**{**attribute, "restricted": True})
        if SENSITIVE_TERMS.search(attribute["text"]) else attribute
        for attribute in attributes
    ]

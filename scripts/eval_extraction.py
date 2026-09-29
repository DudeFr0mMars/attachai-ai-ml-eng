"""Real-API extraction eval against eval/golden_set.json; no database writes."""

import json
from pathlib import Path

from app.services.attribute_extraction import OpenAIAttributeExtractor


GOLDEN_SET = Path(__file__).resolve().parents[1] / "eval" / "golden_set.json"
PASS_THRESHOLD = 0.75


def main() -> int:
    records = json.loads(GOLDEN_SET.read_text())
    extractor = OpenAIAttributeExtractor()
    passes = 0
    restricted_correct = True
    for index, record in enumerate(records, 1):
        try:
            attributes = extractor.extract(record["message"])
        except Exception as exc:
            print(f"record {index}: ERROR {exc}")
            restricted_correct = False
            continue

        relevant = [
            a for a in attributes
            if any(keyword.lower() in a.text.lower() for keyword in record["expected_keywords"])
        ]
        kind_ok = any(a.kind == record["expected_kind"] for a in relevant)
        restricted_ok = bool(relevant) and all(
            a.restricted is record["expected_restricted"] for a in relevant
        )
        text_ok = bool(relevant)
        # The three checks must describe the same extracted attribute.
        matched = any(
            a.kind == record["expected_kind"]
            and a.restricted is record["expected_restricted"]
            and any(keyword.lower() in a.text.lower() for keyword in record["expected_keywords"])
            for a in attributes
        )
        passes += matched
        restricted_correct &= restricted_ok
        print(
            f"record {index}: kind={kind_ok} restricted={restricted_ok} keyword={text_ok} "
            f"pass={matched} attributes={len(attributes)}"
        )

    score = passes / len(records)
    print(f"overall: {passes}/{len(records)} = {score:.1%}; threshold={PASS_THRESHOLD:.0%}; restricted_all_correct={restricted_correct}")
    return 0 if score >= PASS_THRESHOLD and restricted_correct else 1


if __name__ == "__main__":
    raise SystemExit(main())

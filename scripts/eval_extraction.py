"""Real-API extraction eval against eval/golden_set.json; no database writes."""

import json
from datetime import datetime, timezone
from pathlib import Path

from app.services.attribute_extraction import OpenAIAttributeExtractor


GOLDEN_SET = Path(__file__).resolve().parents[1] / "eval" / "golden_set.json"
RESULTS_FILE = GOLDEN_SET.with_name("golden_set_results.json")
PASS_THRESHOLD = 0.75


def main() -> int:
    records = json.loads(GOLDEN_SET.read_text())
    extractor = OpenAIAttributeExtractor()
    passes = 0
    restricted_correct = True
    results = []
    for index, record in enumerate(records, 1):
        try:
            attributes = extractor.extract(record["message"])
        except Exception as exc:
            print(f"record {index}: ERROR {exc}")
            restricted_correct = False
            results.append({
                "record": index,
                "expected_kind": record["expected_kind"],
                "expected_restricted": record["expected_restricted"],
                "expected_keywords": record["expected_keywords"],
                "extracted_attributes": [],
                "kind_match": False,
                "restricted_match": False,
                "keyword_match": False,
                "passed": False,
                "error": type(exc).__name__,
            })
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
        results.append({
            "record": index,
            "expected_kind": record["expected_kind"],
            "expected_restricted": record["expected_restricted"],
            "expected_keywords": record["expected_keywords"],
            "extracted_attributes": [attribute.model_dump() for attribute in attributes],
            "kind_match": kind_ok,
            "restricted_match": restricted_ok,
            "keyword_match": text_ok,
            "passed": matched,
            "error": None,
        })
        print(
            f"record {index}: kind={kind_ok} restricted={restricted_ok} keyword={text_ok} "
            f"pass={matched} attributes={len(attributes)}"
        )

    score = passes / len(records)
    overall_passed = score >= PASS_THRESHOLD and restricted_correct
    report = {
        "dataset": "eval/golden_set.json",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": extractor.model,
        "records": results,
        "overall": {
            "passed_records": passes,
            "total_records": len(records),
            "score": score,
            "threshold": PASS_THRESHOLD,
            "restricted_all_correct": restricted_correct,
            "passed": overall_passed,
        },
    }
    RESULTS_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"overall: {passes}/{len(records)} = {score:.1%}; threshold={PASS_THRESHOLD:.0%}; restricted_all_correct={restricted_correct}")
    print(f"results_json: {RESULTS_FILE}")
    return 0 if overall_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

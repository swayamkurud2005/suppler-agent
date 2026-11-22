"""Validate source hashes and ground truth in the evaluation dataset."""
import hashlib
import argparse
import json
import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATASET = BACKEND_DIR / "data" / "evaluations" / "contract_qa_v1.jsonl"
CONTRACTS_DIR = BACKEND_DIR / "data" / "contracts"


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument(
        "--expected-count",
        type=int,
        help="Optionally assert a fixed record count (for example, 10 for the initial dataset).",
    )
    args = parser.parse_args()

    import sys
    sys.path.insert(0, str(BACKEND_DIR))
    from app.services.document_parser import parse_document

    records = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors = []
    if not records:
        errors.append("Dataset is empty.")
    if args.expected_count is not None and len(records) != args.expected_count:
        errors.append(f"Expected {args.expected_count} records; found {len(records)}.")

    ids = [record.get("question_id") for record in records]
    if len(ids) != len(set(ids)):
        errors.append("Question IDs are not unique.")

    questions = [normalize(record.get("question", "")) for record in records]
    if len(questions) != len(set(questions)):
        errors.append("Duplicate question text found.")

    full_records = [json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records]
    if len(full_records) != len(set(full_records)):
        errors.append("Duplicate records found.")

    page_cache = {}
    for index, record in enumerate(records, 1):
        print(f"Checking {record.get('question_id')}...", flush=True)
        prefix = f"Record {index} ({record.get('question_id')}): "
        for required in ("question", "reference_answer", "source_document", "source_file", "category", "difficulty", "ground_truth_status"):
            if not str(record.get(required, "")).strip():
                errors.append(prefix + f"missing {required}.")

        status = record.get("ground_truth_status")
        if status not in {"verified", "synthetic", "unavailable"}:
            errors.append(prefix + "ground_truth_status must be verified, synthetic, or unavailable.")

        contexts = record.get("reference_contexts", [])
        if status in {"verified", "synthetic"} and not contexts:
            errors.append(prefix + "grounded record has no reference context.")
        if status == "unavailable" and not str(record.get("notes", "")).strip():
            errors.append(prefix + "unavailable ground truth needs an explanatory note.")

        filename = record.get("source_file", "")
        if record.get("category_source") == "project_seed":
            source_path = BACKEND_DIR / filename
        else:
            source_path = CONTRACTS_DIR / Path(filename).name
        if not source_path.is_file():
            errors.append(prefix + f"source file does not exist: {filename}.")
            continue

        raw = source_path.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if record.get("source_sha256", "").lower() != actual_hash:
            errors.append(prefix + "source SHA-256 does not match the original file.")
            continue

        if status == "synthetic":
            normalized_source = normalize(raw.decode("utf-8", errors="replace"))
            for context in contexts:
                if normalize(context) not in normalized_source:
                    errors.append(prefix + "synthetic reference context was not found in its declared seed source.")
                    break
            continue
        if status != "verified":
            continue

        if filename not in page_cache:
            print(f"Extracting {filename}...", flush=True)
            page_cache[filename] = parse_document(filename, raw)
            print(f"Extracted {len(page_cache[filename])} pages.", flush=True)
        pages = page_cache[filename]
        source_page = record.get("source_page")
        if source_page is None:
            extracted = " ".join(page["text"] for page in pages)
        else:
            matching = [page["text"] for page in pages if page["page"] == source_page]
            if not matching:
                errors.append(prefix + f"source page {source_page} was not extracted.")
                continue
            extracted = matching[0]

        normalized_extracted = normalize(extracted)
        for context in contexts:
            if normalize(context) not in normalized_extracted:
                errors.append(prefix + "reference context was not found in the indicated extracted source.")
                break

    if errors:
        print("Dataset validation FAILED")
        for error in errors:
            print("- " + error)
        return 1

    unique_sources = len({record["source_file"] for record in records})
    print(f"Dataset validation PASSED: {len(records)} records, {len(set(ids))} unique IDs, {unique_sources} source files; verified contexts match extracted source text and synthetic contexts match their declared seed source and SHA-256 hash.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

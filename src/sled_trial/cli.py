import argparse
import json
from pathlib import Path

from .pipeline import load_records, normalize


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    normalized = []
    errors = []
    for record in load_records(args.input):
        try:
            normalized.append(normalize(record).to_dict())
        except ValueError as exc:
            errors.append({"record": record, "error": str(exc)})
    (args.output / "opportunities.json").write_text(json.dumps(normalized, indent=2) + "\n")
    (args.output / "review_queue.json").write_text(json.dumps(errors, indent=2) + "\n")
    print(f"normalized={len(normalized)} review={len(errors)}")


if __name__ == "__main__":
    main()


from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from photoclean.safety_contract import (
        SafetyContractError,
        build_source_safety_contract,
        validate_source_safety_contract,
    )
except ModuleNotFoundError:  # direct execution from tools/ on unusual launchers
    import sys

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from photoclean.safety_contract import (  # type: ignore
        SafetyContractError,
        build_source_safety_contract,
        validate_source_safety_contract,
    )

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "assets" / "safety-contract.json"


def write_contract(output: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output).expanduser().resolve()
    payload = build_source_safety_contract(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def verify_contract(path: str | Path = DEFAULT_OUTPUT) -> dict:
    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SafetyContractError(f"cannot read safety contract: {error}") from error
    return validate_source_safety_contract(payload, ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate or verify the deterministic SwirPhotoClean release-safety contract."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    writer = subparsers.add_parser("write")
    writer.add_argument("--output", default=str(DEFAULT_OUTPUT))
    verifier = subparsers.add_parser("verify")
    verifier.add_argument("--file", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    try:
        if args.command == "write":
            output = write_contract(args.output)
            payload = verify_contract(output)
            print(f"SAFETY_CONTRACT_WRITTEN path={output} sha256={payload['sha256']}")
            return 0
        payload = verify_contract(args.file)
        print(f"SAFETY_CONTRACT_VALID sha256={payload['sha256']}")
        return 0
    except SafetyContractError as error:
        raise SystemExit(f"safety contract failed: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())

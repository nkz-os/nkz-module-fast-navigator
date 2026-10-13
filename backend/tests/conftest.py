import json
import pathlib

CONTRACTS = pathlib.Path(__file__).parent / "fixtures" / "contracts"


def load_contract(name: str) -> dict:
    """A recorded response of a platform service (see fixtures/contracts)."""
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))

#!/usr/bin/env python3
"""Write a seed corpus of valid register images and manifests.

A coverage-guided fuzzer starting from random bytes spends its whole budget
failing to produce the four-byte "SunS" marker. Starting from real images
produced by the simulator, it spends that budget on the decode paths instead.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from otwin.io.simulator import SunSpecSimulator  # noqa: E402


def main(out: Path) -> None:
    chain = out / "sunspec_chain"
    chain.mkdir(parents=True, exist_ok=True)
    for i, soc in enumerate((0.0, 0.25, 0.5, 0.87, 1.0)):
        words = SunSpecSimulator(soc=soc).get_raw(40000, 900)
        blob = b"".join(int(w).to_bytes(2, "big") for w in words)
        (chain / f"image_{i}.bin").write_bytes(blob)

    man = out / "manifest"
    man.mkdir(parents=True, exist_ok=True)
    seed = {
        "manifest_version": "1.0",
        "provenance": {"created_at": "2026-01-01T00:00:00Z"},
        "estimated": ["soc"],
        "validation": {"horizon": 500, "state_bounds": [[0.0, 1.0]]},
        "calibration": {"empirical_coverage": 0.94},
    }
    (man / "seed.json").write_text(json.dumps(seed))
    print(f"wrote seed corpus under {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "fuzz/corpus"))

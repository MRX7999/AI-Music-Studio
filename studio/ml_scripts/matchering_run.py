"""Matchering 2.0 runner, executed with the Python of a separate venv (~/.ams-tools/matchering).

Matchering is GPL-3.0. It is never imported by the MIT engine and is not bundled; this script
only talks to it through its public API in its own process.

usage: python matchering_run.py TARGET REFERENCE OUTPUT.wav [--bits 24] [--no-limiter]
"""
import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("reference")
    ap.add_argument("output")
    ap.add_argument("--bits", type=int, default=24, choices=(16, 24, 32))
    ap.add_argument("--no-limiter", action="store_true")
    a = ap.parse_args()
    import matchering as mg
    print("Matchering", getattr(mg, "__version__", "?"), flush=True)
    mg.log(print)
    subtype = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[a.bits]
    res = mg.Result(a.output, subtype=subtype, use_limiter=not a.no_limiter)
    print("10%", flush=True)
    mg.process(target=a.target, reference=a.reference, results=[res])
    print("100%", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

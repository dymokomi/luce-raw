#!/usr/bin/env python3
"""Corrupt the sample raws and check luce-raw fails with errors, never traps.

Each round truncates a sample or overwrites bytes in its first 256 KiB (where the
headers, directories and maker notes live) or in its sensor data, then runs the
driver's `sensor` (parse and unpack) and `develop` (the whole pipeline, fast
mode) on it. An error exit is fine; a trap or a signal is a failure.
Usage: fuzz.py [ROUNDS_PER_SAMPLE] [SEED] [SAMPLE...]
"""
import json, random, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "build/driver"


def run(path, out):
    for command in (["sensor", path, out], ["develop", path, out, "fast", "1", "1"]):
        done = subprocess.run([DRIVER, *command], capture_output=True, text=True, timeout=300)
        if "trap" in done.stderr or done.returncode < 0 or done.returncode > 2:
            return f"{command[0]}: exit {done.returncode}: {done.stderr.strip()[:300]}"
    return None


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    manifest = json.loads((ROOT / "tests/samples.json").read_text())
    if len(sys.argv) > 3:
        manifest = [entry for entry in manifest if entry["name"] in sys.argv[3:]]
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        case, out = Path(tmp) / "case.raw", str(Path(tmp) / "out")
        for entry in manifest:
            data = (ROOT / "build/samples" / entry["name"]).read_bytes()
            for i in range(rounds):
                kind = rng.choice(["truncate", "header", "header", "data"])
                bad = bytearray(data)
                if kind == "truncate":
                    bad = bad[:rng.randrange(0, len(bad))]
                else:
                    lo, hi = (0, min(len(bad), 262144)) if kind == "header" else (len(bad) // 4, len(bad))
                    for _ in range(rng.randint(1, 16)):
                        at = rng.randrange(lo, hi)
                        bad[at] = rng.choice([0, 255, rng.randrange(256), bad[at] ^ (1 << rng.randrange(8))])
                case.write_bytes(bad)
                problem = run(str(case), out)
                if problem:
                    keep = ROOT / f"build/fuzz-{entry['name']}-{i}"
                    keep.write_bytes(bad)
                    failures.append(f"{entry['name']} round {i} ({kind}): {problem} -> {keep.name}")
                    print("FAIL", failures[-1], flush=True)
            print(f"fuzzed {entry['name']}", flush=True)
    if failures:
        raise SystemExit(f"{len(failures)} fuzz failures")
    print("PASS fuzz: errors only, no traps")


if __name__ == "__main__":
    main()

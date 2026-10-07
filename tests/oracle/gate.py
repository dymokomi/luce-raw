#!/usr/bin/env python3
"""luce-raw against LibRaw, run by tests/oracle/main.luc (`luc test`); the module's
own test blocks run in `luc test` too.

1. The sample raws (tests/samples.json, CC0 files from raw.pixls.us, fetched into
   build/samples and checked by SHA-256) against LibRaw through rawpy, in a
   virtual environment under build/venv: sensor samples and levels exactly, the
   developed image within tolerance (tests/oracle.py).
2. The time to develop a 24 MP raw.

--fuzz N adds N corruption rounds per sample (tests/fuzz.py). Exits 77 when the
samples cannot be fetched (no network), which the program reports as a skip.
"""
import argparse, hashlib, json, os, subprocess, sys, urllib.request, venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"
BASE = os.environ.get("LUCE_BASE", "luce-base")
ENV = dict(os.environ)


def run(*command, **options):
    subprocess.run([str(c) for c in command], env=ENV, check=True, cwd=ROOT, **options)


def fetch_samples():
    folder = BUILD / "samples"
    folder.mkdir(parents=True, exist_ok=True)
    for entry in json.loads((ROOT / "tests/samples.json").read_text()):
        path = folder / entry["name"]
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]:
            continue
        print(f"fetching {entry['name']} ({entry['camera']})", flush=True)
        try:
            with urllib.request.urlopen(entry["url"], timeout=600) as response:
                data = response.read()
        except OSError as failure:
            print(f"skip: the sample raws cannot be fetched ({failure})", flush=True)
            sys.exit(77)
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise SystemExit(f"{entry['name']}: checksum mismatch")
        path.write_bytes(data)


def oracle_python():
    folder = BUILD / "venv"
    python = folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        venv.create(folder, with_pip=True)
    # Reinstall whenever the venv's rawpy is not the pinned one (tests/requirements.txt).
    pinned = next(line.split("==")[1].strip() for line in (ROOT / "tests/requirements.txt").read_text().splitlines()
                  if line.startswith("rawpy=="))
    probe = subprocess.run([python, "-c", f"import numpy, rawpy; assert rawpy.__version__ == {pinned!r}"],
                           capture_output=True)
    if probe.returncode != 0:
        run(python, "-m", "pip", "install", "-q", "-r", ROOT / "tests/requirements.txt")
    return python


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fuzz", type=int, default=0, help="corruption rounds per sample")
    args = parser.parse_args()
    BUILD.mkdir(exist_ok=True)
    run(BASE, "build", "tests/driver.lucb", "-o", BUILD / "driver", "--release", timeout=900)
    fetch_samples()
    run(oracle_python(), ROOT / "tests/oracle.py", timeout=3600)
    if args.fuzz:
        run(sys.executable, ROOT / "tests/fuzz.py", args.fuzz, timeout=7200)
    for name in ["sony_a7m2_14c.arw", "nikon_d750_14l.nef"]:
        for quality in ["best", "fast"]:
            spent = subprocess.run([BUILD / "driver", "bench", BUILD / "samples" / name, "3", quality],
                                   env=ENV, check=True, capture_output=True, text=True).stdout.strip()
            print(f"speed {name} (24 MP) {quality}: {spent}")
    print("PASS luce-raw")


if __name__ == "__main__":
    main()

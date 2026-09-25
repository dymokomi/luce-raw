#!/usr/bin/env python3
"""Compare luce-raw with LibRaw (rawpy) on the sample raws.

For each sample: the sensor samples after linearization must equal LibRaw's
raw_image exactly, with the same white level and black levels; the developed
image (AHD, as-shot white balance, linear sRGB, no crop, no exposure) must
agree with LibRaw's postprocess within the tolerances below. Run with the
virtual environment tests/run.py prepares; prints one line per sample.
"""
import json, os, subprocess, sys, time
from pathlib import Path
import numpy as np
import rawpy

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
DRIVER = BUILD / "driver"
# Developed image tolerances, on values where white is 1.0: the mean absolute
# difference, and the share of pixels differing by more than 0.05 in any channel.
# Camera space (before the color matrix) isolates levels, white balance and
# demosaicing; sRGB adds the color model, where DNG differs by design: LibRaw
# uses the D65 ColorMatrix alone, luce-raw the DNG SDK's interpolated matrices
# and ForwardMatrix.
MEAN_LIMIT = {"camera": 0.002, "dng": 0.012, "table": 0.004, "generic": 1.0}
OUTLIER_LIMIT = {"camera": 0.002, "dng": 0.05, "table": 0.01, "generic": 1.0}


def header(path):
    return Path(str(path) + ".txt").read_text().split()


def check_sensor(sample, out):
    subprocess.run([DRIVER, "sensor", sample, out], check=True)
    h = header(out)
    width, height, channels, top, left, aw, ah = map(int, h[:7])
    cfa = list(map(int, h[7:11]))
    black = list(map(float, h[11:15]))
    white = float(h[15])
    ours = np.fromfile(out, dtype=np.uint16).reshape(height, width, channels)
    with rawpy.imread(str(sample)) as r:
        if channels == 1:
            theirs = r.raw_image.copy()
            if theirs.shape != (height, width):
                return False, f"sensor size {width}x{height} vs LibRaw {theirs.shape[1]}x{theirs.shape[0]}"
            mismatch = int(np.count_nonzero(theirs != ours[:, :, 0]))
            if mismatch:
                return False, f"{mismatch} sensor samples differ from LibRaw"
            # LibRaw's per-color black levels against ours at the active area's 2x2.
            lib_black = r.black_level_per_channel
            pattern = r.raw_pattern
            desc = r.color_desc.decode()
            for i in range(4):
                y, x = (top + i // 2), (left + i % 2)
                idx = pattern[y % 2][x % 2]
                if abs(lib_black[idx] - black[i]) > 1.0:
                    return False, f"black {black} vs LibRaw {lib_black}"
                color = "RGB".index(desc[idx]) if desc[idx] in "RGB" else 1
                if color != cfa[i]:
                    return False, f"CFA {cfa} vs LibRaw {pattern.tolist()} {desc}"
            if abs(r.white_level - white) > 1.0:
                return False, f"white {white} vs LibRaw {r.white_level}"
        else:
            theirs = r.raw_image_visible
    return True, f"sensor exact ({width}x{height}, black {black[0]:g}, white {white:g})"


def overlap(ours, theirs, dy, dx):
    """The overlapping windows when our origin sits at (dy, dx) of theirs."""
    y0, x0 = max(0, dy), max(0, dx)
    y1 = min(theirs.shape[0], dy + ours.shape[0])
    x1 = min(theirs.shape[1], dx + ours.shape[1])
    return ours[y0 - dy:y1 - dy, x0 - dx:x1 - dx], theirs[y0:y1, x0:x1]


def best_alignment(ours, theirs):
    """Where our origin sits in LibRaw's image: the crops differ by camera."""
    best = None
    ry = range(min(0, theirs.shape[0] - ours.shape[0]) - 2, max(0, theirs.shape[0] - ours.shape[0]) + 3)
    rx = range(min(0, theirs.shape[1] - ours.shape[1]) - 2, max(0, theirs.shape[1] - ours.shape[1]) + 3)
    for dy in ry:
        for dx in rx:
            a, b = overlap(ours, theirs, dy, dx)
            err = float(np.mean(np.abs(a[::7, ::7] - b[::7, ::7])))
            if best is None or err < best[0]:
                best = (err, dy, dx)
    return best[1], best[2]


def check_develop(sample, out, matrix, space):
    subprocess.run([DRIVER, "develop", sample, out, "best", "0", "0", space], check=True)
    w, h = map(int, header(out)[:2])
    ours = np.fromfile(out, dtype=np.float32).reshape(h, w, 3)
    with rawpy.imread(str(sample)) as r:
        theirs = r.postprocess(demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD, use_camera_wb=True,
                               output_color=rawpy.ColorSpace.raw if space == "camera" else rawpy.ColorSpace.sRGB, gamma=(1, 1), no_auto_bright=True,
                               output_bps=16, highlight_mode=rawpy.HighlightMode.Clip,
                               adjust_maximum_thr=0.0, user_sat=None, bright=1.0)
    theirs = theirs.astype(np.float32) / 65535.0
    if abs(theirs.shape[0] - h) > 64 or abs(theirs.shape[1] - w) > 64:
        return False, f"developed {w}x{h} vs LibRaw {theirs.shape[1]}x{theirs.shape[0]}"
    dy, dx = best_alignment(ours, theirs)
    a, b = overlap(ours, theirs, dy, dx)
    # Leave out the five-pixel border, which each library fills its own way.
    a = np.clip(a[5:-5, 5:-5], 0, 1)
    b = b[5:-5, 5:-5]
    diff = np.abs(a - b)
    mean = float(diff.mean())
    outliers = float(np.mean(diff.max(axis=2) > 0.05))
    kind = "camera" if space == "camera" else matrix
    ok = mean <= MEAN_LIMIT[kind] and outliers <= OUTLIER_LIMIT[kind]
    return ok, f"{space} mean |diff| {mean:.5f}, >0.05 in {outliers * 100:.3f}%"


def main():
    manifest = json.loads((ROOT / "tests/samples.json").read_text())
    names = sys.argv[1:] or [entry["name"] for entry in manifest]
    failed = []
    for name in names:
        sample = BUILD / "samples" / name
        out = BUILD / "out" / name
        out.parent.mkdir(exist_ok=True)
        info = subprocess.run([DRIVER, "info", sample], check=True, capture_output=True, text=True).stdout.split()
        matrix = info[info.index("matrix") + 1]
        ok1, text1 = check_sensor(sample, out.with_suffix(".sensor"))
        ok2, text2 = check_develop(sample, out.with_suffix(".cam"), matrix, "camera")
        ok3, text3 = check_develop(sample, out.with_suffix(".rgb"), matrix, "srgb")
        good = ok1 and ok2 and ok3
        print(f"{'ok  ' if good else 'FAIL'} {name} ({matrix} matrix): {text1}; {text2}; {text3}", flush=True)
        if not good:
            failed.append(name)
    if failed:
        raise SystemExit(f"oracle mismatch: {', '.join(failed)}")


if __name__ == "__main__":
    main()

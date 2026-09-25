# luce-raw

Camera RAW decoding for Luce/Base: DNG, Canon CR2, Nikon NEF, Sony ARW, Olympus ORF,
Panasonic RW2, Pentax PEF and Fujifilm RAF (Bayer) into scene-linear RGB, in pure Luce
Base with no platform codecs. It develops the sensor data the way a raw converter's
open does: black and white levels, white balance, highlight clipping, AHD (or
bilinear) demosaicing, the camera's color matrix into linear sRGB, baseline exposure
and orientation. The result is a luce-raster `Raster` with three float channels, R, G
and B, where the sensor's white after white balance is 1.0.

```luce
import raw
from raster import Raster

var image = Raster(encoded = bytes)            # the file's bytes, owned by the Raster
defer image.close()
let options = raw.Options(quality = .best)     # or temperature = 5500.0, tint = 10.0
try raw.probe(&image, options)                 # size, channels, "make"/"model"/"raw.matrix"
try raw.decode(&image, options)                # image.pixels: linear sRGB, RGB interleaved
```

## API (export `raw`, module `luce_raw.raw`)

- `detect(data) -> bool`: whether the bytes are a raw this package reads (plain TIFFs are not).
- `probe(image: Raster*, options = Options()) -> !`: sizes the Raster from
  `image.encoded`: the developed width and height (after the default crop and
  orientation), three `float32` channels, `file_format` ("DNG", "CR2", ...), and the
  attributes `make`, `model` and `raw.matrix`.
- `decode(image: Raster*, options = Options()) -> !`: develops into `image.pixels`
  (allocated when empty). Probe with the same options first.
- `info(data) -> Info`: format, camera, sensor and developed sizes, bit depth, the
  as-shot `WhiteBalance`, baseline exposure, orientation, and where the color matrix
  came from (`matrix`: "dng", "table" or "generic").
- `white_balance(data, temperature, tint) -> WhiteBalance`: the multipliers that
  make light of that temperature (kelvin) and tint neutral for this camera; zero
  temperature answers the as-shot balance. Temperature and tint use Adobe's
  convention (Robertson's isotemperature lines, tint positive towards magenta), so
  the as-shot numbers read like Camera Raw's.
- `sensor(data) -> Sensor`: the raw sensor samples after the file's linearization,
  with the active area, filter pattern, black and white levels.

`Options`: `quality` (`.best` AHD, `.fast` bilinear), `temperature` and `tint` (zero
temperature keeps the as-shot balance), `exposure` (apply the baseline exposure,
default on), `crop` (the camera's default crop, default on), `camera` (skip the color
matrix: white-balanced camera RGB, for profiling), `threads` (zero: one per processor).

## Formats

| Format | Codings | Notes |
| --- | --- | --- |
| DNG | uncompressed (8/16-bit and bit-packed), lossless JPEG (strips and tiles), Deflate (8/16-bit, horizontal predictors) | Bayer CFA of any 2×2 pattern and LinearRaw; LinearizationTable, BlackLevel with repeat patterns and row/column deltas, WhiteLevel, ActiveArea, DefaultCrop; AsShotNeutral or AsShotWhiteXY; ColorMatrix1/2 with CameraCalibration, AnalogBalance and ForwardMatrix1/2 interpolated for the white's temperature as the DNG SDK does, into XYZ D50 and by Bradford to sRGB; BaselineExposure (+ offset); Orientation |
| Canon CR2 | lossless JPEG with slices | sensor rectangle from the maker note, black measured from the masked columns (or the color data's levels), as-shot white balance from the color data |
| Nikon NEF | lossless and lossy Huffman (with the split-row trees), uncompressed and bit-packed | linearization curve, white balance and black level from the maker note |
| Sony ARW | ARW2 (with the tone curve), uncompressed, lossless (JPEG tiles) | white balance and black from the encrypted SR2 sub-IFD, DefaultCrop |
| Olympus ORF | compressed 12-bit, uncompressed | white balance, black, valid bits and crop from the ImageProcessing directory |
| Panasonic RW2 | raw format 4 (the classic 14-pixels-in-16-bytes coding) | sensor borders, black (+15) and white balance from IFD0 |
| Pentax PEF | Huffman, uncompressed | code table, black and white balance from the maker note |
| Fujifilm RAF | uncompressed 12-bit Bayer | crop, black and white balance from the RAF records and raw block |

Proprietary raws carry no calibrated matrix; `matrices_*.lucb` hold Adobe DNG
Converter's XYZ(D65)-to-camera matrices with their black and white levels, as dcraw's
`adobe_coeff` and LibRaw publish them (619 bodies: Canon, Nikon, Sony, Panasonic,
Leica, Fujifilm, Olympus/OM, Pentax, Ricoh). `tools/matrices.py` regenerates them from
LibRaw's `colordata.cpp`. A camera missing from the tables develops with a generic
matrix (camera RGB taken as sRGB) and says so: `Info.matrix` and the `raw.matrix`
attribute are "generic".

## Pipeline

1. **Unpack** the sensor samples into a 16-bit mosaic and apply the file's
   linearization curve (tiles decode in parallel).
2. **Levels**: subtract black, scale by white − black and by the white balance
   multiplier of each pixel's color (the smallest multiplier is 1), clip to [0, 1],
   as 16-bit values — dcraw's and LibRaw's `scale_colors`.
3. **Demosaic** in tiles on all processors: AHD (dcraw/LibRaw's integer
   implementation, homogeneity in CIELAB) inside a five-pixel border that is filled by
   neighbour averages; or bilinear.
4. **Color**: the balanced camera values to linear sRGB (DNG: the DNG SDK's model;
   tables: dcraw's `cam_xyz_coeff`), times 2^BaselineExposure, negative values clipped,
   written through the orientation.

## Accuracy against LibRaw

`tests/oracle.py` compares every sample with LibRaw 0.22 through rawpy set up like
this package (AHD, as-shot white balance, linear sRGB, clip highlights, no
auto-brightness, no crop):

- The sensor samples must equal LibRaw's `raw_image` exactly, and the white level
  and the black level of every 2×2 position must match within one unit.
- Before the color matrix (camera space), the developed image must match within a
  mean absolute difference of 0.0005, with at most 0.1 % of pixels off by more
  than 0.05 (white is 1.0). Measured: 0.00000–0.00017, and at most 0.05 %.
- In sRGB, tabled cameras must match within 0.001 mean and 0.1 % of pixels
  (measured 0.00002–0.00015 and at most 0.02 %).
  DNGs are held to 0.012: LibRaw develops a DNG with its D65 ColorMatrix alone,
  while this package follows the DNG specification (interpolated matrices and
  ForwardMatrix), which is the point of difference (measured 0.0024–0.0045; with
  LibRaw's model the difference falls to 0.00003).

## Tests

```
./test.sh           # test blocks (native and C), then the samples against LibRaw
./test.sh --quick   # test blocks only (what CI runs)
./test.sh --fuzz 20 # also 20 corruption rounds per sample: errors, never traps
```

The test blocks cover the lossless JPEG decoder (every predictor, one to four
components, restart intervals, 16-bit differences), Huffman tables and the bit
reader on synthetic streams; synthetic DNGs (uncompressed and lossless JPEG) that
must develop a flat field to one grey in every mode; the white balance round trip
through temperature and tint; and truncated and corrupted inputs, which must fail
with errors. The sample raws are CC0 files from raw.pixls.us, listed with their
SHA-256 in `tests/samples.json` and fetched into `build/samples` on first use; the
oracle runs in a virtual environment under `build/venv`.

## Speed

Developing a 24 MP raw on a 16-core Apple M-series machine (`--release`, probe and
decode, file already in memory): 0.32–0.44 s for tiled DNG and for lossless,
uncompressed and ARW2 Sony files; 0.6–0.7 s for NEF, CR2 and single-strip DNG, whose
one entropy-coded stream decodes on a single thread. Bilinear (`fast`) saves
0.15–0.2 s. Tiled decoding, levels and demosaicing use every processor.

## Not supported yet

Canon CR3 (CRX), CRW and sRAW/mRAW; Nikon HE/HE*; 14-bit Olympus/OM ORF; Panasonic
raw formats 5–8 (GH5S, S1, GH6 and later); Fujifilm compressed RAF and X-Trans; Sony
ARW1 and Sony's newer lossy codings; floating-point and lossy-JPEG DNGs, DNG opcode
lists (the lens-shading GainMaps phone DNGs rely on), DefaultScale, and filter
patterns other than 2×2 RGB; embedded previews.

# luce-raw

Camera RAW decoding for Luce/Base: DNG, Canon CR2 and CR3, Nikon NEF, Sony ARW, Olympus ORF,
Panasonic RW2, Pentax PEF and Fujifilm RAF (Bayer and X-Trans, uncompressed and
compressed) into scene-linear RGB, in pure Luce Base with no platform codecs. It
develops the sensor data the way a raw converter's open does: black and white
levels, white balance, highlight clipping, AHD (or bilinear) demosaicing —
Markesteijn's for X-Trans — the camera's color matrix into linear sRGB, baseline
exposure and orientation. The result is a luce-raster `Raster` with three float
channels, R, G and B, where the sensor's white after white balance is 1.0; or the
same pixels as float32 tiles handed to a sink while the develop runs; or, in a
fraction of a millisecond, the largest JPEG the camera embedded.

```luce
import raw
from raster import Raster

var image = Raster(encoded = bytes)            # the file's bytes, owned by the Raster
defer image.close()
let options = raw.Options(quality = .best)     # or temperature = 5500.0, tint = 10.0
try raw.probe(&image, options)                 # size, channels, "make"/"model"/"raw.matrix"
try raw.decode(&image, options)                # image.pixels: linear sRGB, RGB interleaved
```

For an editor's canvas, `develop` delivers the image in tiles as they finish,
from worker threads, without a Raster:

```luce
func paint(context: void*?, tile: const raw.Tile*) -> !:
    let canvas = (Canvas*)(context else return)
    ...                                          # tile.x, tile.y, tile.width, tile.height, tile.pixels

let options = raw.Options(tile = 256, alpha = true)    # 256×256 RGBA float32 tiles
let (width, height) = try raw.dimensions(bytes, options)
try raw.develop(bytes, options, (void*)&canvas, paint)
```

## API (export `raw`, module `luce_raw.raw`)

- `detect(data) -> bool`: whether this package can develop the bytes (plain TIFFs: false).
- `recognize(data) -> bool`: whether the bytes are a camera raw at all, developable or
  not (CRW, X3F, MRW, or a maker TIFF holding sensor data). When `detect` is false
  and `recognize` true, `probe` and `decode` fail with a message saying what is not
  supported (for example "Canon CRW raws are not supported"), so an editor can show
  that instead of treating the file as a plain TIFF.
- `probe(image: Raster*, options = Options()) -> !`: sizes the Raster from
  `image.encoded`: the developed width and height (after the default crop and
  orientation), three `float32` channels, `file_format` ("DNG", "CR2", ...), and the
  attributes `make`, `model` and `raw.matrix`.
- `decode(image: Raster*, options = Options()) -> !`: develops into `image.pixels`
  (allocated when empty). Probe with the same options first.
- `develop(data, options, context: void*?, sink: func(void*?, const Tile*) -> unit!) -> !`:
  develops `data` into tiles of the developed image and hands each to
  `sink(context, tile)` as soon as it is finished. Tiles are `options.tile` pixels
  square (smaller at the right and bottom edges) on a grid from the image's
  top-left, in developed (oriented) coordinates; `Tile` holds `x`, `y`, `width`,
  `height`, `channels` (3, or 4 with `alpha`: alpha 1.0) and `pixels`, `width` ×
  `height` × `channels` straight, linear float32 values, rows packed, valid during
  the call only. The sink runs on worker threads, several at once and in no
  particular order (roughly top to bottom of the sensor); an error it returns stops
  the develop and is returned. Every pixel is delivered exactly once.
- `dimensions(data, options = Options()) -> (usize, usize)`: the width and height
  `develop` and `decode` produce with these options (crop, half size, orientation).
- `preview(data) -> Preview?`: the largest embedded JPEG — TIFF directories and
  SubIFDs (JPEG interchange and JPEG strips), Olympus' camera settings, Panasonic's
  JpgFromRaw, CR3's JPEG track, the RAF header — as `jpeg` (a view of `data`),
  its own `width` and `height` (before orientation), and the raw's `orientation`
  (1–8), or none when the file carries no JPEG. Nothing is decoded: well under a
  millisecond.
- `info(data) -> Info`: format, camera, sensor and developed sizes, bit depth, the
  as-shot `WhiteBalance`, baseline exposure, orientation, and where the color matrix
  came from (`matrix`: "dng", "table" or "generic").
- `white_balance(data, temperature, tint) -> WhiteBalance`: the multipliers that
  make light of that temperature (kelvin) and tint neutral for this camera; zero
  temperature answers the as-shot balance. Temperature and tint use Adobe's
  convention (Robertson's isotemperature lines, tint positive towards magenta), so
  the as-shot numbers read like Camera Raw's.
- `sensor(data) -> Sensor`: the raw sensor samples after the file's linearization,
  with the active area, filter pattern (2×2 `cfa`, and the 6×6 `pattern` with an
  `xtrans` flag), black and white levels.

`Options`: `quality` (`.best` AHD, or Markesteijn's three-pass X-Trans demosaic;
`.fast` bilinear), `temperature` and `tint` (zero temperature keeps the as-shot
balance), `exposure` (apply the baseline exposure, default on), `crop` (the
camera's default crop, default on), `camera` (skip the color matrix: white-balanced
camera RGB, for profiling), `half` (half size without demosaicing: each 2×2 filter
cell becomes one pixel, as LibRaw's `half_size` — the two greens of a Bayer cell
averaged; X-Trans cells as LibRaw lays them, green-only cells taking red and blue
from their neighbours; LinearRaw DNGs, which LibRaw leaves at full size, average
each 2×2 block), `threads` (zero: one per processor), `tile` and `alpha`
(`develop`'s tile side, default 256, and RGBA instead of RGB), and `timings`
(a `Timings*` that receives the time spent parsing, unpacking, leveling and
developing, and the demosaic and output time summed over the workers).

## Formats

| Format | Codings | Notes |
| --- | --- | --- |
| DNG | uncompressed (8/16-bit and bit-packed), lossless JPEG (strips and tiles), Deflate (8/16-bit, horizontal predictors) | Bayer CFA of any 2×2 pattern and LinearRaw; LinearizationTable, BlackLevel with repeat patterns and row/column deltas, WhiteLevel, ActiveArea, DefaultCrop; AsShotNeutral or AsShotWhiteXY; ColorMatrix1/2 with CameraCalibration, AnalogBalance and ForwardMatrix1/2 interpolated for the white's temperature as the DNG SDK does, into XYZ D50 and by Bradford to sRGB; BaselineExposure (+ offset); Orientation |
| Canon CR2 | lossless JPEG with slices | sensor rectangle from the maker note, black measured from the masked columns (or the color data's levels), as-shot white balance from the color data |
| Canon CR3 | CRX: lossless, and C-RAW (up to three levels of 5/3 wavelets, per-subband and version 0x200's per-area quantization), tiled, as LibRaw's crx.cpp | ISO media container; IFD0 and maker note from Canon's uuid box, color data (white balance, black levels) from the CTMD track; the largest raw track |
| Nikon NEF | lossless and lossy Huffman (with the split-row trees), uncompressed and bit-packed | linearization curve, white balance and black level from the maker note (quartered for 12-bit files, as Nikon states it on the 14-bit scale) |
| Sony ARW | ARW2 (with the tone curve), uncompressed, lossless (JPEG tiles) | white balance and black from the encrypted SR2 sub-IFD, DefaultCrop |
| Olympus ORF | compressed 12-bit, uncompressed | white balance, black, valid bits and crop from the ImageProcessing directory |
| Panasonic RW2 | raw format 4 (the classic 14-pixels-in-16-bytes coding) | sensor borders, black (+15) and white balance from IFD0 |
| Pentax PEF | Huffman, uncompressed | code table, black and white balance from the maker note (both the "AOC" and the newer "PENTAX" layouts, as the K-1 writes), masked borders of recent bodies |
| Fujifilm RAF | uncompressed (12-bit packed, 14/16-bit words), compressed lossless and lossy (Fujifilm's strip coding, as LibRaw's fuji_compressed) | Bayer and X-Trans (6×6 pattern from the RAF records), crop, 2×2 or 6×6 black levels and white balance from the raw block |

Proprietary raws carry no calibrated matrix; `matrices_*.lucb` hold Adobe DNG
Converter's XYZ(D65)-to-camera matrices with their black and white levels, as dcraw's
`adobe_coeff` and LibRaw publish them (619 bodies: Canon, Nikon, Sony, Panasonic,
Leica, Fujifilm, Olympus/OM, Pentax, Ricoh). `tools/matrices.py` regenerates them from
LibRaw's `colordata.cpp`. A camera missing from the tables develops with a generic
matrix (camera RGB taken as sRGB) and says so: `Info.matrix` and the `raw.matrix`
attribute are "generic".

## Pipeline

1. **Unpack** the sensor samples into a 16-bit mosaic and apply the file's
   linearization curve. Tiles, ARW2 rows, Fujifilm strips and CRX planes decode in
   parallel. The single entropy-coded streams of CR2 (lossless JPEG) and NEF decode
   in parallel too (`serial.lucb`): their Huffman codes resynchronise, so chunks
   decode speculatively, find where their neighbour's true symbols begin, and then
   decode their own share of differences into place.
2. **Levels**: subtract black, scale by white − black and by the white balance
   multiplier of each pixel's color (the smallest multiplier is 1), clip to [0, 1],
   as 16-bit values — dcraw's and LibRaw's `scale_colors`, through lookup tables
   where the black pattern allows.
3. **Demosaic** in tiles on all processors: AHD (dcraw/LibRaw's integer
   implementation, homogeneity in CIELAB) inside a five-pixel border that is filled by
   neighbour averages; for X-Trans, Markesteijn's three-pass algorithm as LibRaw's
   `xtrans_interpolate(3)` inside an eight-pixel border; or bilinear. The kernels
   are branch-free where the choice is data (which neighbours are homogeneous,
   which direction wins).
4. **Color**: the balanced camera values to linear sRGB (DNG: the DNG SDK's model;
   tables: dcraw's `cam_xyz_coeff`) with 2^BaselineExposure folded into the matrix,
   negative values clipped, turned by the orientation into float32 tiles.

Tiles are cut in developed coordinates, so each output tile maps to one rectangle
of the sensor. For compressed RAF and CR3 at `best`, the stages overlap
(`pipeline.lucb`): levels, X-Trans green ranges and tiles start on the rows the
decoder has finished while it is still working further down the sensor.

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
- `fast` against LibRaw's bilinear (`LINEAR`) and `half` against its `half_size`,
  both in camera space with the camera-space limits (measured 0.00000–0.00010).
- `preview` must answer LibRaw's thumbnail (LibRaw may insert an EXIF segment after
  its start marker) or a larger JPEG, and none only when LibRaw has none.

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
with errors. The sample raws come from raw.pixls.us (almost all CC0), listed with their
SHA-256 in `tests/samples.json` and fetched into `build/samples` on first use; the
oracle runs in a virtual environment under `build/venv`.

## Speed

SPEED_TABLE

## Not supported yet

Canon CRW, sRAW/mRAW and CR3's CRX encoding 3; Nikon HE/HE*; 14-bit Olympus/OM ORF; Panasonic
raw formats 5–8 (GH5S, S1, GH6 and later); Fujifilm SuperCCD (rotated) RAF; Sony
ARW1 and Sony's newer lossy codings; floating-point and lossy-JPEG DNGs, DNG opcode
lists (the lens-shading GainMaps phone DNGs rely on), DefaultScale, and filter
patterns other than 2×2 RGB.

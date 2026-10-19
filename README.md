# UEVR Quad Views Mono

This repository preserves the user-tested Build182 release of a monoscopic
foveated rendering path for STALKER 2 through UEVR, DX12, OpenXR, and PSVR2
Toolkit gaze input.

Despite the project name, this is **not** four-view stereo or OpenXR quad
views. DuoView combines a high-density foveal source and a lower-density
peripheral source into one full-field monoscopic image, then sends that same
image to both OpenXR eye regions. Both Unreal source views share one camera.

## Build182 status

Build182 is the exact package from the original Build182 Actions run, published
here without rebuilding or repacking. On the tested setup, the user confirmed
that it resolved recurring stutter, flicker, gaze jumping, and trembling.
That confirms the user's hardware acceptance for this build; it does not
establish a numerical missed-frame rate or guarantee behavior on other systems.

The package targets STALKER 2 running DX12 with OpenXR. The DuoView path uses
PSVR2 Toolkit's CAPI for gaze when available. Build notes and setup details are
inside the package's `READ_FIRST.txt`.

## Download and install

Download `UEVR-Quad-Views-Mono-v182.zip` from the [v182 release](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v182).
Extract it to a separate folder and follow the included `READ_FIRST.txt`.
Keep an existing working UEVR installation untouched while testing this build.

The release also includes `UEVR-Quad-Views-Mono-v182-actions-artifact.zip`,
the byte-for-byte GitHub Actions artifact archive from the original build. It
contains the original installable package and its original SHA-256 sidecar.
Check release attachments with [`SHA256SUMS`](SHA256SUMS).

## Source and reproducibility

The [`build-182` branch](https://github.com/liviutrn/UEVR-Quad-Views-Mono/tree/build-182) preserves the selected source
files from `liviutrn/OpenNR` commit
[`67c6e1ec5b931d2922e0ef5d253b8e9bef7a1a80`](https://github.com/liviutrn/OpenNR/commit/67c6e1ec5b931d2922e0ef5d253b8e9bef7a1a80).
The `duoview/` source tree is unchanged from that commit and can be checked
with `python scripts/verify_baseline.py`.

The single retained workflow, [duoview-joey-stage234.yml](.github/workflows/duoview-joey-stage234.yml),
reconstructs and verifies the pinned backend, applies the guarded DuoView
changes, runs the CPU and Windows WARP test suites, and packages the injector.
It needs the `UEVR_SOURCE_TOKEN` Actions secret (or the legacy `PAT_TOKEN`)
with access to the pinned `joeyhodge/UESDK` source.

Pinned source revisions and the original run, artifact digest, source hashes,
and verification history are in [`PROVENANCE.json`](PROVENANCE.json). Historical
handoff and review documents under `duoview/` describe earlier work states;
this README and `PROVENANCE.json` are authoritative for Build182. The workflow
is manual so importing this repository does not silently start another build.
Future Actions run numbers restart in the new repository and do not identify
the original Build182 run.

The user's tested setup showed the reported stability fixes. Very high
resolution behavior and VRAM headroom were not characterized; a final crash in
one high-resolution run had no evidence establishing an out-of-memory cause.
One observed UI field rejection (`0x4000`) remains a known limitation. The
reproducible-build workflow does not claim headset validation beyond the user's
Build182 confirmation or a GPU performance gain.

## License and attribution

The included source is distributed under the GNU GPL v3; see [`COPYING`](COPYING)
and [`NOTICE.md`](NOTICE.md). UEVR, UESDK, and third-party components retain
their own names, licenses, and notices.

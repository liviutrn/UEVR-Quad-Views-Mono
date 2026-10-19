# UEVR Quad Views Mono v182

This release republishes the exact package from the original Build182 Actions
run. The package was not rebuilt, modified, or repacked for this repository.

The user tested this exact Build182 package and confirmed that it resolved
stutter, flicker, gaze jumping, and trembling on their setup. No quantitative
0.001% missed-frame measurement is available, and this release makes no such
claim.

The mode produces one monoscopic full-field image from foveal and peripheral
sources and duplicates it to both OpenXR eye regions. It is not four-view
stereo or OpenXR quad views. See the package's `READ_FIRST.txt` for setup and
known limitations.

Release files:

- `UEVR-Quad-Views-Mono-v182.zip`: the original installable package ZIP,
  extracted byte-for-byte from the original Actions artifact archive.
- `UEVR-Quad-Views-Mono-v182-actions-artifact.zip`: the original downloaded
  Actions artifact archive, unchanged.
- `SHA256SUMS` and `PROVENANCE.json`: checksums and build provenance.

Original GitHub Actions run: [39265628148](https://github.com/liviutrn/OpenNR/actions/runs/39265628148).

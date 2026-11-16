# Independent metric-depth raycast WARP replay (research only)

This is **not** the V3 procedural scene family and it is **not** the shipping runtime. It extends the generated, test-only production compositor WARP executable after V3. It has its own camera model, stereo signs, resolution, source fidelity and independent target visibility oracle.

## Provenance / exact inputs

The original `stereo_ground_truth_fixture.py` in the unified DuoView engineering archive generates 12 frames: occlusion, foliage (49 thin leaves at different depths) and near-field weapon, each at four times. It ray-casts real geometric occlusions into left and right images. Re-rendered original raw files matched the source evidence byte-for-byte under Linux. The adapter `export_raycast_inputs.py` creates four GPU inputs per frame: center mono full RGB, encoded central 50%-FOV fovea RGB, and full/fovea **inverse metric depth**. Target left/right images, object IDs and metric depth are **evaluator-only** and must never reach the C++ compositor uploader.

The pinned `raycast_expected.json` contains SHA256s of all 120 adapter input/reference binaries and of the original scene generator. The scorer refuses unverified inputs. It validates the input manifest and GPU metadata without loosening binary hashes. Windows could reveal a platform-dependent binary difference; that is a blocker to investigate rather than a justification to disable the hash gate.

## Projection and native source contract

- Per eye 512×408 RGB8, doublewide WARP output 1024×408 BGRA8, 24 captures (12 zero strength + 12 stereo), metadata `recon_raycast_capture_contract.jsonl`.
- Native periphery source 128×102; native fovea source 256×204. Full 512×408 source textures are padded allocations; uploader fills actual active rectangles.
- Focal length 486.4 output pixels, principal pixel (255.5,203.5), physical eye baseline 0.064 m. At infinity, both per-eye 3×3 homographies equal identity.
- Depth is inverse metric metres, `1/Z_m`, not original metric Z; shader coefficients `{0,1,1}`, `world_to_meters=1`.
- Left signed `k_uv=-0.0304`, right `k_uv=+0.0304`; opposite signs from the V3 synthetic affine corpus.
- The production shader and runtime are untouched; only the generated fixture gets the `DUOVIEW_RECON_RAYCAST=1` conditional block.

## Fail-closed measurements

The evaluator first verifies 120 binary hashes and 24 GPU metadata records, then **all 12 zero-strength** source-registration checks: center interior mean RGB8 <=2.5 and periphery bicubic-filtered outer band <=3.0; both eyes must be byte-identical at zero stereo. It then scores paired zero/stereo against independent left/right GT with true metric Z and object IDs. Its visibility oracle checks center-source sample object ID **and** 2 cm metric depth agreement to distinguish layered leaves sharing the same ID. Reported regions include fovea core, outer periphery, foreground edges, and hidden pixels, with per-eye p95/p99.

## Run locally (Linux is only input/scorer validation)

```bash
python stereo_ground_truth_fixture.py --out /tmp/raycast-original --width 512 --height 408 --frames 4
python export_raycast_inputs.py --input /tmp/raycast-original --out /tmp/raycast-corpus
python score_raycast_warp.py --corpus /tmp/raycast-corpus --expected raycast_expected.json --verify-only
python check_raycast_contract.py --corpus /tmp/raycast-corpus --original /tmp/raycast-original --out /tmp/raycast-geometry-oracle.json
```

**Only after Windows WARP CTest emits 24 real GPU captures:**

```bash
python score_raycast_warp.py --corpus /tmp/raycast-corpus --expected raycast_expected.json --captures /path/to/win-evidence --original /tmp/raycast-original --out /tmp/raycast-scores
```

Never use fabricated perfect-reference controls from the local scoring self-test as GPU measurements. Do not extrapolate WARP timing to RTX 5070 or headset quality, and do not introduce forward splatting or new shader resources until the baseline comparisons justify it.
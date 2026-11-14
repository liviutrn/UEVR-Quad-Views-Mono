# DuoView M9 reviewed test candidate — 14 November 2026

This branch is the first build candidate for M9. Source baseline: `52477eff460c3bee42d48cac0e83fe4f73255720` on `wip/duoview-m9-quality-review-20261114`. No compositor or shader code is modified by this commit.

M9 contains: UEVR world-scale applied once to stereo baseline; depth-edge history with 2–20 output-pixel reach and independently controlled 0–1 strength; widened, depth-reprojected disocclusion color history; depth-aware 5-tap blur configurable 0–32 px; maximum per-eye occlusion sharpness 0.99; distance-faded per-eye asymmetry with independent near/far controls. Retains the M8 fine-depth, eye-tracking stability, near/far edge/ fill controls, and M7 ping-pong accumulation.

Review fixes before this CI run: M8 UI slider exact-anchor corrected to match 0–32 px introduced by M7; temporal correction strength no longer gets applied to the reach budget twice; source-level regression tests updated to match.

CI should run `.github/workflows/triview-b1.yml` through FXC shader compile, generated-source checks, Windows backend, GPU compositor tests and package publishing.

IMPORTANT: This is a build candidate; user has not yet tested M9 in PSVR2. Compare to M8 #294 and M4 #265 for stability. Cheeky DLSS5 NR + stereo ~4 ms interaction remains unconfirmed and has not been fixed here.

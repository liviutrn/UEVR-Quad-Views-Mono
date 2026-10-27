# DuoView 165 V3 + R5 Depth Diagnostics V1

## Baseline

This branch is a descendant of validated V3 source commit
`26b1b412c60fb5383faf078e0f9a4cb30dc94ab3`.
The source UE scene assignment is **UE0 LEFT fovea, UE1 RIGHT periphery**. The cropped LEFT projection is applied **during** UE rendering. Existing Mono-combined output remains unchanged.

## What is proven by this build

The R5 D3D12 observer observes depth DSV bindings/viewport bindings and captures compatible depth textures as GPU-owned resources. Its queue-execution proof is recorded only after a successful actual GPU queue submission with DSV+viewport provenance. Candidate history is bounded to four recent proofs and includes resource identity (opaque pointer for correlating multiple candidates), texture size/format, DSV viewport origin and extent, frame epoch, submission path and explicit unknown eye attribution.

**It does not prove that the depth belongs to left or right**. It does not perform reprojection or write any depth data into the user's headset image.

## How to test in STALKER 2

1. Install ZIP from THIS experimental branch into a separate directory. Preserve the verified V3 installation untouched.
2. Choose UEVR rendering method DuoView ID6 and turn **Split-Eye V3** ON.
3. In the DuoView settings menu enable **R5 DSV/RDG capture in DuoView (experimental, opt-in)**. Exit and re-enter DuoView ID6 so the observer is attached for the new mode generation.
4. In the same DuoView menu look for **Depth DSV/queue proof**. First confirm that `captured` and `submitted` advance over time and `proofHistory` contains actual allocation / viewport metadata. `consumed=0` is expected here because this diagnostic build does not lease captured depth for a shader.
5. First select **Source diagnostic 2 (Fovea)** and take a screenshot with a foreground pole/weapon. Then select **Source diagnostic 1 (Periphery)** from the same head position and take another screenshot. Take a third screenshot with the depth diagnostics expanded and include a short log excerpt containing `[DuoView][R5DepthBridge]` and `[DuoView][Split165]`.
6. Repeat after turning 30–60° and in a doorway/near-field scene. Look for blank captures, resource changes and any freeze, visual regression or V3 camera behavior change.

## What the logs and screenshots let us establish

- Which depth resource(s) were genuinely captured and submitted.
- Capture extents relative to the actual source color allocations.
- Whether there are distinct resource/viewport signatures that might map to the two UE views.
- Whether resource identities are stable over a scene change or move with the camera.
- Whether turning the observer on affects performance/UEVR lifecycle.

To prove **semantic** eye association rather than guessing it, the next diagnostic milestone must bind depth capture to a specific UE view/pass identity or render aligned depth-as-color for each candidate and test alignment against native source color. Shape-only matching is not enough. Do not enable stereo synthesis until both mappings are proven.

## Safety and CI

- The old split-eye V3 code, direct-XR preference, fallback and camera/projection hooks remain unmodified.
- Stock DIBR capture hooks are imported from previously successful R5 code; no stereo shader is used for DuoView.
- Full native backend and frontend build, original compatibility tests, production WARP depth/queue/transaction fixtures, pinned geometry/split-eye tests, and standalone compositor WARP fixtures are mandatory in CI.
- No automatic screenshots are captured from STALKER 2 by GitHub Actions, since the game's runtime and VR headset are not available to CI. User screenshots are necessary for the semantic color/depth proof.

**Interpretation:** A successful CI run means it builds and passes fixtures. Only the user's headset run can verify STALKER 2 color/depth behavior.

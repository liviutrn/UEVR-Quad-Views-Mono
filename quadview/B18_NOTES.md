# TriView B18 — reviewed stability and resource reuse

Parent: B17 `8d1b9d88f6dd27a32da6a641438026c65514d60c`, itself descended directly from B15 `55b99d0`. B16 is not used. Headset verification: **false**.

## Implemented

- NativeDelivery's three-active-role behavior now lives in the canonical header used by both tests and production. Final generated headers are compared after every overlay. B17's failed CI/test mismatch is repaired without masking the assertion.
- Three native color allocations remain roles 0/2/3. Dormant logical role 1 has no UE texture/actor/RHI/native owner; its compositor descriptor aliases role 0.
- A same-world, same-device resize reuses unchanged active source allocations. A periphery-only change retains both fovea textures and gamma-hook owners. Immutable publication snapshots get a new set generation while preserving physical-allocation identity and shared leases. Failed/canceled builds never roll back a reused owner's hook.
- Admission/dispatch rejects stale world/device ownership. When no world is available on GT, publication and pending build admission are invalidated; leased resources still retire conservatively.
- While native targets initialize, an admitted four-logical-view main family renders only the context for engine/RHI progress. It cannot publish an atlas packet. The normal two-view engine bootstrap during closed admission is unchanged.
- Native-only presentation requires shared-context geometry, compact native layout and a real target-set generation. Both foveas keep the B15 per-eye camera/projection path.
- Depth captures track real D3D12 command-list Reset epochs. Execute submission bookkeeping and Reset are sequenced so a GPU-enqueued copy cannot be mistaken for discarded work. Failed fence signals quarantine resources.
- Pending depth recordings retain their command-list object. Successful Reset discards only unsubmitted recording references. No wall-clock abandonment or accumulating depth-resource graveyard is used.
- Completed/unleased obsolete-size depth slots are released; disabling depth releases safe completed allocations while preserving in-flight leases. Epoch bookkeeping is pruned without confusing reused object addresses.
- Approximate depth selection rejects a capture recorded before the selected color packet was created, and reports age from actual recording time. The existing jitter-aware reprojection remains functional.
- The original menu diagnostics child forwards wheel input to the original parent. A regression test sends a real ImGui IO wheel event to the pinned library.
- Automatic GPU snapshots/readback after 25 seconds are removed. The manual snapshot action remains.

## Important limitations

**Exact depth/color frame identity remains unresolved.** Size, submission and capture time do not authenticate an NGX evaluation to a particular UE scene/packet when work overlaps. B18 improves definite stale-capture rejection and recording lifetime; it does not claim exact per-frame provenance. The depth control/tooltip states that it is approximate. Missing acceptable depth uses the existing homography-only periphery rather than unrelated older cached depth. A speculative custom RHI marker without a proven family-end boundary was rejected during review.

**Arbitrary world-destruction cleanup remains unproven.** The new world/device gates reject stale dispatch. If an engine FRenderTarget has already disappeared or its vtable changed before safe restoration, conservative retirement still retains its owner rather than freeing a potentially referenced hook table. There is no claimed complete fix for that conditional teardown retention path.

No BSOD/crash cause was established from the supplied evidence. No crash-free, FPS, GPU-time or measured VRAM claim is made. Raw allocation work is reduced structurally; real results require the same-scene headset comparison. No new user-facing resolution cap is introduced; inherited physical dimension checks remain.

## Validation

New behavioral coverage includes canonical null-role delivery, partial native allocation/publication reuse, lease survival across canceled publications, 720 interleaved writes across publications sharing two foveas, context-only bootstrap restoration on exception, native-only publication, D3D12 recording epochs/discard/reuse, submission/Reset concurrency sequencing, stale capture-time rejection, and pinned-ImGui parent wheel routing.

The workflow applies B18 core, depth and resource overlays after the complete B15/B17 chain; validates final generated exports/parity; runs CPU and WARP compositor tests; runs portable ASan/UBSan tests; builds original production backend/auxiliary DLLs and frontend; verifies source checkpoints; and packages exact DLL/PDB identity. Passing a test of an identity helper alone is not proof that NGX has real scene identity.

## Short headset checklist

1. Inject/start ID7 directly. Confirm both stereo foveas and periphery, then recenter/standing height.
2. Check near hands and peripheral motion with depth on/off. Keep approximation artifacts separate from a black-eye failure.
3. Scroll while hovering diagnostics; save/restart and compare actual values.
4. Change only periphery resolution moderately. Log `reuse_mask=12` when only roles 2/3 are retained; verify new allocation estimate and retired queue state. Then test crop/density and a world load.
5. Compare B15/B18 in the same scene/settings. Log CPU/GPU time, game VRAM and actual resource identities. Stop on instability; preserve backend log, driver version and minidump/stop code.

Reproducibility: B15 pose/FOV/native-fix and UI contracts remain in the generated-source chain. No original DuoView baseline sources or restricted SDK files are modified.

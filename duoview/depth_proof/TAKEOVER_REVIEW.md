# Depth capture takeover review

## Confirmed

- The headset-tested #113 depth controls produced no depth image: the attached log reports an armed attempt, `copies=0`, and 54,129 matching-shape transition observations. Its `wrong_state` counter also includes subresource rejection, so that count does not establish which predicate failed.
- P1 observes D3D12 resource barriers through `D3D12Hook::resource_barrier` before the original barrier. It selects a candidate by pool/shape heuristics, allocates two snapshots of that selected shape, and accepts two events as a pair. That does not prove one snapshot is fovea and the other periphery, nor that either matches a color frame.
- The depth display and S0 preview require the GPU-ready gate. With zero copies, the user sees the normal Mono path rather than a visible depth failure.
- The #114 state-recovery revision broadens accepted pre-states and logs the first rejected tuple. Its CI run passed and produced artifacts, but no headset result or valid scene-depth image is established by that run.
- The independent cyan/pink EyeCheck reached distinct eye output in the headset. This confirms an eye-specific color route in that test, not depth access, view pairing, calibrated disparity, or stereo reconstruction.
- The protected stable reference is v186.1 Build49 at `60d0aae86949723d21266e4121a833f0191729c2`. Preserve it and retain a one-click Mono fallback.

## Hypotheses to test

- The old rejection may be caused by subresource selection, barrier kind, or the actual before/after state; the aggregate counter cannot distinguish them.
- A 1208×1064 resource may be an internal scene-depth surface, but dimensions and aspect ratio do not prove its UE pass or role.
- A global barrier callback may observe shadow, history, depth-pyramid, or transient RDG resources rather than the final scene depth used by a specific view.
- Inserting transitions and copies from the observer may be illegal or unsafe during an active render pass, on the wrong command list/queue, or before producer work is complete. The current evidence does not establish legal copy timing or queue-fence ownership.
- A candidate may be correct depth but stale, overwritten, or unrelated to the color and pose that the compositor later presents.

## Source audit of #114

The capture copies plane 0, but transitions `ALL_SUBRESOURCES` using the observed state of one incoming transition. For a two-plane depth/stencil texture, plane 1 can legally have a different state. Restoring all planes does not repair an invalid transition. The observer also does not reject split-barrier flags or establish whether a D3D12 render pass is active. These are confirmed omissions in source; no claim is made that they caused a particular headset failure.

P1's completion marker is signalled on the queue obtained through the later color-submit path, not on evidence that the command list recording the depth copy has executed there. Consequently the current source does not prove GPU completion of that copy. Its `GetCompletedValue() >= 1` check also accepts `UINT64_MAX`, which D3D12 uses for device removal. The new proof rejects that sentinel and maps a readback only after observing its exact list submission and fence retirement.

The replacement is a stable-based, independent diagnostic. It samples anonymous depth at a qualified write-to-read boundary, with per-plane transitions and explicit lifecycle rejects, and saves files. It does not solve UE producer provenance. WARP validation is required before offering the package, and real-game image inspection remains required after that.

Primary API references: [CopyTextureRegion](https://learn.microsoft.com/en-us/windows/win32/api/d3d12/nf-d3d12-id3d12graphicscommandlist-copytextureregion), [resource barriers and split barriers](https://learn.microsoft.com/en-us/windows/win32/direct3d12/using-resource-barriers-to-synchronize-resource-states-in-direct3d-12), [render-pass restrictions](https://learn.microsoft.com/en-us/windows/win32/direct3d12/direct3d-12-render-passes), [GetCompletedValue device removal](https://learn.microsoft.com/en-us/windows/win32/api/d3d12/nf-d3d12-id3d12fence-getcompletedvalue).

## Preferred next step

Instrument first and copy only after the exact producer, subresource, state, render-pass context, queue and completion point are known. Prefer a UE render-graph or explicit scene-view hook that identifies `FSceneView`, view rect, pass, frame and pose, and inserts a readback at a defined post-depth point. If that layer is inaccessible, use a read-only D3D12 survey first: collect a bounded histogram of resource identity, extent/format, plane/subresource, before/after states, command list, viewport/RTV/DSV bindings and render-pass context. Then choose a legal copy point and attach completion to the queue that executes it.

The first success criterion is one unmistakable offline image and manifest, not stereo. Keep roles unknown until producer metadata proves them; keep capture one-shot, bounded, and independent of normal Mono output.

## Later architecture choices

After a real depth image is verified and associated with a same-frame color view, compare calibrated center-to-eye reprojection with disocclusion handling against alternating-eye real renders with reprojection/AFW, fixed-eye reprojection, and hybrid temporal methods. DIBR is one option, not a requirement. Measure artifacts, comfort, GPU time and frame pacing on the target headset before choosing a path.

## Fallback if the legal boundary sampler yields no usable scene image

Do not loosen the copy predicates until a histogram explains why they reject. If the hook is missing Reset/queue interfaces, correct interception first. If snapshots are valid shadow/prepass resources, obtain semantic ownership rather than adding a larger size heuristic. Two focused options are an explicit UE scene-texture/RDG callback (requires exact engine interfaces) or the DLSS evaluation boundary: NVIDIA's NGX evaluation API receives a command list and parameter object containing input resources. A read-only parameter tap could identify the actual upscaler depth input and subrect per evaluation. This is a proposed research route, not implemented or proven compatible with the game's NGX/Streamline stack. It must establish the actual module/export ABI, resource states and queue ownership before copying.

Primary API basis: [NVIDIA NGX feature evaluation](https://docs.nvidia.com/ngx/programming-guide/index.html) and [NVIDIA parameter interface](https://github.com/NVIDIA/DLSS/blob/main/include/nvsdk_ngx_params.h).

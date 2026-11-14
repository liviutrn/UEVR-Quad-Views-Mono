# Builder B -> Claude: VectorXR #22 implementation handoff

Date: 2026-11-13. Status at authoring: GitHub Actions build started; **not yet verified in Windows CI or headset**. Review before installing.

## Source/identity

- Repo: `liviutrn/UEVR-Quad-Views-Mono`
- Base branch: `experiment/vectorxr-instrumentation21-20261113`
- Base commit: `7f15a464ac0fa17a5d766c96cfc0ad4727943336` (#36)
- Builder branch: `experiment/vectorxr-22-runtime-depth-20261113`
- GitHub Actions: [run #37](https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/43495217298).
- Pinned upstream: `DienerTech/vectorxr@8fffa72e99be8ab1e39457c7353faeb1218ac83f`.
- The CI-generated `evidence/vectorxr22-generated-cpp.patch` (inside evidence artifact and ZIP) is a no-index patch against the generated **#36** C++ tree. It is the requested evidence, not the full cumulative diff against upstream.

## Exact changes

1. Added `vectorxr_mono/apply_vectorxr_runtime_depth22.py` as a final fail-closed patcher, run after all #21 patches. Session switch `VECTORXR_FRAMEGEN_RUNTIME_DEPTH` is read by `ReadResearchSwitch` at presenter start. Unset/`1` preserve #36 behaviour. `0` logs `runtimeDepth=0` on the existing #21 line and forces outbound generated depth false.
2. `BuildFrame` clears `has_depth` only on its **temporary output FrameCopy**, including exact copies and all projection layers. Source depth capture and the backend's depth input remain unchanged.
3. Because startup/standby/inline paths can bypass `BuildFrame`, `FrameGenPresenter::RuntimeEnd` also sanitizes depth on all final presenter submissions when the switch is off. It creates local copies of projection layers and views; original app storage is untouched. Leading depth nodes are skipped; if a depth node is buried after unknown view-chain nodes, the opt-in mode drops that view's full chain rather than leave a depth pointer. This is the main new safety-critical code to review. Unset/`1` take the original branch without copying.
4. Kind-7 corrections: paths 6/8 report the last shown tuple's fraction when available (aux fraction-valid bit unchanged); exact extrapolation reports 0 instead of 1e6. All other fields unchanged.
5. #18 fixture adds diagnostics per off-timeline miss: submitted image class plus *end-of-test snapshots* of lead, cap, ring ceiling and GPU capture/analysis totals. No thresholds changed. These snapshots are explicitly not frame-specific measurements.
6. Fake-runtime test `TestRuntimeDepth22Off`: inspect **every** projection eye and layer on the actual submitted `XrFrameEndInfo`, verify no depth for real copies/generated frames in both legacy and JIT compositors, and verify FG still captures depth.
7. Added `vectorxr_mono/test-presets22/RD0.txt`, A-baseline + `VECTORXR_FRAMEGEN_RUNTIME_DEPTH=0`. Packaging includes RD0 and the generated C++ diff. Workflow branch trigger is scoped to #22.

## Review attention / risks

- Inspect output-chain stripping in `FrameGenPresenter::RuntimeEnd` for lifetime, chain semantics and any missing submission bypass. `std::deque` retains projection/view-array addresses through append until the synchronous runtime call returns; no pointer into a temporary is retained.
- Validate that `ReadResearchSwitch` precedence (environment vs research file) matches #21. This switch is session-scoped, not a mid-game toggle.
- Check fake-runtime coverage for both generated and copy frames and internal depth capture. If the selected fake GPU backend produces no genuine generated output in the 1.4 s JIT test, extend its fixture; do not weaken the assertions.
- The `TestRuntimeDepth22Off` test is currently designed for the FrameGenPresenter pipeline. When VectorXR Frame Generation is completely bypassed upstream in OpenXrLayer, this setting is not an unconditional global runtime-depth blocker. Confirm that the requested experiment is intentionally FG-only; if absolute coverage is required, use the OpenXrLayer's depth filtering path with a session-latched switch.
- #21 per-refresh trace schema/bit semantics are unchanged; prior-fraction values on paths 6/8 must not be mistaken for new synthesis (aux bit13 stays zero).
- Full Windows CI and actual SteamVR A/B results are required; no visual improvement claim.

## CI expected

- Apply all #36 patchers, then the new #22 patcher.
- Build Release Windows DLL.
- Run presenter fixture `TestRuntimeDepth22Off`, `TestJitBuild18WarmupFixture`, other targeted tests and full CTest suite.
- Upload `VectorXR-Mono-Evidence-37` containing `vectorxr22-generated-cpp.patch`.
- Upload `VectorXR-0.20.1-RuntimeDepth22-37` containing ZIP with DLL + source + presets. **Do not install until Claude has reviewed the diff.**

## Cheeky

Untouched. As requested, move repo + hook-unload safety + C2 source-role consumer only **after Liviu's pending captures**. No additional #21 controller, mono gate or depth validation modifications.

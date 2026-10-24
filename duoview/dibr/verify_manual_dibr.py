#!/usr/bin/env python3
"""Run the unchanged stable verifier plus exact manual-DIBR integration guards."""
import importlib.util
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STABLE = ROOT / "joey_stage1" / "verify_stage234.py"
spec = importlib.util.spec_from_file_location("duoview_stable_verifier", STABLE)
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load the unchanged stable release verifier")
stable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stable)

# Keep every original stable semantic check. Extend its exact backend path sets
# only for files installed or edited by this reviewed feature patch.
stable.EDITED_BACKEND |= {
    "src/hooks/D3D12Hook.cpp",
    "src/hooks/D3D12Hook.hpp",
}
stable.ADDED_BACKEND |= {
    "src/mods/vr/dibr/ManualDibrContract.hpp",
    "src/mods/vr/dibr/DuoViewDibrD3D12.hpp",
    "src/mods/vr/d3d12/ManualDibrCapture.hpp",
    "src/mods/vr/dibr/ManualDibrPreview.hpp",
    "src/mods/vr/dibr/ManualDibrProjection.hpp",
    "src/mods/vr/dibr/ManualDibrUi.hpp",
}


def require_tokens(source: str, tokens: tuple[str, ...], description: str) -> None:
    for token in tokens:
        if token not in source:
            raise RuntimeError(f"{description} is missing required integration token: {token}")


def required_region(source: str, start: str, end: str, description: str) -> str:
    start_at = source.find(start)
    if start_at < 0 or source.find(start, start_at + len(start)) >= 0:
        raise RuntimeError(f"Could not identify one exact {description} scope")
    end_at = source.find(end, start_at + len(start))
    if end_at < 0:
        raise RuntimeError(f"Could not find the end of {description} scope")
    return source[start_at:end_at]


def require_ordered(source: str, tokens: tuple[str, ...], description: str) -> None:
    positions = []
    for token in tokens:
        at = source.find(token)
        if at < 0:
            raise RuntimeError(f"{description} is missing required callsite: {token}")
        positions.append(at)
    if positions != sorted(positions):
        raise RuntimeError(f"{description} callsites are not in the required order: {tokens}")


def verify_feature(backend: Path) -> None:
    contract = (backend / "src/mods/vr/dibr/ManualDibrContract.hpp").read_text(encoding="utf-8")
    capture = (backend / "src/mods/vr/d3d12/ManualDibrCapture.hpp").read_text(encoding="utf-8")
    compositor = (backend / "src/mods/vr/dibr/DuoViewDibrD3D12.hpp").read_text(encoding="utf-8")
    mono_compositor = (backend / "src/mods/vr/DuoViewD3D12.hpp").read_text(encoding="utf-8")
    component = (backend / "src/mods/vr/D3D12Component.cpp").read_text(encoding="utf-8")
    component_header = (backend / "src/mods/vr/D3D12Component.hpp").read_text(encoding="utf-8")
    hook = (backend / "src/hooks/D3D12Hook.cpp").read_text(encoding="utf-8")
    render_hook = (backend / "src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
    ui = (backend / "src/mods/VR.cpp").read_text(encoding="utf-8")
    shaders = (backend / "src/mods/vr/DuoViewShaderSource.hpp").read_text(encoding="utf-8")

    for source_relative, installed_relative in (
        ("dibr/ManualDibrContract.hpp", "dibr/ManualDibrContract.hpp"),
        ("dibr/DuoViewDibrD3D12.hpp", "dibr/DuoViewDibrD3D12.hpp"),
        ("dibr/ManualDibrPreview.hpp", "dibr/ManualDibrPreview.hpp"),
        ("dibr/ManualDibrProjection.hpp", "dibr/ManualDibrProjection.hpp"),
        ("dibr/ManualDibrUi.hpp", "dibr/ManualDibrUi.hpp"),
        ("dibr/ManualDibrCapture.hpp", "d3d12/ManualDibrCapture.hpp"),
    ):
        source_header = (ROOT / source_relative).read_bytes()
        installed_header = (backend / "src/mods/vr" / installed_relative).read_bytes()
        if installed_header != source_header:
            raise RuntimeError(f"Installed backend header differs from reviewed source: {source_relative}")
    if "UEVR-backend-pinned-clean" in capture:
        raise RuntimeError("DIBR capture must not include a local clone path in the Windows build")

    require_tokens(contract, (
        "ProducerKey", "CandidateKey", "RoleAssignments", "validate_selected_sample",
        "QueueRelation::same_queue", "QueueRelation::cross_queue", "SnapshotRing",
        "CopyReceipt", "origin_subresource", "owned_subresource", "validate_owned_sample",
    ), "Manual DIBR frame contract")
    require_tokens(capture, (
        "D3D12_RESOURCE_STATE_DEPTH_WRITE",
        "D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE", "resource_generation",
        "active_rect", "CaptureStage", "queue",
    ), "Manual DIBR producer capture")
    require_tokens(compositor, (
        "validate_selected_sample", "ConsumerReceipt", "D3D12_RESOURCE_STATE_RENDER_TARGET",
        "DrawInstanced(3, 1, 0, 0)", "retire_after_fence", "range.NumDescriptors = 3",
        "const OwnedDepthTexture* fovea", "projection.use_fovea_depth",
        "validate_owned_sample", "fovea_reference_",
    ), "Manual DIBR production adapter")
    if "ID3D12Resource* mono_output() const" not in mono_compositor:
        raise RuntimeError("DIBR adapter cannot read the fenced center-color compositor output")
    require_tokens(component_header, (
        "D3D12DepthStencilObserver", "manual_dibr_compositors", "manual_dibr_capture",
        "on_depth_stencil_view_created", "on_resource_barriers",
        "on_command_list_reset", "on_execute_command_lists",
    ), "Manual DIBR producer capture and submission state")
    require_tokens(hook, (
        "manual_dibr_reset(", "manual_dibr_close(", "manual_dibr_execute(",
        "on_command_list_reset(", "on_command_list_close(", "on_execute_command_lists(",
        "m_depth_stencil_observer",
    ), "Manual DIBR real D3D12 lifetime hooks")

    # Exact live OpenXR rendering callsite: in Joey this is the pre_commands
    # callback passed to OpenXR::copy() by D3D12Component::on_frame(), not in
    # the body of the generic copy helper. Require the same callback to own
    # Mono composition, current-frame depth, eye matrices and DIBR recording.
    scene_path = required_region(
        component,
        "vr::EVRCompositorError D3D12Component::on_frame(VR* vr)",
        "void D3D12Component::on_reset(",
        "DuoView XR recording path",
    )
    require_ordered(scene_path, (
        "compositor.record_native(",
        "manual_dibr_compositor.record(",
        "if (manual_dibr_compositor.recorded_commands())",
    ), "OpenXR producer color then depth-consumer then submission-flag order")
    require_tokens(scene_path, (
        "manual_dibr_capture", "mono_output()", "selected_periphery(",
        "build_native_eye_target_from_source(", "build_manual_dibr_clip_transform(",
        "D3D12_RESOURCE_STATE_RENDER_TARGET", "commands.has_commands=true",
        "m_openxr.copy(",
    ), "Live opt-in DIBR output route")
    require_tokens(component, ("manual_dibr_compositor.prewarm(",),
                   "DIBR swapchain/configuration prewarm")
    require_tokens(render_hook, (
        "capture_source_stamps.begin_direct(", "capture_source_stamp_from_command(",
        "duo_source", "view_family",
    ), "Immutable direct RHI producer identity")
    manual_ui = (backend / "src/mods/vr/dibr/ManualDibrUi.hpp").read_text(encoding="utf-8")
    require_tokens(manual_ui, (
        "Enable DuoView Stereo", "Full view / Periphery depth", "Fovea depth",
        "Choose full-view depth", "Selected; timing unverified",
    ), "Manual DIBR depth selection UI")
    require_tokens(ui, ("ManualDibrUi.hpp", "m_duo_dibr_stereo", "manual_dibr_capture",
        "ui::draw(", "Mono fallback", "Waiting",
    ), "Connected opt-in DIBR UI and fallback status")
    require_tokens(shaders, ("dibr_vertex_shader_bytecode[]", "dibr_pixel_shader_bytecode[]"),
                   "Precompiled DIBR shaders")
    if "D3DCompile(" in compositor:
        raise RuntimeError("Runtime shader compilation is forbidden in the DIBR output callback")


def verify_warp_test() -> None:
    warp = (ROOT / "dibr" / "manual_dibr_warp_test.cpp").read_text(encoding="utf-8")
    require_tokens(warp, (
        "EnumWarpAdapter", "D3D12CreateDevice", "Compositor compositor",
        "compositor.record(", "CopyTextureRegion(&output_readback", "readback->Map",
        "constexpr UINT DW = 40, DH = 24", "constexpr Rect DepthRect{6, 5, 24, 12}",
        "constexpr Rect ColorRect{4, 2, 56, 28}", "depth_array_desc.DepthOrArraySize = 2",
        "depth_array_locations[1]", "zero_baseline", "convergence",
        "padded_rect_near", "reversed_z_far", "reversed_z_near",
        "near_disparity >", "far_disparity <", "require_identical_eyes", "clear_image",
        "projections.use_fovea_depth = true", "projections.fovea_uv_rect =",
        "fovea_disparity", "periphery_left_disparity", "periphery_right_disparity",
        "infinite_reverse_z_source_to_eye", "asymmetric_sky_disparity",
        "Clear reversed-Z sky must retain", "DXGI_FORMAT_B8G8R8A8_TYPELESS",
        "DXGI_FORMAT_B8G8R8A8_UNORM_SRGB", "center_color_srgb = true",
        "require_pixel_near",
    ), "Production DX12 WARP geometry test")
    if "DuoViewDibrD3D12.hpp" not in warp:
        raise RuntimeError("WARP test does not instantiate the production DIBR adapter")


def verify_feature_source_hashes(evidence: Path, final: bool) -> None:
    files = (
        ROOT.parent / "DIBR_RELEASE_BASE.json",
        ROOT.parent / "scripts" / "verify_dibr_release_base.py",
        ROOT / "CMakeLists.txt",
        ROOT / "embed_shader.py",
        ROOT / "DuoViewComposite.hlsl",
        ROOT / "DuoViewCompositeRaster.hlsl",
        ROOT / "DuoViewNativeCompositeRaster.hlsl",
        ROOT / "DuoViewGlamaryeFovea.hlsl",
        ROOT / "production_warp_test.cpp",
        ROOT / "dibr" / "DuoViewDibrRaster.hlsl",
        ROOT / "dibr" / "ManualDibrCapture.hpp",
        ROOT / "dibr" / "ManualDibrContract.hpp",
        ROOT / "dibr" / "DuoViewDibrD3D12.hpp",
        ROOT / "dibr" / "manual_dibr_tests.cpp",
        ROOT / "dibr" / "manual_dibr_warp_test.cpp",
        ROOT / "dibr" / "verify_manual_dibr.py",
        ROOT / "joey_stage1" / "apply_manual_dibr.py",
    )
    hashes = {}
    for path in files:
        if not path.is_file():
            raise RuntimeError(f"Missing manual-DIBR build input: {path}")
        hashes[path.relative_to(ROOT.parent).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    lock = evidence / "manual-dibr-source-hashes.json"
    if final:
        if not lock.is_file() or json.loads(lock.read_text(encoding="utf-8")) != hashes:
            raise RuntimeError("Manual DIBR build inputs changed after acceptance verification")
    else:
        evidence.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit("usage: verify_manual_dibr.py BACKEND FRONTEND EVIDENCE [--final]")
    backend = Path(sys.argv[1])
    evidence = Path(sys.argv[3])
    final = "--final" in sys.argv[4:]
    # stable.main parses the same backend/frontend/evidence arguments and keeps
    # every original exact-path, SDK, semantic, and final-hash check active.
    stable.main()
    verify_feature(backend)
    verify_warp_test()
    verify_feature_source_hashes(evidence, final)
    print("Manual DIBR production callsites and real WARP geometry route: PASS")


if __name__ == "__main__":
    main()

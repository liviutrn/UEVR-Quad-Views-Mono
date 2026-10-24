#!/usr/bin/env python3
"""Install reviewed manual DIBR units into the exact pinned Joey backend.

This is an intentionally fail-closed production integration stage.  It never
relaxes the existing stable source verifier, builds generated shaders offline,
and only installs source that belongs to the approved feature branch.
The subsequent verifier must still prove *live callsites* before packaging.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    original = path.read_text(encoding="utf-8-sig")
    occurrences = original.count(old)
    if occurrences != 1:
        raise RuntimeError(f"{label}: expected one source anchor, found {occurrences}")
    path.write_text(original.replace(old, new, 1), encoding="utf-8", newline="")


def install_file(original: Path, dest: Path) -> None:
    if not original.is_file():
        raise RuntimeError(f"Reviewed DIBR source missing: {original}")
    if dest.exists():
        raise RuntimeError(f"Refusing to overwrite existing backend source: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(original, dest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", type=Path)
    parser.add_argument("frontend", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()

    source = args.source
    backend = args.backend
    if not (backend / "src/mods/vr/DuoViewD3D12.hpp").is_file():
        raise RuntimeError("Accepted Stage 2-4 DuoView producer must be patched first")
    stable_mono = (backend / "src/mods/vr/DuoViewD3D12.hpp").read_text(encoding="utf-8")
    if "ID3D12Resource* mono_output() const" not in stable_mono:
        raise RuntimeError("DIBR requires a properly owned and fenced Mono source")
    if not (source / "dibr/manual_dibr_warp_test.cpp").is_file():
        raise RuntimeError("Required production DX12 WARP source missing")

    # The WARP acceptance job compiles these same exact headers. We install
    # them without rewriting their content so the final verifier can compare
    # their bytes, and source-level regressions remain detectable.
    modules = {
        "dibr/ManualDibrContract.hpp": "dibr/ManualDibrContract.hpp",
        "dibr/ManualDibrPreview.hpp": "dibr/ManualDibrPreview.hpp",
        "dibr/ManualDibrProjection.hpp": "dibr/ManualDibrProjection.hpp",
        "dibr/ManualDibrUi.hpp": "dibr/ManualDibrUi.hpp",
        "dibr/DuoViewDibrD3D12.hpp": "dibr/DuoViewDibrD3D12.hpp",
        "dibr/ManualDibrCapture.hpp": "d3d12/ManualDibrCapture.hpp",
    }
    installed = []
    for relative_src, relative_backend in modules.items():
        dest = backend / "src/mods/vr" / relative_backend
        install_file(source / relative_src, dest)
        installed.append(str(dest.relative_to(backend)))

    # Compile and embed the production DIBR shaders on the Windows CI runner.
    # This is *not* a runtime D3DCompile call.
    embed = source / "embed_shader.py"
    target = backend / "src/mods/vr/DuoViewShaderSource.hpp"
    subprocess.run([sys.executable, str(embed), str(target), "--include-dibr"],
                   check=True)
    shaders = target.read_text(encoding="utf-8")
    if "dibr_vertex_shader_bytecode[]" not in shaders or \
       "dibr_pixel_shader_bytecode[]" not in shaders:
        raise RuntimeError("DIBR bytecode absent after offline HLSL compilation")

    # Integrate the native units into the exact accepted DX12 backend without
    # modifying original Joey modes 0 and 5. Every edit requires one anchor.
    backend_vr = backend / "src/mods/VR.hpp"
    backend_ui = backend / "src/mods/VR.cpp"
    dx12_header = backend / "src/mods/vr/D3D12Component.hpp"

    replace_exact(dx12_header,
        '#include "DuoViewD3D12.hpp"',
        '#include "DuoViewD3D12.hpp"\n'
        '#include "dibr/DuoViewDibrD3D12.hpp"\n'
        '#include "d3d12/ManualDibrCapture.hpp"',
        "DIBR DX12 header imports")
    replace_exact(dx12_header,
        '        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;',
        '        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;\n'
        '        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dibr::dx12::Compositor>> manual_dibr_compositors;\n'
        '        uevr::duoview::dibr::dx12::ManualDibrCapture manual_dibr_capture{};',
        "Own DIBR texture ring per fenced XR command slot")

    replace_exact(backend_vr,
        '    bool is_duoview_renderer_active() const;',
        '    bool is_duoview_renderer_active() const;\n'
        '    bool manual_dibr_stereo_requested() const { return is_duoview_renderer_active() && m_duo_dibr_stereo->value(); }\n'
        '    bool manual_dibr_picker_open() const { return m_duo_dibr_picker_open.load(std::memory_order_acquire); }',
        "DuoView-only DIBR opt-in")
    replace_exact(backend_vr,
        '    const ModToggle::Ptr m_duo_gaze{ModToggle::create(generate_name("DuoViewEyeTracking"), true)};',
        '    const ModToggle::Ptr m_duo_gaze{ModToggle::create(generate_name("DuoViewEyeTracking"), true)};\n'
        '    const ModToggle::Ptr m_duo_dibr_stereo{ModToggle::create(generate_name("DuoViewManualDibrStereo"), false)};\n'
        '    std::atomic<bool> m_duo_dibr_picker_open{false};',
        "DIBR controls default OFF")
    replace_exact(backend_vr,
        '*m_duo_feather, *m_duo_sharpen, *m_duo_gaze, *m_duo_border,',
        '*m_duo_feather, *m_duo_sharpen, *m_duo_gaze, *m_duo_dibr_stereo, *m_duo_border,',
        "Persistent opt-in DIBR control")

    replace_exact(backend_ui,
        '#include "VR.hpp"',
        '#include "VR.hpp"\n#include "vr/dibr/ManualDibrUi.hpp"',
        "Manual DIBR ImGui module")
    replace_exact(backend_ui,
        '                m_duo_gaze->draw("Eye tracking");',
        '''                m_duo_gaze->draw("Eye tracking");
                if (ImGui::TreeNode("DuoView Stereo - manual depth (experimental)")) {
                    auto& capture = m_d3d12.openxr().manual_dibr_capture;
                    capture.poll_completed_previews();
                    uevr::duoview::dibr::ui::Frame frame{};
                    frame.picker_open = m_duo_dibr_picker_open.load(std::memory_order_acquire);
                    frame.stereo_enabled = manual_dibr_stereo_requested();
                    frame.assignments = capture.assignments();
                    frame.first_candidate = capture.preview_page();
                    frame.candidates_complete = capture.candidates_complete();
                    frame.output_status = frame.stereo_enabled
                        ? "Mono fallback - waiting for current RGB-D packet and production stereo submission"
                        : "Mono fallback - Stereo disabled";
                    for (auto& candidate : capture.candidates()) {
                        frame.candidates.push_back({candidate.candidate, candidate.preview,
                            candidate.preview_status, candidate.age_ms, candidate.status});
                    }
                    uevr::duoview::dibr::ui::Actions actions{};
                    actions.set_stereo_enabled = [this](bool on) {
                        m_duo_dibr_stereo->value() = on;
                        m_d3d12.force_reset();
                    };
                    actions.set_picker_open = [this](bool open) {
                        m_duo_dibr_picker_open.store(open, std::memory_order_release);
                    };
                    actions.set_first_candidate = [&capture](size_t first) {
                        capture.set_preview_page(first);
                    };
                    actions.assign_periphery = [&capture](uevr::duoview::dibr::CandidateKey key) {
                        return capture.assign_periphery(key);
                    };
                    actions.assign_fovea = [&capture](uevr::duoview::dibr::CandidateKey key) {
                        return capture.assign_fovea(key);
                    };
                    actions.clear_periphery = [&capture]() { capture.clear_periphery(); };
                    actions.clear_fovea = [&capture]() { capture.clear_fovea(); };
                    static uevr::duoview::dibr::ui::State picker_state{};
                    uevr::duoview::dibr::ui::draw(frame, picker_state, actions);
                    capture.set_requested(frame.picker_open, frame.stereo_enabled);
                    ImGui::TreePop();
                }''',
        "Manual DIBR picker & explicit truthful Mono fallback UI")

    # Attach a small opt-in D3D12 observation adapter. The underlying stable
    # DX12 hook already reports DSV creation and resource barriers. A command
    # is eligible for copying only with proven epoch/frame ownership; never
    # invent a current frame when the hook did not see one.
    replace_exact(dx12_header,
        '#include "d3d12/ManualDibrCapture.hpp"',
        '#include "d3d12/ManualDibrCapture.hpp"\n'
        '#include "../../hooks/D3D12Hook.hpp"',
        "DIBR observer type")
    replace_exact(dx12_header,
        '        uevr::duoview::dibr::dx12::ManualDibrCapture manual_dibr_capture{};',
        '''        uevr::duoview::dibr::dx12::ManualDibrCapture manual_dibr_capture{};
        struct ManualDibrHookObserver final : D3D12DepthStencilObserver {
            uevr::duoview::dibr::dx12::ManualDibrCapture* capture{};
            void on_depth_stencil_view_created(
                ID3D12Resource* resource, const D3D12_DEPTH_STENCIL_VIEW_DESC* desc,
                D3D12_CPU_DESCRIPTOR_HANDLE handle) override {
                if (capture && capture->requested())
                    capture->on_depth_stencil_view_created(resource, desc, handle);
            }
            void on_resource_barriers(
                ID3D12GraphicsCommandList* list, UINT count,
                const D3D12_RESOURCE_BARRIER* barriers) override {
                if (!capture || !capture->requested() || !list) return;
                const auto stamp = uevr::duoview::capture_source_stamps.current(GetCurrentThreadId());
                const auto epoch = uevr::duoview::command_list_epochs.current(
                    reinterpret_cast<uintptr_t>(list));
                capture->on_resource_barriers_scoped(list, count, barriers, stamp, epoch);
            }
        } manual_dibr_observer{};
        // The observer is owned by the OpenXR backend, not by the game resource.
        // DIBR remains disabled unless the picker or stereo is explicitly selected.''',
        "Bounded DIBR depth-stencil observer")

    dx12_cpp = backend / "src/mods/vr/D3D12Component.cpp"
    replace_exact(dx12_cpp,
        'vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {\n',
        '''vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
    // No DIBR hook work in any other original Joey mode. The stable
    // Mono/DuoView render path remains bit-for-bit the same while off.
    const bool dibr_picker = vr->manual_dibr_picker_open();
    const bool dibr_stereo = vr->manual_dibr_stereo_requested();
    m_openxr.manual_dibr_capture.set_requested(dibr_picker, dibr_stereo);
    m_openxr.manual_dibr_observer.capture = &m_openxr.manual_dibr_capture;
    if (auto* hook = g_framework->get_d3d12_hook(); hook)
        hook->set_depth_stencil_observer(
            (dibr_picker || dibr_stereo) && vr->get_runtime()->is_openxr()
                ? &m_openxr.manual_dibr_observer : nullptr);
''',
        "Opt-in DSV/ResourceBarrier capture registration")
    # Only the already accepted DuoView paths are installed here. The separate
    # production callsites / GPU fence hooks are still mandatory and are
    # rejected by verify_manual_dibr.py until actually implemented.
    (args.evidence / "manual_dibr_modules_installed.txt").write_text(
        "\n".join(installed) + "\n", encoding="utf-8"
    )
    print("Manual DIBR shader and reviewed sources installed. Production integration verification remains mandatory.")


if __name__ == "__main__":
    main()

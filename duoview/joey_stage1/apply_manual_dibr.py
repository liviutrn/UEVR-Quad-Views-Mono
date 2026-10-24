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
    # D3D12 transaction hooks establish actual command-list lifetimes and queue
    # execution, not guessed chronology from UI or frame-count polling.
    d3d_hook_h = backend / "src/hooks/D3D12Hook.hpp"
    d3d_hook_cpp = backend / "src/hooks/D3D12Hook.cpp"
    replace_exact(d3d_hook_h,
        '''        const D3D12_RESOURCE_BARRIER* barriers) = 0;
};''',
        '''        const D3D12_RESOURCE_BARRIER* barriers) = 0;
    virtual void on_command_list_reset(ID3D12GraphicsCommandList*) {}
    virtual void on_command_list_close(ID3D12GraphicsCommandList*, bool) {}
    virtual void on_execute_command_lists(
        ID3D12CommandQueue*, UINT, ID3D12CommandList* const*) {}
};''',
        "Observer real GPU command lifetimes")
    replace_exact(d3d_hook_h,
        '    std::vector<std::unique_ptr<PointerHook>> m_resource_barrier_hooks{};',
        '''    std::vector<std::unique_ptr<PointerHook>> m_resource_barrier_hooks{};
    std::vector<std::unique_ptr<PointerHook>> m_dibr_reset_hooks{};
    std::vector<std::unique_ptr<PointerHook>> m_dibr_close_hooks{};
    std::vector<std::unique_ptr<PointerHook>> m_dibr_execute_hooks{};''',
        "Command lifecycle hook owners")
    replace_exact(d3d_hook_h,
        '    std::unordered_map<uintptr_t, PointerHook*> m_resource_barrier_hook_lookup{};',
        '''    std::unordered_map<uintptr_t, PointerHook*> m_resource_barrier_hook_lookup{};
    std::unordered_map<uintptr_t, PointerHook*> m_dibr_reset_lookup{};
    std::unordered_map<uintptr_t, PointerHook*> m_dibr_close_lookup{};
    std::unordered_map<uintptr_t, PointerHook*> m_dibr_execute_lookup{};''',
        "Command lifecycle hook lookup")
    replace_exact(d3d_hook_h,
        '    static void WINAPI resource_barrier(ID3D12GraphicsCommandList* command_list, UINT count, const D3D12_RESOURCE_BARRIER* barriers);',
        '''    static void WINAPI resource_barrier(ID3D12GraphicsCommandList* command_list, UINT count, const D3D12_RESOURCE_BARRIER* barriers);
    static HRESULT WINAPI manual_dibr_reset(ID3D12GraphicsCommandList* list, ID3D12CommandAllocator* allocator, ID3D12PipelineState* initial_state);
    static HRESULT WINAPI manual_dibr_close(ID3D12GraphicsCommandList* list);
    static void WINAPI manual_dibr_execute(ID3D12CommandQueue* queue, UINT count, ID3D12CommandList* const* lists);''',
        "DIBR hook thunk declarations")
    replace_exact(d3d_hook_h,
        '    PointerHook* find_resource_barrier_hook(void* slot) const;',
        '''    PointerHook* find_resource_barrier_hook(void* slot) const;
    PointerHook* find_manual_dibr_reset_hook(void* slot) const;
    PointerHook* find_manual_dibr_close_hook(void* slot) const;
    PointerHook* find_manual_dibr_execute_hook(void* slot) const;''',
        "Hook lookup declarations")

    replace_exact(d3d_hook_cpp,
        'constexpr size_t RESOURCE_BARRIER_VTABLE_INDEX = 26;',
        '''constexpr size_t RESOURCE_BARRIER_VTABLE_INDEX = 26;
constexpr size_t DIBR_CMD_CLOSE_VTABLE_INDEX = 9;  // ID3D12GraphicsCommandList::Close
constexpr size_t DIBR_CMD_RESET_VTABLE_INDEX = 10; // ID3D12GraphicsCommandList::Reset
constexpr size_t DIBR_QUEUE_EXEC_VTABLE_INDEX = 10;// ID3D12CommandQueue::ExecuteCommandLists''',
        "Pinned DX12 COM vtable indices")
    replace_exact(d3d_hook_cpp,
        '        std::unordered_set<uintptr_t> resource_barrier_slots{};',
        '''        std::unordered_set<uintptr_t> resource_barrier_slots{};
        std::unordered_set<uintptr_t> dibr_reset_slots{}, dibr_close_slots{}, dibr_execute_slots{};
        add_unique_pointer_hook(
            command_queue, DIBR_QUEUE_EXEC_VTABLE_INDEX,
            reinterpret_cast<void*>(&D3D12Hook::manual_dibr_execute),
            m_dibr_execute_hooks, m_dibr_execute_lookup, dibr_execute_slots);''',
        "Install D3D12 queue execution hook")
    replace_exact(d3d_hook_cpp,
        '''        add_unique_pointer_hook(
            command_list,
            RESOURCE_BARRIER_VTABLE_INDEX,
            reinterpret_cast<void*>(&D3D12Hook::resource_barrier),
            m_resource_barrier_hooks,
            m_resource_barrier_hook_lookup,
            resource_barrier_slots
        );''',
        '''        add_unique_pointer_hook(
            command_list,
            RESOURCE_BARRIER_VTABLE_INDEX,
            reinterpret_cast<void*>(&D3D12Hook::resource_barrier),
            m_resource_barrier_hooks,
            m_resource_barrier_hook_lookup,
            resource_barrier_slots
        );
        add_unique_pointer_hook(
            command_list, DIBR_CMD_RESET_VTABLE_INDEX,
            reinterpret_cast<void*>(&D3D12Hook::manual_dibr_reset),
            m_dibr_reset_hooks, m_dibr_reset_lookup, dibr_reset_slots);
        add_unique_pointer_hook(
            command_list, DIBR_CMD_CLOSE_VTABLE_INDEX,
            reinterpret_cast<void*>(&D3D12Hook::manual_dibr_close),
            m_dibr_close_hooks, m_dibr_close_lookup, dibr_close_slots);''',
        "Install list Reset / Close hooks")
    replace_exact(d3d_hook_cpp,
        '''                m_resource_barrier_hook_lookup,
                resource_barrier_slots
            );
        }

        m_hooked = true;''',
        '''                m_resource_barrier_hook_lookup,
                resource_barrier_slots
            );
            add_unique_pointer_hook(
                iface, DIBR_CMD_RESET_VTABLE_INDEX,
                reinterpret_cast<void*>(&D3D12Hook::manual_dibr_reset),
                m_dibr_reset_hooks, m_dibr_reset_lookup, dibr_reset_slots);
            add_unique_pointer_hook(
                iface, DIBR_CMD_CLOSE_VTABLE_INDEX,
                reinterpret_cast<void*>(&D3D12Hook::manual_dibr_close),
                m_dibr_close_hooks, m_dibr_close_lookup, dibr_close_slots);
        }

        m_hooked = true;''',
        "Track all supported command-list COM versions")
    replace_exact(d3d_hook_cpp,
        '''    m_resource_barrier_hooks.clear();
    m_create_graphics_pipeline_state_hook_lookup.clear();''',
        '''    m_resource_barrier_hooks.clear();
    m_dibr_reset_hooks.clear();
    m_dibr_close_hooks.clear();
    m_dibr_execute_hooks.clear();
    m_dibr_reset_lookup.clear();
    m_dibr_close_lookup.clear();
    m_dibr_execute_lookup.clear();
    m_create_graphics_pipeline_state_hook_lookup.clear();''',
        "Unhook DIBR command-list/queue observation")

    # Resolve each original thunk from its vtable slot, exactly as the stable
    # pipeline-state and ResourceBarrier hooks do. Disabled path is one atomic
    # observer check; original Reset/Close/Execute behavior is never replaced.
    replace_exact(d3d_hook_cpp,
        '''thread_local int32_t g_resize_buffers_depth = 0;''',
        '''PointerHook* D3D12Hook::find_manual_dibr_reset_hook(void* slot) const {
    auto it=m_dibr_reset_lookup.find(reinterpret_cast<uintptr_t>(slot));
    return it!=m_dibr_reset_lookup.end() ? it->second : nullptr;
}
PointerHook* D3D12Hook::find_manual_dibr_close_hook(void* slot) const {
    auto it=m_dibr_close_lookup.find(reinterpret_cast<uintptr_t>(slot));
    return it!=m_dibr_close_lookup.end() ? it->second : nullptr;
}
PointerHook* D3D12Hook::find_manual_dibr_execute_hook(void* slot) const {
    auto it=m_dibr_execute_lookup.find(reinterpret_cast<uintptr_t>(slot));
    return it!=m_dibr_execute_lookup.end() ? it->second : nullptr;
}

HRESULT WINAPI D3D12Hook::manual_dibr_reset(
    ID3D12GraphicsCommandList* list, ID3D12CommandAllocator* allocator,
    ID3D12PipelineState* initial_state) {
    auto* hook=g_d3d12_hook;
    auto* slot=list ? &(*(void***)list)[DIBR_CMD_RESET_VTABLE_INDEX] : nullptr;
    auto* entry=hook ? hook->find_manual_dibr_reset_hook(slot) : nullptr;
    auto* original=entry ? entry->get_original<decltype(D3D12Hook::manual_dibr_reset)*>() : nullptr;
    if (!original) return E_FAIL;
    HRESULT result=original(list,allocator,initial_state);
    if (SUCCEEDED(result) && hook) {
        if (auto* obs=hook->m_depth_stencil_observer.load(std::memory_order_acquire))
            obs->on_command_list_reset(list);
    }
    return result;
}
HRESULT WINAPI D3D12Hook::manual_dibr_close(ID3D12GraphicsCommandList* list) {
    auto* hook=g_d3d12_hook;
    auto* slot=list ? &(*(void***)list)[DIBR_CMD_CLOSE_VTABLE_INDEX] : nullptr;
    auto* entry=hook ? hook->find_manual_dibr_close_hook(slot) : nullptr;
    auto* original=entry ? entry->get_original<decltype(D3D12Hook::manual_dibr_close)*>() : nullptr;
    if (!original) return E_FAIL;
    HRESULT result=original(list);
    if (hook) {
        if (auto* obs=hook->m_depth_stencil_observer.load(std::memory_order_acquire))
            obs->on_command_list_close(list,SUCCEEDED(result));
    }
    return result;
}
void WINAPI D3D12Hook::manual_dibr_execute(
    ID3D12CommandQueue* queue, UINT count, ID3D12CommandList* const* lists) {
    auto* hook=g_d3d12_hook;
    auto* slot=queue ? &(*(void***)queue)[DIBR_QUEUE_EXEC_VTABLE_INDEX] : nullptr;
    auto* entry=hook ? hook->find_manual_dibr_execute_hook(slot) : nullptr;
    auto* original=entry ? entry->get_original<decltype(D3D12Hook::manual_dibr_execute)*>() : nullptr;
    if (!original) return;
    original(queue,count,lists);
    if (hook) {
        if (auto* obs=hook->m_depth_stencil_observer.load(std::memory_order_acquire))
            obs->on_execute_command_lists(queue,count,lists);
    }
}

thread_local int32_t g_resize_buffers_depth = 0;''',
        "Observe real command-list reset/close/submit and preserve original calls")

    replace_exact(dx12_header,
        '''            void on_resource_barriers(
                ID3D12GraphicsCommandList* list, UINT count,
                const D3D12_RESOURCE_BARRIER* barriers) override {''',
        '''            std::atomic<uint64_t> executed_order{1};
            void on_command_list_reset(ID3D12GraphicsCommandList* list) override {
                if (!capture || !capture->requested()) return;
                const auto epoch=uevr::duoview::command_list_epochs.reset(
                    reinterpret_cast<uintptr_t>(list));
                if (epoch.known) capture->on_command_list_reset(list,epoch.value);
            }
            void on_command_list_close(ID3D12GraphicsCommandList* list, bool succeeded) override {
                if (!capture || !capture->requested()) return;
                const auto epoch=uevr::duoview::command_list_epochs.current(
                    reinterpret_cast<uintptr_t>(list));
                uevr::duoview::command_list_epochs.close(
                    reinterpret_cast<uintptr_t>(list),succeeded);
                capture->on_command_list_close(list,succeeded,epoch.value);
            }
            void on_execute_command_lists(
                ID3D12CommandQueue* queue, UINT count,
                ID3D12CommandList* const* lists) override {
                if (!capture || !capture->requested()) return;
                const uint64_t order=executed_order.fetch_add(1,std::memory_order_relaxed)+1;
                capture->on_queue_execute_command_lists(queue,count,lists,order);
            }
            void on_resource_barriers(
                ID3D12GraphicsCommandList* list, UINT count,
                const D3D12_RESOURCE_BARRIER* barriers) override {''',
        "Record actual Reset/Close/queue submission proof")
    # Freeze native source frame identity when its direct RHI marker executes.
    # Frame identity MUST be the immutable DuoView generation/frame, not the
    # separately progressing UE family frame number.
    render_hook = backend / "src/mods/vr/FFakeStereoRenderingHook.cpp"
    replace_exact(render_hook,
        '''        const auto duo_source = duo_command.owner();''',
        '''        const auto duo_source = duo_command.owner();
        if (vr->is_duoview_renderer_active() && duo_source) {
            const auto stamp = uevr::duoview::capture_source_stamp_from_command(duo_command, true);
            uevr::duoview::capture_source_stamps.begin_direct(GetCurrentThreadId(), stamp);
        }''',
        "Bind producer identity to real direct RHI checkpoint")
    replace_exact(dx12_header,
        '#include "dibr/DuoViewDibrD3D12.hpp"',
        '#include "dibr/DuoViewDibrD3D12.hpp"\n#include "dibr/ManualDibrProjection.hpp"',
        "DIBR native eye projection bridge")

    # A DIBR texture and descriptor set belongs to the same fenced OpenXR
    # image/command slot as its working Mono compositor. No per-frame PSO or
    # descriptor creation is allowed inside the XR scene-copy callback.
    replace_exact(dx12_cpp,
        '''                if (comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), srgb, frequency))
                    ++prepared;''',
        '''                if (comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), srgb, frequency))
                    ++prepared;
                if (vr->manual_dibr_stereo_requested()) {
                    auto& dibr=m_openxr.manual_dibr_compositors[&tc->commands];
                    if (!dibr) dibr=std::make_unique<uevr::duoview::dibr::dx12::Compositor>();
                    if (!dibr->prewarm(device,vr->get_hmd_width(),vr->get_hmd_height(),
                        DXGI_FORMAT_B8G8R8A8_UNORM))
                        SPDLOG_WARNING_EVERY_N_SEC(2,"[DuoView][DIBR] Unable to prewarm native stereo raster");
                }''',
        "Prewarm DIBR raster on DuoView activation")
    replace_exact(dx12_cpp,
        '''                if (!comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), duo_srgb, duo_frequency)) {
                    SPDLOG_WARNING_EVERY_N_SEC(2,
                        "[DuoView] DX12 prewarm failed; guarded compositing/fallback remains available");
                }''',
        '''                if (!comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), duo_srgb, duo_frequency)) {
                    SPDLOG_WARNING_EVERY_N_SEC(2,
                        "[DuoView] DX12 prewarm failed; guarded compositing/fallback remains available");
                }
                if (vr->manual_dibr_stereo_requested()) {
                    auto& dibr=this->manual_dibr_compositors[&tc->commands];
                    if (!dibr) dibr=std::make_unique<uevr::duoview::dibr::dx12::Compositor>();
                    if (!dibr->prewarm(device,vr->get_hmd_width(),vr->get_hmd_height(),
                        DXGI_FORMAT_B8G8R8A8_UNORM))
                        SPDLOG_WARNING_EVERY_N_SEC(2,"[DuoView][DIBR] XR swapchain stereo raster prewarm unavailable");
                }''',
        "Prewarm on OpenXR swapchain recreation")

    replace_exact(dx12_cpp,
        '''                            bool recorded = false;
                            bool callback_attempted = false;''',
        '''                            bool recorded = false;
                            bool manual_dibr_recorded = false;
                            bool callback_attempted = false;''',
        "Track actual stereo warp recording separately from stable Mono")
    replace_exact(dx12_cpp,
        '''                                 &recorded, &callback_attempted, &compositor_fault,
                                 &output_direct, &source_extents, &recorded_secondary, &recorded_target](''',
        '''                                 &recorded, &manual_dibr_recorded, &callback_attempted, &compositor_fault,
                                 &output_direct, &source_extents, &recorded_secondary, &recorded_target](''',
        "Preserve stereo state through XR copy callback")
    replace_exact(dx12_cpp,
        '''                                    recorded = compositor.record_native(device, commands.cmd_list.Get(),
                                        source.Get(), secondary.Get(), destination,
                                        D3D12_RESOURCE_STATE_RENDER_TARGET,
                                        D3D12_RESOURCE_STATE_RENDER_TARGET, *packet_frame,
                                        std::static_pointer_cast<const void>(packet),
                                        packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0);''',
        '''                                    auto mono_frame=*packet_frame;
                                    if (vr->manual_dibr_stereo_requested()) {
                                        // A true stereo draw consumes the private Mono
                                        // render target. Never bypass it with a direct
                                        // double-wide Mono raster in this mode.
                                        mono_frame.config.settings.direct_xr_output=false;
                                    }
                                    recorded = compositor.record_native(device, commands.cmd_list.Get(),
                                        source.Get(), secondary.Get(), destination,
                                        D3D12_RESOURCE_STATE_RENDER_TARGET,
                                        D3D12_RESOURCE_STATE_RENDER_TARGET, mono_frame,
                                        std::static_pointer_cast<const void>(packet),
                                        packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0);''',
        "Preserve exact Mono raster for DIBR source before stereo reprojection")

    replace_exact(dx12_cpp,
        '''                                    if (compositor.recorded_commands()) commands.has_commands = true;''',
        '''                                    if (compositor.recorded_commands()) commands.has_commands = true;
                                    if (recorded && vr->manual_dibr_stereo_requested() &&
                                        packet->duoview_pose_valid && packet_frame &&
                                        compositor.mono_output() && !compositor.last_native_direct_xr()) {
                                        // A valid DIBR result needs a current, owned
                                        // depth snapshot from this exact DuoView
                                        // producer packet. Missing samples do not
                                        // prevent the proven Mono path from submitting.
                                        auto& cap=m_openxr.manual_dibr_capture;
                                        const uevr::duoview::dibr::ProducerKey producer{
                                            packet_frame->config.key.generation,packet_frame->config.key.frame};
                                        const auto* queue=g_framework->get_d3d12_hook()->get_command_queue();
                                        const auto order=m_openxr.manual_dibr_observer.executed_order.load(
                                            std::memory_order_acquire)+1;
                                        auto periphery=cap.selected_periphery(producer,const_cast<ID3D12CommandQueue*>(queue),order);
                                        if (periphery) {
                                            using namespace uevr::duoview::dibr;
                                            using DibrRaster=uevr::duoview::dibr::dx12::Compositor;
                                            const auto make_pose=[](const XrView& view) {
                                                return NativeEyePose{
                                                    {view.pose.orientation.x,view.pose.orientation.y,
                                                     view.pose.orientation.z,view.pose.orientation.w},
                                                    {view.pose.position.x,view.pose.position.y,view.pose.position.z}};
                                            };
                                            const auto make_fov=[](const XrView& view) {
                                                return NativeEyeFovAngles{
                                                    view.fov.angleLeft,view.fov.angleRight,
                                                    view.fov.angleUp,view.fov.angleDown};
                                            };
                                            const auto native_left=make_pose(packet->duoview_views[0]);
                                            const auto native_right=make_pose(packet->duoview_views[1]);
                                            auto build_eye=[&](size_t eye,std::array<float,16>& matrix) {
                                                std::array<double,16> target_from_source{};
                                                if (!build_native_eye_target_from_source(native_left,native_right,
                                                    eye==0 ? native_left : native_right,vr->get_world_to_meters(),
                                                    target_from_source)) return false;
                                                ManualDibrProjectionInput input{};
                                                for (size_t i=0;i<16;++i)
                                                    input.sourceProjectionColumnMajor[i]=packet_frame->projection[i];
                                                input.targetFov=make_fov(packet->duoview_views[eye]);
                                                input.targetFromSourceColumnMajor=target_from_source;
                                                ManualDibrClipTransform clip{};
                                                if (!build_manual_dibr_clip_transform(input,clip)) return false;
                                                matrix=clip.sourceClipToTargetClipRowMajor;
                                                return true;
                                            };
                                            uevr::duoview::dibr::dx12::ProjectionPair projections{};
                                            auto color_desc=compositor.mono_output()->GetDesc();
                                            if (color_desc.Width<=UINT32_MAX && color_desc.Height<=UINT32_MAX &&
                                                build_eye(0,projections.left) && build_eye(1,projections.right)) {
                                                projections.color_rect={0,0,
                                                    static_cast<uint32_t>(color_desc.Width),color_desc.Height};
                                                const auto& l=packet_frame->config.layout;
                                                projections.fovea_uv_rect={l.u0,l.v0,l.u1,l.v1};
                                                auto fovea=cap.selected_fovea(producer,
                                                    const_cast<ID3D12CommandQueue*>(queue),order);
                                                projections.use_fovea_depth=fovea.has_value();
                                                auto selected_roles=cap.assignments();
                                                auto found=m_openxr.manual_dibr_compositors.find(&commands);
                                                if (found!=m_openxr.manual_dibr_compositors.end() &&
                                                    found->second && queue) {
                                                    auto& manual_dibr_compositor=*found->second;
                                                    manual_dibr_recorded=manual_dibr_compositor.record(
                                                        device,commands.cmd_list.Get(),compositor.mono_output(),
                                                        D3D12_RESOURCE_STATE_RENDER_TARGET,
                                                        *periphery,D3D12_RESOURCE_STATE_COPY_DEST,
                                                        fovea ? &*fovea : nullptr,D3D12_RESOURCE_STATE_COPY_DEST,
                                                        selected_roles,producer,
                                                        {reinterpret_cast<uint64_t>(queue),order,0},
                                                        destination,D3D12_RESOURCE_STATE_RENDER_TARGET,
                                                        projections,std::static_pointer_cast<const void>(packet),
                                                        uevr::duoview::command_list_epochs.current(
                                                            reinterpret_cast<uintptr_t>(commands.cmd_list.Get())).value);
                                                    if (manual_dibr_compositor.recorded_commands())
                                                        commands.has_commands=true;
                                                    if (!manual_dibr_recorded)
                                                        SPDLOG_WARNING_EVERY_N_SEC(2,
                                                            "[DuoView][DIBR] Stereo rejected; guarded Mono stays: {}",
                                                            manual_dibr_compositor.error());
                                                }
                                            }
                                        }
                                    }''',
        "Real live DIBR reprojection after native Mono composite")

    # Instrument just the real executed OpenXR command lists. Depth-capture
    # previews consume a bounded asynchronous copy only when picker is open.
    replace_exact(dx12_cpp,
        '''    texture_ctx->commands.execute();
    bool stalker_enqueued = false;''',
        '''    // Depth previews are recorded only on explicitly opened manual
    // picker pages, never on the default stable DuoView path.
    if (vr->is_duoview_renderer_active() && vr->manual_dibr_picker_open() &&
        swapchain_idx == (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE)
        manual_dibr_capture.record_preview_readbacks(
            binding.device,texture_ctx->commands.cmd_list.Get(),binding.queue,
            uevr::duoview::command_list_epochs.current(
                reinterpret_cast<uintptr_t>(texture_ctx->commands.cmd_list.Get())).value);
    texture_ctx->commands.execute();
    bool stalker_enqueued = false;''',
        "Asynchronous readback with current DX12 command epoch")

    # Bind compositor slot resources to their actual command-list submission
    # and GPU fences. Never recycle descriptors or OpenXR render targets by
    # frame index alone.
    replace_exact(dx12_header,
        '''        struct ManualDibrHookObserver final : D3D12DepthStencilObserver {
            uevr::duoview::dibr::dx12::ManualDibrCapture* capture{};''',
        '''        struct ManualDibrHookObserver final : D3D12DepthStencilObserver {
            OpenXR* owner{};
            uevr::duoview::dibr::dx12::ManualDibrCapture* capture{};''',
        "Bind DIBR queue observer to XR texture slots")
    replace_exact(dx12_header,
        '''                if (epoch.known) capture->on_command_list_reset(list,epoch.value);
            }''',
        '''                if (epoch.known) capture->on_command_list_reset(list,epoch.value);
                if (owner) {
                    std::scoped_lock lock{owner->mtx};
                    for (auto& [command, compositor] : owner->manual_dibr_compositors)
                        if (compositor) compositor->on_command_list_reset(list,epoch.value);
                }
            }''',
        "Retire abandoned DIBR descriptors on command reset")
    replace_exact(dx12_header,
        '''                capture->on_command_list_close(list,succeeded,epoch.value);
            }''',
        '''                capture->on_command_list_close(list,succeeded,epoch.value);
                if (owner) {
                    std::scoped_lock lock{owner->mtx};
                    for (auto& [command, compositor] : owner->manual_dibr_compositors)
                        if (compositor) compositor->on_command_list_close(list,succeeded,epoch.value);
                }
            }''',
        "Preserve only successful DIBR command-list recordings")
    replace_exact(dx12_header,
        '''                capture->on_queue_execute_command_lists(queue,count,lists,order);
            }''',
        '''                capture->on_queue_execute_command_lists(queue,count,lists,order);
                if (owner) {
                    std::scoped_lock lock{owner->mtx};
                    for (auto& [command, compositor] : owner->manual_dibr_compositors)
                        if (compositor) compositor->on_queue_execute_command_lists(queue,count,lists,order);
                }
            }''',
        "Signal per-slot DIBR GPU fences only after actual queue submission")
    replace_exact(dx12_cpp,
        '''    m_openxr.manual_dibr_observer.capture = &m_openxr.manual_dibr_capture;''',
        '''    m_openxr.manual_dibr_observer.capture = &m_openxr.manual_dibr_capture;
    m_openxr.manual_dibr_observer.owner = &m_openxr;
    if (dibr_picker || dibr_stereo) m_openxr.manual_dibr_capture.resume();''',
        "Initialize DIBR capture before connecting game hooks")

    replace_exact(dx12_cpp,
        '''    vr->get_openxr_runtime()->invalidate_duoview_scene();
    this->duoview_compositors.clear();''',
        '''    for (auto& [command, compositor] : this->manual_dibr_compositors) {
        if (compositor && !compositor->references_retired()) {
            spdlog::error("[DuoView][DIBR] XR swapchain retained: stereo descriptors still GPU-owned");
            return;
        }
    }
    vr->get_openxr_runtime()->invalidate_duoview_scene();
    this->manual_dibr_compositors.clear();
    this->manual_dibr_capture.reset();
    this->duoview_compositors.clear();''',
        "Prevent XR swapchain/descriptor release with live stereo commands")
    replace_exact(dx12_cpp,
        '''    this->duoview_compositors.clear();
    this->contexts.clear();''',
        '''    this->manual_dibr_compositors.clear();
    this->duoview_compositors.clear();
    this->contexts.clear();''',
        "Clear retired DIBR slots alongside stable DuoView slots")
    # Only the already accepted DuoView paths are installed here. The separate
    # production callsites / GPU fence hooks are still mandatory and are
    # rejected by verify_manual_dibr.py until actually implemented.
    (args.evidence / "manual_dibr_modules_installed.txt").write_text(
        "\n".join(installed) + "\n", encoding="utf-8"
    )
    print("Manual DIBR shader and reviewed sources installed. Production integration verification remains mandatory.")


if __name__ == "__main__":
    main()

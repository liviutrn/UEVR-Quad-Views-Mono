"""Guarded overlay onto clean Joey 5ac7edc; no DuoView source is applied."""
import pathlib, sys, shutil, subprocess, re, hashlib, json
root = pathlib.Path(sys.argv[1]).resolve()
here = pathlib.Path(__file__).resolve().parent
assert subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip() == '5ac7edc207866569334175e4ed8a7517971547f6'
changed = []
def edit(path, old, new):
    p=root/path
    s=p.read_text(encoding='utf-8')
    if s.count(old)!=1: raise RuntimeError(f'{path}: expected exactly one anchor, got {s.count(old)}: {old[:90]}')
    p.write_text(s.replace(old,new),encoding='utf-8'); changed.append(path)
def copy(name, path):
    shutil.copyfile(here/name, root/path); changed.append(path)
hdr='src/hooks/D3D12Hook.hpp'
cpp='src/hooks/D3D12Hook.cpp'
p=root/hdr; s=p.read_text(); start=s.index('class D3D12DepthStencilObserver {'); end=s.index('\nclass D3D12Hook',start)
observer=s[start:end]
observer=observer.replace('\n};','''
    virtual void on_post_resource_barriers(ID3D12GraphicsCommandList*, UINT, const D3D12_RESOURCE_BARRIER*) {}
    virtual void on_command_lists_executed(ID3D12CommandQueue*, UINT, ID3D12CommandList* const*) {}
    virtual void on_command_list_reset(ID3D12GraphicsCommandList*) {}
    virtual void on_render_pass(ID3D12GraphicsCommandList*, bool) {}
};''')
(root/'src/hooks/D3D12DepthStencilObserver.hpp').write_text('#pragma once\n#include <d3d12.h>\n'+observer)
edit(hdr,s[start:end], '#include "D3D12DepthStencilObserver.hpp"\n')
edit(hdr,'    static void WINAPI resource_barrier(','''    static void WINAPI execute_command_lists(ID3D12CommandQueue*, UINT, ID3D12CommandList* const*);
    static HRESULT WINAPI reset_command_list(ID3D12GraphicsCommandList*, ID3D12CommandAllocator*, ID3D12PipelineState*);
    static void WINAPI begin_render_pass(ID3D12GraphicsCommandList4*, UINT, const D3D12_RENDER_PASS_RENDER_TARGET_DESC*, const D3D12_RENDER_PASS_DEPTH_STENCIL_DESC*, D3D12_RENDER_PASS_FLAGS);
    static void WINAPI end_render_pass(ID3D12GraphicsCommandList4*);
    std::unique_ptr<PointerHook> m_stock_execute_hook{}, m_stock_reset_hook{}, m_stock_begin_hook{}, m_stock_end_hook{};
    static void WINAPI resource_barrier(''')
edit(cpp,'        m_hooked = true;','''        // The exact queue used by UEVR presentation establishes the ordering
        // proof. Unobserved/wrapper queues cannot publish a live depth slot.
        auto& execute_slot = (*(void***)command_queue)[10];
        m_stock_execute_hook = std::make_unique<PointerHook>(&execute_slot, (void*)&D3D12Hook::execute_command_lists);
        auto& reset_slot = (*(void***)command_list)[10];
        m_stock_reset_hook = std::make_unique<PointerHook>(&reset_slot, (void*)&D3D12Hook::reset_command_list);
        if (command_list4 != nullptr) {
            auto& begin_slot = (*(void***)command_list4.Get())[68];
            auto& end_slot = (*(void***)command_list4.Get())[69];
            m_stock_begin_hook = std::make_unique<PointerHook>(&begin_slot, (void*)&D3D12Hook::begin_render_pass);
            m_stock_end_hook = std::make_unique<PointerHook>(&end_slot, (void*)&D3D12Hook::end_render_pass);
        }
        m_hooked = true;''')
edit(cpp,'    m_resource_barrier_hooks.clear();','''    m_stock_execute_hook.reset(); m_stock_reset_hook.reset();
    m_stock_begin_hook.reset(); m_stock_end_hook.reset();
    m_resource_barrier_hooks.clear();''')
anchor='''    if (original != nullptr) {
        original(command_list, count, barriers);
    }
}
'''
edit(cpp,anchor,'''    if (original != nullptr) {
        original(command_list, count, barriers);
        if (!g_inside_depth_stencil_observer && d3d12 != nullptr) {
            if (auto* observer = d3d12->m_depth_stencil_observer.load(std::memory_order_acquire)) {
                g_inside_depth_stencil_observer = true;
                observer->on_post_resource_barriers(command_list, count, barriers);
                g_inside_depth_stencil_observer = false;
            }
        }
    }
}

void WINAPI D3D12Hook::execute_command_lists(ID3D12CommandQueue* queue, UINT n, ID3D12CommandList* const* lists) {
    auto* self = g_d3d12_hook;
    if (!self || !self->m_stock_execute_hook) return;
    self->m_stock_execute_hook->get_original<decltype(&D3D12Hook::execute_command_lists)>()(queue, n, lists);
    if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire))
        observer->on_command_lists_executed(queue, n, lists);
}
HRESULT WINAPI D3D12Hook::reset_command_list(ID3D12GraphicsCommandList* list, ID3D12CommandAllocator* allocator, ID3D12PipelineState* pso) {
    auto* self = g_d3d12_hook;
    if (!self || !self->m_stock_reset_hook) return E_FAIL;
    const auto result = self->m_stock_reset_hook->get_original<decltype(&D3D12Hook::reset_command_list)>()(list, allocator, pso);
    if (SUCCEEDED(result)) if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire))
        observer->on_command_list_reset(list);
    return result;
}
void WINAPI D3D12Hook::begin_render_pass(ID3D12GraphicsCommandList4* list, UINT n,
    const D3D12_RENDER_PASS_RENDER_TARGET_DESC* targets, const D3D12_RENDER_PASS_DEPTH_STENCIL_DESC* depth, D3D12_RENDER_PASS_FLAGS flags) {
    auto* self = g_d3d12_hook;
    if (!self || !self->m_stock_begin_hook) return;
    if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire)) observer->on_render_pass(list, true);
    self->m_stock_begin_hook->get_original<decltype(&D3D12Hook::begin_render_pass)>()(list,n,targets,depth,flags);
}
void WINAPI D3D12Hook::end_render_pass(ID3D12GraphicsCommandList4* list) {
    auto* self = g_d3d12_hook;
    if (!self || !self->m_stock_end_hook) return;
    self->m_stock_end_hook->get_original<decltype(&D3D12Hook::end_render_pass)>()(list);
    if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire)) observer->on_render_pass(list, false);
}
''')
copy('DepthPolicy.hpp','src/mods/vr/d3d12/DepthPolicy.hpp')
copy('StockDibrDepth.hpp','src/mods/vr/d3d12/StockDibrDepth.hpp')
dc='src/mods/vr/D3D12Component.cpp'; dh='src/mods/vr/D3D12Component.hpp'
edit(dh,'#include "d3d12/DIBRPreview.hpp"','#include "d3d12/DIBRPreview.hpp"\n#include "d3d12/StockDibrDepth.hpp"')
edit(dh,'    d3d12::DIBRPreview m_dibr_depth_capture{};','''    d3d12::DIBRPreview m_dibr_depth_capture{};
    stock_dibr::DepthCapture m_stock_dibr_depth{};
    bool m_stock_dibr_scope{};''')
edit(dh,'return m_dibr_depth_capture.depth_trace_summary();','return m_stock_dibr_scope ? m_stock_dibr_depth.summary() : m_dibr_depth_capture.depth_trace_summary();')
edit(dc,'    m_dibr_depth_capture.reset();','    m_dibr_depth_capture.reset();\n    m_stock_dibr_depth.reset();\n    m_stock_dibr_scope = false;')
edit(dc,'''        hook->set_depth_stencil_observer(vr->is_dibr_depth_trace_requested() ? &m_dibr_depth_capture : nullptr);''','''        m_stock_dibr_scope = is_stalker2_current_game() && vr->is_dibr_depth_trace_requested() &&
            vr->is_dibr_ue5_rdg_depth_capture_enabled();
        // Extent will be updated from the actual scene texture below.
        m_stock_dibr_depth.configure(hook->get_device(), hook->get_command_queue(),
            0, 0, m_stock_dibr_scope);
        hook->set_depth_stencil_observer(m_stock_dibr_scope ?
            static_cast<D3D12DepthStencilObserver*>(&m_stock_dibr_depth) :
            (vr->is_dibr_depth_trace_requested() ? &m_dibr_depth_capture : nullptr));''')
edit(dc,'''        m_dibr_depth_capture.set_depth_trace_expected_extent(
            static_cast<uint32_t>(source_desc.Width),
            source_desc.Height);''','''        m_dibr_depth_capture.set_depth_trace_expected_extent(
            static_cast<uint32_t>(source_desc.Width), source_desc.Height);
        if (m_stock_dibr_scope) m_stock_dibr_depth.configure(device, command_queue,
            source_desc.Width, source_desc.Height, true);''')
edit(dc,'''        dibr_depth_tex = m_dibr_depth_capture.captured_depth_snapshot();''','''        dibr_depth_tex = m_stock_dibr_scope ? m_stock_dibr_depth.acquire() :
            m_dibr_depth_capture.captured_depth_snapshot();
        if (m_stock_dibr_scope) SPDLOG_INFO_EVERY_N_SEC(2, "[StockDIBR] {}", m_stock_dibr_depth.summary());''')
edit(dc,'''    if (dibr_preview_succeeded) {
        // The DSV/RDG observer''','''    if (m_stock_dibr_scope) m_stock_dibr_depth.finish_frame();

    if (dibr_preview_succeeded) {
        // The DSV/RDG observer''')
# Source is often sRGB/BGRA and cannot be bound as an RGBA UAV. Use an RGBA
# compute output and explicit format conversion into Joey's BGRA XR source.
start=(root/dc).read_text().index('    if (output_desc.Width != present_desc.Width', (root/dc).read_text().index('bool D3D12Component::run_dibr_preview'))
end=(root/dc).read_text().index("    // DIBR records directly into this context",start)
old=(root/dc).read_text()[start:end]
edit(dc,old,'''    if (output_desc.Width != present_desc.Width || output_desc.Height != present_desc.Height) return false;
    // Alpha is explicitly opaque in the stock DIBR shader. SpriteBatch now
    // performs only RGBA -> BGRA storage conversion, avoiding unsupported
    // BGRA UAV writes and incompatible CopyResource between format families.
    d3d12::render_srv_to_rtv(m_game_batch.get(), slot->commands.cmd_list.Get(),
        slot->preview.output(), slot->present_tex,
        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);

''')
dp='src/mods/vr/d3d12/DIBRPreview.cpp'
edit(dp,'#include "DIBRPreview.hpp"','#include "DIBRPreview.hpp"\n#include "DepthPolicy.hpp"')
edit(dp,'''    if (depth_desc.Height != color_desc.Height ||
        (depth_desc.Width != color_desc.Width && depth_desc.Width != color_desc.Width / 2)) {''','''    if (stock_dibr::layout(depth_desc.Width, depth_desc.Height, color_desc.Width, color_desc.Height) == stock_dibr::Layout::Invalid) {''')
edit(dp,'    const auto output_format = color_srv_format(color_desc.Format);','    const auto output_format = DXGI_FORMAT_R8G8B8A8_UNORM;')
edit(dp,'    constants.depth_is_double_wide = depth_desc.Width == color_desc.Width ? 1 : 0;','''    constants.depth_is_double_wide = stock_dibr::layout(depth_desc.Width, depth_desc.Height,
        color_desc.Width, color_desc.Height) == stock_dibr::Layout::Packed ? 1 : 0;''')
edit(dp,'    source_desc.Width = eye_width;','''    // A linear SRV is illegal on a fully typed sRGB resource. Stage into
    // compatible typeless storage before creating the linear sampling view.
    if (source_desc.Format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB) source_desc.Format = DXGI_FORMAT_B8G8R8A8_TYPELESS;
    if (source_desc.Format == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB) source_desc.Format = DXGI_FORMAT_R8G8B8A8_TYPELESS;
    source_desc.Width = eye_width;''')
edit(dp,'''    case DXGI_FORMAT_R8G8B8A8_UNORM:
    case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:''','''    case DXGI_FORMAT_R8G8B8A8_TYPELESS:
    case DXGI_FORMAT_R8G8B8A8_UNORM:
    case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:''')
edit(dp,'    Output[dispatch_id.xy] = output_color;','    output_color.a = 1.0f;\n    Output[dispatch_id.xy] = output_color;')
# Stock declared DepthIsDoubleWide but never used it in any depth lookup.
# Packed stereo must sample the LEFT half for a left-eye source; all iterative
# reprojection/edge/repair reads must use the same mapping, including DLSS.
p=root/dp; s=p.read_text()
s,n=re.subn(r'SourceDepth\.SampleLevel\(LinearClamp, (.+?), 0\)',r'ReadDepth(\1)',s)
assert n == 9, n
p.write_text(s)
edit(dp,'float2 ReprojectSourceUv(float2 source_uv, float raw_depth) {','''float ReadDepth(float2 uv) {
    const float max_u = DepthIsDoubleWide != 0 ? 0.5f : 1.0f;
    const float2 half_texel = 0.5f / float2(DepthWidth, DepthHeight);
    const float2 mapped = float2(saturate(uv.x) * max_u, saturate(uv.y));
    return SourceDepth.SampleLevel(LinearClamp, clamp(mapped, half_texel,
        float2(max_u, 1.0f) - half_texel), 0);
}

float2 ReprojectSourceUv(float2 source_uv, float raw_depth) {''')
edit(dp,'    const float2 texel = 1.0f / float2((float)DepthWidth, (float)DepthHeight);','''    const float2 texel = float2(DepthIsDoubleWide != 0 ? 2.0f : 1.0f, 1.0f) /
        float2((float)DepthWidth, (float)DepthHeight);''')
# Construct the single source view before renderer creation in STALKER. Its
# stock Mono mode already takes this route. Never truncate a two-view family
# after engine stereo/instancing metadata has been constructed for two views.
fh='src/mods/vr/FFakeStereoRenderingHook.cpp'
edit(fh,'    if (vr->is_using_mono()) { return 1; }','''    if (stalker2_is_current_game() && vr->is_dibr_single_view_requested() && vr->is_dibr_preview_active()) {
        const auto ready = vr->d3d12().get_dibr_single_view_readiness();
        if (ready.preview_ready && ready.consecutive_ready_frames >= DIBR_SINGLE_VIEW_WARMUP_FRAMES) return 1;
    }
    if (vr->is_using_mono()) { return 1; }''')
anchor='''        if (g_hook->m_dibr_single_view_latched_generation == readiness.generation) {
            set_dibr_status(DIBR_SINGLE_VIEW_BLOCKED, "three DIBR output failures in this generation");'''
edit(fh,anchor,'''        if (stalker2_is_current_game()) {
            // View count was chosen by GetDesiredNumberOfViews, as in Joey
            // Mono. Observe and report; do not mutate an instantiated family.
            const auto main_family = view_family->get_render_target() == rtm->get_viewport() &&
                rtm->get_viewport() != nullptr && view_family->get_scene_interface() != nullptr &&
                (prev_count == 1 || prev_count == 2) &&
                sdk::FSceneViewFamily::validate_views(view_family, views_ptr, prev_count);
            if (main_family && prev_count == 1 && readiness.preview_ready) {
                g_hook->m_dibr_single_view_suppressed_frames.fetch_add(1, std::memory_order_relaxed);
                set_dibr_status(DIBR_SINGLE_VIEW_ACTIVE, "STALKER: one source view constructed before renderer creation");
            } else if (main_family && prev_count == 2) {
                set_dibr_status(DIBR_SINGLE_VIEW_WARMING_UP, "STALKER: two-view depth/output warmup; no family truncation");
                g_hook->m_dibr_single_view_fallback_frames.fetch_add(1, std::memory_order_relaxed);
            }
            g_hook->m_render_module_begin_render_viewfamily_hook.unsafe_call<void>(render_module, canvas, view_family_candidate);
            return;
        }

        if (g_hook->m_dibr_single_view_latched_generation == readiness.generation) {
            set_dibr_status(DIBR_SINGLE_VIEW_BLOCKED, "three DIBR output failures in this generation");''')
# Default RDG capture enabled in this dedicated test package; rendering mode
# remains user selected, and all capture stays gated to DIBR mode only.
edit('src/mods/VR.hpp','ModToggle::create(generate_name("DIBRUE5RDGDepthCapture"), false)','ModToggle::create(generate_name("DIBRUE5RDGDepthCapture"), true)')
print(json.dumps({'baseline':'5ac7edc207866569334175e4ed8a7517971547f6','changed':sorted(set(changed))},indent=2))

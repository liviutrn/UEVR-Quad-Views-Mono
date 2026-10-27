"""R5 observer ordering and capture-default corrections after the R4 overlay."""
import pathlib
import shutil
import sys

root = pathlib.Path(sys.argv[1]).resolve()
here = pathlib.Path(__file__).resolve().parent
def edit(path, old, new):
    p = root / path
    s = p.read_text()
    if s.count(old) != 1:
        raise RuntimeError(f'{path}: expected one adversarial anchor, got {s.count(old)}: {old[:90]}')
    p.write_text(s.replace(old, new))

shutil.copyfile(here / 'DsvMetadataCache.hpp', root / 'src/hooks/DsvMetadataCache.hpp')
h = 'src/hooks/D3D12Hook.hpp'
c = 'src/hooks/D3D12Hook.cpp'
edit(h, '#include "QueueSubmitHook.hpp"', '#include "QueueSubmitHook.hpp"\n#include "DsvMetadataCache.hpp"')
p = root / h
s = p.read_text()
start = s.index('    struct CachedDepthStencilView {')
end = s.index('    void cache_depth_stencil_view(', start)
p.write_text(s[:start] + '    stock_dibr::DsvMetadataCache m_stock_dsv_cache{};\n' + s[end:])
p = root / c
s = p.read_text()
start = s.index('void D3D12Hook::set_depth_stencil_observer(')
end = s.index('\nvoid WINAPI D3D12Hook::create_render_target_view(', start)
p.write_text(s[:start] + '''void D3D12Hook::set_depth_stencil_observer(D3D12DepthStencilObserver* observer) {
    m_stock_dsv_cache.attach(m_depth_stencil_observer, observer);
}

void D3D12Hook::cache_depth_stencil_view(ID3D12Resource* resource,
    const D3D12_DEPTH_STENCIL_VIEW_DESC* desc, D3D12_CPU_DESCRIPTOR_HANDLE descriptor) {
    m_stock_dsv_cache.publish(m_depth_stencil_observer, resource, desc, descriptor);
}
''' + s[end:])
edit(c, '''        d3d12->cache_depth_stencil_view(resource, desc, descriptor);
        if (const auto observer = d3d12->m_depth_stencil_observer.load(std::memory_order_acquire); observer != nullptr)
            observer->on_depth_stencil_view_created(resource, desc, descriptor);''',
    '        d3d12->cache_depth_stencil_view(resource, desc, descriptor);')
edit('src/mods/VR.hpp', 'ModToggle::create(generate_name("DIBRUE5RDGDepthCapture"), true)',
    'ModToggle::create(generate_name("DIBRUE5RDGDepthCapture"), false)')
print('Applied serialized DSV replay/live updates and restored opt-in capture default')

# Preserve late Execute/Reset retirement after active DIBR observation stops.
shutil.copyfile(here / 'DepthRetirementHub.hpp', root / 'src/hooks/DepthRetirementHub.hpp')
edit('src/hooks/D3D12DepthStencilObserver.hpp',
    '    virtual bool accepts_cached_dsv_metadata() const { return false; }',
    '    virtual bool accepts_cached_dsv_metadata() const { return false; }\n    virtual bool has_pending_retirement() { return false; }')
edit(h, '#include "DsvMetadataCache.hpp"', '#include "DsvMetadataCache.hpp"\n#include "DepthRetirementHub.hpp"')
edit(c, '''    if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire))
        observer->on_command_lists_executed(queue, n, lists);''',
    '''    auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire);
    if (observer) observer->on_command_lists_executed(queue, n, lists);
    stock_dibr::DepthRetirementHub::submitted(observer, queue, n, lists);''')
edit(c, '''    if (SUCCEEDED(result)) if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire))
        observer->on_command_list_reset(list);''',
    '''    if (SUCCEEDED(result)) {
        auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire);
        if (observer) observer->on_command_list_reset(list);
        stock_dibr::DepthRetirementHub::reset_list(observer, list);
    }''')
dc = 'src/mods/vr/D3D12Component.cpp'
dh = 'src/mods/vr/D3D12Component.hpp'
edit(dh, '    stock_dibr::DepthCapture m_stock_dibr_depth{};',
    '    std::shared_ptr<stock_dibr::DepthCapture> m_stock_dibr_depth{std::make_shared<stock_dibr::DepthCapture>()};')
edit(dc, 'void D3D12Component::reset_dibr_preview() {',
    'void D3D12Component::reset_dibr_preview() {\n    stock_dibr::DepthRetirementHub::arm(m_stock_dibr_depth);')
edit(dc, '    m_stock_dibr_depth.reset();\n    m_stock_dibr_scope = false;',
    '    m_stock_dibr_depth.reset();\n    stock_dibr::DepthRetirementHub::disarm(m_stock_dibr_depth);\n    m_stock_dibr_scope = false;')
edit(dc, '''        hook->set_depth_stencil_observer(m_stock_dibr_scope ?''',
    '''        if (m_stock_dibr_scope) stock_dibr::DepthRetirementHub::arm(m_stock_dibr_depth);
        else stock_dibr::DepthRetirementHub::disarm(m_stock_dibr_depth);
        hook->set_depth_stencil_observer(m_stock_dibr_scope ?''')
edit(dc, 'static_cast<D3D12DepthStencilObserver*>(&m_stock_dibr_depth)',
    'static_cast<D3D12DepthStencilObserver*>(m_stock_dibr_depth.get())')
p = root / dc
s = p.read_text().replace('m_stock_dibr_depth.', 'm_stock_dibr_depth->')
# get() refers to shared ownership rather than the depth capture object.
s = s.replace('m_stock_dibr_depth->get()', 'm_stock_dibr_depth.get()')
p.write_text(s)
 
# Detach drains every observer callback before its owner may be destroyed.
# The recursive gate admits observer-private ResourceBarrier calls; never hold
# it around the outer original driver/proxy dispatch.
edit(h, '    std::atomic<D3D12DepthStencilObserver*> m_depth_stencil_observer{nullptr};',
    '    std::recursive_mutex m_depth_stencil_activity{};\n    std::atomic<D3D12DepthStencilObserver*> m_depth_stencil_observer{nullptr};')
edit(c, '''    m_stock_dsv_cache.attach(m_depth_stencil_observer, observer);''',
    '''    std::scoped_lock activity{m_depth_stencil_activity};
    m_stock_dsv_cache.attach(m_depth_stencil_observer, observer);''')
edit(c, '''    m_stock_dsv_cache.publish(m_depth_stencil_observer, resource, desc, descriptor);''',
    '''    std::scoped_lock activity{m_depth_stencil_activity};
    m_stock_dsv_cache.publish(m_depth_stencil_observer, resource, desc, descriptor);''')
edit(c, '    m_depth_stencil_observer.store(nullptr, std::memory_order_release);',
    '    set_depth_stencil_observer(nullptr);')
p = root / c
s = p.read_text()
import re
s, guarded = re.subn(
    r'(?m)^( +)((?:if \(const auto observer|if \(auto\* observer|auto\* observer) = (self|d3d12)->m_depth_stencil_observer\.load[^\n]*)',
    lambda match: match[1] + 'std::scoped_lock activity{' + match[3] + '->m_depth_stencil_activity};\n' + match[0], s)
if guarded != 8:
    raise RuntimeError(f'Expected eight observer callback gates, got {guarded}')
p.write_text(s)
# BeginRenderPass previously retained its raw observer across the original.
# Use separate gated snapshots on either side, as ResourceBarrier does.
edit(c, '''    std::scoped_lock activity{self->m_depth_stencil_activity};
    auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire);
    if (observer) observer->on_render_pass(list, true);
    self->m_stock_begin_hook->get_original<decltype(&D3D12Hook::begin_render_pass)>()(list,n,targets,depth,flags);
    if (observer) {
        D3D12_CPU_DESCRIPTOR_HANDLE dsv{};
        if (depth) dsv = depth->cpuDescriptor;
        observer->on_render_targets(list, n, dsv);
    }''', '''    {
        std::scoped_lock activity{self->m_depth_stencil_activity};
        if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire))
            observer->on_render_pass(list, true);
    }
    self->m_stock_begin_hook->get_original<decltype(&D3D12Hook::begin_render_pass)>()(list,n,targets,depth,flags);
    {
        std::scoped_lock activity{self->m_depth_stencil_activity};
        if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire)) {
            D3D12_CPU_DESCRIPTOR_HANDLE dsv{};
            if (depth) dsv = depth->cpuDescriptor;
            observer->on_render_targets(list, n, dsv);
        }
    }''')
edit(dc, '''D3D12Component::~D3D12Component() {
''', '''D3D12Component::~D3D12Component() {
    // Drain raw observer callbacks before either capture member is destroyed.
    // Retain pending stock recordings through late Execute/Reset retirement.
    stock_dibr::DepthRetirementHub::arm(m_stock_dibr_depth);
    if (g_framework != nullptr) {
        if (auto& hook = g_framework->get_d3d12_hook(); hook != nullptr)
            hook->set_depth_stencil_observer(nullptr);
    }
    m_stock_dibr_depth->reset();
    stock_dibr::DepthRetirementHub::disarm(m_stock_dibr_depth);
''')
print('Applied observer callback drain and component capture teardown')
print('Applied shared capture retirement routing across mode exit')
# Invalidate old readiness before constructing views in a replacement UWorld.
edit(dh, '    struct DIBRSingleViewReadiness {', '''    void invalidate_dibr_single_view_readiness() {
        m_dibr_single_view_preview_ready.store(false, std::memory_order_release);
        m_dibr_single_view_ready_frames.store(0, std::memory_order_release);
        m_dibr_single_view_generation.fetch_add(1, std::memory_order_acq_rel);
    }

    struct DIBRSingleViewReadiness {''')
fh = 'src/mods/vr/FFakeStereoRenderingHook.hpp'
fc = 'src/mods/vr/FFakeStereoRenderingHook.cpp'
edit(fh, '    uintptr_t m_dibr_single_view_scene{};',
    '    uintptr_t m_dibr_single_view_scene{};\n    uintptr_t m_dibr_single_view_world{};')
edit(fc, '''    if (stalker2_is_current_game() && vr->is_dibr_single_view_requested() && vr->is_dibr_preview_active()) {
        const auto ready = vr->d3d12().get_dibr_single_view_readiness();''',
    '''    if (stalker2_is_current_game() && vr->is_dibr_single_view_requested() && vr->is_dibr_preview_active()) {
        if (!is_stereo_enabled || !g_hook->is_in_viewport_client_draw()) return is_stereo_enabled ? 2u : 1u;
        const auto engine = sdk::UEngine::get();
        const auto world = engine != nullptr ? engine->get_world() : nullptr;
        const auto world_identity = reinterpret_cast<uintptr_t>(world);
        if (g_hook->m_dibr_single_view_world != world_identity) {
            g_hook->m_dibr_single_view_world = world_identity;
            g_hook->m_dibr_single_view_stable_frames = 0;
            vr->d3d12().invalidate_dibr_single_view_readiness();
        }
        const auto ready = vr->d3d12().get_dibr_single_view_readiness();''')
edit(fc, '''        const bool validated_main_family = ready.generation != 0 &&''',
    '''        const bool validated_main_family = world_identity != 0 && ready.generation != 0 &&''')
print('Applied pre-construction UWorld change readiness invalidation')
p = root / dh
s = p.read_text().replace('m_stock_dibr_depth.', 'm_stock_dibr_depth->')
s = s.replace('#include "d3d12/StockDibrDepth.hpp"', '#include "d3d12/StockDibrDepth.hpp"\n#include <memory>')
p.write_text(s)

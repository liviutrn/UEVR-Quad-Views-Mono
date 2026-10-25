"""Apply the bounded DSV/viewport provenance overlay after apply.py."""
import pathlib
import subprocess
import sys
import json

root = pathlib.Path(sys.argv[1]).resolve()
baseline = "5ac7edc207866569334175e4ed8a7517971547f6"
actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
if actual != baseline:
    raise RuntimeError(f"expected clean Joey baseline {baseline}, got {actual}")
observer_path = root / "src/hooks/D3D12DepthStencilObserver.hpp"
if not observer_path.exists() or not (root / "src/mods/vr/d3d12/StockDibrDepth.hpp").exists():
    raise RuntimeError("run stock_dibr/apply.py before apply_provenance.py")

changed = []

def edit(path, old, new):
    target = root / path
    source = target.read_text(encoding="utf-8")
    hits = source.count(old)
    if hits != 1:
        raise RuntimeError(f"{path}: expected one overlay anchor, found {hits}: {old[:100]}")
    target.write_text(source.replace(old, new), encoding="utf-8")
    changed.append(path)

edit("src/hooks/D3D12DepthStencilObserver.hpp", """    virtual void on_render_pass(ID3D12GraphicsCommandList*, bool) {}
};""", """    virtual void on_render_pass(ID3D12GraphicsCommandList*, bool) {}
    virtual void on_render_targets(ID3D12GraphicsCommandList*, UINT, D3D12_CPU_DESCRIPTOR_HANDLE) {}
    virtual void on_viewports(ID3D12GraphicsCommandList*, UINT, const D3D12_VIEWPORT*) {}
    virtual bool accepts_cached_dsv_metadata() const { return false; }
};""")

hdr = "src/hooks/D3D12Hook.hpp"
cpp = "src/hooks/D3D12Hook.cpp"
edit(hdr, "#include <iostream>\n", "#include <iostream>\n#include <iterator>\n#include <list>\n#include <mutex>\n")
edit(hdr, """    void set_depth_stencil_observer(D3D12DepthStencilObserver* observer) {
        m_depth_stencil_observer.store(observer, std::memory_order_release);
    }""", """    void set_depth_stencil_observer(D3D12DepthStencilObserver* observer);""")
edit(hdr, """protected:
    ID3D12Device4* m_device{ nullptr };""", """protected:
    struct CachedDepthStencilView {
        ID3D12Resource* resource{}; // non-owning; cache replay never dereferences it
        D3D12_DEPTH_STENCIL_VIEW_DESC desc{};
        bool has_desc{};
        D3D12_CPU_DESCRIPTOR_HANDLE descriptor{};
    };
    struct CachedDepthStencilViewEntry {
        CachedDepthStencilView view{};
        std::list<SIZE_T>::iterator recency;
    };
    static constexpr size_t DSV_CACHE_LIMIT = 4096;
    std::mutex m_dsv_cache_mutex{};
    std::list<SIZE_T> m_dsv_cache_order{};
    std::unordered_map<SIZE_T, CachedDepthStencilViewEntry> m_dsv_cache{};
    void cache_depth_stencil_view(ID3D12Resource*, const D3D12_DEPTH_STENCIL_VIEW_DESC*, D3D12_CPU_DESCRIPTOR_HANDLE);

    ID3D12Device4* m_device{ nullptr };""")
edit(hdr, """    static void WINAPI end_render_pass(ID3D12GraphicsCommandList4*);
    std::unique_ptr<PointerHook> m_stock_execute_hook{}, m_stock_reset_hook{}, m_stock_begin_hook{}, m_stock_end_hook{};""", """    static void WINAPI end_render_pass(ID3D12GraphicsCommandList4*);
    static void WINAPI set_render_targets(ID3D12GraphicsCommandList*, UINT, const D3D12_CPU_DESCRIPTOR_HANDLE*, BOOL, const D3D12_CPU_DESCRIPTOR_HANDLE*);
    static void WINAPI set_viewports(ID3D12GraphicsCommandList*, UINT, const D3D12_VIEWPORT*);
    std::unique_ptr<PointerHook> m_stock_execute_hook{}, m_stock_reset_hook{}, m_stock_begin_hook{}, m_stock_end_hook{};
    std::unique_ptr<PointerHook> m_stock_render_targets_hook{}, m_stock_viewports_hook{};""")

edit(cpp, """        auto& reset_slot = (*(void***)command_list)[10];
        m_stock_reset_hook = std::make_unique<PointerHook>(&reset_slot, (void*)&D3D12Hook::reset_command_list);
        if (command_list4 != nullptr) {""", """        auto& reset_slot = (*(void***)command_list)[10];
        m_stock_reset_hook = std::make_unique<PointerHook>(&reset_slot, (void*)&D3D12Hook::reset_command_list);
        auto& render_targets_slot = (*(void***)command_list)[46];
        m_stock_render_targets_hook = std::make_unique<PointerHook>(&render_targets_slot, (void*)&D3D12Hook::set_render_targets);
        auto& viewports_slot = (*(void***)command_list)[21];
        m_stock_viewports_hook = std::make_unique<PointerHook>(&viewports_slot, (void*)&D3D12Hook::set_viewports);
        if (command_list4 != nullptr) {""")
edit(cpp, """    m_stock_execute_hook.reset(); m_stock_reset_hook.reset();
    m_stock_begin_hook.reset(); m_stock_end_hook.reset();""", """    m_stock_execute_hook.reset(); m_stock_reset_hook.reset();
    m_stock_begin_hook.reset(); m_stock_end_hook.reset();
    m_stock_render_targets_hook.reset(); m_stock_viewports_hook.reset();""")

edit(cpp, "void WINAPI D3D12Hook::create_render_target_view(", """void D3D12Hook::set_depth_stencil_observer(D3D12DepthStencilObserver* observer) {
    auto* previous = m_depth_stencil_observer.exchange(observer, std::memory_order_acq_rel);
    if (!observer || observer == previous || !observer->accepts_cached_dsv_metadata()) return;

    std::vector<CachedDepthStencilView> replay;
    {
        std::scoped_lock lock{m_dsv_cache_mutex};
        replay.reserve(m_dsv_cache.size());
        for (const auto& [key, entry] : m_dsv_cache) {
            (void)key;
            replay.push_back(entry.view);
        }
    }
    for (const auto& view : replay)
        observer->on_depth_stencil_view_created(view.resource, view.has_desc ? &view.desc : nullptr, view.descriptor);
}

void D3D12Hook::cache_depth_stencil_view(
    ID3D12Resource* resource,
    const D3D12_DEPTH_STENCIL_VIEW_DESC* desc,
    D3D12_CPU_DESCRIPTOR_HANDLE descriptor
) {
    if (!descriptor.ptr) return;
    CachedDepthStencilView view{};
    view.resource = resource;
    view.descriptor = descriptor;
    if (desc != nullptr) { view.desc = *desc; view.has_desc = true; }

    std::scoped_lock lock{m_dsv_cache_mutex};
    const auto found = m_dsv_cache.find(descriptor.ptr);
    if (found != m_dsv_cache.end()) {
        found->second.view = view;
        m_dsv_cache_order.splice(m_dsv_cache_order.end(), m_dsv_cache_order, found->second.recency);
        found->second.recency = std::prev(m_dsv_cache_order.end());
        return;
    }
    if (m_dsv_cache.size() >= DSV_CACHE_LIMIT) {
        const auto oldest = m_dsv_cache_order.front();
        m_dsv_cache_order.pop_front();
        m_dsv_cache.erase(oldest);
    }
    m_dsv_cache_order.push_back(descriptor.ptr);
    m_dsv_cache.emplace(descriptor.ptr, CachedDepthStencilViewEntry{view, std::prev(m_dsv_cache_order.end())});
}

void WINAPI D3D12Hook::create_render_target_view(""")
edit(cpp, """    (void)desc;
    auto d3d12 = g_d3d12_hook;""", """    auto d3d12 = g_d3d12_hook;""")
edit(cpp, """    if (d3d12 != nullptr) {
        if (const auto observer = d3d12->m_depth_stencil_observer.load(std::memory_order_acquire); observer != nullptr) {
            observer->on_depth_stencil_view_created(resource, desc, descriptor);
        }
    }""", """    if (d3d12 != nullptr) {
        d3d12->cache_depth_stencil_view(resource, desc, descriptor);
        if (const auto observer = d3d12->m_depth_stencil_observer.load(std::memory_order_acquire); observer != nullptr)
            observer->on_depth_stencil_view_created(resource, desc, descriptor);
    }""")

edit(cpp, """    if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire)) observer->on_render_pass(list, true);
    self->m_stock_begin_hook->get_original<decltype(&D3D12Hook::begin_render_pass)>()(list,n,targets,depth,flags);
}""", """    auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire);
    if (observer) observer->on_render_pass(list, true);
    self->m_stock_begin_hook->get_original<decltype(&D3D12Hook::begin_render_pass)>()(list,n,targets,depth,flags);
    if (observer) {
        D3D12_CPU_DESCRIPTOR_HANDLE dsv{};
        if (depth) dsv = depth->cpuDescriptor;
        observer->on_render_targets(list, n, dsv);
    }
}""")

edit(cpp, """thread_local int32_t g_resize_buffers_depth = 0;""", """void WINAPI D3D12Hook::set_render_targets(ID3D12GraphicsCommandList* list, UINT n,
    const D3D12_CPU_DESCRIPTOR_HANDLE* rtvs, BOOL single_range, const D3D12_CPU_DESCRIPTOR_HANDLE* dsv) {
    auto* self = g_d3d12_hook;
    if (!self || !self->m_stock_render_targets_hook) return;
    self->m_stock_render_targets_hook->get_original<decltype(&D3D12Hook::set_render_targets)>()(
        list, n, rtvs, single_range, dsv);
    if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire)) {
        D3D12_CPU_DESCRIPTOR_HANDLE bound_dsv{};
        if (dsv) bound_dsv = *dsv;
        observer->on_render_targets(list, n, bound_dsv);
    }
}

void WINAPI D3D12Hook::set_viewports(ID3D12GraphicsCommandList* list, UINT n, const D3D12_VIEWPORT* viewports) {
    auto* self = g_d3d12_hook;
    if (!self || !self->m_stock_viewports_hook) return;
    self->m_stock_viewports_hook->get_original<decltype(&D3D12Hook::set_viewports)>()(list, n, viewports);
    if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire))
        observer->on_viewports(list, n, viewports);
}

thread_local int32_t g_resize_buffers_depth = 0;""")

print(json.dumps({"baseline": baseline, "apply_after": "stock_dibr/apply.py", "changed": sorted(set(changed))}, indent=2))

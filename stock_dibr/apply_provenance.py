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
    std::unique_ptr<PointerHook> m_stock_execute_hook{}, m_stock_begin_hook{}, m_stock_end_hook{};
    std::vector<std::unique_ptr<PointerHook>> m_stock_reset_hooks{}, m_stock_render_targets_hooks{}, m_stock_viewports_hooks{};
    std::unordered_map<uintptr_t, PointerHook*> m_stock_reset_hook_lookup{}, m_stock_render_targets_hook_lookup{}, m_stock_viewports_hook_lookup{};""")

# These three command-list methods are inherited by the queried interfaces,
# but the concrete COM object can expose distinct vtables. Hook each unique
# slot and dispatch to its own original implementation.
edit(cpp, """        std::unordered_set<uintptr_t> set_pipeline_state_slots{};
        std::unordered_set<uintptr_t> resource_barrier_slots{};""", """        std::unordered_set<uintptr_t> set_pipeline_state_slots{};
        std::unordered_set<uintptr_t> resource_barrier_slots{};
        std::unordered_set<uintptr_t> reset_slots{};
        std::unordered_set<uintptr_t> render_targets_slots{};
        std::unordered_set<uintptr_t> viewports_slots{};""")
edit(cpp, """        const std::array<IUnknown*, 7> command_list_interfaces{
            command_list1.Get(),
            command_list2.Get(),
            command_list3.Get(),
            command_list4.Get(),
            command_list5.Get(),
            command_list6.Get(),
            command_list7.Get()
        };""", """        const std::array<IUnknown*, 8> command_list_interfaces{
            command_list,
            command_list1.Get(),
            command_list2.Get(),
            command_list3.Get(),
            command_list4.Get(),
            command_list5.Get(),
            command_list6.Get(),
            command_list7.Get()
        };""")
edit(cpp, """            add_unique_pointer_hook(
                iface,
                RESOURCE_BARRIER_VTABLE_INDEX,
                reinterpret_cast<void*>(&D3D12Hook::resource_barrier),
                m_resource_barrier_hooks,
                m_resource_barrier_hook_lookup,
                resource_barrier_slots
            );
        }""", """            add_unique_pointer_hook(
                iface,
                RESOURCE_BARRIER_VTABLE_INDEX,
                reinterpret_cast<void*>(&D3D12Hook::resource_barrier),
                m_resource_barrier_hooks,
                m_resource_barrier_hook_lookup,
                resource_barrier_slots
            );
            add_unique_pointer_hook(iface, 10,
                reinterpret_cast<void*>(&D3D12Hook::reset_command_list),
                m_stock_reset_hooks, m_stock_reset_hook_lookup, reset_slots);
            add_unique_pointer_hook(iface, 46,
                reinterpret_cast<void*>(&D3D12Hook::set_render_targets),
                m_stock_render_targets_hooks, m_stock_render_targets_hook_lookup, render_targets_slots);
            add_unique_pointer_hook(iface, 21,
                reinterpret_cast<void*>(&D3D12Hook::set_viewports),
                m_stock_viewports_hooks, m_stock_viewports_hook_lookup, viewports_slots);
        }""")
edit(cpp, """        auto& reset_slot = (*(void***)command_list)[10];
        m_stock_reset_hook = std::make_unique<PointerHook>(&reset_slot, (void*)&D3D12Hook::reset_command_list);
        if (command_list4 != nullptr) {""", """        if (command_list4 != nullptr) {""")
edit(cpp, """    m_stock_execute_hook.reset(); m_stock_reset_hook.reset();
    m_stock_begin_hook.reset(); m_stock_end_hook.reset();""", """    m_stock_execute_hook.reset();
    m_stock_begin_hook.reset(); m_stock_end_hook.reset();
    m_stock_reset_hooks.clear(); m_stock_render_targets_hooks.clear(); m_stock_viewports_hooks.clear();
    m_stock_reset_hook_lookup.clear(); m_stock_render_targets_hook_lookup.clear(); m_stock_viewports_hook_lookup.clear();""")

edit(cpp, """HRESULT WINAPI D3D12Hook::reset_command_list(ID3D12GraphicsCommandList* list, ID3D12CommandAllocator* allocator, ID3D12PipelineState* pso) {
    auto* self = g_d3d12_hook;
    if (!self || !self->m_stock_reset_hook) return E_FAIL;
    const auto result = self->m_stock_reset_hook->get_original<decltype(&D3D12Hook::reset_command_list)>()(list, allocator, pso);""", """HRESULT WINAPI D3D12Hook::reset_command_list(ID3D12GraphicsCommandList* list, ID3D12CommandAllocator* allocator, ID3D12PipelineState* pso) {
    auto* self = g_d3d12_hook;
    if (!self || list == nullptr) return E_FAIL;
    const auto slot = &(*(void***)list)[10];
    const auto found = self->m_stock_reset_hook_lookup.find(reinterpret_cast<uintptr_t>(slot));
    auto* hook = found != self->m_stock_reset_hook_lookup.end() ? found->second : nullptr;
    auto original = hook != nullptr ? hook->get_original<decltype(&D3D12Hook::reset_command_list)>() : nullptr;
    if (original == nullptr) return E_FAIL;
    const auto result = original(list, allocator, pso);""")

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
    if (!self || list == nullptr) return;
    const auto slot = &(*(void***)list)[46];
    const auto found = self->m_stock_render_targets_hook_lookup.find(reinterpret_cast<uintptr_t>(slot));
    auto* hook = found != self->m_stock_render_targets_hook_lookup.end() ? found->second : nullptr;
    auto original = hook != nullptr ? hook->get_original<decltype(&D3D12Hook::set_render_targets)>() : nullptr;
    if (original == nullptr) return;
    original(list, n, rtvs, single_range, dsv);
    if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire)) {
        D3D12_CPU_DESCRIPTOR_HANDLE bound_dsv{};
        if (dsv) bound_dsv = *dsv;
        observer->on_render_targets(list, n, bound_dsv);
    }
}

void WINAPI D3D12Hook::set_viewports(ID3D12GraphicsCommandList* list, UINT n, const D3D12_VIEWPORT* viewports) {
    auto* self = g_d3d12_hook;
    if (!self || list == nullptr) return;
    const auto slot = &(*(void***)list)[21];
    const auto found = self->m_stock_viewports_hook_lookup.find(reinterpret_cast<uintptr_t>(slot));
    auto* hook = found != self->m_stock_viewports_hook_lookup.end() ? found->second : nullptr;
    auto original = hook != nullptr ? hook->get_original<decltype(&D3D12Hook::set_viewports)>() : nullptr;
    if (original == nullptr) return;
    original(list, n, viewports);
    if (auto* observer = self->m_depth_stencil_observer.load(std::memory_order_acquire))
        observer->on_viewports(list, n, viewports);
}

thread_local int32_t g_resize_buffers_depth = 0;""")

print(json.dumps({"baseline": baseline, "apply_after": "stock_dibr/apply.py", "changed": sorted(set(changed))}, indent=2))

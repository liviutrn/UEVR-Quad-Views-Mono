#pragma once
#include <hooks/D3D12DepthStencilObserver.hpp>
#include <atomic>
#include <list>
#include <mutex>
#include <unordered_map>

namespace stock_dibr {
// Replay and live updates share one serialization boundary. A descriptor
// replacement can never be delivered before an older cached replay.
class DsvMetadataCache {
    struct View {
        ID3D12Resource* resource{}; // metadata only, never dereferenced
        D3D12_DEPTH_STENCIL_VIEW_DESC desc{};
        bool has_desc{};
        D3D12_CPU_DESCRIPTOR_HANDLE descriptor{};
    };
    struct Entry { View view; std::list<SIZE_T>::iterator recency; };
    std::mutex mutex;
    std::list<SIZE_T> order;
    std::unordered_map<SIZE_T, Entry> views;
    static constexpr size_t Capacity = 4096;
    static void notify(D3D12DepthStencilObserver* observer, const View& view) {
        if (observer) observer->on_depth_stencil_view_created(view.resource,
            view.has_desc ? &view.desc : nullptr, view.descriptor);
    }
public:
    void attach(std::atomic<D3D12DepthStencilObserver*>& current, D3D12DepthStencilObserver* next) {
        std::scoped_lock lock{mutex};
        auto* previous = current.exchange(next, std::memory_order_acq_rel);
        if (!next || next == previous || !next->accepts_cached_dsv_metadata()) return;
        for (const auto handle : order) notify(next, views.at(handle).view);
    }
    void publish(std::atomic<D3D12DepthStencilObserver*>& current, ID3D12Resource* resource,
        const D3D12_DEPTH_STENCIL_VIEW_DESC* desc, D3D12_CPU_DESCRIPTOR_HANDLE descriptor) {
        if (!descriptor.ptr) return;
        View view{}; view.resource = resource; view.descriptor = descriptor;
        if (desc) { view.desc = *desc; view.has_desc = true; }
        std::scoped_lock lock{mutex};
        if (auto found = views.find(descriptor.ptr); found != views.end()) {
            found->second.view = view;
            order.splice(order.end(), order, found->second.recency);
            found->second.recency = std::prev(order.end());
        } else {
            if (views.size() >= Capacity) { views.erase(order.front()); order.pop_front(); }
            order.push_back(descriptor.ptr);
            views.emplace(descriptor.ptr, Entry{view, std::prev(order.end())});
        }
        notify(current.load(std::memory_order_acquire), view);
    }
};
}

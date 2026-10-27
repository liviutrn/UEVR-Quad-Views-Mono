#pragma once
#include <hooks/D3D12DepthStencilObserver.hpp>
#include <algorithm>
#include <memory>
#include <mutex>
#include <vector>

namespace stock_dibr {
// Submission/reset retirement remains connected after the capture observer is
// disabled. Shared ownership covers mode exits while RHI lists are pending.
class DepthRetirementHub {
    struct Entry { std::shared_ptr<D3D12DepthStencilObserver> observer; bool armed{}; };
    std::mutex mutex;
    std::vector<Entry> entries;
    static DepthRetirementHub& instance() {
        // Outlives hook/component recreation. Unprovable GPU work is retained
        // rather than freed during teardown; normal retired work is collected.
        static auto* hub = new DepthRetirementHub;
        return *hub;
    }
    static auto snapshot(D3D12DepthStencilObserver* skip) {
        auto& hub = instance();
        std::scoped_lock lock{hub.mutex};
        std::vector<std::shared_ptr<D3D12DepthStencilObserver>> result;
        for (const auto& entry : hub.entries) if (entry.observer.get() != skip) result.push_back(entry.observer);
        return result;
    }
public:
    static void arm(std::shared_ptr<D3D12DepthStencilObserver> observer) {
        if (!observer) return;
        auto& hub = instance();
        std::scoped_lock lock{hub.mutex};
        for (auto& entry : hub.entries) if (entry.observer == observer) { entry.armed = true; return; }
        hub.entries.push_back({std::move(observer), true});
    }
    static void disarm(const std::shared_ptr<D3D12DepthStencilObserver>& observer) {
        auto& hub = instance();
        {
            std::scoped_lock lock{hub.mutex};
            for (auto& entry : hub.entries) if (entry.observer == observer) entry.armed = false;
        }
        collect();
    }
    static void collect() {
        auto& hub = instance();
        std::scoped_lock lock{hub.mutex};
        std::erase_if(hub.entries, [](const Entry& entry) {
            return !entry.armed && !entry.observer->has_pending_retirement();
        });
    }
    static void submitted(D3D12DepthStencilObserver* active, ID3D12CommandQueue* queue,
        UINT count, ID3D12CommandList* const* lists) {
        for (const auto& observer : snapshot(active)) if (observer.get() != active)
            observer->on_command_lists_executed(queue, count, lists);
        collect();
    }
    static void reset_list(D3D12DepthStencilObserver* active, ID3D12GraphicsCommandList* list) {
        for (const auto& observer : snapshot(active)) if (observer.get() != active)
            observer->on_command_list_reset(list);
        collect();
    }
};
}

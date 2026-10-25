#pragma once
#include <windows.h>
#include <d3d12.h>
#include <wrl/client.h>
#include <mutex>
#include <shared_mutex>
#include <unordered_map>

namespace stock_dibr {
// The temporary setup queue does not establish coverage of live queue
// interfaces. Each slot has its own original; forwarding metadata outlives
// hook instances so an already-entered detour can still forward during unhook.
class QueueSubmitHook final {
public:
    using Callback = void (WINAPI *)(ID3D12CommandQueue*, UINT, ID3D12CommandList* const*);
private:
    struct Registry {
        std::shared_mutex activity;
        std::shared_mutex metadata;
        std::unordered_map<void**, Callback> originals;
        QueueSubmitHook* owner{};
        Callback callback{};
    };
    static Registry& registry() { static Registry state; return state; }
    std::unordered_map<void**, Microsoft::WRL::ComPtr<ID3D12CommandQueue>> slots;
    Callback callback{};
    inline static thread_local unsigned forwarding_depth{};

    static void WINAPI execute(ID3D12CommandQueue* queue, UINT count, ID3D12CommandList* const* lists) {
        auto& state = registry();
        const bool outer = forwarding_depth == 0;
        // clear() drains all outer calls, including their observer callbacks.
        // Nested proxy forwarding uses its outer call's activity lock.
        std::shared_lock<std::shared_mutex> activity;
        if (outer) activity = std::shared_lock{state.activity};
        Callback original{};
        {
            std::shared_lock lock{state.metadata};
            const auto found = state.originals.find(&(*(void***)queue)[10]);
            if (found != state.originals.end()) original = found->second;
        }
        // Every installed slot publishes its original before this function is
        // callable. Originals remain available after the slot is restored.
        if (!original) return;
        struct ForwardingScope {
            ForwardingScope() { ++forwarding_depth; }
            ~ForwardingScope() { --forwarding_depth; }
        } scope;
        original(queue, count, lists);
        if (outer && state.callback) state.callback(queue, count, lists);
    }
public:
    explicit QueueSubmitHook(Callback fn) : callback{fn} {}
    QueueSubmitHook(const QueueSubmitHook&) = delete;
    QueueSubmitHook& operator=(const QueueSubmitHook&) = delete;
    ~QueueSubmitHook() { clear(); }

    bool install(ID3D12CommandQueue* queue) {
        if (!queue) return false;
        auto& state = registry();
        std::unique_lock activity{state.activity};
        if (state.owner && state.owner != this) return false;
        auto* slot = &(*(void***)queue)[10];
        if (slots.contains(slot)) return true;
        DWORD protection{};
        if (!VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &protection)) return false;
        const auto original = reinterpret_cast<Callback>(*slot);
        if (!original || original == &execute) {
            DWORD ignored{}; VirtualProtect(slot, sizeof(void*), protection, &ignored);
            return false;
        }
        {
            std::unique_lock metadata{state.metadata};
            state.originals.insert_or_assign(slot, original);
        }
        slots.emplace(slot, queue);
        state.owner = this; state.callback = callback;
        InterlockedExchangePointer(reinterpret_cast<void* volatile*>(slot), reinterpret_cast<void*>(&execute));
        DWORD ignored{}; VirtualProtect(slot, sizeof(void*), protection, &ignored);
        return true;
    }
    size_t size() const { std::shared_lock lock{registry().activity}; return slots.size(); }
    void clear() {
        auto& state = registry();
        std::unique_lock activity{state.activity};
        if (state.owner != this) return;
        for (const auto& [slot, owner] : slots) {
            (void)owner;
            Callback original{};
            { std::shared_lock metadata{state.metadata}; original = state.originals.at(slot); }
            DWORD protection{};
            if (*slot == reinterpret_cast<void*>(&execute) &&
                VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &protection)) {
                InterlockedExchangePointer(reinterpret_cast<void* volatile*>(slot), reinterpret_cast<void*>(original));
                DWORD ignored{}; VirtualProtect(slot, sizeof(void*), protection, &ignored);
            }
        }
        state.callback = nullptr; state.owner = nullptr;
        slots.clear();
        // Do not clear originals: a CPU thread may have read the old vtable
        // target immediately before restoration, then enter after this drain.
        // It must forward, with no access to the retired hook/observer object.
    }
};
}

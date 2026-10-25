#pragma once
#include <windows.h>
#include <d3d12.h>
#include <wrl/client.h>
#include <mutex>
#include <shared_mutex>
#include <unordered_map>
#include <utility>

namespace stock_dibr {
// NVIDIA Streamline's documented QueryInterface route for third-party
// overlays to obtain an underlying native interface without linking its SDK.
inline constexpr GUID StreamlineNativeInterface{
    0xadec44e2, 0x61f0, 0x45c3, {0xad, 0x9f, 0x1b, 0x37, 0x37, 0x92, 0x84, 0xff}};
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
    inline static thread_local bool notifying{};

    static void WINAPI execute(ID3D12CommandQueue* queue, UINT count, ID3D12CommandList* const* lists) {
        auto& state = registry();
        Callback original{};
        {
            std::shared_lock lock{state.metadata};
            const auto found = state.originals.find(&(*(void***)queue)[10]);
            if (found != state.originals.end()) original = found->second;
        }
        // Every installed slot publishes its original before this function is
        // callable. Originals remain available after the slot is restored.
        if (!original) return;
        original(queue, count, lists);
        // Observe every forwarding layer: a proxy can replace the list array,
        // and only the native layer may match the recorded COM identities.
        // Matching slots become non-pending, so later outer callbacks cannot
        // publish the same capture twice. Drain observer calls during clear,
        // without holding an activity lock across arbitrary driver/proxy code.
        // Our observer signals fences. If a driver implements that using a
        // private nested Execute call, forward it without reentering the
        // observer's capture mutex. Ordinary proxy forwarding remains visible.
        if (notifying) return;
        std::shared_lock activity{state.activity};
        if (state.callback) {
            struct NotifyScope {
                NotifyScope() { notifying = true; }
                ~NotifyScope() { notifying = false; }
            } scope;
            state.callback(queue, count, lists);
        }
    }
    bool install_slot(ID3D12CommandQueue* queue) {
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
public:
    explicit QueueSubmitHook(Callback fn) : callback{fn} {}
    QueueSubmitHook(const QueueSubmitHook&) = delete;
    QueueSubmitHook& operator=(const QueueSubmitHook&) = delete;
    ~QueueSubmitHook() { clear(); }

    bool install(ID3D12CommandQueue* queue) {
        Microsoft::WRL::ComPtr<ID3D12CommandQueue> current{queue};
        ID3D12CommandQueue* visited[8]{};
        for (size_t depth = 0; current && depth < 8; ++depth) {
            for (size_t i = 0; i < depth; ++i) if (visited[i] == current.Get()) return true;
            visited[depth] = current.Get();
            if (!install_slot(current.Get())) return false;
            Microsoft::WRL::ComPtr<IUnknown> native;
            if (FAILED(current->QueryInterface(StreamlineNativeInterface,
                reinterpret_cast<void**>(native.GetAddressOf()))) || !native) return true;
            Microsoft::WRL::ComPtr<ID3D12CommandQueue> native_queue;
            if (FAILED(native.As(&native_queue))) return true;
            current = std::move(native_queue);
        }
        return queue != nullptr;
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

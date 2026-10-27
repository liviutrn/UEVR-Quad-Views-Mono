#include <windows.h>
#include <d3d12.h>
#include <hooks/QueueSubmitHook.hpp>
#include <hooks/DsvMetadataCache.hpp>
#include <hooks/DepthRetirementHub.hpp>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <iostream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>
using namespace std::chrono_literals;
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }

struct ReplayObserver : D3D12DepthStencilObserver {
    std::mutex mutex;
    std::condition_variable cv;
    bool entered{}, release{}, block{true}, pending{true};
    std::vector<ID3D12Resource*> delivered;
    bool accepts_cached_dsv_metadata() const override { return true; }
    bool has_pending_retirement() override { return pending; }
    void on_resource_barriers(ID3D12GraphicsCommandList*, UINT, const D3D12_RESOURCE_BARRIER*) override {}
    void on_command_list_reset(ID3D12GraphicsCommandList*) override { pending = false; }
    void on_depth_stencil_view_created(ID3D12Resource* resource, const D3D12_DEPTH_STENCIL_VIEW_DESC*,
        D3D12_CPU_DESCRIPTOR_HANDLE) override {
        std::unique_lock lock{mutex};
        if (block) { entered = true; cv.notify_all(); cv.wait(lock, [&] { return release; }); block = false; }
        delivered.push_back(resource);
    }
};

std::mutex test_mutex;
std::condition_variable test_cv;
bool a_entered{}, release_a{};
std::vector<std::pair<ID3D12CommandQueue*, uintptr_t>> enqueued, observed;
constexpr uintptr_t TagA = 1, TagB = 2, TagC = 3;
void WINAPI observe(ID3D12CommandQueue* q, UINT count, ID3D12CommandList* const* lists) {
    std::scoped_lock lock{test_mutex};
    if (count) observed.emplace_back(q, reinterpret_cast<uintptr_t>(lists[0]));
}
class FakeQueue : public ID3D12CommandQueue {
    std::atomic<ULONG> refs{1};
public:
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** out) override {
        if (!out) return E_POINTER; *out = nullptr;
        if (iid == __uuidof(IUnknown) || iid == __uuidof(ID3D12Object) ||
            iid == __uuidof(ID3D12DeviceChild) || iid == __uuidof(ID3D12Pageable) || iid == __uuidof(ID3D12CommandQueue)) {
            *out = static_cast<ID3D12CommandQueue*>(this); AddRef(); return S_OK;
        }
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
    ULONG STDMETHODCALLTYPE Release() override { return --refs; }
    HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID, UINT*, void*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID, UINT, const void*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID, const IUnknown*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE SetName(LPCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE GetDevice(REFIID, void**) override { return E_NOTIMPL; }
    void STDMETHODCALLTYPE UpdateTileMappings(ID3D12Resource*, UINT, const D3D12_TILED_RESOURCE_COORDINATE*,
        const D3D12_TILE_REGION_SIZE*, ID3D12Heap*, UINT, const D3D12_TILE_RANGE_FLAGS*, const UINT*, const UINT*, D3D12_TILE_MAPPING_FLAGS) override {}
    void STDMETHODCALLTYPE CopyTileMappings(ID3D12Resource*, const D3D12_TILED_RESOURCE_COORDINATE*, ID3D12Resource*,
        const D3D12_TILED_RESOURCE_COORDINATE*, const D3D12_TILE_REGION_SIZE*, D3D12_TILE_MAPPING_FLAGS) override {}
    void STDMETHODCALLTYPE ExecuteCommandLists(UINT count, ID3D12CommandList* const* lists) override {
        std::unique_lock lock{test_mutex};
        const auto tag = count ? reinterpret_cast<uintptr_t>(lists[0]) : 0;
        enqueued.emplace_back(this, tag);
        if (tag == TagA) { a_entered = true; test_cv.notify_all(); test_cv.wait(lock, [] { return release_a; }); }
    }
    void STDMETHODCALLTYPE SetMarker(UINT, const void*, UINT) override {}
    void STDMETHODCALLTYPE BeginEvent(UINT, const void*, UINT) override {}
    void STDMETHODCALLTYPE EndEvent() override {}
    HRESULT STDMETHODCALLTYPE Signal(ID3D12Fence*, UINT64) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE Wait(ID3D12Fence*, UINT64) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE GetTimestampFrequency(UINT64*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetClockCalibration(UINT64*, UINT64*) override { return E_NOTIMPL; }
    D3D12_COMMAND_QUEUE_DESC STDMETHODCALLTYPE GetDesc() override { D3D12_COMMAND_QUEUE_DESC d{}; d.Type = D3D12_COMMAND_LIST_TYPE_DIRECT; return d; }
};
void submit(ID3D12CommandQueue* q, uintptr_t tag) {
    auto* list = reinterpret_cast<ID3D12CommandList*>(tag); // opaque mock payload; never dereferenced
    auto fn = reinterpret_cast<stock_dibr::QueueSubmitHook::Callback>((*(void***)q)[10]);
    fn(q, 1, &list);
}

int main() try {
    stock_dibr::DsvMetadataCache cache;
    std::atomic<D3D12DepthStencilObserver*> active{};
    auto observer = std::make_shared<ReplayObserver>();
    auto* old_resource = reinterpret_cast<ID3D12Resource*>(uintptr_t{16});
    auto* new_resource = reinterpret_cast<ID3D12Resource*>(uintptr_t{32});
    D3D12_CPU_DESCRIPTOR_HANDLE handle{64};
    cache.publish(active, old_resource, nullptr, handle);
    std::thread replay([&] { cache.attach(active, observer.get()); });
    {
        std::unique_lock lock{observer->mutex};
        require(observer->cv.wait_for(lock, 5s, [&] { return observer->entered; }), "cached replay did not enter");
    }
    std::thread update([&] { cache.publish(active, new_resource, nullptr, handle); });
    {
        std::scoped_lock lock{observer->mutex}; observer->release = true; observer->cv.notify_all();
    }
    replay.join(); update.join();
    require(observer->delivered == std::vector<ID3D12Resource*>{old_resource, new_resource}, "stale cache replay overwrote live descriptor metadata");
    cache.attach(active, nullptr);
    std::weak_ptr<ReplayObserver> weak = observer;
    stock_dibr::DepthRetirementHub::arm(observer);
    stock_dibr::DepthRetirementHub::disarm(observer);
    observer.reset();
    require(!weak.expired(), "pending observer lost on mode detach");
    stock_dibr::DepthRetirementHub::reset_list(nullptr, nullptr);
    require(weak.expired(), "retired observer leaked after late list reset");

    FakeQueue first, second;
    stock_dibr::QueueSubmitHook hook{&observe};
    require(hook.install(&first), "queue hook install failed");
    std::thread a([&] { submit(&first, TagA); });
    {
        std::unique_lock lock{test_mutex};
        require(test_cv.wait_for(lock, 5s, [] { return a_entered; }), "original enqueue A did not enter");
    }
    std::atomic<bool> b_started{}, c_done{};
    std::thread b([&] { b_started = true; submit(&first, TagB); });
    std::thread c([&] { submit(&second, TagC); c_done = true; test_cv.notify_all(); });
    bool independent{};
    {
        std::unique_lock lock{test_mutex};
        independent = test_cv.wait_for(lock, 2s, [&] { return c_done.load() && b_started.load(); });
        release_a = true; test_cv.notify_all();
    }
    a.join(); b.join(); c.join();
    require(independent, "one blocked queue stalled an independent queue");
    std::vector<uintptr_t> driver, callbacks;
    for (const auto& [q, tag] : enqueued) if (q == &first) driver.push_back(tag);
    for (const auto& [q, tag] : observed) if (q == &first) callbacks.push_back(tag);
    require(driver == std::vector<uintptr_t>{TagA, TagB}, "mock enqueue ordering invalid");
    require(callbacks == driver, "observer order differs from real queue enqueue order");
    hook.clear();
    std::cout << "PASS: serialized cached/live DSV metadata; detached pending retirement and collection; per-queue enqueue/callback order; independent queues remain concurrent\n";
} catch (const std::exception& e) { std::cerr << "FAIL: " << e.what() << '\n'; return 1; }

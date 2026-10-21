#!/usr/bin/env python3
"""Fence-retire Native Stereo Fix source targets after Unreal GPU use."""
from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Native retirement expected one anchor, found {count}: {old[:120]!r}")
    return text.replace(old, new, 1)


OWNER_IMPL = r'''struct VRRenderTargetManager_Base::QuadViewNativeTargetOwner {
    inline static std::atomic_bool servicing_enabled{};
    sdk::UObjectReference<sdk::UTexture> texture{nullptr};
    sdk::FRenderTarget* render_target{};
    uintptr_t original_vtable_address{};
    std::array<uintptr_t,100> original_vtable{};
    std::array<uintptr_t,100> hooked_vtable{};
    Microsoft::WRL::ComPtr<ID3D12Resource> native_resource{};
    bool rooted{}, gamma_hooked{};
    QuadViewNativeTargetOwner* next_retired{};
    Microsoft::WRL::ComPtr<ID3D12Fence> retire_fence{};
    uint64_t retire_fence_value{};

    struct RetireQueue {
        std::mutex mutex{};
        QuadViewNativeTargetOwner *pending_head{}, *pending_tail{};
        QuadViewNativeTargetOwner *staged_head{}, *staged_tail{};
        QuadViewNativeTargetOwner* in_flight_head{};
        QuadViewNativeTargetOwner *ready_head{}, *ready_tail{};
        Microsoft::WRL::ComPtr<ID3D12Device> signal_device{};
        Microsoft::WRL::ComPtr<ID3D12Fence> signal_fence{};
        uint64_t next_fence_value{};
    };
    static RetireQueue& retire_queue() { static auto* queue=new RetireQueue{}; return *queue; }

    static void append(QuadViewNativeTargetOwner*& head, QuadViewNativeTargetOwner*& tail,
                       QuadViewNativeTargetOwner* owner) noexcept {
        if (!owner) return;
        owner->next_retired=nullptr;
        if (tail) tail->next_retired=owner; else head=owner;
        tail=owner;
    }
    static void append_list(QuadViewNativeTargetOwner*& head, QuadViewNativeTargetOwner*& tail,
                            QuadViewNativeTargetOwner* list_head,
                            QuadViewNativeTargetOwner* list_tail) noexcept {
        if (!list_head) return;
        if (tail) tail->next_retired=list_head; else head=list_head;
        tail=list_tail;
    }
    static void retire(QuadViewNativeTargetOwner* owner) noexcept {
        const bool unrendered=!owner->native_resource && !owner->gamma_hooked;
        try {
            auto& queue=retire_queue();
            std::scoped_lock lock{queue.mutex};
            if (unrendered)
                append(queue.ready_head,queue.ready_tail,owner);
            else
                append(queue.pending_head,queue.pending_tail,owner);
        } catch (...) {
            // The object and its UTexture remain rooted if retirement bookkeeping fails.
        }
        if (unrendered) {
            try { GameThreadWorker::get().enqueue([] { QuadViewNativeTargetOwner::drain_retired(); }); }
            catch (...) { /* A later GT target service drains unrendered owners. */ }
        }
    }

    static void drain_retired() {
        auto& queue=retire_queue();
        QuadViewNativeTargetOwner* head{};
        {
            std::scoped_lock lock{queue.mutex};
            head=std::exchange(queue.ready_head,nullptr);
            queue.ready_tail=nullptr;
        }
        while (head) {
            auto* owner=head;
            head=owner->next_retired;
            owner->next_retired=nullptr;
            bool safe_to_delete=true;
            try {
                if (owner->gamma_hooked) {
                    uintptr_t live_vtable{};
                    const auto address=reinterpret_cast<uintptr_t>(owner->render_target);
                    if (!owner->render_target || !is_writable_process_range(address,sizeof(uintptr_t)) ||
                        !safe_read_value(address,live_vtable)) {
                        safe_to_delete=false;
                    } else if (live_vtable==reinterpret_cast<uintptr_t>(owner->hooked_vtable.data())) {
                        *reinterpret_cast<uintptr_t*>(owner->render_target)=owner->original_vtable_address;
                        owner->gamma_hooked=false;
                    } else if (live_vtable==owner->original_vtable_address) {
                        owner->gamma_hooked=false;
                    } else {
                        // Do not free our hook table if another owner changed this vtable.
                        safe_to_delete=false;
                    }
                }
                if (safe_to_delete && owner->rooted) {
                    if (!owner->texture.valid()) {
                        safe_to_delete=false;
                    } else {
                        unroot_dedicated_ui_texture(owner->texture.get());
                        owner->rooted=false;
                    }
                }
            } catch (...) {
                safe_to_delete=false;
                SPDLOG_WARNING_EVERY_N_SEC(5,"[QuadViews][NativeFix] Could not retire a fenced source target safely");
            }
            if (safe_to_delete) {
                owner->native_resource.Reset();
                delete owner;
            } else {
                try {
                    std::scoped_lock lock{queue.mutex};
                    append(queue.ready_head,queue.ready_tail,owner);
                } catch (...) {
                    // Leave the still-rooted owner allocated if the retry list cannot grow.
                }
            }
        }
    }

    static void service_after_present(ID3D12CommandQueue* command_queue) noexcept {
        auto& queue=retire_queue();
        bool queue_game_thread_drain{};
        try {
            std::scoped_lock lock{queue.mutex};

            auto** link=&queue.in_flight_head;
            while (*link) {
                auto* owner=*link;
                const auto completed=owner->retire_fence ? owner->retire_fence->GetCompletedValue() : 0;
                if (owner->retire_fence && completed!=UINT64_MAX && completed>=owner->retire_fence_value) {
                    *link=owner->next_retired;
                    owner->next_retired=nullptr;
                    owner->retire_fence.Reset();
                    owner->retire_fence_value=0;
                    append(queue.ready_head,queue.ready_tail,owner);
                    queue_game_thread_drain=true;
                } else {
                    link=&owner->next_retired;
                }
            }

            Microsoft::WRL::ComPtr<ID3D12Device> queue_device{};
            if (command_queue && SUCCEEDED(command_queue->GetDevice(IID_PPV_ARGS(&queue_device))) && queue_device) {
                QuadViewNativeTargetOwner *signal_head{}, *signal_tail{};
                auto** staged_link=&queue.staged_head;
                queue.staged_tail=nullptr;
                while (*staged_link) {
                    auto* owner=*staged_link;
                    Microsoft::WRL::ComPtr<ID3D12Device> owner_device{};
                    const bool same_device=owner->native_resource &&
                        SUCCEEDED(owner->native_resource->GetDevice(IID_PPV_ARGS(&owner_device))) &&
                        owner_device.Get()==queue_device.Get();
                    if (same_device) {
                        *staged_link=owner->next_retired;
                        owner->next_retired=nullptr;
                        append(signal_head,signal_tail,owner);
                    } else {
                        queue.staged_tail=owner;
                        staged_link=&owner->next_retired;
                    }
                }

                if (signal_head) {
                    if (!queue.signal_fence || queue.signal_device.Get()!=queue_device.Get()) {
                        Microsoft::WRL::ComPtr<ID3D12Fence> new_fence{};
                        if (SUCCEEDED(queue_device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&new_fence))) && new_fence) {
                            queue.signal_device=queue_device;
                            queue.signal_fence=std::move(new_fence);
                            queue.next_fence_value=0;
                        }
                    }
                    const auto value=queue.next_fence_value+1;
                    if (queue.signal_fence && queue.signal_device.Get()==queue_device.Get() &&
                        SUCCEEDED(command_queue->Signal(queue.signal_fence.Get(),value))) {
                        for (auto* owner=signal_head; owner; owner=owner->next_retired) {
                            owner->retire_fence=queue.signal_fence;
                            owner->retire_fence_value=value;
                        }
                        QuadViewNativeTargetOwner* flight_tail=signal_head;
                        while (flight_tail && flight_tail->next_retired) flight_tail=flight_tail->next_retired;
                        if (flight_tail) {
                            flight_tail->next_retired=queue.in_flight_head;
                            queue.in_flight_head=signal_head;
                        }
                        queue.next_fence_value=value;
                    } else {
                        QuadViewNativeTargetOwner* staged_tail=signal_head;
                        while (staged_tail && staged_tail->next_retired) staged_tail=staged_tail->next_retired;
                        append_list(queue.staged_head,queue.staged_tail,signal_head,staged_tail);
                    }
                }
            }

            // Owners are staged only after this present. The following present
            // queues the fence after Unreal's complete intervening GPU work.
            append_list(queue.staged_head,queue.staged_tail,queue.pending_head,queue.pending_tail);
            queue.pending_head=nullptr;
            queue.pending_tail=nullptr;
        } catch (...) {
            // Keep owners in their current rooted stage; no failure releases GPU resources.
        }
        if (queue_game_thread_drain) {
            try { GameThreadWorker::get().enqueue([] { QuadViewNativeTargetOwner::drain_retired(); }); }
            catch (...) { /* The next GT target service drains the completed list. */ }
        }
    }
};'''


def main() -> None:
    root = Path(sys.argv[1])
    hp = root / "src/mods/vr/FFakeStereoRenderingHook.hpp"
    cp = root / "src/mods/vr/FFakeStereoRenderingHook.cpp"
    dp = root / "src/mods/vr/D3D12Component.cpp"
    h, s, d = hp.read_text(), cp.read_text(), dp.read_text()

    if "QuadViewNativeDelivery.hpp" not in h or "quadview_native_delivery" not in h:
        raise RuntimeError("Run native retirement after the NativeDelivery overlay")
    if "service_quadview_native_target_retirements_after_present" in s or "service_quadview_native_target_retirements_after_present" in d:
        raise RuntimeError("Native target retirement overlay already applied")

    owner_start = s.index("struct VRRenderTargetManager_Base::QuadViewNativeTargetOwner {")
    owner_end = s.index("\nstruct VRRenderTargetManager_Base::QuadViewNativeTargetBuild {", owner_start)
    s = s[:owner_start] + OWNER_IMPL + s[owner_end:]

    h = replace_once(
        h,
        "    void retire_quadview_native_target_set();",
        "    void retire_quadview_native_target_set();\n"
        "    void service_quadview_native_target_retirements_after_present(ID3D12CommandQueue* command_queue);",
    )
    s = replace_once(
        s,
        "            chains[i]=*validated;",
        "            chains[i]=*validated;\n            owner->native_resource=validated->native_resource;",
    )
    s = replace_once(
        s,
        "bool VRRenderTargetManager_Base::ensure_quadview_native_target_set(uint32_t width,uint32_t height) {",
        "void VRRenderTargetManager_Base::service_quadview_native_target_retirements_after_present(ID3D12CommandQueue* command_queue) {\n"
        "    QuadViewNativeTargetOwner::service_after_present(command_queue);\n"
        "}\n\n"
        "bool VRRenderTargetManager_Base::ensure_quadview_native_target_set(uint32_t width,uint32_t height) {",
    )

    d = replace_once(
        d,
        "void D3D12Component::on_post_present(VR* vr) {\n    if (vr->is_mono_transition_quiescing()) { return; }",
        "void D3D12Component::on_post_present(VR* vr) {\n"
        "    if (vr != nullptr && g_framework != nullptr) {\n"
        "        const auto& d3d12_hook=g_framework->get_d3d12_hook();\n"
        "        const auto& stereo=vr->get_fake_stereo_hook();\n"
        "        if (d3d12_hook && stereo) {\n"
        "            if (auto* manager=stereo->get_render_target_manager())\n"
        "                manager->service_quadview_native_target_retirements_after_present(d3d12_hook->get_command_queue());\n"
        "        }\n"
        "    }\n"
        "    if (vr->is_mono_transition_quiescing()) { return; }",
    )

    hp.write_text(h)
    cp.write_text(s)
    dp.write_text(d)
    print("Applied fenced Native Stereo Fix target retirement.")


if __name__ == "__main__":
    main()

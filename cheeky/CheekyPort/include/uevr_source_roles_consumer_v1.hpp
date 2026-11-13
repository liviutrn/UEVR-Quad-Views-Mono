#pragma once
// Cheeky consumer of UEVR's immutable C2 V1 roles ABI (contract header unchanged).
// Per-evaluation copy; absent, mismatched or unlisted handles fall back to
// the existing classifier. No UEVR linkage or hard load dependency.
#include <Windows.h>
#include <atomic>
#include <cstdint>
#include <mutex>
#include "uevr_source_roles_v1.h"

namespace cheeky::foveated_dlss {
struct C2RoleDecision {
    bool authoritative{};
    bool transition{};
    std::uint32_t role_mask{};     // Cheeky masks: 1 left/duo fovea, 2 right, 4 periphery
    std::uint32_t method{};        // 6 Duo, 7 Tri
    std::uint64_t generation{};
};
using C2ProviderV1 = int (__cdecl *)(UevrSourceRolesV1*);

inline C2RoleDecision c2_classify_snapshot(
    const UevrSourceRolesV1& s, std::uint64_t handle) noexcept {
    // Fail closed on incompatible layout; do not read unknown appended fields.
    if (s.version != UEVR_SOURCE_ROLES_VERSION ||
        s.struct_size < sizeof(UevrSourceRolesV1) ||
        s.count > 6 || (s.rendering_method != 6 && s.rendering_method != 7))
        return {};
    C2RoleDecision out{};
    out.method = s.rendering_method;
    out.generation = s.layout_generation;
    if (s.transition_in_progress != 0) {
        // Even an unknown handle is held during the producer's layout transition.
        out.authoritative = true;
        out.transition = true;
        return out;
    }
    if (s.count == 0) return {}; // not transitioning: fallback to legacy classifier
    for (std::uint32_t i = 0; i < s.count; ++i) {
        const auto& entry = s.entries[i];
        if (entry.ngx_feature_handle != handle) continue;
        switch (entry.role) {
        case UEVR_ROLE_DUO_FOVEA:
            if (s.rendering_method == 6) out.role_mask = 1; break;
        case UEVR_ROLE_DUO_PERIPHERY:
            if (s.rendering_method == 6) out.role_mask = 4; break;
        case UEVR_ROLE_TRI_FOVEA_LEFT:
            if (s.rendering_method == 7) out.role_mask = 1; break;
        case UEVR_ROLE_TRI_FOVEA_RIGHT:
            if (s.rendering_method == 7) out.role_mask = 2; break;
        case UEVR_ROLE_TRI_PERIPHERY:
            if (s.rendering_method == 7) out.role_mask = 4; break;
        default: break;
        }
        out.authoritative = out.role_mask != 0;
        return out;
    }
    return {}; // unlisted handle: old classifier remains authoritative
}
inline C2RoleDecision c2_query_with_provider(
    C2ProviderV1 provider, std::uint64_t handle) noexcept {
    if (!provider) return {};
    UevrSourceRolesV1 snapshot{};
    snapshot.struct_size = sizeof(snapshot);
    if (provider(&snapshot) == 0) return {};
    return c2_classify_snapshot(snapshot, handle);
}
class C2RoleConsumerV1 {
    std::atomic<C2ProviderV1> provider_{nullptr};
    std::atomic<HMODULE> module_{nullptr};
    std::atomic<ULONGLONG> next_retry_{0};
    std::mutex resolve_mutex_;
    std::atomic<std::uint64_t> used_{0}, fallback_{0}, generation_{0};
    std::atomic<ULONGLONG> next_log_{0};
public:
    C2RoleDecision Query(std::uint64_t feature_handle) noexcept {
        const HMODULE installed = GetModuleHandleW(L"UEVRBackend.dll");
        const HMODULE cached = module_.load(std::memory_order_acquire);
        if (installed != cached) {
            std::lock_guard guard(resolve_mutex_);
            if (module_.load(std::memory_order_relaxed) != installed) {
                provider_.store(nullptr, std::memory_order_release);
                module_.store(installed, std::memory_order_release);
                next_retry_.store(0, std::memory_order_release);
            }
        }
        auto provider = provider_.load(std::memory_order_acquire);
        const auto now = GetTickCount64();
        if (!provider && installed && now >= next_retry_.load(std::memory_order_relaxed)) {
            std::lock_guard guard(resolve_mutex_);
            provider = provider_.load(std::memory_order_relaxed);
            if (!provider && now >= next_retry_.load(std::memory_order_relaxed)) {
                next_retry_.store(now + 5000, std::memory_order_release);
                provider = reinterpret_cast<C2ProviderV1>(
                    GetProcAddress(installed, "UEVR_GetSourceRolesV1"));
                provider_.store(provider, std::memory_order_release);
            }
        }
        const auto decision = c2_query_with_provider(provider, feature_handle);
        if (decision.authoritative) used_.fetch_add(1, std::memory_order_relaxed);
        else fallback_.fetch_add(1, std::memory_order_relaxed);
        if (decision.authoritative) generation_.store(decision.generation, std::memory_order_release);
        return decision;
    }
    bool DueForLog() noexcept {
        const auto now = GetTickCount64();
        auto next = next_log_.load(std::memory_order_relaxed);
        return now >= next && next_log_.compare_exchange_strong(
            next, now + 2000, std::memory_order_acq_rel);
    }
    std::uint64_t Used() const noexcept { return used_.load(std::memory_order_relaxed); }
    std::uint64_t Fallback() const noexcept { return fallback_.load(std::memory_order_relaxed); }
    std::uint64_t Generation() const noexcept { return generation_.load(std::memory_order_relaxed); }
};
inline C2RoleConsumerV1& c2_roles() {
    static C2RoleConsumerV1 consumer;
    return consumer;
}
} // namespace cheeky::foveated_dlss

#pragma once
#include "UevrSourceRolesV1.h"
#include <array>
#include <chrono>
#include <cstring>
#include <mutex>

namespace uevr::contracts {
// Producer side of contract C2. Roles come from DuoView's own requested
// extents; ambiguous sizes are never published.
class SourceRoleTable {
public:
    static SourceRoleTable& self() { static SourceRoleTable table; return table; }

    void note(uint64_t handle, uint32_t role, uint32_t method, uint64_t family,
              uint32_t out_w, uint32_t out_h, uint32_t in_w, uint32_t in_h) {
        if (!handle || role == UEVR_ROLE_UNKNOWN) return;
        const int64_t now = now_ns();
        std::scoped_lock lock(mutex_);
        if (family != family_ || method != method_) {
            family_ = family;
            method_ = method;
            ++layout_generation_;
            transition_ = true;
            count_ = 0;
        }
        expire_locked(now);
        std::size_t index = count_;
        for (std::size_t i = 0; i < count_; ++i)
            if (entries_[i].ngx_feature_handle == handle) { index = i; break; }
        if (index == count_) {
            if (count_ == entries_.size()) return;
            ++count_;
            evaluations_[index] = 0;
        }
        entries_[index] = {handle, role, out_w, out_h, in_w, in_h, 0u};
        seen_ns_[index] = now;
        if (evaluations_[index] < 255u) ++evaluations_[index];
        if (transition_) {
            bool settled = count_ > 0;
            for (std::size_t i = 0; i < count_; ++i) settled = settled && evaluations_[i] >= 2u;
            if (settled) transition_ = false;
        }
        produced_ns_ = now;
    }

    int snapshot(UevrSourceRolesV1* out) {
        if (!out || out->struct_size < sizeof(UevrSourceRolesV1)) return 0;
        const auto size = out->struct_size;
        std::scoped_lock lock(mutex_);
        expire_locked(now_ns());
        std::memset(out, 0, sizeof(UevrSourceRolesV1));
        out->struct_size = size;
        out->version = UEVR_SOURCE_ROLES_VERSION;
        out->rendering_method = method_;
        out->transition_in_progress = transition_ ? 1u : 0u;
        out->layout_generation = layout_generation_;
        out->produced_qpc_ns = static_cast<uint64_t>(produced_ns_);
        out->count = static_cast<uint32_t>(count_);
        for (std::size_t i = 0; i < count_; ++i) out->entries[i] = entries_[i];
        return 1;
    }

private:
    static int64_t now_ns() {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
    }
    void expire_locked(int64_t now) {
        std::size_t kept = 0;
        for (std::size_t i = 0; i < count_; ++i) {
            if (now - seen_ns_[i] > 2'000'000'000ll) continue;
            entries_[kept] = entries_[i];
            seen_ns_[kept] = seen_ns_[i];
            evaluations_[kept] = evaluations_[i];
            ++kept;
        }
        count_ = kept;
    }

    std::mutex mutex_;
    std::array<UevrSourceRoleEntryV1, 6> entries_{};
    std::array<int64_t, 6> seen_ns_{};
    std::array<uint32_t, 6> evaluations_{};
    std::size_t count_{};
    uint64_t family_{};
    uint32_t method_{};
    uint64_t layout_generation_{};
    int64_t produced_ns_{};
    bool transition_{};
};
} // namespace uevr::contracts

#pragma once
// Cheeky NR Batch 2 allocation/reuse predicates shared by production and
// deterministic host tests. All calculations are overflow-safe.
#include <cstdint>

namespace cheeky::foveated_dlss {
inline constexpr std::uint64_t nr_batch2_mib = 1024ULL*1024ULL;
[[nodiscard]] constexpr bool nr_batch2_admit(
    bool valid_dxgi, std::uint64_t free_bytes,
    std::uint64_t model_bytes, std::uint64_t guard_bytes) noexcept {
    // The model allocation, estimated conservatively when unmeasured, and
    // user's headroom must BOTH fit before any NGX allocation is attempted.
    return valid_dxgi && model_bytes <= free_bytes &&
           guard_bytes <= free_bytes-model_bytes;
}
[[nodiscard]] constexpr bool nr_batch2_reuse_eligible(
    bool enabled, bool same_role, bool same_family,
    bool same_key, bool same_device, bool gpu_complete,
    std::uint64_t now_ms, std::uint64_t retired_at_ms) noexcept {
    return enabled && same_role && same_family && same_key &&
           same_device && gpu_complete && now_ms >= retired_at_ms &&
           now_ms-retired_at_ms <= 10000ULL;
}
} // namespace cheeky::foveated_dlss

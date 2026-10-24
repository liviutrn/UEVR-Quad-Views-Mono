#pragma once

// CPU-side, owned preview payload and contrast mapping for the manual depth
// picker. The capture path publishes this payload only after its async GPU
// readback fence completes. The ImGui UI never receives a borrowed engine
// resource or an unreferenced GPU handle.
#include "ManualDibrContract.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>

namespace uevr::duoview::dibr {

inline constexpr float kDefaultPreviewLogMinimum = 1.0e-4f;
inline constexpr float kDefaultPreviewLogMaximum = 1.0e-2f;
inline constexpr uint32_t kPreviewWidth = 64;
inline constexpr uint32_t kPreviewHeight = 48;
inline constexpr size_t kPreviewPixelCount = size_t{kPreviewWidth} * kPreviewHeight;
inline constexpr size_t kManualDibrCandidatePageSize = 4;

enum class PreviewAssociation : uint8_t {
    timing_unverified,
    producer_frame_matched,
};

enum class CandidatePreviewStatus : uint8_t {
    unsupported,
    waiting_for_live_capture,
    readback_pending,
    live,
    stale,
    source_changed,
};

// Immutable-after-publication CPU copy of a small raw R32 depth thumbnail.
// Its fixed size bounds both host memory and per-frame ImGui draw work.
struct PreviewPayload {
    CandidateKey key{};
    uint64_t capture_serial{};
    uint64_t producer_generation{};
    uint64_t producer_frame{};
    uint64_t submitted_order{};
    uint64_t completed_ms{};
    // This payload is published only after the private readback fence has
    // completed. Keep both the submission proof and observed completion
    // value with the pixels so the UI can explain their provenance.
    QueueProof queue{};
    uint64_t private_readback_fence_value{};
    uint64_t completed_private_readback_fence_value{};
    uint32_t width{kPreviewWidth};
    uint32_t height{kPreviewHeight};
    PreviewAssociation association{PreviewAssociation::timing_unverified};
    std::array<float, kPreviewPixelCount> raw_depth{};
};

struct CandidatePageWindow {
    size_t first{};
    size_t end{};
    size_t page_index{}; // zero-based
    size_t page_count{};

    constexpr bool has_previous() const noexcept { return page_index > 0; }
    constexpr bool has_next() const noexcept { return page_index + 1 < page_count; }
};

// Page over the complete observed candidate vector. `first` is always
// aligned to a page boundary and clamped to the final non-empty page.
inline constexpr CandidatePageWindow candidate_page_window(
    size_t candidate_count,
    size_t requested_first,
    size_t page_size = kManualDibrCandidatePageSize) noexcept
{
    if (!candidate_count || !page_size) return {};
    const size_t page_count = 1 + (candidate_count - 1) / page_size;
    const size_t last_first = (page_count - 1) * page_size;
    const size_t first = (std::min)(requested_first / page_size * page_size, last_first);
    const size_t end = first + (std::min)(page_size, candidate_count - first);
    return {first, end, first / page_size, page_count};
}

inline bool candidate_can_be_assigned(const Candidate& candidate) noexcept {
    return candidate.capture_supported && candidate.key.id && candidate.key.resource_generation;
}

// Capture publishes only fence-complete owned readbacks, so the CPU payload
// needs no GPU handle or second completion flag. This validates shape and
// identity before pixels are handed to ImGui.
inline bool valid_preview_payload(const PreviewPayload& preview, CandidateKey expected_key) noexcept {
    if (preview.key != expected_key || !preview.capture_serial || !preview.submitted_order ||
        !preview.completed_ms || preview.width != kPreviewWidth || preview.height != kPreviewHeight ||
        !preview.private_readback_fence_value ||
        preview.completed_private_readback_fence_value < preview.private_readback_fence_value ||
        !queue_proven(preview.queue))
        return false;
    switch (preview.association) {
    case PreviewAssociation::timing_unverified:
        return true;
    case PreviewAssociation::producer_frame_matched:
        return preview.producer_generation && preview.producer_frame;
    default:
        return false;
    }
}

inline bool preview_has_verified_producer_frame(
    const PreviewPayload& preview, CandidateKey expected_key) noexcept
{
    return valid_preview_payload(preview, expected_key) &&
        preview.association == PreviewAssociation::producer_frame_matched &&
        preview.producer_generation && preview.producer_frame;
}

inline bool preview_payload_is_displayable(
    CandidatePreviewStatus status,
    const PreviewPayload* preview,
    CandidateKey expected_key) noexcept
{
    if (!preview || !valid_preview_payload(*preview, expected_key)) return false;
    return status == CandidatePreviewStatus::live || status == CandidatePreviewStatus::stale ||
        status == CandidatePreviewStatus::readback_pending;
}

// Reversed-Z is larger for nearer geometry. A logarithmic ramp makes the
// useful 1e-4..1e-2 range visible while keeping the ordering intuitive:
// farther values are dark, nearer values are bright. Values outside the
// selected range clamp for display only; the depth sample itself is untouched.
inline uint8_t reversed_z_preview_gray(
    float depth,
    float log_minimum = kDefaultPreviewLogMinimum,
    float log_maximum = kDefaultPreviewLogMaximum) noexcept
{
    if (!std::isfinite(depth) || depth <= 0.0f) return 0;
    if (!std::isfinite(log_minimum) || !std::isfinite(log_maximum) ||
        log_minimum <= 0.0f || log_maximum <= log_minimum) {
        log_minimum = kDefaultPreviewLogMinimum;
        log_maximum = kDefaultPreviewLogMaximum;
    }
    if (depth <= log_minimum) return 0;
    if (depth >= log_maximum) return 255;

    const float lo = std::log(log_minimum);
    const float hi = std::log(log_maximum);
    const float value = (std::log(depth) - lo) / (hi - lo);
    const float scaled = (std::clamp)(value, 0.0f, 1.0f) * 255.0f;
    return static_cast<uint8_t>(std::lround(scaled));
}

} // namespace uevr::duoview::dibr

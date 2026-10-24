#include "ManualDibrPreview.hpp"

#include <cassert>
#include <cmath>
#include <limits>

using namespace uevr::duoview::dibr;

int main() {
    static_assert(kManualDibrCandidatePageSize == 4);
    constexpr auto empty_page = candidate_page_window(0, 0);
    static_assert(empty_page.first == 0 && empty_page.end == 0 && empty_page.page_count == 0);
    constexpr auto first_page = candidate_page_window(10, 0);
    static_assert(first_page.first == 0 && first_page.end == 4 && first_page.page_index == 0);
    static_assert(first_page.page_count == 3 && !first_page.has_previous() && first_page.has_next());
    constexpr auto middle_page = candidate_page_window(10, 5);
    static_assert(middle_page.first == 4 && middle_page.end == 8 && middle_page.page_index == 1);
    static_assert(middle_page.has_previous() && middle_page.has_next());
    constexpr auto last_page = candidate_page_window(10, 99);
    static_assert(last_page.first == 8 && last_page.end == 10 && last_page.page_index == 2);
    static_assert(last_page.has_previous() && !last_page.has_next());
    constexpr auto exact_page = candidate_page_window(4, 4);
    static_assert(exact_page.first == 0 && exact_page.end == 4 && exact_page.page_count == 1);

    assert(reversed_z_preview_gray(1.0e-4f) == 0);
    assert(reversed_z_preview_gray(1.0e-3f) >= 127);
    assert(reversed_z_preview_gray(1.0e-3f) <= 128);
    assert(reversed_z_preview_gray(1.0e-2f) == 255);
    assert(reversed_z_preview_gray(5.0e-4f) < reversed_z_preview_gray(1.0e-3f));
    assert(reversed_z_preview_gray(1.0e-3f) < reversed_z_preview_gray(2.0e-3f));
    assert(reversed_z_preview_gray(1.0e-6f) == 0);
    assert(reversed_z_preview_gray(1.0f) == 255);
    assert(reversed_z_preview_gray(0.0f) == 0);
    assert(reversed_z_preview_gray(-1.0e-3f) == 0);
    assert(reversed_z_preview_gray(std::numeric_limits<float>::quiet_NaN()) == 0);
    assert(reversed_z_preview_gray(std::numeric_limits<float>::infinity()) == 0);

    // Invalid contrast controls fall back to the documented reversed-Z range.
    assert(reversed_z_preview_gray(1.0e-3f, 0.0f, 0.0f) >= 127);
    assert(reversed_z_preview_gray(1.0e-3f, 0.0f, 0.0f) <= 128);

    PreviewPayload payload{};
    payload.key = {6, 2, 1};
    payload.capture_serial = 9;
    payload.submitted_order = 17;
    payload.completed_ms = 25;
    payload.queue = {QueueRelation::same_queue, 101, 101, 17, 18, 0, 0};
    payload.private_readback_fence_value = 33;
    payload.completed_private_readback_fence_value = 33;
    assert(valid_preview_payload(payload, payload.key));
    assert(!preview_has_verified_producer_frame(payload, payload.key));
    assert(!preview_payload_is_displayable(CandidatePreviewStatus::waiting_for_live_capture,
        &payload, payload.key));
    assert(preview_payload_is_displayable(CandidatePreviewStatus::live, &payload, payload.key));
    // A stale view remains renderable from its last completed, privately owned copy.
    assert(preview_payload_is_displayable(CandidatePreviewStatus::stale, &payload, payload.key));
    assert(preview_payload_is_displayable(CandidatePreviewStatus::readback_pending,
        &payload, payload.key));
    assert(!valid_preview_payload(payload, CandidateKey{7, 2, 1}));
    assert(!preview_payload_is_displayable(CandidatePreviewStatus::stale,
        &payload, CandidateKey{7, 2, 1}));
    payload.capture_serial = 0;
    assert(!valid_preview_payload(payload, payload.key));
    payload.capture_serial = 9;
    payload.width = 32;
    assert(!valid_preview_payload(payload, payload.key));
    payload.width = kPreviewWidth;
    payload.completed_private_readback_fence_value = 32;
    assert(!valid_preview_payload(payload, payload.key));
    payload.completed_private_readback_fence_value = 33;
    payload.queue = {};
    assert(!valid_preview_payload(payload, payload.key));
    payload.queue = {QueueRelation::cross_queue, 101, 202, 17, 18, 41, 40};
    assert(!valid_preview_payload(payload, payload.key));
    payload.queue.consumer_wait = 41;
    assert(valid_preview_payload(payload, payload.key));
    payload.association = PreviewAssociation::producer_frame_matched;
    assert(!valid_preview_payload(payload, payload.key));
    assert(!preview_has_verified_producer_frame(payload, payload.key));
    payload.producer_generation = 4;
    payload.producer_frame = 12;
    assert(valid_preview_payload(payload, payload.key));
    assert(preview_has_verified_producer_frame(payload, payload.key));
    payload.producer_generation = 0;
    assert(!valid_preview_payload(payload, payload.key));
    assert(!preview_has_verified_producer_frame(payload, payload.key));
    payload.producer_generation = 4;
    payload.producer_frame = 0;
    assert(!valid_preview_payload(payload, payload.key));
    assert(!preview_has_verified_producer_frame(payload, payload.key));
    payload.producer_frame = 12;
    payload.association = static_cast<PreviewAssociation>(255);
    assert(!valid_preview_payload(payload, payload.key));

    Candidate candidate{};
    candidate.key = {6, 2, 1};
    candidate.capture_supported = true;
    assert(candidate_can_be_assigned(candidate));
    candidate.capture_supported = false;
    assert(!candidate_can_be_assigned(candidate));
    candidate.capture_supported = true;
    candidate.key.id = 0;
    assert(!candidate_can_be_assigned(candidate));
    candidate.key = {6, 0, 1};
    assert(!candidate_can_be_assigned(candidate));

    return 0;
}

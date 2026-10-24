#include "ManualDibrContract.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>

using namespace uevr::duoview::dibr;

static void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}

static Candidate candidate(CandidateKey key, uint64_t serial = 12) {
    return {key, 344, 276, {0, 0, 344, 276}, 19,
        CaptureStage::depth_write_to_shader_read, true, true, 1234, serial};
}

static OwnedDepthSample sample(CandidateKey key, ProducerKey producer, uint64_t serial = 44) {
    return {key, producer, CaptureStage::depth_write_to_shader_read, serial, 12,
        {key, key.subresource, 0, serial},
        {0, 0, 344, 276}, true, true,
        {QueueRelation::same_queue, 7, 7, 90, 91, 0, 0}};
}

int main() try {
    const CandidateKey full{6, 3, 1}, focus{1, 8, 2};
    RoleAssignments roles{};
    roles.assign_periphery(full);
    roles.assign_fovea(focus);
    require(roles.periphery == full && roles.fovea == focus,
        "Fovea and full-view/periphery assignments must be independent");
    roles.clear_fovea();
    require(roles.periphery == full && !roles.fovea,
        "Clearing the optional fovea choice must preserve the full-view choice");

    const ProducerKey frame{3, 55};
    auto current = candidate(full);
    roles.assign_periphery(full);
    auto live = sample(full, frame);
    require(static_cast<bool>(validate_selected_sample(current, roles, live, frame, 12)),
        "Exact owned current-frame sample on a proven same queue must pass");

    auto stale = live;
    stale.producer.frame--;
    require(validate_selected_sample(current, roles, stale, frame, 12).reason == GateReason::frame_mismatch,
        "Stale depth must not pair with current color");
    stale = live;
    stale.key.resource_generation++;
    require(validate_selected_sample(current, roles, stale, frame, 12).reason == GateReason::source_changed,
        "A changed allocation must invalidate the manual assignment");
    stale = live;
    stale.owned_snapshot = false;
    require(validate_selected_sample(current, roles, stale, frame, 12).reason == GateReason::sample_not_owned,
        "A borrowed resource is never a consumable depth sample");
    stale = live;
    stale.stage = CaptureStage::unknown;
    require(validate_selected_sample(current, roles, stale, frame, 12).reason == GateReason::stage_unverified,
        "Unknown capture stages stay preview-only");
    stale = live;
    stale.resource_update_serial--;
    require(validate_selected_sample(current, roles, stale, frame, 12).reason == GateReason::no_current_sample,
        "A previous update cannot masquerade as current depth");
    stale = live;
    stale.queue = {};
    require(validate_selected_sample(current, roles, stale, frame, 12).reason == GateReason::queue_unproven,
        "Unknown queue lineage must reject stereo");
    stale = live;
    stale.queue.consumer_order = stale.queue.producer_order - 1;
    require(validate_selected_sample(current, roles, stale, frame, 12).reason == GateReason::queue_order_unproven,
        "Same queue without producer-before-consumer order must reject stereo");
    stale = live;
    stale.queue.consumer_order = stale.queue.producer_order;
    require(validate_selected_sample(current, roles, stale, frame, 12).reason == GateReason::queue_order_unproven,
        "Equal producer and consumer order is not a happens-before relationship");
    stale = live;
    stale.copy.owned_subresource = 1;
    require(validate_selected_sample(current, roles, stale, frame, 12).reason == GateReason::sample_not_owned,
        "The adapter can sample only the private snapshot's subresource zero");
    stale = live;
    stale.copy.origin_subresource = 0;
    require(validate_selected_sample(current, roles, stale, frame, 12).reason == GateReason::sample_not_owned,
        "A copy receipt must retain its exact nonzero source slice");

    stale = live;
    stale.queue = {QueueRelation::cross_queue, 7, 9, 0, 0, 30, 29};
    require(validate_selected_sample(current, roles, stale, frame, 12).reason == GateReason::consumer_wait_missing,
        "Cross-queue use requires a wait on the producer fence");
    stale.queue.consumer_wait = 30;
    require(static_cast<bool>(validate_selected_sample(current, roles, stale, frame, 12)),
        "Cross-queue use passes only with the exact producer-fence dependency");

    roles.clear_periphery();
    require(validate_selected_sample(current, roles, live, frame, 12).reason == GateReason::choose_full_view_depth,
        "Fovea-only choice cannot be stretched over the full view");
    roles.assign_periphery(full);

    current.capture_supported = false;
    require(validate_selected_sample(current, roles, live, frame, 12).reason == GateReason::unsupported_subresource,
        "Unsupported candidate remains listed but cannot activate");
    current.capture_supported = true;
    stale = live;
    stale.active_rect = {300, 0, 64, 276};
    require(validate_selected_sample(current, roles, stale, frame, 12).reason == GateReason::invalid_rect,
        "Invalid active rectangles must be rejected");

    const auto near = rectified_pixel_disparity(860, 100.0 * 3.141592653589793 / 180.0,
        .064, .5, 2.0);
    const auto convergence = rectified_pixel_disparity(860, 100.0 * 3.141592653589793 / 180.0,
        .064, 2.0, 2.0);
    const auto far = rectified_pixel_disparity(860, 100.0 * 3.141592653589793 / 180.0,
        .064, 10.0, 2.0);
    require(near && convergence && far, "Valid geometry must produce analytic disparity");
    require(std::abs(*near - 34.638) < .01 && std::abs(*convergence) < 1e-9 &&
        std::abs(*far + 9.237) < .01,
        "Near, convergence-plane, and far disparity must match the signed oracle");
    require(!rectified_pixel_disparity(860, 1.0, .064, 0.0, 2.0),
        "Zero/invalid depth must not enter the geometry solve");

    std::array<float, 16> gl_column_major{};
    for (size_t col = 0; col != 4; ++col)
        for (size_t row = 0; row != 4; ++row)
            gl_column_major[col * 4 + row] = static_cast<float>(row * 10 + col);
    const auto hlsl_row_major = column_major_to_row_major(gl_column_major);
    for (size_t row = 0; row != 4; ++row)
        for (size_t col = 0; col != 4; ++col)
            require(hlsl_row_major[row * 4 + col] == static_cast<float>(row * 10 + col),
                "Frozen GLM column-major projection must transpose for row-major HLSL upload");

    SnapshotRing<2> ring;
    auto slot0 = ring.reserve(frame, 1);
    auto slot1 = ring.reserve({3, 56}, 2);
    require(slot0 && slot1 && *slot0 != *slot1, "The bounded ring should allocate distinct slots");
    require(!ring.reserve({3, 57}, 3), "A full bounded ring must refuse allocation instead of overwrite");
    require(ring.submitted(*slot0, 7, 100) && ring.submitted(*slot1, 7, 101),
        "Only recorded slots with a real queue/fence may submit");
    require(!ring.gpu_complete(*slot0, 7, 99), "A slot cannot retire before its fence completes");
    require(ring.hold_cpu(*slot0) && ring.gpu_complete(*slot0, 7, 100),
        "A packet hold must span GPU completion and preserve slot ownership");
    require(!ring.reserve({3, 57}, 3), "A CPU-held completed packet still owns its slot");
    require(ring.release_cpu(*slot0), "The retained packet should release its slot");
    auto slot2 = ring.reserve({3, 57}, 3);
    require(slot2 && *slot2 == *slot0, "Only a fully retired slot may be reused");

    OutputTelemetry telemetry{};
    telemetry.requested = true;
    telemetry.path = OutputPath::mono_fallback;
    telemetry.reason = GateReason::frame_mismatch;
    telemetry.source = frame;
    telemetry.depth_candidate = full.id;
    telemetry.submitted_serial = frame.frame;
    require(telemetry.requested && telemetry.path == OutputPath::mono_fallback &&
        telemetry.reason == GateReason::frame_mismatch && telemetry.depth_candidate == 6,
        "Telemetry must distinguish a requested mode from the actual fallback output");

    std::cout << "manual depth assignments, frame/queue gates, retirement, and disparity oracle: PASS\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr << e.what() << '\n';
    return 1;
}

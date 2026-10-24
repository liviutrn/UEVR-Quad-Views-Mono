#pragma once

// Portable contracts for manual depth selection and current-frame stereo.
// This header contains no D3D12/UE types so CI can test the safety gates on
// every platform before the Windows GPU adapter consumes the same metadata.
#include "../DuoViewGeometry.hpp"
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <mutex>

namespace uevr::duoview::dibr {

struct ProducerKey {
    uint64_t generation{};
    uint64_t frame{};
    constexpr bool operator==(const ProducerKey&) const = default;
};

// DuoView's frozen projection is stored in the column-major order used by
// GLM. The production HLSL cbuffer declares row_major matrices and uses
// mul(M, vector), so upload the same mathematical matrix in row-major memory.
inline std::array<float, 16> column_major_to_row_major(const std::array<float, 16>& matrix) {
    std::array<float, 16> result{};
    for (size_t row = 0; row != 4; ++row)
        for (size_t column = 0; column != 4; ++column)
            result[row * 4 + column] = matrix[column * 4 + row];
    return result;
}

struct CandidateKey {
    uint64_t id{};                 // session-local identity; never a pointer
    uint64_t resource_generation{};
    uint32_t subresource{};
    constexpr bool operator==(const CandidateKey&) const = default;
};

enum class CaptureStage : uint8_t {
    unknown,
    depth_write_to_shader_read,
    upscaler_input,
    engine_pass,
};

enum class QueueRelation : uint8_t { unknown, same_queue, cross_queue };

struct QueueProof {
    QueueRelation relation{QueueRelation::unknown};
    uint64_t producer_queue{};
    uint64_t consumer_queue{};
    uint64_t producer_order{};
    uint64_t consumer_order{};
    uint64_t producer_fence{};
    uint64_t consumer_wait{};
};

struct Candidate {
    CandidateKey key{};
    uint32_t width{}, height{};
    Rect active_rect{};
    uint32_t format{};
    CaptureStage stage{CaptureStage::unknown};
    bool preview_supported{};
    bool capture_supported{};
    uint64_t last_update_ms{};
    uint64_t update_serial{};
};

// A copy is consumable only when the owned single-slice snapshot is tied to
// the exact source candidate/subresource that was copied. The original
// subresource may be nonzero (for example an array slice); owned_subresource
// is always zero in the adapter's private 2D texture.
struct CopyReceipt {
    CandidateKey origin_key{};
    uint32_t origin_subresource{};
    uint32_t owned_subresource{};
    uint64_t capture_serial{};
    constexpr bool valid() const {
        return origin_key.id && origin_key.resource_generation && capture_serial &&
            origin_subresource == origin_key.subresource && owned_subresource == 0;
    }
};

struct OwnedDepthSample {
    CandidateKey key{};
    ProducerKey producer{};
    CaptureStage stage{CaptureStage::unknown};
    uint64_t capture_serial{};
    uint64_t resource_update_serial{};
    CopyReceipt copy{};
    Rect active_rect{};
    bool owned_snapshot{};
    bool completion_recorded{};
    QueueProof queue{};
};

struct RoleAssignments {
    std::optional<CandidateKey> periphery{};
    std::optional<CandidateKey> fovea{};

    void assign_periphery(CandidateKey key) { periphery = key; }
    void assign_fovea(CandidateKey key) { fovea = key; }
    void clear_periphery() { periphery.reset(); }
    void clear_fovea() { fovea.reset(); }
};

enum class GateReason : uint8_t {
    ready,
    not_requested,
    choose_full_view_depth,
    source_changed,
    no_current_sample,
    sample_not_owned,
    stage_unverified,
    frame_mismatch,
    producer_generation_mismatch,
    unsupported_subresource,
    queue_unproven,
    queue_order_unproven,
    producer_fence_missing,
    consumer_wait_missing,
    invalid_rect,
};

struct GateResult {
    GateReason reason{GateReason::choose_full_view_depth};
    explicit constexpr operator bool() const { return reason == GateReason::ready; }
};

inline bool rect_valid(Rect r, uint32_t width, uint32_t height) {
    return r.width && r.height && r.x <= width && r.y <= height &&
        uint64_t(r.x) + r.width <= width && uint64_t(r.y) + r.height <= height;
}

inline bool same_rect(Rect a, Rect b) {
    return a.x == b.x && a.y == b.y && a.width == b.width && a.height == b.height;
}

inline bool queue_proven(const QueueProof& q) {
    if (q.relation == QueueRelation::same_queue) {
        return q.producer_queue && q.producer_queue == q.consumer_queue &&
            q.producer_order && q.consumer_order && q.producer_order < q.consumer_order;
    }
    if (q.relation == QueueRelation::cross_queue) {
        return q.producer_queue && q.consumer_queue && q.producer_queue != q.consumer_queue &&
            q.producer_fence && q.consumer_wait >= q.producer_fence;
    }
    return false;
}

inline bool sample_lineage_valid(
    const Candidate& current,
    const OwnedDepthSample& sample,
    ProducerKey consumer,
    uint64_t latest_resource_update_serial)
{
    if (sample.key != current.key) return false;
    if (!sample.owned_snapshot || !sample.completion_recorded || !sample.copy.valid() ||
        sample.copy.capture_serial != sample.capture_serial || !current.capture_supported) return false;
    if (sample.stage == CaptureStage::unknown || sample.stage != current.stage) return false;
    if (sample.resource_update_serial != latest_resource_update_serial ||
        sample.resource_update_serial != current.update_serial) return false;
    if (!sample.producer.generation || !consumer.generation ||
        sample.producer.generation != consumer.generation ||
        !sample.producer.frame || !consumer.frame || sample.producer != consumer) return false;
    if (!rect_valid(sample.active_rect, current.width, current.height) ||
        !same_rect(sample.active_rect, current.active_rect)) return false;
    return queue_proven(sample.queue);
}

inline GateResult validate_owned_sample(
    const Candidate& current,
    const OwnedDepthSample& sample,
    ProducerKey consumer,
    uint64_t latest_resource_update_serial)
{
    if (sample.key != current.key || sample.copy.origin_key != current.key)
        return {GateReason::source_changed};
    if (!sample.owned_snapshot || !sample.completion_recorded || !sample.copy.valid() ||
        sample.copy.capture_serial != sample.capture_serial)
        return {GateReason::sample_not_owned};
    if (!current.capture_supported) return {GateReason::unsupported_subresource};
    if (sample.stage == CaptureStage::unknown || sample.stage != current.stage)
        return {GateReason::stage_unverified};
    if (sample.resource_update_serial != latest_resource_update_serial ||
        sample.resource_update_serial != current.update_serial)
        return {GateReason::no_current_sample};
    if (!sample.producer.generation || !consumer.generation ||
        sample.producer.generation != consumer.generation)
        return {GateReason::producer_generation_mismatch};
    if (!sample.producer.frame || !consumer.frame || sample.producer != consumer)
        return {GateReason::frame_mismatch};
    if (!rect_valid(sample.active_rect, current.width, current.height))
        return {GateReason::invalid_rect};
    if (!same_rect(sample.active_rect, current.active_rect))
        return {GateReason::invalid_rect};
    if (!queue_proven(sample.queue)) {
        if (sample.queue.relation == QueueRelation::cross_queue) {
            if (!sample.queue.producer_fence) return {GateReason::producer_fence_missing};
            if (sample.queue.consumer_wait < sample.queue.producer_fence)
                return {GateReason::consumer_wait_missing};
        }
        if (sample.queue.relation == QueueRelation::same_queue)
            return {GateReason::queue_order_unproven};
        return {GateReason::queue_unproven};
    }
    return {GateReason::ready};
}

inline GateResult validate_selected_sample(
    const Candidate& current,
    const RoleAssignments& selected,
    const OwnedDepthSample& sample,
    ProducerKey consumer,
    uint64_t latest_resource_update_serial)
{
    if (!selected.periphery) return {GateReason::choose_full_view_depth};
    if (*selected.periphery != current.key || sample.key != current.key)
        return {GateReason::source_changed};
    return validate_owned_sample(current, sample, consumer, latest_resource_update_serial);
}

struct Vec3 { double x{}, y{}, z{}; };

// Rectified parallel-camera sanity oracle. Production output uses frozen
// source/target matrices; this formula is for unit/sign and synthetic tests.
inline std::optional<double> rectified_pixel_disparity(
    double output_width,
    double horizontal_fov_radians,
    double baseline_meters,
    double depth_meters,
    double convergence_meters)
{
    if (!std::isfinite(output_width) || !std::isfinite(horizontal_fov_radians) ||
        !std::isfinite(baseline_meters) || !std::isfinite(depth_meters) ||
        !std::isfinite(convergence_meters) || output_width <= 0.0 ||
        horizontal_fov_radians <= 0.0 || horizontal_fov_radians >= 3.13 ||
        baseline_meters < 0.0 || depth_meters <= 0.0 || convergence_meters <= 0.0)
        return {};
    const double focal = output_width / (2.0 * std::tan(horizontal_fov_radians * .5));
    return focal * baseline_meters * (1.0 / depth_meters - 1.0 / convergence_meters);
}

enum class OutputPath : uint8_t { none, mono_fallback, stereo_double_wide };

struct OutputTelemetry {
    bool requested{};
    OutputPath path{OutputPath::none};
    GateReason reason{GateReason::not_requested};
    ProducerKey source{};
    uint64_t depth_candidate{};
    uint64_t submitted_serial{};
    uint64_t eye_left_hash{};
    uint64_t eye_right_hash{};
};

// A bounded ownership ledger mirrored by the DX12 texture ring. A slot does
// not become reusable until both its GPU completion and CPU packet holds have
// retired. The production class attaches the real resource/fence objects to
// the returned slot index.
template <size_t Capacity>
class SnapshotRing {
    static_assert(Capacity > 0);
public:
    enum class State : uint8_t { free, recording, submitted, complete };
    struct SlotView {
        State state{State::free};
        ProducerKey producer{};
        uint64_t capture_serial{};
        uint64_t queue{};
        uint64_t fence{};
        uint32_t cpu_holds{};
    };

    std::optional<size_t> reserve(ProducerKey producer, uint64_t capture_serial) {
        std::scoped_lock lock{mutex_};
        if (!producer.generation || !producer.frame || !capture_serial) return {};
        for (size_t i = 0; i < slots_.size(); ++i) {
            if (slots_[i].state == State::free) {
                slots_[i] = SlotView{State::recording, producer, capture_serial};
                return i;
            }
        }
        return {};
    }

    bool submitted(size_t index, uint64_t queue, uint64_t fence) {
        std::scoped_lock lock{mutex_};
        if (index >= slots_.size() || !queue || !fence ||
            slots_[index].state != State::recording) return false;
        slots_[index].state = State::submitted;
        slots_[index].queue = queue;
        slots_[index].fence = fence;
        return true;
    }

    bool gpu_complete(size_t index, uint64_t queue, uint64_t completed_fence) {
        std::scoped_lock lock{mutex_};
        if (index >= slots_.size()) return false;
        auto& slot = slots_[index];
        if (slot.state != State::submitted || slot.queue != queue ||
            completed_fence < slot.fence) return false;
        slot.state = State::complete;
        maybe_recycle(slot);
        return true;
    }

    bool hold_cpu(size_t index) {
        std::scoped_lock lock{mutex_};
        if (index >= slots_.size() || slots_[index].state == State::free ||
            slots_[index].cpu_holds == UINT32_MAX) return false;
        ++slots_[index].cpu_holds;
        return true;
    }

    bool release_cpu(size_t index) {
        std::scoped_lock lock{mutex_};
        if (index >= slots_.size() || slots_[index].state != State::complete ||
            !slots_[index].cpu_holds) return false;
        --slots_[index].cpu_holds;
        maybe_recycle(slots_[index]);
        return true;
    }

    std::optional<SlotView> inspect(size_t index) const {
        std::scoped_lock lock{mutex_};
        if (index >= slots_.size() || slots_[index].state == State::free) return {};
        return slots_[index];
    }

private:
    static void maybe_recycle(SlotView& slot) {
        if (slot.state == State::complete && !slot.cpu_holds) slot = {};
    }
    mutable std::mutex mutex_{};
    std::array<SlotView, Capacity> slots_{};
};

} // namespace uevr::duoview::dibr

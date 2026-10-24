#pragma once

#include <cstdint>

// Small, XR-type-free contract shared by the manual DIBR OpenXR patch and its
// portable state-flow tests.  `output_ready` means the GPU output was created
// and copied successfully; it does not mean the compositor accepted it.
namespace uevr::duoview::xr {

enum class OutputPath : std::uint8_t {
    none,
    dibr_stereo,
};

enum class SubmitPhase : uint8_t {
    none,
    output_ready,
    submitted,
};

struct OutputState {
    OutputPath path{OutputPath::none};
    SubmitPhase phase{SubmitPhase::none};
    std::uint64_t serial{};
    std::uint64_t generation{};
    bool held{};
};

constexpr bool source_matches(
    std::uint64_t source_serial,
    std::uint64_t source_generation,
    std::uint64_t frame_serial,
    std::uint64_t generation)
{
    return source_serial != 0 && source_generation != 0 && frame_serial != 0 && generation != 0 &&
        source_serial == frame_serial && source_generation == generation;
}

constexpr OutputState output_ready(std::uint64_t serial, std::uint64_t generation) {
    if (!serial || !generation) {
        return {};
    }
    return {OutputPath::dibr_stereo, SubmitPhase::output_ready, serial, generation, false};
}

constexpr bool is_dibr_stereo(const OutputState& state, std::uint64_t generation) {
    return state.path == OutputPath::dibr_stereo &&
        (state.phase == SubmitPhase::output_ready || state.phase == SubmitPhase::submitted) &&
        state.serial != 0 && state.generation != 0 && state.generation == generation;
}

constexpr bool is_stereo_submitted(const OutputState& state, std::uint64_t generation) {
    return is_dibr_stereo(state, generation) && state.phase == SubmitPhase::submitted;
}

constexpr bool stereo_submission_accepted(
    const OutputState& state,
    std::uint64_t generation,
    bool end_frame_succeeded,
    bool real_projection_submitted,
    std::uint32_t projection_view_count)
{
    return is_dibr_stereo(state, generation) && end_frame_succeeded &&
        real_projection_submitted && projection_view_count == 2;
}

constexpr OutputState held_candidate(const OutputState& submitted, std::uint64_t generation) {
    if (!is_stereo_submitted(submitted, generation)) {
        return {};
    }
    auto result = submitted;
    result.held = true;
    return result;
}

// Promote only after xrEndFrame succeeds with the actual two-view projection.
// Failure preserves the prior phase so a failed submission cannot be reported
// as StereoSubmitted.
constexpr OutputState confirm_xr_submit(
    OutputState state,
    std::uint64_t generation,
    bool end_frame_succeeded,
    bool real_projection_submitted,
    std::uint32_t projection_view_count)
{
    if (!stereo_submission_accepted(state, generation, end_frame_succeeded,
            real_projection_submitted, projection_view_count)) {
        return state;
    }
    state.phase = SubmitPhase::submitted;
    return state;
}

} // namespace uevr::duoview::xr

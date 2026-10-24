#include "DuoViewDibrXrState.hpp"

#include <cstdlib>
#include <iostream>

using namespace uevr::duoview::xr;

namespace {
void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}
}

int main() {
    const auto empty = OutputState{};
    require(!is_dibr_stereo(empty, 7), "empty/mono state cannot opt out of the mono submit path");
    require(!is_stereo_submitted(empty, 7), "empty state is never reported as StereoSubmitted");
    require(!source_matches(18, 7, 19, 7),
        "mismatched immutable packet serial cannot bind a DIBR output to different views");
    require(!source_matches(19, 8, 19, 7),
        "mismatched immutable packet generation cannot bind stale views");
    require(source_matches(19, 7, 19, 7), "matching immutable packet stamp remains bound");

    require(output_ready(0, 7).phase == SubmitPhase::none,
        "zero serial is rejected before an output packet is published");
    require(output_ready(19, 0).phase == SubmitPhase::none,
        "zero generation is rejected before an output packet is published");

    const auto ready = output_ready(19, 7);
    require(is_dibr_stereo(ready, 7), "successful DIBR output is eligible for the stereo projection");
    require(!is_dibr_stereo(ready, 8), "generation mismatch invalidates a pending stereo output");
    require(!is_stereo_submitted(ready, 7), "GPU output readiness alone is not a compositor submit");

    const auto failed = confirm_xr_submit(ready, 7, false, true, 2);
    require(failed.phase == SubmitPhase::output_ready && !is_stereo_submitted(failed, 7) &&
        !stereo_submission_accepted(ready, 7, false, true, 2),
        "xrEndFrame failure cannot set StereoSubmitted");
    const auto empty_projection = confirm_xr_submit(ready, 7, true, false, 2);
    require(empty_projection.phase == SubmitPhase::output_ready && !is_stereo_submitted(empty_projection, 7),
        "success without a real projection cannot set StereoSubmitted");
    const auto one_eye = confirm_xr_submit(ready, 7, true, true, 1);
    require(one_eye.phase == SubmitPhase::output_ready && !is_stereo_submitted(one_eye, 7),
        "one-eye projection cannot set StereoSubmitted");

    const auto submitted = confirm_xr_submit(ready, 7, true, true, 2);
    require(is_stereo_submitted(submitted, 7), "only successful two-view xrEndFrame promotes the packet");
    require(stereo_submission_accepted(ready, 7, true, true, 2),
        "StereoSubmitted event requires current-frame success and a real two-view projection");
    require(submitted.serial == 19 && submitted.generation == 7,
        "submitted packet keeps its original immutable serial and generation");

    const auto held = held_candidate(submitted, 7);
    require(is_stereo_submitted(held, 7) && held.held && held.serial == 19,
        "held stereo preserves the last actually submitted camera packet and serial");
    require(!held_candidate(ready, 7).serial,
        "a merely ready packet cannot become held before successful submission");
    require(!is_stereo_submitted(held, 8), "held stereo is invalidated by generation change");
    require(held_candidate(submitted, 8).phase == SubmitPhase::none,
        "generation change cannot carry a stale held stereo camera into a new scene");
    require(!stereo_submission_accepted(held, 7, false, true, 2),
        "failed held-frame xrEndFrame cannot emit a new StereoSubmitted event");

    std::cout << "Manual DIBR XR output-state contract passed (mono, pending, submit failure, one-eye, held, generation reset).\n";
    return 0;
}

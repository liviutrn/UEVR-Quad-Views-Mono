#pragma once
// Experimental same-tick RGB-D provenance contract for A+ and B+.
// Pure C++17, no D3D dependencies: unit-test it independently of XR/Unreal.
// This ledger does NOT itself establish producer role; only accepts explicit proof.
#include <cstdint>

namespace uevr::duoview::stereo {
enum class Origin : uint8_t { Center, Left, Right };
enum class Role : uint8_t { Periphery, Fovea };
enum class Stage : uint8_t { Unknown, SceneBeforeUpscale, SceneAfterUpscale, Presentation };
enum class Proof : uint8_t {
    Absent, Candidate, GPUComplete, ProducerMatched, GeometryCalibrated
};
enum class Reject : uint8_t {
    None, Missing, Generation, DifferentTick, DifferentOrigin,
    DifferentPose, WrongRoles, UnmatchedColorDepth, UntrustedGPU,
    UncalibratedGeometry, DifferentColorStage, UnknownProjections
};

struct TextureIdentity {
    uintptr_t resource{};          // diagnostic pointer, not sufficient alone
    uint64_t allocation_revision{}; // RHI/RT-pool generation
    uint32_t width{}, height{}, subresource{};
    uint32_t format{};
    bool valid() const {
        return resource != 0 && allocation_revision != 0 &&
            width != 0 && height != 0 && format != 0;
    }
};
struct Pass {
    uint64_t generation{}, tick{}, serial{}, pose_token{}, projection_token{};
    uint64_t queue_token{}, gpu_copy_fence{}, gpu_queue_completed{};
    uint64_t color_stage_token{}, depth_stage_token{};
    Origin origin{Origin::Center};
    Role role{Role::Periphery};
    Stage color_stage{Stage::Unknown};
    Stage depth_stage{Stage::Unknown};
    Proof proof{Proof::Absent};
    TextureIdentity color{}, depth{};
    // 'producer_pass_verified' requires direct UE producer provenance, not
    // identical extents, a raw DSV pointer or "second barrier after first".
    bool producer_pass_verified{};
    bool matrices_calibrated{};
};
inline Reject check_pass(const Pass& p) {
    if (!p.generation || !p.tick || !p.serial || !p.pose_token ||
        !p.projection_token || !p.color.valid() || !p.depth.valid())
        return Reject::Missing;
    if (!p.producer_pass_verified ||
        p.color_stage_token == 0 || p.color_stage_token != p.depth_stage_token)
        return Reject::UnmatchedColorDepth;
    if (!p.queue_token || !p.gpu_copy_fence ||
        p.gpu_queue_completed < p.gpu_copy_fence ||
        p.proof < Proof::ProducerMatched)
        return Reject::UntrustedGPU;
    if (!p.matrices_calibrated || p.proof < Proof::GeometryCalibrated)
        return Reject::UncalibratedGeometry;
    if (p.color_stage == Stage::Unknown || p.depth_stage == Stage::Unknown ||
        p.color_stage != p.depth_stage)
        return Reject::DifferentColorStage;
    return Reject::None;
}
inline Reject check_pair(const Pass& peripheral, const Pass& foveal) {
    if (const auto x=check_pass(peripheral); x!=Reject::None) return x;
    if (const auto x=check_pass(foveal); x!=Reject::None) return x;
    if (peripheral.role != Role::Periphery || foveal.role != Role::Fovea)
        return Reject::WrongRoles;
    if (peripheral.generation != foveal.generation) return Reject::Generation;
    if (peripheral.tick != foveal.tick) return Reject::DifferentTick;
    if (peripheral.origin != foveal.origin) return Reject::DifferentOrigin;
    if (peripheral.pose_token != foveal.pose_token) return Reject::DifferentPose;
    if (peripheral.color_stage != foveal.color_stage)
        return Reject::DifferentColorStage;
    // Individual projection tokens may differ: fovea crop != full periphery.
    return Reject::None;
}
inline bool ready_for_center_stereo(const Pass& p, const Pass& f) {
    return check_pair(p,f)==Reject::None && p.origin==Origin::Center;
}
} // namespace uevr::duoview::stereo

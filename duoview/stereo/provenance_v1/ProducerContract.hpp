#pragma once
// CI31: typed producer-provenance contract. NOT a producer hook and NOT an
// assertion that the existing R5 observer knows UE view/frame identity.
// Only authoritative UE producer records may populate authenticated stamps.
#include <array>
#include <cmath>
#include <cstdint>

namespace uevr::duoview::stereo::provenance {
enum class Role : uint8_t { Unknown, LeftFovea, RightPeriphery };
enum class Stage : uint8_t { Unknown, SceneDepth, SceneColor };
enum class Reject : uint8_t {
    None, NoLeftDepth, NoRightDepth, RoleUnverified,
    SourceFrameMismatch, SourceStageMismatch, DepthMatrixUnknown,
    SourceViewMismatch, WorldOriginMismatch, GPUWaitFail,
    SlotRetired, ResourceUnowned, InvalidMatrix
};
inline constexpr const char* name(Reject code) noexcept {
    switch(code) {
        case Reject::None: return "NONE";
        case Reject::NoLeftDepth: return "NO_LEFT_DEPTH";
        case Reject::NoRightDepth: return "NO_RIGHT_DEPTH";
        case Reject::RoleUnverified: return "ROLE_UNVERIFIED";
        case Reject::SourceFrameMismatch: return "SOURCE_FRAME_MISMATCH";
        case Reject::SourceStageMismatch: return "SOURCE_STAGE_MISMATCH";
        case Reject::DepthMatrixUnknown: return "DEPTH_MATRIX_UNKNOWN";
        case Reject::SourceViewMismatch: return "SOURCE_VIEW_MISMATCH";
        case Reject::WorldOriginMismatch: return "WORLD_ORIGIN_MISMATCH";
        case Reject::GPUWaitFail: return "GPU_WAIT_FAIL";
        case Reject::SlotRetired: return "SLOT_RETIRED";
        case Reject::ResourceUnowned: return "RESOURCE_UNOWNED";
        case Reject::InvalidMatrix: return "INVALID_MATRIX";
    }
    return "UNKNOWN_REJECT";
}
// Tokens are issued at the producer, never from the Present observer epoch,
// viewport geometry, DSV pointer, XR frame index or candidate ordinal.
struct Stamp {
    uint64_t sceneFrame{};       // UE scene/view-family render generation
    uint64_t viewGeneration{};   // invalidated on load/re-enter/resolution
    uint64_t viewFamily{};       // shared by LEFT and RIGHT scene views
    uint64_t viewToken{};        // unique physical producer view
    uint64_t stageFamily{};      // matching scene geometric stage
    uint64_t projectionToken{};  // actual depth+color projection, includes crop
    uint64_t jitterToken{};      // exact depth/color jitter and sample space
    uint64_t originToken{};      // common camera-relative world origin
    uint64_t resourceGeneration{}; // allocation generation (not raw pointer)
    uint64_t producerWrite{};    // exact write version
    uint64_t producerFence{};    // verified submit/complete ordering
    uint32_t subresource{};
    Role role{Role::Unknown};
    Stage stage{Stage::Unknown};
    bool authenticated{};       // only from real producer hook
    bool owned{};               // strong resource lifetime proof
    bool submitted{};
    bool gpuReady{};            // producer complete or ordered queue wait
    bool retired{};
};
struct Eye {
    Stamp color{};
    Stamp depth{};
    std::array<float,16> depthClipFromWorld{};
    std::array<float,16> depthWorldFromClip{};
    std::array<float,16> colorClipFromWorld{};
    bool matricesFromProducer{};
};
struct Pair {
    Eye left{}, right{};
    uint64_t consumedSceneFrame{}; // actual packet scene generation, NOT XR tick
    uint64_t consumedViewGeneration{};
};
inline bool valid_matrix(const std::array<float,16>& m) noexcept {
    double magnitude=0.0;
    for(float x:m) {
        if(!std::isfinite(x))return false;
        magnitude += double(x)*x;
    }
    return std::isfinite(magnitude) && magnitude>1.e-12;
}
inline bool verified_resource(const Stamp& x) noexcept {
    return x.authenticated && x.owned && !x.retired && x.resourceGeneration &&
           x.producerWrite && x.producerFence && x.submitted && x.gpuReady;
}
inline Reject verify_eye(const Eye& e, Role expected) noexcept {
    const auto& c=e.color;const auto& d=e.depth;
    if(!d.authenticated || !c.authenticated ||
       c.role!=expected || d.role!=expected || expected==Role::Unknown)
        return Reject::RoleUnverified;
    if(!c.sceneFrame || c.sceneFrame!=d.sceneFrame ||
       !c.viewGeneration || c.viewGeneration!=d.viewGeneration ||
       !c.viewFamily || c.viewFamily!=d.viewFamily)
        return Reject::SourceFrameMismatch;
    if(c.stage!=Stage::SceneColor || d.stage!=Stage::SceneDepth ||
       !c.stageFamily || c.stageFamily!=d.stageFamily)
        return Reject::SourceStageMismatch;
    if(!c.viewToken || c.viewToken!=d.viewToken ||
       !c.projectionToken || c.projectionToken!=d.projectionToken ||
       !c.jitterToken || c.jitterToken!=d.jitterToken)
        return Reject::SourceViewMismatch;
    if(!c.originToken || c.originToken!=d.originToken)
        return Reject::WorldOriginMismatch;
    if(!e.matricesFromProducer) return Reject::DepthMatrixUnknown;
    if(!valid_matrix(e.depthClipFromWorld) ||
       !valid_matrix(e.depthWorldFromClip) ||
       !valid_matrix(e.colorClipFromWorld)) return Reject::InvalidMatrix;
    if(c.retired || d.retired)return Reject::SlotRetired;
    if(!c.owned || !d.owned || !c.resourceGeneration || !d.resourceGeneration)
        return Reject::ResourceUnowned;
    if(!c.submitted || !d.submitted || !c.gpuReady || !d.gpuReady ||
       !c.producerFence || !d.producerFence ||
       !c.producerWrite || !d.producerWrite)
        return Reject::GPUWaitFail;
    return Reject::None;
}
inline Reject verify(const Pair& pair) noexcept {
    // Empty/offline observer data must NEVER enable hybrid (or legacy mode).
    if(!pair.left.depth.authenticated)return Reject::NoLeftDepth;
    if(!pair.right.depth.authenticated)return Reject::NoRightDepth;
    if(auto r=verify_eye(pair.left,Role::LeftFovea);r!=Reject::None)return r;
    if(auto r=verify_eye(pair.right,Role::RightPeriphery);r!=Reject::None)return r;
    const auto& l=pair.left.color;const auto& r=pair.right.color;
    if(!pair.consumedSceneFrame || l.sceneFrame!=r.sceneFrame ||
       l.sceneFrame!=pair.consumedSceneFrame ||
       !pair.consumedViewGeneration ||
       l.viewGeneration!=r.viewGeneration ||
       l.viewGeneration!=pair.consumedViewGeneration ||
       l.viewFamily!=r.viewFamily)
        return Reject::SourceFrameMismatch;
    if(l.viewToken==r.viewToken)return Reject::RoleUnverified;
    if(l.originToken!=r.originToken)return Reject::WorldOriginMismatch;
    return Reject::None;
}
} // namespace uevr::duoview::stereo::provenance

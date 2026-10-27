#pragma once
// Matching root-constant/constant-buffer layout for StereoBackwardGather.hlsl.
// CPU must supply actual same-frame jittered matrices for depth and color passes.
// row_major matrices are used with mul(matrix, float4(vector,1)) in HLSL.
// This file deliberately has NO dependencies on UEVR or a particular SDK.
#include <cstdint>
#include <cstddef>

namespace uevr::duoview::stereo {
struct alignas(16) BackwardConstants {
    float targetWorldFromClip[16]{};
    float sourceDepthClipFromWorld[16]{};
    float sourceDepthWorldFromClip[16]{};
    float sourceColorClipFromWorld[16]{};
    float sourceCameraWorld[4]{};
    float targetCameraWorld[4]{};
    float sourceDepthRect[4]{};
    float targetDepthRect[4]{};
    float sourceColorRect[4]{};
    float targetRealColorRect[4]{};
    float depthParams[4]{}; // minDepth, maxDepth, absWorldError, relativeWorldError
    float edgeParams[4]{};  // targetEdgeAbs, targetEdgeRel, minimumSourceCoverage, maximumPhotoLumaDelta
    std::uint32_t outputRegion[4]{};
    std::uint32_t outputConfig[4]{}; // width,height,flags,reserved
};
static_assert(sizeof(BackwardConstants)==416);
static_assert(alignof(BackwardConstants)==16);
static_assert(offsetof(BackwardConstants, outputConfig)==400);
enum Reject : std::uint32_t {
    InvalidTargetDepth=1u, UnreliableTargetEdge=2u, OutsideSourceProjection=4u,
    InvalidSourceDepth=8u, NoNativeFallback=16u, PhotometricMismatch=32u
};
enum Flags : std::uint32_t {
    HasTargetColor=1u, GuardTargetDepthEdge=2u, PhotometricGuard=4u
};
struct BindingContract {
    // D3D12 descriptor table registers: SRV t0=SourceColor, t1=SourceDepth,
    // t2=TargetDepth, t3=TargetRealColor; UAV u0=OutColor,
    // u1=OutConfidence R32_FLOAT, u2=OutReject R32_UINT.
    // b0=BackwardConstants; static sampler s0=LINEAR_CLAMP.
    // Source/target depth SRVs MUST be typed R32_FLOAT / R24_UNORM_X8_TYPELESS /
    // R16_UNORM as appropriate, with HLSL float reconstruction matching the
    // actual depth format and plane (typed float SRV load).
    // All views must be captured from one UE frame with correct matrices.
    // Same color-space exposure/postprocess stage for left/right color.
    // A DSV copy is not evidence that it matches either camera.
    // This is a diagnostic/prototype contract, not an active UEVR hook.
    bool depthEyeProven{};
    bool frameGenerationMatches{};
    bool viewMatricesMatchDepth{};
    bool compatibleColorEncoding{};
    bool renderTargetsReady{};
    bool canDispatch() const noexcept {
        return depthEyeProven && frameGenerationMatches &&
          viewMatricesMatchDepth && compatibleColorEncoding && renderTargetsReady;
    }
};
} // namespace uevr::duoview::stereo

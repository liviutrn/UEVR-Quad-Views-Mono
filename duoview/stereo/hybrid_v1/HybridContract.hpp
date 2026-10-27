#pragma once
#include <cstdint>
#include <cstddef>
namespace uevr::duoview::stereo {
struct alignas(16) HybridConstants {
    float sourceWorldFromClip[16]{};
    float sourceColorClipFromWorld[16]{};
    float targetClipFromWorld[16]{};
    float targetWorldFromClip[16]{};
    float sourceCameraWorld[4]{};
    float targetCameraWorld[4]{};
    float sourceDepthRect[4]{};
    float sourceColorRect[4]{};
    float targetDepthRect[4]{};
    float targetColorRect[4]{};
    float limits[4]{};
    float blendParams[4]{};
    uint32_t sourceDimensions[4]{};
    uint32_t targetDimensions[4]{};
    uint32_t flags[4]{};
};
static_assert(sizeof(HybridConstants)==496);
static_assert(offsetof(HybridConstants,flags)==480);
enum class CandidateMode : uint32_t { Auto=0, LockedLeft=1, LockedRight=2, BothLocked=3 };
struct StereoProvenance {
    bool leftSceneColorDepthSamePass{};
    bool rightSceneColorDepthSamePass{};
    bool sourceFrameSynchronized{};
    bool matricesCameraRelative{};
    bool outputsReady{};
    bool canSynthesize() const {
        return leftSceneColorDepthSamePass && rightSceneColorDepthSamePass
          && sourceFrameSynchronized && matricesCameraRelative && outputsReady;
    }
};
}

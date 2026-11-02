// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//
// Mono Frame Generation (personal modification of VectorXR 0.20.0 for
// DuoView Mono / UEVR, not an official VectorXR feature).
//
// When BOTH views of the game's projection layer show the SAME image (same
// swapchain, array slice and image rectangle, no depth), Frame Generation can
// run once: the layer hands Frame Generation a one-view copy of the frame
// (view 0), and every frame it submits to the runtime gets its second view
// back as a copy of view 0 carrying view 1's own pose and field of view.
// History, flow, synthesis and output swapchains then exist for one view only.
#pragma once

#include <openxr/openxr.h>

#include <cmath>
#include <cstdint>
#include <cstring>

namespace depthxr::mono_framegen {

// Frames in a row that must be shareable before collapsing starts (flapping
// between one and two views would rebuild Frame Generation's images).
constexpr std::uint32_t kActivateFrames = 45;

// The last real frame's two views, kept to rebuild view 1 of every frame
// Frame Generation submits (generated frames included).
struct RealViews {
    XrPosef pose0{}, pose1{};
    XrFovf fov0{}, fov1{};
};

// The first projection layer with views: the one Frame Generation works on
// (FrameGenPresenter's FindProjection uses the same rule).
inline const XrCompositionLayerProjection* FirstProjection(const XrFrameEndInfo& info, std::uint32_t* index) {
    for (std::uint32_t i = 0; info.layers && i < info.layerCount; ++i) {
        const XrCompositionLayerBaseHeader* base = info.layers[i];
        if (base && base->type == XR_TYPE_COMPOSITION_LAYER_PROJECTION) {
            const auto* projection = reinterpret_cast<const XrCompositionLayerProjection*>(base);
            if (projection->viewCount > 0 && projection->views) {
                if (index) *index = i;
                return projection;
            }
        }
    }
    return nullptr;
}

inline bool SameRect(const XrRect2Di& a, const XrRect2Di& b) {
    return a.offset.x == b.offset.x && a.offset.y == b.offset.y && a.extent.width == b.extent.width &&
           a.extent.height == b.extent.height;
}

// nullptr when the two views show the same image; else why not.
inline const char* NotShareable(const XrCompositionLayerProjection* projection) {
    if (!projection) return "no projection layer";
    if (projection->viewCount != 2) return "projection layer does not have exactly two views";
    const XrCompositionLayerProjectionView& a = projection->views[0];
    const XrCompositionLayerProjectionView& b = projection->views[1];
    if (a.subImage.swapchain == XR_NULL_HANDLE) return "view 0 has no swapchain";
    if (a.subImage.swapchain != b.subImage.swapchain) return "views use different swapchains";
    if (a.subImage.imageArrayIndex != b.subImage.imageArrayIndex) return "views use different array slices";
    if (!SameRect(a.subImage.imageRect, b.subImage.imageRect)) return "views use different image rectangles";
    if (a.subImage.imageRect.extent.width <= 0 || a.subImage.imageRect.extent.height <= 0) return "empty image rectangle";
    if (a.next || b.next) return "views carry depth or other chained data";
    return nullptr;
}

inline XrQuaternionf Multiply(const XrQuaternionf& a, const XrQuaternionf& b) {
    return {a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y, a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
            a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w, a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z};
}

inline XrVector3f Rotate(const XrQuaternionf& q, const XrVector3f& v) {
    // v + 2 w (u x v) + 2 u x (u x v), u = q.xyz.
    const XrVector3f uv{q.y * v.z - q.z * v.y, q.z * v.x - q.x * v.z, q.x * v.y - q.y * v.x};
    const XrVector3f uuv{q.y * uv.z - q.z * uv.y, q.z * uv.x - q.x * uv.z, q.x * uv.y - q.y * uv.x};
    return {v.x + 2.0f * (q.w * uv.x + uuv.x), v.y + 2.0f * (q.w * uv.y + uuv.y), v.z + 2.0f * (q.w * uv.z + uuv.z)};
}

inline XrPosef Compose(const XrPosef& a, const XrPosef& b) {
    const XrVector3f moved = Rotate(a.orientation, b.position);
    return {Multiply(a.orientation, b.orientation),
            {a.position.x + moved.x, a.position.y + moved.y, a.position.z + moved.z}};
}

inline XrPosef Inverse(const XrPosef& a) {
    const XrQuaternionf conjugate{-a.orientation.x, -a.orientation.y, -a.orientation.z, a.orientation.w};
    const XrVector3f back = Rotate(conjugate, a.position);
    return {conjugate, {-back.x, -back.y, -back.z}};
}

inline bool SamePose(const XrPosef& a, const XrPosef& b) { return std::memcmp(&a, &b, sizeof(XrPosef)) == 0; }
inline bool SameFov(const XrFovf& a, const XrFovf& b) { return std::memcmp(&a, &b, sizeof(XrFovf)) == 0; }

// View 1 for a frame whose single view is `view0`: the same image, placed
// where view 1 sat relative to view 0 in the last real frame, with view 1's
// field of view (shifted by any change Frame Generation made to view 0's).
inline XrCompositionLayerProjectionView SecondView(const XrCompositionLayerProjectionView& view0, const RealViews& real) {
    XrCompositionLayerProjectionView view1 = view0;
    if (SamePose(real.pose0, real.pose1)) {
        view1.pose = view0.pose; // DuoView Mono: both eyes share one pose
    } else {
        view1.pose = Compose(view0.pose, Compose(Inverse(real.pose0), real.pose1));
    }
    if (SameFov(view0.fov, real.fov0)) {
        view1.fov = real.fov1;
    } else {
        view1.fov.angleLeft = view0.fov.angleLeft + (real.fov1.angleLeft - real.fov0.angleLeft);
        view1.fov.angleRight = view0.fov.angleRight + (real.fov1.angleRight - real.fov0.angleRight);
        view1.fov.angleUp = view0.fov.angleUp + (real.fov1.angleUp - real.fov0.angleUp);
        view1.fov.angleDown = view0.fov.angleDown + (real.fov1.angleDown - real.fov0.angleDown);
    }
    return view1;
}

} // namespace depthxr::mono_framegen

// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//
// Mono Frame Generation (personal modification): detection of a projection
// layer whose two views show the same image, and the rebuilt second view.
#include "depthxr/mono_framegen.h"

#include <cmath>
#include <cstdio>

namespace mf = depthxr::mono_framegen;

static int failures = 0;
#define EXPECT(cond, msg)                                                                                               \
    do {                                                                                                                \
        if (!(cond)) {                                                                                                  \
            std::printf("FAIL: %s\n", msg);                                                                             \
            ++failures;                                                                                                 \
        }                                                                                                               \
    } while (0)

static bool Close(float a, float b) { return std::fabs(a - b) < 1e-5f; }

static XrCompositionLayerProjectionView View(XrSwapchain swapchain, int x, int y, int w, int h) {
    XrCompositionLayerProjectionView view{XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW};
    view.pose.orientation = {0.0f, 0.0f, 0.0f, 1.0f};
    view.fov = {-0.9f, 0.8f, 0.85f, -0.95f};
    view.subImage.swapchain = swapchain;
    view.subImage.imageRect = {{x, y}, {w, h}};
    return view;
}

int main() {
    const auto swapchain = reinterpret_cast<XrSwapchain>(static_cast<std::uintptr_t>(0x1234));
    const auto other = reinterpret_cast<XrSwapchain>(static_cast<std::uintptr_t>(0x5678));
    XrCompositionLayerProjectionView views[2]{View(swapchain, 0, 152, 3840, 2948), View(swapchain, 0, 152, 3840, 2948)};
    XrCompositionLayerProjection projection{XR_TYPE_COMPOSITION_LAYER_PROJECTION};
    projection.viewCount = 2;
    projection.views = views;
    EXPECT(mf::NotShareable(&projection) == nullptr, "same swapchain/slice/rect is shareable");

    // Separate eye halves of a double-wide image (UEVR v207) stay stereo.
    views[1].subImage.imageRect.offset.x = 4096;
    EXPECT(mf::NotShareable(&projection) != nullptr, "different rectangles are not shareable");
    views[1] = views[0];
    views[1].subImage.swapchain = other;
    EXPECT(mf::NotShareable(&projection) != nullptr, "different swapchains are not shareable");
    views[1] = views[0];
    views[1].subImage.imageArrayIndex = 1;
    EXPECT(mf::NotShareable(&projection) != nullptr, "different array slices are not shareable");
    views[1] = views[0];
    XrCompositionLayerDepthInfoKHR depth{XR_TYPE_COMPOSITION_LAYER_DEPTH_INFO_KHR};
    views[1].next = &depth;
    EXPECT(mf::NotShareable(&projection) != nullptr, "views with depth are not shareable");
    views[1] = views[0];
    projection.viewCount = 1;
    EXPECT(mf::NotShareable(&projection) != nullptr, "one view is not a stereo pair");
    projection.viewCount = 2;
    EXPECT(mf::NotShareable(nullptr) != nullptr, "no projection is not shareable");

    // First projection layer with views is found, after a quad layer.
    XrCompositionLayerQuad quad{XR_TYPE_COMPOSITION_LAYER_QUAD};
    const XrCompositionLayerBaseHeader* layers[2]{reinterpret_cast<const XrCompositionLayerBaseHeader*>(&quad),
                                                  reinterpret_cast<const XrCompositionLayerBaseHeader*>(&projection)};
    XrFrameEndInfo info{XR_TYPE_FRAME_END_INFO};
    info.layerCount = 2;
    info.layers = layers;
    std::uint32_t index = 99;
    EXPECT(mf::FirstProjection(info, &index) == &projection && index == 1, "first projection layer found");

    // DuoView Mono: identical poses, FOVs differing only by eye alignment.
    mf::RealViews real;
    real.pose0 = {{0.0f, 0.258819f, 0.0f, 0.965926f}, {0.1f, 1.6f, -0.2f}};
    real.pose1 = real.pose0;
    real.fov0 = {-1.20f, 1.10f, 1.00f, -1.05f};
    real.fov1 = {-1.18f, 1.12f, 1.00f, -1.05f};
    XrCompositionLayerProjectionView generated = views[0];
    generated.pose = {{0.0f, 0.3f, 0.0f, 0.953939f}, {0.12f, 1.61f, -0.21f}}; // a predicted pose
    generated.fov = real.fov0;
    XrCompositionLayerProjectionView second = mf::SecondView(generated, real);
    EXPECT(mf::SamePose(second.pose, generated.pose), "identical real poses: view 1 takes view 0's pose exactly");
    EXPECT(mf::SameFov(second.fov, real.fov1), "unchanged FOV: view 1 gets its own real FOV exactly");
    EXPECT(second.subImage.swapchain == generated.subImage.swapchain &&
               mf::SameRect(second.subImage.imageRect, generated.subImage.imageRect),
           "view 1 shows the same image as view 0");

    // Changed view 0 FOV: view 1 keeps the same per-eye difference.
    generated.fov.angleLeft += 0.01f;
    second = mf::SecondView(generated, real);
    EXPECT(Close(second.fov.angleLeft, real.fov1.angleLeft + 0.01f) && Close(second.fov.angleRight, real.fov1.angleRight),
           "shifted FOV keeps the eyes' difference");

    // Different real poses: view 1 keeps its offset relative to view 0.
    real.pose1 = mf::Compose(real.pose0, XrPosef{{0.0f, 0.0f, 0.0f, 1.0f}, {0.072f, 0.0f, 0.0f}});
    generated.fov = real.fov0;
    generated.pose = real.pose0;
    second = mf::SecondView(generated, real);
    EXPECT(Close(second.pose.position.x, real.pose1.position.x) && Close(second.pose.position.y, real.pose1.position.y) &&
               Close(second.pose.position.z, real.pose1.position.z),
           "real frame: rebuilt view 1 sits where the game put it");
    const XrPosef round = mf::Compose(mf::Inverse(real.pose0), real.pose0);
    EXPECT(Close(round.orientation.w, 1.0f) && Close(round.position.x, 0.0f) && Close(round.position.z, 0.0f),
           "inverse composes to identity");

    if (failures) {
        std::printf("%d failure(s)\n", failures);
        return 1;
    }
    std::printf("PASS: mono frame generation detection and second view\n");
    return 0;
}

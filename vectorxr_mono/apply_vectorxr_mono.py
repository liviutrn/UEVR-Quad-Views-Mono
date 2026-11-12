#!/usr/bin/env python3
"""Personal VectorXR 0.20.1 (DienerTech/vectorxr 87e575f, MPL-2.0) patch:
Frame Generation runs ONCE when both projection views show the same image.

Usage: apply_vectorxr_mono.py <vectorxr checkout>

Detection (per frame, no setting needed): the game's first projection layer has
exactly two views with the same swapchain, array slice and image rectangle and
no depth (DuoView v208 "Same image for both eyes"). After 45 such frames in a
row the layer hands Frame Generation a ONE-view copy of each frame (view 0), so
capture, history, flow, synthesis and output swapchains exist once. Every frame
sent to the runtime (SubmitRuntimeFrame: real, generated, held, 1x pass-through)
gets view 1 back: the same image, view 1's own pose offset and field of view
(so UEVR's Mono Eye Alignment is kept). Any frame that is not shareable goes
through unchanged as normal stereo, immediately. Frames without a projection layer leave the
mono state unchanged. All FG modes collapse, Extrapolate included (no depth path). Disable with the environment
variable VECTORXR_MONO_FRAMEGEN=0.

Touches: layer/include/depthxr/openxr_layer.h, layer/src/openxr_layer.cpp,
layer/CMakeLists.txt; adds layer/include/depthxr/mono_framegen.h and
layer/tests/mono_framegen_tests.cpp. The Frame Generation engine is unchanged.
"""
from pathlib import Path
import shutil
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_vectorxr_mono.py <vectorxr checkout>")
root = Path(sys.argv[1])
here = Path(__file__).resolve().parent
files = {}


def load(rel):
    if rel not in files:
        files[rel] = (root / rel).read_text(encoding="utf-8-sig")
    return files[rel]


def replace(rel, old, new, label):
    text = load(rel)
    found = text.count(old)
    if found != 1:
        raise SystemExit(f"VectorXR mono anchor mismatch in {rel} ({label}): found {found}, expected 1")
    files[rel] = text.replace(old, new)


shutil.copyfile(here / "mono_framegen.h", root / "layer/include/depthxr/mono_framegen.h")
shutil.copyfile(here / "mono_framegen_tests.cpp", root / "layer/tests/mono_framegen_tests.cpp")

H = "layer/include/depthxr/openxr_layer.h"
replace(H, '#include "depthxr/logger.h"\n', '#include "depthxr/logger.h"\n#include "depthxr/mono_framegen.h"\n', "include")
replace(H, "    XrResult SubmitRuntimeFrame(XrSession, const XrFrameEndInfo*);\n",
        r'''    XrResult SubmitRuntimeFrame(XrSession, const XrFrameEndInfo*);
    // Mono Frame Generation (personal patch, depthxr/mono_framegen.h): when both
    // views of the game's projection show the same image, Frame Generation gets
    // view 0 only (CollapseMonoFrame, in TraceRuntimeEndFrame) and every runtime
    // submission gets view 1 back (ExpandMonoFrame, in SubmitRuntimeFrame).
    // The returned pointer is `info` itself or the caller's storage.
    const XrFrameEndInfo* CollapseMonoFrame(XrSession, const XrFrameEndInfo* info, XrFrameEndInfo& storage,
                                            std::vector<const XrCompositionLayerBaseHeader*>& layers,
                                            XrCompositionLayerProjection& projection,
                                            XrCompositionLayerProjectionView& view);
    const XrFrameEndInfo* ExpandMonoFrame(XrSession, const XrFrameEndInfo* info, XrFrameEndInfo& storage,
                                          std::vector<const XrCompositionLayerBaseHeader*>& layers,
                                          std::vector<XrCompositionLayerProjection>& projections,
                                          std::vector<XrCompositionLayerProjectionView>& views);
    struct MonoFrameGenState {
        XrSession session{XR_NULL_HANDLE};
        int enabled{-1}; // -1 not read yet, 0 off (VECTORXR_MONO_FRAMEGEN=0), 1 on
        bool active{false};
        bool real_valid{false};
        std::uint32_t streak{0};
        mono_framegen::RealViews real{};
        std::uint64_t collapsed{0};
        std::uint64_t expanded{0};
        std::uint64_t unexpandable{0};
        std::chrono::steady_clock::time_point next_log{};
    };
    std::mutex mono_framegen_mutex_;
    MonoFrameGenState mono_framegen_;
    // Read by the stock Frame Generation OSD without taking the mono-state mutex.
    std::atomic<bool> mono_framegen_active_{false};
''', "SubmitRuntimeFrame declaration")

C = "layer/src/openxr_layer.cpp"
# 1) Collapse: Frame Generation sees one view.
replace(C, "    if (framegen_owns_pacing_.load(std::memory_order_acquire) && info) {\n"
           "        if (FrameGenTrace& trace = framegen_.Trace(); trace.Enabled()) {\n",
        "    XrFrameEndInfo mono_info{};\n"
        "    std::vector<const XrCompositionLayerBaseHeader*> mono_layers;\n"
        "    XrCompositionLayerProjection mono_projection{};\n"
        "    XrCompositionLayerProjectionView mono_view{};\n"
        "    if (framegen_owns_pacing_.load(std::memory_order_acquire) && info &&\n"
        "        !(quad && quad->route == FrameGenQuadRoute::kClaimed)) {\n"
        "        info = CollapseMonoFrame(session, info, mono_info, mono_layers, mono_projection, mono_view);\n"
        "    } else if (quad && quad->route == FrameGenQuadRoute::kClaimed) {\n"
        "        std::scoped_lock lock(mono_framegen_mutex_);\n"
        "        mono_framegen_.active = false;\n"
        "        mono_framegen_.streak = 0;\n"
        "        mono_framegen_active_.store(false, std::memory_order_release);\n"
        "    }\n"
        "    if (framegen_owns_pacing_.load(std::memory_order_acquire) && info) {\n"
        "        if (FrameGenTrace& trace = framegen_.Trace(); trace.Enabled()) {\n", "collapse")
# 2) Expand: every runtime submission gets view 1 back (after the queue
#    flushes, which already covered the shared swapchain, before the OSD).
replace(C, "            default:\n                break;\n            }\n        }\n    }\n"
           "    std::unique_lock queue_lock(osd_vulkan_queue_mutex_,std::defer_lock);\n",
        "            default:\n                break;\n            }\n        }\n    }\n"
        "    XrFrameEndInfo mono_info{};\n"
        "    std::vector<const XrCompositionLayerBaseHeader*> mono_layers;\n"
        "    std::vector<XrCompositionLayerProjection> mono_projections;\n"
        "    std::vector<XrCompositionLayerProjectionView> mono_views;\n"
        "    info = ExpandMonoFrame(session, info, mono_info, mono_layers, mono_projections, mono_views);\n"
        "    std::unique_lock queue_lock(osd_vulkan_queue_mutex_,std::defer_lock);\n", "expand")
# 3) Definitions, right before TraceRuntimeEndFrame.
replace(C, "XrResult OpenXrLayer::TraceRuntimeEndFrame(XrSession session, const XrFrameEndInfo* info) {\n",
        r'''const XrFrameEndInfo* OpenXrLayer::CollapseMonoFrame(XrSession session, const XrFrameEndInfo* info,
                                                    XrFrameEndInfo& storage,
                                                    std::vector<const XrCompositionLayerBaseHeader*>& layers,
                                                    XrCompositionLayerProjection& projection,
                                                    XrCompositionLayerProjectionView& view) {
    if (!info) return info;
    std::uint32_t index = 0;
    const XrCompositionLayerProjection* source = mono_framegen::FirstProjection(*info, &index);
    const char* reason = mono_framegen::NotShareable(source);
    {
        std::scoped_lock lock(mono_framegen_mutex_);
        MonoFrameGenState& state = mono_framegen_;
        if (state.enabled < 0) {
            const char* value = std::getenv("VECTORXR_MONO_FRAMEGEN");
            state.enabled = value && (std::string(value) == "0" || std::string(value) == "off") ? 0 : 1;
            logger_.Info(std::string("Mono Frame Generation (personal DuoView patch on VectorXR 0.20.1): ") +
                         (state.enabled ? "enabled; it starts when both views show the same image."
                                        : "disabled by VECTORXR_MONO_FRAMEGEN."));
        }
        if (state.session != session) {
            const int enabled = state.enabled;
            state = MonoFrameGenState{};
            state.enabled = enabled;
            state.session = session;
            mono_framegen_active_.store(false, std::memory_order_release);
        }
        if (!state.enabled) {
            mono_framegen_active_.store(false, std::memory_order_release);
            return info;
        }
        // No game image this frame (loading, dashboard, shouldRender false): nothing to
        // collapse and nothing to judge, so keep the mono state as it is (avoids a costly
        // stereo->mono rebuild cycle after a single empty frame).
        if (!source) return info;
        if (reason) {
            // Never collapse a frame whose eyes differ; leave at once.
            if (state.active) {
                logger_.Info(std::string("Mono Frame Generation stopped (") + reason + "): back to two views after " +
                             std::to_string(state.collapsed) + " one-view frames.");
            }
            state.active = false;
            state.streak = 0;
            mono_framegen_active_.store(false, std::memory_order_release);
            return info;
        }
        if (!state.active) {
            if (++state.streak < mono_framegen::kActivateFrames) return info;
            state.active = true;
            mono_framegen_active_.store(true, std::memory_order_release);
            const XrRect2Di& rect = source->views[0].subImage.imageRect;
            logger_.Info("Mono Frame Generation started: both views show " + std::to_string(rect.extent.width) + "x" +
                         std::to_string(rect.extent.height) + " at " + std::to_string(rect.offset.x) + "," +
                         std::to_string(rect.offset.y) + " of one swapchain; Frame Generation runs on one view.");
        }
        state.real = {source->views[0].pose, source->views[1].pose, source->views[0].fov, source->views[1].fov};
        state.real_valid = true;
        ++state.collapsed;
        const auto now = std::chrono::steady_clock::now();
        if (now >= state.next_log) {
            state.next_log = now + std::chrono::seconds(30);
            logger_.Info("Mono Frame Generation: " + std::to_string(state.collapsed) + " frames generated from one view, " +
                         std::to_string(state.expanded) + " runtime frames given both views, " +
                         std::to_string(state.unexpandable) + " one-view frames left unexpanded.");
        }
    }
    projection = *source;
    view = source->views[0];
    projection.viewCount = 1;
    projection.views = &view;
    layers.assign(info->layers, info->layers + info->layerCount);
    layers[index] = reinterpret_cast<const XrCompositionLayerBaseHeader*>(&projection);
    storage = *info;
    storage.layers = layers.data();
    return &storage;
}

const XrFrameEndInfo* OpenXrLayer::ExpandMonoFrame(XrSession session, const XrFrameEndInfo* info,
                                                  XrFrameEndInfo& storage,
                                                  std::vector<const XrCompositionLayerBaseHeader*>& layers,
                                                  std::vector<XrCompositionLayerProjection>& projections,
                                                  std::vector<XrCompositionLayerProjectionView>& views) {
    if (!info || !info->layers) return info;
    std::size_t single = 0;
    for (std::uint32_t i = 0; i < info->layerCount; ++i) {
        const XrCompositionLayerBaseHeader* base = info->layers[i];
        if (base && base->type == XR_TYPE_COMPOSITION_LAYER_PROJECTION) {
            const auto* projection = reinterpret_cast<const XrCompositionLayerProjection*>(base);
            if (projection->viewCount == 1 && projection->views) ++single;
        }
    }
    if (!single) return info;
    mono_framegen::RealViews real;
    {
        std::scoped_lock lock(mono_framegen_mutex_);
        if (!mono_framegen_.real_valid || mono_framegen_.session != session) {
            // Not ours (a stereo runtime would reject it anyway): unchanged.
            if (++mono_framegen_.unexpandable <= 3) {
                logger_.Error("Mono Frame Generation: a one-view projection reached the runtime without mono data; "
                              "submitted unchanged.");
            }
            return info;
        }
        real = mono_framegen_.real;
        mono_framegen_.expanded += 1;
    }
    // Reserved first: the projections point into `views`, the frame into both.
    projections.reserve(single);
    views.reserve(single * 2);
    layers.assign(info->layers, info->layers + info->layerCount);
    for (std::uint32_t i = 0; i < info->layerCount; ++i) {
        const XrCompositionLayerBaseHeader* base = info->layers[i];
        if (!base || base->type != XR_TYPE_COMPOSITION_LAYER_PROJECTION) continue;
        const auto* projection = reinterpret_cast<const XrCompositionLayerProjection*>(base);
        if (projection->viewCount != 1 || !projection->views) continue;
        const XrCompositionLayerProjectionView& view0 = projection->views[0];
        views.push_back(view0);
        views.push_back(mono_framegen::SecondView(view0, real));
        projections.push_back(*projection);
        projections.back().viewCount = 2;
        projections.back().views = &views[views.size() - 2];
        layers[i] = reinterpret_cast<const XrCompositionLayerBaseHeader*>(&projections.back());
    }
    storage = *info;
    storage.layers = layers.data();
    return &storage;
}

XrResult OpenXrLayer::TraceRuntimeEndFrame(XrSession session, const XrFrameEndInfo* info) {
''', "definitions")

# 4) Put the selected mono/stereo mode into the stock Frame Generation HUD row
# in both expanded and compact layouts; the standard badge and FPS remain stock.
replace(C,
        "    snapshot.framegen=framegen.row;\n"
        "    snapshot.compact_framegen=framegen.compact;\n"
        "    snapshot.framegen_detail=framegen.detail;\n",
        "    snapshot.framegen=framegen.row;\n"
        "    snapshot.compact_framegen=framegen.compact;\n"
        "    snapshot.framegen_detail=framegen.detail;\n"
        "    if (framegen_owns_pacing_.load(std::memory_order_acquire) &&\n"
        "        !framegen_off_for_toolkit_.load(std::memory_order_acquire)) {\n"
        "        const std::string eye_mode = mono_framegen_active_.load(std::memory_order_acquire) ? \"MONO\" : \"STEREO\";\n"
        "        snapshot.framegen += \"  /  \" + eye_mode;\n"
        "        snapshot.compact_framegen += \"  /  \" + eye_mode;\n"
        "    }\n",
        "stock FG OSD mode")

CM = "layer/CMakeLists.txt"
replace(CM, "        set_tests_properties(depthxr_layer_load_tests PROPERTIES TIMEOUT 30)\n",
        r'''        set_tests_properties(depthxr_layer_load_tests PROPERTIES TIMEOUT 30)
        # Mono Frame Generation (personal patch): shared-image detection and the rebuilt second view.
        add_executable(vectorxr_mono_framegen_tests tests/mono_framegen_tests.cpp)
        target_include_directories(vectorxr_mono_framegen_tests PRIVATE include)
        # The OpenXR headers only: the test calls nothing in the loader.
        target_link_libraries(vectorxr_mono_framegen_tests PRIVATE OpenXR::openxr_loader)
        target_compile_features(vectorxr_mono_framegen_tests PRIVATE cxx_std_20)
        target_compile_definitions(vectorxr_mono_framegen_tests PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
        add_test(NAME vectorxr_mono_framegen_tests COMMAND vectorxr_mono_framegen_tests)
        set_tests_properties(vectorxr_mono_framegen_tests PROPERTIES TIMEOUT 10)
''', "test registration")

for rel, text in files.items():
    (root / rel).write_text(text, encoding="utf-8", newline="")
print("VectorXR mono frame generation patch applied:", ", ".join(sorted(files)))

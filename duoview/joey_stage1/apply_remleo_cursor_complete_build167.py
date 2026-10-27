#!/usr/bin/env python3
"""Build167: guarded Remleo-style full cursor fix on verified v186.1 Build49.
Original STALKER2 mode6, exact pinned backend. No XYZ or failed Build166 code.
Opt-in through existing FrameworkConfig Always Show Cursor.
"""
import argparse
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument("backend",type=Path)
root=p.parse_args().backend/"src"
def edit(rel, old, new, desc):
    path=root/rel
    s=path.read_text(encoding="utf-8-sig")
    n=s.count(old)
    if n!=1:
        raise RuntimeError(f"Build167 anchor {desc} expected one occurrence, got {n} in {rel}")
    path.write_text(s.replace(old,new,1),encoding="utf-8",newline="")
    print(f"BUILD167 {desc}: {rel}")

# Framework: opt-in and fail-closed safetyhook support. No global hooks installed
# when AlwaysShowCursor is OFF, when mode6 inactive, or before the first UI frame.
edit("Framework.hpp",
'''    void patch_set_cursor_pos();
    void remove_set_cursor_pos_patch();
    void post_message''',
'''    void patch_set_cursor_pos();
    void remove_set_cursor_pos_patch();
    // Build167: UEVR's existing cursor, Remleo-style mouse-to-game-window map.
    // All mouse hooks remain dormant until an explicit opt-in in STALKER2 DuoView.
    bool is_duoview_cursor_remap_active() const;
    bool is_duoview_cursor_hooks_ready() const {
        return m_duoview_cursor_hooks_ready.load(std::memory_order_acquire);
    }
    bool should_block_duoview_set_cursor_pos() const {
        return m_duoview_cursor_block_set.load(std::memory_order_acquire);
    }
    void install_duoview_cursor_hooks();
    void map_duoview_cursor_to_game(POINT& pt) const;
    void map_duoview_cursor_from_game(POINT& pt) const;
    LPARAM map_duoview_mouse_message(UINT message, LPARAM l_param) const;
    bool duoview_cursor_map_regions(RECT& client, RECT& visible) const;
    void post_message''',
"Framework cursor helper declarations")

edit("Framework.hpp",
'''    Patch::Ptr m_set_cursor_pos_patch{};

    std::unique_ptr<ThreadWorker<void>>''',
'''    Patch::Ptr m_set_cursor_pos_patch{};
    bool m_duoview_cursor_hooks_tried{false};
    std::atomic<bool> m_duoview_cursor_hooks_ready{false};
    std::atomic<bool> m_duoview_cursor_block_set{false};

    std::unique_ptr<ThreadWorker<void>>''',
"Fail-closed cursor hook state")

edit("Framework.cpp",
'''#include <windows.h>
#include <ShlObj.h>''',
'''#include <windows.h>
#include <windowsx.h>
#include <ShlObj.h>
#include <cmath>''',
"Win32 pointer and coordinate types")
edit("Framework.cpp",
'''#include <spdlog/sinks/basic_file_sink.h>

#include <imgui.h>''',
'''#include <spdlog/sinks/basic_file_sink.h>
#include <SafetyHook.hpp>

#include <imgui.h>''',
"Original vendored SafetyHook library")

hooks=r'''
// Build167: independent small equivalent of Remleo's complete Windows cursor
// handling. Remleo discovered that the window may be wider than the display,
// requiring BOTH GetCursorPos and WM_MOUSE* message mapping for hit-testing.
// These global hooks do NOTHING outside opted-in Stalker2 DuoView mode6.
namespace {
safetyhook::InlineHook g_duoview_get_cursor_hook{};
safetyhook::InlineHook g_duoview_set_cursor_hook{};

BOOL WINAPI duoview_get_cursor_hook(LPPOINT pt) {
    const BOOL result = g_duoview_get_cursor_hook.call<BOOL>(pt);
    if (result && pt != nullptr && g_framework &&
        g_framework->is_duoview_cursor_hooks_ready() &&
        g_framework->is_duoview_cursor_remap_active()) {
        g_framework->map_duoview_cursor_to_game(*pt);
    }
    return result;
}

BOOL WINAPI duoview_set_cursor_hook(int x, int y) {
    if (g_framework && g_framework->is_duoview_cursor_hooks_ready() &&
        g_framework->is_duoview_cursor_remap_active()) {
        if (g_framework->should_block_duoview_set_cursor_pos()) {
            return TRUE;
        }
        POINT pt{x,y};
        g_framework->map_duoview_cursor_from_game(pt);
        x=pt.x; y=pt.y;
    }
    return g_duoview_set_cursor_hook.call<BOOL>(x,y);
}

LONG duoview_remap_span(LONG v,LONG from0,LONG from1,LONG to0,LONG to1) {
    const auto from=from1-from0, to=to1-to0;
    if (from<=1 || to<=1 || from==to) return v+(to0-from0);
    return to0+(LONG)std::lround((double)(v-from0)*(to-1)/(from-1));
}
}

bool Framework::is_duoview_cursor_remap_active() const {
    const auto vr=VR::get();
    return !m_draw_ui && FrameworkConfig::get()->is_always_show_cursor() &&
        vr && vr->is_duoview_renderer_active();
}

void Framework::install_duoview_cursor_hooks() {
    std::scoped_lock lock{m_patch_mtx};
    if (m_duoview_cursor_hooks_tried) return;
    m_duoview_cursor_hooks_tried=true;

    const auto dll=GetModuleHandleW(L"user32.dll");
    const auto p_get=dll ? (void*)GetProcAddress(dll,"GetCursorPos") : nullptr;
    const auto p_set=dll ? (void*)GetProcAddress(dll,"SetCursorPos") : nullptr;
    if (p_get && p_set) {
        // Fail closed. If either hook cannot be placed, both detours continue
        // forwarding unchanged and the old stock cursor logic stays enabled.
        g_duoview_get_cursor_hook=safetyhook::create_inline(p_get,(void*)duoview_get_cursor_hook);
        g_duoview_set_cursor_hook=safetyhook::create_inline(p_set,(void*)duoview_set_cursor_hook);
    }
    const bool ok=bool(g_duoview_get_cursor_hook) && bool(g_duoview_set_cursor_hook);
    m_duoview_cursor_hooks_ready.store(ok,std::memory_order_release);
    spdlog::info("[DuoView Cursor167] Windows Get/SetCursorPos hooks {}",ok ? "ready" : "unavailable, stock fallback");
}

bool Framework::duoview_cursor_map_regions(RECT& client,RECT& visible) const {
    if (!is_duoview_cursor_hooks_ready() ||
        !is_duoview_cursor_remap_active() || !m_wnd) return false;
    RECT c{};
    POINT origin{0,0};
    if (!GetClientRect(m_wnd,&c) || !ClientToScreen(m_wnd,&origin)) return false;
    client={origin.x,origin.y,origin.x+c.right,origin.y+c.bottom};
    if (client.right<=client.left || client.bottom<=client.top) return false;
    const RECT desktop{
        GetSystemMetrics(SM_XVIRTUALSCREEN),GetSystemMetrics(SM_YVIRTUALSCREEN),
        GetSystemMetrics(SM_XVIRTUALSCREEN)+GetSystemMetrics(SM_CXVIRTUALSCREEN),
        GetSystemMetrics(SM_YVIRTUALSCREEN)+GetSystemMetrics(SM_CYVIRTUALSCREEN)};
    if (!IntersectRect(&visible,&client,&desktop)) return false;
    return (visible.right-visible.left)<(client.right-client.left) ||
           (visible.bottom-visible.top)<(client.bottom-client.top);
}

void Framework::map_duoview_cursor_to_game(POINT& pt) const {
    RECT client{},visible{};
    if (!duoview_cursor_map_regions(client,visible)) return;
    pt.x=duoview_remap_span(pt.x,visible.left,visible.right,client.left,client.right);
    pt.y=duoview_remap_span(pt.y,visible.top,visible.bottom,client.top,client.bottom);
}

void Framework::map_duoview_cursor_from_game(POINT& pt) const {
    RECT client{},visible{};
    if (!duoview_cursor_map_regions(client,visible)) return;
    pt.x=duoview_remap_span(pt.x,client.left,client.right,visible.left,visible.right);
    pt.y=duoview_remap_span(pt.y,client.top,client.bottom,visible.top,visible.bottom);
}

LPARAM Framework::map_duoview_mouse_message(UINT message,LPARAM value) const {
    bool client_coords=false;
    switch(message) {
    case WM_MOUSEMOVE:
    case WM_LBUTTONDOWN: case WM_LBUTTONUP: case WM_LBUTTONDBLCLK:
    case WM_RBUTTONDOWN: case WM_RBUTTONUP: case WM_RBUTTONDBLCLK:
    case WM_MBUTTONDOWN: case WM_MBUTTONUP: case WM_MBUTTONDBLCLK:
    case WM_XBUTTONDOWN: case WM_XBUTTONUP: case WM_XBUTTONDBLCLK:
        client_coords=true; break;
    case WM_MOUSEWHEEL: case WM_MOUSEHWHEEL: break;
    default: return value;
    }
    RECT client{},visible{};
    if (!duoview_cursor_map_regions(client,visible)) return value;
    POINT pt{GET_X_LPARAM(value),GET_Y_LPARAM(value)};
    if(client_coords){pt.x+=client.left;pt.y+=client.top;}
    pt.x=duoview_remap_span(pt.x,visible.left,visible.right,client.left,client.right);
    pt.y=duoview_remap_span(pt.y,visible.top,visible.bottom,client.top,client.bottom);
    if(client_coords){pt.x-=client.left;pt.y-=client.top;}
    return MAKELPARAM((SHORT)pt.x,(SHORT)pt.y);
}

'''
path=root/"Framework.cpp"
s=path.read_text(encoding="utf-8")
anchor="void Framework::patch_set_cursor_pos() {"
assert s.count(anchor)==1
s=s.replace(anchor,hooks+anchor,1)
path.write_text(s,encoding="utf-8",newline="")
print("BUILD167 Windows mapping and lazily installed complete hooks")

edit("Framework.cpp",
'''void Framework::set_mouse_to_center() {
    if (m_wnd == nullptr) {
        return;
    }

    RECT rect{};
    GetWindowRect(m_wnd, &rect);

    int x = (rect.left + rect.right) / 2;
    int y = (rect.top + rect.bottom) / 2;''',
'''void Framework::set_mouse_to_center() {
    if (m_wnd == nullptr) {
        return;
    }

    RECT rect{};
    GetWindowRect(m_wnd, &rect);

    int x = (rect.left + rect.right) / 2;
    int y = (rect.top + rect.bottom) / 2;
    if (m_duoview_cursor_hooks_ready.load(std::memory_order_acquire)) {
        POINT pt{x,y};
        map_duoview_cursor_from_game(pt);
        // UEVR's explicit centering bypasses our opt-in game SetCursorPos block.
        g_duoview_set_cursor_hook.call<BOOL>(pt.x,pt.y);
        return;
    }''',
"Center cursor without our hook recursion")

edit("Framework.cpp",
'''    if (!m_draw_ui) {
        // remove SetCursorPos patch
        if (!FrameworkConfig::get()->is_always_show_cursor()) {
            remove_set_cursor_pos_patch();
        } else {
            patch_set_cursor_pos();
        }

        m_is_ui_focused = false;''',
'''    if (!m_draw_ui) {
        if (is_duoview_cursor_remap_active()) {
            // Never combine the old global RET patch with SafetyHook.
            remove_set_cursor_pos_patch();
            install_duoview_cursor_hooks();
            const bool ready = m_duoview_cursor_hooks_ready.load(std::memory_order_acquire);
            m_duoview_cursor_block_set.store(ready,std::memory_order_release);
            if (!ready) patch_set_cursor_pos(); // harmless original fallback
        } else {
            m_duoview_cursor_block_set.store(false,std::memory_order_release);
            // Exact original behavior outside STALKER2 DuoView opt-in.
            if (!FrameworkConfig::get()->is_always_show_cursor()) {
                remove_set_cursor_pos_patch();
            } else {
                patch_set_cursor_pos();
            }
        }

        m_is_ui_focused = false;''',
"Only enable complete mapping while opted in, original fallback otherwise")

edit("Framework.cpp",
'''    // UI Specific code:
    m_is_ui_focused = ImGui::IsWindowFocused(ImGuiFocusedFlags_AnyWindow);''',
'''    m_duoview_cursor_block_set.store(false,std::memory_order_release);
    // UI Specific code:
    m_is_ui_focused = ImGui::IsWindowFocused(ImGuiFocusedFlags_AnyWindow);''',
"Preserve normal UEVR overlay input on menu-open")

# Windows mouse messages MUST be mapped too. Old Build166 omitted this,
# making hit-testing fail when the render window exceeds monitor bounds.
edit("hooks/WindowsMessageHook.cpp",
'''    // Call our onMessage callback.
    auto& on_message = g_windows_message_hook->on_message;''',
'''    // Build167: Remleo-compatible message coordinates for oversized game
    // windows. The method is an exact no-op when our cursor fix is inactive.
    if (g_framework != nullptr) {
        l_param = g_framework->map_duoview_mouse_message(message,l_param);
    }

    // Call our onMessage callback.
    auto& on_message = g_windows_message_hook->on_message;''',
"Route both mouse messages and cursor position through same map")

# Game UI / cursor quad: copy the actual current submission, not a stale
# previous frame, and NEVER change the game projection or compositor source.
edit("mods/vr/OverlayComponent.hpp",
'''        std::optional<std::reference_wrapper<XrCompositionLayerQuad>> generate_framework_ui_quad();

    private:
        XrCompositionLayerQuad m_slate_layer{};''',
'''        std::optional<std::reference_wrapper<XrCompositionLayerQuad>> generate_framework_ui_quad();
        void begin_duoview_cursor_submit() { m_duoview_game_ui_quad_valid=false; }

    private:
        bool m_duoview_game_ui_quad_valid{false};
        XrCompositionLayerQuad m_slate_layer{};''',
"Reset game UI quad readiness before each D3D12 submission")

edit("mods/vr/OverlayComponent.cpp",
'''#include "Framework.hpp"
#include "../VR.hpp"''',
'''#include "Framework.hpp"
#include "../FrameworkConfig.hpp"
#include "../VR.hpp"''',
"Read existing Always Show Cursor option")

edit("mods/vr/OverlayComponent.cpp",
'''void OverlayComponent::OpenXR::reset_daysgone_ahud_pose() {
    m_daysgone_ahud_pose_basis = {};
}''',
'''void OverlayComponent::OpenXR::reset_daysgone_ahud_pose() {
    m_daysgone_ahud_pose_basis = {};
    m_duoview_game_ui_quad_valid=false;
}''',
"Discard stale UI quad after runtime/device reset")

path=root/"mods/vr/OverlayComponent.cpp"
s=path.read_text(encoding="utf-8")
start=s.index("std::optional<std::reference_wrapper<XrCompositionLayerQuad>> OverlayComponent::OpenXR::generate_slate_quad(")
end=s.index("std::optional<std::reference_wrapper<XrCompositionLayerCylinderKHR>> OverlayComponent::OpenXR::generate_slate_cylinder(",start)
part=s[start:end]
old='''    layer.pose.orientation = runtimes::OpenXR::to_openxr(glm::quat_cast(glm_matrix));
    layer.pose.position = runtimes::OpenXR::to_openxr(glm_matrix[3]);

    vr->record_ui_layer_pose_sample('''
new='''    layer.pose.orientation = runtimes::OpenXR::to_openxr(glm::quat_cast(glm_matrix));
    layer.pose.position = runtimes::OpenXR::to_openxr(glm_matrix[3]);

    // GAME quad's actual final pose (including optical convergence) for THIS
    // compositor submission. Unlike Build166 no unreliable HMD frame token.
    if (vr->is_duoview_renderer_active() &&
        swapchain == runtimes::OpenXR::SwapchainIndex::UI &&
        eye == XR_EYE_VISIBILITY_BOTH) {
        m_duoview_game_ui_quad_valid=true;
    }

    vr->record_ui_layer_pose_sample('''
assert part.count(old)==1
part=part.replace(old,new,1)
s=s[:start]+part+s[end:]
start=s.index("std::optional<std::reference_wrapper<XrCompositionLayerQuad>> OverlayComponent::OpenXR::generate_framework_ui_quad()")
part=s[start:]
old='''    layer.layerFlags = XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT;
    layer.eyeVisibility = XrEyeVisibility::XR_EYE_VISIBILITY_BOTH;

    auto glm_matrix = glm::identity<glm::mat4>();'''
new='''    layer.layerFlags = XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT;
    layer.eyeVisibility = XrEyeVisibility::XR_EYE_VISIBILITY_BOTH;

    // Build167: match Remleo's cursor-to-game-plane approach, but fail closed.
    // With the menu closed the framework target contains ONLY the ImGui mouse
    // pointer. Do not submit ANY pointer quad if the current compositor submit
    // did not generate a valid game UI quad (prevents a stale/full-screen layer).
    if (!g_framework->is_drawing_ui() &&
        FrameworkConfig::get()->is_always_show_cursor() &&
        vr->is_duoview_renderer_active()) {
        if (!m_duoview_game_ui_quad_valid ||
            m_slate_layer.type != XR_TYPE_COMPOSITION_LAYER_QUAD ||
            m_slate_layer.eyeVisibility != XR_EYE_VISIBILITY_BOTH ||
            m_slate_layer.space == XR_NULL_HANDLE ||
            m_slate_layer.subImage.swapchain !=
                vr->m_openxr->swapchains[(uint32_t)runtimes::OpenXR::SwapchainIndex::UI].handle ||
            !std::isfinite(m_slate_layer.size.width) ||
            !std::isfinite(m_slate_layer.size.height) ||
            m_slate_layer.size.width <= 0 || m_slate_layer.size.height <= 0) {
            m_parent->m_framework_intersect_state.intersecting=false;
            return std::nullopt;
        }

        // Both textures must have the same aspect for pixel-perfect clicks.
        const auto game_width=m_slate_layer.subImage.imageRect.extent.width;
        const auto game_height=m_slate_layer.subImage.imageRect.extent.height;
        if (game_width <= 0 || game_height <= 0 ||
            ui_swapchain.width==0 || ui_swapchain.height==0 ||
            std::abs((double)game_width/game_height -
                     (double)ui_swapchain.width/ui_swapchain.height)>0.02) {
            m_parent->m_framework_intersect_state.intersecting=false;
            return std::nullopt;
        }
        layer.space=m_slate_layer.space;
        layer.pose=m_slate_layer.pose;
        layer.size=m_slate_layer.size;
        const auto& q=layer.pose.orientation;
        const glm::quat rotation{q.w,q.x,q.y,q.z};
        const glm::vec3 to_user=rotation*glm::vec3{0.f,0.f,0.01f};
        layer.pose.position.x+=to_user.x;
        layer.pose.position.y+=to_user.y;
        layer.pose.position.z+=to_user.z;
        m_parent->m_framework_intersect_state.intersecting=false;
        return layer;
    }

    // No modifications to the original renderer outside active cursor fix.
    auto glm_matrix = glm::identity<glm::mat4>();'''
assert part.count(old)==1
part=part.replace(old,new,1)
s=s[:start]+part
path.write_text(s,encoding="utf-8",newline="")
print("BUILD167 copy complete Remleo UI pose/size in same compositor submit")

edit("mods/vr/D3D12Component.cpp",
'''            auto& openxr_overlay = vr->get_overlay_component().get_openxr();

            if (vr->m_2d_screen_mode->value())''',
'''            auto& openxr_overlay = vr->get_overlay_component().get_openxr();
            openxr_overlay.begin_duoview_cursor_submit();

            if (vr->m_2d_screen_mode->value())''',
"Invalidate previous UI plane at start of current D3D12 layer submission")

print("PASS applied Build167 Remleo cursor source (Framework/Win32/Overlay/D3D12), all changes opt-in and guarded.")

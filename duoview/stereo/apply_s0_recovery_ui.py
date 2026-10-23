#!/usr/bin/env python3
"""UI-only recovery for S0: bounded diagnostic pane and explicit state messaging.

Applied AFTER P1 capture, P1 visual and S0 preview source adapters.
The native renderer, frame transactions, OpenXR and UI settings remain untouched.
"""
from pathlib import Path
import argparse

def edit(root, relative, old, new):
    p=root/relative
    s=p.read_text(encoding="utf-8-sig")
    count=s.count(old)
    if count!=1:
        raise RuntimeError(f"S0 UI source drift: {relative}, anchor seen {count} times: {old[:90]}")
    p.write_text(s.replace(old,new,1),encoding="utf-8",newline="\n")

def closing_brace(s,opening):
    level=0
    i=opening
    state="normal"
    while i<len(s):
        ch=s[i]; nxt=s[i+1] if i+1<len(s) else ""
        if state=="line":
            if ch=="\n":state="normal"
        elif state=="block":
            if ch=="*" and nxt=="/":state="normal";i+=1
        elif state=="string":
            if ch=="\\":i+=1
            elif ch=='"':state="normal"
        elif state=="char":
            if ch=="\\":i+=1
            elif ch=="'":state="normal"
        else:
            if ch=="/" and nxt=="/":state="line";i+=1
            elif ch=="/" and nxt=="*":state="block";i+=1
            elif ch=='"':state="string"
            elif ch=="'":state="char"
            elif ch=="{":level+=1
            elif ch=="}":
                level-=1
                if level==0:return i
        i+=1
    raise RuntimeError("Unbalanced P1 diagnostics tree")

def apply(root):
    target=root/"src/mods/VR.cpp"
    src=target.read_text(encoding="utf-8-sig")
    marker='if (ImGui::TreeNode("DuoView P1 owned depth capture (experimental)")) {'
    if src.count(marker)!=1: raise RuntimeError("P1 panel source drift")
    pos=src.index(marker)
    opening=pos+len(marker)-1
    closing=closing_brace(src,opening)
    chunk=src[opening+1:closing]
    pop=chunk.rfind("ImGui::TreePop();")
    if pop<0:raise RuntimeError("P1 diagnostic tree missing closing TreePop")
    # A child window prevents verbose probe output from expanding the entire
    # UEVR sidebar beyond monitor height, and provides its own mouse-wheel bar.
    chunk=("""\n                    ImGui::BeginChild("##DuoViewDepthDiagnosticsScroll",
                        ImVec2(0.0f, 244.0f), true,
                        ImGuiWindowFlags_AlwaysVerticalScrollbar);"""
           +chunk[:pop]+"""ImGui::EndChild();
                    """+chunk[pop:])
    src=src[:opening+1]+chunk+src[closing:]
    pos=src.index(marker)
    src=src[:pos]+"ImGui::SetNextItemOpen(false, ImGuiCond_Once);\n                "+src[pos:]
    target.write_text(src,encoding="utf-8",newline="\n")

    # Show why stereo is not activating immediately, even if the user has not
    # expanded the diagnostic pane or missed the zero-capture counter.
    edit(root,"src/mods/VR.cpp",
        '                    m_duo_center_stereo_strength->draw("S0 test strength: 0..40% (8% initial)");',
        '''                    m_duo_center_stereo_strength->draw("S0 test strength: 0..40% (8% initial)");
                    if (m_duo_center_stereo_preview->value() &&
                        !d3d12().duoview_p1_gpu_ready()) {
                        ImGui::TextColored(ImVec4(1.f,.65f,.14f,1.f),
                            "S0 BLOCKED: no completed GPU depth pair (0/2 or not fence-ready).");
                        ImGui::TextWrapped("Eye Output Check is independent. Turn it OFF for depth experiments.");
                    }''')

    # Read-only Unreal console-variable survey. Unlike the observed OpenXR
    # swapchain extent, these numbers were NOT included in earlier Build97 logs.
    # Never treat a missing DLSS CVar as DLSS disabled.
    edit(root,"src/mods/VR.cpp",
        '                ImGui::TextWrapped("This confirms two different eye images reach OpenXR. It requires no depth and is NOT a stereo-geometry test.");',
        '''                ImGui::TextWrapped("This confirms two different eye images reach OpenXR. It requires no depth and is NOT a stereo-geometry test.");
                if (ImGui::Button("Log UE screen percentage and DLSS CVars (read-only)")) {
                    const float sp = get_runtime_cvar_float(L"r.ScreenPercentage").value_or(-1.f);
                    const float secondary_sp = get_runtime_cvar_float(L"r.SecondaryScreenPercentage.GameViewport").value_or(-1.f);
                    const int dynamic_mode = get_runtime_cvar_int(L"r.DynamicRes.OperationMode").value_or(-1);
                    const int taa_upscale = get_runtime_cvar_int(L"r.TemporalAA.Upsampling").value_or(-1);
                    const int dlss_enable = get_runtime_cvar_int(L"r.NGX.DLSS.Enable").value_or(-1);
                    const int dlss_quality = get_runtime_cvar_int(L"r.NGX.DLSS.Quality").value_or(-1);
                    const int streamline_dlss = get_runtime_cvar_int(L"r.Streamline.DLSS.Enable").value_or(-1);
                    const int temporal_upscale = get_runtime_cvar_int(L"r.TemporalAA.Upscaler").value_or(-1);
                    const auto* runtime = get_runtime();
                    SPDLOG_INFO("[StereoScaleSurvey][READONLY] xr_eye={}x{} r.ScreenPercentage={} r.SecondaryScreenPercentage.GameViewport={} r.DynamicRes.OperationMode={} r.TemporalAA.Upsampling={} r.TemporalAA.Upscaler={} r.NGX.DLSS.Enable={} r.NGX.DLSS.Quality={} r.Streamline.DLSS.Enable={} (-1=unavailable, NOT disabled)",
                        runtime ? runtime->get_width() : 0,
                        runtime ? runtime->get_height() : 0,
                        sp, secondary_sp, dynamic_mode, taa_upscale,
                        temporal_upscale, dlss_enable, dlss_quality, streamline_dlss);
                    ImGui::TextUnformatted("Logged raw UE CVars once. -1 = not exposed; no settings changed.");
                }''')
    print("S0 UI recovery: default-closed P1 diagnostics, 244px scrollable pane, missing-depth warning, read-only Unreal scale CVars.")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("backend",type=Path)
    apply(ap.parse_args().backend)

#!/usr/bin/env python3
"""Goal D (2026-11-18): improve Off. Switch 1 = fovea depth grid 1024 / 4096.

Plan + pre-registered criteria: workspace research/edge-fix/54_goalD_plan.md; diagnosis 55_.
Default 1024 = the unchanged baseline path: same PSOs, same descriptors, same DXBC.
4096 = the M4 fovea depth field is conditioned at up to 4096 texels per axis (allocated to
the fine NGX rect, ~1:1; the baseline fits 1625x1435 into 1024x904). Production Stereo V2
path only; anything else falls back to 1024 with a logged reason.

Off identity: new HLSL lives only inside `#ifdef DUOVIEW_GOALD_GRID` and is compiled into
separate, appended DXBC arrays (m4g_*); strip_goald(shader) must equal the input shader.
Also: GPU timestamps around the M4 conditioning passes (criterion C4), log + menu status.
Evidence level of this file: compiled locally (overlay + FXC); CI/headset pending.
"""
import argparse
from pathlib import Path

TAG = 'DUOVIEW_GOALD_GRID'


def once(src, old, new, what):
    n = src.count(old)
    if n != 1:
        raise RuntimeError(f'goal D anchor "{what}": {n} matches')
    return src.replace(old, new, 1)


def edit(path, fn):
    # Keep the file's line endings (generated sources are pure CRLF on Windows), so the
    # generated diff shows only goal D lines. Anchors are written with '\n'.
    raw = path.read_bytes().decode('utf-8')
    crlf = raw.count('\n') > 0 and raw.count('\r\n') == raw.count('\n')
    out = fn(raw.replace('\r\n', '\n') if crlf else raw)
    if crlf:
        out = out.replace('\n', '\r\n')
    path.write_bytes(out.encode('utf-8'))


# ---------------------------------------------------------------- shader
def shader(src):
    body = Path(__file__).with_name('DuoViewGoalDGrid.hlsl').read_text(encoding='utf-8')
    if not body.endswith('\n'):
        body += '\n'
    return once(src, '\n#endif\n\n#ifdef DUOVIEW_M1_RASTER',
                f'\n#ifdef {TAG}\n{body}#endif\n#endif\n\n#ifdef DUOVIEW_M1_RASTER',
                'end of the conditioning block')


def strip_goald(src):
    out, inside = [], False
    for line in src.splitlines(keepends=True):
        tag = line.strip()
        if tag == f'#ifdef {TAG}':
            if inside:
                raise RuntimeError('nested goal D block')
            inside = True
            continue
        if inside and tag == '#endif':
            inside = False
            continue
        if not inside:
            out.append(line)
    if inside:
        raise RuntimeError('unterminated goal D block')
    return ''.join(out)


# ---------------------------------------------------------------- M1 resources
M1_MEMBERS = r'''    ComPtr<ID3D12Resource> m4_depth;
    // ---- Goal D switch 1: optional M4 fovea field up to 4096 per axis. Single
    // slice (V2 conditions both eyes alike; slice-1 reads clamp to slice 0),
    // allocated to the fine rect on first use, grown only when a larger rect needs it.
    static constexpr uint32_t goald_grid_limit = 4096;
    ComPtr<ID3D12PipelineState> m4g_condition, m4g_vertical;
    ComPtr<ID3D12Resource> m4_depth_hi;
    bool m4_hi_active{};
    uint32_t m4_hi_generation{};
    // 0 none/1024, 1 needs Stereo V2 depth policy, 2 pipeline missing,
    // 3 GPU allocation failed, 4 M4 fovea depth grid off or no fine depth
    uint32_t goald_grid_reason{};
    inline static std::atomic<uint64_t> goald_m4_gpu_ns{}, goald_m4_gpu_samples{}, goald_hi_frames{};
    static void goald_note_m4_gpu(double ns) {
        if (ns>=0. && ns<1.e9) { goald_m4_gpu_ns+=uint64_t(ns); ++goald_m4_gpu_samples; }
    }
    ID3D12Resource* m4_field() const { return m4_hi_active && m4_depth_hi ? m4_depth_hi.Get() : m4_depth.Get(); }
    uint32_t m4_field_key() const { return m4_hi_active && m4_depth_hi ? (m4_hi_generation<<1u)|1u : 0u; }
    bool goald_ensure_field(ID3D12Device* device, uint32_t fw, uint32_t fh) {
        const uint32_t need_w=(std::min)(goald_grid_limit,(fw+127u)&~127u);
        const uint32_t need_h=(std::min)(goald_grid_limit,(fh+127u)&~127u);
        uint32_t w=need_w, h=need_h;
        if (m4_depth_hi) {
            const auto d=m4_depth_hi->GetDesc();
            if (d.Width>=need_w && d.Height>=need_h) return true;
            w=(std::max)(uint32_t(d.Width),need_w); h=(std::max)(d.Height,need_h);
        }
        // This M1Resources belongs to one fenced XR command slot that has retired
        // before it records again, and the compositor rewrites this slot's t8/u5
        // descriptors (new m4_hi_generation) before any use: release is safe.
        m4_depth_hi.Reset();
        D3D12_HEAP_PROPERTIES heap{};
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC t{};
        t.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        t.Width=w; t.Height=h; t.DepthOrArraySize=1; t.MipLevels=1;
        t.Format=DXGI_FORMAT_R32_FLOAT; t.SampleDesc.Count=1;
        t.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&t,
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,nullptr,IID_PPV_ARGS(&m4_depth_hi)))) {
            m4_depth_hi.Reset();
            return false;
        }
        m4_depth_hi->SetName(L"DuoView::GoalDFoveaField4096");
        ++m4_hi_generation;
        return true;
    }
'''

M1_PSO = r'''        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4_vertical)))) m4_vertical.Reset();
        // Goal D switch 1: optional; failure only keeps the 1024 field.
        compute.CS={m4g_condition_bytecode,sizeof(m4g_condition_bytecode)};
        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4g_condition)))) m4g_condition.Reset();
        compute.CS={m4g_vertical_bytecode,sizeof(m4g_vertical_bytecode)};
        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4g_vertical)))) m4g_vertical.Reset();
'''

M1_FIELD_CHOICE = r'''            const float fw=float(focus->rect[2]), fh=float(focus->rect[3]);
            // Goal D switch 1 (default 1024 = unchanged baseline field and PSOs).
            goald_grid_reason=0u;
            if(depth_grid>=4096u) {
                if(edge_reach_px<10.f || m3_edges) goald_grid_reason=1u; // not Stereo V2 depth policy
                else if(!m4g_condition || !m4g_vertical) goald_grid_reason=2u;
                else if(!goald_ensure_field(device,focus->rect[2],focus->rect[3])) goald_grid_reason=3u;
                else m4_hi_active=true;
            }
            const auto field=m4_field()->GetDesc();
'''


def m1_backend(src):
    src = once(src, '    ComPtr<ID3D12Resource> m4_depth;\n', M1_MEMBERS, 'goal D members')
    src = once(src,
               '        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4_vertical)))) m4_vertical.Reset();\n',
               M1_PSO, 'goal D pipelines')
    src = once(src, '                         float eye_near,float eye_far) {',
               '                         float eye_near,float eye_far,uint32_t depth_grid=1024u) {',
               'goal D grid argument')
    src = once(src, '        m4_active=false; m4_columns=m4_rows=0;\n',
               '        m4_active=false; m4_columns=m4_rows=0;\n'
               '        m4_hi_active=false;\n'
               '        goald_grid_reason=depth_grid>=4096u ? 4u : 0u;\n',
               'goal D per-frame reset')
    src = once(src,
               '            const auto field=m4_depth->GetDesc();\n'
               '            const float fw=float(focus->rect[2]), fh=float(focus->rect[3]);\n',
               M1_FIELD_CHOICE, 'goal D field choice')
    src = once(src,
               '            m4_last_w=w4; m4_last_h=h4; m4_fine_w=focus->rect[2]; m4_fine_h=focus->rect[3];\n',
               '            m4_last_w=w4; m4_last_h=h4; m4_fine_w=focus->rect[2]; m4_fine_h=focus->rect[3];\n'
               '            if(m4_hi_active) ++goald_hi_frames;\n',
               'goal D frame counter')
    return src


# ---------------------------------------------------------------- compositor
COMPOSITOR_METHODS = r'''    // ---- Goal D switch 1: this slot's t8/u5 descriptors follow the M4 field in
    // use. Rewritten on the CPU before any descriptor table is set this frame;
    // the slot's previous GPU work has retired (fenced XR slot).
    void goald_bind_m4_field(ID3D12Device* device) {
        const uint32_t key=m1_.m4_field_key();
        ID3D12Resource* field=m1_.m4_field();
        if (key==goald_bound_key_ || !field || !goald_m4_srv_cpu_.ptr || !goald_m4_uav_cpu_.ptr) return;
        auto srv=goald_srv_desc_;
        auto uav=goald_uav_desc_;
        const UINT slices=field->GetDesc().DepthOrArraySize;
        srv.Texture2DArray.ArraySize=slices;
        uav.Texture2DArray.ArraySize=slices;
        device->CreateShaderResourceView(field,&srv,goald_m4_srv_cpu_);
        device->CreateUnorderedAccessView(field,nullptr,&uav,goald_m4_uav_cpu_);
        goald_bound_key_=key;
    }
    void goald_report_status(uint32_t depth_grid, bool m1_active) {
        const bool requested=depth_grid>=4096u;
        const bool effective=m1_active && m1_.m4_active && m1_.m4_hi_active;
        uint32_t reason=m1_active ? m1_.goald_grid_reason : 5u;
        if (!requested) reason=0u;
        duo_goald_status().store((1u<<31)|(requested?1u:0u)|(effective?2u:0u)|((reason&15u)<<2),
                                 std::memory_order_relaxed);
        if (effective) {
            const auto d=m1_.m4_depth_hi->GetDesc();
            duo_goald_field().store((uint32_t(d.Width)<<16)|(d.Height&0xffffu),std::memory_order_relaxed);
        }
        if (m1_active && m1_.m4_active)
            duo_goald_grid().store((m1_.m4_columns<<16)|(m1_.m4_rows&0xffffu),std::memory_order_relaxed);
    }
public:
    // Test accessors (WARP fixture): read-only.
    bool goald_m4_hi_active() const { return m1_.m4_active && m1_.m4_hi_active; }
    uint32_t goald_m4_columns() const { return m1_.m4_columns; }
    uint32_t goald_m4_rows() const { return m1_.m4_rows; }
    ID3D12Resource* goald_m4_field() const { return m1_.m4_field(); }
private:
    void update_timing(bool timed, bool direct_xr) {'''


def compositor_backend(src):
    src = once(src, '                settings.m9_eye_near,settings.m9_eye_far);\n',
               '                settings.m9_eye_near,settings.m9_eye_far,settings.goald_depth_grid);\n'
               '        if (m1_active) goald_bind_m4_field(device);\n'
               '        goald_report_status(settings.goald_depth_grid,m1_active);\n',
               'goal D write_constants argument')
    # M4 dispatch: field resource, PSOs and timestamps 2/3 around both passes.
    src = once(src,
               '            if(m1_.m4_active) {\n'
               '                transition(cmd,m1_.m4_depth.Get(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,\n',
               '            if(m1_.m4_active) {\n'
               '                goald_m4_timed_=timed;\n'
               '                if(timed) cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2);\n'
               '                transition(cmd,m1_.m4_field(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,\n',
               'goal D M4 field before')
    src = once(src, '                ID3D12PipelineState* m4_gpu_pso=m1_.m4_condition.Get();\n',
               '                ID3D12PipelineState* m4_gpu_pso=m1_.m4_hi_active ? m1_.m4g_condition.Get() : m1_.m4_condition.Get();\n',
               'goal D condition PSO')
    src = once(src, '                    m4_uav.UAV.pResource=m1_.m4_depth.Get();\n',
               '                    m4_uav.UAV.pResource=m1_.m4_field();\n', 'goal D UAV barrier')
    src = once(src, '                    cmd->SetPipelineState(m1_.m4_vertical.Get());\n',
               '                    cmd->SetPipelineState(m1_.m4_hi_active ? m1_.m4g_vertical.Get() : m1_.m4_vertical.Get());\n',
               'goal D vertical PSO')
    src = once(src,
               '                transition(cmd,m1_.m4_depth.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,\n'
               '                           D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);\n'
               '                M1Resources::m4_count_frame();\n',
               '                transition(cmd,m1_.m4_field(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,\n'
               '                           D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);\n'
               '                if(timed) cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,3);\n'
               '                M1Resources::m4_count_frame();\n',
               'goal D M4 field after')
    if src.count('m1_.m4_depth.Get()') != 2:  # only the setup descriptors (t8, u5) remain
        raise RuntimeError(f'goal D: unexpected m4_depth uses {src.count("m1_.m4_depth.Get()")}')
    src = once(src,
               '        recorded_commands_=true;\n        if (timed) cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);\n',
               '        recorded_commands_=true;\n        goald_m4_timed_=false;\n'
               '        if (timed) cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);\n',
               'goal D timing reset')
    src = once(src,
               '            cmd->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timestamps_.Get(),0);\n'
               '            timing_pending_=true; pending_direct_xr_=direct_xr;\n',
               '            cmd->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timestamps_.Get(),0);\n'
               '            if (goald_m4_timed_)\n'
               '                cmd->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2,2,timestamps_.Get(),2*sizeof(UINT64));\n'
               '            timing_pending_=true; pending_direct_xr_=direct_xr; goald_m4_pending_=goald_m4_timed_;\n',
               'goal D resolve')
    src = once(src, '            timing_pending_=false;\n            gpu_ms_=-1.f;\n',
               '            timing_pending_=false;\n            goald_m4_pending_=false;\n            gpu_ms_=-1.f;\n',
               'goal D timing invalidation')
    src = once(src, '        D3D12_RANGE range{0, sizeof(UINT64) * 2};\n',
               '        D3D12_RANGE range{0, sizeof(UINT64) * 4};\n', 'goal D map range')
    src = once(src,
               '            if (data[1] >= data[0]) gpu_ms_ = static_cast<float>((data[1] - data[0]) * 1000.0 / frequency_);\n',
               '            if (data[1] >= data[0]) gpu_ms_ = static_cast<float>((data[1] - data[0]) * 1000.0 / frequency_);\n'
               '            if (goald_m4_pending_ && data[3] >= data[2])\n'
               '                M1Resources::goald_note_m4_gpu(double(data[3] - data[2]) * 1.0e9 / double(frequency_));\n',
               'goal D read M4 timing')
    src = once(src, '        timing_pending_ = false;\n    }\n',
               '        timing_pending_ = false;\n        goald_m4_pending_ = false;\n    }\n', 'goal D timing consumed')
    src = once(src, 'q.Count = 2;', 'q.Count = 4;', 'goal D query count')
    src = once(src, 'buffer.Width = sizeof(UINT64) * 2;', 'buffer.Width = sizeof(UINT64) * 4;', 'goal D readback size')
    # Remember the setup descriptors so the field can be swapped per slot.
    src = once(src,
               '        desc_cpu.ptr+=srv_descriptor_increment_; // [12] t8 M4 fovea field\n'
               '        device->CreateShaderResourceView(m1_.m4_depth.Get(),&soft_array_srv,desc_cpu);\n',
               '        desc_cpu.ptr+=srv_descriptor_increment_; // [12] t8 M4 fovea field\n'
               '        device->CreateShaderResourceView(m1_.m4_depth.Get(),&soft_array_srv,desc_cpu);\n'
               '        goald_m4_srv_cpu_=desc_cpu; goald_srv_desc_=soft_array_srv;\n',
               'goal D t8 descriptor')
    src = once(src,
               '        desc_cpu.ptr+=srv_descriptor_increment_; // [15] u5 M4 fovea field\n'
               '        device->CreateUnorderedAccessView(m1_.m4_depth.Get(),nullptr,&soft_uav,desc_cpu);\n',
               '        desc_cpu.ptr+=srv_descriptor_increment_; // [15] u5 M4 fovea field\n'
               '        device->CreateUnorderedAccessView(m1_.m4_depth.Get(),nullptr,&soft_uav,desc_cpu);\n'
               '        goald_m4_uav_cpu_=desc_cpu; goald_uav_desc_=soft_uav; goald_bound_key_=0u;\n',
               'goal D u5 descriptor')
    src = once(src, '    void update_timing(bool timed, bool direct_xr) {', COMPOSITOR_METHODS, 'goal D methods')
    src = once(src,
               '    D3D12_CPU_DESCRIPTOR_HANDLE m2_fovea_srv_{}, m6_previous_srv_{}, m7_current_srv_{}, m7_current_uav_{};\n',
               '    D3D12_CPU_DESCRIPTOR_HANDLE m2_fovea_srv_{}, m6_previous_srv_{}, m7_current_srv_{}, m7_current_uav_{};\n'
               '    D3D12_CPU_DESCRIPTOR_HANDLE goald_m4_srv_cpu_{}, goald_m4_uav_cpu_{};\n'
               '    D3D12_SHADER_RESOURCE_VIEW_DESC goald_srv_desc_{};\n'
               '    D3D12_UNORDERED_ACCESS_VIEW_DESC goald_uav_desc_{};\n'
               '    uint32_t goald_bound_key_{};\n'
               '    bool goald_m4_timed_{}, goald_m4_pending_{};\n',
               'goal D compositor state')
    return src


# ---------------------------------------------------------------- settings, menu, log
GOALD_STATUS = r'''
// Goal D status, written by the compositor every frame, read by the UEVR menu.
// status: bit 0 requested 4096, bit 1 effective, bits 2-5 reason, bit 31 written.
// field/grid: (width<<16)|height of the allocated 4096 field / active M4 grid.
inline std::atomic<uint32_t>& duo_goald_status() { static std::atomic<uint32_t> s{0u}; return s; }
inline std::atomic<uint32_t>& duo_goald_field() { static std::atomic<uint32_t> s{0u}; return s; }
inline std::atomic<uint32_t>& duo_goald_grid() { static std::atomic<uint32_t> s{0u}; return s; }
inline const char* duo_goald_reason_text(uint32_t reason) {
    switch (reason) {
    case 1u: return "NOT ACTIVE - needs the Stereo V2 depth policy (edge reach >= 10 px, per-eye edges off).";
    case 2u: return "NOT ACTIVE - 4096 shader pipeline could not be created.";
    case 3u: return "NOT ACTIVE - GPU memory for the 4096 field could not be allocated.";
    case 4u: return "NOT ACTIVE - turn on full-resolution foveal depth (M4) and wait for fine depth.";
    case 5u: return "NOT ACTIVE - no synthetic stereo frame yet.";
    default: return "NOT ACTIVE.";
    }
}

struct Settings {
'''


def config(src):
    src = once(src, '    float m2_left_sharpen{1.f}, m2_right_sharpen{1.f};\n',
               '    float m2_left_sharpen{1.f}, m2_right_sharpen{1.f};\n'
               '    uint32_t goald_depth_grid{1024}; // goal D: fovea depth grid 1024 (baseline) or 4096\n',
               'goal D settings field')
    src = once(src, '    out.m4_fovea_grid=requested.m4_fovea_grid;\n',
               '    out.m4_fovea_grid=requested.m4_fovea_grid;\n'
               '    out.goald_depth_grid=requested.goald_depth_grid>=4096u ? 4096u : 1024u;\n',
               'goal D settings sanitize')
    if '#include <atomic>' not in src:
        src = once(src, '#include <optional>\n', '#include <optional>\n#include <atomic>\n', 'goal D atomic include')
    src = once(src, '\nstruct Settings {\n', GOALD_STATUS, 'goal D status')
    return src


def vr_hpp(src):
    src = once(src, '    static const inline std::vector<std::string> s_duo_m3_jitter_modes{',
               '    static const inline std::vector<std::string> s_duo_goald_grids{ "1024 (baseline)", "4096 (goal D test)" };\n'
               '    static const inline std::vector<std::string> s_duo_m3_jitter_modes{',
               'goal D grid names')
    src = once(src,
               '    const ModToggle::Ptr m_duo_m4_fovea_grid{ModToggle::create(generate_name("DuoM4FoveaDepthGrid"),false)};\n',
               '    const ModToggle::Ptr m_duo_m4_fovea_grid{ModToggle::create(generate_name("DuoM4FoveaDepthGrid"),false)};\n'
               '    const ModCombo::Ptr m_duo_goald_grid{ModCombo::create(generate_name("DuoFoveaDepthGridSize"),s_duo_goald_grids,0)};\n',
               'goal D grid control')
    src = once(src, '*m_duo_m4_fovea_grid, ', '*m_duo_m4_fovea_grid, *m_duo_goald_grid, ', 'goal D grid persisted')
    return src


GOALD_MENU = r'''                    m_duo_m8_far_m->draw("Depth transition ends (metres)");
                    m_duo_goald_grid->draw("Fovea depth grid (test build: 1024 = baseline, 4096 = goal D)");
                    {
                        const uint32_t gd=uevr::duoview::duo_goald_status().load(std::memory_order_relaxed);
                        const uint32_t gf=uevr::duoview::duo_goald_field().load(std::memory_order_relaxed);
                        const uint32_t gg=uevr::duoview::duo_goald_grid().load(std::memory_order_relaxed);
                        if (!(gd>>31)) ImGui::TextWrapped("Fovea depth grid status: no stereo frame yet.");
                        else if (!(gd&1u)) ImGui::TextWrapped("Fovea depth grid status: 1024 (baseline), field %ux%u.", gg>>16, gg&0xffffu);
                        else if (gd&2u) ImGui::TextWrapped("Fovea depth grid status: ACTIVE 4096 - field %ux%u used, %ux%u allocated.",
                            gg>>16, gg&0xffffu, gf>>16, gf&0xffffu);
                        else ImGui::TextWrapped("Fovea depth grid status: %s", uevr::duoview::duo_goald_reason_text((gd>>2)&15u));
                    }
'''


def vr_cpp(src):
    src = once(src, '                    m_duo_m8_far_m->draw("Depth transition ends (metres)");\n',
               GOALD_MENU, 'goal D grid UI')
    src = once(src, '        .m2_right_sharpen=m_duo_m2_right->value()};',
               '        .m2_right_sharpen=m_duo_m2_right->value(),\n'
               '        .goald_depth_grid=m_duo_goald_grid->value()==1 ? 4096u : 1024u};',
               'goal D grid settings')
    src = once(src, '        current.m2_right_sharpen==candidate.m2_right_sharpen) return;',
               '        current.m2_right_sharpen==candidate.m2_right_sharpen &&\n'
               '        current.goald_depth_grid==candidate.goald_depth_grid) return;',
               'goal D grid change detection')
    return src


GOALD_LOG = r'''                                                    uevr::duoview::dx12::M1Resources::m4_fine_h.load());
                                                {
                                                    const uint32_t gd=uevr::duoview::duo_goald_status().load();
                                                    const uint32_t gf=uevr::duoview::duo_goald_field().load();
                                                    const uint64_t gpu_ns=uevr::duoview::dx12::M1Resources::goald_m4_gpu_ns.exchange(0);
                                                    const uint64_t gpu_n=uevr::duoview::dx12::M1Resources::goald_m4_gpu_samples.exchange(0);
                                                    SPDLOG_INFO("[DuoView][GoalD] grid requested={} effective={} reason={} field={}x{} hi_frames={} m4_gpu_ms={:.3f} gpu_samples={}",
                                                        (gd&1u) ? 4096 : 1024, (gd&2u) ? 4096 : 1024, (gd>>2)&15u,
                                                        gf>>16, gf&0xffffu,
                                                        uevr::duoview::dx12::M1Resources::goald_hi_frames.exchange(0),
                                                        gpu_n ? double(gpu_ns)/double(gpu_n)/1.0e6 : -1.0, gpu_n);
                                                }
'''


def component(src):
    return once(src, '                                                    uevr::duoview::dx12::M1Resources::m4_fine_h.load());\n',
                GOALD_LOG, 'goal D log line')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('backend', type=Path)
    ap.add_argument('shaders', type=Path)
    a = ap.parse_args()
    vr = a.backend / 'src/mods/vr'
    hlsl = a.shaders / 'DuoViewM1Stereo.hlsl'
    original = hlsl.read_bytes().decode('utf-8')
    edit(hlsl, shader)
    if strip_goald(hlsl.read_bytes().decode('utf-8')) != original:  # exact, line endings included
        raise RuntimeError('Off shader text changed outside DUOVIEW_GOALD_GRID blocks')
    edit(vr / 'DuoViewM1D3D12.hpp', m1_backend)
    edit(vr / 'DuoViewD3D12.hpp', compositor_backend)
    edit(vr / 'DuoViewConfig.hpp', config)
    edit(a.backend / 'src/mods/VR.hpp', vr_hpp)
    edit(a.backend / 'src/mods/VR.cpp', vr_cpp)
    edit(vr / 'D3D12Component.cpp', component)
    print('goal D switch 1: grid 1024 unchanged (Off); 4096 in separate m4g_* DXBC, single-slice field')


if __name__ == '__main__':
    main()

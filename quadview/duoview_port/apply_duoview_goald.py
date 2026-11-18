#!/usr/bin/env python3
"""Goal D (2026-11-18): improve Off. Four runtime switches, all default OFF (= baseline):
 1 fovea depth grid 1024 / 4096;  2 temporal fovea depth history (all fovea depth, K=4);
 3 one-sided ramp per eye (raw step on the side the warp does not need a ramp);
 4 background fill in the fovea (mirror, full/half) + fine jitter direction switch.
Switches 2-4 and the jitter direction run on the 4096 kernels (they turn the 4096 grid on).

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


def shader_raster(src):
    body = Path(__file__).with_name('DuoViewGoalDRaster.hlsl').read_text(encoding='utf-8')
    if not body.endswith('\n'):
        body += '\n'
    helper, body = body.split('// ---- GOALD_RASTER_BODY\n')
    src = once(src, '\nfloat2 M1PullUv(', f'\n#ifdef {TAG}\n{helper}#endif\nfloat2 M1PullUv(', 'goal D raster helper')
    anchor = '        uv.x=clamp(root,lo,hi);\n'
    return once(src, anchor, anchor + f'#ifdef {TAG}\n{body}#endif\n', 'goal D raster root choice')


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
        t.Width=w; t.Height=h; t.DepthOrArraySize=3; t.MipLevels=1; // slices 0/1 per eye (switch 3), 2 raw seed (switch 4 halo at background depth)
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
    // ---- Goal D switch 2: temporal fovea depth history. ONE history shared by
    // every XR slot (all slots record on the game's single queue, in order).
    // R32_UINT array, always in UNORDERED_ACCESS state: slices 2p/2p+1 = kept
    // seed (float bits)/age of parity p, slice 4 = counters. Replaced textures
    // stay alive for 16 committed history frames (more than the XR slots that
    // may still reference them), then are released.
    // The CPU record (parity, camera, crop, sizes, time, type, jitter sign) is
    // committed only when the caller reports the recorded command list as
    // submitted (note_fine_depth_enqueued -> goald_commit_history; review #372 R1).
    // Any rejected frame, gather fallback or frame without a history pass drops
    // it and invalidates the history (goald_drop_frame; R2).
    // Assumption (R1/R6, documented, not fence-proven): all XR slots submit on the
    // game's one direct queue in recording order, fewer than 16 slots in flight.
    struct GoalDHistoryShared {
        ComPtr<ID3D12Resource> texture;
        std::vector<std::pair<uint64_t,ComPtr<ID3D12Resource>>> retired;
        ID3D12Device* device{};
        uint32_t generation{}, parity{}, type{};
        uint64_t commits{};
        bool have_previous{}, fresh_counters{}, jitter_negative{};
        stereo::FineDepthCamera camera{};
        std::array<float,4> crop{};
        std::array<float,3> coefficients{};
        uint32_t w{}, h{}, fine_w{}, fine_h{};
        std::chrono::steady_clock::time_point time{};
    };
    static GoalDHistoryShared& goald_history_state() { static GoalDHistoryShared s; return s; }
    ComPtr<ID3D12PipelineState> m4g_history, m4g_condition_h;
    ComPtr<ID3D12PipelineState> m4g_raster; // switch 3 true depth: front-most root in the fovea
    bool goald_true_depth{};
    bool goald_halo_bg{}; // switch 4 value 3: halo at background depth (m4g_raster)
    uint32_t goald_mode_bits{}; // 1 true depth -> tight (no PSO), 2 halo off (true depth on), 4 halo off (no PSO)
    ComPtr<ID3D12Resource> goald_counter_readback;
    bool goald_hist_active{}, goald_counter_pending{}, goald_counter_recorded{};
    uint32_t goald_hist_parity{}, goald_counter_parity{};
    // 0 off/active, 1 needs the 4096 field, 2 pipeline/readback missing, 3 GPU memory, 4 no camera pose
    uint32_t goald_hist_reason{};
    inline static std::atomic<uint64_t> goald_hist_frames{}, goald_hist_valid_frames{}, goald_hist_texels{}, goald_hist_used{};
    inline static std::atomic<uint32_t> goald_hist_permille{};
    bool goald_ensure_history(ID3D12Device* device, uint32_t fw, uint32_t fh) {
        auto& s=goald_history_state();
        const uint32_t need_w=(fw+127u)&~127u, need_h=(fh+127u)&~127u;
        if (s.texture && s.device==device) {
            const auto d=s.texture->GetDesc();
            if (d.Width>=need_w && d.Height>=need_h) return true;
        }
        if (s.texture) s.retired.emplace_back(s.commits,std::move(s.texture));
        D3D12_HEAP_PROPERTIES heap{};
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC t{};
        t.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        t.Width=need_w; t.Height=need_h; t.DepthOrArraySize=5; t.MipLevels=1;
        t.Format=DXGI_FORMAT_R32_UINT; t.SampleDesc.Count=1;
        t.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&t,
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&s.texture)))) {
            s.texture.Reset();
            return false;
        }
        s.texture->SetName(L"DuoView::GoalDFoveaDepthHistory");
        s.device=device; ++s.generation; s.have_previous=false;
        s.fresh_counters=true; // new texture: the first dispatch's counters are undefined
        return true;
    }
    // Provisional history record of this frame (committed by goald_commit_history).
    struct GoalDHistoryPending {
        bool active{}, valid{}, jitter_negative{};
        uint32_t parity{}, type{}, w{}, h{}, fine_w{}, fine_h{};
        stereo::FineDepthCamera camera{};
        std::array<float,4> crop{};
        std::array<float,3> coefficients{};
        std::chrono::steady_clock::time_point time{};
    } goald_pending{};
    // Caller submitted this slot's recorded list (one queue, recording order).
    void goald_commit_history() {
        auto& s=goald_history_state();
        if (!goald_pending.active) return;
        const auto& p=goald_pending;
        s.parity=p.parity; s.have_previous=true; s.camera=p.camera; s.crop=p.crop;
        s.coefficients=p.coefficients; s.w=p.w; s.h=p.h; s.fine_w=p.fine_w; s.fine_h=p.fine_h; s.time=p.time;
        s.type=p.type; s.jitter_negative=p.jitter_negative;
        // This submitted pass cleared the other parity's counters = the next pass's own (R7).
        s.fresh_counters=false;
        if (p.valid) ++goald_hist_valid_frames;
        if (goald_counter_recorded) { goald_counter_pending=true; goald_counter_recorded=false; }
        ++s.commits;
        s.retired.erase(std::remove_if(s.retired.begin(),s.retired.end(),
            [&](const auto& r){ return s.commits-r.first>=16u; }),s.retired.end());
        goald_pending.active=false;
    }
    // Rejected frame / gather fallback / frame without a history pass / diagnostic
    // skip: nothing of this frame is committed and the next history frame starts
    // fresh (stale parity, camera or counters can never be reused; R2, R7).
    void goald_drop_frame() {
        auto& s=goald_history_state();
        goald_pending.active=false;
        goald_counter_recorded=false;
        s.have_previous=false;
        s.fresh_counters=true;
    }
    void goald_read_counters() {
        // Caller owns a retired XR command slot; never wait on the GPU.
        if (!goald_counter_pending || !goald_counter_readback) return;
        const D3D12_RANGE read{0,4*sizeof(uint32_t)};
        void* p=nullptr;
        if (SUCCEEDED(goald_counter_readback->Map(0,&read,&p)) && p) {
            const auto* v=static_cast<const uint32_t*>(p);
            const uint32_t texels=v[2u*goald_counter_parity], used=v[2u*goald_counter_parity+1u];
            const D3D12_RANGE written{0,0};
            goald_counter_readback->Unmap(0,&written);
            goald_hist_texels+=texels; goald_hist_used+=used;
            if (texels) goald_hist_permille.store(uint32_t(uint64_t(used)*1000u/texels),std::memory_order_relaxed);
        }
        goald_counter_pending=false;
    }
'''

M1_PSO = r'''        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4_vertical)))) m4_vertical.Reset();
        // Goal D switch 1: optional; failure only keeps the 1024 field.
        compute.CS={m4g_condition_bytecode,sizeof(m4g_condition_bytecode)};
        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4g_condition)))) m4g_condition.Reset();
        compute.CS={m4g_vertical_bytecode,sizeof(m4g_vertical_bytecode)};
        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4g_vertical)))) m4g_vertical.Reset();
        // Goal D switch 2: optional; failure only reports "history not active".
        {   // Goal D switch 3 true depth: raster variant (same root signature/state)
            auto gd_graphics=graphics;
            gd_graphics.PS={m4g_raster_bytecode,sizeof(m4g_raster_bytecode)};
            if(FAILED(device->CreateGraphicsPipelineState(&gd_graphics,IID_PPV_ARGS(&m4g_raster)))) m4g_raster.Reset();
        }
        compute.CS={m4g_history_bytecode,sizeof(m4g_history_bytecode)};
        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4g_history)))) m4g_history.Reset();
        compute.CS={m4g_condition_h_bytecode,sizeof(m4g_condition_h_bytecode)};
        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4g_condition_h)))) m4g_condition_h.Reset();
        {
            D3D12_HEAP_PROPERTIES rb{};
            rb.CreationNodeMask=rb.VisibleNodeMask=1;
            rb.Type=D3D12_HEAP_TYPE_READBACK;
            D3D12_RESOURCE_DESC b{};
            b.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; b.Width=256;
            b.Height=b.DepthOrArraySize=b.MipLevels=1; b.SampleDesc.Count=1;
            b.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
            if(FAILED(device->CreateCommittedResource(&rb,D3D12_HEAP_FLAG_NONE,&b,
                D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&goald_counter_readback)))) goald_counter_readback.Reset();
        }
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


M1_GOALD_FRAME = r'''        // ---- Goal D switches 2-4 + jitter direction (4096 kernels only; the M6
        // slots are unused under Stereo V2, so Off constants stay all-zero there).
        goald_true_depth=false;
        goald_halo_bg=false;
        goald_pending.active=false;
        goald_mode_bits=0u;
        if (m4_active && m4_hi_active && focus) {
            const bool raster_true=bool(m4g_raster);
            data.m6_previous_jitter[0]=goald_jitter_negative ? -1.f : 1.f;
            uint32_t goald_flags=goald_one_sided==1u ? 4u : goald_one_sided==2u ? 12u : goald_one_sided>=3u ? (raster_true ? 16u : 12u) : 0u;
            goald_true_depth=goald_one_sided>=3u && raster_true;
            if (goald_one_sided>=3u && !raster_true) goald_mode_bits|=1u; // true depth fell back to tight
            if (goald_history) {
                auto& s=goald_history_state();
                const auto& cam=geometry.fine_depth_camera;
                const bool camera_ok=cam.projection[0]!=0.f && cam.projection[2]!=0.f &&
                    cam.world_to_meters>0.f && std::isfinite(cam.position[0]);
                if (!m4g_history || !m4g_condition_h || !goald_counter_readback) goald_hist_reason=2u;
                else if (!camera_ok) goald_hist_reason=4u;
                else if (!goald_ensure_history(device,m4_columns,m4_rows)) goald_hist_reason=3u;
                else {
                    const auto now=std::chrono::steady_clock::now();
                    std::array<float,3> coefficients{};
                    std::copy_n(geometry.depth_coefficients.begin(),3,coefficients.begin());
                    // Safety resets only: field/fine size change, stale record, depth coefficient change.
                    #if defined(DUOVIEW_M4_WARP_PROBE)
                    const auto stale_limit=std::chrono::milliseconds(60000); // WARP frames are slow
                    #else
                    const auto stale_limit=std::chrono::milliseconds(90);
                    #endif
                    // R2: a history type (All/Thin) or jitter sign change also starts fresh.
                    const bool same_mode=s.type==goald_history && s.jitter_negative==goald_jitter_negative;
                    if (s.have_previous && !same_mode) goald_hist_permille.store(0u,std::memory_order_relaxed);
                    const bool valid=s.have_previous && same_mode && s.w==m4_columns && s.h==m4_rows &&
                        s.fine_w==focus->rect[2] && s.fine_h==focus->rect[3] &&
                        s.coefficients==coefficients && now-s.time<=stale_limit;
                    const uint32_t next_parity=s.parity^1u; // committed only after a successful record
                    if (valid) {
                        const auto motion=stereo::fine_depth_reprojection(cam,s.camera);
                        std::memcpy(data.m6_view,motion.rows.data(),sizeof(data.m6_view));
                        std::copy(cam.projection.begin(),cam.projection.end(),data.m6_current_projection);
                        std::copy(motion.previous_projection.begin(),motion.previous_projection.end(),
                                  data.m6_previous_projection);
                        std::copy(s.crop.begin(),s.crop.end(),data.m6_previous_crop);
                    }
                    goald_flags|=2u|(valid ? 1u : 0u)|(goald_history>=2u ? 64u : 0u); // 64: thin objects only
                    data.m6_previous_rect[0]=next_parity;
                    data.m6_previous_jitter[1]=4.f;                 // K=4
                    data.m6_previous_jitter[2]=data.m8_distance[0]; // nearer than the M8 near distance: weapon/hands (All: camera-locked; Thin: none)
                    data.m6_previous_jitter[3]=.75f;                // accept radius, field texels
                    auto& p=goald_pending;
                    p.active=true; p.valid=valid; p.parity=next_parity; p.camera=cam;
                    p.type=goald_history; p.jitter_negative=goald_jitter_negative;
                    std::copy(std::begin(data.m2_crop),std::end(data.m2_crop),p.crop.begin());
                    p.coefficients=coefficients; p.w=m4_columns; p.h=m4_rows;
                    p.fine_w=focus->rect[2]; p.fine_h=focus->rect[3]; p.time=now;
                    goald_hist_active=true; goald_hist_reason=0u; goald_hist_parity=next_parity;
                    ++goald_hist_frames;
                }
            }
            data.m6_previous_rect[1]=goald_flags;
            if (goald_fill==3u) { // switch 4 "halo at background depth": raster PSO only, no M8 fill
                data.m8_effects[2]=data.m8_effects[3]=0.f; // the legacy M8 fill must not move the source again
                goald_halo_bg=raster_true && !goald_true_depth; // with true depth there is no lift: halo off
                if (goald_halo_bg) data.m6_previous_rect[1]|=32u;
                else goald_mode_bits|=raster_true ? 2u : 4u;  // 2: off because of true depth, 4: no raster PSO
            } else if (goald_fill>0u) // switch 4: mirror background fill inside the fovea crop
                data.m8_effects[2]=data.m8_effects[3]=goald_fill==1u ? 1.f : .5f;
        }
        // Safety reset: history Off / not running this frame -> the next On starts fresh.
        if (!goald_hist_active) goald_history_state().have_previous=false;
'''


def m1_backend(src):
    src = once(src, '#include <memory>\n', '#include <memory>\n#include <vector>\n#include <algorithm>\n', 'goal D vector include')
    src = once(src, '    ComPtr<ID3D12Resource> m4_depth;\n', M1_MEMBERS, 'goal D members')
    src = once(src,
               '        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4_vertical)))) m4_vertical.Reset();\n',
               M1_PSO, 'goal D pipelines')
    src = once(src, '                         float eye_near,float eye_far) {',
               '                         float eye_near,float eye_far,uint32_t depth_grid=1024u,\n'
               '                         uint32_t goald_history=0u,bool goald_jitter_negative=false,\n'
               '                         uint32_t goald_one_sided=0u,uint32_t goald_fill=0u) {',
               'goal D grid argument')
    src = once(src, '        m25_read_retired_stats(); // The owning XR command slot has retired before reuse.\n',
               '        m25_read_retired_stats(); // The owning XR command slot has retired before reuse.\n'
               '        goald_read_counters();\n', 'goal D counter readback')
    src = once(src, '        m4_active=false; m4_columns=m4_rows=0;\n',
               '        m4_active=false; m4_columns=m4_rows=0;\n'
               '        m4_hi_active=false;\n'
               '        goald_hist_active=false; goald_hist_reason=goald_history ? 1u : 0u;\n'
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
    src = once(src, '        void* address{};\n        const D3D12_RANGE no_read{0,0};\n',
               M1_GOALD_FRAME + '        void* address{};\n        const D3D12_RANGE no_read{0,0};\n',
               'goal D switches 2-4 constants')
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
    // Switches 2-4 and the jitter direction run on the 4096 kernels: they turn it on.
    template<class S> static uint32_t goald_grid(const S& s) {
        return (s.goald_history || s.goald_jitter_negative || s.goald_one_sided || s.goald_fill) ?
            4096u : s.goald_depth_grid;
    }
    // u6 follows the shared history texture (slot's previous GPU work has retired).
    void goald_bind_history(ID3D12Device* device) {
        if (!m1_.goald_hist_active || !m7_current_uav_.ptr) return;
        auto& s=M1Resources::goald_history_state();
        if (!s.texture || s.generation==goald_hist_bound_) return;
        D3D12_UNORDERED_ACCESS_VIEW_DESC u{};
        u.Format=DXGI_FORMAT_R32_UINT;
        u.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2DARRAY;
        u.Texture2DArray.ArraySize=5;
        device->CreateUnorderedAccessView(s.texture.Get(),nullptr,&u,m7_current_uav_);
        goald_hist_bound_=s.generation;
    }
    void goald_copy_counters(ID3D12GraphicsCommandList* cmd) {
        auto& s=M1Resources::goald_history_state();
        if (!s.texture || !m1_.goald_counter_readback) return;
        // Own-parity counters are only known cleared when the previous history pass
        // was submitted (goald_commit_history clears fresh_counters); after a new
        // texture or any dropped frame skip this readback (review #372 R7).
        if (s.fresh_counters) return;
        transition(cmd,s.texture.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION src{};
        src.pResource=s.texture.Get();
        src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        src.SubresourceIndex=4; // counters slice
        D3D12_TEXTURE_COPY_LOCATION dst{};
        dst.pResource=m1_.goald_counter_readback.Get();
        dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        dst.PlacedFootprint.Footprint.Format=DXGI_FORMAT_R32_UINT;
        dst.PlacedFootprint.Footprint.Width=4;
        dst.PlacedFootprint.Footprint.Height=1;
        dst.PlacedFootprint.Footprint.Depth=1;
        dst.PlacedFootprint.Footprint.RowPitch=256;
        const D3D12_BOX box{0,0,0,4,1,1};
        cmd->CopyTextureRegion(&dst,0,0,0,&src,&box);
        transition(cmd,s.texture.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        m1_.goald_counter_recorded=true; // read back only once this list is submitted
        m1_.goald_counter_parity=m1_.goald_hist_parity;
    }
    void goald_report_status(uint32_t depth_grid, bool m1_active, bool history) {
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
        const uint32_t hreason=!history ? 0u : (m1_active ? m1_.goald_hist_reason : 5u);
        duo_goald_history().store((1u<<31)|(history?1u:0u)|(m1_active && m1_.goald_hist_active?2u:0u)|((hreason&15u)<<2)|
            ((M1Resources::goald_hist_permille.load(std::memory_order_relaxed)&1023u)<<8),std::memory_order_relaxed);
        duo_goald_modes().store((1u<<31)|(m1_active ? m1_.goald_mode_bits : 0u),std::memory_order_relaxed);
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
               '                settings.m9_eye_near,settings.m9_eye_far,goald_grid(settings),\n'
               '                settings.goald_history,settings.goald_jitter_negative!=0u,\n'
               '                settings.goald_one_sided,settings.goald_fill);\n'
               '        if (m1_active) { goald_bind_m4_field(device); goald_bind_history(device); }\n'
               '        goald_report_status(goald_grid(settings),m1_active,settings.goald_history!=0u);\n',
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
               '                ID3D12PipelineState* m4_gpu_pso=m1_.m4_hi_active ?\n'
               '                    (m1_.goald_hist_active ? m1_.m4g_condition_h.Get() : m1_.m4g_condition.Get()) : m1_.m4_condition.Get();\n',
               'goal D condition PSO')
    src = once(src,
               '                    cmd->SetComputeRootDescriptorTable(0,srv_gpu_start_);\n'
               '                    cmd->SetPipelineState(m4_gpu_pso);\n',
               '                    cmd->SetComputeRootDescriptorTable(0,srv_gpu_start_);\n'
               '                    if(m1_.goald_hist_active) { // goal D switch 2: history pass writes the seed\n'
               '                        cmd->SetPipelineState(m1_.m4g_history.Get());\n'
               '                        cmd->Dispatch((m1_.m4_columns+7u)/8u,(m1_.m4_rows+7u)/8u,1);\n'
               '                        D3D12_RESOURCE_BARRIER goald_uav{};\n'
               '                        goald_uav.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV; // every UAV: field + history\n'
               '                        cmd->ResourceBarrier(1,&goald_uav);\n'
               '                    }\n'
               '                    cmd->SetPipelineState(m4_gpu_pso);\n',
               'goal D history dispatch')
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
               '                if(m1_.goald_hist_active) goald_copy_counters(cmd);\n'
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
    src = once(src, 'cmd->SetPipelineState(m1_active ? m1_.raster.Get() : native_pipeline_.Get());',
               'cmd->SetPipelineState(m1_active ? ((m1_.goald_true_depth || m1_.goald_halo_bg) ? m1_.m4g_raster.Get() : m1_.raster.Get()) : native_pipeline_.Get());',
               'goal D raster PSO')
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
    src = once(src,
               '        desc_cpu.ptr+=srv_descriptor_increment_; // [16] u6 new history\n'
               '        m7_current_uav_=desc_cpu;\n',
               '        desc_cpu.ptr+=srv_descriptor_increment_; // [16] u6 new history\n'
               '        m7_current_uav_=desc_cpu; goald_hist_bound_=0u;\n',
               'goal D u6 descriptor')
    src = once(src, '    void update_timing(bool timed, bool direct_xr) {', COMPOSITOR_METHODS, 'goal D methods')
    # Switch 2 (review #372 R1/R2): the history record is committed only when the XR
    # caller reports the recorded list as submitted (note_fine_depth_enqueued); every
    # reject, gather fallback, diagnostic skip or frame without a history pass drops it.
    src = once(src,
               '        m1_.fovea_depth_lease.reset();\n        error_.clear();\n        last_native_direct_xr_=false;\n'
               '        const auto reject=[this](const char* reason) { error_=reason; return false; };\n',
               '        m1_.fovea_depth_lease.reset();\n        error_.clear();\n        last_native_direct_xr_=false;\n'
               '        m1_.goald_pending.active=false; m1_.goald_counter_recorded=false; // goal D: nothing pending yet\n'
               '        const auto reject=[this](const char* reason) { m1_.goald_drop_frame(); error_=reason; return false; };\n',
               'goal D reject drops history')
    src = once(src,
               '        next_fine_depth_={};\n        return true;\n    }\n    // Fallback for capture resources',
               '        next_fine_depth_={};\n'
               '        // goal D: a frame with a history pass commits at submission; any other frame resets history\n'
               '        if (!m1_active || !m1_.goald_pending.active) m1_.goald_drop_frame();\n'
               '        return true;\n    }\n    // Fallback for capture resources',
               'goal D history drop without pass')
    src = once(src,
               '        const auto reject = [this](const char* reason) { error_ = reason; return false; };\n',
               '        m1_.goald_drop_frame(); // goal D: gather never runs the history pass\n'
               '        const auto reject = [this](const char* reason) { error_ = reason; return false; };\n',
               'goal D gather drops history')
    src = once(src,
               '    void note_fine_depth_enqueued() {\n',
               '    void note_fine_depth_enqueued() {\n'
               '        m1_.goald_commit_history(); // goal D: the recorded list was submitted\n',
               'goal D history commit at submission')
    src = once(src,
               "                    m4_probe_skip=(stage[0]=='s');\n",
               "                    m4_probe_skip=(stage[0]=='s');\n"
               "                    if(m4_probe_skip) m1_.goald_drop_frame(); // goal D: no history pass this frame (R1)\n",
               'goal D diagnostic skip drops history')
    src = once(src,
               '    D3D12_CPU_DESCRIPTOR_HANDLE m2_fovea_srv_{}, m6_previous_srv_{}, m7_current_srv_{}, m7_current_uav_{};\n',
               '    D3D12_CPU_DESCRIPTOR_HANDLE m2_fovea_srv_{}, m6_previous_srv_{}, m7_current_srv_{}, m7_current_uav_{};\n'
               '    D3D12_CPU_DESCRIPTOR_HANDLE goald_m4_srv_cpu_{}, goald_m4_uav_cpu_{};\n'
               '    D3D12_SHADER_RESOURCE_VIEW_DESC goald_srv_desc_{};\n'
               '    D3D12_UNORDERED_ACCESS_VIEW_DESC goald_uav_desc_{};\n'
               '    uint32_t goald_bound_key_{}, goald_hist_bound_{};\n'
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
// history: bit 0 requested, bit 1 active, bits 2-5 reason, bits 8-17 permille from history, bit 31 written.
inline std::atomic<uint32_t>& duo_goald_history() { static std::atomic<uint32_t> s{0u}; return s; }
// modes (effective vs requested): bit 0 true depth fell back to tight (no raster PSO),
// bit 1 halo at background depth off because true depth is on, bit 2 halo off (no raster PSO).
inline std::atomic<uint32_t>& duo_goald_modes() { static std::atomic<uint32_t> s{0u}; return s; }
inline const char* duo_goald_history_reason_text(uint32_t reason) {
    switch (reason) {
    case 1u: return "NOT ACTIVE - needs the 4096 fovea depth grid running (see the grid status above).";
    case 2u: return "NOT ACTIVE - history shader pipeline could not be created.";
    case 3u: return "NOT ACTIVE - GPU memory for the history could not be allocated.";
    case 4u: return "NOT ACTIVE - no camera pose for the fine depth yet.";
    case 5u: return "NOT ACTIVE - no synthetic stereo frame yet.";
    default: return "NOT ACTIVE.";
    }
}
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
               '    uint32_t goald_depth_grid{1024}; // goal D: fovea depth grid 1024 (baseline) or 4096\n'
               '    uint32_t goald_history{0}, goald_jitter_negative{0}, goald_one_sided{0}, goald_fill{0}; // goal D switches 2-4\n',
               'goal D settings field')
    src = once(src, '    out.m4_fovea_grid=requested.m4_fovea_grid;\n',
               '    out.m4_fovea_grid=requested.m4_fovea_grid;\n'
               '    out.goald_depth_grid=requested.goald_depth_grid>=4096u ? 4096u : 1024u;\n'
               '    out.goald_history=(std::min)(requested.goald_history,2u); // 0 off, 1 all fovea depth, 2 thin objects only\n'
               '    out.goald_jitter_negative=requested.goald_jitter_negative ? 1u : 0u;\n'
               '    out.goald_one_sided=(std::min)(requested.goald_one_sided,3u);\n'
               '    out.goald_fill=(std::min)(requested.goald_fill,3u);\n',
               'goal D settings sanitize')
    if '#include <atomic>' not in src:
        src = once(src, '#include <optional>\n', '#include <optional>\n#include <atomic>\n', 'goal D atomic include')
    src = once(src, '\nstruct Settings {\n', GOALD_STATUS, 'goal D status')
    return src


def vr_hpp(src):
    src = once(src, '    static const inline std::vector<std::string> s_duo_m3_jitter_modes{',
               '    static const inline std::vector<std::string> s_duo_goald_grids{ "1024 (baseline)", "4096 (goal D test)" };\n'
               '    static const inline std::vector<std::string> s_duo_goald_offon{ "Off (baseline)", "On (goal D test)" };\n'
               '    static const inline std::vector<std::string> s_duo_goald_history{ "Off (baseline)", "All fovea depth (Liviu)", "Thin objects only (reviews)" };\n'
               '    static const inline std::vector<std::string> s_duo_goald_jitter{ "+ (current)", "- (flipped)" };\n'
               '    static const inline std::vector<std::string> s_duo_goald_fill{ "Off (baseline)", "Mirror, full", "Mirror, half", "Halo at background depth (use with 3 Off)" };\n'
               '    static const inline std::vector<std::string> s_duo_goald_ramp{ "Off (baseline)", "One-sided, soft", "One-sided, tight", "True depth (no ramp)" };\n'
               '    static const inline std::vector<std::string> s_duo_m3_jitter_modes{',
               'goal D grid names')
    src = once(src,
               '    const ModToggle::Ptr m_duo_m4_fovea_grid{ModToggle::create(generate_name("DuoM4FoveaDepthGrid"),false)};\n',
               '    const ModToggle::Ptr m_duo_m4_fovea_grid{ModToggle::create(generate_name("DuoM4FoveaDepthGrid"),false)};\n'
               '    const ModCombo::Ptr m_duo_goald_grid{ModCombo::create(generate_name("DuoFoveaDepthGridSize"),s_duo_goald_grids,0)};\n'
               '    const ModCombo::Ptr m_duo_goald_history{ModCombo::create(generate_name("DuoFoveaDepthHistory"),s_duo_goald_history,0)};\n'
               '    const ModCombo::Ptr m_duo_goald_jitter{ModCombo::create(generate_name("DuoFoveaJitterDirection"),s_duo_goald_jitter,0)};\n'
               '    const ModCombo::Ptr m_duo_goald_one_sided{ModCombo::create(generate_name("DuoOneSidedRamp"),s_duo_goald_ramp,0)};\n'
               '    const ModCombo::Ptr m_duo_goald_fill{ModCombo::create(generate_name("DuoFoveaBackgroundFill"),s_duo_goald_fill,0)};\n',
               'goal D grid control')
    src = once(src, '*m_duo_m4_fovea_grid, ', '*m_duo_m4_fovea_grid, *m_duo_goald_grid, *m_duo_goald_history, *m_duo_goald_jitter, *m_duo_goald_one_sided, *m_duo_goald_fill, ', 'goal D grid persisted')
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
                    ImGui::TextWrapped("Goal D switches 2-4 (test build). Any of them turns the 4096 grid on.");
                    m_duo_goald_history->draw("2. Fovea depth history, up to 4 frames (All = all depth, weapon follows camera; Thin only = no weapon, no wide objects)");
                    {
                        const uint32_t gh=uevr::duoview::duo_goald_history().load(std::memory_order_relaxed);
                        if (!(gh>>31) || !(gh&1u)) ImGui::TextWrapped("Fovea depth history: off.");
                        else if (gh&2u) ImGui::TextWrapped("Fovea depth history: ACTIVE, %.1f%% of fovea depth from history.",
                            float((gh>>8)&1023u)/10.f);
                        else ImGui::TextWrapped("Fovea depth history: %s", uevr::duoview::duo_goald_history_reason_text((gh>>2)&15u));
                    }
                    m_duo_goald_jitter->draw("Fovea depth jitter direction");
                    m_duo_goald_one_sided->draw("3. Depth ramp next to near objects (true depth = background keeps its own depth; use with 4)");
                    m_duo_goald_fill->draw("4. Background fill in the fovea (mirror: best with 3; halo at background depth: EXPERIMENTAL, 3 Off)");
                    {
                        const uint32_t gm=uevr::duoview::duo_goald_modes().load(std::memory_order_relaxed);
                        if ((gm>>31) && (gm&1u)) ImGui::TextWrapped("NOTE: True depth is NOT running (raster shader missing) - you see One-sided, tight.");
                        if ((gm>>31) && (gm&2u)) ImGui::TextWrapped("NOTE: Halo at background depth is OFF while 3 = True depth.");
                        if ((gm>>31) && (gm&4u)) ImGui::TextWrapped("NOTE: Halo at background depth is NOT running (raster shader missing).");
                    }
'''


def vr_cpp(src):
    src = once(src, '                    m_duo_m8_far_m->draw("Depth transition ends (metres)");\n',
               GOALD_MENU, 'goal D grid UI')
    src = once(src, '        .m2_right_sharpen=m_duo_m2_right->value()};',
               '        .m2_right_sharpen=m_duo_m2_right->value(),\n'
               '        .goald_depth_grid=m_duo_goald_grid->value()==1 ? 4096u : 1024u,\n'
               '        .goald_history=uint32_t((std::clamp)(m_duo_goald_history->value(),0,2)),\n'
               '        .goald_jitter_negative=m_duo_goald_jitter->value()==1 ? 1u : 0u,\n'
               '        .goald_one_sided=uint32_t((std::clamp)(m_duo_goald_one_sided->value(),0,3)),\n'
               '        .goald_fill=uint32_t((std::clamp)(m_duo_goald_fill->value(),0,3))};',
               'goal D grid settings')
    src = once(src, '        current.m2_right_sharpen==candidate.m2_right_sharpen) return;',
               '        current.m2_right_sharpen==candidate.m2_right_sharpen &&\n'
               '        current.goald_depth_grid==candidate.goald_depth_grid &&\n'
               '        current.goald_history==candidate.goald_history &&\n'
               '        current.goald_jitter_negative==candidate.goald_jitter_negative &&\n'
               '        current.goald_one_sided==candidate.goald_one_sided &&\n'
               '        current.goald_fill==candidate.goald_fill) return;',
               'goal D grid change detection')
    return src


GOALD_LOG = r'''                                                    uevr::duoview::dx12::M1Resources::m4_fine_h.load());
                                                {
                                                    const uint32_t gd=uevr::duoview::duo_goald_status().load();
                                                    const uint32_t gf=uevr::duoview::duo_goald_field().load();
                                                    const uint64_t gpu_ns=uevr::duoview::dx12::M1Resources::goald_m4_gpu_ns.exchange(0);
                                                    const uint64_t gpu_n=uevr::duoview::dx12::M1Resources::goald_m4_gpu_samples.exchange(0);
                                                    const uint32_t gh=uevr::duoview::duo_goald_history().load();
                                                    const uint64_t ht=uevr::duoview::dx12::M1Resources::goald_hist_texels.exchange(0);
                                                    const uint64_t hu=uevr::duoview::dx12::M1Resources::goald_hist_used.exchange(0);
                                                    SPDLOG_INFO("[DuoView][GoalD] history requested={} active={} reason={} frames={} valid_frames={} from_history_permille={} mode_fallback_bits={}",
                                                        gh&1u, (gh>>1)&1u, (gh>>2)&15u,
                                                        uevr::duoview::dx12::M1Resources::goald_hist_frames.exchange(0),
                                                        uevr::duoview::dx12::M1Resources::goald_hist_valid_frames.exchange(0),
                                                        ht ? hu*1000u/ht : 0u,
                                                        uevr::duoview::duo_goald_modes().load()&7u);
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
    edit(hlsl, shader_raster)
    if strip_goald(hlsl.read_bytes().decode('utf-8')) != original:  # exact, line endings included
        raise RuntimeError('Off shader text changed outside DUOVIEW_GOALD_GRID blocks')
    edit(vr / 'DuoViewM1D3D12.hpp', m1_backend)
    edit(vr / 'DuoViewD3D12.hpp', compositor_backend)
    edit(vr / 'DuoViewConfig.hpp', config)
    edit(a.backend / 'src/mods/VR.hpp', vr_hpp)
    edit(a.backend / 'src/mods/VR.cpp', vr_cpp)
    edit(vr / 'D3D12Component.cpp', component)
    print('goal D switches 1-4: Off unchanged; 4096/history/one-sided/fill only in separate m4g_* DXBC + goal D settings')


if __name__ == '__main__':
    main()

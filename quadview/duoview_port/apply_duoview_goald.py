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
    src = once(src, anchor, anchor + f'#ifdef {TAG}\n{body}#endif\n', 'goal D raster root choice')
    # Fast raster (flag 128, 2026-11-19, #377 log: raster 5-5.8 ms of ~6 ms): the warp solve
    # calls M1ReadConditionedEye 8+ times per output pixel; fully inside the fovea (blend 1)
    # the coarse read is discarded by lerp(coarse,fovea,1), so read only the fovea field.
    fast = ('#ifdef ' + TAG + '\n'
            '    [branch] if((M6PreviousRect.y&128u)!=0u && M4Flags.x>.5 && M4Grid.x>0u && M4Grid.y>0u) {\n'
            '        const float2 gfLocal=(uv-M2Crop.xy)/(M2Crop.zw-M2Crop.xy);\n'
            '        const float gfEdge=min(min(gfLocal.x,gfLocal.y),min(1.0-gfLocal.x,1.0-gfLocal.y));\n'
            '        if(gfEdge>=max(M4Flags.w,.0001)) {\n'
            '            const float2 gfCell=clamp(gfLocal*float2(M4Grid.xy),float2(.5,.5),float2(M4Grid.xy)-.5);\n'
            '            return M4FoveaSoft.SampleLevel(LinearClamp,float3(gfCell/float2(M4Grid.zw),float(eye)),0);\n'
            '        }\n'
            '    }\n'
            '#endif\n')
    head = 'float M1ReadConditionedEye(float2 uv, uint eye) {\n'
    src = once(src, head + '    const float coarse=M1ReadCoarseEye(uv,eye);\n',
               head + fast + '    const float coarse=M1ReadCoarseEye(uv,eye);\n', 'goal D fast raster read')
    # Raster cost test (65_, 2026-11-19), m4g_raster only:
    #  bit 20 warp bypass: no warp solve (source = homography base), same colour path, two
    #         eyes -> GPU stages "raster" = colour floor of the stereo raster (diagnostic).
    #  bits 12-15 / 16-19: 8 - bisection steps for pixels whose base uv lies inside / outside
    #         the fovea crop (0 = 8 = today). Fewer steps = wider final bracket (secant kept).
    bypass = ('#ifdef ' + TAG + '\n'
              '    [branch] if((M6PreviousRect.y&0x100000u)!=0u) return saturate(base); // warp bypass\n'
              '#endif\n')
    solve = '    [branch] if(M1Grid.x>0 && abs(k)>1.e-6) {\n'
    src = once(src, '    const float k=M1Eye[eye];\n' + solve,
               '    const float k=M1Eye[eye];\n' + bypass + solve, 'goal D warp bypass')
    steps = ('#ifdef ' + TAG + '\n'
             '        const bool gsFovea=all(base>M2Crop.xy) && all(base<M2Crop.zw);\n'
             '        const uint gsSteps=8u-((M6PreviousRect.y>>(gsFovea ? 12u : 16u))&7u);\n'
             '#endif\n')
    src = once(src, '        bool haveLo=false, haveHi=false;\n',
               '        bool haveLo=false, haveHi=false;\n' + steps, 'goal D search steps')
    loop = '        [unroll] for(uint iteration=0u;iteration<8u;++iteration) {\n'
    return once(src, loop, loop + '#ifdef ' + TAG + '\n            if(iteration>=gsSteps) break;\n#endif\n',
                'goal D search step limit')


# Colour path speed-up (2026-11-19, 67_ follow-up), m4g_raster only, same image:
# HLSL `c ? a : b` evaluates BOTH sides; FXC flattened the periphery choice to a movc,
# so every stereo pixel fetched the 9 Catmull-Rom taps AND the bilinear tap and kept one
# (verified in the m4g_raster disassembly: 10 unconditional t1 samples). A real [branch]
# fetches 1 tap (Sharper periphery OFF, or fovea weight 1) or 9 (ON, periphery visible).
PERIPHERY_TERNARY = (
    '    float4 periphery = (SharpenFlags & 8u) != 0u && weight < 1.0\n'
    '        ? SamplePeripheryCatmullRom(DuoLogicalToSourceUv(fullUv), PeripheralRect.zw, NativePeripheryDimensions)\n'
    '        : PeripheralNativeSource.SampleLevel(LinearClamp, peripherySample, 0.0);\n')
PERIPHERY_BRANCH = (
    '    float4 periphery;\n'
    '    [branch] if ((SharpenFlags & 8u) != 0u && weight < 1.0)\n'
    '        periphery = SamplePeripheryCatmullRom(DuoLogicalToSourceUv(fullUv), PeripheralRect.zw, NativePeripheryDimensions);\n'
    '    else\n'
    '        periphery = PeripheralNativeSource.SampleLevel(LinearClamp, peripherySample, 0.0);\n')


def native_raster(src):
    return once(src, PERIPHERY_TERNARY,
                f'#ifdef {TAG}\n{PERIPHERY_BRANCH}#else\n{PERIPHERY_TERNARY}#endif\n',
                'goal D periphery branch')


def strip_goald(src):
    # A goal D block is insert-only (#ifdef TAG ... #endif), or a replacement
    # (#ifdef TAG <goal D> #else <original, kept verbatim for Off> #endif).
    out, inside, keep = [], False, False
    for line in src.splitlines(keepends=True):
        tag = line.strip()
        if tag == f'#ifdef {TAG}':
            if inside:
                raise RuntimeError('nested goal D block')
            inside, keep = True, False
            continue
        if inside and tag == '#else':
            if keep:
                raise RuntimeError('second #else in goal D block')
            keep = True
            continue
        if inside and tag == '#endif':
            inside, keep = False, False
            continue
        if not inside or keep:
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
    // seed (float bits)/age of parity p, slice 4 = counters, slices 5+2p/6+2p = motion
    // (field texels, float bits) carried with the kept seed (MV mode, 62_). Replaced textures
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
        uint64_t record_seq{}; // review #373 F1: sequence of the latest recorded history pass
        uint64_t epoch{};      // review #373 F4: bumped on every drop; older counter readbacks are ignored
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
    bool goald_fast_raster_on{}; // fast raster (flag 128, m4g_raster): skip the discarded coarse read in the fovea
    bool goald_raster_variant_on{}; // 65_: warp bypass / fewer search steps (m4g_raster, 4096 path)
    // 65_ VRS: fovea rect in output-eye uv per eye (x0,y0,x1,y1), from the M2 crop widened by the warp
    // bracket and mapped by the inverse output->source homography; valid only when goald_vrs_fovea_ok.
    std::array<float,8> goald_vrs_fovea{};
    bool goald_vrs_fovea_ok{};
    uint32_t goald_mode_bits{}; // 1 true depth -> tight (no PSO), 2 halo off (true depth on), 4 halo off (no PSO)
    ComPtr<ID3D12Resource> goald_counter_readback;
    bool goald_hist_active{}, goald_counter_pending{}, goald_counter_recorded{};
    uint32_t goald_hist_parity{}, goald_counter_parity{};
    uint64_t goald_counter_epoch{};
    bool goald_counter_mv{};
    float goald_last_shift{};
    // Motion gate (#373 headset: history lagged head yaw): field-texel shift of this frame
    // vs the previous one; history is used only while it is <= the menu limit.
    inline static std::atomic<uint64_t> goald_hist_moving_frames{};
    inline static std::atomic<uint64_t> goald_shift_centi{}, goald_shift_samples{}, goald_shift_max_centi{}; // log: head shift (field texels x100)
    inline static std::atomic<uint32_t> goald_log_settings{}; // log: bit0 history, 1-2 motion source, 4-7 confirm texels, 8 jitter negative, 9 fast raster,
                                                              // 10 warp bypass, 12-15 fovea steps, 16-19 periphery steps
    inline static std::atomic<float> goald_log_limit{};
    inline static std::atomic<uint32_t> goald_still_permille{}; // smoothed, for the menu
    // 0 off/active, 1 needs the 4096 field, 2 pipeline/readback missing, 3 GPU memory, 4 no camera pose
    uint32_t goald_hist_reason{};
    inline static std::atomic<uint64_t> goald_hist_frames{}, goald_hist_valid_frames{}, goald_hist_texels{}, goald_hist_used{};
    inline static std::atomic<uint32_t> goald_hist_permille{};
    // History motion source (62_): DLSS motion vectors of the fine depth (t9) or head pose.
    ID3D12Resource* goald_mv_resource{};
    DXGI_FORMAT goald_mv_format{DXGI_FORMAT_UNKNOWN};
    bool goald_mv_active{};
    inline static std::atomic<uint64_t> goald_mv_frames{}, goald_mv_fallback_frames{}, goald_mv_abs_quarter{};
    // 68_ VRAM: slices 5..8 (per-parity motion) only exist once MV mode is wanted
    // (5 slices otherwise, ~4 x 10 MB saved at 1664x1536); grows to 9, never shrinks.
    bool goald_ensure_history(ID3D12Device* device, uint32_t fw, uint32_t fh, bool mv_slices) {
        auto& s=goald_history_state();
        const uint32_t need_w=(fw+127u)&~127u, need_h=(fh+127u)&~127u;
        const uint32_t need_slices=mv_slices ? 9u : 5u;
        if (s.texture && s.device==device) {
            const auto d=s.texture->GetDesc();
            if (d.Width>=need_w && d.Height>=need_h && d.DepthOrArraySize>=need_slices) return true;
        }
        if (s.texture) s.retired.emplace_back(s.commits,std::move(s.texture));
        D3D12_HEAP_PROPERTIES heap{};
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC t{};
        t.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        t.Width=need_w; t.Height=need_h; t.DepthOrArraySize=UINT16(need_slices); t.MipLevels=1; // + slices 5..8: per-parity motion (MV mode only)
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
        uint64_t seq{};
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
        // Review #373 F1: only the LATEST recorded history pass may become the history.
        // An older list submitted after a newer one (another XR slot recorded meanwhile)
        // ran on stale state and may overwrite the newer pass's slice on the GPU: drop.
        if (p.seq!=s.record_seq) { goald_drop_frame(); return; }
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
        goald_pending.active=false;
        goald_counter_recorded=false;
        goald_drop_shared();
    }
    // Shared part, also called by the XR caller (review #373 F2) when a DuoView copy
    // was attempted but no recorded list was submitted (early return before record).
    static void goald_drop_shared() {
        auto& s=goald_history_state();
        s.have_previous=false;
        s.fresh_counters=true;
        ++s.epoch;                                                  // F4: in-flight readbacks are stale
        goald_hist_permille.store(0u,std::memory_order_relaxed);    // F4: menu % restarts
    }
    void goald_read_counters() {
        // Caller owns a retired XR command slot; never wait on the GPU.
        if (!goald_counter_pending || !goald_counter_readback) return;
        if (goald_counter_epoch!=goald_history_state().epoch) { goald_counter_pending=false; return; } // F4
        const D3D12_RANGE read{0,6*sizeof(uint32_t)};
        void* p=nullptr;
        if (SUCCEEDED(goald_counter_readback->Map(0,&read,&p)) && p) {
            const auto* v=static_cast<const uint32_t*>(p);
            const uint32_t texels=v[2u*goald_counter_parity], used=v[2u*goald_counter_parity+1u];
            if (goald_counter_mv) goald_mv_abs_quarter+=v[4u+goald_counter_parity]; // sum |MV| (quarter texels)
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
        goald_fast_raster_on=false;
        goald_raster_variant_on=false;
        goald_pending.active=false;
        const uint32_t gs_fovea=(std::clamp)(goald_fovea_steps,2u,8u), gs_periphery=(std::clamp)(goald_periphery_steps,2u,8u);
        goald_log_settings.store((goald_history&1u)|((goald_motion_source&3u)<<1u)|((goald_confirm_texels&15u)<<4u)|
                                 ((goald_jitter_negative ? 1u : 0u)<<8u)|((goald_fast_raster ? 1u : 0u)<<9u)|
                                 ((goald_warp_bypass ? 1u : 0u)<<10u)|(gs_fovea<<12u)|(gs_periphery<<16u),std::memory_order_relaxed);
        // 65_ VRS fovea rect (any grid size): output-eye uv whose warp source can lie in the M2 crop.
        goald_vrs_fovea_ok=false;
        if (goald_vrs && data.m2_crop[2]>data.m2_crop[0] && data.m2_crop[3]>data.m2_crop[1]) {
            const float cap=data.depth[3]>0.f ? 2.f*data.depth[3] : data.filter[1];
            bool ok=std::isfinite(cap);
            for (int e=0; e<2 && ok; ++e) {
                const float reach=std::abs(data.eye[e]*cap); // farthest root from its homography base (uv)
                const auto& H=data.homography;
                const int r=3*e;
                const double a=H[r][0], b=H[r][1], c=H[r][2], d=H[r+1][0], f=H[r+1][1], g=H[r+1][2],
                             h=H[r+2][0], i=H[r+2][1], j=H[r+2][2];
                const double det=a*(f*j-g*i)-b*(d*j-g*h)+c*(d*i-f*h);
                if (!(std::abs(det)>1.e-12) || !std::isfinite(det)) { ok=false; break; }
                const double inv[3][3]{{(f*j-g*i)/det,(c*i-b*j)/det,(b*g-c*f)/det},
                                       {(g*h-d*j)/det,(a*j-c*h)/det,(c*d-a*g)/det},
                                       {(d*i-f*h)/det,(b*h-a*i)/det,(a*f-b*d)/det}};
                float x0=1.e9f, y0=1.e9f, x1=-1.e9f, y1=-1.e9f;
                for (int cx=0; cx<2; ++cx) for (int cy=0; cy<2; ++cy) {
                    const double sx=cx ? double(data.m2_crop[2])+reach : double(data.m2_crop[0])-reach;
                    const double sy=cy ? double(data.m2_crop[3]) : double(data.m2_crop[1]);
                    const double W=inv[2][0]*sx+inv[2][1]*sy+inv[2][2];
                    if (!(W>1.e-6)) { ok=false; continue; }
                    const float ux=float((inv[0][0]*sx+inv[0][1]*sy+inv[0][2])/W);
                    const float uy=float((inv[1][0]*sx+inv[1][1]*sy+inv[1][2])/W);
                    x0=(std::min)(x0,ux); x1=(std::max)(x1,ux); y0=(std::min)(y0,uy); y1=(std::max)(y1,uy);
                }
                ok=ok && std::isfinite(x0) && std::isfinite(x1) && std::isfinite(y0) && std::isfinite(y1);
                goald_vrs_fovea[4*e+0]=(std::clamp)(x0,0.f,1.f); goald_vrs_fovea[4*e+1]=(std::clamp)(y0,0.f,1.f);
                goald_vrs_fovea[4*e+2]=(std::clamp)(x1,0.f,1.f); goald_vrs_fovea[4*e+3]=(std::clamp)(y1,0.f,1.f);
            }
            goald_vrs_fovea_ok=ok;
        }
        goald_log_limit.store(goald_motion_limit,std::memory_order_relaxed);
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
                else if (!goald_ensure_history(device,m4_columns,m4_rows,
                    goald_motion_source!=0u && focus->mv && focus->mv_format!=DXGI_FORMAT_UNKNOWN)) goald_hist_reason=3u;
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
                    // 62_: DLSS motion vectors of this fine depth (menu 1, or 2 = flipped sign);
                    // without them the history falls back to head-pose mode (counted, menu note).
                    const bool mv_mode=goald_motion_source!=0u && focus->mv && focus->mv_format!=DXGI_FORMAT_UNKNOWN &&
                        std::isfinite(focus->mv_scale[0]) && std::isfinite(focus->mv_scale[1]);
                    if (goald_motion_source!=0u && !mv_mode) ++goald_mv_fallback_frames;
                    const uint32_t hist_type=goald_history|(mv_mode ? 16u : 0u)|(goald_motion_source==2u ? 32u : 0u);
                    const bool same_mode=s.type==hist_type && s.jitter_negative==goald_jitter_negative;
                    if (s.have_previous && !same_mode) goald_hist_permille.store(0u,std::memory_order_relaxed);
                    const bool valid=s.have_previous && same_mode && s.w==m4_columns && s.h==m4_rows &&
                        s.fine_w==focus->rect[2] && s.fine_h==focus->rect[3] &&
                        s.coefficients==coefficients && now-s.time<=stale_limit;
                    const uint32_t next_parity=s.parity^1u; // committed only after a successful record
                    // Search range for camera translation: nearer than the M8 near distance
                    // (>= .25 m). NOT camera-locked any more (#373: with M8 start ~1 m all
                    // near depth followed the head).
                    const float search_near=data.m8_distance[0];
                    bool still=true;
                    if (valid) { // head-pose shift also in MV mode: logged next to the MV size (units check)
                        const auto motion=stereo::fine_depth_reprojection(cam,s.camera);
                        // Motion gate: largest field-texel shift of 9 crop points at infinity and
                        // at the nearest search depth (CPU copy of GDPreviousCell).
                        float shift=0.f;
                        const auto& pc=cam.projection;
                        const auto& pp=motion.previous_projection;
                        const float pw=(std::max)(s.crop[2]-s.crop[0],1.e-6f), ph=(std::max)(s.crop[3]-s.crop[1],1.e-6f);
                        for (int iy=0; iy<3; ++iy) for (int ix=0; ix<3; ++ix) for (int iz=0; iz<2; ++iz) {
                            const float lx=.5f*float(ix), ly=.5f*float(iy);
                            const float ux=data.m2_crop[0]+(data.m2_crop[2]-data.m2_crop[0])*lx;
                            const float uy=data.m2_crop[1]+(data.m2_crop[3]-data.m2_crop[1])*ly;
                            const float ray[4]{(2.f*ux-1.f-pc[1])/pc[0],(1.f-2.f*uy-pc[3])/pc[2],1.f,iz ? search_near*2.f/3.f : 0.f};
                            float pr[3]{};
                            for (int r=0; r<3; ++r)
                                for (int c=0; c<4; ++c) pr[r]+=motion.rows[r][c]*ray[c];
                            if (!(pr[2]>.01f)) { shift=1.e9f; continue; }
                            const float qx=.5f+.5f*(pp[0]*pr[0]/pr[2]+pp[1]);
                            const float qy=.5f-.5f*(pp[2]*pr[1]/pr[2]+pp[3]);
                            const float cx=((qx-s.crop[0])/pw-lx)*float(m4_columns);
                            const float cy=((qy-s.crop[1])/ph-ly)*float(m4_rows);
                            shift=(std::max)(shift,(std::max)(std::abs(cx),std::abs(cy)));
                        }
                        // #377 headset: limit 2 dropped history in most frames (from history 1-2%).
                        // Limit >= 32 = no limit: history is reprojected by head pose in every frame;
                        // the confirm distance still bounds trails behind things that move by themselves.
                        still=mv_mode || (std::isfinite(shift) && (goald_motion_limit>=32.f || shift<=goald_motion_limit));
                        goald_last_shift=shift;
                        if (std::isfinite(shift) && shift<1.e6f) {
                            goald_shift_centi+=uint64_t(shift*100.f); ++goald_shift_samples;
                            uint64_t m=goald_shift_max_centi.load(std::memory_order_relaxed);
                            const uint64_t v=uint64_t(shift*100.f);
                            while (v>m && !goald_shift_max_centi.compare_exchange_weak(m,v,std::memory_order_relaxed)) {}
                        }
                        if (!mv_mode) {
                            std::memcpy(data.m6_view,motion.rows.data(),sizeof(data.m6_view));
                            std::copy(cam.projection.begin(),cam.projection.end(),data.m6_current_projection);
                            std::copy(motion.previous_projection.begin(),motion.previous_projection.end(),
                                      data.m6_previous_projection);
                            std::copy(s.crop.begin(),s.crop.end(),data.m6_previous_crop);
                        }
                    }
                    // A moving frame is still recorded and committed (its depth becomes the
                    // next frame's history) but uses none: no trail can follow the head.
                    if (valid && !still) ++goald_hist_moving_frames;
                    if (mv_mode) {
                        // MV mode: no head-still gate (MVs include camera motion). M6View row 0 =
                        // raw MV -> field texels (x,y) and the MV texel extent (= fine depth extent).
                        const float sign=goald_motion_source==2u ? -1.f : 1.f;
                        data.m6_view[0][0]=sign*focus->mv_scale[0]*float(m4_columns)/float((std::max)(focus->rect[2],1u));
                        data.m6_view[0][1]=sign*focus->mv_scale[1]*float(m4_rows)/float((std::max)(focus->rect[3],1u));
                        data.m6_view[0][2]=float(focus->rect[2]);
                        data.m6_view[0][3]=float(focus->rect[3]);
                        goald_mv_active=true; goald_mv_resource=focus->mv; goald_mv_format=focus->mv_format;
                        ++goald_mv_frames;
                    }
                    if (valid && !mv_mode) {
                        const uint32_t old=goald_still_permille.load(std::memory_order_relaxed);
                        goald_still_permille.store((old*31u+(still ? 1000u : 0u))/32u,std::memory_order_relaxed);
                    }
                    const bool use=valid && still;
                    goald_flags|=2u|(use ? 1u : 0u)|((goald_confirm_texels&15u)<<8u)|(mv_mode ? 64u : 0u); // bits 8-11 confirm radius, 64 MV mode
                    data.m6_previous_rect[0]=next_parity;
                    data.m6_previous_jitter[1]=4.f;           // K=4
                    data.m6_previous_jitter[2]=search_near;   // translation search range (no camera lock)
                    data.m6_previous_jitter[3]=mv_mode ? .75f : .5f; // accept radius, field texels (MV: own-motion test)
                    auto& p=goald_pending;
                    p.seq=++s.record_seq; // F1
                    p.active=true; p.valid=use; p.parity=next_parity; p.camera=cam;
                    p.type=hist_type; p.jitter_negative=goald_jitter_negative;
                    std::copy(std::begin(data.m2_crop),std::end(data.m2_crop),p.crop.begin());
                    p.coefficients=coefficients; p.w=m4_columns; p.h=m4_rows;
                    p.fine_w=focus->rect[2]; p.fine_h=focus->rect[3]; p.time=now;
                    goald_hist_active=true; goald_hist_reason=0u; goald_hist_parity=next_parity;
                    ++goald_hist_frames;
                }
            }
            data.m6_previous_rect[1]=goald_flags;
            if (goald_fast_raster && raster_true) { data.m6_previous_rect[1]|=128u; goald_fast_raster_on=true; } // fast raster (m4g_raster)
            else if (goald_fast_raster) goald_mode_bits|=8u; // 8: fast raster requested but no m4g_raster PSO
            if (goald_warp_bypass || gs_fovea<8u || gs_periphery<8u) { // 65_: raster cost test (m4g_raster)
                if (raster_true) {
                    data.m6_previous_rect[1]|=((8u-gs_fovea)<<12u)|((8u-gs_periphery)<<16u)|(goald_warp_bypass ? 0x100000u : 0u);
                    goald_raster_variant_on=true;
                } else goald_mode_bits|=16u; // 16: bypass / steps requested but no m4g_raster PSO
            }
            if (goald_fill==3u) { // switch 4 "halo at background depth": raster PSO only, no M8 fill
                data.m8_effects[2]=data.m8_effects[3]=0.f; // the legacy M8 fill must not move the source again
                goald_halo_bg=raster_true && !goald_true_depth; // with true depth there is no lift: halo off
                if (goald_halo_bg) {
                    data.m6_previous_rect[1]|=32u;
                    const float wu=(std::max)(geometry.world_to_meters,1.f);
                    const float hn=(std::max)(goald_halo_near_m,.1f)*wu;
                    const float hf=(std::max)(goald_halo_fade_m*wu,hn);
                    std::memcpy(&data.m6_previous_rect[2],&hn,sizeof(float));
                    std::memcpy(&data.m6_previous_rect[3],&hf,sizeof(float));
                }
                else goald_mode_bits|=raster_true ? 2u : 4u;  // 2: off because of true depth, 4: no raster PSO
            } else if (goald_fill>0u) // switch 4: mirror background fill inside the fovea crop
                data.m8_effects[2]=data.m8_effects[3]=goald_fill==1u ? 1.f : .5f;
        }
        // Safety reset: history Off / not running this frame -> the next On starts fresh.
        if (!goald_hist_active && goald_history_state().have_previous) goald_drop_shared();
'''


def m1_backend(src):
    src = once(src, '    float fine_weight{1.f};\n};\n',
               '    float fine_weight{1.f};\n'
               '    // Goal D (62_): DLSS motion vectors of the same Evaluate (fine depth only).\n'
               '    ID3D12Resource* mv{};\n'
               '    DXGI_FORMAT mv_format{DXGI_FORMAT_UNKNOWN};\n'
               '    std::array<float,2> mv_scale{1.f,1.f};\n'
               '};\n', 'goal D MV input')
    src = once(src, '#include <memory>\n', '#include <memory>\n#include <vector>\n#include <algorithm>\n', 'goal D vector include')
    src = once(src, '    ComPtr<ID3D12Resource> m4_depth;\n', M1_MEMBERS, 'goal D members')
    src = once(src,
               '        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4_vertical)))) m4_vertical.Reset();\n',
               M1_PSO, 'goal D pipelines')
    src = once(src, '                         float eye_near,float eye_far) {',
               '                         float eye_near,float eye_far,uint32_t depth_grid=1024u,\n'
               '                         uint32_t goald_history=0u,bool goald_jitter_negative=false,\n'
               '                         uint32_t goald_one_sided=0u,uint32_t goald_fill=0u,\n'
               '                         float goald_motion_limit=8.f,float goald_halo_near_m=1.f,float goald_halo_fade_m=3.f,uint32_t goald_fast_raster=0u,\n'
               '                         uint32_t goald_confirm_texels=0u,uint32_t goald_motion_source=0u,\n'
               '                         bool goald_warp_bypass=false,uint32_t goald_fovea_steps=8u,uint32_t goald_periphery_steps=8u,\n'
               '                         bool goald_vrs=false) {',
               'goal D grid argument')
    src = once(src, '        m25_read_retired_stats(); // The owning XR command slot has retired before reuse.\n',
               '        m25_read_retired_stats(); // The owning XR command slot has retired before reuse.\n'
               '        goald_read_counters();\n', 'goal D counter readback')
    src = once(src, '        m4_active=false; m4_columns=m4_rows=0;\n',
               '        m4_active=false; m4_columns=m4_rows=0;\n'
               '        m4_hi_active=false;\n'
               '        goald_hist_active=false; goald_hist_reason=goald_history ? 1u : 0u;\n'
               '        goald_mv_active=false; goald_mv_resource=nullptr;\n'
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
        u.Texture2DArray.ArraySize=s.texture->GetDesc().DepthOrArraySize; // 5, or 9 with MV slices (68_)
        device->CreateUnorderedAccessView(s.texture.Get(),nullptr,&u,m7_current_uav_);
        goald_hist_bound_=s.generation;
    }
    // t9 (retired M6 slot, 62_): this frame's DLSS motion vectors in MV mode, else a NULL view.
    // The resource stays alive and unchanged through the fine depth lease.
    void goald_bind_motion(ID3D12Device* device) {
        if (!m6_previous_srv_.ptr || !m1_.goald_hist_active) return;
        D3D12_SHADER_RESOURCE_VIEW_DESC v{};
        v.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
        v.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        v.Texture2D.MipLevels=1;
        v.Format=m1_.goald_mv_active ? m1_.goald_mv_format : DXGI_FORMAT_R16G16_FLOAT;
        device->CreateShaderResourceView(m1_.goald_mv_active ? m1_.goald_mv_resource : nullptr,&v,m6_previous_srv_);
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
        dst.PlacedFootprint.Footprint.Width=6; // + per-parity sum |MV| (62_)
        dst.PlacedFootprint.Footprint.Height=1;
        dst.PlacedFootprint.Footprint.Depth=1;
        dst.PlacedFootprint.Footprint.RowPitch=256;
        const D3D12_BOX box{0,0,0,6,1,1};
        cmd->CopyTextureRegion(&dst,0,0,0,&src,&box);
        transition(cmd,s.texture.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        m1_.goald_counter_recorded=true; // read back only once this list is submitted
        m1_.goald_counter_parity=m1_.goald_hist_parity;
        m1_.goald_counter_epoch=s.epoch; // F4: ignored if a drop happens before it is read
        m1_.goald_counter_mv=m1_.goald_mv_active;
    }
    void goald_stamp(ID3D12GraphicsCommandList* cmd, bool timed, uint32_t i) {
        if (!timed || !queries_) return;
        cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,i);
        goald_stage_mask_|=1u<<i;
    }
    // Stage durations (ns) of one completed frame -> per-mode sums (log) and EMA (menu).
    // 0 B40 Mono composite, 1 coarse depth conditioning, 2 history pass, 3 M4 fovea
    // conditioning, 4 other compute (stats copies, transitions), 5 raster (warp / Mono
    // draw), 6 output copy + transitions, 7 total of this DuoView list.
    void goald_note_stages(const UINT64* t) {
        const uint32_t m=goald_stage_pending_;
        const auto d=[&](uint32_t a, uint32_t b)->uint64_t {
            return t[b]>=t[a] ? uint64_t(double(t[b]-t[a])*1.0e9/double(frequency_)) : 0u; };
        const bool m4=(m&4u) && (m&8u), hist=m4 && (m&128u);
        uint64_t st[8]{};
        st[0]=(m&16u) ? d(0,4) : 0u;
        const uint32_t after_b40=(m&16u) ? 4u : 0u;
        st[1]=m4 ? d(after_b40,2) : ((m&32u) ? d(after_b40,5) : 0u);
        st[2]=hist ? d(2,7) : 0u;
        st[3]=m4 ? d(hist ? 7u : 2u,3) : 0u;
        st[4]=(m4 && (m&32u)) ? d(3,5) : 0u;
        st[5]=((m&32u) && (m&64u)) ? d(5,6) : 0u;
        st[6]=(m&64u) ? d(6,1) : 0u;
        st[7]=d(0,1);
        if (st[7]>1000000000ull) return; // bad sample
        const uint32_t mode=(m&0x100u) ? 1u : 0u; // 1 stereo synthesis, 0 Mono
        auto* sum=duo_stage_ns()+mode*9u;
        auto* ema=duo_stage_us()+mode*8u;
        for (uint32_t i=0; i<8; ++i) {
            sum[i]+=st[i];
            const uint32_t us=uint32_t((std::min)(st[i]/1000u,uint64_t(1000000u)));
            const uint32_t old=ema[i].load(std::memory_order_relaxed);
            ema[i].store(old ? (old*15u+us)/16u : us,std::memory_order_relaxed);
        }
        ++sum[8];
    }
    // 65_ VRS (2026-11-19): periphery shading rate for the stereo raster. Tier 1 per-draw rates +
    // scissors (no rate image, nothing to upload or keep alive): the fovea rect of each eye and a
    // band at the eye split (the pixel shader picks the eye by x) at 1x1, the rest of each eye at
    // the menu rate, as disjoint scissored draws of the same full-screen triangle. Rates above 2x2
    // need AdditionalShadingRatesSupported, else 2x2 (logged). Returns false = draw normally.
    bool goald_vrs_draw(ID3D12Device* device, ID3D12GraphicsCommandList* cmd, uint32_t rate_index,
                        bool stereo, UINT direct_width) {
        static constexpr D3D12_SHADING_RATE rates[7]{D3D12_SHADING_RATE_1X1,D3D12_SHADING_RATE_1X2,
            D3D12_SHADING_RATE_2X1,D3D12_SHADING_RATE_2X2,D3D12_SHADING_RATE_2X4,D3D12_SHADING_RATE_4X2,
            D3D12_SHADING_RATE_4X4};
        rate_index=(std::min)(rate_index,6u);
        if (!goald_vrs_caps_ && device) {
            goald_vrs_caps_=1u;
            D3D12_FEATURE_DATA_D3D12_OPTIONS6 o6{};
            if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS6,&o6,sizeof(o6)))) {
                goald_vrs_tier_=uint32_t(o6.VariableShadingRateTier)&3u;
                goald_vrs_additional_=o6.AdditionalShadingRatesSupported!=FALSE;
            }
        }
        uint32_t effective=0u, reason=0u, draws=0u;
        uint64_t eye0=0u;
        const auto report=[&]{
            duo_goald_vrs().store((1u<<31)|rate_index|(effective<<4)|(goald_vrs_tier_<<8)|
                (goald_vrs_additional_ ? 1u<<10 : 0u)|(reason<<12)|(draws<<16),std::memory_order_relaxed);
            duo_goald_vrs_rect().store(eye0,std::memory_order_relaxed);
        };
        if (!rate_index) { report(); return false; }
        ComPtr<ID3D12GraphicsCommandList5> cl5;
        const UINT W=direct_width/2u, H=height_;
        constexpr LONG band=16, margin=32;
        if (goald_vrs_tier_<1u) reason=1u;                                  // no VRS on this GPU/driver
        else if (!stereo || W<=UINT(4*band) || direct_width!=width_*2u) reason=2u; // Mono / not double-wide
        else if (!m1_.goald_vrs_fovea_ok) reason=3u;                        // no fovea crop this frame
        else if (FAILED(cmd->QueryInterface(IID_PPV_ARGS(&cl5)))) reason=4u;
        if (reason) { report(); return false; }
        effective=rate_index>=4u && !goald_vrs_additional_ ? 3u : rate_index;
        struct Part { D3D12_RECT r; bool fine; };
        Part parts[11]{};
        uint32_t n=0u;
        const auto add=[&](LONG x0, LONG y0, LONG x1, LONG y1, bool fine) {
            if (x1>x0 && y1>y0 && n<11u) parts[n++]=Part{D3D12_RECT{x0,y0,x1,y1},fine};
        };
        const LONG w=LONG(W), h=LONG(H);
        add(w-band,0,w+band,h,true); // eye split band
        for (int e=0; e<2; ++e) {
            const LONG ex0=e ? w+band : 0, ex1=e ? 2*w : w-band, off=e ? w : 0;
            const float* f=m1_.goald_vrs_fovea.data()+4*e;
            const auto lo=[](float v, LONG size, LONG m) { return (LONG(std::floor(v*float(size)))-m)&~LONG(3); };
            const auto hi=[](float v, LONG size, LONG m) { return (LONG(std::ceil(v*float(size)))+m+3)&~LONG(3); };
            const LONG fx0=(std::clamp)(off+lo(f[0],w,margin),ex0,ex1), fx1=(std::clamp)(off+hi(f[2],w,margin),ex0,ex1);
            const LONG fy0=(std::clamp)(lo(f[1],h,margin),LONG(0),h), fy1=(std::clamp)(hi(f[3],h,margin),LONG(0),h);
            if (fx1<=fx0 || fy1<=fy0) { add(ex0,0,ex1,h,false); continue; }
            if (!e) eye0=(uint64_t(fx0)&0xffffu)|((uint64_t(fy0)&0xffffu)<<16)|((uint64_t(fx1)&0xffffu)<<32)|((uint64_t(fy1)&0xffffu)<<48);
            add(fx0,fy0,fx1,fy1,true);
            add(ex0,0,ex1,fy0,false); add(ex0,fy1,ex1,h,false);
            add(ex0,fy0,fx0,fy1,false); add(fx1,fy0,ex1,fy1,false);
        }
        for (int pass=0; pass<2; ++pass) {
            cl5->RSSetShadingRate(pass ? rates[effective] : D3D12_SHADING_RATE_1X1,nullptr);
            for (uint32_t i=0; i<n; ++i) {
                if (parts[i].fine!=(pass==0)) continue;
                cmd->RSSetScissorRects(1,&parts[i].r);
                cmd->DrawInstanced(3,1,0,0);
                ++draws;
            }
        }
        cl5->RSSetShadingRate(D3D12_SHADING_RATE_1X1,nullptr); // restore
        const D3D12_RECT full{0,0,LONG(direct_width),h};
        cmd->RSSetScissorRects(1,&full);
        report();
        return true;
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
        duo_goald_still().store(M1Resources::goald_still_permille.load(std::memory_order_relaxed),std::memory_order_relaxed);
        duo_goald_motion().store((1u<<31)|(m1_active && m1_.goald_mv_active ? 1u : 0u),std::memory_order_relaxed);
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
               '                settings.goald_one_sided,settings.goald_fill,\n'
               '                settings.goald_motion_limit,settings.goald_halo_near_m,settings.goald_halo_fade_m,settings.goald_fast_raster,\n'
               '                settings.goald_confirm_texels,settings.goald_motion_source,\n'
               '                settings.goald_warp_bypass!=0u,settings.goald_fovea_steps,settings.goald_periphery_steps,\n'
               '                settings.goald_vrs_rate!=0u);\n'
               '        if (m1_active) { goald_bind_m4_field(device); goald_bind_history(device); goald_bind_motion(device); }\n'
               '        goald_report_status(goald_grid(settings),m1_active,settings.goald_history!=0u);\n',
               'goal D write_constants argument')
    # M4 dispatch: field resource, PSOs and timestamps 2/3 around both passes.
    src = once(src,
               '            if(m1_.m4_active) {\n'
               '                transition(cmd,m1_.m4_depth.Get(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,\n',
               '            if(m1_.m4_active) {\n'
               '                goald_m4_timed_=timed;\n'
               '                goald_stamp(cmd,timed,2u); // stage: M4 start\n'
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
               '                        cmd->Dispatch((m1_.m4_columns+15u)/16u,(m1_.m4_rows+15u)/16u,1); // 68_: 16x16 groups\n'
               '                        D3D12_RESOURCE_BARRIER goald_uav{};\n'
               '                        goald_uav.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV; // every UAV: field + history\n'
               '                        cmd->ResourceBarrier(1,&goald_uav);\n'
               '                        goald_stamp(cmd,timed,7u); // stage: history pass end\n'
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
               '                goald_stamp(cmd,timed,3u); // stage: M4 end\n'
               '                M1Resources::m4_count_frame();\n',
               'goal D M4 field after')
    if src.count('m1_.m4_depth.Get()') != 2:  # only the setup descriptors (t8, u5) remain
        raise RuntimeError(f'goal D: unexpected m4_depth uses {src.count("m1_.m4_depth.Get()")}')
    src = once(src,
               '        recorded_commands_=true;\n        if (timed) cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);\n',
               '        recorded_commands_=true;\n        goald_m4_timed_=false; goald_stage_mask_=0u;\n'
               '        if (timed) cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);\n',
               'goal D timing reset')
    src = once(src,
               '            cmd->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timestamps_.Get(),0);\n'
               '            timing_pending_=true; pending_direct_xr_=direct_xr;\n',
               '            cmd->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timestamps_.Get(),0);\n'
               '            // Stages not run this frame get a (meaningless) stamp here so the whole 0..7\n'
               '            // range is resolvable; the mask says which ones are real.\n'
               '            for (UINT gi=2; gi<8; ++gi) if (!(goald_stage_mask_&(1u<<gi))) cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,gi);\n'
               '            cmd->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2,6,timestamps_.Get(),2*sizeof(UINT64));\n'
               '            timing_pending_=true; pending_direct_xr_=direct_xr; goald_m4_pending_=goald_m4_timed_;\n'
               '            goald_stage_pending_=goald_stage_mask_|3u|(last_stereo_output_ ? 0x100u : 0u);\n',
               'goal D resolve')
    src = once(src, '            timing_pending_=false;\n            gpu_ms_=-1.f;\n',
               '            timing_pending_=false;\n            goald_m4_pending_=false; goald_stage_pending_=0u;\n            gpu_ms_=-1.f;\n',
               'goal D timing invalidation')
    src = once(src, '        D3D12_RANGE range{0, sizeof(UINT64) * 2};\n',
               '        D3D12_RANGE range{0, sizeof(UINT64) * 8};\n', 'goal D map range')
    src = once(src,
               '            if (data[1] >= data[0]) gpu_ms_ = static_cast<float>((data[1] - data[0]) * 1000.0 / frequency_);\n',
               '            if (data[1] >= data[0]) gpu_ms_ = static_cast<float>((data[1] - data[0]) * 1000.0 / frequency_);\n'
               '            if (goald_m4_pending_ && data[3] >= data[2])\n'
               '                M1Resources::goald_note_m4_gpu(double(data[3] - data[2]) * 1.0e9 / double(frequency_));\n'
               '            if (goald_stage_pending_) goald_note_stages(data);\n',
               'goal D read M4 timing')
    src = once(src, '        timing_pending_ = false;\n    }\n',
               '        timing_pending_ = false;\n        goald_m4_pending_ = false; goald_stage_pending_ = 0u;\n    }\n', 'goal D timing consumed')
    src = once(src, 'q.Count = 2;', 'q.Count = 8;', 'goal D query count')
    src = once(src, 'cmd->SetPipelineState(m1_active ? m1_.raster.Get() : native_pipeline_.Get());',
               'cmd->SetPipelineState(m1_active ? ((m1_.goald_true_depth || m1_.goald_halo_bg || m1_.goald_fast_raster_on || m1_.goald_raster_variant_on) ? m1_.m4g_raster.Get() : m1_.raster.Get()) : native_pipeline_.Get());',
               'goal D raster PSO')
    src = once(src, 'buffer.Width = sizeof(UINT64) * 2;', 'buffer.Width = sizeof(UINT64) * 8;', 'goal D readback size')
    # Stage stamps: 4 after the B40 Mono composite, 5 compute end / raster start, 6 raster end.
    src = once(src, '        if (b40_active) dispatch_b40(cmd,constants,true);\n        if (m1_active && m1_.rows) {\n',
               '        if (b40_active) dispatch_b40(cmd,constants,true);\n        goald_stamp(cmd,timed,4u); // stage: B40 end\n'
               '        if (m1_active && m1_.rows) {\n', 'goal D stage stamp 4')
    src = once(src, '        cmd->SetGraphicsRootSignature(root_.Get());\n        cmd->SetPipelineState(m1_active ? ((m1_.goald_true_depth',
               '        goald_stamp(cmd,timed,5u); // stage: compute end, raster start\n'
               '        cmd->SetGraphicsRootSignature(root_.Get());\n        cmd->SetPipelineState(m1_active ? ((m1_.goald_true_depth',
               'goal D stage stamp 5')
    src = once(src,
               '            cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);\n'
               '            cmd->DrawInstanced(3,1,0,0);\n'
               '        } else {\n',
               '            cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);\n'
               '            // 65_ VRS periphery rate (stereo double-wide raster only; Off = the single draw)\n'
               '            if (!goald_vrs_draw(device,cmd,settings.goald_vrs_rate,m1_active && settings.synthetic_stereo,direct_width))\n'
               '                cmd->DrawInstanced(3,1,0,0);\n'
               '        } else {\n'
               '            if (settings.goald_vrs_rate) goald_vrs_draw(device,cmd,settings.goald_vrs_rate,false,0u); // status: not applied\n',
               'goal D VRS draw')
    src = once(src, '        transition(cmd,fovea,fovea_sample_state,fovea_state);\n',
               '        goald_stamp(cmd,timed,6u); // stage: raster end\n'
               '        transition(cmd,fovea,fovea_sample_state,fovea_state);\n', 'goal D stage stamp 6')
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
               '        // goal D (review #373 F2): a slot is re-recorded only after its list retired, so a\n'
               '        // record still pending here was never submitted: its history must not be reused.\n'
               '        if (m1_.goald_pending.active) m1_.goald_drop_frame();\n'
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
               '        goald_stage_mask_=0u;\n'
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
               '    bool goald_m4_timed_{}, goald_m4_pending_{};\n'
               '    uint32_t goald_stage_mask_{}, goald_stage_pending_{}; // stamped indices; 0x100 = stereo frame\n'
               '    uint32_t goald_vrs_caps_{}, goald_vrs_tier_{}; bool goald_vrs_additional_{}; // 65_ VRS caps (queried once)\n',
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
// history motion gate: smoothed permille of frames with the head nearly still (menu).
inline std::atomic<uint32_t>& duo_goald_still() { static std::atomic<uint32_t> s{0u}; return s; }
// history motion source in use: bit 0 DLSS motion vectors active, bit 31 written.
inline std::atomic<uint32_t>& duo_goald_motion() { static std::atomic<uint32_t> s{0u}; return s; }
// 65_ VRS: bits 0-3 requested rate, 4-7 effective rate (0 Off,1 1x2,2 2x1,3 2x2,4 2x4,5 4x2,6 4x4),
// 8-9 tier, 10 additional rates, 12-15 reason (1 no VRS, 2 Mono/not double-wide, 3 no fovea rect,
// 4 no CommandList5), 16-23 draws, 31 written. rect: eye 0 fovea px x0|y0<<16|x1<<32|y1<<48.
inline std::atomic<uint32_t>& duo_goald_vrs() { static std::atomic<uint32_t> s{0u}; return s; }
inline std::atomic<uint64_t>& duo_goald_vrs_rect() { static std::atomic<uint64_t> s{0u}; return s; }
// GPU stage timing (needs "GPU timing: DuoView"): per mode [0 Mono, 1 stereo] 8 stage
// sums in ns + sample count (log, reset per line) and 8 smoothed stage values in us (menu).
inline std::atomic<uint64_t>* duo_stage_ns() { static std::atomic<uint64_t> s[18]{}; return s; }
inline std::atomic<uint32_t>* duo_stage_us() { static std::atomic<uint32_t> s[16]{}; return s; }
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
               '    uint32_t goald_history{0}, goald_jitter_negative{0}, goald_one_sided{0}, goald_fill{0}; // goal D switches 2-4\n'
               '    float goald_motion_limit{8.f}; // goal D history: used only while the field moves <= this many texels per frame (>= 32: always)\n'
               '    uint32_t goald_confirm_texels{2}; // goal D history: kept only with similar current depth within N texels (0 = off)\n'
               '    uint32_t goald_motion_source{1}; // goal D history motion: 0 head pose (head still only), 1 DLSS MVs, 2 DLSS MVs flipped\n'
               '    float goald_halo_near_m{1.f}, goald_halo_fade_m{3.f}; // goal D halo at background depth: full up to / off from\n'
               '    uint32_t goald_fast_raster{}; // goal D fast stereo raster (1 = skip the discarded coarse depth read inside the fovea)\n'
               '    uint32_t goald_warp_bypass{}; // 65_: 1 = no warp solve (colour floor diagnostic, 4096 path)\n'
               '    uint32_t goald_fovea_steps{8}, goald_periphery_steps{8}; // 65_: warp search steps 2..8 (8 = today)\n'
               '    uint32_t goald_vrs_rate{}; // 65_: periphery VRS 0 Off, 1 1x2, 2 2x1, 3 2x2, 4 2x4, 5 4x2, 6 4x4\n',
               'goal D settings field')
    src = once(src, '    out.m4_fovea_grid=requested.m4_fovea_grid;\n',
               '    out.m4_fovea_grid=requested.m4_fovea_grid;\n'
               '    out.goald_depth_grid=requested.goald_depth_grid>=4096u ? 4096u : 1024u;\n'
               '    out.goald_history=(std::min)(requested.goald_history,1u); // 0 off, 1 on (all fovea depth; Thin removed after #373)\n'
               '    out.goald_motion_limit=std::isfinite(requested.goald_motion_limit) ? (std::clamp)(requested.goald_motion_limit,.25f,64.f) : 8.f;\n'
               '    out.goald_confirm_texels=(std::min)(requested.goald_confirm_texels,8u);\n'
               '    out.goald_motion_source=(std::min)(requested.goald_motion_source,2u);\n'
               '    out.goald_halo_near_m=std::isfinite(requested.goald_halo_near_m) ? (std::clamp)(requested.goald_halo_near_m,.1f,50.f) : 1.f;\n'
               '    out.goald_halo_fade_m=std::isfinite(requested.goald_halo_fade_m) ? (std::clamp)(requested.goald_halo_fade_m,out.goald_halo_near_m,100.f) : 3.f;\n'
               '    out.goald_fast_raster=requested.goald_fast_raster ? 1u : 0u;\n'
               '    out.goald_warp_bypass=requested.goald_warp_bypass ? 1u : 0u;\n'
               '    out.goald_fovea_steps=(std::clamp)(requested.goald_fovea_steps,2u,8u);\n'
               '    out.goald_periphery_steps=(std::clamp)(requested.goald_periphery_steps,2u,8u);\n'
               '    out.goald_vrs_rate=(std::min)(requested.goald_vrs_rate,6u);\n'
               '    out.goald_jitter_negative=requested.goald_jitter_negative ? 1u : 0u;\n'
               '    out.goald_one_sided=0u; // switch 3 removed after #373 (ramp NO-GO); code kept, unreachable\n'
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
               '    static const inline std::vector<std::string> s_duo_goald_history{ "Off (baseline)", "On (all fovea depth, head still only)" };\n'
               '    static const inline std::vector<std::string> s_duo_goald_jitter{ "+ (current)", "- (flipped)" };\n'
               '    static const inline std::vector<std::string> s_duo_goald_confirm{ "Off (trails behind moving things)", "1 texel", "2 texels", "3 texels", "4 texels", "6 texels", "8 texels" };\n'
               '    static const inline std::vector<std::string> s_duo_goald_motion_src{ "Head pose (head still only)", "DLSS motion vectors", "DLSS motion vectors (flipped sign)" };\n'
               '    static const inline std::vector<std::string> s_duo_goald_steps{ "8 (today)", "7", "6", "5", "4", "3", "2" };\n'
               '    static const inline std::vector<std::string> s_duo_goald_vrs{ "Off (baseline)", "1x2", "2x1", "2x2", "2x4", "4x2", "4x4" };\n'
               '    static const inline std::vector<std::string> s_duo_goald_fill{ "Off (baseline)", "Mirror, full", "Mirror, half", "Halo at background depth" };\n'
               '    static const inline std::vector<std::string> s_duo_m3_jitter_modes{',
               'goal D grid names')
    src = once(src,
               '    const ModToggle::Ptr m_duo_m4_fovea_grid{ModToggle::create(generate_name("DuoM4FoveaDepthGrid"),false)};\n',
               '    const ModToggle::Ptr m_duo_m4_fovea_grid{ModToggle::create(generate_name("DuoM4FoveaDepthGrid"),false)};\n'
               '    const ModCombo::Ptr m_duo_goald_grid{ModCombo::create(generate_name("DuoFoveaDepthGridSize"),s_duo_goald_grids,0)};\n'
               '    const ModCombo::Ptr m_duo_goald_history{ModCombo::create(generate_name("DuoFoveaDepthHistory"),s_duo_goald_history,0)};\n'
               '    const ModCombo::Ptr m_duo_goald_jitter{ModCombo::create(generate_name("DuoFoveaJitterDirection"),s_duo_goald_jitter,0)};\n'
               '    const ModSlider::Ptr m_duo_goald_motion{ModSlider::create(generate_name("DuoFoveaHistoryStillLimit"),.25f,32.f,8.f)};\n'
               '    const ModCombo::Ptr m_duo_goald_confirm{ModCombo::create(generate_name("DuoFoveaHistoryConfirm"),s_duo_goald_confirm,2)};\n'
               '    const ModSlider::Ptr m_duo_goald_halo_near{ModSlider::create(generate_name("DuoHaloBgFullMeters"),.1f,20.f,1.f)};\n'
               '    const ModSlider::Ptr m_duo_goald_halo_fade{ModSlider::create(generate_name("DuoHaloBgOffMeters"),.1f,50.f,3.f)};\n'
               '    const ModToggle::Ptr m_duo_goald_fast_raster{ModToggle::create(generate_name("DuoFastStereoRaster"),false)};\n'
               '    const ModToggle::Ptr m_duo_goald_warp_bypass{ModToggle::create(generate_name("DuoWarpBypassDiag"),false)};\n'
               '    const ModCombo::Ptr m_duo_goald_fovea_steps{ModCombo::create(generate_name("DuoFoveaSearchSteps"),s_duo_goald_steps,0)};\n'
               '    const ModCombo::Ptr m_duo_goald_periphery_steps{ModCombo::create(generate_name("DuoPeripherySearchSteps"),s_duo_goald_steps,0)};\n'
               '    const ModCombo::Ptr m_duo_goald_vrs{ModCombo::create(generate_name("DuoPeripheryVrsRate"),s_duo_goald_vrs,0)};\n'
               '    const ModCombo::Ptr m_duo_goald_motion_src{ModCombo::create(generate_name("DuoFoveaHistoryMotion"),s_duo_goald_motion_src,1)};\n'
               '    const ModCombo::Ptr m_duo_goald_fill{ModCombo::create(generate_name("DuoFoveaBackgroundFill"),s_duo_goald_fill,0)};\n',
               'goal D grid control')
    src = once(src, '*m_duo_m4_fovea_grid, ', '*m_duo_m4_fovea_grid, *m_duo_goald_grid, *m_duo_goald_history, *m_duo_goald_jitter, *m_duo_goald_fill, *m_duo_goald_motion, *m_duo_goald_confirm, *m_duo_goald_motion_src, *m_duo_goald_halo_near, *m_duo_goald_halo_fade, *m_duo_goald_fast_raster, *m_duo_goald_warp_bypass, *m_duo_goald_fovea_steps, *m_duo_goald_periphery_steps, *m_duo_goald_vrs, ', 'goal D grid persisted')
    return src


GOALD_MENU = r'''                    m_duo_m8_far_m->draw("Depth transition ends (metres)");
                    m_duo_goald_grid->draw("Fovea depth grid (test build: 1024 = baseline, 4096 = goal D)");
                    for (uint32_t mode=0; mode<2; ++mode) {
                        const auto* u=uevr::duoview::duo_stage_us()+mode*8u;
                        const auto v=[&](uint32_t i){ return float(u[i].load(std::memory_order_relaxed))/1000.f; };
                        if (v(7)>0.f) ImGui::TextWrapped("GPU stages %s (ms, needs GPU timing ON): B40 %.2f | coarse depth %.2f | history %.2f | M4 fovea %.2f | other %.2f | raster %.2f | output %.2f | TOTAL %.2f",
                            mode ? "STEREO" : "MONO", v(0), v(1), v(2), v(3), v(4), v(5), v(6), v(7));
                    }
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
                    ImGui::TextWrapped("Goal D switches 2 and 4 (test build). Any of them turns the 4096 grid on.");
                    m_duo_goald_history->draw("2. Fovea depth history, up to 4 frames");
                    m_duo_goald_motion_src->draw("2. History motion source (DLSS motion vectors follow head, hands and objects)");
                    m_duo_goald_motion->draw("2. History head-motion limit (fovea depth texels per frame; higher = history helps more while turning; 32 = no limit)");
                    m_duo_goald_confirm->draw("2. History confirm distance (kept only next to similar depth now; smaller = shorter trails behind hands/moving objects)");
                    {
                        const uint32_t gh=uevr::duoview::duo_goald_history().load(std::memory_order_relaxed);
                        if (!(gh>>31) || !(gh&1u)) ImGui::TextWrapped("Fovea depth history: off.");
                        else if (gh&2u && (uevr::duoview::duo_goald_motion().load(std::memory_order_relaxed)&1u))
                            ImGui::TextWrapped("Fovea depth history: ACTIVE with DLSS motion vectors, %.1f%% of fovea depth from history.",
                            float((gh>>8)&1023u)/10.f);
                        else if (gh&2u) ImGui::TextWrapped("Fovea depth history: ACTIVE with head pose%s, %.1f%% of fovea depth from history; head still in %.0f%% of frames.",
                            m_duo_goald_motion_src->value()!=0 ? " (NO motion vectors from DLSS - fallback)" : "",
                            float((gh>>8)&1023u)/10.f,
                            float(uevr::duoview::duo_goald_still().load(std::memory_order_relaxed))/10.f);
                        else ImGui::TextWrapped("Fovea depth history: %s", uevr::duoview::duo_goald_history_reason_text((gh>>2)&15u));
                    }
                    m_duo_goald_jitter->draw("Fovea depth jitter direction");
                    m_duo_goald_fill->draw("4. Background fill in the fovea (halo at background depth: EXPERIMENTAL)");
                    m_duo_goald_halo_near->draw("4. Halo at background depth: full strength up to (metres)");
                    m_duo_goald_halo_fade->draw("4. Halo at background depth: fades to normal halo by (metres)");
                    m_duo_goald_fast_raster->draw("5. Fast stereo raster (skips a depth read that is discarded inside the fovea; needs the 4096 grid; compare GPU stages raster ms)");
                    ImGui::TextWrapped("6. Raster cost test (compare GPU stages raster ms; edges on weapon / fences):");
                    m_duo_goald_warp_bypass->draw("6. DIAGNOSTIC warp bypass (no stereo warp: eyes are WRONG; shows the colour-only raster cost; needs the 4096 grid)");
                    m_duo_goald_fovea_steps->draw("6. Fovea warp search steps (fewer = faster, edges may wobble; needs the 4096 grid)");
                    m_duo_goald_periphery_steps->draw("6. Periphery warp search steps (fewer = faster; needs the 4096 grid)");
                    m_duo_goald_vrs->draw("6. Periphery shading rate VRS (fovea + eye split stay 1x1; coarser = faster, blockier)");
                    {
                        const uint32_t gv=uevr::duoview::duo_goald_vrs().load(std::memory_order_relaxed);
                        static const char* vrs_names[7]{"Off","1x2","2x1","2x2","2x4","4x2","4x4"};
                        static const char* vrs_reasons[5]{"","this GPU/driver has no VRS","Mono frame / not a double-wide stereo target","no fovea crop this frame","command list without VRS"};
                        if ((gv>>31) && (gv&15u)) {
                            if ((gv>>12)&15u) ImGui::TextWrapped("VRS: NOT ACTIVE - %s.", vrs_reasons[(std::min)((gv>>12)&15u,4u)]);
                            else ImGui::TextWrapped("VRS: ACTIVE %s (tier %u, rates above 2x2 %s), %u draws.", vrs_names[(std::min)((gv>>4)&15u,6u)],
                                (gv>>8)&3u, (gv&1024u) ? "supported" : "NOT supported -> 2x2", (gv>>16)&255u);
                        }
                    }
                    {
                        const uint32_t gm=uevr::duoview::duo_goald_modes().load(std::memory_order_relaxed);
                        if ((gm>>31) && (gm&4u)) ImGui::TextWrapped("NOTE: Halo at background depth is NOT running (raster shader missing).");
                        if ((gm>>31) && (gm&16u)) ImGui::TextWrapped("NOTE: warp bypass / search steps NOT running (raster shader missing).");
                    }
'''


def vr_cpp(src):
    src = once(src, '                    m_duo_m8_far_m->draw("Depth transition ends (metres)");\n',
               GOALD_MENU, 'goal D grid UI')
    src = once(src, '        .m2_right_sharpen=m_duo_m2_right->value()};',
               '        .m2_right_sharpen=m_duo_m2_right->value(),\n'
               '        .goald_depth_grid=m_duo_goald_grid->value()==1 ? 4096u : 1024u,\n'
               '        .goald_history=uint32_t((std::clamp)(m_duo_goald_history->value(),0,1)),\n'
               '        .goald_jitter_negative=m_duo_goald_jitter->value()==1 ? 1u : 0u,\n'
               '        .goald_one_sided=0u,\n'
               '        .goald_fill=uint32_t((std::clamp)(m_duo_goald_fill->value(),0,3)),\n'
               '        .goald_motion_limit=m_duo_goald_motion->value(),\n'
               '        .goald_confirm_texels=uint32_t((std::clamp)(m_duo_goald_confirm->value(),0,6)<=4 ? (std::clamp)(m_duo_goald_confirm->value(),0,6) : (m_duo_goald_confirm->value()==5 ? 6 : 8)),\n'
               '        .goald_motion_source=uint32_t((std::clamp)(m_duo_goald_motion_src->value(),0,2)),\n'
               '        .goald_halo_near_m=m_duo_goald_halo_near->value(),\n'
               '        .goald_halo_fade_m=m_duo_goald_halo_fade->value(),\n'
               '        .goald_fast_raster=m_duo_goald_fast_raster->value() ? 1u : 0u,\n'
               '        .goald_warp_bypass=m_duo_goald_warp_bypass->value() ? 1u : 0u,\n'
               '        .goald_fovea_steps=8u-uint32_t((std::clamp)(m_duo_goald_fovea_steps->value(),0,6)),\n'
               '        .goald_periphery_steps=8u-uint32_t((std::clamp)(m_duo_goald_periphery_steps->value(),0,6)),\n'
               '        .goald_vrs_rate=uint32_t((std::clamp)(m_duo_goald_vrs->value(),0,6))};',
               'goal D grid settings')
    src = once(src, '        current.m2_right_sharpen==candidate.m2_right_sharpen) return;',
               '        current.m2_right_sharpen==candidate.m2_right_sharpen &&\n'
               '        current.goald_depth_grid==candidate.goald_depth_grid &&\n'
               '        current.goald_history==candidate.goald_history &&\n'
               '        current.goald_jitter_negative==candidate.goald_jitter_negative &&\n'
               '        current.goald_one_sided==candidate.goald_one_sided &&\n'
               '        current.goald_fill==candidate.goald_fill &&\n'
               '        current.goald_motion_limit==candidate.goald_motion_limit &&\n'
               '        current.goald_confirm_texels==candidate.goald_confirm_texels &&\n'
               '        current.goald_motion_source==candidate.goald_motion_source &&\n'
               '        current.goald_halo_near_m==candidate.goald_halo_near_m &&\n'
               '        current.goald_halo_fade_m==candidate.goald_halo_fade_m &&\n'
               '        current.goald_fast_raster==candidate.goald_fast_raster &&\n'
               '        current.goald_warp_bypass==candidate.goald_warp_bypass &&\n'
               '        current.goald_fovea_steps==candidate.goald_fovea_steps &&\n'
               '        current.goald_periphery_steps==candidate.goald_periphery_steps &&\n'
               '        current.goald_vrs_rate==candidate.goald_vrs_rate) return;',
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
                                                    const uint64_t hsn=uevr::duoview::dx12::M1Resources::goald_shift_samples.exchange(0);
                                                    const uint64_t hsc=uevr::duoview::dx12::M1Resources::goald_shift_centi.exchange(0);
                                                    const uint64_t hsm=uevr::duoview::dx12::M1Resources::goald_shift_max_centi.exchange(0);
                                                    const uint32_t gls=uevr::duoview::dx12::M1Resources::goald_log_settings.load();
                                                    SPDLOG_INFO("[DuoView][GoalD] settings history={} motion_source={} motion_limit={:.2f} confirm_texels={} jitter_negative={} fast_raster={} warp_bypass={} fovea_steps={} periphery_steps={} head_shift_mean={:.2f} head_shift_max={:.2f}",
                                                        gls&1u, (gls>>1)&3u, double(uevr::duoview::dx12::M1Resources::goald_log_limit.load()),
                                                        (gls>>4)&15u, (gls>>8)&1u, (gls>>9)&1u, (gls>>10)&1u, (gls>>12)&15u, (gls>>16)&15u,
                                                        hsn ? double(hsc)/100.0/double(hsn) : -1.0, double(hsm)/100.0);
                                                    {   // 65_ VRS state (last frame)
                                                        const uint32_t gv=uevr::duoview::duo_goald_vrs().load();
                                                        const uint64_t gr=uevr::duoview::duo_goald_vrs_rect().load();
                                                        SPDLOG_INFO("[DuoView][GoalD] vrs requested={} effective={} tier={} additional_rates={} reason={} draws={} eye0_fovea_px={},{}-{},{} raster_variant_missing={}",
                                                            gv&15u, (gv>>4)&15u, (gv>>8)&3u, (gv>>10)&1u, (gv>>12)&15u, (gv>>16)&255u,
                                                            gr&0xffffu, (gr>>16)&0xffffu, (gr>>32)&0xffffu, (gr>>48)&0xffffu,
                                                            (uevr::duoview::duo_goald_modes().load()>>4)&1u);
                                                    }
                                                    SPDLOG_INFO("[DuoView][GoalD] history requested={} active={} reason={} frames={} valid_frames={} moving_frames={} from_history_permille={} mode_fallback_bits={}",
                                                        gh&1u, (gh>>1)&1u, (gh>>2)&15u,
                                                        uevr::duoview::dx12::M1Resources::goald_hist_frames.exchange(0),
                                                        uevr::duoview::dx12::M1Resources::goald_hist_valid_frames.exchange(0),
                                                        uevr::duoview::dx12::M1Resources::goald_hist_moving_frames.exchange(0),
                                                        ht ? hu*1000u/ht : 0u,
                                                        uevr::duoview::duo_goald_modes().load()&15u);
                                                    {   // 62_: motion vector capture + NGX depth/MV copy GPU time (game list)
                                                        using PD=uevr::quadview::ngx::PeripheryDepth;
                                                        const uint64_t mvf=uevr::duoview::dx12::M1Resources::goald_mv_frames.exchange(0);
                                                        const uint64_t mvq=uevr::duoview::dx12::M1Resources::goald_mv_abs_quarter.exchange(0);
                                                        const uint64_t cns=PD::goald_copy_ns.exchange(0), cn=PD::goald_copy_samples.exchange(0);
                                                        const uint32_t msz=PD::goald_mv_size.load();
                                                        SPDLOG_INFO("[DuoView][GoalD] motion mv_frames={} fallback_frames={} mean_abs_mv_texels={:.3f} mv_copies={} mv_fails={} mv_reason={} mv_format={} mv_size={}x{} depth_size={}x{} mv_scale={:.4f},{:.4f} ngx_copy_gpu_ms={:.3f} copy_samples={}",
                                                            mvf, uevr::duoview::dx12::M1Resources::goald_mv_fallback_frames.exchange(0),
                                                            ht ? double(mvq)/4.0/double(ht) : 0.0,
                                                            PD::goald_mv_copies.exchange(0), PD::goald_mv_fails.exchange(0), PD::goald_mv_reason.load(),
                                                            PD::goald_mv_format.load(), msz>>16, msz&0xffffu,
                                                            PD::goald_depth_size.load()>>16, PD::goald_depth_size.load()&0xffffu,
                                                            PD::goald_mv_scale_x.load(), PD::goald_mv_scale_y.load(),
                                                            cn ? double(cns)/double(cn)/1.0e6 : -1.0, cn);
                                                    }
                                                    for (uint32_t mode=0; mode<2; ++mode) {
                                                        auto* st=uevr::duoview::duo_stage_ns()+mode*9u;
                                                        const uint64_t n=st[8].exchange(0);
                                                        double ms[8]{};
                                                        for (uint32_t i=0; i<8; ++i) ms[i]=n ? double(st[i].exchange(0))/double(n)/1.0e6 : (st[i].exchange(0),0.0);
                                                        if (n) SPDLOG_INFO("[DuoView][Timing] mode={} frames={} gpu_ms: b40_mono={:.3f} coarse_depth={:.3f} history={:.3f} m4_fovea={:.3f} other_compute={:.3f} raster={:.3f} output_copy={:.3f} total={:.3f}",
                                                            mode ? "stereo" : "mono", n, ms[0], ms[1], ms[2], ms[3], ms[4], ms[5], ms[6], ms[7]);
                                                    }
                                                    SPDLOG_INFO("[DuoView][GoalD] grid requested={} effective={} reason={} field={}x{} hi_frames={} m4_gpu_ms={:.3f} gpu_samples={}",
                                                        (gd&1u) ? 4096 : 1024, (gd&2u) ? 4096 : 1024, (gd>>2)&15u,
                                                        gf>>16, gf&0xffffu,
                                                        uevr::duoview::dx12::M1Resources::goald_hi_frames.exchange(0),
                                                        gpu_n ? double(gpu_ns)/double(gpu_n)/1.0e6 : -1.0, gpu_n);
                                                }
'''


GOALD_CALLER_GUARD = r'''                            // Goal D (review #373 F2): a DuoView copy that was attempted but did not end
                            // in a submitted recorded list (early return before record, reject, copy
                            // failure) invalidates the fovea depth history: never reuse older data.
                            if (callback_attempted && !(submitted && recorded))
                                uevr::duoview::dx12::M1Resources::goald_drop_shared();
                            if (compositor_fault) {
                                vr->duoview_abort("Validated Native Stereo Fix pair failed DuoView composition");
'''


GOALD_CALLER_MV = r'''                                            // Goal D (62_): ask the NGX hook for motion vectors / copy timing (next Evaluate).
                                            uevr::quadview::ngx::PeripheryDepth::goald_mv_request.store(
                                                config.settings.goald_history!=0u && config.settings.goald_motion_source!=0u,std::memory_order_relaxed);
                                            uevr::quadview::ngx::PeripheryDepth::goald_copy_timing.store(config.settings.gpu_timing,std::memory_order_relaxed);
                                            if (snapshot && m25_fine && (config.settings.m25_fine_mode==1u || pair.first==snapshot)) {
'''


def component(src):
    src = once(src, '                                            if (snapshot && m25_fine && (config.settings.m25_fine_mode==1u || pair.first==snapshot)) {\n',
               GOALD_CALLER_MV, 'goal D MV request')
    src = once(src, '                                                    focus->jitter_uv,focus,config.settings.m25_fine_mode==1u ? 1.f : depths.m24_fine_weight()};\n',
               '                                                    focus->jitter_uv,focus,config.settings.m25_fine_mode==1u ? 1.f : depths.m24_fine_weight()};\n'
               '                                                if (focus->mv_valid && focus->mv_texture) { // goal D (62_): same slot, same lease\n'
               '                                                    fine_depth->mv=focus->mv_texture.Get();\n'
               '                                                    fine_depth->mv_format=focus->mv_srv_format;\n'
               '                                                    fine_depth->mv_scale=focus->mv_scale;\n'
               '                                                }\n',
               'goal D MV into fine depth')
    src = once(src, '                                                    uevr::duoview::dx12::M1Resources::m4_fine_h.load());\n',
               GOALD_LOG, 'goal D log line')
    return once(src,
                '                            if (compositor_fault) {\n'
                '                                vr->duoview_abort("Validated Native Stereo Fix pair failed DuoView composition");\n',
                GOALD_CALLER_GUARD, 'goal D caller drops history without a submitted list')


# ---------------------------------------------------------------- NGX motion vectors (62_)
NGX_SLOT_MEMBERS = r'''    ComPtr<ID3D12CommandQueue> duoview_producer_queue;
    // Goal D (62_): DLSS motion vectors of the same Evaluate, copied next to the fine
    // depth (same slot, lease and pairing). Fine output only, only while requested.
    ComPtr<ID3D12Resource> mv_texture, mv_source_reference;
    DXGI_FORMAT mv_srv_format{DXGI_FORMAT_UNKNOWN};
    std::array<float,2> mv_scale{1.f,1.f};
    bool mv_valid{};
    // Goal D: GPU timestamps around this slot's depth (+MV) copies on the game list;
    // read only after the slot's producer fence completed (slot reuse).
    uint32_t goald_ts_index{~0u};
    bool goald_ts_pending{};
};
'''

NGX_CLASS_MEMBERS = r'''class PeripheryDepth final {
public:
    // ---- Goal D (62_): requested by the DuoView caller every frame (menu).
    inline static std::atomic<bool> goald_mv_request{}, goald_copy_timing{};
    // MV capture diagnostics (log). reason: 0 ok, 1 no MotionVectors parameter,
    // 2 unsupported format/layout, 3 render-res subrect outside the MV texture, 4 allocation failed.
    inline static std::atomic<uint32_t> goald_mv_format{}, goald_mv_size{}, goald_mv_reason{}, goald_depth_size{};
    inline static std::atomic<float> goald_mv_scale_x{}, goald_mv_scale_y{};
    inline static std::atomic<uint64_t> goald_mv_copies{}, goald_mv_fails{};
    inline static std::atomic<uint64_t> goald_copy_ns{}, goald_copy_samples{}, goald_copy_frequency{};
    static constexpr uint32_t goald_ts_slots = 32;
    ComPtr<ID3D12QueryHeap> goald_ts_heap_;
    ComPtr<ID3D12Resource> goald_ts_readback_;
    uint32_t goald_ts_next_{};
    bool goald_ts_ready(ID3D12Device* dev) {
        if (goald_ts_heap_ && goald_ts_readback_) return true;
        if (goald_ts_heap_ || goald_ts_readback_) return false; // a failed creation is not retried
        D3D12_QUERY_HEAP_DESC q{}; q.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP; q.Count=2u*goald_ts_slots;
        if (FAILED(dev->CreateQueryHeap(&q,IID_PPV_ARGS(&goald_ts_heap_)))) { goald_ts_heap_.Reset(); return false; }
        D3D12_HEAP_PROPERTIES hp{}; hp.Type=D3D12_HEAP_TYPE_READBACK;
        D3D12_RESOURCE_DESC b{}; b.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; b.Width=16u*goald_ts_slots;
        b.Height=b.DepthOrArraySize=b.MipLevels=1; b.SampleDesc.Count=1; b.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&b,D3D12_RESOURCE_STATE_COPY_DEST,nullptr,
                IID_PPV_ARGS(&goald_ts_readback_)))) { goald_ts_readback_.Reset(); return false; }
        return true;
    }
    // Previous copy time of a slot about to be reused (its producer work has completed).
    void goald_read_copy_time(DepthSnapshot& slot) {
        if (!slot.goald_ts_pending || slot.goald_ts_index>=goald_ts_slots || !goald_ts_readback_) { slot.goald_ts_pending=false; return; }
        slot.goald_ts_pending=false;
        const uint64_t f=goald_copy_frequency.load(std::memory_order_relaxed);
        if (!f || !slot.producer_fence || !slot.producer_fence_value ||
            slot.producer_fence->GetCompletedValue()<slot.producer_fence_value) return;
        const SIZE_T o=16u*slot.goald_ts_index;
        const D3D12_RANGE r{o,o+16u};
        void* m=nullptr;
        if (FAILED(goald_ts_readback_->Map(0,&r,&m)) || !m) return;
        uint64_t t[2]{};
        std::memcpy(t,static_cast<const char*>(m)+o,sizeof(t));
        const D3D12_RANGE w{0,0};
        goald_ts_readback_->Unmap(0,&w);
        if (t[1]>=t[0]) {
            const double ns=double(t[1]-t[0])*1.0e9/double(f);
            if (ns<1.0e9) { goald_copy_ns+=uint64_t(ns); ++goald_copy_samples; }
        }
    }
    // Copy the DLSS motion vectors of this Evaluate into the slot (render-resolution
    // MVs at the depth subrect only; anything else is logged and history falls back
    // to head-pose mode).
    void goald_capture_mv(ID3D12GraphicsCommandList* cmd, const NgxParameters* p, DepthSnapshot& slot, bool fine,
                          uint32_t in_w, uint32_t in_h, const D3D12_RESOURCE_DESC& depth_desc, ID3D12Device* dev) {
        slot.mv_valid=false; slot.mv_source_reference.Reset();
        if (!fine || !goald_mv_request.load(std::memory_order_relaxed)) return;
        const auto fail=[](uint32_t r) { goald_mv_reason.store(r,std::memory_order_relaxed); ++goald_mv_fails; };
        auto* mv=ngx_resource(p,"MotionVectors");
        if (!mv) { fail(1u); return; }
        const auto d=mv->GetDesc();
        goald_mv_format.store(uint32_t(d.Format),std::memory_order_relaxed);
        goald_mv_size.store((uint32_t(d.Width)<<16)|(d.Height&0xffffu),std::memory_order_relaxed);
        DXGI_FORMAT srv=DXGI_FORMAT_UNKNOWN, copy=DXGI_FORMAT_UNKNOWN;
        switch (d.Format) {
        case DXGI_FORMAT_R16G16_FLOAT: case DXGI_FORMAT_R16G16_TYPELESS:
            srv=DXGI_FORMAT_R16G16_FLOAT; copy=DXGI_FORMAT_R16G16_TYPELESS; break;
        case DXGI_FORMAT_R32G32_FLOAT: case DXGI_FORMAT_R32G32_TYPELESS:
            srv=DXGI_FORMAT_R32G32_FLOAT; copy=DXGI_FORMAT_R32G32_TYPELESS; break;
        case DXGI_FORMAT_R16G16B16A16_FLOAT: case DXGI_FORMAT_R16G16B16A16_TYPELESS:
            srv=DXGI_FORMAT_R16G16B16A16_FLOAT; copy=DXGI_FORMAT_R16G16B16A16_TYPELESS; break;
        case DXGI_FORMAT_R32G32B32A32_FLOAT: case DXGI_FORMAT_R32G32B32A32_TYPELESS:
            srv=DXGI_FORMAT_R32G32B32A32_FLOAT; copy=DXGI_FORMAT_R32G32B32A32_TYPELESS; break;
        default: break;
        }
        if (d.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D || d.SampleDesc.Count!=1 || d.DepthOrArraySize!=1 ||
            srv==DXGI_FORMAT_UNKNOWN) { fail(2u); return; }
        const auto bx=ngx_uint(p,"DLSS.Input.MV.Subrect.Base.X"), by=ngx_uint(p,"DLSS.Input.MV.Subrect.Base.Y");
        // #377 headset: STALKER 2 gives a 2436x2150 MV texture while the depth texture differs
        // (old size check -> reason 3 every frame). UE's DLSS plugin always declares MVLowRes
        // (velocity rendered at render resolution inside a pooled, larger texture), so accept
        // any MV texture whose render-res subrect fits; units are verified in the log
        // (mean_abs_mv_texels vs head_shift). Only a subrect outside the texture is reason 3.
        goald_depth_size.store((uint32_t(depth_desc.Width)<<16)|(depth_desc.Height&0xffffu),std::memory_order_relaxed);
        if (uint64_t(bx)+in_w>d.Width || uint64_t(by)+in_h>d.Height) { fail(3u); return; }
        constexpr auto read=D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE;
        const auto have=slot.mv_texture ? slot.mv_texture->GetDesc() : D3D12_RESOURCE_DESC{};
        if (!slot.mv_texture || have.Width!=in_w || have.Height!=in_h || have.Format!=copy) {
            slot.mv_texture.Reset(); // the slot's producer work and every lease have retired
            D3D12_RESOURCE_DESC td{};
            td.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
            td.Width=in_w; td.Height=in_h; td.DepthOrArraySize=1; td.MipLevels=1;
            td.Format=copy; td.SampleDesc.Count=1; td.Layout=D3D12_TEXTURE_LAYOUT_UNKNOWN;
            D3D12_HEAP_PROPERTIES hp{}; hp.Type=D3D12_HEAP_TYPE_DEFAULT;
            if (FAILED(dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&td,read,nullptr,IID_PPV_ARGS(&slot.mv_texture)))) {
                slot.mv_texture.Reset(); fail(4u); return;
            }
            slot.mv_texture->SetName(L"DuoView::GoalDMotionVectors");
        }
        constexpr auto ngx_state=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        transition(cmd,mv,ngx_state,D3D12_RESOURCE_STATE_COPY_SOURCE);
        transition(cmd,slot.mv_texture.Get(),read,D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_TEXTURE_COPY_LOCATION from{}, to{};
        from.pResource=mv; from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        to.pResource=slot.mv_texture.Get(); to.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        const D3D12_BOX box{bx,by,0,bx+in_w,by+in_h,1};
        cmd->CopyTextureRegion(&to,0,0,0,&from,&box);
        transition(cmd,slot.mv_texture.Get(),D3D12_RESOURCE_STATE_COPY_DEST,read);
        transition(cmd,mv,D3D12_RESOURCE_STATE_COPY_SOURCE,ngx_state);
        float sx=1.f, sy=1.f;
        if (!ngx_success(p->Get("MV.Scale.X",&sx)) || !std::isfinite(sx) || sx==0.f) sx=1.f;
        if (!ngx_success(p->Get("MV.Scale.Y",&sy)) || !std::isfinite(sy) || sy==0.f) sy=1.f;
        slot.mv_scale={sx,sy}; slot.mv_srv_format=srv; slot.mv_valid=true; slot.mv_source_reference=mv;
        goald_mv_scale_x.store(sx,std::memory_order_relaxed); goald_mv_scale_y.store(sy,std::memory_order_relaxed);
        goald_mv_reason.store(0u,std::memory_order_relaxed);
        ++goald_mv_copies;
    }
'''

NGX_COPY_BEFORE = r'''        // Goal D: time this slot's copies (previous result first; the slot has retired).
        goald_read_copy_time(*slot);
        const bool goald_timed=goald_copy_timing.load(std::memory_order_relaxed) &&
            cmd->GetType()!=D3D12_COMMAND_LIST_TYPE_COPY && goald_ts_ready(dev.Get());
        if (goald_timed && slot->goald_ts_index==~0u && goald_ts_next_<goald_ts_slots) slot->goald_ts_index=goald_ts_next_++;
        const bool goald_stamp=goald_timed && slot->goald_ts_index<goald_ts_slots;
        if (goald_stamp) cmd->EndQuery(goald_ts_heap_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2u*slot->goald_ts_index);
        // Plane 0 (depth) only; subresource 0 is the depth plane for every accepted format.
'''

NGX_COPY_AFTER = r'''        slot->source_reference = depth;
        goald_capture_mv(cmd,p,*slot,m25_role==2u,in_w,in_h,desc,dev.Get()); // goal D (62_)
        if (goald_stamp) {
            cmd->EndQuery(goald_ts_heap_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2u*slot->goald_ts_index+1u);
            cmd->ResolveQueryData(goald_ts_heap_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2u*slot->goald_ts_index,2,
                                  goald_ts_readback_.Get(),16u*slot->goald_ts_index);
        }
        slot->goald_ts_pending=goald_stamp;
'''


def ngx_depth(src):
    src = once(src, '    ComPtr<ID3D12CommandQueue> duoview_producer_queue;\n};\n', NGX_SLOT_MEMBERS, 'goal D MV slot members')
    src = once(src, 'class PeripheryDepth final {\npublic:\n', NGX_CLASS_MEMBERS, 'goal D MV capture methods')
    src = once(src,
               '        // Plane 0 (depth) only; subresource 0 is the depth plane for every accepted format.\n',
               NGX_COPY_BEFORE, 'goal D copy timestamp start')
    src = once(src, '        slot->source_reference = depth;\n', NGX_COPY_AFTER, 'goal D MV copy + timestamp end')
    src = once(src, '            const auto value = ++next_fence_value_;\n',
               '            const auto value = ++next_fence_value_;\n'
               '            if (!goald_copy_frequency.load(std::memory_order_relaxed)) { // goal D copy timing\n'
               '                UINT64 goald_f{};\n'
               '                if (SUCCEEDED(queue->GetTimestampFrequency(&goald_f))) goald_copy_frequency.store(goald_f,std::memory_order_relaxed);\n'
               '            }\n',
               'goal D copy timestamp frequency')
    if '#include <cstring>' not in src:
        src = once(src, '#include <atomic>\n', '#include <atomic>\n#include <cstring>\n', 'goal D cstring include')
    return src


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
    native = a.shaders / 'DuoViewNativeCompositeRaster.hlsl'
    native_original = native.read_bytes().decode('utf-8')
    edit(native, native_raster)
    if strip_goald(native.read_bytes().decode('utf-8')) != native_original:
        raise RuntimeError('Off native raster text changed outside DUOVIEW_GOALD_GRID blocks')
    edit(vr / 'DuoViewM1D3D12.hpp', m1_backend)
    edit(vr / 'DuoViewD3D12.hpp', compositor_backend)
    edit(vr / 'DuoViewConfig.hpp', config)
    edit(a.backend / 'src/mods/VR.hpp', vr_hpp)
    edit(a.backend / 'src/mods/VR.cpp', vr_cpp)
    edit(vr / 'D3D12Component.cpp', component)
    edit(vr / 'QuadViewNgxDepth.hpp', ngx_depth)
    print('goal D switches 1-4: Off unchanged; 4096/history/one-sided/fill only in separate m4g_* DXBC + goal D settings')


if __name__ == '__main__':
    main()

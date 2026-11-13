#!/usr/bin/env python3
"""M3b P1: source-colour/depth GPU jitter score with 120-frame hysteresis."""
from pathlib import Path
import sys
from apply_duoview_b40_pipeline import patch

def main():
    if len(sys.argv)!=3:raise SystemExit("Usage: apply_duoview_m3b_jitter.py <backend> <shaders>")
    mods=Path(sys.argv[1])/"src/mods";sh=Path(sys.argv[2])
    patch(sh/"DuoViewM1Stereo.hlsl",[
      ("P1 score kernel",
       "groupshared uint M25Valid[256],M25Agree[256];",
       """groupshared uint M3bScoreReduction[384];
[numthreads(128,1,1)]
void CSJitterScoreM3b(uint lane:SV_GroupIndex) {
    uint scoreMinus=0u,scoreZero=0u,scorePlus=0u;
    const uint w=M1Grid.x,h=(M1Grid.y+3u)/4u;
    const float2 stepUv=1.0/float2(max(M1Grid.xy,uint2(1u,1u)));
    [loop] for(uint n=lane;n<w*h;n+=128u) {
        const uint x=n%w,y=(n/w)*4u;
        if(x==0u || x+1u>=w || y>=M1Grid.y) continue;
        const float2 u=(float2(x,y)+.5)/float2(M1Grid.xy);
        if(any(u<M2Crop.xy) || any(u>=M2Crop.zw)) continue;
        const float3 cl=M3bColorAt(u-float2(stepUv.x,0));
        const float3 cr=M3bColorAt(u+float2(stepUv.x,0));
        const float ec=abs(dot(cr-cl,float3(.2126,.7152,.0722)));
        if(ec<.00001) continue;
        uint candidates[3];
        [unroll] for(uint s=0u;s<3u;++s) {
            const float sign=float(int(s)-1);
            const float2 corrected=u+sign*M1Eye.zw;
            const int2 center=int2(corrected*float2(M1Rect.zw));
            const int2 left=int2((corrected-float2(stepUv.x,0))*float2(M1Rect.zw));
            const int2 right=int2((corrected+float2(stepUv.x,0))*float2(M1Rect.zw));
            const float d=DecodeM1Depth(center);
            const float ed=abs(DecodeM1Depth(right)-DecodeM1Depth(left))/max(d,.0001);
            candidates[s]=uint(min(ed*ec*4096.0,65535.0));
        }
        scoreMinus+=candidates[0];scoreZero+=candidates[1];scorePlus+=candidates[2];
    }
    M3bScoreReduction[lane]=scoreMinus;
    M3bScoreReduction[128u+lane]=scoreZero;
    M3bScoreReduction[256u+lane]=scorePlus;
    GroupMemoryBarrierWithGroupSync();
    for(uint st=64u;st>0u;st>>=1u) {
        if(lane<st) {
            M3bScoreReduction[lane]+=M3bScoreReduction[lane+st];
            M3bScoreReduction[128u+lane]+=M3bScoreReduction[128u+lane+st];
            M3bScoreReduction[256u+lane]+=M3bScoreReduction[256u+lane+st];
        }
        GroupMemoryBarrierWithGroupSync();
    }
    if(lane==0u) {
        M25StatsWrite.Store(32,0u);M25StatsWrite.Store(36,0u);M25StatsWrite.Store(40,0u);
        uint old=0u;
        M25StatsWrite.InterlockedAdd(32,M3bScoreReduction[0],old);
        M25StatsWrite.InterlockedAdd(36,M3bScoreReduction[128],old);
        M25StatsWrite.InterlockedAdd(40,M3bScoreReduction[256],old);
    }
}
groupshared uint M25Valid[256],M25Agree[256];"""),
    ])
    patch(mods/"vr/DuoViewM1D3D12.hpp",[
      ("P1 includes",
       "#include <memory>\n",
       "#include <memory>\n#include <mutex>\n#include <atomic>\n#include <spdlog/spdlog.h>\n"),
      ("P1 shader pipeline and readback flags",
       "    ComPtr<ID3D12PipelineState> raster, condition, vertical, m25_analyse, m25_guard;",
       "    ComPtr<ID3D12PipelineState> raster, condition, vertical, m25_analyse, m25_guard, m3b_jitter_score;"),
      ("P1 pending auto",
       "    bool m25_content_active{},m25_pending{};",
       "    bool m25_content_active{},m25_pending{};\n"
       "    bool m3b_auto_active{},m3b_pending_auto{},m3b_pending_gate{};\n"
       "    float m3b_pending_jitter_px{};"),
      ("P1 extend score buffer",
       "    struct M25GpuCounters {uint32_t guard{},cells{},agree{},varied{},passing{},weight_x1000{},reserved[2]{};};",
       "    struct M25GpuCounters {uint32_t guard{},cells{},agree{},varied{},passing{},weight_x1000{},reserved[2]{},m3b_scores[3]{};};"),
      ("P1 global scoring state",
       "    static void m25_count_vertical() {++vertical_dispatches;}",
       """    inline static std::atomic<uint64_t> m3b_minus{},m3b_zero{},m3b_plus{};
    struct M3bAutoJitter {
        inline static std::mutex mutex{};
        inline static std::atomic<int> sign{1};
        inline static uint32_t frames{},streak{};
        inline static int last_vote{99};
        inline static uint64_t scores[3]{};
        inline static double pixel_sum{};
        static void note(const M25GpuCounters& result,float pixelMagnitude) {
            std::scoped_lock lock(mutex);
            scores[0]+=result.m3b_scores[0];scores[1]+=result.m3b_scores[1];scores[2]+=result.m3b_scores[2];
            pixel_sum+=pixelMagnitude;
            if(++frames<120u) return;
            uint32_t best=0u;
            if(scores[1]>scores[best]) best=1u;
            if(scores[2]>scores[best]) best=2u;
            const uint64_t other=(std::max)(scores[(best+1u)%3u],scores[(best+2u)%3u]);
            const bool decisive=other>0u && double(scores[best])>=1.03*double(other) && pixel_sum/120.0>.05;
            const int vote=decisive ? (best==0u ? -1 : (best==2u ? 1 : 0)) : 99;
            if(vote!=99) {
                streak=vote==last_vote ? streak+1u : 1u;last_vote=vote;
                if(streak>=2u && vote!=0) sign.store(vote,std::memory_order_relaxed);
            } else {streak=0u;last_vote=99;}
            spdlog::info("[DuoView][M3b] jitter score minus={} zero={} plus={} vote={} active={} mean_px={:.3f}",
                scores[0],scores[1],scores[2],vote,sign.load(),pixel_sum/120.0);
            scores[0]=scores[1]=scores[2]=0u;frames=0u;pixel_sum=0.0;
        }
    };
    static void m25_count_vertical() {++vertical_dispatches;}"""),
      ("P1 consume retired scores",
       "            ++gpu_frames;gpu_guard_off+=c.guard;gpu_cells+=c.cells;",
       "            if(m3b_pending_auto) {\n"
       "                M3bAutoJitter::note(c,m3b_pending_jitter_px);\n"
       "                m3b_minus+=c.m3b_scores[0];m3b_zero+=c.m3b_scores[1];m3b_plus+=c.m3b_scores[2];\n"
       "            }\n            if(m3b_pending_gate) {\n"
       "            ++gpu_frames;gpu_guard_off+=c.guard;gpu_cells+=c.cells;"),
      ("P1 close gate stats block",
       "            gpu_weight_x1000+=c.weight_x1000;gpu_active_tiles+=c.reserved[0];",
       "            gpu_weight_x1000+=c.weight_x1000;gpu_active_tiles+=c.reserved[0];\n            }"),
      ("P1 extend public counter window",
       "    static std::array<uint64_t,9> m25_take_gpu_window() {",
       "    static std::array<uint64_t,12> m25_take_gpu_window() {"),
      ("P1 append scoring window",
       "                vertical_dispatches.exchange(0)};",
       "                vertical_dispatches.exchange(0),\n"
       "                m3b_minus.exchange(0),m3b_zero.exchange(0),m3b_plus.exchange(0)};"),
      ("P1 create pipeline",
       "        compute.CS={m25_guard_bytecode,sizeof(m25_guard_bytecode)};",
       "        compute.CS={m3b_jitter_score_bytecode,sizeof(m3b_jitter_score_bytecode)};\n"
       "        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m3b_jitter_score)))) return false;\n"
       "        compute.CS={m25_guard_bytecode,sizeof(m25_guard_bytecode)};"),
      ("P1 ready",
       "m25_analyse && m25_guard && m25_tiles",
       "m25_analyse && m25_guard && m3b_jitter_score && m25_tiles"),
      ("P1 activate auto and sign",
       "        if(jitter_mode==1u || jitter_mode==2u) {",
       "        if(jitter_mode==3u && data.grid[0]) {\n"
       "            data.m2_sharpen[3]=1.f;\n"
       "            data.m3_flags[1]=float(M3bAutoJitter::sign.load(std::memory_order_relaxed));\n"
       "        }\n"
       "        m3b_auto_active=jitter_mode==3u && data.grid[0]>0u;\n"
       "        m3b_pending_jitter_px=std::hypot(data.eye[2]*float(data.rect[2]),data.eye[3]*float(data.rect[3]));\n"
       "        if(jitter_mode==1u || jitter_mode==2u) {"),
    ])
    patch(mods/"vr/DuoViewD3D12.hpp",[
      ("P1 dispatch auto score",
       "            cmd->Dispatch(m1_.rows,1,1);",
       """            if(m1_.m3b_auto_active) {
                constexpr auto reads=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |
                                     D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
                transition(cmd,m1_.m25_stats.Get(),reads,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                cmd->SetPipelineState(m1_.m3b_jitter_score.Get());
                cmd->Dispatch(1,1,1);
                D3D12_RESOURCE_BARRIER scoreBarrier{};
                scoreBarrier.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;
                scoreBarrier.UAV.pResource=m1_.m25_stats.Get();
                cmd->ResourceBarrier(1,&scoreBarrier);
                transition(cmd,m1_.m25_stats.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,reads);
                cmd->SetPipelineState(m1_.condition.Get());
            }
            cmd->Dispatch(m1_.rows,1,1);"""),
      ("P1 copy scoring stats",
       "            if(m1_.m25_content_active) {\n                constexpr auto reads=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |\n                                     D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;\n                transition(cmd,m1_.m25_stats.Get(),reads,D3D12_RESOURCE_STATE_COPY_SOURCE);",
       "            if(m1_.m25_content_active || m1_.m3b_auto_active) {\n"
       "                m1_.m3b_pending_gate=m1_.m25_content_active;\n"
       "                m1_.m3b_pending_auto=m1_.m3b_auto_active;\n"
       "                constexpr auto reads=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |\n"
       "                                     D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;\n"
       "                transition(cmd,m1_.m25_stats.Get(),reads,D3D12_RESOURCE_STATE_COPY_SOURCE);"),
    ])
    patch(mods/"vr/DuoViewConfig.hpp",[
      ("P1 allow Auto",
       "out.m3_jitter_mode=(std::min)(requested.m3_jitter_mode,2u);",
       "out.m3_jitter_mode=(std::min)(requested.m3_jitter_mode,3u);"),
    ])
    patch(mods/"VR.hpp",[
      ("P1 combo label",
       '"Align: + direction", "Align: - direction" };',
       '"Align: + direction", "Align: - direction", "Auto (GPU score)" };'),
    ])
    patch(mods/"VR.cpp",[
      ("P1 freeze Auto",
       'm_duo_m3_jitter->value(),0,2)),',
       'm_duo_m3_jitter->value(),0,3)),'),
    ])
    patch(Path(__file__).resolve().parent/"embed_duoview_b40.py",[
      ("P1 compile jitter kernel",
       '            ("CSGuardM25","cs_5_0","m25_guard_bytecode","DuoViewM1Stereo.hlsl",("DUOVIEW_M1_CONDITION",)),',
       '            ("CSGuardM25","cs_5_0","m25_guard_bytecode","DuoViewM1Stereo.hlsl",("DUOVIEW_M1_CONDITION",)),\n'
       '            ("CSJitterScoreM3b","cs_5_0","m3b_jitter_score_bytecode","DuoViewM1Stereo.hlsl",("DUOVIEW_M1_CONDITION",)),'),
    ])
    print("M3b P1 GPU jitter candidate scoring, 120-frame vote, two-window hysteresis installed")

if __name__=="__main__":main()

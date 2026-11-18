#!/usr/bin/env python3
"""Generated-source contracts for goal D switch 1 (fovea depth grid 1024 / 4096). No GPU.

Off (1024) must keep the baseline PSOs, the baseline field and an unchanged constant
buffer; 4096 code exists only in DUOVIEW_GOALD_GRID blocks and separate m4g_* PSOs."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_duoview_goald import strip_goald  # noqa: E402

backend, shaders = map(Path, sys.argv[1:3])
vr = backend / 'src/mods/vr'
hlsl = (shaders / 'DuoViewM1Stereo.hlsl').read_text(encoding='utf-8')
m1 = (vr / 'DuoViewM1D3D12.hpp').read_text(encoding='utf-8')
comp = (vr / 'DuoViewD3D12.hpp').read_text(encoding='utf-8')
cfg = (vr / 'DuoViewConfig.hpp').read_text(encoding='utf-8')
vrcpp = (backend / 'src/mods/VR.cpp').read_text(encoding='utf-8')
log = (vr / 'D3D12Component.cpp').read_text(encoding='utf-8')
fails = []


def need(cond, what):
    if not cond:
        fails.append(what)


off = strip_goald(hlsl)
for token in ('CSConditionM4G', 'GDRow', 'DUOVIEW_GOALD_GRID'):
    need(token not in off, f'Off shader text contains {token}')
need(hlsl.count('#ifdef DUOVIEW_GOALD_GRID') == 3, 'goal D shader blocks: conditioning + raster helper + raster root choice')
need('void CSConditionM4G(' in hlsl and 'void CSConditionM4GVertical(' in hlsl, 'goal D kernels present')
# Groupshared budget of the new kernels: one 4096-float row only (16 KiB).
block = hlsl.split('#ifdef DUOVIEW_GOALD_GRID', 1)[1].split('#endif', 1)[0]
shared = re.findall(r'groupshared\s+float\s+(\w+)\[(\d+)\]', block)
need(shared == [('GDRow', '4096')], f'goal D groupshared {shared}')
need('void CSGoalDHistory(' in block and 'void CSConditionM4GH(' in block, 'switch 2 kernels present')
need('RWTexture2DArray<uint> GDHistory : register(u6);' in block, 'history on the reserved u6 slot')
need('M4FoveaConditioned[uint3(x,row,eye)]' in block, 'switch 3 per-eye slices')
# Constant buffer unchanged: no new cbuffer members.
cb = hlsl.split('cbuffer DuoViewM1', 1)[1].split('};', 1)[0]
need('Goal' not in cb and 'GD' not in cb, 'cbuffer DuoViewM1 unchanged')
need('sizeof(M1Constants) == ' in m1 and 'goald' not in m1.split('struct M1Constants', 1)[1].split('};', 1)[0],
     'M1Constants unchanged')
# Off path: baseline PSOs and field whenever the 4096 field is not active.
need('(m1_.goald_hist_active ? m1_.m4g_condition_h.Get() : m1_.m4g_condition.Get()) : m1_.m4_condition.Get();' in comp, 'condition PSO select')
need(comp.index('goald_bind_history(device);') < comp.index('cmd->SetComputeRootDescriptorTable(8,m4_table);'), 'u6 bound before tables')
need('if (m4_active && m4_hi_active && focus) {' in m1, 'switches 2-4 constants only on the 4096 path')
need('bool goald_history{0}' not in cfg and 'goald_history{0}' in cfg, 'switch 2 default off')
need('m1_.m4_hi_active ? m1_.m4g_vertical.Get() : m1_.m4_vertical.Get()' in comp, 'vertical PSO select')
need('return m4_hi_active && m4_depth_hi ? m4_depth_hi.Get() : m4_depth.Get();' in m1, 'field select')
need(m1.count('m4_hi_active=true;') == 1, 'single activation site')
need('if(edge_reach_px<10.f || m3_edges) goald_grid_reason=1u;' in m1, 'V2-only eligibility')
need('uint32_t depth_grid=1024u' in m1, 'default 1024')
need('goald_bound_key_=0u;' in comp and 'if (key==goald_bound_key_' in comp, 'descriptor rebinding keyed')
need(comp.index('goald_bind_m4_field(device);') < comp.index('cmd->SetComputeRootDescriptorTable(7,m4_table);'),
     'descriptors rebound before tables are set')
need('out.goald_depth_grid=requested.goald_depth_grid>=4096u ? 4096u : 1024u;' in cfg, 'settings sanitize')
need('uint32_t goald_depth_grid{1024};' in cfg, 'settings default 1024')
need('m_duo_goald_grid->value()==1 ? 4096u : 1024u' in vrcpp, 'menu maps to grid')
need('current.goald_depth_grid==candidate.goald_depth_grid' in vrcpp, 'menu change detection')
need('[DuoView][GoalD] grid requested=' in log, 'log line')
need('q.Count = 4;' in comp and 'TIMESTAMP,2);' in comp and 'TIMESTAMP,3);' in comp, 'M4 GPU timestamps')
# Review #368 fixes (11-18 pm).
need('s.parity^=1u' not in m1 and 'const uint32_t next_parity=s.parity^1u;' in m1, 'history parity not advanced in write_constants')
need(comp.count('m1_.goald_commit_history();') == 1 and
     comp.index('m1_.goald_commit_history();') > comp.index('void note_fine_depth_enqueued() {'),
     'history committed only when the XR caller reports the list submitted (review #372 R1)')
need('{ m1_.goald_drop_frame(); error_=reason; return false; }' in comp and
     'if (!m1_active || !m1_.goald_pending.active) m1_.goald_drop_frame();' in comp and
     'm1_.goald_drop_frame(); // goal D: gather never runs the history pass' in comp,
     'history dropped on reject, gather and frames without a history pass (R2)')
need('const bool same_mode=s.type==goald_history && s.jitter_negative==goald_jitter_negative;' in m1,
     'history type / jitter sign change starts fresh (R2)')
need('if (s.fresh_counters) return;' in comp and 's.fresh_counters=false;' in m1, 'counters valid only after a submitted pass (R7)')
need('GDThinAt(c,h,previous)' in hlsl and 'float(a+1u)<M6PreviousJitter.y' in hlsl and 'bestC' not in hlsl,
     'age + thin tested per candidate before max (R3)')
need('float GDKeptAt(' in hlsl, 'out-of-crop thin neighbours count as far (R4)')
need('if (!goald_hist_active) goald_history_state().have_previous=false;' in m1, 'history reset when Off')
need('goald_halo_bg=raster_true && !goald_true_depth;' in m1, 'halo off with true depth')
need('data.m8_effects[2]=data.m8_effects[3]=0.f;' in m1, 'legacy M8 fill zero in halo mode')
need('s.commits-r.first>=16u' in m1, 'retired history textures released')
need('const bool thinOnly=(GDFlags()&64u)!=0u;' in hlsl and 'GDLockedCell' in hlsl, 'history types all / thin only')
need('(goald_history>=2u ? 64u : 0u)' in m1 and 'm_duo_goald_history->value(),0,2' in vrcpp, 'history type from the menu')
need('hbBlend*smoothstep' in hlsl and 'GDReadFineEye(' in hlsl, 'K1: fine vs fine, crop blend weight')
need('duo_goald_modes()' in vrcpp, 'menu shows mode fallbacks')

if fails:
    print('GOALD CONTRACT FAIL:', *fails, sep='\n  ')
    sys.exit(1)
print('GOALD CONTRACTS PASS: Off text/PSOs/field/cbuffer unchanged; switches 1-4 isolated in m4g_* kernels + 4096 path')

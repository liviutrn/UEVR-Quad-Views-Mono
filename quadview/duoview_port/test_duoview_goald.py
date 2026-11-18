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
need(hlsl.count('#ifdef DUOVIEW_GOALD_GRID') == 1, 'exactly one goal D shader block')
need('void CSConditionM4G(' in hlsl and 'void CSConditionM4GVertical(' in hlsl, 'goal D kernels present')
# Groupshared budget of the new kernels: one 4096-float row only (16 KiB).
block = hlsl.split('#ifdef DUOVIEW_GOALD_GRID', 1)[1].split('#endif', 1)[0]
shared = re.findall(r'groupshared\s+float\s+(\w+)\[(\d+)\]', block)
need(shared == [('GDRow', '4096')], f'goal D groupshared {shared}')
need(block.count('M4FoveaConditioned[uint3(') == 3 and ',1u)]' not in block, 'goal D writes slice 0 only')
# Constant buffer unchanged: no new cbuffer members.
cb = hlsl.split('cbuffer DuoViewM1', 1)[1].split('};', 1)[0]
need('Goal' not in cb and 'GD' not in cb, 'cbuffer DuoViewM1 unchanged')
need('sizeof(M1Constants) == ' in m1 and 'goald' not in m1.split('struct M1Constants', 1)[1].split('};', 1)[0],
     'M1Constants unchanged')
# Off path: baseline PSOs and field whenever the 4096 field is not active.
need('m4_gpu_pso=m1_.m4_hi_active ? m1_.m4g_condition.Get() : m1_.m4_condition.Get();' in comp, 'condition PSO select')
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

if fails:
    print('GOALD CONTRACT FAIL:', *fails, sep='\n  ')
    sys.exit(1)
print('GOALD CONTRACTS PASS: Off text/PSOs/field/cbuffer unchanged; 4096 isolated in m4g_* kernels')

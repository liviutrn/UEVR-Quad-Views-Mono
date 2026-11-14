#!/usr/bin/env python3
"""UEVR Lua panel smoke test against real GENERATED script, not patch snippets.

Runs with Lua 5.4 and mocked UEVR/ImGui event bridge. Exercises both the
NR and Stereo menus with pass 1 and pass 2 enabled. No GPU/UEVR simulation
is claimed: only GUI execution and control registration are checked.
"""
from pathlib import Path
import sys
from lupa.lua54 import LuaRuntime

source = Path(sys.argv[1]) / "uevr/scripts/cheeky_foveated_dlss.lua"
if not source.is_file():
    raise RuntimeError(f"Missing generated script: {source}")
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
__seen = {}
__cb = {}
__toggle = {}
__sent = {}
fs = {
    read=function(path) return "disableMod=0" end,
    write=function(path,data) return true end
}
imgui = {
    ColumnFlags = nil,
    tree_node = function(label)
        return label == "Cheeky Foveated DLSS"
          or label == "DLSS 5 NR — game-native SR"
          or label == "Stereo and gaze"
          or label == "Pass 2 settings"
    end,
    tree_pop = function() end,
    text = function(s) end,
    text_colored = function(...) end,
    separator = function() end,
    spacing = function() end,
    same_line = function() end,
    begin_disabled = function(...) end,
    end_disabled = function(...) end,
    is_item_active = function() return false end,
    checkbox = function(label,v)
        __seen[label]=true
        if __toggle[label] ~= nil then
            local selected = __toggle[label]; __toggle[label]=nil
            return true, selected
        end
        return false,v
    end,
    slider_float = function(label,v) __seen[label]=true; return false,v end,
    slider_int = function(label,v) __seen[label]=true; return false,v end,
    combo = function(label,v,values) __seen[label]=true; return false,v end,
    button = function(label) __seen[label]=true;return false end,
    begin_table = function(...) return false end
}
uevr = {
    api = {dispatch_custom_event=function(_,evt,payload)
        __sent[#__sent+1] = {evt, payload}
    end},
    sdk = {callbacks = {
        on_lua_event=function(f) __cb.event=f end,
        on_frame=function(f) __cb.frame=f end
    }},
    lua = {add_script_panel=function(label, f) __cb.panel=f end}
}
__snap = {
    protocol=1,request=0,applied_request=0,ready=true,renderer=1,
    version="0.6.3",message="Ready.",nr="Active",
    settings={
        NrEnabled=true,NrPasses=2,NrPass1Views=7,NrPass2Views=3,
        NrPass2Foveated=true,NrPass2Width=0.5,NrPass2Height=0.5,
        NrPass2Roundness=0,NrPass2TransitionWidth=0.1,
        NrFoveated=false,NrWorkingScale=1,NrProcessingOrder=1,
        EyeProcessingMode=3,CenterMode=0,AutoStereoAlignment=false,
        NrPreset=1,ManualStereoMapping=false,
        FgEnabled=false,D3D11D3D12Transport=false,
        NrPass2SameAsPass1=true, NrIntensity=1,
        NrVramGuardMiB=1536, NrUseSourceRoles=true,
        NrAllocAdmission=true, NrFeatureReuse=true
    },
    nr_details={
        processing_width=1355,processing_height=1077,
        region_width=1355,region_height=1077,
        working_width=1355,working_height=1077,
        decoded_frames=1024,completed_two_pass_frames=512,
        before_sr_processed_frames=1024,
        view_a_id=1234,view_b_id=5678,view_a_frames=512,view_b_frames=512,
        active_passes=2
    },
    gpu_memory={["local"]={valid=true,headroom_bytes=1073741824}},
    afw_experiment={},apis={{},{}},frame={},fg={},gaze={},support={}
}
json = {load_string=function(s) return __snap end}
''')
lua.execute(source.read_text(encoding="utf-8-sig"))
cb = lua.globals().__cb
if cb.event is None or cb.panel is None:
    raise RuntimeError("Generated Lua did not register UEVR panel + snapshot callback")
cb.event("cheeky.foveated_dlss.load_state.v1", "enabled")
cb.event("cheeky.foveated_dlss.snapshot.v1", "{}")
cb.panel()
seen = lua.globals().__seen
expected = [
    "Pass 1 source views",
    "Pass 2 source views",
    "Crop pass 2 inside selected views",
    "Pass 2 crop width",
    "Pass 2 crop height",
    "Model passes",
    "Max VRAM admission reserve (MiB)",
    "Use UEVR source roles (C2; automatic fallback)",
    "Admission guard before NGX allocation",
    "Reuse retired NGX model for 10 s (2 slots)",
]
absent = [name for name in expected if seen[name] is None]
if absent:
    raise RuntimeError(f"Generated UI missing {absent}; observed controls={list(seen.keys())}")
# Exhaust the Batch2 menu paths instead of only checking Lua syntax or
# a single ready snapshot. Simulate both renderer layouts, 1/2 passes,
# independently configured crop flags and optional C2 fields.
lua.execute(r'''
for mode=0,3 do
  for passes=1,2 do
    for full=0,1 do
      for same=0,1 do
        __snap.settings.NrTargetMode=mode
        __snap.settings.NrPasses=passes
        __snap.settings.NrFoveated=full==1
        __snap.settings.NrUseSrFoveation=same==1
        __snap.settings.NrPass2Foveated=full==1
        __snap.settings.NrPass2SameAsPass1=same==1
        __cb.event("cheeky.foveated_dlss.snapshot.v1", "{}")
        __cb.panel()
      end
    end
  end
end
assert(__seen["Duo mono fovea rule"])
assert(__seen["Crop NR inside each source fovea (OFF = full fovea)"])
assert(__seen["Pass 2 crop width"])
assert(__seen["Model passes"])
-- A real change must produce a native command, not merely draw a widget.
__snap.settings.NrTargetMode=2
__cb.event("cheeky.foveated_dlss.snapshot.v1", "{}")
__toggle["Use UEVR source roles (C2; automatic fallback)"]=false
__cb.panel()
local delivered=false
for _,message in ipairs(__sent) do
  if message[1]=="cheeky.foveated_dlss.command.v1"
     and type(message[2])=="string"
     and message[2]:find("NrUseSourceRoles=false", 1, true) then delivered=true end
end
assert(delivered, "Batch2 toggle did not reach native command bridge")
-- A mixed install can reconnect to an older runtime without C2 settings.
-- Unsupported controls must disappear rather than remain draft-pending.
__snap.settings.NrVramGuardMiB=nil
__snap.settings.NrUseSourceRoles=nil
__snap.settings.NrAllocAdmission=nil
__snap.settings.NrFeatureReuse=nil
__cb.event("cheeky.foveated_dlss.snapshot.v1", "{}")
__seen={}
__cb.panel()
assert(not __seen["Max VRAM admission reserve (MiB)"])
assert(not __seen["Use UEVR source roles (C2; automatic fallback)"])
assert(not __seen["Admission guard before NGX allocation"])
assert(not __seen["Reuse retired NGX model for 10 s (2 slots)"])
''')
print("PASS Lua 5.4 UI smoke: loaded enabled runtime, decoded snapshot, rendered real NR UI,"
      " validated both source masks, pass-2 crop and 2-pass controls")

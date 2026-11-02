#!/usr/bin/env python3
"""Fail CI when a depth patch is present but live NGX provenance wiring is absent."""
from pathlib import Path
import sys

root=Path(sys.argv[1])
read=lambda path: (root/path).read_text(encoding="utf-8-sig")
observer=read("src/mods/vr/d3d12/DuoViewNgxManualObserver.hpp")
rhi=read("src/mods/vr/FFakeStereoRenderingHook.cpp")
vrh=read("src/mods/vr/FFakeStereoRenderingHook.hpp")
dx=read("src/mods/vr/D3D12Component.cpp")
vr=read("src/mods/VR.cpp")
ticket=read("src/mods/vr/DuoViewNgxRhiTicket.hpp")
sharpen=read("src/mods/vr/DuoViewConfig.hpp")
native=read("src/mods/vr/DuoViewD3D12.hpp")

checks={
  "Output identity fallback is strict and single-use": (
      "depth_snapshots().capture(cmd,depth,sample,{},output);" in observer and
      "slot->output_identity=output_proof?" in read("src/mods/vr/DuoViewNgxDepthCapture.hpp") and
      "find_by_output" in read("src/mods/vr/DuoViewD3D12.hpp") and
      "last_unkeyed_used_sequence_" in read("src/mods/vr/DuoViewNgxDepthCapture.hpp")),
  "NGX selected-source diagnostics distinguish missing owner from capture": (
     all(s in observer for s in ["++selected_count_", "++inactive_renderer_", "++stale_packet_", "++capture_attempts_",
                                  "last_output_w_.store", "last_command_type_.store"]) and
     all(s in dx for s in ["ngx_depth_browser.selected_calls()", "ngx_depth_browser.capture_attempts()",
                           "ngx_depth_browser.last_command_type()",
                           "ngx_depth_browser.last_selected_thread()"])),
  "Observer consumes immutable RHI ticket": "const auto key=current_rhi_producer_key;" in observer
     and "const auto key=vr->duoview_producer_key();" not in observer,
  "RHI execution scope carries the producer packet": "ScopedRhiProducerKey rhi_depth_scope{rhi_depth_key};" in rhi
     and "duo_source.packet->duoview_frame->config.key" in rhi,
  "RHI ticket header included by hooked command": '#include "DuoViewNgxRhiTicket.hpp"' in vrh,
  "Ticket is thread-local": "inline thread_local FrameKey current_rhi_producer_key" in ticket,
  "Game queue bound for native NGX observer": "ngx_depth_browser.install_queue(g_framework->get_d3d12_hook()->get_command_queue());" in dx,
  "Game queue forwarded to compositor not defaulted null": (
     "packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0,\n"
     "                                        g_framework->get_d3d12_hook()->get_command_queue());") in dx,
  "Native compositor uses same queue in depth lookup": "device,source_queue,frame.config.key,pick.source[0]," in native,
  "NGX diagnostic counters appear in the runtime log": '[DuoView][NGX] unavailable:' in dx
     and "ngx_depth_browser.missing_rhi_ticket()" in dx,
  "Distance meter tuple is fixed before validation": "std::clamp(m_duo_far_distance->value()," in vr
     and "std::clamp(m_duo_near_distance->value(),0.f,999.9f)" in vr,
  "Distance feature remains opt-in": "bool distance_sharpen_enabled{false};" in sharpen,
}
failed=[k for k,ok in checks.items() if not ok]
for label,ok in checks.items():print(("PASS" if ok else "FAIL")+" v213: "+label)
if failed:raise SystemExit("Missing required live NGX integration: "+", ".join(failed))

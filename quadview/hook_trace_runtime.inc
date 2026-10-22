namespace uevr::quadview {
int hook_trace_mode() {
    const auto& vr=VR::get();
    if(!vr) return -1;
    return vr->is_quadview_mode_selected()?7:vr->is_duoview_renderer_active()?6:
        vr->is_using_mono()?5:vr->is_using_native_stereo()?0:-1;
}
void emit_hook_trace(size_t site,const HookTraceRecord& r) {
    static HookTraceGate gate;
    const auto now=std::chrono::steady_clock::now();
    const auto ms=std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
    const auto decision=gate.visit(site,r.generation,r.serial,static_cast<uint64_t>(ms));
    if(!decision.emit) return;
    SPDLOG_INFO("[QuadViews][HookTrace] event={} generation={} serial={} frame={} role={} mode={} reason={} site={} count={} thread={} root={:x} tail={:x} list={:x} family={:x} target={:x} scene={:x} recorded={} ours_known={} ours={} live_vtable={:x} original_vtable={:x} recorded_frame={} owner_generation={} owner_serial={} engine={} native={} source={} duo={} vtables={} engines={} natives={} drains={} drain={} index={} expected_index={} result={} elapsed_us={} pending={} canonical={} rendered={} hooked={} executed={} written={} detail=\"{}\"",
        r.event,r.generation,r.serial,r.frame,r.role,r.mode,r.reason,site,decision.count,GetCurrentThreadId(),
        r.root,r.tail,r.list,r.family,r.target,r.scene,r.recorded,r.ours_known,r.ours,r.vtable,r.original_vtable,
        r.recorded_frame,r.owner_generation,r.owner_serial,r.engine,r.native,r.source,r.duo,
        r.vtables,r.engines,r.natives,r.drains,r.drain,r.index,r.expected_index,r.result,r.elapsed_us,r.pending,
        r.canonical_frame,r.rendered,r.hooked,r.executed,r.written,r.detail?r.detail:"none");
}
}

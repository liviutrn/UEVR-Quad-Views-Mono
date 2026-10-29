"""Build67 bounded NGX producer bridge. Apply AFTER verified CI51 overlay.

The observer uses the game's NGX resource arguments as Cheeky does, while
the DuoView-owned RHI source boundary supplies a recent source-pair ticket.
All replacements have exact anchors and fail closed on source divergence.
No Cheeky GPL implementation code is copied.
"""
from pathlib import Path
import sys

def replace_once(path, old, new):
    value=path.read_text(encoding="utf-8")
    if new in value:
        print("Build67 already applied:",path.name)
        return
    if value.count(old)!=1:
        raise RuntimeError("Build67: unexpected source contract for "+str(path))
    path.write_text(value.replace(old,new,1),encoding="utf-8")
    print("Build67 patched",path.name)

def apply(backend):
    root=backend/"src/mods/vr"
    guide=root/"DuoViewNgxGuide.hpp"
    replace_once(guide,"#include <cmath>\n#include <cstdint>",
                       "#include <cmath>\n#include <chrono>\n#include <mutex>\n#include <cstdint>")
    anchor="inline bool same_pair(const Guide& a,const Guide& b,uint64_t packet,uint64_t generation) {"
    bridge="""// Build67: bounded, cross-thread handoff from a complete RHI source-pair.
// This is a short interval association, NOT proof of individual UE cameras.
struct ProducerBridgeCounters {
    uint64_t published{}, empty{}, resolved{}, stale{}, absent{}, shape_rejected{};
};
class ProducerBridge final {
    using Clock=std::chrono::steady_clock;
    mutable std::mutex mutex_;
    ProducerTicket current_{};
    Clock::time_point timestamp_{};
    ProducerBridgeCounters counters_{};
public:
    void publish(const ProducerTicket& ticket) {
        std::lock_guard guard(mutex_);
        // Reject mixed/incomplete owners and equal-size ambiguous roles.
        current_=ticket && ticket.roles==3u &&
            (ticket.outputs[0]!=ticket.outputs[2] || ticket.outputs[1]!=ticket.outputs[3])
            ? ticket : ProducerTicket{};
        timestamp_=Clock::now();
        if(current_)++counters_.published;
        else ++counters_.empty;
    }
    ProducerTicket resolve(uint32_t output_width,uint32_t output_height,
                           std::chrono::milliseconds max_age=std::chrono::milliseconds{80}) {
        std::lock_guard guard(mutex_);
        if(!current_){++counters_.absent;return {};}
        if(Clock::now()-timestamp_>max_age){++counters_.stale;return {};}
        if(!role_for(current_,output_width,output_height)){
            ++counters_.shape_rejected;return {};
        }
        ++counters_.resolved;return current_;
    }
    ProducerBridgeCounters counters()const {
        std::lock_guard guard(mutex_);return counters_;
    }
    void reset(){publish({});}
};
inline ProducerBridge& producer_bridge() {
    static ProducerBridge bridge;
    return bridge;
}
"""
    replace_once(guide,anchor,bridge+anchor)
    hook=root/"FFakeStereoRenderingHook.cpp"
    replace_once(hook,
        "                uevr::duoview::ngx::current_rhi_ticket=ngx_ticket;\n                if (!duo_source",
        """                // CPU TLS alone cannot carry attribution to an independent
                // NGX evaluation thread. Empty handoffs erase old ownership.
                uevr::duoview::ngx::current_rhi_ticket=ngx_ticket;
                uevr::duoview::ngx::producer_bridge().publish(ngx_ticket);
                if (!duo_source""")
    observer=root/"d3d12/DuoViewNgxObserver.hpp"
    replace_once(observer,
        """        g.producer=uevr::duoview::ngx::current_rhi_ticket;
        if(!g.producer){++missing_ticket;return;}
        g.output_width=read_uint(p,"OutWidth");g.output_height=read_uint(p,"OutHeight");
        g.role=uevr::duoview::ngx::role_for(g.producer,g.output_width,g.output_height);""",
        """        // Resolve by the actual native NGX output extent. Never fabricate
        // an SR eye from FG or from a stale CPU thread-local token.
        g.output_width=read_uint(p,"OutWidth");g.output_height=read_uint(p,"OutHeight");
        g.producer=uevr::duoview::ngx::producer_bridge().resolve(g.output_width,g.output_height);
        if(!g.producer){++missing_ticket;return;}
        g.role=uevr::duoview::ngx::role_for(g.producer,g.output_width,g.output_height);""")
    component=root/"D3D12Component.cpp"
    replace_once(component,
        """SPDLOG_INFO_EVERY_N_SEC(5,"[DuoView][NGX] evaluations={} eligibleGuides={} missingRhiTicket={}",
                ngx.observed_calls(),ngx.sr_calls(),ngx.missing_tickets());""",
        """const auto bridge=uevr::duoview::ngx::producer_bridge().counters();
            SPDLOG_INFO_EVERY_N_SEC(5,"[DuoView][NGX] evaluations={} eligibleGuides={} missingRhiTicket={} producerBridge[published/empty/resolved/stale/absent/shape]={}/{}/{}/{}/{}/{}",
                ngx.observed_calls(),ngx.sr_calls(),ngx.missing_tickets(),
                bridge.published,bridge.empty,bridge.resolved,bridge.stale,bridge.absent,bridge.shape_rejected);""")
    print("Build67 NGX source bridge complete")

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: build67_bridge.py BACKEND_ROOT")
    apply(Path(sys.argv[1]).resolve())

#include "MonoRenderingPolicy.hpp" // actual patched backend policy, not a test copy
#include "QuadViewTransition.hpp"
#include "QuadViewDelivery.hpp"
#include "QuadViewViewDemand.hpp"
#include <cassert>
#include <memory>

using namespace uevr::quadview;
using Selection = uevr::mono::Selection;

static void initialize(Selection& selection, int method) {
    selection.set_defer_all_transitions(true);
    selection.initialize(method);
    if (selection.pending()) {
        selection.consumers_retired(selection.request_token());
        assert(selection.commit_at_game_frame_boundary());
    }
    assert(selection.active()==method);
}

int main() {
    // Every serialized mode pair, including native/sequential/AFR/DIBR,
    // uses the opt-in transaction without renumbering any mode.
    for (int from=0;from<8;++from) for (int to=0;to<8;++to) {
        Selection s;
        initialize(s,from);
        const auto generation=s.generation();
        s.request(to);
        assert(s.active()==from);
        if (from==to) { assert(!s.pending()); continue; }
        const auto request=s.request_token();
        assert(s.pending() && !s.commit_at_game_frame_boundary());
        s.consumers_retired(request-1);
        assert(!s.commit_at_game_frame_boundary());
        s.consumers_retired(request);
        assert(s.commit_at_game_frame_boundary());
        assert(s.active()==to && !s.pending() && s.generation()==generation+1);
        assert(!s.commit_at_game_frame_boundary());
    }
    for (int from=0;from<8;++from) for (int first=0;first<8;++first)
        for (int last=0;last<8;++last) {
            if (first==from) continue;
            Selection s;
            initialize(s,from);
            s.request(first);
            const auto stale=s.request_token();
            s.consumers_retired(stale);
            s.request(last); // cancel or supersede after a present acknowledgement
            if (last==first) {
                assert(s.commit_at_game_frame_boundary() && s.active()==last);
            } else {
                s.consumers_retired(stale);
                assert(!s.commit_at_game_frame_boundary() && s.active()==from);
                if (last!=from) {
                    s.consumers_retired(s.request_token());
                    assert(s.commit_at_game_frame_boundary() && s.active()==last);
                } else assert(!s.pending());
            }
        }
    // The opt-in leaves ordinary original policy behavior intact elsewhere.
    {
        Selection s; s.initialize(0); s.request(1);
        assert(s.active()==1 && !s.pending());
    }
    {
        Selection s; initialize(s,7); s.request(6);
        const auto rejected=s.request_token();
        s.request(0);
        assert(!s.cancel_request(rejected)); // A stale rejection cannot cancel a newer UI request.
        assert(s.requested()==0 && s.pending() && s.active()==7);
        assert(s.cancel_request(s.request_token()));
        assert(!s.pending() && s.active()==7);
    }
    for (unsigned flags=0;flags<32;++flags) {
        const bool selected=flags&1,pending=flags&2,closed=flags&4,owner=flags&8,scope=flags&16;
        assert(allow_transition_callback(selected,pending,closed,owner,scope)==
            (selected && pending && closed && !owner && scope));
    }
    {
        TransitionCallbackTicket ticket{5,100};
        assert(ticket.current(5,100,true,true,true));
        assert(!ticket.current(6,100,true,true,true));
        assert(!ticket.current(5,101,true,true,true));
        assert(!ticket.current(5,100,false,true,true));
        assert(!ticket.current(5,100,true,false,true));
        assert(!ticket.current(5,100,true,true,false));
    }
    // A maintenance callback's existence does not retire an engine owner.
    // Only the real tail's execution can allow the mode commit.
    {
        struct Packet { uint64_t serial{}; };
        using Ledger=Delivery<Packet,4>;
        Selection s; initialize(s,7); s.request(6);
        const auto generation=s.generation(),request=s.request_token();
        DrawDemandLatch demand;
        demand.begin(generation,10,true,true,request);
        assert(demand.transition_closed(generation,10,request,true,true));
        Ledger ledger;
        Ledger::EngineTicket owner{generation,9,77,0x100,0x200,0x300};
        assert(ledger.register_engine_family(owner));
        assert(allow_transition_callback(true,true,true,false,true));
        assert(!ledger.engine_commands_retired(generation));
        assert(!s.commit_at_game_frame_boundary());
        const auto rendered=ledger.render_engine_family(generation,77,0x200,0x300);
        assert(rendered && ledger.tail_hooked_engine_family(*rendered,0x400));
        assert(!ledger.engine_commands_retired(generation));
        assert(ledger.executed_engine_family(*rendered,0x400));
        assert(ledger.engine_commands_retired(generation));
        // An unsignalled presentation fence still forbids acknowledgement.
        bool gpu_retired=false;
        if (gpu_retired) s.consumers_retired(request);
        assert(!s.commit_at_game_frame_boundary());
        gpu_retired=true;
        if (gpu_retired) s.consumers_retired(request);
        assert(s.commit_at_game_frame_boundary() && s.active()==6);
    }
}

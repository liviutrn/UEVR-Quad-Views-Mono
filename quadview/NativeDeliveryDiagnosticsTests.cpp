#include "QuadViewDelivery.hpp"
#include "QuadViewNativeDelivery.hpp"

#include <array>
#include <cassert>
#include <condition_variable>
#include <chrono>
#include <future>
#include <memory>
#include <mutex>
#include <thread>
#include <type_traits>
#include <utility>

using namespace uevr::quadview;

struct Gate {
    std::mutex mutex;
    std::condition_variable cv;
    bool entered{}, released{};
    void wait_inside_destructor() {
        std::unique_lock lock{mutex};
        entered=true;
        cv.notify_all();
        cv.wait(lock,[&] { return released; });
    }
    bool wait_until_entered() {
        std::unique_lock lock{mutex};
        return cv.wait_for(lock,std::chrono::seconds(5),[&] { return entered; });
    }
    void release() {
        std::scoped_lock lock{mutex};
        released=true;
        cv.notify_all();
    }
};

struct Packet {
    uint64_t serial{};
    std::shared_ptr<Gate> gate{};
    Packet(uint64_t value, std::shared_ptr<Gate> block = {}) : serial(value), gate(std::move(block)) {}
    ~Packet() { if (gate) gate->wait_inside_destructor(); }
};
using D=Delivery<Packet,32>;
using N=NativeDelivery<D>;

struct Owner { D::Source source{}; D::EngineTicket engine{}; };

static Owner make_owner(uint64_t generation,uint64_t serial,uint32_t frame,
                        std::shared_ptr<Gate> gate = {}) {
    D::Source source{std::make_shared<const Packet>(serial,std::move(gate)),generation,serial,frame,serial,
        0x100+serial,0x200+serial,0x300+serial,{0x401,0x402,0x403,0x404}};
    return {source,{generation,serial,frame,source.family,source.target,source.scene}};
}

static void register_owner(D& d,N& n,const Owner& owner,uint64_t target_set=44,
                           std::array<uintptr_t,4> targets={0x501,0x502,0x503,0x504}) {
    assert(d.register_engine_family(owner.engine));
    assert(d.register_bound(owner.source));
    assert(n.bind(owner.source,owner.engine,target_set,targets));
}

int main() {
    static_assert(std::is_trivially_copyable_v<D::DiagnosticsSnapshot>);
    static_assert(std::is_trivially_copyable_v<N::DiagnosticsSnapshot>);

    {
        D d; N n(d);
        const auto empty_d=d.diagnostics_snapshot(1);
        const auto empty_n=n.diagnostics_snapshot(1);
        assert(!empty_d.busy && empty_d.source_slots==0 && empty_d.pending_engine_tickets==0);
        assert(!empty_n.busy && empty_n.occupied_slots==0 && empty_n.active_tails==0);

        const auto owner=make_owner(1,1,100);
        register_owner(d,n,owner);
        const auto partial_d=d.diagnostics_snapshot(1);
        const auto partial_n=n.diagnostics_snapshot(1);
        assert(partial_d.source_slots==1 && partial_d.incomplete_source_slots==1);
        assert(partial_d.pending_engine_tickets==1 && !partial_d.engine_tracking_overflowed);
        assert(partial_n.occupied_slots==1 && partial_n.oldest_retained_found);
        assert(partial_n.oldest_retained_generation==1 && partial_n.oldest_retained_serial==1);
        assert(partial_n.oldest_retained_rendered==0 && partial_n.oldest_retained_pending_count[0]==0);

        std::array<N::TailTicket,4> tickets{};
        for (size_t view=0; view<4; ++view) {
            const auto command=n.render(1,100,0x501+view,owner.source.scene);
            assert(command);
            const auto hooked=n.hook_batch(*command,0x700+view,0xabc,0xdef,100);
            assert(hooked.status==N::AttachStatus::attached);
            tickets[view]=hooked.tail;
        }
        const auto hooked=n.diagnostics_snapshot(1);
        assert(hooked.active_tails==4 && hooked.shared_tails==0 && hooked.ambiguous_tails==0);
        for (const auto ticket:tickets) assert(n.executed_tail(ticket,77).accepted);
        const auto full_d=d.diagnostics_snapshot(1);
        const auto full_n=n.diagnostics_snapshot(1);
        assert(full_d.source_slots==1 && full_d.incomplete_source_slots==0);
        assert(full_d.pending_engine_tickets==0);
        assert(full_n.occupied_slots==0 && full_n.active_tails==0);
        assert(!full_n.oldest_retained_found);
        assert(d.select(1,77)->serial==1);
        assert(d.engine_commands_retired(1));
        assert(d.select(1,77)->serial==1); // Sampling does not change selection.
        n.reset(); d.retire_all();
        const auto reset_d=d.diagnostics_snapshot();
        const auto reset_n=n.diagnostics_snapshot();
        assert(reset_d.source_slots==0 && reset_d.pending_engine_tickets==0);
        assert(reset_n.occupied_slots==0 && reset_n.active_tails==0);
    }

    {
        // A retained source can remain after all role masks complete when the
        // engine ticket disappeared before the late tail callbacks finished.
        D d; N n(d);
        const auto owner=make_owner(12,1,1201);
        register_owner(d,n,owner);
        std::array<N::TailTicket,4> tickets{};
        for (size_t view=0;view<4;++view) {
            const auto command=n.render(12,1201,0x501+view,owner.source.scene);
            assert(command);
            const auto hooked=n.hook_batch(*command,0xa00+view,0xabc,0xdef,1201);
            assert(hooked.status==N::AttachStatus::attached);
            tickets[view]=hooked.tail;
        }
        d.retire_generation(12);
        for (const auto ticket:tickets) assert(n.executed_tail(ticket,77).accepted);
        const auto retained=n.diagnostics_snapshot(12);
        assert(retained.occupied_slots==1 && retained.oldest_retained_found);
        assert(retained.oldest_retained_executed==0x0f);
        assert(retained.oldest_retained_completion_latched);
    }

    {
        // Four roles sharing one ticket still count as a shared tail.
        D d; N n(d);
        const auto owner=make_owner(2,1,200);
        register_owner(d,n,owner);
        std::array<N::Command,4> commands{};
        for (size_t view=0;view<4;++view) {
            const auto command=n.render(2,200,0x501+view,owner.source.scene);
            assert(command); commands[view]=*command;
        }
        N::TailTicket shared{};
        for (const auto& command:commands) {
            const auto result=n.hook_batch(command,0x800,0xabc,0xdef,200);
            assert(result.status==N::AttachStatus::attached);
            shared=result.tail;
        }
        const auto snap=n.diagnostics_snapshot(2);
        assert(snap.active_tails==1 && snap.shared_tails==1 && snap.ambiguous_tails==0);
        assert(n.executed_tail(shared,77).accepted);
        assert(d.select(2,77)->serial==1);
    }

    {
        // A shared tail crossing two source quartets is visible as ambiguous.
        D d; N n(d);
        const auto first=make_owner(3,1,301), second=make_owner(3,2,302);
        register_owner(d,n,first,44,{0x501,0x502,0x503,0x504});
        register_owner(d,n,second,45,{0x601,0x602,0x603,0x604});
        const auto a=n.render(3,301,0x501,first.source.scene);
        const auto b=n.render(3,302,0x601,second.source.scene);
        assert(a && b);
        const auto first_tail=n.hook_batch(*a,0x900,0xabc,0xdef,301);
        const auto second_tail=n.hook_batch(*b,0x900,0xabc,0xdef,302);
        assert(first_tail.status==N::AttachStatus::attached);
        assert(second_tail.status==N::AttachStatus::quarantined);
        const auto snap=n.diagnostics_snapshot(3);
        assert(snap.occupied_slots==2 && snap.active_tails==1);
        assert(snap.shared_tails==1 && snap.ambiguous_tails==1);
        assert(!d.select(3,77)); // A diagnostic read does not publish quarantined work.
    }

    {
        // Overflow remains latched and visible after an on-demand sample.
        Delivery<Packet,2> d;
        for (uint64_t serial=1;serial<=3;++serial) {
            Delivery<Packet,2>::EngineTicket ticket{9,serial,static_cast<uint32_t>(100+serial),
                0x100+serial,0x200+serial,0x300+serial};
            const bool accepted=d.register_engine_family(ticket);
            assert(accepted==(serial<=2));
        }
        const auto snapshot=d.diagnostics_snapshot(9);
        assert(snapshot.pending_engine_tickets==2 && snapshot.engine_tracking_overflowed);
        assert(d.engine_tracking_overflowed(9));
    }

    {
        // Delivery's try-lock drops a busy snapshot without blocking or copying owners.
        D d;
        auto gate=std::make_shared<Gate>();
        auto owner=make_owner(10,1,1001,gate);
        assert(d.register_engine_family(owner.engine));
        assert(d.register_bound(owner.source));
        owner.source.packet.reset();
        std::thread resetter{[&] { d.retire_all(); }};
        const bool entered=gate->wait_until_entered();
        auto sample=entered ? std::async(std::launch::async,[&] { return d.diagnostics_snapshot(10); })
                            : std::future<D::DiagnosticsSnapshot>{};
        const bool ready=entered && sample.wait_for(std::chrono::seconds(2))==std::future_status::ready;
        gate->release();
        resetter.join();
        D::DiagnosticsSnapshot busy{};
        if (sample.valid()) busy=sample.get();
        assert(entered && ready);
        assert(busy.busy && busy.source_slots==0 && busy.pending_engine_tickets==0);
        assert(d.diagnostics_snapshot(10).source_slots==0);
    }

    {
        // NativeDelivery's try-lock drops a busy snapshot during reset.
        D d; N n(d);
        auto gate=std::make_shared<Gate>();
        auto owner=make_owner(11,1,1101,gate);
        register_owner(d,n,owner);
        owner.source.packet.reset();
        d.retire_all(); // Leave the packet owned only by NativeDelivery.
        std::thread resetter{[&] { n.reset(); }};
        const bool entered=gate->wait_until_entered();
        auto sample=entered ? std::async(std::launch::async,[&] { return n.diagnostics_snapshot(11); })
                            : std::future<N::DiagnosticsSnapshot>{};
        const bool ready=entered && sample.wait_for(std::chrono::seconds(2))==std::future_status::ready;
        gate->release();
        resetter.join();
        N::DiagnosticsSnapshot busy{};
        if (sample.valid()) busy=sample.get();
        assert(entered && ready);
        assert(busy.busy && busy.occupied_slots==0 && busy.active_tails==0);
        assert(n.diagnostics_snapshot(11).occupied_slots==0);
    }
}

#include "QuadViewDelivery.hpp"
#include "QuadViewNativeDelivery.hpp"
#include <algorithm>
#include <cassert>
#include <iostream>
#include <memory>
using namespace uevr::quadview;
struct Packet { uint64_t serial{}; };
using D=Delivery<Packet,32>;
using N=NativeDelivery<D>;
static D::Source bind(D& d,N& n,uint64_t serial,uint32_t frame) {
    D::Source s{std::make_shared<const Packet>(Packet{serial}),1,serial,frame,serial,
        0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
    D::EngineTicket e{1,serial,frame,s.family,s.target,s.scene};
    assert(d.register_engine_family(e)); assert(d.register_bound(s));
    assert(n.bind(s,e,44,{0x501,0x502,0x503,0x504}));
    s.engine_frame_bound=true; return s;
}
static std::array<N::Command,4> hook(D& d,N& n,uint32_t frame,uintptr_t base) {
    std::array<N::Command,4> c;
    for(size_t i=0;i<4;++i) {
        auto found=n.render(1,frame,0x501+i,0x300); assert(found); c[i]=*found;
        assert(!n.render(1,frame,0x501+i,0x300));
        assert(!n.render(1,frame,0x501+i,0x301));
        assert(n.hook(c[i],base+i)); assert(!n.hook(c[i],base+i));
    }
    assert(!d.engine_commands_retired(1)); return c;
}
static std::array<N::TailTicket,4> hook_partial_shared_tail(N& n,
    const std::array<N::Command,4>& commands,uintptr_t base,uint32_t frame) {
    std::array<N::TailTicket,4> tails{};
    const auto first=n.hook_batch(commands[0],base,0xabc,0xdef,frame);
    const auto second=n.hook_batch(commands[1],base,0xabc,0xdef,frame);
    assert(first.status==N::AttachStatus::attached);
    assert(second.status==N::AttachStatus::attached);
    tails[0]=first.tail; tails[1]=second.tail;
    for(size_t i=2;i<4;++i) {
        const auto result=n.hook_batch(commands[i],base+i,0xabc,0xdef,frame);
        assert(result.status==N::AttachStatus::attached); tails[i]=result.tail;
    }
    return tails;
}
int main() {
    {
        D d; N n(d);
        D::Source source{std::make_shared<const Packet>(Packet{1}),1,1,100,1,
            0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
        D::EngineTicket engine{1,1,100,0x100,0x200,0x300};
        assert(!n.bind(source,engine,44,{0x501,0x501,0x503,0x504}));
        assert(!n.bind(source,engine,44,{0x501,0,0x503,0x504}));
        assert(!n.bind(source,engine,0,{0x501,0x502,0x503,0x504}));
        engine.generation=2;
        assert(!n.bind(source,engine,44,{0x501,0x502,0x503,0x504}));
    }
    {
        D d;N n(d);
        for(uint64_t serial=1;serial<=32;++serial) {
            D::Source queued{std::make_shared<const Packet>(Packet{serial}),1,serial,uint32_t(serial),serial,
                0x100+serial,0x200,0x300,{0x401,0x402,0x403,0x404}};
            assert(d.register_bound(queued));
            const auto pending=d.render(1,uint32_t(serial),queued.family,queued.target,queued.scene);
            assert(pending && d.tail_hooked(*pending,0x2000+serial));
        }
        D::Source unpublishable{std::make_shared<const Packet>(Packet{99}),1,99,900,99,
            0x999,0x200,0x300,{0x401,0x402,0x403,0x404}};
        D::EngineTicket engine{1,99,900,0x999,0x200,0x300};
        assert(d.register_engine_family(engine));
        assert(n.bind(unpublishable,engine,44,{0x501,0x502,0x503,0x504}));
        assert(!d.register_bound(unpublishable));
        auto c=hook(d,n,900,0x900);
        for(size_t i=0;i<4;++i) assert(n.executed(c[i],0x900+i,77));
        assert(d.pending_engine_commands(1)==0); // New quartet did not strand its engine ticket.
        assert(!d.engine_commands_retired(1)); // Original full ledger still owns its pending tails.
        assert(!d.select(1,77));
    }
    {
        D d;N n(d);
        // Invalid/missing pose: retain engine targets but authorize no XR source.
        D::Source discard{std::make_shared<const Packet>(Packet{1}),1,1,100,0,
            0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
        D::EngineTicket engine{1,1,100,0x100,0x200,0x300};
        assert(d.register_engine_family(engine));
        assert(n.bind(discard,engine,44,{0x501,0x502,0x503,0x504}));
        auto c=hook(d,n,100,0x700);
        for(size_t i=0;i<4;++i) assert(n.executed(c[i],0x700+i,77));
        assert(d.engine_commands_retired(1)); assert(!d.select(1,77));
    }
    std::array<unsigned,4> order{0,1,2,3};
    do {
        D d; N n(d); bind(d,n,1,100); auto c=hook(d,n,100,0x700);
        for(size_t j=0;j<4;++j) {
            auto i=order[j]; assert(n.executed(c[i],0x700+i,77));
            assert(!n.executed(c[i],0x700+i,77));
            assert(bool(d.select(1,77))==(j==3));
        }
        assert(d.engine_commands_retired(1)); assert(!d.select(1,78));
    } while(std::next_permutation(order.begin(),order.end()));
    {
        D d;N n(d);bind(d,n,1,100);auto old=hook(d,n,100,0x700);
        for(size_t i=0;i<4;++i) assert(n.executed(old[i],0x700+i,77));
        assert(d.select(1,77));
        bind(d,n,2,101);auto next=hook(d,n,101,0x800);
        // Merely queueing a new quartet cannot erase an executed old image.
        assert(d.select(1,77));
        assert(n.executed(next[0],0x800,77));
        assert(!d.select(1,77)); // First actual writer invalidates old pixels.
        for(size_t i=1;i<4;++i) assert(n.executed(next[i],0x800+i,77));
        assert(d.select(1,77)->serial==2);
    }
    {
        D d;N n(d);bind(d,n,1,100);auto old=hook(d,n,100,0x700);
        bind(d,n,2,101);auto next=hook(d,n,101,0x800);
        assert(n.executed(old[0],0x700,77));
        for(size_t i=0;i<4;++i) assert(n.executed(next[i],0x800+i,77));
        for(size_t i=1;i<4;++i) assert(n.executed(old[i],0x700+i,77));
        assert(!d.select(1,77)); // A late old physical write invalidates newer content.
        assert(d.engine_commands_retired(1));
        bind(d,n,3,102);auto fresh=hook(d,n,102,0x900);
        for(size_t i=0;i<4;++i) assert(n.executed(fresh[i],0x900+i,77));
        assert(d.select(1,77)->serial==3);
    }
    {
        // Both quartets are queued before the older deferred tails execute.
        // They must not poison the never-written future quartet.
        D d;N n(d);bind(d,n,1,100);auto old=hook(d,n,100,0x700);
        bind(d,n,2,101);auto next=hook(d,n,101,0x800);
        for(size_t i=0;i<4;++i) assert(n.executed(old[i],0x700+i,77));
        for(size_t i=0;i<4;++i) assert(n.executed(next[i],0x800+i,77));
        assert(d.select(1,77)->serial==2);
        assert(d.engine_commands_retired(1));
    }
    {
        D d;N n(d);bind(d,n,1,100);
        std::array<N::Command,4> commands{};
        for(size_t i=0;i<4;++i) {
            auto found=n.render(1,100,0x501+i,0x300); assert(found); commands[i]=*found;
        }
        const auto tails=hook_partial_shared_tail(n,commands,0xb00,100);
        assert(tails[0].command==tails[1].command && tails[0].id==tails[1].id);
        assert(n.executed_tail(tails[0],77).accepted); // Shared roles 0 and 1.
        assert(!d.select(1,77));
        assert(n.executed_tail(tails[2],77).accepted);
        assert(!d.select(1,77));
        assert(n.executed_tail(tails[3],77).accepted);
        assert(d.select(1,77)->serial==1);
        assert(d.engine_commands_retired(1));
    }
    {
        // Startup/partial worker drains do not advance runtime cadence until
        // the canonical role-3 tail is present. Shared and distinct tails
        // retain the same runtime event API used by the generated RHI hook.
        D d;N n(d);bind(d,n,1,100);
        std::array<N::Command,4> commands{};
        for(size_t view=0;view<4;++view) {
            auto found=n.render(1,100,0x501+view,0x300); assert(found); commands[view]=*found;
        }
        const auto first_scope=NativeDrainScope::current();
        assert(!first_scope.id && !first_scope.immediate_list);
        N::TailTicket shared{}, role2{}, role3{};
        {
            NativeDrainScope drain{0xdef};
            const auto identity=NativeDrainScope::current();
            assert(identity.id && identity.immediate_list==0xdef);
            const auto a=n.hook_batch(commands[0],0xf00,identity.id,identity.immediate_list,100);
            const auto b=n.hook_batch(commands[1],0xf00,identity.id,identity.immediate_list,100);
            assert(a.status==N::AttachStatus::attached && b.status==N::AttachStatus::attached);
            shared=a.tail;
            const auto c=n.hook_batch(commands[2],0xf01,identity.id,identity.immediate_list,100);
            const auto d3=n.hook_batch(commands[3],0xf02,identity.id,identity.immediate_list,100);
            assert(c.status==N::AttachStatus::attached && d3.status==N::AttachStatus::attached);
            role2=c.tail; role3=d3.tail;
            assert(!n.runtime_event(shared) && !n.runtime_event(role2));
            assert(!n.runtime_event(shared) && !n.runtime_event(role2));
            assert(n.runtime_event(role3));
        }
        assert(!NativeDrainScope::current().id && !NativeDrainScope::current().immediate_list);
        N::RuntimeEvent event{};
        assert(n.claim_runtime_event(role3,event));
        assert(event.generation==1 && event.serial==1 && event.frame==100);
        assert(!n.claim_runtime_event(role3,event)); // One runtime callback for this quartet.
        assert(n.executed_tail(shared,77).accepted);
        assert(n.executed_tail(role2,77).accepted);
        assert(n.executed_tail(role3,77).accepted);
        assert(d.select(1,77)->serial==1);

        // A late older view-3 tail cannot regress runtime frame state; a new
        // generation starts a fresh runtime cadence.
        D::Source newer{std::make_shared<const Packet>(Packet{2}),1,2,101,2,
            0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
        D::EngineTicket newer_engine{1,2,101,newer.family,newer.target,newer.scene};
        assert(d.register_engine_family(newer_engine)); assert(d.register_bound(newer));
        assert(n.bind(newer,newer_engine,44,{0x501,0x502,0x503,0x504}));
        const auto old_view3=n.render(1,101,0x504,0x300); assert(old_view3);
        const auto old_tail=n.hook_batch(*old_view3,0xf03,0xabc,0xdef,101); assert(old_tail);
        assert(n.claim_runtime_event(old_tail.tail,event));
        assert(event.serial==2 && event.frame==101);
        assert(n.executed_tail(old_tail.tail,77).accepted);
    }
    {
        // One tail shared by two quartets has no observable GPU ordering.
        // It must drain both owners without publishing either source.
        D d;N n(d);bind(d,n,1,100);bind(d,n,2,101);
        auto old=n.render(1,100,0x501,0x300);
        auto next=n.render(1,101,0x501,0x300);
        assert(old&&next);
        const auto first=n.hook_batch(*old,0xc00,0xabc,0xdef,100);
        const auto second=n.hook_batch(*next,0xc00,0xabc,0xdef,101);
        assert(first.status==N::AttachStatus::attached);
        assert(second.status==N::AttachStatus::quarantined);
        std::array<N::TailTicket,6> remaining{};
        size_t count{};
        for(uint64_t serial=1;serial<=2;++serial) {
            const auto frame=static_cast<uint32_t>(99+serial);
            for(size_t view=1;view<4;++view) {
                auto command=n.render(1,frame,0x501+view,0x300); assert(command);
                const auto result=n.hook_batch(*command,0xc10+count,0xabc,0xdef,frame);
                assert(result.status==N::AttachStatus::attached);
                remaining[count++]=result.tail;
            }
        }
        assert(count==remaining.size());
        assert(n.executed_tail(first.tail,77).accepted);
        for(const auto& tail:remaining) assert(n.executed_tail(tail,77).accepted);
        assert(!d.select(1,77));
        assert(d.engine_commands_retired(1));
    }
    {
        // An independently attached tail for a role that already executed
        // must reopen that role's completion bit until the new tail drains.
        D d;N n(d);bind(d,n,1,100);
        std::array<N::Command,4> commands{};
        std::array<N::TailTicket,4> tails{};
        for(size_t i=0;i<4;++i) {
            auto found=n.render(1,100,0x501+i,0x300); assert(found); commands[i]=*found;
            const auto result=n.hook_batch(commands[i],0xd00+i,0xabc,0xdef,100);
            assert(result.status==N::AttachStatus::attached); tails[i]=result.tail;
        }
        assert(n.executed_tail(tails[0],77).accepted);
        const auto late=n.hook_batch(commands[0],0xd10,0xabc,0xdef,100);
        assert(late.status==N::AttachStatus::attached);
        for(size_t i=1;i<4;++i) assert(n.executed_tail(tails[i],77).accepted);
        assert(!d.select(1,77));
        assert(n.executed_tail(late.tail,77).accepted);
        assert(!d.select(1,77));
        assert(d.engine_commands_retired(1));
    }
    {
        // The source ledger may reclaim a rendered packet before the last
        // native hook arrives. The engine completion falls back to drain-only.
        D d;N n(d);bind(d,n,1,100);
        std::array<N::Command,4> commands{};
        for(size_t i=0;i<4;++i) {
            auto found=n.render(1,100,0x501+i,0x300); assert(found); commands[i]=*found;
        }
        for(size_t i=0;i<3;++i) assert(n.hook(commands[i],0xe00+i));
        for(uint64_t serial=10;serial<50;++serial) {
            D::Source extra{std::make_shared<const Packet>(Packet{serial}),1,serial,
                uint32_t(100+serial),serial,0x100+serial,0x200,0x300,
                {0x401,0x402,0x403,0x404}};
            (void)d.register_bound(extra);
        }
        for(uint64_t serial=10;serial<50;++serial) (void)d.retire(1,serial);
        const auto last=n.hook_batch(commands[3],0xe03,0,0,100);
        assert(last.status==N::AttachStatus::attached);
        for(size_t i=0;i<3;++i) assert(n.executed(commands[i],0xe00+i,77));
        assert(n.executed_tail(last.tail,77).accepted);
        assert(!d.select(1,77));
        assert(d.pending_engine_commands(1)==0);
        assert(d.engine_commands_retired(1));
    }
    {
        D d;N n(d);bind(d,n,1,100);auto c=hook(d,n,100,0x700);
        assert(!n.executed(c[0],0x701,77)); // An owner cannot retire another role's tail.
        assert(!n.executed(c[1],0x700,77));
        for(size_t i=0;i<4;++i) assert(n.executed(c[i],0x700+i,77));
        assert(d.select(1,77)->serial==1);
        assert(d.engine_commands_retired(1));
    }
    {
        D d;N n(d);
        for(uint64_t serial=1;serial<=40;++serial) {
            const auto frame=static_cast<uint32_t>(100+serial);
            const auto set=1000+serial;
            const std::array<uintptr_t,4> targets{
                0x10000+serial*16,0x10001+serial*16,0x10002+serial*16,0x10003+serial*16};
            D::Source source{std::make_shared<const Packet>(Packet{serial}),1,serial,frame,serial,
                0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
            D::EngineTicket engine{1,serial,frame,source.family,source.target,source.scene};
            assert(d.register_engine_family(engine)); assert(d.register_bound(source));
            assert(n.bind(source,engine,set,targets));
            std::array<N::Command,4> commands{};
            for(size_t view=0;view<4;++view) {
                auto command=n.render(1,frame,targets[view],source.scene); assert(command);
                commands[view]=*command;
                assert(n.hook(commands[view],0x20000+serial*8+view));
            }
            for(size_t view=0;view<4;++view)
                assert(n.executed(commands[view],0x20000+serial*8+view,77));
            assert(d.select(1,77)->serial==serial);
            (void)d.retire(1,serial);
        }
        // Provenance has seen 160 physical targets without a generation reset.
        // Stale records are reclaimed and the newest set remains publishable.
        assert(d.pending_engine_commands(1)==0);
        assert(d.engine_commands_retired(1));
    }
    {
        D d;N n(d);bind(d,n,1,100);auto c=hook(d,n,100,0x700);
        assert(!n.executed(c[0],0x999,77));
        assert(!n.executed(c[0],0x700,0));
        assert(n.executed(c[0],0x700,77));
        assert(!n.executed(c[1],0x701,78));
        assert(!d.select(1,77)); assert(!d.engine_commands_retired(1));
        n.reset();d.retire_all();
        assert(!n.executed(c[1],0x701,77)); assert(d.engine_commands_retired(1));
    }
    {
        // The production RHI map record owns the source packet after the
        // delivery ledger is reset, and a copied execution lease keeps it
        // alive after the map entry is erased until the callback returns.
        D d;N n(d);
        auto packet=std::make_shared<const Packet>(Packet{9});
        std::weak_ptr<const Packet> weak=packet;
        D::Source source{packet,1,9,109,9,0x100,0x200,0x300,
            {0x401,0x402,0x403,0x404}};
        D::EngineTicket engine{1,9,109,source.family,source.target,source.scene};
        assert(d.register_engine_family(engine)); assert(d.register_bound(source));
        assert(n.bind(source,engine,44,{0x501,0x502,0x503,0x504}));
        auto command=n.render(1,109,0x501,0x300); assert(command);
        const auto attached=n.hook_batch(*command,0xf10,0xabc,0xdef,109); assert(attached);
        N::TailOwnerBatch map_record{};
        assert(map_record.retain(*command,attached.tail));
        auto execution_lease=map_record; // copied before map erase
        map_record={};
        command.reset();
        packet.reset(); source.packet.reset();
        n.reset(); d.retire(1,9);
        assert(!n.executed_tail(execution_lease.ticket,77).accepted);
        assert(!weak.expired());
        execution_lease={};
        assert(weak.expired());
    }
    std::cout<<"Native quartet: shared tails, physical provenance, deferred owner leases, cadence, late callbacks, and bounded target replacement passed.\n";
}

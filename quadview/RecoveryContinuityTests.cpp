#include "QuadViewDelivery.hpp"
#include "QuadViewNativeDelivery.hpp"
#include "QuadViewFamilyRouting.hpp"
#include <cassert>
#include <iostream>
#include <memory>
#include <string_view>
using namespace uevr::quadview;
struct RecoveryPacket { uint64_t serial{}; };
using D=Delivery<RecoveryPacket,32>;
using N=NativeDelivery<D>;

int main(int argc,char** argv) {
    const bool legacy=argc>1 && std::string_view(argv[1])=="--legacy";
    FamilyIdentity main{};
    main.family=0x100; main.scene=0x300; main.target=0x200;
    main.views={0x401,0x402,0x403,0x404}; main.view_count=4; main.readable=true;
    PartialFamilyIdentity partial{main.family,main.scene,main.target,{0x401,0x402},2};
    const std::array<FamilyIdentity,1> candidates{main};
    assert(classify_partial_main_family(candidates,partial)==PartialFamilyRouteStatus::possible_main);
    // This is the Build47 rejection branch: incomplete snapshot suppresses the
    // engine callback required to acquire the next runtime pose. --legacy must
    // fail so CI checks that the harness actually detects this starvation.
    const bool admitted=legacy
        ? classify_partial_main_family(candidates,partial)==PartialFamilyRouteStatus::auxiliary_only
        : bool(route_drain_family(candidates,partial));
    if(!admitted) { std::cerr<<"Reproduced incomplete-snapshot startup starvation\n"; return 2; }
    auto bad=main; bad.views[1]=bad.views[0];
    assert(!route_drain_family(std::array{bad},partial));
    bad=main; bad.target++;
    assert(route_drain_family(std::array{bad},partial).status==FamilyRouteStatus::auxiliary_only);
    bad=main; bad.scene++;
    assert(!route_drain_family(std::array{bad},partial));
    bad=main; bad.family++;
    assert(!route_drain_family(std::array{bad},partial));
    bad=main; bad.readable=false;
    assert(!route_drain_family(std::array{main,bad},partial));
    assert(!route_drain_family(std::array{main,main},partial));
    assert(!route_drain_family(candidates,PartialFamilyIdentity{}));
    auto two=main; two.view_count=2;
    assert(route_drain_family(std::array{two},partial));
    auto aux=main; aux.family=0x800; aux.target=0x900; aux.view_count=0; aux.views={};
    assert(route_drain_family(std::array{aux,main},partial).index==1);

    {
        // The production adapter may see ordinary startup owners and native
        // roles join the same deferred tail in either order. Drainage of the
        // engine-only family must not strand or authorize the native packet.
        for(bool native_first:{false,true}) {
            D mixed; N native{mixed}; EngineDrainBatch<D> drain{};
            D::EngineTicket startup{1,1,10,0x100,0x200,0x300};
            assert(mixed.register_engine_family(startup));
            auto ordinary=mixed.render_engine_family(1,10,0x200,0x300); assert(ordinary);
            D::Source source{std::make_shared<const RecoveryPacket>(RecoveryPacket{2}),
                1,2,11,20,0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
            D::EngineTicket engine{1,2,11,0x100,0x200,0x300};
            assert(mixed.register_engine_family(engine)); assert(mixed.register_bound(source));
            assert(native.bind(source,engine,1,{0x501,0x502,0x503,0x504}));
            if(!native_first) assert(drain.attach(mixed,*ordinary,0x700));
            N::TailTicket tail{};
            for(size_t i=0;i<4;++i) {
                auto role=native.render(1,11,0x501+i,0x300); assert(role);
                auto attached=native.hook_batch(*role,0x700,1,0x900,11); assert(attached.publishable());
                tail=attached.tail;
                assert(!mixed.select(1,77));
            }
            if(native_first) assert(drain.attach(mixed,*ordinary,0x700));
            assert(drain.execute(mixed,0x700,77,1));
            assert(native.executed_tail(tail,77).accepted);
            assert(mixed.engine_commands_retired(1));
            auto result=mixed.select(1,77); assert(result && result->serial==2);
        }
    }
    {
        // A legacy atlas plus a later recovery write is deliberately not a
        // pixel proof. Retain its exact engine ticket but revoke its source.
        D mixed; EngineDrainBatch<D> drain{};
        D::Source source{std::make_shared<const RecoveryPacket>(RecoveryPacket{1}),
            1,1,10,20,0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
        D::EngineTicket first{1,1,10,0x100,0x200,0x300};
        assert(mixed.register_engine_family(first)); assert(mixed.register_bound(source));
        auto owner=mixed.render_engine_family(1,10,0x200,0x300); assert(owner);
        auto rendered=mixed.render(1,10,0x100,0x200,0x300); assert(rendered);
        assert(mixed.tail_hooked_engine_family(*owner,*rendered,0x700));
        D::EngineTicket second{1,2,11,0x100,0x200,0x300};
        assert(mixed.register_engine_family(second));
        auto next=mixed.render_engine_family(1,11,0x200,0x300); assert(next);
        assert(drain.attach(mixed,*next,0x700));
        assert(mixed.retire(1,1));
        assert(drain.execute(mixed,0x700,77,1));
        assert(mixed.executed_engine_family(*owner,D::Source{},0x700,77));
        assert(mixed.engine_commands_retired(1)); assert(!mixed.select(1,77));
    }

    {
        // A newly demoted source must survive map erasure and ledger retirement
        // until the original RHI callback has returned, including after reset.
        D mixed; EngineDrainBatch<D> pending{};
        D::Source source{std::make_shared<const RecoveryPacket>(RecoveryPacket{1}),
            1,1,10,20,0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
        std::weak_ptr<const RecoveryPacket> weak=source.packet;
        D::EngineTicket ticket{1,1,10,0x100,0x200,0x300};
        assert(mixed.register_engine_family(ticket)); assert(mixed.register_bound(source));
        auto owner=mixed.render_engine_family(1,10,0x200,0x300); assert(owner);
        auto rendered=mixed.render(1,10,0x100,0x200,0x300); assert(rendered);
        assert(pending.attach(mixed,*owner,0x700,*rendered));
        assert(mixed.retire(1,1)); source={}; rendered.reset();
        assert(!weak.expired());
        {
            const auto executing=pending; // same local lease as production
            pending={}; mixed.retire_all();
            assert(!weak.expired());
            assert(executing.execute(mixed,0x700,77,2)); // stale generation ignored
            assert(!weak.expired()); // original command has not returned
        }
        assert(weak.expired());
    }
    {
        D mixed; N native{mixed};
        D::Source legacy_source{std::make_shared<const RecoveryPacket>(RecoveryPacket{1}),
            1,1,10,20,0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
        D::EngineTicket first{1,1,10,0x100,0x200,0x300};
        assert(mixed.register_engine_family(first)); assert(mixed.register_bound(legacy_source));
        auto primary=mixed.render_engine_family(1,10,0x200,0x300); assert(primary);
        auto old=mixed.render(1,10,0x100,0x200,0x300); assert(old);
        assert(mixed.tail_hooked_engine_family(*primary,*old,0x700));
        D::Source fresh{std::make_shared<const RecoveryPacket>(RecoveryPacket{2}),
            1,2,11,21,0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
        D::EngineTicket next{1,2,11,0x100,0x200,0x300};
        assert(mixed.register_engine_family(next)); assert(mixed.register_bound(fresh));
        assert(native.bind(fresh,next,1,{0x501,0x502,0x503,0x504}));
        N::TailTicket tail{};
        for(size_t i=0;i<4;++i) {
            auto role=native.render(1,11,0x501+i,0x300); assert(role);
            auto attach=native.hook_batch(*role,0x700,1,0x900,11); assert(attach.publishable());
            tail=attach.tail;
        }
        assert(mixed.retire(1,1)); // native joining legacy revokes old atlas proof
        assert(native.executed_tail(tail,77).accepted);
        assert(mixed.executed_engine_family(*primary,D::Source{},0x700,77));
        assert(mixed.engine_commands_retired(1));
        auto result=mixed.select(1,77); assert(result && result->serial==2);
    }
    {
        using Wide=Delivery<RecoveryPacket,40>;
        Wide ledger; EngineDrainBatch<Wide> batch{};
        for(uint64_t serial=1;serial<=33;++serial) {
            Wide::EngineTicket ticket{1,serial,uint32_t(serial),0x100,0x200,0x300};
            assert(ledger.register_engine_family(ticket));
            auto owner=ledger.render_engine_family(1,uint32_t(serial),0x200,0x300); assert(owner);
            assert(batch.attach(ledger,*owner,0x700)==(serial<=32));
        }
        assert(batch.count==32 && batch.newest_serial==32);
        assert(batch.execute(ledger,0x700,77,1));
        assert(ledger.pending_engine_commands(1)==1); // overflow cannot falsely retire unknown work
        assert(!ledger.engine_commands_retired(1));
        assert(!ledger.select(1,77));
    }
    D d; N n{d};
    uint64_t published{}, runtime_events{}, drained{};
    for(uint64_t generation=1;generation<=24;++generation) {
        // Simulate startup, loading/paused poses and resumed rendering every
        // generation. Serials/frame counters/command pointers are reused.
        EngineDrainBatch<D> drains{};
        for(uint64_t serial=1;serial<=8;++serial) {
            D::EngineTicket ticket{generation,serial,uint32_t(serial),0x100,0x200,0x300};
            assert(d.register_engine_family(ticket));
            auto render=d.render_engine_family(generation,uint32_t(serial),0x200,0x300);
            assert(render);
            assert(drains.attach(d,*render,0x700));
            assert(drains.attach(d,*render,0x700)); // idempotent
            assert(drains.count==serial);
            assert(!drains.attach(d,*render,0x701));
            assert(!d.select(generation,77)); // no pose, no source, no output
        }
        assert(!d.engine_commands_retired(generation));
        assert(!drains.execute(d,0x701,77,generation)); // wrong tail cannot retire
        assert(!d.engine_commands_retired(generation));
        assert(drains.execute(d,0x700,77,generation));
        assert(d.engine_commands_retired(generation)); drained+=drains.count;
        assert(!d.select(generation,77));
        for(uint64_t serial=9;serial<=108;++serial) {
            const uint32_t frame=uint32_t(serial);
            D::Source source{std::make_shared<const RecoveryPacket>(RecoveryPacket{serial}),
                generation,serial,frame,serial,0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
            D::EngineTicket ticket{generation,serial,frame,0x100,0x200,0x300};
            assert(d.register_engine_family(ticket)); assert(d.register_bound(source));
            assert(n.bind(source,ticket,generation,{0x501,0x502,0x503,0x504}));
            std::array<N::TailTicket,4> tails{};
            for(size_t i=0;i<4;++i) {
                assert(!n.render(generation+1,frame,0x501+i,0x300));
                auto role=n.render(generation,frame,0x501+i,0x300); assert(role);
                // Multiple roles share one genuine drain; later roles use a
                // separate tail. No early mask authorizes output.
                auto tail=n.hook_batch(*role,0x800+(i/2),serial,0x900,frame);
                assert(tail.publishable()); tails[i]=tail.tail;
                assert(!d.select(generation,77));
            }
            N::RuntimeEvent event{};
            assert(n.claim_runtime_event(tails[3],event)); ++runtime_events;
            assert(event.serial==serial && event.generation==generation && event.frame==frame);
            assert(!n.claim_runtime_event(tails[3],event));
            // Reverse the two tail executions on alternating frames.
            size_t first=serial%2 ? 0:3, second=serial%2 ? 3:0;
            assert(n.executed_tail(tails[first],77).accepted);
            assert(!d.select(generation,77));
            assert(n.executed_tail(tails[second],77).accepted);
            auto output=d.select(generation,77); assert(output && output->serial==serial);
            assert(d.submitted(*output,0xa00)); ++published;
            assert(d.retire(generation,serial));
            assert(d.engine_commands_retired(generation));
        }
        d.retire_all(); n.reset();
        // Stale CPU callbacks after reset cannot retire a new generation.
        assert(drains.execute(d,0x700,77,generation+1));
        assert(!d.select(generation+1,77));
    }
    assert(published==2400 && runtime_events==published && drained==192);
    std::cout<<"2400 coherent quartets/two-eye output owners, 24 generations, "
             <<drained<<" engine-only recovery owners; legacy starvation rejected.\n";
}

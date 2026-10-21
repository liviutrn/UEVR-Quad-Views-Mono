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
        assert(d.select(1,77)->serial==2); // Late old callbacks cannot republish torn pixels.
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
    std::cout<<"Native quartet: 24 execution permutations, duplicate rejection, missing tails, reused targets and late older callbacks passed.\n";
}

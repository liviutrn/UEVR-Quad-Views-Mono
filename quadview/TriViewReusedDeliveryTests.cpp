#include "QuadViewDelivery.hpp"
#include "QuadViewNativeDelivery.hpp"
#include <algorithm>
#include <array>
#include <cassert>
#include <memory>
#include <iostream>
using namespace uevr::quadview;
struct Packet { uint64_t serial; };
using D=Delivery<Packet,16>;
using N=NativeDelivery<D>;
constexpr std::array<size_t,3> roles{0,2,3};
constexpr std::array<uintptr_t,4> older_targets{0x501,0,0x503,0x504};
constexpr std::array<uintptr_t,4> newer_targets{0x601,0,0x503,0x504};
std::array<N::Command,4> prepare(D& d,N& n,uint64_t serial,const std::array<uintptr_t,4>& targets) {
    const auto frame=uint32_t(100+serial);
    D::Source s{std::make_shared<const Packet>(Packet{serial}),1,serial,frame,serial,
        0x100,0x200,0x300,{0x401,0x402,0x403,0x404}};
    D::EngineTicket e{1,serial,frame,s.family,s.target,s.scene};
    assert(d.register_engine_family(e));assert(d.register_bound(s));
    assert(n.bind(s,e,700+serial,targets,false,0x0d));
    std::array<N::Command,4> out{};
    for(auto role:roles){auto c=n.render(1,frame,targets[role],s.scene);assert(c);out[role]=*c;assert(n.hook(*c,0x1000+serial*16+role));}
    return out;
}
int main(){
    std::array<unsigned,6> order{0,1,2,3,4,5};unsigned permutations=0;
    do{
        D d;N n(d);const auto a=prepare(d,n,1,older_targets),b=prepare(d,n,2,newer_targets);
        // Independent physical-pixel reference: two peripheries, reused foveas.
        std::array<uint64_t,4> pixels{};
        for(auto step:order){
            auto serial=step<3?uint64_t(1):uint64_t(2);auto role=roles[step%3];
            pixels[role==0?size_t(serial-1):role]=serial;
            assert(n.executed(serial==1?a[role]:b[role],0x1000+serial*16+role,77));
            if(auto selected=d.select(1,77)){
                const auto s=selected->serial;assert(s==1||s==2);
                assert(pixels[size_t(s-1)]==s&&pixels[2]==s&&pixels[3]==s);
            }
        }
        assert(d.engine_commands_retired(1));
        const auto fresh=prepare(d,n,3,newer_targets);
        for(auto role:roles)assert(n.executed(fresh[role],0x1000+3*16+role,77));
        const auto recovered=d.select(1,77);assert(recovered&&recovered->serial==3);
        ++permutations;
    }while(std::next_permutation(order.begin(),order.end()));
    assert(permutations==720);
    std::cout<<"720 mixed-publication write orders preserved reused-fovea content identity and recovered\n";
}

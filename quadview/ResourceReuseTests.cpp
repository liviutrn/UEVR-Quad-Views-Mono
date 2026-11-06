#include "QuadViewResourceReuse.hpp"
#include <cassert>
#include <iostream>
using namespace uevr::quadview;

struct Owner {
    int* releases;
    explicit Owner(int* value):releases(value) {}
    bool gamma_hooked=true;
    ~Owner() { ++*releases; }
};
struct Snapshot {
    uint64_t generation{}, resource_allocation_generation{};
    std::shared_ptr<Owner> owner_lifetime{};
};
int main() {
    const NativeResourceExtents old{{{1024,768},{0,0},{2048,1536},{2048,1536}}};
    auto wanted=old; wanted[0]={1280,960};
    auto plan=plan_native_resource_reuse(true,true,old,wanted);
    assert(plan.reuse_mask==0x0c && plan.reuses(2) && plan.reuses(3));
    assert(!plan.reuses(0) && !plan.reuses(1) && !plan.reuses(4));
    assert(plan.new_color_bytes==uint64_t(1280)*960*4);
    assert(plan_native_resource_reuse(true,true,old,old).reuse_mask==0x0d);
    wanted[2][0]+=64;
    assert(plan_native_resource_reuse(true,true,old,wanted).reuse_mask==0x08);
    const auto full_bytes=uint64_t(1280)*960*4+uint64_t(2112)*1536*4+uint64_t(2048)*1536*4;
    for (const auto gate : std::array<std::array<bool,2>,3>{{{false,true},{true,false},{false,false}}}) {
        const auto fresh=plan_native_resource_reuse(gate[0],gate[1],old,wanted);
        assert(fresh.reuse_mask==0 && fresh.new_color_bytes==full_bytes);
    }
    assert(!valid_resource_publication(19,18,17));
    assert(!valid_resource_publication(19,19,0));
    assert(!valid_resource_publication(19,19,20));
    assert(valid_resource_publication(19,19,17));
    int releases=0;
    auto physical=std::make_shared<Owner>(&releases);
    auto first=std::make_shared<Snapshot>(Snapshot{17,17,physical});
    std::shared_ptr<const Snapshot> packet=first;
    auto second=republish_resource_snapshot(packet,18);
    assert(second && second->generation==18 && second->resource_allocation_generation==17);
    assert(first->generation==17 && second->owner_lifetime==physical);
    assert(!republish_resource_snapshot(packet,17));
    assert(!republish_resource_snapshot(packet,16));
    // A canceled replacement releases only its lease; it neither changes the
    // old packet publication nor clears a gamma table used by another packet.
    auto canceled=republish_resource_snapshot(std::shared_ptr<const Snapshot>(second),19);
    canceled.reset();
    assert(physical->gamma_hooked && packet->generation==17 && releases==0);
    first.reset(); physical.reset();
    packet.reset();
    assert(releases==0); // New publication still leases the original physical owner.
    auto final_lease=second->owner_lifetime;
    second.reset();
    assert(releases==0);
    final_lease.reset();
    assert(releases==1);
    auto invalid=std::make_shared<Snapshot>();
    assert(!republish_resource_snapshot(std::shared_ptr<const Snapshot>(invalid),20));
    assert(!republish_resource_snapshot(std::shared_ptr<const Snapshot>{},20));
    std::cout << "Resource reuse: per-role payload, world/liveness gates, immutable publications and cancellation leases passed\n";
}

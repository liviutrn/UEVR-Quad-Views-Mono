#include "TriViewLocatedPose.hpp"
#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>
struct Pose { uint64_t quadview_locate_serial{}; uint32_t located_frame{}; int head{}, left{}, right{}; };
int main() {
    uevr::triview::LocatedPose<Pose> cache;
    assert(!cache.get());
    cache.publish({0, 100, 10, 11, 12});
    const auto frozen=*cache.get();
    Pose ring_slot=frozen;
    ring_slot.located_frame=106; // Unreal stamps a recycled role slot without locating.
    assert(ring_slot.located_frame==106 && cache.get()->located_frame==100 && cache.get()->head==10);
    assert(frozen.quadview_locate_serial==cache.get()->quadview_locate_serial);
    cache.publish({0, 4, 20, 21, 22}); // same object, counter rolled back across a world change
    assert(cache.get()->located_frame==4 && cache.get()->head==20);
    assert(cache.get()->quadview_locate_serial!=frozen.quadview_locate_serial);
    assert(frozen.head==10 && frozen.left==11 && frozen.right==12);
    const auto before_invalidate=cache.get()->quadview_locate_serial;
    cache.invalidate(); assert(!cache.get());
    cache.publish({0, 4, 30, 31, 32});
    assert(cache.get()->quadview_locate_serial>before_invalidate);
    struct DynamicPose { uint64_t quadview_locate_serial{}; std::vector<int> views; };
    uevr::triview::LocatedPose<DynamicPose> dynamic;
    DynamicPose source{0,{10,20}};
    dynamic.publish(source);
    const auto* storage=dynamic.get()->views.data();
    source.views={30,40}; dynamic.publish(source);
    assert(dynamic.get()->views.data()==storage && dynamic.get()->views[0]==30);
    std::cout << "TriView located pose identity tests passed\n";
}

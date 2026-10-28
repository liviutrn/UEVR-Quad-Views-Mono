#include "DuoViewGeometry.hpp"
#include <cassert>
#include <iostream>
using namespace uevr::duoview;
int main() {
    assert(!depth_viewport_valid({},64,64));
    const DepthViewport good{11,7,32,24,0,1};
    assert(depth_viewport_valid(good,64,64));
    assert(!depth_viewport_valid(good,32,24));
    assert(depth_viewport_valid({.25f,.75f,10.5f,9.25f,.2f,.8f},64,64));
    assert(depth_viewport_valid({0,0,64,64,1,0},64,64));
    for(float bad : {std::numeric_limits<float>::quiet_NaN(),
                      std::numeric_limits<float>::infinity(),-1.f}) {
        for(int field=0;field<6;++field) {
            auto v=good;
            if(field==0)v.x=bad;
            if(field==1)v.y=bad;
            if(field==2)v.width=bad;
            if(field==3)v.height=bad;
            if(field==4)v.min_depth=bad;
            if(field==5)v.max_depth=bad;
            assert(!depth_viewport_valid(v,64,64));
        }
    }
    assert(!depth_viewport_valid({0,0,64,64,.5f,.5f},64,64));
    assert(!depth_viewport_valid({0,0,64,64,0,1.1f},64,64));
    assert(!depth_viewport_valid(good,0,64));
    assert(!depth_viewport_valid(good,UINT64_MAX,64));
    assert(!depth_viewport_valid({0,0,.5f,10,0,1},64,64));
    std::cout<<"PASS: 28 depth viewport/range/finite/resource-boundary contracts\n";
}

#include "QuadViewNativeTargets.hpp"
#include "QuadViewGeometry.hpp"
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>

using namespace uevr::quadview;

static void test_zero_physical_slot_one() {
    Layout layout{};
    layout.native_local=true;
    layout.shared_context=true;
    layout.views[0]={0,0,800,600};
    layout.views[1]={8,0,800,600}; // logical view family is retained
    layout.views[2]={16,0,1800,1400};
    layout.views[3]={24,0,1800,1400};
    const auto requested=triview_source_extents(layout);
    assert(requested[1][0]==0 && requested[1][1]==0);
    assert(requested[0][0]>800 && requested[0][1]>=600);
    assert(requested[2][0]>1800 && requested[2][1]>=1400);
    assert(requested[3]==requested[2]);
    // The original QuadView geometry function remains unchanged for other
    // geometry tests; B17 only uses this TriView-specific physical extent.
    const auto four=source_extents(layout);
    assert(four[1][0]!=0 && four[1][1]!=0);

    std::array<NativeTargetIdentity,4> targets{};
    for (size_t i : {size_t(0),size_t(2),size_t(3)}) {
        const uintptr_t n=static_cast<uintptr_t>(i+1);
        targets[i]={0x1000+n,0x2000+n,0x3000+n,0x4000+n,
                    17,requested[i][0],requested[i][1],28};
    }
    assert(valid_native_triview_targets(targets,requested));
    auto wrong=targets;
    wrong[1].native_resource=0x12345;
    assert(!valid_native_triview_targets(wrong,requested));
    wrong=targets;
    wrong[2].native_resource=wrong[0].native_resource;
    assert(!valid_native_triview_targets(wrong,requested));
    wrong=targets;
    wrong[3].target_set_generation++;
    assert(!valid_native_triview_targets(wrong,requested));
    wrong=targets;
    wrong[3].width++;
    assert(!valid_native_triview_targets(wrong,requested));
    auto wrong_extents=requested;
    wrong_extents[1]={64,64};
    assert(!valid_native_triview_targets(targets,wrong_extents));
    wrong=targets;
    wrong[0].render_target=0;
    assert(!valid_native_triview_targets(wrong,requested));
}

int main() {
    test_zero_physical_slot_one();
    std::cout<<"TriView 3 physical source role contracts passed\n";
}

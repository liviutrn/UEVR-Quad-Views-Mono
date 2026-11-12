#include "depthxr/dynamic_smooth.h"
#include <cmath>
#include <iostream>
int main() {
    using depthxr::dynamic_smooth::Slots;
    using depthxr::dynamic_smooth::LeadFloor;
    unsigned errors = 0;
    auto check = [&](bool ok, const char* label) {
        if (!ok) { ++errors; std::cerr << "FAIL: " << label << "\n"; }
    };
    const double refresh = 1000.0 / 120.0;
    check(Slots(0,4)==2, "unmeasured stock");
    check(Slots(6,4)==4, "4x default");
    check(Slots(6,6)==6, "6x toggle");
    check(Slots(5,6)==5, "5x toggle");
    check(Slots(5.6,6)==6, "round measured cadence");
    check(LeadFloor(50,50,refresh,0,24)==0, "reserve off");
    check(LeadFloor(50,50,refresh,2,24)==14, "20fps reserve 2");
    check(LeadFloor(50,50,refresh,2,12)==12, "lead cap");
    for (int i=1; i<=5; ++i)
        check(std::abs((i*refresh)/50.0-i/6.0)<1e-10, "20fps 120Hz fractions");
    check(depthxr::dynamic_smooth::CanProbeDown(14,13), "probe allowed above floor");
    check(!depthxr::dynamic_smooth::CanProbeDown(13,13), "no probe at floor");
    check(!depthxr::dynamic_smooth::CanProbeDown(12,13), "no probe below floor");
    check(depthxr::dynamic_smooth::CanProbeDown(2,0), "stock minimum remains one");
    using depthxr::dynamic_smooth::ClassifyJit;
    using depthxr::dynamic_smooth::JitKind;
    check(ClassifyJit(true,3,true,true,false,true)==JitKind::kInterpolate,
          "accepted, distinct actual JIT interpolation");
    check(ClassifyJit(true,3,true,true,false,false)==JitKind::kPredict,
          "accepted, distinct JIT extrapolation");
    check(ClassifyJit(false,3,true,true,false,true)==JitKind::kOther,
          "failed RuntimeEnd never counted as interpolation");
    check(ClassifyJit(true,4,true,true,false,true)==JitKind::kOther,
          "fallback path is not proven interpolation");
    check(ClassifyJit(true,3,true,true,true,true)==JitKind::kOther,
          "exact copy never counted as interpolation");
    check(ClassifyJit(true,3,false,true,false,true)==JitKind::kOther,
          "repeat never counted as interpolation");
    check(ClassifyJit(true,3,true,false,false,true)==JitKind::kOther,
          "no GPU write never counted as interpolation");
    using depthxr::dynamic_smooth::MissingGridSlots;
    constexpr std::int64_t grid = 8333333;
    check(MissingGridSlots(grid,grid)==0, "ordinary target interval");
    check(MissingGridSlots(6*grid,grid)==5, "20fps target gap at 120Hz");
    check(MissingGridSlots(3*grid,grid)==2, "missing two grid slots");
    check(MissingGridSlots(149*grid/100,grid)==0, "jitter below half-slot");
    check(MissingGridSlots(151*grid/100,grid)==1, "jitter beyond half-slot");
    check(MissingGridSlots(200*grid,grid)==120, "large hitch bounded");
    check(MissingGridSlots(0,grid)==0, "nonpositive target interval");
    check(MissingGridSlots(grid,0)==0, "invalid grid period");
    check(MissingGridSlots(-grid,grid)==0, "backwards target counted separately");
    if (!errors) std::cout << "Dynamic Smooth tests passed\n";
    return errors ? 1 : 0;
}

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
    using depthxr::dynamic_smooth::ScoreLead;
    using namespace depthxr::dynamic_smooth;
    // Reserve OFF: exact stock classification, including no slack.
    check(ScoreLead(true,false,0,refresh,0)==kLeadLate,"stock late");
    check(ScoreLead(false,false,0,refresh,0)==kLeadOnTime,"stock unknown");
    check(ScoreLead(false,true,0.5*refresh,refresh,0)==kLeadOnTime,"stock half refresh");
    check(ScoreLead(false,true,1.0*refresh,refresh,0)==kLeadOnTime,"stock one refresh");
    check(ScoreLead(false,true,1.1*refresh,refresh,0)==kLeadOnTime,"stock strict threshold");
    check(ScoreLead(false,true,1.2*refresh,refresh,0)==kLeadSpare,"stock spare");
    check(ScoreLead(false,true,5.0*refresh,refresh,0)==kLeadSpare,"stock abundant slack");
    // Reserve ON: thin <2 periods, spare >3.1, no blind probe on unknown.
    check(ScoreLead(true,true,4*refresh,refresh,2)==kLeadLate,"reserve late prioritized");
    check(ScoreLead(false,false,0,refresh,2)==kLeadUnknown,"reserve unknown");
    check(ScoreLead(false,true,1.9*refresh,refresh,2)==kLeadThin,"reserve thin");
    check(ScoreLead(false,true,2.0*refresh,refresh,2)==kLeadOnTime,"reserve target boundary");
    check(ScoreLead(false,true,3.1*refresh,refresh,2)==kLeadOnTime,"reserve anti-flap band");
    check(ScoreLead(false,true,3.2*refresh,refresh,2)==kLeadSpare,"reserve measured spare");
    check(ScoreLead(false,true,5.0*refresh,refresh,2)==kLeadSpare,"reserve large slack");
    for (int i=1; i<=5; ++i)
        check(std::abs((i*refresh)/50.0-i/6.0)<1e-10, "20fps 120Hz fractions");
    using depthxr::dynamic_smooth::MotionStep;
    using depthxr::dynamic_smooth::ClassifyMotionStep;
    const std::int64_t p = 8333333;
    check(ClassifyMotionStep(p,p,p)==MotionStep::kEven, "normal content step");
    check(ClassifyMotionStep(0,p,p)==MotionStep::kFreeze, "repeated content");
    check(ClassifyMotionStep(-p,p,p)==MotionStep::kRewind, "content rewind");
    check(ClassifyMotionStep(2*p,p,p)==MotionStep::kJump, "content jump");
    check(ClassifyMotionStep(3*p,2*p,p)==MotionStep::kJump, "jump when target skipped");
    check(ClassifyMotionStep(2*p,2*p,p)==MotionStep::kEven, "content advances with requested gap");
    check(ClassifyMotionStep(p,0,p)==MotionStep::kEven, "no prior target");
    using depthxr::dynamic_smooth::ContentTime;
    check(ContentTime(0,6*p,0.5f,true,false)==3*p, "interpolated content midpoint");
    check(ContentTime(0,6*p,1.0f,false,false)==12*p, "extrapolated content interval");
    check(ContentTime(0,6*p,0.1f,true,true)==6*p, "exact image newest time");
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

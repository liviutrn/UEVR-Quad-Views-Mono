#include "depthxr/dynamic_smooth.h"
#include <cmath>
#include <iostream>
int main() {
    using depthxr::dynamic_smooth::Slots;
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
    // Positive reserve decisions: unlike a smoke-only runtime test, these
    // assert what the controller would do with known evidence.
    check(!ReserveWantsUp(2), "two thin is not enough");
    check(ReserveWantsUp(3), "three thin raises reserve");
    check(ReserveWantsUp(3) && !ReserveWantsDown(10, 0, 7, 3),
          "seven spare plus three thin must not simultaneously lower");
    check(ReserveWantsDown(10, 0, 6, 0),
          "four unknown and six spare must lower on measured evidence");
    check(!ReserveWantsDown(10, 4, 4, 2), "two thin block lowering");
    check(!ReserveWantsDown(10, 4, 2, 0), "too little spare");
    check(!ReserveWantsDown(7, 0, 7, 0), "not enough history");
    check(!ReserveWantsDown(10, 0, 4, 0), "too few measured frames");
    check(!ReserveRingShort(true,true,false,true,true,true,true),
          "cover does not trigger ring backoff");
    check(!ReserveRingShort(true,false,false,true,true,true,false),
          "late presenter does not trigger ring backoff");
    check(!ReserveRingShort(true,false,false,true,false,true,true),
          "old lead ring short cannot trigger backoff");
    check(ReserveRingShort(true,false,false,true,true,true,true),
          "current lead timely ring short triggers backoff even at ring 3");
    using Clock = DownHold::Clock;
    using namespace std::chrono;
    const auto base = Clock::time_point{} + seconds(1);
    DownHold hold;
    check(!hold.NoteUp(base, seconds(60)), "no prior down: no flap");
    hold.NoteDown(base);
    check(hold.NoteUp(base + seconds(1), seconds(60)),
          "up within fifteen seconds triggers hold");
    check(hold.hold == seconds(20), "first hold is 20 seconds");
    check(hold.BlockDown(base + seconds(12)), "hold blocks early down");
    check(!hold.BlockDown(base + seconds(22)), "hold expires");
    hold.NoteDown(base + seconds(23));
    check(hold.NoteUp(base + seconds(24), seconds(60)), "second flap");
    check(hold.hold == seconds(40), "second hold doubles");
    hold.NoteDown(base + seconds(25));
    check(hold.NoteUp(base + seconds(26), seconds(60)), "third flap");
    check(hold.hold == seconds(60), "third hold caps at sixty seconds");
    hold.NoteDown(base + seconds(27));
    check(hold.NoteUp(base + seconds(28), seconds(60)), "fourth flap");
    check(hold.hold == seconds(60), "hold remains capped");
    DownHold noflap;
    noflap.NoteDown(base);
    check(!noflap.NoteUp(base + seconds(15), seconds(60)),
          "exact fifteen seconds is no flap");
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
    check(ContentTime(2*p,8*p,0.5f,true,false)==5*p, "interpolated content midpoint");
    check(ContentTime(2*p,8*p,1.0f,false,false)==14*p, "extrapolated content interval");
    check(ContentTime(2*p,8*p,0.1f,true,true)==8*p, "exact image newest time");
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

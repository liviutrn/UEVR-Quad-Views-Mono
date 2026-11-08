#include "QuadViewDepthContinuity.hpp"
#include <cstdlib>
#include <iostream>
#include <vector>

using namespace uevr::quadview::ngx::continuity;

static void check(bool ok, const char* message) {
    if (!ok) { std::cerr << "FAILED: " << message << '\n'; std::exit(1); }
}

int main() {
    constexpr uint32_t w=640,h=360;
    const auto ready=[](uint64_t seq,uint32_t age=0,uint32_t width=640,uint32_t height=360) {
        return Candidate{seq,width,height,age,true,true,true,false,true};
    };
    std::vector<Candidate> one{ready(1)};
    check(newest_protected(one,w,h)==0,"singleton latest depth stays protected");
    // Repeated 22.5 fps Record/Present/Submit cadence: pending replacement is
    // not a candidate, so the prior submitted snapshot remains selectable.
    for (uint32_t frame=0;frame<6;++frame) {
        one[0].age_ms=frame*44;
        check(newest_protected(one,w,h)==0,"old submitted snapshot survives each pending capture");
        one.push_back(Candidate{uint64_t(frame+2),w,h,0,false,false,true,false,true});
        check(newest_protected(one,w,h)==0,"pending replacement cannot displace valid submitted depth");
        one.pop_back();
    }
    one={ready(1,44),ready(2,0)};
    check(newest_protected(one,w,h)==1,"new submitted replacement promotes; old slot becomes reusable");
    one={ready(1,0,642,362)};
    check(newest_protected(one,w,h)==0,"same selector alignment tolerance applies to continuity");
    for(uint32_t interval:{44u,50u}) {
        std::vector<Candidate> slots{ready(10)};
        for(uint32_t frame=0;frame<20;++frame) {
            slots[0].age_ms=interval;
            slots.push_back(Candidate{11+frame,w,h,0,false,false,true,false,true});
            check(newest_protected(slots,w,h)==0,"22.5/20 FPS pending recording preserves selectable depth");
            slots[1]=ready(11+frame);
            check(newest_protected(slots,w,h)==1,"replacement is promoted only after submission");
            slots[0]=slots[1];slots.pop_back();
        }
    }
    one[0].age_ms=250;
    check(newest_protected(one,w,h)==SIZE_MAX,"age limit still expires old snapshot");
    one[0]=ready(2,0,800,450);
    check(newest_protected(one,w,h)==SIZE_MAX,"resize invalidates old-size protection");
    one[0]=Candidate{3,w,h,0,true,false,true,false,true};
    check(newest_protected(one,w,h)==SIZE_MAX,"failed evaluation is not protected");
    std::vector<Candidate> queued{ready(4),Candidate{5,w,h,0,true,true,true,true,false}};
    check(newest_protected(queued,w,h)==0,"incomplete foreign-queue fence cannot supersede usable depth");
    queued[0].foreign_queue=true;queued[0].fence_complete=false;
    check(newest_protected(queued,w,h)==SIZE_MAX,"busy foreign fence provides no continuity");
    std::cout << "B36 depth continuity policy passed\n";
}

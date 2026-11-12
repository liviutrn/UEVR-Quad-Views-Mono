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
    if (!errors) std::cout << "Dynamic Smooth tests passed\n";
    return errors ? 1 : 0;
}

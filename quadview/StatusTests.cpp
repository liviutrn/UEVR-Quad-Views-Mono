#include "QuadViewStatus.hpp"
#include <stdexcept>
#include <thread>
#include <vector>
using namespace uevr::quadview;
void check(bool ok) { if (!ok) throw std::runtime_error("Status contract failed"); }
int main() {
    StatusTracker tracker;
    check(tracker.state({2,100,false,false,false}) == DisplayState::waiting_targets);
    check(!tracker.submitted(1,99,100));
    check(tracker.submitted(2,1,100));
    check(tracker.state({2,1099,false,false,false}) == DisplayState::active);
    check(tracker.state({2,1100,false,false,true}) == DisplayState::stalled);
    check(tracker.state({2,101,true,false,true}) == DisplayState::transitioning);
    check(tracker.state({2,101,false,true,true}) == DisplayState::unavailable);
    check(!tracker.submitted(2,1,1200)); // Held/replayed serial cannot refresh age.
    check(!tracker.submitted(2,2,99));
    check(tracker.state({3,1200,false,false,true}) == DisplayState::waiting_submit);
    check(!tracker.submitted(2,1000,1201));
    std::vector<std::thread> writers;
    for (unsigned i=0;i<4;++i) writers.emplace_back([&,i] {
        for (uint64_t n=1;n<=2000;++n) tracker.submitted(3,n*4+i,n*4+i+1200);
    });
    for (auto& writer:writers) writer.join();
    const auto result=tracker.snapshot(3);
    check(result.generation==3 && result.serial==8003 && result.tick==9203);
}

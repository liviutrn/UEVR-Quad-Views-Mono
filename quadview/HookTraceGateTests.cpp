#include "QuadViewHookTrace.hpp"
#include <cassert>
#include <thread>
#include <vector>
using uevr::quadview::HookTraceGate;
int main() {
    HookTraceGate gate;
    for(uint64_t s=4126;s<4129;++s)
        for(unsigned role=0;role<4;++role) assert(gate.visit(7,3,s,100).emit);
    assert(!gate.visit(7,3,4129,100).emit);
    assert(gate.visit(8,3,4129,100).emit); // First rejection at each site cannot be hidden by another site.
    assert(gate.visit(7,3,4129,1100).emit);
    assert(!gate.visit(7,3,4129,1101).emit);
    assert(gate.visit(7,4,9000,1101).emit); // New generation gets an independent trace.
    HookTraceGate stalled;
    for(int n=0;n<64;++n) assert(stalled.visit(1,1,1,0).emit);
    assert(!stalled.visit(1,1,1,0).emit); // A stuck draw cannot cause unbounded logging.
    assert(stalled.visit(1,1,1,1000).emit);
    assert(!stalled.visit(HookTraceGate::site_count,1,1,1000).emit);
    HookTraceGate concurrent;
    std::vector<std::thread> threads;
    for(int i=0;i<4;++i) threads.emplace_back([&]{for(int n=0;n<10000;++n)concurrent.visit(2,1,0,0);});
    for(auto& t:threads)t.join();
    assert(concurrent.visit(2,1,0,1000).count==40001);
}

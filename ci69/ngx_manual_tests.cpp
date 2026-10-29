#include "mods/vr/DuoViewNgxGuide.hpp"
#include <thread>
#include <stdexcept>
#include <iostream>
#include <array>
using namespace uevr::duoview::ngx;
static void check(bool value,const char* why){if(!value)throw std::runtime_error(why);}
int main()try {
 auto& c=manual_registry();
 std::thread a([&]{c.observe({0x123,3,100,800,600,400,300,1,true,true});});
 std::thread b([&]{c.observe({0x456,8,101,320,240,160,120,1,true,true});});
 a.join();b.join();
 check(c.browse().size()>=2,"two concurrent NGX sources registered");
 check(c.pin(0,0x123,800,600),"left pin by feature and output extent");
 check(!c.pin(1,0x123,800,600),"duplicate signature must not become right");
 check(c.pin(1,0x456,320,240),"right pin by feature and extent");
 check(c.role(0x123,800,600)==1&&c.role(0x456,320,240)==2,"manual roles");
 check(c.role(0x123,320,240)==0,"wrong extent must not match");
 auto pins=c.pins();
 check(pins[0]==std::array<uintptr_t,3>{0x123,800,600},"left pin stable key");
 check(pins[1]==std::array<uintptr_t,3>{0x456,320,240},"right pin stable key");
 c.observe({0x123,11,201,800,600,400,300,1,true,true});
 check(c.role(0x123,800,600)==1,"generation or ordinal changes cannot invalidate same-size pin");
 c.observe({0x123,12,202,320,240,160,120,1,true,true});
 check(c.role(0x123,320,240)==0,"alternating extent cannot silently remap role");
 c.released(0x123);
 check(c.role(0x123,800,600)==0,"feature release invalidates pin");
 check(!c.pin(0,0x123,800,600),"released feature cannot repin");
 c.clear(1);check(c.role(0x456,320,240)==0,"explicit clear");
 Guide g{};g.manual_source=true;g.feature_generation=2;g.evaluation=3;g.role=1;
 g.input_width=400;g.input_height=300;g.output_width=800;g.output_height=600;
 check(bool(g),"manual source accepted independent of old RHI ticket");
 g.role=0;check(!bool(g),"unassigned guide not stereo-valid");
 std::cout<<"PASS CI69 NGX manual stable dimensions and lifecycle\n";
 return 0;
} catch(const std::exception& ex){std::cerr<<ex.what()<<"\n";return 1;}

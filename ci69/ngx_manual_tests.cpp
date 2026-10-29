#include "mods/vr/DuoViewNgxGuide.hpp"
#include <thread>
#include <stdexcept>
#include <iostream>
using namespace uevr::duoview::ngx;
static void check(bool value,const char* why){if(!value)throw std::runtime_error(why);}
int main()try {
 auto& c=manual_registry();
 std::thread a([&]{c.observe({0x123,3,100,800,600,400,300,1,true,true});});
 std::thread b([&]{c.observe({0x456,8,101,320,240,160,120,1,true,true});});
 a.join();b.join();
 check(c.browse().size()>=2,"two concurrent NGX sources registered");
 check(c.pin(0,0x123,3),"left pin");
 check(!c.pin(1,0x123,3),"duplicate feature must not become right");
 check(c.pin(1,0x456,8),"right pin");
 check(c.role(0x123,3)==1&&c.role(0x456,8)==2,"manual roles");
 c.released(0x123);check(c.role(0x123,3)==0,"feature release invalidates pin");
 check(!c.pin(0,0x123,3),"released generation cannot repin");
 c.clear(1);check(c.role(0x456,8)==0,"explicit clear");
 Guide g{};g.manual_source=true;g.feature_generation=2;g.evaluation=3;g.role=1;g.input_width=400;
 g.input_height=300;g.output_width=800;g.output_height=600;
 check(bool(g),"manual source accepted independent of RHI ticket");
 g.role=0;check(!bool(g),"unassigned guide not stereo-valid");
 std::cout<<"PASS CI69 NGX-only manual registry\n";
 return 0;
} catch(const std::exception& ex){std::cerr<<ex.what()<<"\n";return 1;}

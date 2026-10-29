#include "mods/vr/DuoViewNgxGuide.hpp"
#include <iostream>
#include <stdexcept>
#include <thread>
#include <chrono>
#include <vector>
using namespace uevr::duoview::ngx;
void need(bool v,const char* why){if(!v)throw std::runtime_error(why);}
int main()try {
 ProducerTicket t{42,3,99,100,3,{800,600,320,240}};
 need(role_for(t,800,600)==1 && role_for(t,320,240)==2,"exact role dimensions");
 need(role_for(t,799,600)==0,"near equal dims must not guess");
 auto ambiguous=t;ambiguous.outputs={800,600,800,600};need(role_for(ambiguous,800,600)==0,"ambiguous dimensions");
 auto role=t;role.roles=2;need(role_for(role,800,600)==0,"ticket role mask");
 Features f;f.created(0x100,1,10,true,800,600);auto first=f.observed(0x100,0,false,800,600);
 need(first.create_observed && first.kind==1 && first.flags_known && first.flags==10,"create flags persist across eval params");
 f.released(0x100);auto reused=f.observed(0x100,0,false,800,600);
 need(reused.generation!=first.generation && !reused.create_observed && !reused.flags_known,"released pointer cannot keep old contract");
 f.created(0x200,13,8,true,800,600);need(f.observed(0x200,0,false,800,600).kind!=1,"known RR is not SR");
 Guide a;a.producer=t;a.role=1;a.feature_generation=1;a.evaluation=1;a.input_width=400;a.input_height=300;a.output_width=800;a.output_height=600;
 auto b=a;b.role=2;b.output_width=320;b.output_height=240;b.feature_generation=2;b.evaluation=2;
 need(same_pair(a,b,42,3),"same producer packet");b.producer.packet=43;need(!same_pair(a,b,42,3),"interleaved packet rejected");
 b=a;b.role=2;b.output_width=320;b.output_height=240;b.producer.render_frame++;need(!same_pair(a,b,42,3),"interleaved render frame rejected");
 b=a;b.role=2;b.output_width=320;b.output_height=240;need(!same_pair(a,b,42,4),"generation reset rejected");
 std::vector<SnapshotIdentity> planes;
 for(unsigned role_id=1;role_id<=2;++role_id)for(unsigned plane=1;plane<=3;++plane)
  planes.push_back({role_id==1?a:b,role_id==1?100u:200u,static_cast<Plane>(plane)});
 for(size_t n=0;n<=planes.size();++n)need(complete_snapshot(std::span(planes).first(n),100,200,42,3)==(n==6),"0..6 atomic plane gate");
 auto invalid=planes;invalid[0].serial++;need(!complete_snapshot(invalid,100,200,42,3),"wrong selected serial");
 invalid=planes;invalid[0].guide.producer.packet++;need(!complete_snapshot(invalid,100,200,42,3),"wrong selected packet");
 invalid=planes;invalid[0].guide.evaluation++;need(!complete_snapshot(invalid,100,200,42,3),"mixed guide evaluation");
 invalid=planes;invalid[0].plane=Plane::motion;need(!complete_snapshot(invalid,100,200,42,3),"duplicate plane");
 auto wrong_role=b;wrong_role.output_width=800;wrong_role.output_height=600;need(!same_pair(a,wrong_role,42,3),"wrong role output contract");
 a.jitter_x=.5f;a.jitter_y=-.25f;const auto j=a.jitter_uv();need(j[0]==.5f/400.f && j[1]==-.25f/300.f,"jitter uses input not output pixels");
 // Build67: observe a complete RHI source pair on a distinct NGX CPU thread.
 auto& bridge=producer_bridge();bridge.reset();
 need(!bridge.resolve(800,600),"no ticket must reject");
 std::thread producer([&]{bridge.publish(t);});producer.join();
 ProducerTicket transfer{};
 std::thread consumer([&]{transfer=bridge.resolve(800,600);});consumer.join();
 need(transfer==t,"cross-thread producer transfer failed");
 need(!bridge.resolve(799,600),"unrelated NGX output not accepted");
 need(!bridge.resolve(800,600,std::chrono::milliseconds{-1}),"stale interval accepted");
 bridge.publish(ambiguous);need(!bridge.resolve(800,600),"ambiguous owner must invalidate");
 bridge.publish(t);bridge.publish({});need(!bridge.resolve(320,240),"empty handoff must clear owner");
 const auto counters=bridge.counters();
 need(counters.published>=2 && counters.empty>=2 && counters.resolved>=1 &&
      counters.stale>=1 && counters.shape_rejected>=1,"bridge counters");
 std::cout<<"PASS: exact roles, ambiguity, late injection, Create/Release reuse, RR classification, packet/frame/generation pairing, atomic0..6 planes and jitter units\n";
 return 0;
} catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}

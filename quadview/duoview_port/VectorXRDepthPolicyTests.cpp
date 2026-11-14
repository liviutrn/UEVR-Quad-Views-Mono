#include "VectorXRDepthPolicy.hpp"
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <iostream>
using namespace uevr::duoview::xrdepth;

Packet valid() {
    Packet p{};
    p.frame=91; p.source=42; p.output=11;
    p.color_generation=p.depth_generation=7;
    p.enabled=p.depth_extension=true;
    p.near_m=3.4e38f; p.far_m=.1f;
    for(int i=0;i<2;++i) {
        auto& e=p.eye[i];
        e.frame=p.frame; e.source=p.source; e.output=p.output;
        e.color={10,p.color_generation,0,1,{i*512,0,512,512}};
        e.depth={20,p.depth_generation,0,1,{i*512,0,512,512}};
        e.render_pose.pose={0,0,0,0,0,0,1};
        e.render_pose.fov={-.9f,.9f,.9f,-.9f};
        e.submit_pose=e.render_pose;
        e.selected_final_color_uv=e.selected_background_fill=true;
        e.depth_written=e.copy_queued=e.released=e.state_restored=true;
        e.sampleable=e.supported_format=true;
    }
    return p;
}
void is(Decision got,Decision expected) {
    if(got!=expected) {
        std::cerr << reason(got) << " expected " << reason(expected) << "\n";
        std::abort();
    }
}
void check_packets() {
    auto p=valid(); is(admit(p),Decision::Attach);
    p.enabled=false; is(admit(p),Decision::Disabled); p=valid();
    p.depth_extension=false; is(admit(p),Decision::NoExtension); p=valid();
    p.holding_color=true; is(admit(p),Decision::HeldColor); p=valid();
    p.far_m=0; is(admit(p),Decision::BadEncoding); p=valid();
    p.eye[1].source++; is(admit(p),Decision::Stale); p=valid();
    p.eye[0].output++; is(admit(p),Decision::Stale); p=valid();
    p.eye[1].depth.generation++; is(admit(p),Decision::Generation); p=valid();
    p.eye[1].submit_pose.pose[0]+=.01f; is(admit(p),Decision::Pose); p=valid();
    p.eye[0].depth.rect.x++; is(admit(p),Decision::RectMismatch); p=valid();
    p.eye[1].depth.slice=1; is(admit(p),Decision::RectMismatch); p=valid();
    p.eye[1].depth.samples=4; is(admit(p),Decision::BadSwapchain); p=valid();
    p.eye[1].sampleable=false; is(admit(p),Decision::BadSwapchain); p=valid();
    p.eye[1].depth_written=false; is(admit(p),Decision::MissingEye); p=valid();
    p.eye[1].selected_background_fill=false; is(admit(p),Decision::MissingEye); p=valid();
    p.eye[1].released=false; is(admit(p),Decision::NotReleased); p=valid();
    p.eye[0].state_restored=false; is(admit(p),Decision::NotReleased);
}
void check_geometry() {
    const float near_engine=10.f, scale=1.f;
    const float bar=1.f/(.5f*100.f);
    const float wall=1.f/(12.f*100.f);
    const float conditioned=near_knee(bar,1.f/100.f);
    assert(conditioned<bar && conditioned>wall);
    for(const float strength:{0.f,.4f,.8f,1.f}) for(int eye=0;eye<2;++eye) {
        const float physical_k=eye==0 ? -.07f : .07f;
        // The color and depth read the same selected sample. In particular,
        // the near-limit knee must be applied ONCE, before both reads.
        const float color_disparity=physical_k*strength*conditioned;
        const float normalized=reversed_infinite(conditioned,near_engine,scale,strength);
        const float depth_disparity=physical_k*normalized/(near_engine*scale);
        assert(std::abs(color_disparity-depth_disparity)<1.e-7f);
        assert(normalized>=reversed_infinite(wall,near_engine,scale,strength));
    }
    assert(reversed_infinite(-1.f,near_engine,scale,1.f)==0.f);
}
int main() { check_packets(); check_geometry(); std::cout<<"PASS depth policy and stereo math\n"; }

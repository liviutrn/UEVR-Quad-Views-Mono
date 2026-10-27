#include "DuoViewState.hpp"
#include <cassert>
#include <cmath>
#include <iostream>

using namespace uevr::duoview;
using Matrix = std::array<std::array<double,4>,4>;

static bool near(double a,double b) { return std::abs(a-b)<1.e-5; }
static Matrix mat(const ViewFrame& f,unsigned eye) {
    Matrix r{};
    apply_frame_projection(r,f,eye);
    return r;
}

int main() {
    State s;
    Settings opts{};
    opts.eye_tracked=false;
    opts.fovea_view=0;
    assert(s.configure(opts));

    // Different native LEFT/RIGHT off-axis projection matrices, not a single
    // cloned MONO matrix. This corresponds to frame-snapshotted HMD projections.
    std::array<float,16> left{},right{};
    left[0]=.8f; left[5]=.95f; left[8]=.04f;
    left[11]=1.f; left[14]=.1f;
    right[0]=1.2f; right[5]=.85f; right[8]=-.07f;
    right[11]=1.f; right[14]=.1f;
    const FrameKey id{7,10};
    auto frame=s.begin(id,3000,3000,left,
        []()->std::optional<UV>{return UV{.5f,.5f};},100,321,true,right);
    assert(frame && frame->split_eye && frame->mono_source_frame==321);
    assert(frame->config.settings.fovea_view==0);
    assert(frame->config.layout.fovea.width==1500);
    assert(frame->config.layout.periphery.width==600);

    const auto lm=mat(*frame,0);
    const auto rm=mat(*frame,1);
    // The left input is the cropped left-eye perspective ALREADY at producer
    // projection time, not a full FOV left image awaiting a late crop.
    assert(near(lm[0][0],1.6));
    assert(near(lm[1][1],1.9));
    assert(near(lm[2][0],.08));
    // The right producer retains its own full native FOV at 20% dimensions.
    assert(near(rm[0][0],1.2));
    assert(near(rm[1][1],.85));
    assert(near(rm[2][0],-.07));
    assert(near(lm[3][2],.1)&&near(rm[3][2],.1));

    const CameraPose left_eye{{1,2,3},{100,200,300}};
    const CameraPose right_eye{{1,2,3},{106.4,200,300}};
    assert(s.camera(id,0,left_eye));
    assert(s.camera(id,1,right_eye));
    const auto stored_l=s.camera(id,0),stored_r=s.camera(id,1);
    assert(stored_l && stored_r);
    assert(stored_l->position != stored_r->position);
    assert(near(stored_r->position[0]-stored_l->position[0],6.4));
    assert(s.rectangle(id,0) && s.rectangle(id,1));
    assert(s.projection(id,0) && s.projection(id,1));
    assert(s.family(id,true,2));
    const auto bound=s.snapshot(id);
    assert(bound && native_frame_binding(*bound));
    const auto complete=s.consume(id);
    assert(complete && complete->split_eye);
    assert(!s.consume(id)); // Duplicate consumption is forbidden.

    // Changing a pending UI preference must never mutate an already latched
    // producer packet for the same frame.
    opts.fovea_view=1;
    assert(s.configure(opts));
    auto same=s.begin(id,3000,3000,right,
        []()->std::optional<UV>{return UV{.1f,.8f};},101,322,false,left);
    assert(same && same->split_eye && same->config.settings.fovea_view==0);
    assert(same->mono_source_frame==321);
    assert(same->projection_right==right);

    // Original Build165 mono input retains shared pose/projection semantics.
    const FrameKey old{7,11};
    auto mono=s.begin(old,3000,3000,left,
        []()->std::optional<UV>{return UV{.5f,.5f};},120,323,false,{});
    assert(mono && !mono->split_eye);
    assert(s.camera(old,0,left_eye));
    assert(s.camera(old,1,left_eye));
    assert(s.camera(old,1)->position==left_eye.position);
    assert(!s.camera(old,1,right_eye)); // Shared mono pose mismatch rejected.
    assert(!s.consume(old));

    // Runtime reset and new generation must clear the previous producer pair.
    s.retire();
    assert(!s.snapshot(id));
    assert(s.begin({8,1},3000,3000,left,
        []()->std::optional<UV>{return UV{.5f,.5f};},200,400,true,right));
    std::cout<<"SplitEye165 Native per-eye input, cropped-left/full-right and packet lifecycle: PASS\n";
}

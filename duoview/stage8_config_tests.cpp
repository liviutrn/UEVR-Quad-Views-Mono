#include "DuoViewConfig.hpp"
#include <cassert>
#include <cmath>
#include <iostream>
namespace d=uevr::duoview;
static bool near(float a,float b){return std::fabs(a-b)<.0001f;}
int main() {
    d::ConfigLatch latch;
    auto first=latch.for_frame({5,10},3000,3000,{.5f,.5f});
    assert(first && first->layout.fovea.width==1500);
    assert(first->layout.periphery.width==600 && first->settings_revision==1);
    d::Settings modified{};
    modified.crop_width=.30f;modified.crop_height=.30f;
    modified.peripheral_scale=.15f;modified.feather_fraction=.04f;
    modified.sharpen_strength=.4f;
    assert(latch.set_settings(modified));
    // Deliberately alter gaze and size mid-frame: immutable frame's
    // geometry must remain unchanged for both views and DX12 shader.
    auto same=latch.for_frame({5,10},2000,2000,{.9f,.8f});
    assert(same && same->layout.fovea.width==1500);
    assert(near(same->gaze.u,.5f) && same->settings_revision==1);
    assert(near(same->settings.sharpen_strength,0.f)); // active-frame setting must not change
    auto next=latch.for_frame({5,11},3000,3000,{.9f,.8f});
    assert(next && next->settings_revision==2);
    assert(near(next->settings.sharpen_strength,.4f));
    assert(next->layout.fovea.width==900);
    assert(next->layout.periphery.width==450);
    assert(near(next->layout.u0,.7f) && near(next->layout.u1,1.f));
    assert(!latch.for_frame({5,10},3000,3000,{.9f,.8f}));
    assert(!latch.for_frame({5,12},3000,3000,{-1.f,.5f}));
    auto invalid=modified;invalid.feather_fraction=2.f;
    assert(!latch.set_settings(invalid));
    invalid=modified;invalid.sharpen_strength=5.5f;
    assert(!latch.set_settings(invalid));
    auto partial=d::reconcile_ui_settings(invalid,modified);
    assert((partial.rejected & d::reject_sharpen)!=0 && near(partial.settings.sharpen_strength,.4f));
    invalid=modified;invalid.sharpen_strength=std::nanf("");
    assert(!latch.set_settings(invalid));
    auto still=latch.for_frame({5,12},3000,3000,{.5f,.5f});
    assert(still && still->settings_revision==2);
    latch.retire();
    assert(!latch.for_frame({5,12},3000,3000,{.5f,.5f}));
    auto fresh=latch.for_frame({6,1},3000,3000,{.5f,.5f});
    assert(fresh && fresh->key.generation==6);
    // Upper limit 5.0 is accepted on its own latch so the revision sequence above is unchanged.
    d::ConfigLatch limit;
    auto at_limit=modified;at_limit.sharpen_strength=5.f;
    assert(limit.set_settings(at_limit));
    // v208b: sharpen max change per pixel (0.05..0.30, default 0.10 = unchanged output).
    d::Settings defaults{};
    assert(near(defaults.sharpen_max_change,.10f));
    auto ui_max=modified;
    ui_max.sharpen_max_change=.20f;
    auto ok_max=d::reconcile_ui_settings(ui_max,modified);
    assert(ok_max.rejected==0 && near(ok_max.settings.sharpen_max_change,.20f));
    ui_max.sharpen_max_change=.30f;
    assert(near(d::reconcile_ui_settings(ui_max,modified).settings.sharpen_max_change,.30f));
    ui_max.sharpen_max_change=.05f;
    assert(near(d::reconcile_ui_settings(ui_max,modified).settings.sharpen_max_change,.05f));
    for (float bad : {.04f, .31f, std::nanf("")}) {
        ui_max.sharpen_max_change=bad;
        auto r=d::reconcile_ui_settings(ui_max,modified);
        assert((r.rejected & d::reject_sharpen_max)!=0);
        assert(near(r.settings.sharpen_max_change,.10f)); // keeps previous value (modified keeps default)
        assert(r.rejected==d::reject_sharpen_max);
    }
    auto max_latch_bad=modified;
    max_latch_bad.sharpen_max_change=.04f;
    d::ConfigLatch max_latch;
    assert(!max_latch.set_settings(max_latch_bad));
    max_latch_bad.sharpen_max_change=.31f;
    assert(!max_latch.set_settings(max_latch_bad));
    max_latch_bad.sharpen_max_change=std::nanf("");
    assert(!max_latch.set_settings(max_latch_bad));
    max_latch_bad.sharpen_max_change=.30f;
    assert(max_latch.set_settings(max_latch_bad));
    std::cout<<"DuoView immutable per-frame config/gaze tests passed\n";
}

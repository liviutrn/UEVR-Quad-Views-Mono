#include "DuoViewSourceFit.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <iostream>

using namespace uevr::duoview;
static bool close(float a,float b,float e=1.e-5f) {return std::abs(a-b)<e;}

int main() {
    // Asymmetric PSVR2-style vertical extent in the center camera basis:
    // upper clipped band is not visible, bottom stays in the current frustum.
    const std::array<std::array<float,4>,2> bounds{{
        {0.f,1.f,.158f,1.f}, {.02f,.99f,.160f,.99f}
    }};
    const SourceFit f=fit_vertical_source(bounds,.02f);
    assert(f.valid() && f.active());
    assert(f.v0>.12f && f.v0<.158f && close(f.v1,1.f));
    assert(f.periphery_height(646)<646 && f.periphery_height(646)%8==0);
    // The headlocked output UV and gaze remain O; source pixels live in F.
    for(float v: {0.f,.158f,.160f,.33f,.5f,.75f,.99f,1.f})
        assert(close(f.to_logical_v(f.to_source_v(v)),v));
    // Fovea may extend beyond the smaller periphery footprint at an
    // extreme gaze position: it must not be clamped or squeezed.
    assert(f.to_source_v(0.f)<0.f);
    const float fovea_height=.5f;
    assert(close(f.to_source_v(.5f)-f.to_source_v(.5f-fovea_height),
                 fovea_height/f.span()));
    std::array<float,16> original{};
    original[0]=1.f/1.2f;
    original[5]=1.f/1.003f;
    original[11]=1.f;
    original[14]=.01f;
    auto fitted=original;
    assert(apply_source_fit_projection(fitted,f));
    assert(close(fitted[0],original[0])); // horizontal projection remains unchanged
    assert(close(fitted[11],original[11]) && close(fitted[14],original[14]));
    for(float v: {0.f,.158f,.25f,.5f,.8f,1.f}) {
        const float tangent=(1.f-2.f*v)*1.003f;
        const float new_ndc=fitted[5]*tangent+fitted[9];
        const float expect=1.f-2.f*f.to_source_v(v);
        assert(close(new_ndc,expect));
    }
    // With symmetric calibration or an invalid view, fallback is the
    // #317 identity source. No speculative source clipping.
    const std::array<std::array<float,4>,2> full{{
        {0.f,1.f,0.f,1.f},{0.f,1.f,.001f,.999f}
    }};
    const SourceFit identity=fit_vertical_source(full);
    assert(identity.valid() && !identity.active());
    assert(identity.periphery_height(646)==646);
    const std::array<std::array<float,4>,2> invalid{{
        {0.f,1.f,.8f,.2f},{0.f,1.f,0.f,1.f}
    }};
    assert(!fit_vertical_source(invalid).active());
    for(unsigned h: {8u,9u,64u,646u,3228u}) {
        const auto n=f.periphery_height(h);
        assert(n>=8u && n<=h);
    }
    std::cout<<"B318 projection, physical viewport, gaze, fallbacks PASS\n";
}

#include "QuadViewFocusLift.hpp"
#include <cassert>
#include <cmath>
#include <iostream>

int main() {
    using namespace uevr::quadview::focus_lift;
    const Profile p{};
    assert(gain(.5f,.5f,p)==1.f);
    assert(std::abs(gain(0.f,0.f,p)-default_corner_gain)<1.e-6f);
    for (int y=0;y<=100;++y) for (int x=0;x<=100;++x) {
        const float u=x/100.f,v=y/100.f,g=gain(u,v,p);
        assert(std::isfinite(g) && g>=1.f && g<=default_corner_gain+1.e-6f);
        assert(std::abs(g-gain(1.f-u,v,p))<1.e-6f);
        assert(std::abs(g-gain(u,1.f-v,p))<1.e-6f);
        Profile zero=p; zero.strength=0.f;
        assert(gain(u,v,zero)==1.f);
    }
    // Actual screenshot 5: flat gray sky. Avoid the yellow border and subtitle.
    struct Sample {float x,y,gray;};
    const Sample samples[]={{440,630,131},{1180,630,132},{520,650,139},
        {620,650,146},{425,900,145},{440,1180,132},{1180,1180,133},{800,900,146}};
    for (const auto s:samples) {
        const float u=(s.x-420.f)/790.f,v=(s.y-602.f)/620.f;
        assert(std::abs(s.gray*gain(u,v,p)-146.f)<2.f);
    }
    Profile brighter=p; brighter.brightness=1.05f;
    assert(std::abs(gain(.5f,.5f,brighter)-1.05f)<1.e-6f);
    std::cout<<"Fitted focus-lift profile: 10201 symmetry/bounds cases and measured sky samples passed\n";
}

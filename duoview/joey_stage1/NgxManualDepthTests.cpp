#include "DuoViewNgxManualDepth.hpp"
#include <cassert>
#include <chrono>
#include <thread>
#include <limits>

using namespace uevr::duoview::ngx;
int main() {
    auto& c=candidates();
    c.reset();
    c.set_expected(800,600,320,240);
    DepthCandidate periphery{};
    periphery.feature=0x101;periphery.output_width=320;periphery.output_height=240;
    periphery.render_width=160;periphery.render_height=120;periphery.depth_width=160;
    periphery.depth_height=120;periphery.depth_present=true;periphery.color_present=true;
    periphery.create_observed=true;periphery.feature_kind=1;
    c.observe(periphery);
    assert(!c.choose().source[0]);
    DepthCandidate fovea=periphery;
    fovea.feature=0x202;fovea.output_width=800;fovea.output_height=600;
    fovea.render_width=400;fovea.render_height=300;
    fovea.depth_width=400;fovea.depth_height=300;
    c.observe(fovea);
    auto choice=c.choose();
    assert(choice.source[0]==0x202 && choice.exact && !choice.manual);
    assert(c.expected()==std::array<uint32_t,4>{800,600,320,240});

    // A new equally sized SR feature is ambiguous, not secretly chosen by
    // evaluation order. A valid already pinned auto source may remain stable.
    auto extra=fovea;extra.feature=0x303;
    c.observe(extra);
    assert(c.choose().source[0]==0x202); // sticky auto
    assert(c.pin(0x303,800,600));
    choice=c.choose();
    assert(choice.source[0]==0x303 && choice.manual);
    c.released(0x303);
    assert(!c.selected()[0]);
    c.set_expected(800,600,320,240); // old sticky auto still retained
    assert(c.choose().source[0]==0x202);
    c.set_expected(802,600,320,240); // resizing invalidates automatic binding
    assert(!c.choose().source[0]);
    c.set_expected(800,600,320,240);
    // Two same-size options after a resize must be manually disambiguated.
    c.observe(extra);
    assert(c.choose().ambiguous && !c.choose().source[0]);
    assert(c.pin(0x202,800,600));
    assert(c.choose().manual && c.choose().source[0]==0x202);

    c.set_expected(800,600,800,600);
    assert(c.choose().manual); // explicit pin remains available for diagnostics
    c.clear();
    assert(c.choose().ambiguous && !c.choose().source[0]);

    // Largest *allocation* is never evidence of fovea identity.
    c.reset();
    c.set_expected(800,600,320,240);
    periphery.depth_width=4096;periphery.depth_height=4096;
    c.observe(periphery);
    assert(!c.choose().source[0]);
    c.observe(fovea);
    assert(c.choose().source[0]==0x202);

    // Manual source can examine nonmatching dimensions, but is labelled
    // explicitly as not exact for the current foveal producer.
    assert(c.pin(0x101,320,240));
    choice=c.choose();assert(choice.manual && !choice.exact && choice.source[0]==0x101);
    c.released(0x101);
    assert(!c.choose().manual);

    c.reset();
    c.set_expected(800,600,320,240);
    auto fg=fovea;fg.feature=0x999;fg.create_observed=true;fg.feature_kind=4;
    c.observe(fg);
    assert(!c.choose().source[0]);
    assert(!c.pin(0x999,800,600));

    c.reset();
    c.set_expected(800,600,320,240);
    auto invalid=fovea;invalid.depth_x=10;invalid.depth_width=400;
    c.observe(invalid);
    assert(!c.choose().source[0]);
}

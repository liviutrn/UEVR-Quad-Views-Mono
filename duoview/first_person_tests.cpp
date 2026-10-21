#include "DuoViewFirstPerson.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <cstring>
#include <limits>
#include <span>

using namespace uevr::duoview::foreground;

int main() {
    std::array<std::byte,0x240> bytes{};
    const auto fill=[&](size_t p,float fov,float desired,float factor,float scale,uint8_t enabled) {
        std::memcpy(bytes.data()+p,&fov,4);
        std::memcpy(bytes.data()+p+4,&desired,4);
        std::memcpy(bytes.data()+p+8,&factor,4);
        std::memcpy(bytes.data()+p+12,&scale,4);
        std::memcpy(bytes.data()+p+16,&enabled,1);
    };
    fill(0x74,90.f,90.f,1.45f,.6f,1);
    auto slot=find_slot(bytes);
    assert(slot && slot->correction_offset==0x7c);
    assert(correct(bytes,*slot,.5f));
    float corrected{};
    std::memcpy(&corrected,bytes.data()+0x7c,4);
    assert(std::fabs(corrected-.725f)<1e-6f);
    assert(!correct(bytes,*slot,0.f));
    assert(!correct(bytes,*slot,.329f));
    assert(!correct(bytes,*slot,3.001f));
    assert(correct(bytes,*slot,3.f)); // maximum permitted scale
    assert(correct(bytes,*slot,.33f)); // minimum permitted scale
    assert(correct(bytes,*slot,1.f)); // neutral
    assert(!correct(bytes,*slot,std::numeric_limits<float>::quiet_NaN()));
    // The immediately adjacent scale, flags and world FOV are NOT modified.
    auto untouched=find_slot(bytes);
    assert(untouched && untouched->fields.first_person_scale==.6f);
    assert(untouched->fields.scene_fov==90.f && untouched->fields.desired_fov==90.f);
    fill(0x90,90.f,90.f,1.1f,.65f,1);
    assert(!find_slot(bytes)); // ambiguity never permits an engine write
    bytes.fill(std::byte{0});
    fill(0x74,90.f,90.f,1.45f,.6f,0);
    assert(!find_slot(bytes)); // tagged first-person disabled
    bytes.fill(std::byte{0});
    fill(0x74,90.f,90.f,1.45f,10.f,1);
    assert(!find_slot(bytes)); // impossible scale
    bytes.fill(std::byte{0});
    fill(0x74,90.f,90.f,1.45f,.6f,1);
    assert(!find_slot(std::span<const std::byte>{bytes.data(),0x78}));
    assert(!correct(std::span<std::byte>{bytes.data(),0x70},
                   Slot{0x7c,{90.f,90.f,1.45f,.6f,1}},.5f));
    return 0;
}

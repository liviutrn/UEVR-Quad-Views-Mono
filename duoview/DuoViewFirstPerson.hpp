#pragma once
// DuoView experimental UE5.5 foreground-only FOV harmonization.
// The native UE5.5 FSceneViewInitOptions layout has consecutive FOV,
// DesiredFOV, and FFirstPersonParameters{correction,scale,enabled}.
// We do not assume a fixed offset into a proprietary SDK structure.
// The caller supplies an independently validated bounded memory range after
// the known StereoPass member, and this scanner refuses ambiguous signatures.
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <optional>
#include <span>

namespace uevr::duoview::foreground {
struct Fields {
    float scene_fov{};
    float desired_fov{};
    float correction{};
    float first_person_scale{};
    uint8_t use_parameters{};
};
struct Slot {
    size_t correction_offset{};
    Fields fields{};
};
inline std::optional<Slot> find_slot(std::span<const std::byte> bytes) {
    std::optional<Slot> only{};
    // Search only a small area AFTER the validated StereoPass field.
    // A false positive or multiple matches must never write into UE memory.
    for (size_t p = 4; p + 17 <= bytes.size(); p += 4) {
        Fields f{};
        std::memcpy(&f.scene_fov, bytes.data()+p, 4);
        std::memcpy(&f.desired_fov, bytes.data()+p+4, 4);
        std::memcpy(&f.correction, bytes.data()+p+8, 4);
        std::memcpy(&f.first_person_scale, bytes.data()+p+12, 4);
        std::memcpy(&f.use_parameters, bytes.data()+p+16, 1);
        if (!std::isfinite(f.scene_fov) || f.scene_fov<35.f || f.scene_fov>150.f ||
            !std::isfinite(f.desired_fov) || f.desired_fov<35.f || f.desired_fov>150.f ||
            std::abs(f.scene_fov-f.desired_fov)>30.f ||
            !std::isfinite(f.correction) || f.correction<.1f || f.correction>4.f ||
            !std::isfinite(f.first_person_scale) || f.first_person_scale<.01f ||
            f.first_person_scale>1.01f || f.use_parameters!=1u) continue;
        if (only) return {}; // ambiguous memory is NEVER writable
        only = Slot{p+8,f};
    }
    return only;
}
inline bool correct(std::span<std::byte> bytes, const Slot& slot, float factor) {
    if (!std::isfinite(factor) || factor < .2f || factor > 3.f ||
        slot.correction_offset+sizeof(float)>bytes.size()) return false;
    const float before=slot.fields.correction;
    if (!std::isfinite(before) || before<.1f || before>4.f) return false;
    const float after=before*factor;
    if (!std::isfinite(after) || after<.05f || after>8.f) return false;
    // Modify ONLY the UE first-person morph factor; never the world projection,
    // view rect, weapon actor, temporal history or compositor parameters.
    std::memcpy(bytes.data()+slot.correction_offset,&after,sizeof(after));
    return true;
}
} // namespace uevr::duoview::foreground

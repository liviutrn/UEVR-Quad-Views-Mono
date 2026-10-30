#pragma once
// Build46 experimental depth capture fingerprint / manual pin policy.
// Source resource identity + rank of its submitted pass within ONE Present interval.
// This is not semantic eye/frame producer authentication. No stale GPU copies are reused.
#include <cstdint>
#include <vector>
#include <span>
#include <algorithm>
#include <limits>

namespace duoview::depthpin {
struct Fingerprint {
    uintptr_t source{};     // non-owning identity: NEVER dereference
    uint32_t stage{};       // ordered write rank for this source during the interval
    uint32_t viewport_x{}, viewport_y{}, viewport_w{}, viewport_h{};
    uint32_t texture_w{}, texture_h{}, format{};
    uint64_t generation{}; // invalidated by layout/device/observer reset
    bool operator==(const Fingerprint&) const = default;
};
struct Observation {
    uintptr_t source{};
    uint32_t viewport_x{}, viewport_y{}, viewport_w{}, viewport_h{};
    uint32_t texture_w{}, texture_h{}, format{};
    uint32_t stage_hint{};  // rank of recognized barriers, including budget-skipped passes
};
// Inputs MUST be sorted by (source identity, capture serial) and contain only
// currently submitted/eligible copies. stage_hint was stamped at the barrier,
// NOT inferred from the eligible set. No semantic Unreal pass attribution.
inline std::vector<Fingerprint> fingerprint(std::span<const Observation> observations, uint64_t generation) {
    std::vector<Fingerprint> result;
    result.reserve(observations.size());
    uintptr_t last=0; uint32_t rank=0; bool first=true;
    for (const auto& o : observations) {
        if (first || o.source!=last) {rank=0;last=o.source;first=false;}
        ++rank;
        result.push_back({o.source,o.stage_hint?o.stage_hint:rank,o.viewport_x,o.viewport_y,o.viewport_w,o.viewport_h,
                          o.texture_w,o.texture_h,o.format,generation});
    }
    return result;
}
struct Pin {bool enabled{}; Fingerprint key{};};
struct RolePins {Pin primary, backup; bool backup_latched{};};
// When an explicitly pinned source momentarily vanishes, the renderer must
// NOT bounce stereo -> mono -> stereo every frame. Resume ONLY after a
// sustained run of valid fresh pairs. No old depth texture is ever reused.
struct RecoveryGate {
    bool waiting{}; uint64_t last_epoch{}; uint32_t consecutive{};
    Fingerprint left{}, right{};
};
inline void lost_pair(RecoveryGate& gate) {
    gate=RecoveryGate{}; gate.waiting=true;
}
inline bool allow_fresh_pair(RecoveryGate& gate,uint64_t epoch,uint32_t threshold=8) {
    if(!gate.waiting)return true;
    if(epoch==0)return false;
    if(epoch!=gate.last_epoch) {
        gate.consecutive=(gate.last_epoch && epoch==gate.last_epoch+1)
            ? gate.consecutive+1 : 1;
        gate.last_epoch=epoch;
    }
    if(gate.consecutive>=threshold) {gate={};return true;}
    return false;
}

// Identity-aware recovery: every eligible Present interval must contain the
// SAME full fresh pair. Switching the Auto partner during the hold restarts it.
// This is a producer-resource fingerprint, NOT a UE frame/eye assertion.
inline bool allow_stable_fresh_pair(RecoveryGate& gate, uint64_t epoch,
                                   const Fingerprint& left, const Fingerprint& right,
                                   uint32_t threshold=8) {
    if(!gate.waiting)return true;
    if(!epoch || !left.source || !right.source)return false;
    if(epoch != gate.last_epoch) {
        const bool continues = gate.last_epoch && epoch == gate.last_epoch+1 &&
            gate.left == left && gate.right == right;
        gate.consecutive = continues ? gate.consecutive+1 : 1;
        gate.left=left; gate.right=right; gate.last_epoch=epoch;
    } else if(gate.left != left || gate.right != right) {
        // More than one attempted selection in the same Present interval must
        // not allow a transient alternate to count as a stable frame.
        gate.left=left;gate.right=right;gate.consecutive=0;
    }
    if(gate.consecutive >= threshold) {gate={};return true;}
    return false;
}

inline int find_exact(std::span<const Fingerprint> list, const Pin& pin) {
    if (!pin.enabled) return 0;
    for (size_t i=0;i<list.size();++i)
        if (list[i]==pin.key && i<size_t((std::numeric_limits<int>::max)()-1))return int(i)+1;
    return -1; // unavailable; never substitute the current ordinal or stale texture
}
inline std::vector<int> alternatives(std::span<const Fingerprint> list, const RolePins& pins) {
    if (!pins.primary.enabled) return {0}; // explicitly Auto
    std::vector<int> out;
    const int first=find_exact(list,pins.primary);
    const int backup=find_exact(list,pins.backup);
    if (pins.backup_latched) {
        // Once a backup is used, do not automatically switch back and forth
        // as a transient primary returns. The user explicitly rearms primary.
        if (pins.backup.enabled && backup>0)out.push_back(backup);
    } else {
        if (first>0)out.push_back(first);
        if (pins.backup.enabled && backup>0 && backup!=first)out.push_back(backup);
    }
    return out; // empty means fail-closed, with no implicit Auto
}
inline bool set_pin(RolePins& pins, bool backup, std::span<const Fingerprint> list, int ordinal) {
    if (ordinal<=0 || size_t(ordinal)>list.size() || (backup && !pins.primary.enabled))return false;
    if (backup && pins.primary.key==list[size_t(ordinal-1)])return false;
    auto& slot=backup?pins.backup:pins.primary;
    slot={true,list[size_t(ordinal-1)]};
    if (!backup) {pins.backup={};pins.backup_latched=false;} // explicitly rearm primary
    return true;
}
inline void clear(RolePins& pins) {pins={};}
inline void commit_backup(RolePins& pins, int selected, std::span<const Fingerprint> list) {
    if (pins.backup.enabled && selected>0 &&
        selected==find_exact(list,pins.backup))pins.backup_latched=true;
}
}

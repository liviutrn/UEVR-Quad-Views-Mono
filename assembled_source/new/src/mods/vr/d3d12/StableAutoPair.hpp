#pragma once
// Auto stereo: keep the prior source+write-pass pair while its two NEW
// current-interval copies remain legal. This is stability, NOT provenance.
#include "DepthPinPolicy.hpp"
#include "DepthPolicy.hpp"
#include <array>
#include <span>
#include <vector>
#include <algorithm>
namespace duoview::depthpin {
inline stock_dibr::DepthPairChoice prefer_previous_pair(
    std::span<const stock_dibr::DepthShape> shapes,
    std::span<const Fingerprint> fingerprints,
    const std::array<std::uintptr_t,4>& prior,
    stock_dibr::DepthPairChoice proposed,
    uint32_t lw,uint32_t lh,uint32_t rw,uint32_t rh) {
    if (!proposed.valid || shapes.size()!=fingerprints.size() ||
        !prior[0] || !prior[2])return proposed;
    int left=0,right=0;
    for(size_t i=0;i<fingerprints.size();++i) {
        const auto& p=fingerprints[i];
        if(p.source==prior[0] && p.stage==prior[1]) left=int(i)+1;
        if(p.source==prior[2] && p.stage==prior[3]) right=int(i)+1;
    }
    if(!left || !right || left==right)return proposed;
    const auto checked=stock_dibr::choose_duoview_depth_pair(shapes,left,right,lw,lh,rw,rh);
    return checked.valid?checked:proposed;
}
// Full-fingerprint retention. The old four-word hint is insufficient when a
// source pointer is recycled with new layout, format, or observer generation.
inline stock_dibr::DepthPairChoice prefer_previous_pair_exact(
    std::span<const stock_dibr::DepthShape> shapes,
    std::span<const Fingerprint> fingerprints,
    const std::array<Fingerprint,2>& prior,
    stock_dibr::DepthPairChoice proposed,
    uint32_t lw,uint32_t lh,uint32_t rw,uint32_t rh) {
    if(!proposed.valid || shapes.size()!=fingerprints.size() ||
       !prior[0].source || !prior[1].source)return proposed;
    int left=0,right=0;
    for(size_t i=0;i<fingerprints.size();++i) {
        if(fingerprints[i]==prior[0])left=int(i)+1;
        if(fingerprints[i]==prior[1])right=int(i)+1;
    }
    if(!left || !right || left==right)return proposed;
    const auto validated=stock_dibr::choose_duoview_depth_pair(
        shapes,left,right,lw,lh,rw,rh);
    return validated.valid?validated:proposed;
}
inline stock_dibr::DepthPairChoice prefer_allowed_previous_pair_exact(
    std::span<const stock_dibr::DepthShape> shapes,
    std::span<const Fingerprint> fingerprints,
    const std::array<Fingerprint,2>& prior,
    stock_dibr::DepthPairChoice proposed,
    std::span<const int> permitted_left,
    std::span<const int> permitted_right,
    uint32_t lw,uint32_t lh,uint32_t rw,uint32_t rh) {
    const auto retained=prefer_previous_pair_exact(shapes,fingerprints,prior,proposed,lw,lh,rw,rh);
    const auto permitted=[](std::span<const int> choices,size_t index) {
        return std::find(choices.begin(),choices.end(),0)!=choices.end() ||
               std::find(choices.begin(),choices.end(),int(index+1))!=choices.end();
    };
    return retained.valid && permitted(permitted_left,retained.left) &&
        permitted(permitted_right,retained.right) ? retained : proposed;
}
// Mixed manual/Auto: retain the prior automatic partner only when BOTH sides
// are still permitted by the current manual primary/backup policy. A backup
// latch must never be overridden by sticky-pair logic.
inline stock_dibr::DepthPairChoice prefer_allowed_previous_pair(
    std::span<const stock_dibr::DepthShape> shapes,
    std::span<const Fingerprint> fingerprints,
    const std::array<std::uintptr_t,4>& prior,
    stock_dibr::DepthPairChoice proposed,
    std::span<const int> permitted_left,
    std::span<const int> permitted_right,
    uint32_t lw,uint32_t lh,uint32_t rw,uint32_t rh) {
    const auto retained=prefer_previous_pair(shapes,fingerprints,prior,proposed,lw,lh,rw,rh);
    const auto permitted=[](std::span<const int> choices,size_t index) {
        return std::find(choices.begin(),choices.end(),0)!=choices.end() ||
               std::find(choices.begin(),choices.end(),int(index+1))!=choices.end();
    };
    return retained.valid && permitted(permitted_left,retained.left) &&
        permitted(permitted_right,retained.right) ? retained : proposed;
}
}

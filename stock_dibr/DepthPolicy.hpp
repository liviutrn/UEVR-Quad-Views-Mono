#pragma once
#include <cstdint>
#include <cmath>
#include <cstddef>
#include <span>

namespace stock_dibr {
enum class Layout : uint32_t { Invalid, Eye, Packed };
// UE aligns internal render allocations to a few pixels. Compare physical
// aspect, not output resolution; DLSS is allowed to change pixel density.
inline Layout layout(uint64_t w, uint32_t h, uint64_t packed_w, uint32_t out_h) {
    if (!w || !h || !packed_w || !out_h || packed_w % 2 || w > 32768 || h > 32768)
        return Layout::Invalid;
    const double scale = double(h) / out_h;
    if (scale < .20 || scale > 1.01) return Layout::Invalid;
    const double eye = double(packed_w / 2) * scale;
    const double eye_error = std::abs(double(w) - eye);
    const double packed_error = std::abs(double(w) - 2 * eye);
    const double tolerance = 8.0;
    if (eye_error <= tolerance && eye_error < packed_error) return Layout::Eye;
    if (packed_error <= tolerance) return Layout::Packed;
    return Layout::Invalid;
}
inline bool completed(uint64_t value, uint64_t wanted) {
    return wanted && value != UINT64_MAX && value >= wanted;
}
// Discovery filter for an explicitly supplied DuoView source viewport. The
// stock DIBR 20%-of-HMD floor is wrong for 20% periphery at 50% DLSS (10%).
// Shape compatibility does NOT establish camera, frame, or render-stage identity.
inline bool duoview_depth_shape(double w,double h,uint32_t source_w,uint32_t source_h) {
    if(!source_w || !source_h || !std::isfinite(w) || !std::isfinite(h) ||
       w<8 || h<8 || w>32768 || h>32768)return false;
    const double scale=h/source_h;
    return scale>=.10 && scale<=1.01 && std::abs(w-source_w*scale)<=2.0;
}
inline bool capture_boundary_supported(bool duoview,bool before_depth_write) {
    return !duoview || before_depth_write;
}
struct DepthShape { double width{},height{};uint64_t serial{}; };
struct DepthPairChoice { size_t left{},right{};bool valid{}; };
inline DepthPairChoice choose_duoview_depth_pair(std::span<const DepthShape> shapes,
        int left_manual,int right_manual,uint32_t lw,uint32_t lh,uint32_t rw,uint32_t rh) {
    const size_t n=shapes.size();
    if(n<2 || left_manual<0 || right_manual<0 || size_t(left_manual)>n || size_t(right_manual)>n)return {};
    if(left_manual && right_manual) {
        if(left_manual==right_manual)return {};
        return {size_t(left_manual-1),size_t(right_manual-1),true};
    }
    DepthPairChoice best{};double best_score=1.e30;uint64_t latest{};
    for(size_t a=0;a<n;++a)for(size_t b=0;b<n;++b) {
        if(a==b || (left_manual && a!=size_t(left_manual-1)) ||
           (right_manual && b!=size_t(right_manual-1)))continue;
        if(!duoview_depth_shape(shapes[a].width,shapes[a].height,lw,lh) ||
           !duoview_depth_shape(shapes[b].width,shapes[b].height,rw,rh))continue;
        const double sl=shapes[a].height/lh,sr=shapes[b].height/rh;
        const double mismatch=std::abs(sl-sr)/(sl+sr);
        if(mismatch>.05)continue; // require one coherent render scale for Auto
        const double score=mismatch+
            std::abs(shapes[a].width/lw-sl)+std::abs(shapes[b].width/rw-sr);
        const auto age=shapes[a].serial<shapes[b].serial?shapes[a].serial:shapes[b].serial;
        if(score<best_score || (score==best_score && age>latest)) {
            best={a,b,true};best_score=score;latest=age;
        }
    }
    return best;
}
}

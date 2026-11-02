#pragma once
// v210: manual DLSS-SR depth candidate catalogue. Metadata only: never retain
// borrowed NGX depth pointers. No inference that evaluation order == fovea.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <mutex>
#include <vector>

namespace uevr::duoview::ngx {
struct DepthCandidate {
    uintptr_t feature{};
    uint64_t serial{}, evaluation{}, last_seen_ms{};
    uint32_t output_width{}, output_height{}, render_width{}, render_height{};
    uint32_t depth_width{}, depth_height{}, depth_x{}, depth_y{}, format{}, feature_kind{};
    float jitter_x{}, jitter_y{};
    bool create_observed{}, depth_present{}, color_present{};
};
class ManualDepthCandidates final {
    mutable std::mutex lock_;
    std::vector<DepthCandidate> observed_;
    std::array<uintptr_t,3> selected_{}; // handle, output width, output height
    uint64_t next_serial_{};
    static uint64_t now_ms() {
        return uint64_t(std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
    }
public:
    void observe(DepthCandidate x) {
        if (!x.feature || !x.output_width || !x.output_height || !x.depth_present ||
            !x.depth_width || !x.depth_height) return;
        std::scoped_lock guard(lock_);
        const auto same=[&](const DepthCandidate& y) {
            return y.feature==x.feature && y.output_width==x.output_width &&
                   y.output_height==x.output_height;
        };
        x.last_seen_ms=now_ms();
        auto it=std::find_if(observed_.begin(),observed_.end(),same);
        if(it!=observed_.end()) {
            x.serial=it->serial;
            *it=x;
        } else {
            x.serial=++next_serial_;
            if(observed_.size()>=24) {
                const auto oldest=std::min_element(observed_.begin(),observed_.end(),
                    [](const auto& a,const auto& b){return a.last_seen_ms<b.last_seen_ms;});
                if(oldest!=observed_.end()) {
                    if(selected_==std::array<uintptr_t,3>{oldest->feature,oldest->output_width,oldest->output_height})
                        selected_={};
                    observed_.erase(oldest);
                }
            }
            observed_.push_back(x);
        }
    }
    void released(uintptr_t feature) {
        std::scoped_lock guard(lock_);
        if(selected_[0]==feature)selected_={};
        observed_.erase(std::remove_if(observed_.begin(),observed_.end(),
            [=](const auto& c){return c.feature==feature;}),observed_.end());
    }
    std::vector<DepthCandidate> browse() const {
        std::scoped_lock guard(lock_);
        auto result=observed_;
        std::sort(result.begin(),result.end(),[](const auto& a,const auto& b) {
            if(a.output_width!=b.output_width)return a.output_width>b.output_width;
            if(a.output_height!=b.output_height)return a.output_height>b.output_height;
            return a.serial<b.serial;
        });
        return result;
    }
    bool pin(uintptr_t feature,uint32_t w,uint32_t h) {
        std::scoped_lock guard(lock_);
        const auto i=std::find_if(observed_.begin(),observed_.end(),[=](const auto& c){
            return c.feature==feature && c.output_width==w && c.output_height==h;
        });
        if(i==observed_.end() || now_ms()-i->last_seen_ms>3000 ||
           (i->create_observed && i->feature_kind!=1u)) return false;
        selected_={feature,w,h};
        return true;
    }
    void clear() {std::scoped_lock guard(lock_);selected_={};}
    void reset() {std::scoped_lock guard(lock_);observed_.clear();selected_={};}
    std::array<uintptr_t,3> selected() const {
        std::scoped_lock guard(lock_);return selected_;
    }
    bool matches(uintptr_t feature,uint32_t w,uint32_t h) const {
        std::scoped_lock guard(lock_);
        if(selected_!=std::array<uintptr_t,3>{feature,w,h})return false;
        const auto i=std::find_if(observed_.begin(),observed_.end(),[=](const auto& c){
            return c.feature==feature && c.output_width==w && c.output_height==h;
        });
        return i!=observed_.end() && now_ms()-i->last_seen_ms<=3000;
    }
    uint64_t age_ms(const DepthCandidate& c) const {
        const auto n=now_ms();
        return n>=c.last_seen_ms ? n-c.last_seen_ms : 0;
    }
};
inline ManualDepthCandidates& candidates() {
    static ManualDepthCandidates singleton;
    return singleton;
}
} // namespace uevr::duoview::ngx

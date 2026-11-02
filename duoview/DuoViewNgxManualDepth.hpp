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
    std::array<uint32_t,4> expected_{}; // Fovea W/H, periphery W/H from immutable DuoView packet.
    std::array<uintptr_t,3> auto_selected_{};
    static std::array<uintptr_t,3> key(const DepthCandidate& c) {
        return {c.feature,c.output_width,c.output_height};
    }
    static bool usable(const DepthCandidate& c, uint64_t t) {
        return c.depth_present && c.color_present && c.render_width && c.render_height &&
            !(!c.create_observed ? false : c.feature_kind!=1u) &&
            uint64_t(c.depth_x)+c.render_width<=c.depth_width &&
            uint64_t(c.depth_y)+c.render_height<=c.depth_height &&
            t>=c.last_seen_ms && t-c.last_seen_ms<=3000;
    }
    static uint64_t now_ms() {
        return uint64_t(std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
    }
public:
    // Expected dimensions are gathered from the actual frozen packet in the
    // OpenXR compositor, never from assumed HMD scale or max texture allocation.
    void set_expected(uint32_t fw, uint32_t fh, uint32_t pw, uint32_t ph) {
        std::scoped_lock guard(lock_);
        const std::array<uint32_t,4> next{fw,fh,pw,ph};
        if (next!=expected_) {
            expected_=next;
            auto_selected_={}; // resolution or crop change requires fresh match
            if(selected_[0] && (selected_[1]!=fw || selected_[2]!=fh))selected_={};
        }
    }
    std::array<uint32_t,4> expected() const {
        std::scoped_lock guard(lock_);
        return expected_;
    }
    struct Pick {
        std::array<uintptr_t,3> source{};
        bool manual{}, exact{}, ambiguous{}, fallback_largest{};
        uint32_t candidates{};
    };
    Pick choose() {
        std::scoped_lock guard(lock_);
        Pick out{};
        const auto now=now_ms();
        std::vector<const DepthCandidate*> live;
        for(const auto& c:observed_)if(usable(c,now))live.push_back(&c);
        out.candidates=uint32_t(live.size());
        for(const auto* c:live)if(selected_==key(*c)) {
            out.source=selected_;out.manual=true;
            out.exact=c->output_width==expected_[0] && c->output_height==expected_[1];
            return out;
        }
        // Manual locks are never silently replaced by auto; release/resize
        // invalidates them explicitly so the user can see the loss.
        if(selected_[0])return out;
        if(!expected_[0] || !expected_[1])return out;
        if(expected_[0]==expected_[2] && expected_[1]==expected_[3]) {
            out.ambiguous=true;return out; // equal-size fovea/periphery
        }
        std::vector<const DepthCandidate*> exact;
        for(const auto* c:live)
            if(c->output_width==expected_[0] && c->output_height==expected_[1])
                exact.push_back(c);
        if(exact.empty()) {
            // Biggest texture is only a suggestion without verified shape.
            // Do not automatically apply a heuristic to the sharpening shader.
            return out;
        }
        if(auto_selected_[0])for(const auto* c:exact)if(key(*c)==auto_selected_) {
            out.source=auto_selected_;out.exact=true;return out;
        }
        if(exact.size()!=1) {
            out.ambiguous=true;auto_selected_={};
            return out;
        }
        out.source=auto_selected_=key(*exact.front());
        out.exact=true;
        return out;
    }
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
                    if(auto_selected_==key(*oldest))auto_selected_={};
                    observed_.erase(oldest);
                }
            }
            observed_.push_back(x);
        }
    }
    void released(uintptr_t feature) {
        std::scoped_lock guard(lock_);
        if(selected_[0]==feature)selected_={};
        if(auto_selected_[0]==feature)auto_selected_={};
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
        auto_selected_={};
        return true;
    }
    void clear() {std::scoped_lock guard(lock_);selected_={};auto_selected_={};}
    void reset() {std::scoped_lock guard(lock_);observed_.clear();selected_={};auto_selected_={};expected_={};}
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

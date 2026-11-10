# Part D - Files ADDED to the tree by the patch chain (full source, B42.1 generated tree)


## FILE src/mods/vr/DuoViewConfig.hpp (231 lines)
```cpp
#pragma once
// Stage 8 — latch all DuoView settings/gaze exactly once per render frame.
// This header deliberately has no UEVR/UESDK/D3D/OpenXR dependency.
// Changes from ImGui/config reload cannot split the two UE views or the
// subsequent shader blend into different crop positions or densities.
#include "DuoViewFrame.hpp"
#include "DuoViewGaze.hpp"
#include <cstdint>
#include <mutex>
#include <optional>

namespace uevr::duoview {

struct Settings {
    float crop_width{.50f}, crop_height{.50f};
    float peripheral_scale{.20f};
    float foveal_density{1.f};
    float feather_fraction{.08f};
    bool debug_border{};
    bool eye_tracked{true};
    uint32_t fovea_view{};
    uint32_t diagnostic_view{}; // 0 composite, 1 periphery, 2 fovea
    bool gpu_timing{};
    bool direct_xr_output{};
    bool stabilize_crop{};
    float guard_fraction{.05f};
    bool independent_shading{};
    // Keep DuoView's proven Native two-target capture in both modes.
    // OFF retains the stock UE SECONDARY shading pass instead of relabeling PRIMARY.
    bool native_fix_same_pass{true};
    uint32_t gaze_quant_pixels{2}; // 0 disables snapping; other values step in fovea pixels.
    int32_t gaze_hold_ms{350};
    int32_t gaze_reacquire_samples{2};
    float gaze_offset_u{}, gaze_offset_v{};
    // Nonlinear gaze response: hold or slowly follow small motion, but follow
    // genuine saccades 1:1. All distances are fractions of the full view.
    float gaze_micro_gain{0.f};        // 0=locked, 1=full follow below breakout
    float gaze_breakout_radius{.035f}; // when farther from locked crop, go 1:1
    float gaze_still_radius{.008f};    // per-sample motion treated as stationary
    uint32_t gaze_relock_samples{3};  // quiet samples before leaving fast tracking
};
// Resolve persisted UI controls field by field. Unlike the strict ConfigLatch,
// one bad slider must not veto eye tracking, shading, position, or other sliders.
// Retain each rejected *field* so the UI can explain it; never silently resize
// Native sources or reinterpret a failed input as a successful renderer change.
enum UiReject : uint32_t {
    reject_width=1u<<0, reject_height=1u<<1, reject_periphery=1u<<2,
    reject_density=1u<<3, reject_feather=1u<<4, reject_fovea_view=1u<<5,
    reject_diagnostic=1u<<6, reject_guard=1u<<7, reject_quant=1u<<8,
    reject_hold=1u<<9, reject_reacquire=1u<<10, reject_offset_u=1u<<11,
    reject_offset_v=1u<<12, reject_micro=1u<<13,
    reject_breakout=1u<<14, reject_still=1u<<15, reject_relock=1u<<16
};
struct UiReconciled {
    Settings settings{};
    uint32_t rejected{};
};
inline UiReconciled reconcile_ui_settings(const Settings& requested,
                                         const Settings& current) {
    UiReconciled result{current, 0};
    auto& out=result.settings;
    const auto valid=[](float x,float lo,float hi) {
        return std::isfinite(x) && x>=lo && x<=hi;
    };
    const auto valid_quality=[](const Settings& x) {
        // Both UE Native source textures are at full output-eye dimensions.
        // A cropped view must fit the existing source, not just the atlas.
        return x.crop_width*x.foveal_density<=1.f &&
               x.crop_height*x.foveal_density<=1.f &&
               make_layout(1024,1024,x.crop_width,x.crop_height,
                           x.peripheral_scale,x.foveal_density).has_value();
    };
    // When multiple quality sliders change together, honor the full valid tuple
    // first (such as reducing density while increasing crop width).
    if (valid_quality(requested)) {
        out.crop_width=requested.crop_width;
        out.crop_height=requested.crop_height;
        out.foveal_density=requested.foveal_density;
        out.peripheral_scale=requested.peripheral_scale;
    } else {
        // Otherwise isolate invalid fields. A failed density must not prevent
        // a valid width, height, peripheral or gaze/visual setting from applying.
        const auto quality_field=[&](float value, float lo, float hi,
                                     uint32_t mask, float Settings::* field) {
            Settings attempt=out;
            attempt.*field=value;
            if (valid(value,lo,hi) && valid_quality(attempt)) {
                out.*field=value;
            } else {
                result.rejected|=mask;
            }
        };
        quality_field(requested.crop_width,.05f,1.f,reject_width,&Settings::crop_width);
        quality_field(requested.crop_height,.05f,1.f,reject_height,&Settings::crop_height);
        quality_field(requested.foveal_density,.25f,4.f,reject_density,&Settings::foveal_density);
        quality_field(requested.peripheral_scale,.05f,.50f,reject_periphery,&Settings::peripheral_scale);
    }
    // Boolean controls are inherently valid and must always apply.
    out.debug_border=requested.debug_border;
    out.eye_tracked=requested.eye_tracked;
    out.gpu_timing=requested.gpu_timing;
    out.direct_xr_output=requested.direct_xr_output;
    out.stabilize_crop=requested.stabilize_crop;
    out.independent_shading=requested.independent_shading;
    out.native_fix_same_pass=requested.native_fix_same_pass;
    const auto scalar=[&](float value,float lo,float hi,uint32_t mask,
                          float Settings::* field) {
        if (valid(value,lo,hi)) out.*field=value;
        else result.rejected|=mask;
    };
    const auto integer=[&](int32_t value,int32_t lo,int32_t hi,uint32_t mask,
                           int32_t Settings::* field) {
        if (value>=lo&&value<=hi) out.*field=value;
        else result.rejected|=mask;
    };
    const auto unsigned_int=[&](uint32_t value,uint32_t lo,uint32_t hi,
                                uint32_t mask,uint32_t Settings::* field) {
        if (value>=lo&&value<=hi) out.*field=value;
        else result.rejected|=mask;
    };
    scalar(requested.feather_fraction,0.f,.45f,reject_feather,&Settings::feather_fraction);
    scalar(requested.guard_fraction,0.f,.05f,reject_guard,&Settings::guard_fraction);
    scalar(requested.gaze_offset_u,-.25f,.25f,reject_offset_u,&Settings::gaze_offset_u);
    scalar(requested.gaze_offset_v,-.25f,.25f,reject_offset_v,&Settings::gaze_offset_v);
    scalar(requested.gaze_micro_gain,0.f,1.f,reject_micro,&Settings::gaze_micro_gain);
    unsigned_int(requested.fovea_view,0u,1u,reject_fovea_view,&Settings::fovea_view);
    unsigned_int(requested.diagnostic_view,0u,2u,reject_diagnostic,&Settings::diagnostic_view);
    unsigned_int(requested.gaze_quant_pixels,0u,16u,reject_quant,&Settings::gaze_quant_pixels);
    unsigned_int(requested.gaze_relock_samples,1u,10u,reject_relock,&Settings::gaze_relock_samples);
    integer(requested.gaze_hold_ms,50,2000,reject_hold,&Settings::gaze_hold_ms);
    integer(requested.gaze_reacquire_samples,1,4,reject_reacquire,&Settings::gaze_reacquire_samples);
    // Breakout/stillness form one inequality. Accept the pair atomically when
    // possible; when not, keep independent controls live and mark the conflict.
    const bool good_breakout=valid(requested.gaze_breakout_radius,.005f,.25f);
    const bool good_still=valid(requested.gaze_still_radius,0.f,.05f);
    if (good_breakout && good_still &&
        requested.gaze_still_radius<requested.gaze_breakout_radius) {
        out.gaze_breakout_radius=requested.gaze_breakout_radius;
        out.gaze_still_radius=requested.gaze_still_radius;
    } else {
        if (good_breakout &&
            out.gaze_still_radius<requested.gaze_breakout_radius) {
            out.gaze_breakout_radius=requested.gaze_breakout_radius;
        } else result.rejected|=reject_breakout;
        if (good_still &&
            requested.gaze_still_radius<out.gaze_breakout_radius) {
            out.gaze_still_radius=requested.gaze_still_radius;
        } else result.rejected|=reject_still;
    }
    return result;
}
struct FrameConfig {
    FrameKey key{};
    Layout layout{};
    UV gaze{};
    Settings settings{};
    uint64_t settings_revision{};
};
class ConfigLatch {
public:
    bool set_settings(Settings proposed) {
        std::scoped_lock lock{mutex_};
        if (!std::isfinite(proposed.feather_fraction) ||
            proposed.feather_fraction < 0.f || proposed.feather_fraction > .45f ||
            proposed.fovea_view > 1 || proposed.diagnostic_view > 2 ||
            !std::isfinite(proposed.guard_fraction) || proposed.guard_fraction<0.f || proposed.guard_fraction>.05f ||
            proposed.gaze_quant_pixels>16 || proposed.gaze_hold_ms<50 || proposed.gaze_hold_ms>2000 ||
            proposed.gaze_reacquire_samples<1 || proposed.gaze_reacquire_samples>4 ||
            !std::isfinite(proposed.gaze_offset_u) || !std::isfinite(proposed.gaze_offset_v) ||
            proposed.gaze_offset_u<-.25f || proposed.gaze_offset_u>.25f ||
            proposed.gaze_offset_v<-.25f || proposed.gaze_offset_v>.25f ||
            !std::isfinite(proposed.gaze_micro_gain) || proposed.gaze_micro_gain<0.f ||
            proposed.gaze_micro_gain>1.f ||
            !std::isfinite(proposed.gaze_breakout_radius) || proposed.gaze_breakout_radius<.005f ||
            proposed.gaze_breakout_radius>.25f ||
            !std::isfinite(proposed.gaze_still_radius) || proposed.gaze_still_radius<0.f ||
            proposed.gaze_still_radius>.05f ||
            proposed.gaze_still_radius>=proposed.gaze_breakout_radius ||
            proposed.gaze_relock_samples<1 || proposed.gaze_relock_samples>10)
            return false;
        // Validate without trusting in-game UI, config files or Lua requests.
        if (!make_layout(1024,1024,proposed.crop_width,proposed.crop_height,
                         proposed.peripheral_scale,proposed.foveal_density)) return false;
        settings_ = proposed;
        ++revision_;
        return true;
    }

    Settings current_settings() const {
        std::scoped_lock lock{mutex_};
        return settings_;
    }

    // Same frame always gets *exactly* the same immutable parameters.
    // A different generation retires the old snapshot. Stale/duplicate
    // generation-frame keys are rejected rather than reusing a prior frame.
    std::optional<FrameConfig> for_frame(
        FrameKey key, uint32_t output_width, uint32_t output_height, UV gaze)
    {
        std::scoped_lock lock{mutex_};
        if (!key.generation || !key.frame) return {};
        if (cached_ && cached_->key == key) return cached_;
        if (key.generation < last_key_.generation ||
            (key.generation == last_key_.generation && key.frame <= last_key_.frame)) return {};
        if (!std::isfinite(gaze.u) || !std::isfinite(gaze.v) ||
            gaze.u < 0.f || gaze.u > 1.f || gaze.v < 0.f || gaze.v > 1.f) return {};
        auto layout=make_layout(output_width,output_height,
                                settings_.crop_width,settings_.crop_height,
                                settings_.peripheral_scale,settings_.foveal_density,
                                gaze.u,gaze.v);
        if (!layout || !layout_valid(*layout)) return {};
        FrameConfig next{key,*layout,gaze,settings_,revision_};
        cached_=next;
        last_key_=key;
        return next;
    }

    // On device reset / runtime recreation, caller increments generation.
    void retire() {
        std::scoped_lock lock{mutex_};
        cached_.reset();
        last_key_ = {};
    }
private:
    mutable std::mutex mutex_{};
    Settings settings_{};
    uint64_t revision_{1};
    FrameKey last_key_{};
    std::optional<FrameConfig> cached_{};
};
} // namespace uevr::duoview

```

## FILE src/mods/vr/DuoViewCropStability.hpp (130 lines)
```cpp
#pragma once
#include "DuoViewConfig.hpp"

namespace uevr::duoview {
class CropStability {
public:
    UV update(FrameKey key, uint32_t w, uint32_t h, const Settings& s,
              std::optional<UV> sample, uint64_t now) {
        if (generation_ != key.generation || width_ != w || height_ != h ||
            crop_width_ != s.crop_width || crop_height_ != s.crop_height ||
            density_ != s.foveal_density || source_ != s.fovea_view || now < last_tick_) {
            reset();
            generation_=key.generation; width_=w; height_=h;
            crop_width_=s.crop_width; crop_height_=s.crop_height;
            density_=s.foveal_density; source_=s.fovea_view;
        }
        last_tick_=now;
        if (!s.eye_tracked) {
            // Manual fovea position is independent of eye tracking and must
            // never be lost when tracking is disabled or unavailable.
            // Also clear the old gaze state so re-enabling starts clean.
            have_=false;
            fast_tracking_=false;
            last_gaze_.reset();
            quiet_samples_=0;
            return UV{
                std::clamp(.5f+s.gaze_offset_u, s.crop_width*.5f, 1.f-s.crop_width*.5f),
                std::clamp(.5f+s.gaze_offset_v, s.crop_height*.5f, 1.f-s.crop_height*.5f)
            };
        }
        // A PSVR2 blink or transient invalid sample must never reset the
        // crop to center. Keep the last accepted position until fresh tracking
        // returns, even if the Toolkit is temporarily unavailable.
        if (!sample) {
            // Tracking loss relocks the last valid crop. Recovery is handled
            // by the independent PSVR2 ray gate; never inject a center jump.
            fast_tracking_=false;
            quiet_samples_=0;
            last_gaze_.reset();
            return have_ ? center_ : UV{};
        }
        const UV adjusted{
            std::clamp(sample->u+s.gaze_offset_u,0.f,1.f),
            std::clamp(sample->v+s.gaze_offset_v,0.f,1.f)
        };
        if (!s.stabilize_crop) {
            fast_tracking_=false;
            quiet_samples_=0;
            last_gaze_.reset();
            have_=true;
            center_=adjusted;
            last_valid_=now;
            return center_;
        }
        const auto layout=make_layout(w,h,s.crop_width,s.crop_height,s.peripheral_scale,s.foveal_density);
        if (!layout) { reset(); return {}; }

        // Measure distance to the ACHIEVABLE crop center, not an unclamped
        // gaze outside the full crop's valid viewport bounds.
        const UV feasible{
            std::clamp(adjusted.u, s.crop_width*.5f, 1.f-s.crop_width*.5f),
            std::clamp(adjusted.v, s.crop_height*.5f, 1.f-s.crop_height*.5f)
        };
        UV target=feasible;
        if (have_) {
            const float delta_u=feasible.u-center_.u;
            const float delta_v=feasible.v-center_.v;
            const float travel=std::hypot(delta_u,delta_v);
            if (!fast_tracking_) {
                if (travel >= s.gaze_breakout_radius) {
                    // A genuine saccade has no smoothing: move 1:1 this frame
                    // and keep tracking the ensuing motion at full speed.
                    fast_tracking_=true;
                    quiet_samples_=0;
                } else {
                    // Tiny motion is locked (gain=0) or followed slowly.
                    // The existing guard is an optional hard noise floor.
                    const float guard=(std::min)(.02f,
                        (std::min)(s.crop_width,s.crop_height)*s.guard_fraction);
                    const float gain=travel<=guard ? 0.f : s.gaze_micro_gain;
                    target={center_.u+delta_u*gain, center_.v+delta_v*gain};
                }
            } else if (last_gaze_) {
                const float step=std::hypot(feasible.u-last_gaze_->u,
                                           feasible.v-last_gaze_->v);
                quiet_samples_=step<=s.gaze_still_radius ? quiet_samples_+1u : 0u;
                if (quiet_samples_>=s.gaze_relock_samples) {
                    fast_tracking_=false;
                    quiet_samples_=0;
                    // One stationary frame must not produce another gaze jump.
                    target=center_;
                }
            }
        }
        last_gaze_=feasible;
        const auto resolve=[&](float old, float gaze, float extent, uint32_t pixels) {
            const float maximum=(std::max)(0.f,1.f-extent);
            const float desired=std::clamp(gaze-extent*.5f,0.f,maximum);
            // Full-speed saccades bypass all crop-guard smoothing.
            // Stationary deadzone behavior was already applied in 2D above.
            // Snap the crop origin on a stable source-pixel grid.
            // Quantization is independent from the deadzone/guard control.
            const float pixel=pixels ? extent/static_cast<float>(pixels) : 0.f;
            const float step=s.gaze_quant_pixels && pixel>0.f
                ? static_cast<float>(s.gaze_quant_pixels)*pixel : 0.f;
            return step>0.f ? std::clamp(std::round(desired/step)*step,0.f,maximum) : desired;
        };
        origin_u_=resolve(origin_u_,target.u,s.crop_width,layout->fovea.width);
        origin_v_=resolve(origin_v_,target.v,s.crop_height,layout->fovea.height);
        center_={origin_u_+s.crop_width*.5f,origin_v_+s.crop_height*.5f};
        last_valid_=now; have_=true;
        return center_;
    }
    void reset() {
        have_=false;
        fast_tracking_=false;
        quiet_samples_=0;
        last_gaze_.reset();
        last_tick_=last_valid_=generation_=0;
    }
private:
    uint64_t generation_{}, last_tick_{}, last_valid_{};
    uint32_t width_{}, height_{}, source_{};
    float crop_width_{},crop_height_{},density_{},origin_u_{},origin_v_{};
    UV center_{};
    std::optional<UV> last_gaze_{};
    uint32_t quiet_samples_{};
    bool have_{},fast_tracking_{};
};
}

```

## FILE src/mods/vr/DuoViewD3D12.hpp (549 lines)
```cpp
#pragma once
#include "DuoViewConfig.hpp"
#include "DuoViewMonoCopyD3D12.hpp"
#include "DuoViewState.hpp"
#include "DuoViewShaderSource.hpp"
#include <memory>
#include <string>

namespace uevr::duoview::dx12 {
using Microsoft::WRL::ComPtr;
struct ShaderConstants {
    uint32_t output[2], atlas[2], fovea[4], periphery[4];
    float crop[4], feather;
    uint32_t border;
    uint32_t diagnostic;
    float reserved;
    uint32_t fovea_source_size[2], peripheral_source_size[2];
    uint32_t output_offset[2];
};
static_assert(sizeof(ShaderConstants) == 104);

class Compositor {
public:
    // Prebuild the per-slot PSO, descriptors and output outside OpenXR frame copy.
    // Called after swapchain images and their command contexts are constructed.
    bool prewarm(ID3D12Device* device, UINT width, UINT height, bool srgb, UINT64 frequency = 0) {
        if (!device || !width || !height || FAILED(device->GetDeviceRemovedReason())) return false;
        if (!prepare(device, width, height, srgb)) return false;
        setup_timing(device, frequency);
        return true;
    }
    // One instance per retired OpenXR command slot; descriptors/resources must
    // stay alive until that slot's GPU fence completes.
    bool record(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
                ID3D12Resource* atlas, ID3D12Resource* destination,
                D3D12_RESOURCE_STATES atlas_state, const FrameConfig& frame, UINT64 frequency = 0) {
        recorded_commands_ = false;
        if (!device || !cmd || !atlas || !destination || atlas == destination ||
            cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT ||
            FAILED(device->GetDeviceRemovedReason()) || !layout_valid(frame.layout)) return false;
        const auto source = atlas->GetDesc(), target = destination->GetDesc();
        const auto& l = frame.layout;
        if (source.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            target.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            source.Width != l.atlas_width || source.Height != l.atlas_height ||
            target.Width != l.atlas_width || target.Height != l.atlas_height ||
            source.DepthOrArraySize != 1 || target.DepthOrArraySize != 1 ||
            source.SampleDesc.Count != 1 || target.SampleDesc.Count != 1 ||
            source.SampleDesc.Quality != 0 || target.SampleDesc.Quality != 0 ||
            !(target.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) ||
            l.atlas_width / 2 > 16384 ||
            source.MipLevels != 1 || target.MipLevels != 1 ||
            (source.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) || !bgra8(target.Format)) return false;
        const auto format = srv_format(source.Format);
        if (format == DXGI_FORMAT_UNKNOWN) return false;
        ComPtr<ID3D12Device> sd, dd, cd;
        if (FAILED(atlas->GetDevice(IID_PPV_ARGS(&sd))) ||
            FAILED(destination->GetDevice(IID_PPV_ARGS(&dd))) ||
            FAILED(cmd->GetDevice(IID_PPV_ARGS(&cd))) ||
            sd.Get() != device || dd.Get() != device || cd.Get() != device) return false;
        const bool srgb = format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB || format == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
        if (!prepare(device, l.atlas_width / 2, l.atlas_height, srgb)) return false;
        const bool timed = frequency && frequency == frequency_ && queries_ && timestamps_;
        update_timing(timed,false);
        ShaderConstants constants{
            {l.atlas_width / 2, l.atlas_height}, {l.atlas_width, l.atlas_height},
            {l.fovea.x, l.fovea.y, l.fovea.width, l.fovea.height},
            {l.periphery.x, l.periphery.y, l.periphery.width, l.periphery.height},
            {l.u0, l.v0, l.u1, l.v1}, frame.settings.feather_fraction,
            frame.settings.debug_border ? 1u : 0u, frame.settings.diagnostic_view, 0.f};
        ensure_srvs(device,atlas,atlas,format);
        source_ = atlas;
        transition(cmd, atlas, atlas_state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        recorded_commands_ = true;
        if (timed) cmd->EndQuery(queries_.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0);
        ID3D12DescriptorHeap* heaps[]{srv_.Get()};
        cmd->SetDescriptorHeaps(1, heaps);
        cmd->SetGraphicsRootSignature(root_.Get());
        cmd->SetPipelineState(pipeline_.Get());
        cmd->SetGraphicsRootDescriptorTable(0, srv_gpu_start_);
        cmd->SetGraphicsRoot32BitConstants(1, sizeof(constants) / 4, &constants, 0);
        const D3D12_VIEWPORT viewport{0, 0, static_cast<float>(width_), static_cast<float>(height_), 0, 1};
        const D3D12_RECT rect{0, 0, static_cast<LONG>(width_), static_cast<LONG>(height_)};
        cmd->RSSetViewports(1, &viewport);
        cmd->RSSetScissorRects(1, &rect);
        const auto handle = rtv_cpu_start_;
        cmd->OMSetRenderTargets(1, &handle, FALSE, nullptr);
        cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        cmd->DrawInstanced(3, 1, 0, 0);
        transition(cmd, atlas, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, atlas_state);
        const auto copied = copy_composite_to_stereo(cmd, device, output_.Get(), destination,
            D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_RENDER_TARGET);
        if (timed) {
            cmd->EndQuery(queries_.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 1);
            cmd->ResolveQueryData(queries_.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0, 2, timestamps_.Get(), 0);
            timing_pending_ = true; pending_direct_xr_=false;
        }
        return copied;
    }
    // Direct Native Fix composition: keep Joey's exact UE rendering and
    // captures, but sample the existing view rectangles as two SRVs instead
    // of copying them to a third (doublewide) render texture first.
    // No new GPU resources or PSO are created in this XR command callback.
    bool record_native(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
                ID3D12Resource* primary, ID3D12Resource* secondary,
                ID3D12Resource* destination, D3D12_RESOURCE_STATES primary_state,
                D3D12_RESOURCE_STATES secondary_state, const ViewFrame& frame,
                std::shared_ptr<const void> packet_lifetime, UINT64 frequency = 0) {
        recorded_commands_=false;
        error_.clear();
        last_native_direct_xr_=false;
        const auto reject=[this](const char* reason) { error_=reason; return false; };
        if (!device || !cmd || !primary || !secondary || !destination ||
            primary==secondary || primary==destination || secondary==destination ||
            cmd->GetType()!=D3D12_COMMAND_LIST_TYPE_DIRECT ||
            FAILED(device->GetDeviceRemovedReason()) || !layout_valid(frame.config.layout))
            return reject("Invalid direct Native source resources or DuoView layout");
        const auto& layout=frame.config.layout;
        if (frame.config.settings.fovea_view>1)
            return reject("Invalid frozen Native fovea source index");
        if (device_.Get()!=device || width_!=layout.atlas_width/2 ||
            height_!=layout.atlas_height || !output_ || !native_pipeline_ ||
            !root_ || !srv_ || !rtv_)
            return reject("Direct Native compositor not prewarmed for frozen source extent");
        const auto p=primary->GetDesc(), s=secondary->GetDesc();
        const auto xrd=destination->GetDesc();
        last_native_source_extents_=
            (uint64_t(static_cast<uint32_t>(p.Width)&0xffffu)<<48)|
            (uint64_t(p.Height&0xffffu)<<32)|
            (uint64_t(static_cast<uint32_t>(s.Width)&0xffffu)<<16)|
            uint64_t(s.Height&0xffffu);
        const auto xr_format=srgb_ ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        // Render directly to the doublewide OpenXR texture only when its
        // render-target format matches the precompiled PSO. Keep a bit-for-bit
        // old compositor+copy fallback for incompatible swapchain formats.
        if (!stereo_destination_valid(xrd,width_,height_))
            return reject("Invalid Mono XR output dimensions, format, or render-target flags");
        const bool direct_xr=frame.config.settings.direct_xr_output &&
            xrd.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
            xrd.Width==static_cast<uint64_t>(width_)*2 && xrd.Height==height_ &&
            xrd.DepthOrArraySize==1 && xrd.MipLevels==1 &&
            xrd.SampleDesc.Count==1 && xrd.SampleDesc.Quality==0 &&
            (xrd.Flags&D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET)!=0 &&
            (xrd.Format==xr_format || xrd.Format==DXGI_FORMAT_B8G8R8A8_TYPELESS);
        const auto& pr=frame.config.settings.fovea_view==0 ? layout.fovea : layout.periphery;
        const auto& sr=frame.config.settings.fovea_view==1 ? layout.fovea : layout.periphery;
        const auto is_bgra_family=[](DXGI_FORMAT f) {
            return f==DXGI_FORMAT_B8G8R8A8_TYPELESS ||
                   f==DXGI_FORMAT_B8G8R8A8_UNORM ||
                   f==DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        };
        const auto valid_source=[&](const D3D12_RESOURCE_DESC& d,const Rect& rect) {
            return d.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
                is_bgra_family(d.Format) && d.Width>=rect.width && d.Height>=rect.height &&
                d.DepthOrArraySize==1 && d.MipLevels==1 &&
                d.SampleDesc.Count==1 && d.SampleDesc.Quality==0 &&
                true;
        };
        if (!valid_source(p,pr) || !valid_source(s,sr) ||
            p.Width>UINT32_MAX || s.Width>UINT32_MAX ||
            p.Height>UINT32_MAX || s.Height>UINT32_MAX)
            return reject("Direct Native source format / rect incompatible with frozen view");
        const auto sampling_format=srgb_
            ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB
            : DXGI_FORMAT_B8G8R8A8_UNORM;
        // A typed resource cannot legally be reinterpreted as a different
        // sRGB class. This deliberately fails closed rather than silently
        // changing shading, unlike a typeless Native Fix capture.
        if ((p.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            (s.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            (p.Format!=DXGI_FORMAT_B8G8R8A8_TYPELESS && p.Format!=sampling_format) ||
            (s.Format!=DXGI_FORMAT_B8G8R8A8_TYPELESS && s.Format!=sampling_format)) {
            // Uncommon sources can still be copied safely. Never turn an
            // optimization compatibility failure into a black headset frame.
            return record_native_gather(device,cmd,primary,secondary,destination,
                primary_state,secondary_state,frame,std::move(packet_lifetime),frequency);
        }
        ComPtr<ID3D12Device> pd,sd,dd,cd;
        if (FAILED(primary->GetDevice(IID_PPV_ARGS(&pd))) ||
            FAILED(secondary->GetDevice(IID_PPV_ARGS(&sd))) ||
            FAILED(destination->GetDevice(IID_PPV_ARGS(&dd))) ||
            FAILED(cmd->GetDevice(IID_PPV_ARGS(&cd))) ||
            pd.Get()!=device || sd.Get()!=device || dd.Get()!=device || cd.Get()!=device)
            return reject("Native primary/secondary/XR resource device mismatch");

        auto* fovea=frame.config.settings.fovea_view==0 ? primary : secondary;
        auto* periphery=frame.config.settings.fovea_view==0 ? secondary : primary;
        const auto& fd=frame.config.settings.fovea_view==0 ? p : s;
        const auto& vd=frame.config.settings.fovea_view==0 ? s : p;
        const auto fovea_state=frame.config.settings.fovea_view==0 ? primary_state : secondary_state;
        const auto peripheral_state=frame.config.settings.fovea_view==0 ? secondary_state : primary_state;

        ShaderConstants constants{
            {layout.atlas_width/2,layout.atlas_height},
            {layout.atlas_width,layout.atlas_height},
            {layout.fovea.x,layout.fovea.y,layout.fovea.width,layout.fovea.height},
            {layout.periphery.x,layout.periphery.y,layout.periphery.width,layout.periphery.height},
            {layout.u0,layout.v0,layout.u1,layout.v1},
            frame.config.settings.feather_fraction,
            frame.config.settings.debug_border ? 1u : 0u,
            frame.config.settings.diagnostic_view, 0.f,
            {static_cast<uint32_t>(fd.Width),fd.Height},
            {static_cast<uint32_t>(vd.Width),vd.Height}
        };
        ensure_srvs(device,fovea,periphery,sampling_format);
        // GPU lifetime remains bound to the exact retired OpenXR command slot,
        // never to whichever engine packet happens to arrive next.
        primary_reference_=primary; secondary_reference_=secondary;
        packet_lifetime_=std::move(packet_lifetime);
        const bool timed=frequency && frequency==frequency_ && queries_ && timestamps_;
        update_timing(timed,direct_xr);
        transition(cmd,fovea,fovea_state,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        transition(cmd,periphery,peripheral_state,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        recorded_commands_=true;
        if (timed) cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
        ID3D12DescriptorHeap* heaps[]{srv_.Get()};
        cmd->SetDescriptorHeaps(1,heaps);
        cmd->SetGraphicsRootSignature(root_.Get());
        cmd->SetPipelineState(native_pipeline_.Get());
        cmd->SetGraphicsRootDescriptorTable(0,srv_gpu_start_);
        cmd->SetGraphicsRoot32BitConstants(1,sizeof(constants)/4,&constants,0);
        auto handle=rtv_cpu_start_;
        if (direct_xr) {
            // Each Compositor is owned by one fenced XR command slot, so its
            // second RTV descriptor cannot be overwritten while GPU-active.
            handle=direct_xr_rtv_cpu_;
            if (xr_rtv_reference_.Get()!=destination || xr_rtv_format_!=xr_format) {
                D3D12_RENDER_TARGET_VIEW_DESC xr_view{};
                xr_view.Format=xr_format; xr_view.ViewDimension=D3D12_RTV_DIMENSION_TEXTURE2D;
                device->CreateRenderTargetView(destination,&xr_view,handle);
                xr_rtv_reference_=destination;
                xr_rtv_format_=xr_format;
                ++xr_rtv_refresh_count_;
            }
            const D3D12_VIEWPORT viewport{
                0,0,static_cast<float>(width_*2),static_cast<float>(height_),0,1};
            const D3D12_RECT rect{
                0,0,static_cast<LONG>(width_*2),static_cast<LONG>(height_)};
            cmd->RSSetViewports(1,&viewport);
            cmd->RSSetScissorRects(1,&rect);
            cmd->OMSetRenderTargets(1,&handle,FALSE,nullptr);
            cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            cmd->DrawInstanced(3,1,0,0);
        } else {
            const D3D12_VIEWPORT viewport{
                0,0,static_cast<float>(width_),static_cast<float>(height_),0,1};
            const D3D12_RECT rect{
                0,0,static_cast<LONG>(width_),static_cast<LONG>(height_)};
            cmd->RSSetViewports(1,&viewport);
            cmd->RSSetScissorRects(1,&rect);
            cmd->OMSetRenderTargets(1,&handle,FALSE,nullptr);
            cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            cmd->DrawInstanced(3,1,0,0);
        }
        transition(cmd,fovea,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,fovea_state);
        transition(cmd,periphery,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,peripheral_state);
        const bool copied=direct_xr ||
            copy_composite_to_stereo(cmd,device,output_.Get(),destination,
                D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET);
        last_native_direct_xr_=direct_xr;
        if (timed) {
            cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
            cmd->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timestamps_.Get(),0);
            timing_pending_=true; pending_direct_xr_=direct_xr;
        }
        if (!copied) return reject("Direct Native blend succeeded but Mono XR output validation failed");
        return true;
    }
    // Fallback for capture resources that cannot be sampled as SRVs.
    // Keep the original bit-for-bit gather path for format and GPU safety.
    // Gather Joey's actual Native Stereo Fix primary and secondary render
    // targets into this command slot's atlas, then run the same Mono compositor.
    bool record_native_gather(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
                ID3D12Resource* primary, ID3D12Resource* secondary,
                ID3D12Resource* destination, D3D12_RESOURCE_STATES primary_state,
                D3D12_RESOURCE_STATES secondary_state, const ViewFrame& frame,
                std::shared_ptr<const void> packet_lifetime, UINT64 frequency = 0) {
        recorded_commands_ = false;
        error_.clear();
        const auto reject = [this](const char* reason) { error_ = reason; return false; };
        if (!device || !cmd || !primary || !secondary || !destination || primary == secondary ||
            primary == destination || secondary == destination || cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT ||
            FAILED(device->GetDeviceRemovedReason()) || !layout_valid(frame.config.layout))
            return reject("Invalid Native resources, D3D12 device, or DuoView layout");
        last_native_direct_xr_=false;
        if (!stereo_destination_valid(destination->GetDesc(),frame.config.layout.atlas_width/2,
                                      frame.config.layout.atlas_height))
            return reject("Invalid gather XR destination before source copy");
        if (!atlas_) return reject("Missing prewarmed Native gather atlas (ID6 activation setup)");
        const auto p = primary->GetDesc(), s = secondary->GetDesc(), a = atlas_->GetDesc();
        const auto& l = frame.config.layout;
        const auto& primary_rect = frame.config.settings.fovea_view == 0 ? l.fovea : l.periphery;
        const auto& secondary_rect = frame.config.settings.fovea_view == 1 ? l.fovea : l.periphery;
        const auto valid_source = [&](const D3D12_RESOURCE_DESC& d, const Rect& r) {
            return d.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && bgra8(d.Format) &&
                d.Width >= r.width && d.Height >= r.height && d.DepthOrArraySize == 1 &&
                d.MipLevels == 1 && d.SampleDesc.Count == 1 && d.SampleDesc.Quality == 0;
        };
        if (!valid_source(p, primary_rect) || !valid_source(s, secondary_rect) ||
            a.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || a.Width != l.atlas_width ||
            a.Height != l.atlas_height || a.DepthOrArraySize != 1 || a.MipLevels != 1 ||
            a.SampleDesc.Count != 1 || a.SampleDesc.Quality != 0 ||
            (a.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            primary == atlas_.Get() || secondary == atlas_.Get() || destination == atlas_.Get())
            return reject("Native capture extent/format incompatible with frozen atlas rectangles");
        ComPtr<ID3D12Device> pd, sd, dd, cd;
        if (FAILED(primary->GetDevice(IID_PPV_ARGS(&pd))) ||
            FAILED(secondary->GetDevice(IID_PPV_ARGS(&sd))) ||
            FAILED(destination->GetDevice(IID_PPV_ARGS(&dd))) ||
            FAILED(cmd->GetDevice(IID_PPV_ARGS(&cd))) ||
            pd.Get() != device || sd.Get() != device || dd.Get() != device || cd.Get() != device)
            return reject("Native source / XR destination command-list device mismatch");
        const auto is_bgra_family = [](DXGI_FORMAT f) {
            return f == DXGI_FORMAT_B8G8R8A8_TYPELESS ||
                   f == DXGI_FORMAT_B8G8R8A8_UNORM ||
                   f == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        };
        if (!is_bgra_family(p.Format) || !is_bgra_family(s.Format) ||
            !bgra8(a.Format) ||
            a.Format != (srgb_ ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM))
            return reject("Native BGRA8 format/sRGB mismatch with prewarmed atlas");
        // record_native must use the exact prewarmed objects. Rebuilding here
        // would release atlas_ after CopyTextureRegion has already been queued.
        if (device_.Get() != device || width_ != l.atlas_width / 2 ||
            height_ != l.atlas_height || !output_ || !pipeline_ || !root_ || !srv_ || !rtv_)
            return reject("Native mode dimensions or shader state differ from prewarmed command slot");
        if (!copy_source_to_atlas(cmd, primary, atlas_.Get(), primary_state,
                                  primary_rect.x, primary_rect.y, primary_rect.width, primary_rect.height) ||
            !copy_source_to_atlas(cmd, secondary, atlas_.Get(), secondary_state,
                                  secondary_rect.x, secondary_rect.y, secondary_rect.width, secondary_rect.height)) {
            return reject("Failed recording Native primary/secondary source atlas copy");
        }
        recorded_commands_ = true;
        // These references live in the OpenXR command slot's compositor object.
        // Its slot is replaced only after the prior command fence has retired.
        primary_reference_ = primary;
        secondary_reference_ = secondary;
        packet_lifetime_ = std::move(packet_lifetime);
        const bool composed = record(device, cmd, atlas_.Get(), destination,
            D3D12_RESOURCE_STATE_COPY_DEST, frame.config, frequency);
        // record() clears its own command marker at entry. Preserve the gather
        // commands even if it rejects the later composite pass.
        const bool gather_recorded = true;
        recorded_commands_ = recorded_commands_ || gather_recorded;
        if (!composed && error_.empty()) error_ = "Native gather succeeded but Mono raster/copy validation failed";
        return composed;
    }
    const std::string& error() const { return error_; }
    bool recorded_commands() const { return recorded_commands_; }
    float gpu_milliseconds() const { return gpu_ms_; }
    bool last_native_direct_xr() const { return last_native_direct_xr_; }
    uint64_t last_native_source_extents() const { return last_native_source_extents_; }
    uint64_t srv_descriptor_refresh_count() const { return srv_descriptor_refresh_count_; }
    uint64_t xr_rtv_refresh_count() const { return xr_rtv_refresh_count_; }
    UINT64 timing_frequency() const { return frequency_; }
private:
    void ensure_srvs(ID3D12Device* device, ID3D12Resource* first,
                     ID3D12Resource* second, DXGI_FORMAT format) {
        if (srv_descriptors_valid_ && srv_first_reference_.Get()==first &&
            srv_second_reference_.Get()==second && srv_cached_format_==format) return;
        D3D12_SHADER_RESOURCE_VIEW_DESC view{};
        view.Format=format;
        view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
        view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        view.Texture2D.MipLevels=1;
        auto cpu=srv_cpu_start_;
        device->CreateShaderResourceView(first,&view,cpu);
        cpu.ptr+=srv_descriptor_increment_;
        device->CreateShaderResourceView(second,&view,cpu);
        srv_first_reference_=first; srv_second_reference_=second;
        srv_cached_format_=format; srv_descriptors_valid_=true;
        ++srv_descriptor_refresh_count_;
    }
    void update_timing(bool timed, bool direct_xr) {
        if (!timed || (timing_pending_ && pending_direct_xr_!=direct_xr)) {
            timing_pending_=false;
            gpu_ms_=-1.f;
        }
        if (timed) read_timing();
    }
    void read_timing() {
        if (!timing_pending_ || !timestamps_ || !frequency_) return;
        D3D12_RANGE range{0, sizeof(UINT64) * 2};
        UINT64* data{};
        if (SUCCEEDED(timestamps_->Map(0, &range, reinterpret_cast<void**>(&data)))) {
            if (data[1] >= data[0]) gpu_ms_ = static_cast<float>((data[1] - data[0]) * 1000.0 / frequency_);
            D3D12_RANGE no_write{0, 0}; timestamps_->Unmap(0, &no_write);
        }
        timing_pending_ = false;
    }
    void setup_timing(ID3D12Device* device, UINT64 frequency) {
        if (!frequency || queries_) return;
        D3D12_QUERY_HEAP_DESC q{}; q.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP; q.Count = 2;
        if (FAILED(device->CreateQueryHeap(&q, IID_PPV_ARGS(&queries_)))) return;
        D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_READBACK;
        heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        D3D12_RESOURCE_DESC buffer{}; buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width = sizeof(UINT64) * 2; buffer.Height = buffer.DepthOrArraySize = buffer.MipLevels = 1;
        buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer,
            D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&timestamps_)))) { queries_.Reset(); return; }
        frequency_ = frequency;
        queries_->SetName(L"DuoView::GPUQueries"); timestamps_->SetName(L"DuoView::GPUTimestamps");
    }
    static DXGI_FORMAT srv_format(DXGI_FORMAT f) {
        switch (f) {
        case DXGI_FORMAT_B8G8R8A8_TYPELESS: return DXGI_FORMAT_B8G8R8A8_UNORM;
        case DXGI_FORMAT_R8G8B8A8_TYPELESS: return DXGI_FORMAT_R8G8B8A8_UNORM;
        case DXGI_FORMAT_B8G8R8A8_UNORM: case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
        case DXGI_FORMAT_R8G8B8A8_UNORM: case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
        case DXGI_FORMAT_R10G10B10A2_UNORM: case DXGI_FORMAT_R16G16B16A16_FLOAT: return f;
        default: return DXGI_FORMAT_UNKNOWN;
        }
    }
    static void transition(ID3D12GraphicsCommandList* cmd, ID3D12Resource* r,
                           D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
        if (before == after) return;
        D3D12_RESOURCE_BARRIER b{};
        b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition = {r, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before, after};
        cmd->ResourceBarrier(1, &b);
    }
    static bool copy_source_to_atlas(ID3D12GraphicsCommandList* cmd, ID3D12Resource* source,
        ID3D12Resource* atlas, D3D12_RESOURCE_STATES source_state, UINT x, UINT y, UINT width, UINT height) {
        if (!width || !height) return false;
        transition(cmd, source, source_state, D3D12_RESOURCE_STATE_COPY_SOURCE);
        const D3D12_TEXTURE_COPY_LOCATION from{source, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX, {0}};
        const D3D12_TEXTURE_COPY_LOCATION to{atlas, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX, {0}};
        const D3D12_BOX box{0, 0, 0, width, height, 1};
        cmd->CopyTextureRegion(&to, x, y, 0, &from, &box);
        transition(cmd, source, D3D12_RESOURCE_STATE_COPY_SOURCE, source_state);
        return true;
    }
    bool check(HRESULT hr, const char* operation) {
        if (SUCCEEDED(hr)) return true;
        error_ = std::string(operation) + " HRESULT " + std::to_string(static_cast<uint32_t>(hr));
        return false;
    }
    bool prepare(ID3D12Device* device, UINT width, UINT height, bool srgb) {
        if (device_.Get() == device && output_ && atlas_ && pipeline_ && native_pipeline_ && root_ && srv_ && rtv_ && width == width_ && height == height_ && srgb == srgb_) return true;
        output_.Reset(); atlas_.Reset(); pipeline_.Reset(); native_pipeline_.Reset(); root_.Reset(); srv_.Reset(); rtv_.Reset();
        srv_first_reference_.Reset(); srv_second_reference_.Reset(); xr_rtv_reference_.Reset();
        srv_descriptors_valid_=false; srv_cached_format_=DXGI_FORMAT_UNKNOWN;
        xr_rtv_format_=DXGI_FORMAT_UNKNOWN;
        srv_cpu_start_={}; srv_gpu_start_={}; rtv_cpu_start_={}; direct_xr_rtv_cpu_={};
        srv_descriptor_increment_=0;
        queries_.Reset(); timestamps_.Reset(); timing_pending_ = false; gpu_ms_ = -1.f; frequency_ = 0;
        device_ = device; width_ = width; height_ = height; srgb_ = srgb;
        D3D12_DESCRIPTOR_RANGE range{};
        range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        range.NumDescriptors = 2;
        D3D12_ROOT_PARAMETER params[2]{};
        params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        params[0].DescriptorTable = {1, &range};
        params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
        params[1].Constants = {0, 0, sizeof(ShaderConstants) / 4};
        params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        D3D12_STATIC_SAMPLER_DESC sampler{};
        sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
        sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
        sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        sampler.MaxAnisotropy = 1;
        sampler.MaxLOD = D3D12_FLOAT32_MAX;
        sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        D3D12_ROOT_SIGNATURE_DESC desc{2, params, 1, &sampler, D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT};
        ComPtr<ID3DBlob> serialized, errors;
        if (!check(D3D12SerializeRootSignature(&desc, D3D_ROOT_SIGNATURE_VERSION_1, &serialized, &errors), "Root signature") ||
            !check(device->CreateRootSignature(0, serialized->GetBufferPointer(), serialized->GetBufferSize(), IID_PPV_ARGS(&root_)), "Create root signature")) return false;
        // Compile shaders in CI and load DXBC directly. Never invoke HLSL compiler on a live XR frame.
        const auto output_format = srgb ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        D3D12_GRAPHICS_PIPELINE_STATE_DESC graphics{};
        graphics.pRootSignature = root_.Get();
        graphics.VS = {vertex_shader_bytecode, sizeof(vertex_shader_bytecode)};
        graphics.PS = {pixel_shader_bytecode, sizeof(pixel_shader_bytecode)};
        auto& blend = graphics.BlendState.RenderTarget[0];
        blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
        blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
        blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
        blend.LogicOp = D3D12_LOGIC_OP_NOOP;
        blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
        graphics.SampleMask = UINT_MAX;
        graphics.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
        graphics.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
        graphics.RasterizerState.DepthClipEnable = TRUE;
        graphics.DepthStencilState.DepthEnable = FALSE;
        graphics.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ZERO;
        graphics.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        graphics.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        graphics.NumRenderTargets = 1; graphics.RTVFormats[0] = output_format; graphics.SampleDesc.Count = 1;
        if (!check(device->CreateGraphicsPipelineState(&graphics, IID_PPV_ARGS(&pipeline_)), "Create raster PSO")) return false;
        graphics.PS = {native_pixel_shader_bytecode, sizeof(native_pixel_shader_bytecode)};
        if (!check(device->CreateGraphicsPipelineState(&graphics, IID_PPV_ARGS(&native_pipeline_)), "Create direct Native raster PSO")) return false;
        D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_DEFAULT; heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        D3D12_RESOURCE_DESC texture{};
        texture.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        texture.Width = width; texture.Height = height; texture.DepthOrArraySize = 1; texture.MipLevels = 1;
        texture.Format = DXGI_FORMAT_B8G8R8A8_TYPELESS; texture.SampleDesc.Count = 1;
        texture.Flags = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
        if (!check(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &texture,
            D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr, IID_PPV_ARGS(&output_)), "Create output")) return false;
        output_->SetName(L"DuoView::MonoComposite");
        D3D12_RESOURCE_DESC atlas_desc=texture;
        atlas_desc.Width=static_cast<uint64_t>(width)*2;
        atlas_desc.Height=height;
        atlas_desc.Format=srgb ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        atlas_desc.Flags=D3D12_RESOURCE_FLAG_NONE;
        if (!check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&atlas_desc,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&atlas_)),"Create Native gather atlas")) return false;
        atlas_->SetName(L"DuoView::NativeGatherAtlasFallback");
        D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.NumDescriptors = 2; hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        if (!check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&rtv_)), "Create RTV heap")) return false;
        hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE; hd.NumDescriptors = 2;
        if (!check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&srv_)), "Create SRV heap")) return false;
        srv_cpu_start_=srv_->GetCPUDescriptorHandleForHeapStart();
        srv_gpu_start_=srv_->GetGPUDescriptorHandleForHeapStart();
        rtv_cpu_start_=rtv_->GetCPUDescriptorHandleForHeapStart();
        srv_descriptor_increment_=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        direct_xr_rtv_cpu_=rtv_cpu_start_;
        direct_xr_rtv_cpu_.ptr+=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
        D3D12_RENDER_TARGET_VIEW_DESC view{}; view.Format = output_format; view.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
        device->CreateRenderTargetView(output_.Get(), &view, rtv_cpu_start_);
        return true;
    }
    ComPtr<ID3D12Device> device_;
    ComPtr<ID3D12Resource> output_, source_, atlas_, primary_reference_, secondary_reference_;
    ComPtr<ID3D12Resource> srv_first_reference_, srv_second_reference_, xr_rtv_reference_;
    std::shared_ptr<const void> packet_lifetime_{};
    ComPtr<ID3D12RootSignature> root_;
    ComPtr<ID3D12PipelineState> pipeline_, native_pipeline_;
    ComPtr<ID3D12DescriptorHeap> srv_, rtv_;
    D3D12_CPU_DESCRIPTOR_HANDLE srv_cpu_start_{}, rtv_cpu_start_{}, direct_xr_rtv_cpu_{};
    D3D12_GPU_DESCRIPTOR_HANDLE srv_gpu_start_{};
    UINT srv_descriptor_increment_{};
    ComPtr<ID3D12QueryHeap> queries_;
    ComPtr<ID3D12Resource> timestamps_;
    UINT64 frequency_{};
    float gpu_ms_{-1.f};
    bool timing_pending_{}, pending_direct_xr_{}, recorded_commands_{}, last_native_direct_xr_{};
    uint64_t last_native_source_extents_{};
    uint64_t srv_descriptor_refresh_count_{}, xr_rtv_refresh_count_{};
    DXGI_FORMAT srv_cached_format_{DXGI_FORMAT_UNKNOWN}, xr_rtv_format_{DXGI_FORMAT_UNKNOWN};
    bool srv_descriptors_valid_{};
    UINT width_{}, height_{};
    bool srgb_{};
    std::string error_;
};
}


```

## FILE src/mods/vr/DuoViewDelivery.hpp (214 lines)
```cpp
#pragma once
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>

namespace uevr::duoview {

enum class SourceRole : uint8_t { primary, secondary, auxiliary };
enum class DeliveryEvent : uint8_t { family, render, hook, duplicate, conflict, execute, select, miss, copy, submit };
struct DeliveryTrace {
    uint64_t sequence{}, time_us{}, generation{}, serial{};
    uintptr_t command{}, target{};
    uint32_t frame{}, thread{};
    DeliveryEvent event{};
    SourceRole role{SourceRole::auxiliary};
    uint64_t draw{}, capture_generation{};
    uint32_t pose{};
};

struct DeliveryCounts {
    uint64_t produced{}, ready{}, matched{}, enqueued{}, submitted{}, duplicate_presents{}, overwritten{}, failed{}, blocked{};
};

template<class Packet, size_t Capacity = 128>
class Delivery {
public:
    struct Source {
        std::shared_ptr<const Packet> packet{};
        uint64_t generation{};
        uintptr_t target{}, scene{};
        uint32_t frame{};
        SourceRole role{SourceRole::auxiliary};
        explicit operator bool() const { return role != SourceRole::auxiliary; }
        bool same_owner(const Source& other) const {
            return generation == other.generation && packet == other.packet &&
                target == other.target && scene == other.scene && frame == other.frame && role == other.role;
        }
    };

    enum class Attachment { added, duplicate, conflict };
    struct Command {
        std::array<Source,2> sources{};
        Source original{};
        Source owner() const { return original; }
        Attachment attach(const Source& source) {
            if (!source) return Attachment::conflict;
            auto& slot=sources[static_cast<size_t>(source.role)];
            if (slot) return slot.same_owner(source) ? Attachment::duplicate : Attachment::conflict;
            const auto existing=owner();
            if (existing && (existing.packet!=source.packet || existing.generation!=source.generation ||
                existing.scene!=source.scene || existing.target==source.target)) return Attachment::conflict;
            slot=source;
            if (!original) original=source;
            return Attachment::added;
        }
    };

    bool family(Source source, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!source || !source.packet || !advance(source.generation) || source.packet->serial<=blocked_serial_) return false;
        targets_[static_cast<size_t>(source.role)] = source.target;
        largest_registered_serial_ = (std::max)(largest_registered_serial_, source.packet->serial);
        for (auto& entry : families_) {
            if (entry && entry.generation == source.generation && entry.frame == source.frame &&
                entry.target == source.target && entry.scene == source.scene) return entry.same_owner(source);
        }
        for (auto& entry : families_) {
            if (!entry) { entry = source; if (source.role==SourceRole::primary) ++counts_.produced; trace(DeliveryEvent::family, source, 0, thread); return true; }
        }
        trace(DeliveryEvent::conflict, source, 0, thread);
        return false;
    }

    Source render(uint64_t generation, uint32_t frame, uintptr_t target, uintptr_t scene, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation)) return {};
        for (auto& entry : families_) {
            if (entry && entry.frame == frame && entry.target == target && entry.scene == scene) {
                auto result = entry; entry = {}; trace(DeliveryEvent::render, result, 0, thread); return result;
            }
        }
        Source missing{{}, generation, target, scene, frame,
            target && target == targets_[0] ? SourceRole::primary :
            target && target == targets_[1] ? SourceRole::secondary : SourceRole::auxiliary};
        if (missing) trace(DeliveryEvent::miss, missing, 0, thread);
        return missing;
    }

    void executed(const Source& source, uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!source || !advance(source.generation) || (source.packet && source.packet->serial<=blocked_serial_)) return;
        const auto& old=sources_[0].packet;
        if (old && old==sources_[1].packet && old!=source.packet && old->serial!=last_submitted_) ++counts_.overwritten;
        const auto index = static_cast<size_t>(source.role);
        sources_[index] = source;
        threads_[index] = thread;
        if (sources_[0].packet && sources_[0].packet==sources_[1].packet && source.packet->serial!=last_ready_) {
            last_ready_=source.packet->serial; ++counts_.ready;
        }
        trace(DeliveryEvent::execute, source, command, thread);
    }

    void block(const Source& source, uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!source || !advance(source.generation)) return;
        ++counts_.blocked;
        blocked_serial_ = (std::max)(blocked_serial_, source.packet ? source.packet->serial : largest_registered_serial_);
        trace(DeliveryEvent::conflict, source, command, thread);
    }

    std::shared_ptr<const Packet> select(uint64_t generation, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation)) return {};
        const auto& a = sources_[0]; const auto& b = sources_[1];
        if (!a.packet || a.packet != b.packet || a.packet->serial <= blocked_serial_ ||
            threads_[0] != thread || threads_[1] != thread) {
            trace(DeliveryEvent::miss, a, 0, thread); return {};
        }
        if (a.packet->serial!=last_matched_) { last_matched_=a.packet->serial; ++counts_.matched; }
        trace(DeliveryEvent::select, a, 0, thread);
        return a.packet;
    }

    void retire(uint64_t generation=0) {
        std::scoped_lock lock{mutex_};
        if (generation && generation<generation_) return;
        if (generation>generation_) advance(generation);
        blocked_serial_=(std::max)(blocked_serial_,largest_registered_serial_);
        families_={}; sources_={}; threads_={}; targets_={};
    }

    DeliveryCounts counts() const { std::scoped_lock lock{mutex_}; return counts_; }
    void reset_counts() { std::scoped_lock lock{mutex_}; counts_={}; }
    void result(DeliveryEvent event, uint64_t serial, bool success, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!success || !serial) ++counts_.failed;
        else if (event==DeliveryEvent::copy && serial!=last_enqueued_) { last_enqueued_=serial; ++counts_.enqueued; }
        else if (event==DeliveryEvent::submit) {
            if (serial!=last_submitted_) { last_submitted_=serial; ++counts_.submitted; }
            else ++counts_.duplicate_presents;
        }
        Source source=sources_[0];
        if (!source.packet || source.packet->serial!=serial) source.packet.reset();
        trace(event, source, 0, thread);
        trace_[(sequence_-1)%trace_.size()].serial=serial;
    }

    void note(DeliveryEvent event, const Source& source, uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_}; trace(event, source, command, thread);
    }

    std::array<DeliveryTrace, 64> recent() const {
        std::scoped_lock lock{mutex_};
        std::array<DeliveryTrace, 64> result{};
        for (size_t i=0; i<result.size(); ++i) {
            if (sequence_ > i) result[result.size()-1-i] = trace_[(sequence_-1-i)%trace_.size()];
        }
        return result;
    }

private:
    bool advance(uint64_t generation) {
        if (!generation || generation < generation_) return false;
        if (generation != generation_) {
            generation_ = generation; families_ = {}; sources_ = {}; threads_ = {}; targets_ = {};
            blocked_serial_ = 0; largest_registered_serial_ = 0;
            last_ready_=0; last_matched_=0; last_enqueued_=0; last_submitted_=0; counts_={};
        }
        return true;
    }
    void trace(DeliveryEvent event, const Source& source, uintptr_t command, uint32_t thread) {
        const auto us = std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
        trace_[sequence_%trace_.size()] = {sequence_+1, static_cast<uint64_t>(us), source.generation,
            source.packet ? source.packet->serial : 0, command, source.target, source.frame, thread, event, source.role};
        if constexpr (requires { source.packet->duoview_frame; source.packet->duoview_mono_source_frame; source.packet->capture_generation; }) {
            auto& event_trace=trace_[sequence_%trace_.size()];
            if (source.packet) {
                event_trace.draw=source.packet->duoview_frame ? source.packet->duoview_frame->config.key.frame : 0;
                event_trace.pose=source.packet->duoview_mono_source_frame;
                event_trace.capture_generation=source.packet->capture_generation;
            }
        }
        ++sequence_;
    }
    mutable std::mutex mutex_{};
    uint64_t generation_{}, sequence_{}, blocked_serial_{}, largest_registered_serial_{};
    uint64_t last_ready_{}, last_matched_{}, last_enqueued_{}, last_submitted_{};
    DeliveryCounts counts_{};
    std::array<Source, Capacity> families_{};
    std::array<Source, 2> sources_{};
    std::array<uintptr_t, 2> targets_{};
    std::array<uint32_t, 2> threads_{};
    std::array<DeliveryTrace, 8192> trace_{};
};

template<class ReadNext>
std::optional<uintptr_t> command_tail(uintptr_t root, ReadNext&& read_next) {
    constexpr size_t maximum_commands = 65536;
    auto current = root;
    for (size_t i=0; current && i<maximum_commands; ++i) {
        const auto next = read_next(current);
        if (!next) return {};
        if (!*next) return current;
        current = *next;
    }
    return {};
}

} // namespace uevr::duoview

```

## FILE src/mods/vr/DuoViewFrame.hpp (155 lines)
```cpp
#pragma once
// Stage 5 — per-frame DuoView coordination. No UE/D3D headers.
// New compositions require a complete pair with matching gaze/pose and method
// generation. Submit continuity may briefly reuse an unchanged released image
// with its original pose; it never recomposes stale source textures.
//
// Backend integration contract:
//  (1) begin() once per game-render frame with the *same* immutable layout,
//      gaze and pose token used by both Unreal view projections.
//  (2) note_view() for each actually completed Unreal view, not merely for
//      GetDesiredNumberOfViews or AdjustViewRect callback invocation.
//  (3) queue_composite() only when both views were rendered.
//  (4) note_gpu_complete() only after the compositing GPU fence has signaled.
//  (5) consume_for_submit() once before both OpenXR eye copies.
//  Source validation and released-image continuity are separate contracts.
#include "DuoViewGeometry.hpp"
#include <array>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <optional>

namespace uevr::duoview {

struct FrameKey {
    uint64_t generation{};
    uint64_t frame{};
    constexpr bool operator==(const FrameKey&) const = default;
};
class SubmitContinuity {
public:
    void reset() { ready_=false; }
    void submitted(uint64_t generation, uint64_t swapchain, uint64_t now_ms) {
        generation_=generation; swapchain_=swapchain; submitted_ms_=now_ms; ready_=true;
    }
    bool can_hold(uint64_t generation, uint64_t swapchain, uint64_t now_ms) const {
        return ready_ && generation==generation_ && swapchain && swapchain==swapchain_ &&
            now_ms>=submitted_ms_ && now_ms-submitted_ms_<=100;
    }
private:
    uint64_t generation_{}, swapchain_{}, submitted_ms_{};
    bool ready_{};
};

struct RenderFrame {
    FrameKey key{};
    Layout layout{};
    uint64_t pose_token{};
    uint64_t gaze_timestamp_ms{};
};
struct CompositedFrame {
    FrameKey key{};
    uint64_t output_resource_id{};
    uint64_t gpu_fence_value{};
};

inline bool layout_valid(const Layout& l) {
    if (!l.fovea.width || !l.fovea.height || !l.periphery.width ||
        !l.periphery.height || !l.atlas_width || !l.atlas_height) return false;
    const auto in_bounds = [&](const Rect& r) {
        return static_cast<uint64_t>(r.x) + r.width <= l.atlas_width &&
               static_cast<uint64_t>(r.y) + r.height <= l.atlas_height;
    };
    if (!in_bounds(l.fovea) || !in_bounds(l.periphery)) return false;
    const bool disjoint = static_cast<uint64_t>(l.fovea.x) + l.fovea.width <= l.periphery.x ||
        static_cast<uint64_t>(l.periphery.x) + l.periphery.width <= l.fovea.x ||
        static_cast<uint64_t>(l.fovea.y) + l.fovea.height <= l.periphery.y ||
        static_cast<uint64_t>(l.periphery.y) + l.periphery.height <= l.fovea.y;
    if (!disjoint) return false;
    return std::isfinite(l.u0) && std::isfinite(l.v0) &&
        std::isfinite(l.u1) && std::isfinite(l.v1) &&
        l.u0 >= 0.f && l.u0 < l.u1 && l.u1 <= 1.f &&
        l.v0 >= 0.f && l.v0 < l.v1 && l.v1 <= 1.f;
}

class FrameCoordinator {
public:
    bool begin(RenderFrame next) {
        std::scoped_lock lock{mutex_};
        if (!next.key.frame || !next.key.generation || !next.pose_token ||
            !layout_valid(next.layout)) return false;
        if (next.key.generation < last_begin_.generation ||
            (last_begin_.generation == next.key.generation &&
             next.key.frame <= last_begin_.frame)) return false;
        clear_locked();
        last_begin_ = next.key;
        active_ = next;
        return true;
    }

    // Called only for the completed scene rendering of the view; returns false
    // if the view's source generation or frame identity differs from the packet.
    bool note_view(FrameKey key, unsigned index, uint64_t pose_token) {
        std::scoped_lock lock{mutex_};
        if (!active_ || key != active_->key || index > 1 ||
            !pose_token || pose_token != active_->pose_token || queued_ ||
            rendered_[index]) return false;
        rendered_[index] = true;
        return true;
    }

    bool queue_composite(FrameKey key, uint64_t output_resource_id,
                         uint64_t gpu_fence_value) {
        std::scoped_lock lock{mutex_};
        if (!active_ || key != active_->key || queued_ || !rendered_[0] ||
            !rendered_[1] || !output_resource_id || !gpu_fence_value) return false;
        pending_ = CompositedFrame{key,output_resource_id,gpu_fence_value};
        queued_ = true;
        return true;
    }

    // Call ONLY when the actual D3D12 fence has reached fence_value.
    bool note_gpu_complete(FrameKey key, uint64_t completed_fence_value) {
        std::scoped_lock lock{mutex_};
        if (!active_ || !pending_ || key != active_->key ||
            completed_fence_value < pending_->gpu_fence_value) return false;
        complete_ = true;
        return true;
    }

    std::optional<CompositedFrame> consume_for_submit(FrameKey key) {
        std::scoped_lock lock{mutex_};
        if (!active_ || !pending_ || !complete_ || submitted_ ||
            key != active_->key) return {};
        submitted_ = true;
        return pending_;
    }

    std::optional<RenderFrame> snapshot(FrameKey key) const {
        std::scoped_lock lock{mutex_};
        if (!active_ || key != active_->key) return {};
        return active_;
    }

    void retire() {
        std::scoped_lock lock{mutex_};
        clear_locked();
    }

private:
    void clear_locked() {
        active_.reset();
        pending_.reset();
        rendered_ = {false,false};
        queued_ = complete_ = submitted_ = false;
    }

    mutable std::mutex mutex_{};
    FrameKey last_begin_{};
    std::optional<RenderFrame> active_{};
    std::optional<CompositedFrame> pending_{};
    std::array<bool,2> rendered_{false,false};
    bool queued_{}, complete_{}, submitted_{};
};
} // namespace uevr::duoview

```

## FILE src/mods/vr/DuoViewGaze.hpp (136 lines)
```cpp
#pragma once
// Stage 4: gaze-to-Mono-frustum mapping and asynchronous validity policy.
// The caller must first convert the PSVR2 Toolkit combined calibrated ray
// from device/OpenXR coordinates into Joey's shared left-optical Mono basis.
// This module is a renderer-independent testable component, NOT a PSVR2 reader.
#include "DuoViewGeometry.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <optional>

namespace uevr::duoview {

struct Ray {
    float right{}, up{}, forward{}; // +forward = looking through the Mono plane
};
struct UV {
    float u{.5f}, v{.5f};
};

inline std::optional<Ray> optical_ray(Ray ray, const std::array<float, 9>& rotation) {
    for (float x : rotation) if (!std::isfinite(x)) return {};
    // Transpose the orthonormal eye rotation in OpenXR's -Z basis, then return to Mono +Z.
    const float x = rotation[0]*ray.right + rotation[1]*ray.up - rotation[2]*ray.forward;
    const float y = rotation[3]*ray.right + rotation[4]*ray.up - rotation[5]*ray.forward;
    const float z = rotation[6]*ray.right + rotation[7]*ray.up - rotation[8]*ray.forward;
    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z) || z >= -.1f) return {};
    return Ray{x, y, -z};
}

// Input: eye ray in the *shared calibrated Mono optical basis*.
// Output: normalized full-frustum tangent-plane coordinates (not angles).
inline std::optional<UV> ray_to_uv(Ray gaze, const Tans& full) {
    if (!std::isfinite(gaze.right) || !std::isfinite(gaze.up) ||
        !std::isfinite(gaze.forward) || gaze.forward <= .1f ||
        !std::isfinite(full.left) || !std::isfinite(full.right) ||
        !std::isfinite(full.top) || !std::isfinite(full.bottom) ||
        full.right <= full.left || full.top <= full.bottom)
        return {};
    const float horizontal = gaze.right / gaze.forward;
    const float vertical = gaze.up / gaze.forward;
    if (!std::isfinite(horizontal) || !std::isfinite(vertical)) return {};
    return UV {
        std::clamp((horizontal - full.left) / (full.right - full.left), 0.f, 1.f),
        std::clamp((full.top - vertical) / (full.top - full.bottom), 0.f, 1.f)
    };
}

class GazeCache {
public:
    void invalidate() { sample_.reset(); }
    // Based on the already-tested PSVR2 Toolkit CAPI behavior: a false read
    // often means "no new frame", not "tracking invalid". Reuse a frame for
    // <= 50ms without extra temporal smoothing or spatial dead zones.
    explicit GazeCache(uint64_t max_age_ms = 50) : max_age_ms_{max_age_ms} {}

    UV update(uint64_t now_ms, std::optional<UV> fresh) {
        if (now_ms < last_tick_ms_) {
            sample_.reset();
        }
        last_tick_ms_ = now_ms;
        if (fresh && std::isfinite(fresh->u) && std::isfinite(fresh->v) &&
            fresh->u >= 0.f && fresh->u <= 1.f &&
            fresh->v >= 0.f && fresh->v <= 1.f) {
            sample_ = fresh;
            last_valid_ms_ = now_ms;
        }
        if (sample_ && now_ms >= last_valid_ms_ &&
            now_ms - last_valid_ms_ <= max_age_ms_) {
            return *sample_;
        }
        sample_.reset();
        return {.5f, .5f};
    }

private:
    std::optional<UV> sample_{};
    uint64_t last_valid_ms_{};
    uint64_t last_tick_ms_{};
    uint64_t max_age_ms_{50};
};


// Reacquisition gate for PSVR2 blink / transient invalid tracking.
// Retains the optical ray, so every frame can reproject it through its own
// frozen shared Mono matrix. A large first sample after lost tracking must
// be confirmed before committing; ordinary continuous saccades are immediate.
class RayRecovery {
public:
    void controls(uint32_t hold_ms, uint32_t reacquire_samples) {
        hold_ms_ = std::clamp(hold_ms, 50u, 2000u);
        confirm_ = std::clamp(reacquire_samples, 1u, 4u);
    }
    void reset() { last_.reset(); pending_.reset(); confirmed_=0; recovering_=false; tick_=valid_at_=0; }
    std::optional<Ray> update(uint64_t now, std::optional<Ray> fresh, bool explicitly_invalid=false) {
        if (now < tick_) reset();
        tick_ = now;
        if (explicitly_invalid) { recovering_=true; pending_.reset(); confirmed_=0; }
        if (!fresh && last_ && now>=valid_at_ && now-valid_at_>50)
            recovering_=true;
        if (fresh) {
            const auto differs=[](const Ray& a,const Ray& b,float threshold) {
                const float dx=a.right-b.right, dy=a.up-b.up, dz=a.forward-b.forward;
                return dx*dx+dy*dy+dz*dz>threshold*threshold;
            };
            if (recovering_ && last_ && confirm_>1 && differs(*fresh,*last_,.10f)) {
                if (!pending_ || differs(*fresh,*pending_,.045f)) {
                    pending_=*fresh;
                    confirmed_=1;
                } else {
                    ++confirmed_;
                }
                if (confirmed_ >= confirm_) {
                    last_=*fresh; valid_at_=now; recovering_=false;
                    pending_.reset(); confirmed_=0;
                }
            } else {
                last_=*fresh; valid_at_=now; recovering_=false;
                pending_.reset(); confirmed_=0;
            }
        }
        if (last_ && now>=valid_at_ && now-valid_at_<=hold_ms_) return last_;
        return {};
    }
    uint32_t age_ms(uint64_t now) const {
        return last_ && now>=valid_at_ ? static_cast<uint32_t>(
            (std::min)(uint64_t(UINT32_MAX), now-valid_at_)) : UINT32_MAX;
    }
private:
    std::optional<Ray> last_{},pending_{};
    uint64_t tick_{},valid_at_{};
    uint32_t hold_ms_{350},confirm_{2},confirmed_{};
    bool recovering_{};
};

} // namespace uevr::duoview

```

## FILE src/mods/vr/DuoViewGeometry.hpp (128 lines)
```cpp
#pragma once
// DuoView Mono: renderer-independent two-view layout, projection crop and
// compositor coordinate model. No UE/UESDK dependencies.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>

namespace uevr::duoview {

constexpr int renderer_view_index(int raw, bool double_precision) {
    if (double_precision) return raw >= 0 && raw <= 1 ? raw : -1;
    return raw >= 1 && raw <= 2 ? raw - 1 : -1;
}

struct Rect {
    uint32_t x{}, y{}, width{}, height{};
};
struct Layout {
    Rect fovea{}, periphery{};
    uint32_t atlas_width{}, atlas_height{};
    float u0{}, u1{}, v0{}, v1{}; // ROI on the full Mono image, top-left UV convention
    float peripheral_scale{};
    float crop_width{}, crop_height{};
};
struct Tans {
    // Left < right; top > bottom. Represent tangent-space extent of the
    // centered combined Mono projection, NOT angular percentages.
    float left{}, right{}, top{}, bottom{};
};

// Diagnostic defaults: preserve ~3000² baseline render density in the fovea
// without silently increasing the output/swapchain resolution.
inline std::optional<Layout> make_layout(
    uint32_t output_width, uint32_t output_height,
    float crop_width = 0.50f, float crop_height = 0.50f,
    float peripheral_scale = 0.20f, float foveal_density = 1.0f,
    float gaze_u = 0.50f, float gaze_v = 0.50f)
{
    if (!output_width || !output_height || output_width > 8192 || output_height > 16384 ||
        !std::isfinite(crop_width) || !std::isfinite(crop_height) ||
        !std::isfinite(peripheral_scale) || !std::isfinite(foveal_density) ||
        !std::isfinite(gaze_u) || !std::isfinite(gaze_v) ||
        crop_width < .05f || crop_height < .05f ||
        crop_width > 1.f || crop_height > 1.f ||
        peripheral_scale < .05f || peripheral_scale > .50f ||
        foveal_density < .25f || foveal_density > 4.f ||
        gaze_u < 0.f || gaze_u > 1.f || gaze_v < 0.f || gaze_v > 1.f)
    {
        return {};
    }
    const auto round_size = [](float x) -> uint32_t {
        return static_cast<uint32_t>((std::max)(1.0f, std::round(x)));
    };
    const auto fw = round_size(output_width * crop_width * foveal_density);
    const auto fh = round_size(output_height * crop_height * foveal_density);
    const auto pw = round_size(output_width * peripheral_scale);
    const auto ph = round_size(output_height * peripheral_scale);
    // Match Joey's existing 2*W by H scene allocation for the initial
    // diagnostic. A more compact atlas is possible after DX12 validation.
    if (static_cast<uint64_t>(fw) + pw > 2ull * output_width ||
        (std::max)(fh, ph) > output_height) { return {}; }
    const float cu = std::clamp(gaze_u, crop_width * .5f, 1.f - crop_width * .5f);
    const float cv = std::clamp(gaze_v, crop_height * .5f, 1.f - crop_height * .5f);
    return Layout{
        .fovea = {0, 0, fw, fh},
        .periphery = {fw, 0, pw, ph},
        .atlas_width = output_width * 2,
        .atlas_height = output_height,
        .u0 = cu - crop_width * .5f,
        .u1 = cu + crop_width * .5f,
        .v0 = cv - crop_height * .5f,
        .v1 = cv + crop_height * .5f,
        .peripheral_scale = peripheral_scale,
        .crop_width = crop_width,
        .crop_height = crop_height
    };
}

inline std::optional<Tans> foveal_frustum(const Tans& full, const Layout& l) {
    if (!(std::isfinite(full.left) && std::isfinite(full.right) &&
          std::isfinite(full.top) && std::isfinite(full.bottom)) ||
        full.right <= full.left || full.top <= full.bottom) { return {}; }
    const float span_x = full.right - full.left;
    const float span_y = full.top - full.bottom;
    return Tans{
        .left = full.left + span_x * l.u0,
        .right = full.left + span_x * l.u1,
        .top = full.top - span_y * l.v0,
        .bottom = full.top - span_y * l.v1
    };
}

// Modify the x/y clip-space rows of ANY compatible GLM-style 4x4 perspective
// matrix, leaving depth and w untouched. Works for reversed-Z projections:
// maps full-frustum UV [u0,u1]x[v0,v1] to the entire cropped viewport.
template <typename Matrix>
void apply_foveal_crop(Matrix& matrix, const Layout& l) {
    const auto x_scale = 1.f / (l.u1 - l.u0);
    const auto y_scale = 1.f / (l.v1 - l.v0);
    const auto x_shift = (1.f - l.u0 - l.u1) * x_scale;
    const auto y_shift = (l.v0 + l.v1 - 1.f) * y_scale;
    for (int col = 0; col < 4; ++col) {
        const auto old_x = matrix[col][0];
        const auto old_y = matrix[col][1];
        const auto old_w = matrix[col][3];
        matrix[col][0] = old_x * x_scale + old_w * x_shift;
        matrix[col][1] = old_y * y_scale + old_w * y_shift;
    }
}

inline float foveal_blend(const Layout& l, float u, float v, float feather) {
    if (u < l.u0 || u > l.u1 || v < l.v0 || v > l.v1) return 0.f;
    if (feather <= 0.f) return 1.f;
    const auto du = (std::min)((u - l.u0) / l.crop_width, (l.u1 - u) / l.crop_width);
    const auto dv = (std::min)((v - l.v0) / l.crop_height, (l.v1 - v) / l.crop_height);
    const float edge = std::clamp((std::min)(du, dv) / feather, 0.f, 1.f);
    return edge * edge * (3.f - 2.f * edge);
}

inline uint64_t rendered_pixels(const Layout& l) {
    return static_cast<uint64_t>(l.fovea.width) * l.fovea.height +
           static_cast<uint64_t>(l.periphery.width) * l.periphery.height;
}

} // namespace uevr::duoview

```

## FILE src/mods/vr/DuoViewMonoCopyD3D12.hpp (82 lines)
```cpp
#pragma once
// Stage 9 — safe single-width BGRA8 Mono image -> OpenXR double-wide copy.
// This is purpose-built for DuoView's full-FOV *composited* image.
// It does not alter Joey's original MonoD3D12::copy_scene contract.
// Call from the existing OpenXR DX12 copy command-list callback, after the
// compositor completes on the SAME queue or a properly waited dependency.
// Own both source/output resources until the swapchain consumer fence retires.
#include <cstdint>
#include <d3d12.h>
#include <wrl/client.h>
#include <utility>

namespace uevr::duoview::dx12 {

inline bool bgra8(DXGI_FORMAT f) {
    return f==DXGI_FORMAT_B8G8R8A8_UNORM ||
           f==DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
           f==DXGI_FORMAT_B8G8R8A8_TYPELESS;
}

inline bool stereo_destination_valid(const D3D12_RESOURCE_DESC& d, UINT64 eye_width, UINT height) {
    return eye_width && eye_width<=16384 && height &&
        d.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
        d.Width==eye_width*2 && d.Height==height &&
        d.DepthOrArraySize==1 && d.MipLevels==1 &&
        d.SampleDesc.Count==1 && d.SampleDesc.Quality==0 &&
        bgra8(d.Format) && (d.Flags&D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
}

inline bool copy_composite_to_stereo(ID3D12GraphicsCommandList* cmd,
                                    ID3D12Device* device,
                                    ID3D12Resource* mono_composite,
                                    ID3D12Resource* openxr_doublewide,
                                    D3D12_RESOURCE_STATES mono_state,
                                    D3D12_RESOURCE_STATES destination_state) {
    if(!cmd || !device || !mono_composite || !openxr_doublewide ||
       mono_composite==openxr_doublewide ||
       cmd->GetType()!=D3D12_COMMAND_LIST_TYPE_DIRECT ||
       FAILED(device->GetDeviceRemovedReason())) return false;

    const auto s=mono_composite->GetDesc();
    const auto d=openxr_doublewide->GetDesc();
    if(s.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
       s.DepthOrArraySize!=1 || s.MipLevels!=1 ||
       s.SampleDesc.Count!=1 || s.SampleDesc.Quality!=0 ||
       !bgra8(s.Format) || !(s.Flags&D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) ||
       !stereo_destination_valid(d,s.Width,s.Height)) return false;

    Microsoft::WRL::ComPtr<ID3D12Device> sd,dd,cd;
    if(FAILED(mono_composite->GetDevice(IID_PPV_ARGS(&sd))) ||
       FAILED(openxr_doublewide->GetDevice(IID_PPV_ARGS(&dd))) ||
       FAILED(cmd->GetDevice(IID_PPV_ARGS(&cd))) ||
       sd.Get()!=device || dd.Get()!=device || cd.Get()!=device) return false;

    D3D12_RESOURCE_BARRIER transitions[2]{};
    UINT count=0;
    auto add_barrier=[&](ID3D12Resource* r,D3D12_RESOURCE_STATES before,
                         D3D12_RESOURCE_STATES after) {
        if(before==after) return;
        auto& b=transitions[count++];
        b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};
    };
    add_barrier(mono_composite,mono_state,D3D12_RESOURCE_STATE_COPY_SOURCE);
    add_barrier(openxr_doublewide,destination_state,D3D12_RESOURCE_STATE_COPY_DEST);
    if(count) cmd->ResourceBarrier(count,transitions);

    const D3D12_TEXTURE_COPY_LOCATION from{mono_composite,D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
    const D3D12_TEXTURE_COPY_LOCATION to{openxr_doublewide,D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
    const UINT w=static_cast<UINT>(s.Width);
    const D3D12_BOX box{0,0,0,w,s.Height,1};
    cmd->CopyTextureRegion(&to,0,0,0,&from,&box);
    cmd->CopyTextureRegion(&to,w,0,0,&from,&box);

    for(UINT i=0;i<count;++i) {
        std::swap(transitions[i].Transition.StateBefore,
                  transitions[i].Transition.StateAfter);
    }
    if(count) cmd->ResourceBarrier(count,transitions);
    return true;
}
} // namespace uevr::duoview::dx12

```

## FILE src/mods/vr/DuoViewPSVR2Gaze.hpp (171 lines)
```cpp
#pragma once
// Stage 5: Joey DuoView PSVR2 Toolkit CAPI reader. No driver or OpenXR layer replacement.
// ABI: BnuuySolutions/PSVR2Toolkit projects/common/hmd2_gaze.h (328 bytes).
#include "DuoViewGaze.hpp"
#include <windows.h>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>
#ifdef _MSC_VER
#pragma comment(lib, "Advapi32.lib")
#endif
namespace uevr::duoview::psvr2 {
enum class Bool : uint32_t { no, yes };
struct Vec2 { float x,y; };
struct Vec3 { float x,y,z; };
struct Lens { Vec3 left,right; };
enum class EnabledEye : uint8_t { left,right,both };
struct WearableEye {
    Bool origin_valid; Vec3 origin_mm;
    Bool direction_valid; Vec3 direction;
    Bool pupil_diameter_valid; float pupil_diameter_mm;
    Bool pupil_position_valid; Vec2 pupil_position;
    Bool guide_valid; Vec2 guide;
    Bool blink_valid; Bool blink;
};
struct Wearable {
    int64_t timestamp; uint32_t frame_counter;
    WearableEye left,right;
    Bool combined_origin_valid; Vec3 combined_origin;
    Bool combined_direction_valid; Vec3 combined_direction;
    Bool convergence_distance_valid;
};
struct Foveated {
    int64_t timestamp; uint32_t frame_counter; uint32_t tracking_state;
    Vec3 left,right,combined; float convergence_distance_mm;
};
struct Status {
    uint8_t magic[2]; uint16_t version; uint32_t size;
    float exposure_l,exposure_r;
    uint32_t led_status,exposure_counter_l,exposure_counter_r,led_counter;
    int32_t dsp_result; Lens lens; uint32_t calibration_id; Vec3 gaze_origin;
    EnabledEye eye; uint8_t motor_sequence,motor_strength;
    Wearable raw; Foveated tracked;
};
static_assert(sizeof(Status)==0x148,"PSVR2 Toolkit CAPI gaze ABI mismatch");
using InitFn = int(__cdecl*)();
using ReadFn = bool(__cdecl*)(Status*,uint32_t);

// Toolkit native basis X-left, Y-up, Z-forward -> common Mono X-right, Y-up, Z-forward.
inline std::optional<Ray> calibrated_ray(const Status& s) {
    if (s.size!=sizeof(Status) || s.magic[0]!='G' || s.magic[1]!='S' ||
        s.raw.combined_direction_valid!=Bool::yes ||
        (s.raw.left.blink_valid==Bool::yes && s.raw.left.blink==Bool::yes) ||
        (s.raw.right.blink_valid==Bool::yes && s.raw.right.blink==Bool::yes)) return {};
    const auto& d=s.raw.combined_direction;
    const float norm=std::sqrt(d.x*d.x+d.y*d.y+d.z*d.z);
    if (!std::isfinite(norm)||norm<.5f||norm>1.5f||d.z<.10f) return {};
    return Ray{-d.x/norm,d.y/norm,d.z/norm};
}

// Projection from Joey's actual shared Mono perspective, not a generic OpenXR matrix.
// Joey OpenXR::update_matrices creates a +Z-forward Unreal projection (p[11] == +1).
// A direction has no translation component; source gaze is already +forward.
inline std::optional<UV> projection_uv(const Ray& r,const std::array<float,16>& p) {
    if (!std::isfinite(r.right)||!std::isfinite(r.up)||
        !std::isfinite(r.forward)||r.forward<=.1f) return {};
    for(float x:p) if(!std::isfinite(x)) return {};
    const float x=p[0]*r.right+p[4]*r.up+p[8]*r.forward;
    const float y=p[1]*r.right+p[5]*r.up+p[9]*r.forward;
    const float w=p[3]*r.right+p[7]*r.up+p[11]*r.forward;
    if(!std::isfinite(w)||w<=.01f) return {};
    const float u=(x/w+1.f)*.5f, v=(1.f-y/w)*.5f;
    if(!std::isfinite(u)||!std::isfinite(v)) return {};
    return UV{std::clamp(u,0.f,1.f),std::clamp(v,0.f,1.f)};
}

struct Counters {
    uint64_t fresh{}, reused{}, invalid{}, expired{}, unavailable{};
    uint32_t age_ms{};
};
class Reader {
public:
    void set_recovery_controls(uint32_t hold_ms, uint32_t reacquire_samples) {
        std::scoped_lock lock{mutex_};
        recovery_.controls(hold_ms, reacquire_samples);
    }
    bool active() const { return active_.load(std::memory_order_acquire); }
    Counters counters() const {
        return {fresh_.load(std::memory_order_relaxed),reused_.load(std::memory_order_relaxed),
            invalid_.load(std::memory_order_relaxed),expired_.load(std::memory_order_relaxed),
            unavailable_.load(std::memory_order_relaxed),age_ms_.load(std::memory_order_relaxed)};
    }
    // Called ONLY for a new DuoView source-frame snapshot, not per eye or compositor.
    std::optional<UV> read_uv(const std::array<float,16>& projection,
                              const std::array<float,9>& optical_rotation) {
        std::scoped_lock lock{mutex_};
        const uint64_t now=GetTickCount64();
        if(!read_ && now>=next_attempt_) { initialize(); next_attempt_=now+1000; }
        if(!read_) {
            unavailable_.fetch_add(1,std::memory_order_relaxed);
            active_.store(false,std::memory_order_release); return {};
        }
        Status candidate{};
        const bool fresh=read_(&candidate,0);
        const auto sample = fresh ? calibrated_ray(candidate) : std::optional<Ray>{};
        const bool invalid = fresh && !sample.has_value();
        if (invalid) invalid_.fetch_add(1,std::memory_order_relaxed);
        const auto held = recovery_.update(now, sample, invalid);
        if (sample && !invalid)
            fresh_.fetch_add(1,std::memory_order_relaxed);
        if (!held) {
            age_ms_.store(UINT32_MAX,std::memory_order_relaxed);
            expired_.fetch_add(1,std::memory_order_relaxed);
            active_.store(false,std::memory_order_release);
            return {};
        }
        age_ms_.store(recovery_.age_ms(now),std::memory_order_relaxed);
        if (!fresh || invalid) reused_.fetch_add(1,std::memory_order_relaxed);
        const auto ray=optical_ray(*held,optical_rotation);
        const auto uv=ray ? projection_uv(*ray,projection) : std::optional<UV>{};
        active_.store(uv.has_value(),std::memory_order_release);
        return uv;
    }
private:
    void initialize() {
        if(!module_) {
            module_=GetModuleHandleW(L"psvr2_toolkit_capi.dll");
            wchar_t path[32768]{};
            const DWORD n=GetEnvironmentVariableW(L"PSVR2TK_CAPI_PATH",path,32768);
            if(!module_ && n && n<32768)
                module_=LoadLibraryExW(path,nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
            if(!module_) try {
                std::ifstream file(std::filesystem::temp_directory_path()/"psvr2tk_capi_path.txt");
                std::string dir;
                if(file && std::getline(file,dir) && !dir.empty()) {
                    const auto f=std::filesystem::path(dir)/"psvr2_toolkit_capi.dll";
                    module_=LoadLibraryExW(f.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
                }
            } catch(...) {}
            if(!module_) {
                wchar_t steam[32768]{};DWORD bytes=sizeof(steam);
                if(RegGetValueW(HKEY_CURRENT_USER,L"Software\\Valve\\Steam",L"SteamPath",
                    RRF_RT_REG_SZ,nullptr,steam,&bytes)==ERROR_SUCCESS) {
                    const std::wstring f=std::wstring(steam)+
                        L"\\steamapps\\common\\PlayStation VR2 App\\SteamVR_Plug-In\\bin\\win64\\psvr2_toolkit_capi.dll";
                    module_=LoadLibraryExW(f.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
                }
            }
            if(!module_) module_=LoadLibraryW(L"psvr2_toolkit_capi.dll");
        }
        if(!module_) return;
        auto init=reinterpret_cast<InitFn>(GetProcAddress(module_,"psvr2_toolkit_init"));
        auto read=reinterpret_cast<ReadFn>(GetProcAddress(module_,"psvr2_toolkit_gaze_status"));
        if(init && read && init()==0) read_=read;
    }
    mutable std::mutex mutex_{};
    std::atomic<bool> active_{false};
    std::atomic<uint64_t> fresh_{0},reused_{0},invalid_{0},expired_{0},unavailable_{0};
    std::atomic<uint32_t> age_ms_{UINT32_MAX};
    HMODULE module_{};
    ReadFn read_{};
    uint64_t next_attempt_{};
    RayRecovery recovery_{};
};
} // namespace uevr::duoview::psvr2

```

## FILE src/mods/vr/DuoViewShaderSource.hpp (43 lines)
```cpp
#pragma once
// HLSL precompiled by Windows SDK fxc.exe in CI; no runtime D3DCompile.
namespace uevr::duoview::dx12 {
inline constexpr unsigned char vertex_shader_bytecode[] = {
    0x44, 0x58, 0x42, 0x43, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};
inline constexpr unsigned char pixel_shader_bytecode[] = {
    0x44, 0x58, 0x42, 0x43, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};
inline constexpr unsigned char native_pixel_shader_bytecode[] = {
    0x44, 0x58, 0x42, 0x43, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};
}

```

## FILE src/mods/vr/DuoViewState.hpp (147 lines)
```cpp
#pragma once
#include "DuoViewConfig.hpp"
#include "DuoViewCropStability.hpp"
#include <array>
#include <functional>

namespace uevr::duoview {
struct CameraPose {
    std::array<double, 3> rotation{}, position{};
    bool operator==(const CameraPose&) const = default;
};
struct ViewFrame {
    FrameConfig config;
    std::array<float, 16> projection{};
    CameraPose camera{};
    std::optional<uint32_t> mono_source_frame{};
    bool camera_valid{}, main_family{}, consumed{}, gaze_valid{}, invalid{};
    std::array<bool, 2> rectangles{}, projections{}, cameras{};
    std::array<uintptr_t,2> scene_states{};
    bool shading_applied{};
};

struct NativeFrameBinding {
    FrameKey key{};
    uint32_t mono_source_frame{};
};

// Bind the Native packet to the exact OpenXR pose/projection frame observed at
// source creation. The Mono token is carried explicitly; it is not derived
// from the later DuoView producer key.
inline std::optional<NativeFrameBinding> native_frame_binding(const ViewFrame& frame) {
    if (!frame.config.key.generation || !frame.config.key.frame || !frame.mono_source_frame ||
        frame.invalid || frame.consumed || !frame.main_family || !frame.camera_valid) return {};
    for (size_t i = 0; i != 2; ++i) {
        if (!frame.rectangles[i] || !frame.projections[i] || !frame.cameras[i]) return {};
    }
    return NativeFrameBinding{frame.config.key, *frame.mono_source_frame};
}

template<typename Matrix>
void apply_frame_projection(Matrix& matrix, const ViewFrame& frame, unsigned view) {
    for (int col=0;col<4;++col) for (int row=0;row<4;++row)
        matrix[col][row]=frame.projection[col*4+row];
    if (view==frame.config.settings.fovea_view) apply_foveal_crop(matrix,frame.config.layout);
}
class State {
public:
    bool configure(Settings settings) { std::scoped_lock lock{mutex_}; return config_.set_settings(settings); }
    Settings settings() const { return config_.current_settings(); }
    std::optional<ViewFrame> begin(FrameKey key, uint32_t w, uint32_t h,
        const std::array<float, 16>& projection, const std::function<std::optional<UV>()>& read_gaze,
        uint64_t now_ms=0, std::optional<uint32_t> mono_source_frame={}) {
        std::scoped_lock lock{mutex_};
        auto& slot = frames_[key.frame % frames_.size()];
        if (slot && slot->config.key == key) return slot;
        if (key.generation<last_begin_.generation ||
            (key.generation==last_begin_.generation && key.frame<=last_begin_.frame)) return {};
        for (float x:projection) if (!std::isfinite(x)) return {};
        const auto s = config_.current_settings();
        const auto gaze = s.eye_tracked ? read_gaze() : std::optional<UV>{UV{}};
        auto stability=stability_;
        const auto center=stability.update(key,w,h,s,gaze,now_ms);
        const auto frozen = config_.for_frame(key, w, h, center);
        if (!frozen) return {};
        stability_=stability; last_begin_=key;
        slot = ViewFrame{*frozen, projection};
        slot->mono_source_frame = mono_source_frame;
        slot->gaze_valid = s.eye_tracked && gaze.has_value();
        return slot;
    }
    std::optional<ViewFrame> snapshot(FrameKey key) const {
        std::scoped_lock lock{mutex_};
        const auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key) return {};
        return slot;
    }
    bool rectangle(FrameKey key, unsigned view) { return observe(key, view, 0); }
    bool projection(FrameKey key, unsigned view) { return observe(key, view, 1); }
    bool scene(FrameKey key, unsigned view, uintptr_t state, bool shading_applied=false) {
        std::scoped_lock lock{mutex_};
        auto& slot=frames_[key.frame%frames_.size()];
        if (!slot || slot->config.key!=key || view>1 || slot->invalid || slot->consumed) return false;
        slot->scene_states[view]=state;
        if (view==1) slot->shading_applied=shading_applied;
        return true;
    }
    bool can_independent_shading(FrameKey key, uintptr_t secondary_state) const {
        std::scoped_lock lock{mutex_};
        const auto& slot=frames_[key.frame%frames_.size()];
        return slot && slot->config.key==key && !slot->invalid && !slot->consumed &&
            slot->config.settings.independent_shading && slot->camera_valid &&
            slot->rectangles[0] && slot->rectangles[1] && slot->projections[0] && slot->projections[1] &&
            slot->scene_states[0] && secondary_state && slot->scene_states[0]!=secondary_state;
    }
    std::optional<CameraPose> camera(FrameKey key, unsigned view) const {
        std::scoped_lock lock{mutex_};
        const auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key || view > 1 || slot->invalid || !slot->camera_valid) return {};
        return slot->camera;
    }
    bool camera(FrameKey key, unsigned view, const CameraPose& pose) {
        std::scoped_lock lock{mutex_};
        auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key || view > 1 || slot->invalid) return false;
        for (auto x : pose.rotation) if (!std::isfinite(x)) return false;
        for (auto x : pose.position) if (!std::isfinite(x)) return false;
        if (!slot->camera_valid) { slot->camera = pose; slot->camera_valid = true; }
        else if (slot->camera != pose) { slot->invalid = true; return false; }
        slot->cameras[view] = true;
        return true;
    }
    bool family(FrameKey key, bool main, unsigned count) {
        std::scoped_lock lock{mutex_};
        auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key || !main || count != 2) return false;
        slot->main_family = true;
        return true;
    }
    std::optional<ViewFrame> consume(FrameKey key) {
        std::scoped_lock lock{mutex_};
        auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key || slot->consumed || slot->invalid || !slot->main_family ||
            !slot->camera_valid || !slot->rectangles[0] || !slot->rectangles[1] ||
            !slot->projections[0] || !slot->projections[1] || !slot->cameras[0] || !slot->cameras[1]) return {};
        slot->consumed = true;
        return slot;
    }
    void retire() {
        std::scoped_lock lock{mutex_};
        frames_ = {}; config_.retire(); stability_.reset(); last_begin_={};
    }
private:
    bool observe(FrameKey key, unsigned view, int kind) {
        std::scoped_lock lock{mutex_};
        auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key || view > 1 || slot->invalid || slot->consumed) return false;
        (kind == 0 ? slot->rectangles : slot->projections)[view] = true;
        return true;
    }
    mutable std::mutex mutex_;
    ConfigLatch config_;
    CropStability stability_;
    FrameKey last_begin_{};
    std::array<std::optional<ViewFrame>, 16> frames_{};
};
}


```

## FILE src/mods/vr/HeadMovementScaling.hpp (15 lines)
```cpp
#pragma once

namespace uevr::head_movement {

// Gains describe recentered player axes, not the runtime's arbitrary room axes.
// Keep this before the game's view rotation and after the recenter rotation.
// Do not use the live HMD orientation: looking around must not move the camera.
template<class Rotation, class Vector>
Vector scale_translation(const Rotation& recenter, const Vector& tracking_delta,
                         const Vector& gains) {
    const Vector aligned = recenter * tracking_delta;
    return Vector{aligned.x * gains.x, aligned.y * gains.y, aligned.z * gains.z};
}

} // namespace uevr::head_movement

```

## FILE src/mods/vr/QuadViewD3D12.hpp (824 lines)
```cpp
#pragma once

#include <d3d12.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include "QuadViewGeometry.hpp"
#include "QuadViewSettings.hpp"
#include "QuadViewSnapshot.hpp"
#include "QuadViewShaderBytecode.hpp"
#include <array>
#include <atomic>
#include <cmath>
#include <cstring>
#include <memory>
#include <utility>
#include <chrono>
#include <ctime>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace uevr::quadview::dx12 {

using Microsoft::WRL::ComPtr;

inline std::atomic<float>& last_seam_analysis_milliseconds() {
    static std::atomic<float> value{-1.f};
    return value;
}

struct alignas(16) ShaderConstants {
    uint32_t eye_and_atlas[4]{};
    uint32_t rectangles[4][4]{};
    float crops[2][4]{};
    float options[4]{};
    float sharpen[4]{};
    float sharpen_eye[4]{}; // left/right strength, left/right change limiter
    float context_h[2][12]{{1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f},
                           {1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f}};
    uint32_t context_source[4]{0, 1, 0, 0};
    float depth_shift[4]{};     // B7
    uint32_t depth_rect[4]{};   // B7
    uint32_t depth_options[4]{}; // B7
    float depth_eye_origin[2][4]{};
    float depth_projection[4]{};
    float depth_coefficients[4]{};
    float depth_jitter[4]{};
    float seam[4]{};
    float seam_options[4]{};
    float seam_local[4]{};
    float focus_lift[4]{};
    float edge_v2[4]{};
    uint32_t edge_history[4]{};
    float focus_profile[4]{};
};
static_assert(sizeof(ShaderConstants) == 512);
static_assert(sizeof(ShaderConstants) <= 512); // slot-local, CB-aligned allocation

// B7: optional periphery depth for reprojection. texture is R32_TYPELESS and
// stays in D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE between uses.

// B35: one tiny state object per XR session. Every compositor retains it,
// including while in flight. It is touched only by command lists explicitly
// pinned to queue. State remains UAV; pixels consume a slot-local copy.
struct EdgeHistoryState {
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12Resource> buffer;
    static std::shared_ptr<EdgeHistoryState> create(ID3D12Device* device, ID3D12CommandQueue* queue) {
        if (!device || !queue) return {};
        auto state=std::make_shared<EdgeHistoryState>();
        state->device=device; state->queue=queue;
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC desc{};
        desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width=64u*3u*4u*sizeof(float);
        desc.Height=desc.DepthOrArraySize=desc.MipLevels=1;
        desc.SampleDesc.Count=1; desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        // Committed resources are zero initialized (no CREATE_NOT_ZEROED).
        if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&state->buffer)))) return {};
        state->buffer->SetName(L"TriView B35 queue-owned edge history");
        return state;
    }
};

struct SnapshotItem {
    Microsoft::WRL::ComPtr<ID3D12Resource> buffer;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT rows{};
    UINT64 row_bytes{};
    std::string name;
};

// Concrete DXGI format for a viewer (typeless -> the view format we sample with).
inline DXGI_FORMAT snapshot_file_format(DXGI_FORMAT f) {
    switch (f) {
    case DXGI_FORMAT_R8G8B8A8_TYPELESS: return DXGI_FORMAT_R8G8B8A8_UNORM;
    case DXGI_FORMAT_B8G8R8A8_TYPELESS: return DXGI_FORMAT_B8G8R8A8_UNORM;
    case DXGI_FORMAT_R10G10B10A2_TYPELESS: return DXGI_FORMAT_R10G10B10A2_UNORM;
    case DXGI_FORMAT_R16G16B16A16_TYPELESS: return DXGI_FORMAT_R16G16B16A16_FLOAT;
    case DXGI_FORMAT_R32_TYPELESS: return DXGI_FORMAT_R32_FLOAT;
    default: return f;
    }
}

inline bool write_snapshot_dds(const std::filesystem::path& file, const SnapshotItem& item) {
    void* data{};
    const UINT64 wanted = item.footprint.Offset + UINT64(item.footprint.Footprint.RowPitch) * (item.rows ? item.rows - 1 : 0) + item.row_bytes;
    const D3D12_RANGE range{0, SIZE_T((std::min)(wanted, item.buffer->GetDesc().Width))};
    if (FAILED(item.buffer->Map(0, &range, &data)) || !data) return false;
    std::ofstream out(file, std::ios::binary);
    uint32_t header[32]{};
    header[0] = 124; header[1] = 0x1 | 0x2 | 0x4 | 0x8 | 0x1000; // caps|height|width|pitch|pixelformat
    header[2] = item.footprint.Footprint.Height; header[3] = item.footprint.Footprint.Width;
    header[4] = uint32_t(item.row_bytes);
    header[18] = 32; header[19] = 0x4; header[20] = 0x30315844; // DDPF_FOURCC 'DX10'
    header[26] = 0x1000;
    const uint32_t dx10[5]{uint32_t(snapshot_file_format(item.footprint.Footprint.Format)), 3u, 0u, 1u, 0u};
    out.write("DDS ", 4);
    out.write(reinterpret_cast<const char*>(header), 124);
    out.write(reinterpret_cast<const char*>(dx10), sizeof(dx10));
    const auto* bytes = static_cast<const char*>(data) + item.footprint.Offset;
    for (UINT row = 0; row < item.rows; ++row)
        out.write(bytes + UINT64(row) * item.footprint.Footprint.RowPitch, std::streamsize(item.row_bytes));
    const D3D12_RANGE no_write{0, 0};
    item.buffer->Unmap(0, &no_write);
    return bool(out);
}

struct DepthInput {
    ID3D12Resource* texture{};
    DXGI_FORMAT srv_format{DXGI_FORMAT_R32_FLOAT}; // R32_FLOAT or R32_FLOAT_X8X24_TYPELESS
    uint32_t rect[4]{};
    float shift[4]{};
    bool reproject{}, show{};
    // Offset from unjittered context color UV to the matching depth sample UV.
    // Capture must provide the NGX jitter sign/normalization; unknown disables warp.
    float jitter_uv[2]{};
    bool jitter_valid{};
    std::shared_ptr<const void> keepalive{};
};

// Each instance belongs to one fence-retired OpenXR command slot. Descriptor
// and upload storage cannot be reused until the owning slot's fence retires.
class Compositor {
public:
    Compositor() = default;
    Compositor(const Compositor&) = delete;
    Compositor& operator=(const Compositor&) = delete;
    ~Compositor() { if (constants_ && mapped_) constants_->Unmap(0, nullptr); }

    static DXGI_FORMAT sampling_format(DXGI_FORMAT format) {
        switch (format) {
        case DXGI_FORMAT_R8G8B8A8_TYPELESS: return DXGI_FORMAT_R8G8B8A8_UNORM;
        case DXGI_FORMAT_B8G8R8A8_TYPELESS: return DXGI_FORMAT_B8G8R8A8_UNORM;
        case DXGI_FORMAT_R10G10B10A2_TYPELESS: return DXGI_FORMAT_R10G10B10A2_UNORM;
        case DXGI_FORMAT_R16G16B16A16_TYPELESS: return DXGI_FORMAT_R16G16B16A16_FLOAT;
        default: return format;
        }
    }

    const char* error() const { return error_; }
    bool prepared() const { return device_ && root_ && pipeline_ && seam_pipeline_ && seam_stats_ && mapped_; }
    bool commands_recorded() const { return recorded_; }
    void set_edge_history(std::shared_ptr<EdgeHistoryState> state) { if (!owner_) edge_history_=std::move(state); }
    ID3D12CommandQueue* edge_submission_queue() const { return edge_history_ ? edge_history_->queue.Get() : nullptr; }


    bool prewarm(ID3D12Device* device, DXGI_FORMAT source_srv_format, DXGI_FORMAT output_format,
                 UINT64 timestamp_frequency = 0) {
        if (!device || source_srv_format == DXGI_FORMAT_UNKNOWN || output_format == DXGI_FORMAT_UNKNOWN)
            return fail("Invalid prewarm device or formats");
        if (owner_) return fail("Cannot recreate an in-flight compositor");
        if (prepared() && device_.Get() == device && source_format_ == source_srv_format && output_format_ == output_format) {
            setup_timing(device,timestamp_frequency);
            return true;
        }
        if (mapped_ && constants_) constants_->Unmap(0, nullptr);
        mapped_ = nullptr;
        constants_.Reset(); root_.Reset(); pipeline_.Reset(); srv_heap_.Reset(); rtv_heap_.Reset();
        seam_pipeline_.Reset(); seam_stats_.Reset();
        queries_.Reset(); timestamps_.Reset(); frequency_=0; timing_pending_=false; gpu_ms_=-1.f; seam_gpu_ms_=-1.f; timed_seam_active_=false;
        device_ = device;
        source_format_ = source_srv_format;
        output_format_ = output_format;

        D3D12_FEATURE_DATA_FORMAT_SUPPORT source_support{source_srv_format};
        D3D12_FEATURE_DATA_FORMAT_SUPPORT output_support{output_format};
        if (FAILED(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &source_support, sizeof(source_support))) ||
            FAILED(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &output_support, sizeof(output_support))) ||
            !(source_support.Support1 & D3D12_FORMAT_SUPPORT1_SHADER_SAMPLE) ||
            !(output_support.Support1 & D3D12_FORMAT_SUPPORT1_RENDER_TARGET))
            return fail("Unsupported source sampling or output render-target format");

        D3D12_DESCRIPTOR_RANGE range{};
        range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        range.NumDescriptors = 6; // 4 colors, depth, seam gain/confidence
        D3D12_DESCRIPTOR_RANGE seam_uav{};
        seam_uav.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
        seam_uav.NumDescriptors = 1;
        D3D12_ROOT_PARAMETER parameters[4]{};
        parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
        parameters[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        parameters[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        parameters[1].DescriptorTable.NumDescriptorRanges = 1;
        parameters[1].DescriptorTable.pDescriptorRanges = &range;
        parameters[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        parameters[2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        parameters[2].DescriptorTable.NumDescriptorRanges = 1;
        parameters[2].DescriptorTable.pDescriptorRanges = &seam_uav;
        parameters[2].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        parameters[3].ParameterType=D3D12_ROOT_PARAMETER_TYPE_UAV;
        parameters[3].Descriptor.ShaderRegister=1;
        parameters[3].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
        D3D12_STATIC_SAMPLER_DESC sampler{};
        sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
        sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
        sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        sampler.MaxAnisotropy = 1;
        sampler.MaxLOD = D3D12_FLOAT32_MAX;
        sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        D3D12_ROOT_SIGNATURE_DESC signature{};
        signature.NumParameters = 4;
        signature.pParameters = parameters;
        signature.NumStaticSamplers = 1;
        signature.pStaticSamplers = &sampler;
        signature.Flags = D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT;
        ComPtr<ID3DBlob> serialized, diagnostics;
        if (FAILED(D3D12SerializeRootSignature(&signature, D3D_ROOT_SIGNATURE_VERSION_1, &serialized, &diagnostics)) ||
            FAILED(device->CreateRootSignature(0, serialized->GetBufferPointer(), serialized->GetBufferSize(), IID_PPV_ARGS(&root_))))
            return fail("Could not create QuadView root signature");

        D3D12_GRAPHICS_PIPELINE_STATE_DESC description{};
        description.pRootSignature = root_.Get();
        description.VS = {shaders::vertex, sizeof(shaders::vertex)};
        description.PS = {shaders::pixel, sizeof(shaders::pixel)};
        auto& blend = description.BlendState.RenderTarget[0];
        blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
        blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
        blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
        blend.LogicOp = D3D12_LOGIC_OP_NOOP;
        blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
        description.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
        description.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
        description.RasterizerState.DepthClipEnable = TRUE;
        description.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ZERO;
        description.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        auto& stencil = description.DepthStencilState.FrontFace;
        stencil.StencilFailOp = stencil.StencilDepthFailOp = stencil.StencilPassOp = D3D12_STENCIL_OP_KEEP;
        stencil.StencilFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        description.DepthStencilState.BackFace = stencil;
        description.SampleMask = UINT32_MAX;
        description.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        description.NumRenderTargets = 1;
        description.RTVFormats[0] = output_format;
        description.SampleDesc.Count = 1;
        if (FAILED(device->CreateGraphicsPipelineState(&description, IID_PPV_ARGS(&pipeline_))))
            return fail("Could not create QuadView raster pipeline");
        D3D12_COMPUTE_PIPELINE_STATE_DESC analysis{};
        analysis.pRootSignature = root_.Get();
        analysis.CS = {shaders::seam, sizeof(shaders::seam)};
        if (FAILED(device->CreateComputePipelineState(&analysis, IID_PPV_ARGS(&seam_pipeline_))))
            return fail("Could not create QuadView seam analysis pipeline");

        D3D12_DESCRIPTOR_HEAP_DESC heap{};
        heap.NumDescriptors = 7; // six SRVs followed by one seam UAV
        heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        if (FAILED(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&srv_heap_)))) return fail("Could not create QuadView SRV heap");
        heap.NumDescriptors = 1;
        heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
        if (FAILED(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&rtv_heap_)))) return fail("Could not create QuadView RTV heap");
        D3D12_HEAP_PROPERTIES upload{};
        upload.Type = D3D12_HEAP_TYPE_UPLOAD;
        upload.CreationNodeMask = upload.VisibleNodeMask = 1;
        D3D12_RESOURCE_DESC buffer{};
        buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width = 512;
        buffer.Height = buffer.DepthOrArraySize = buffer.MipLevels = 1;
        buffer.SampleDesc.Count = 1;
        buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(device->CreateCommittedResource(&upload, D3D12_HEAP_FLAG_NONE, &buffer,
            D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&constants_)))) return fail("Could not create QuadView constants");
        D3D12_HEAP_PROPERTIES gpu{};
        gpu.Type = D3D12_HEAP_TYPE_DEFAULT;
        gpu.CreationNodeMask = gpu.VisibleNodeMask = 1;
        buffer.Width = 146 * 4 * sizeof(float);
        buffer.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        if (FAILED(device->CreateCommittedResource(&gpu, D3D12_HEAP_FLAG_NONE, &buffer,
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, nullptr, IID_PPV_ARGS(&seam_stats_))))
            return fail("Could not create QuadView slot-local seam statistics");
        D3D12_SHADER_RESOURCE_VIEW_DESC match_srv{};
        match_srv.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
        match_srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        match_srv.Buffer.NumElements = 146;
        match_srv.Buffer.StructureByteStride = 4 * sizeof(float);
        const auto descriptor_stride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        auto match_descriptor = srv_heap_->GetCPUDescriptorHandleForHeapStart();
        match_descriptor.ptr += SIZE_T(5) * descriptor_stride;
        device->CreateShaderResourceView(seam_stats_.Get(), &match_srv, match_descriptor);
        match_descriptor.ptr += descriptor_stride;
        D3D12_UNORDERED_ACCESS_VIEW_DESC match_uav{};
        match_uav.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        match_uav.Buffer.NumElements = 146;
        match_uav.Buffer.StructureByteStride = 4 * sizeof(float);
        device->CreateUnorderedAccessView(seam_stats_.Get(), nullptr, &match_uav, match_descriptor);
        D3D12_RANGE no_read{0, 0};
        if (FAILED(constants_->Map(0, &no_read, &mapped_))) return fail("Could not map QuadView constants");
        constants_->SetName(L"QuadView slot constants");
        seam_stats_->SetName(L"QuadView slot seam gain and confidence");
        root_->SetName(L"QuadView root signature");
        pipeline_->SetName(L"QuadView stereo raster pipeline");
        srv_heap_->SetName(L"QuadView slot SRV");
        rtv_heap_->SetName(L"QuadView slot RTV");
        setup_timing(device,timestamp_frequency);
        error_ = "";
        return true;
    }

    void on_slot_retired() {
        // Call only after the owning command-context fence proves every query
        // and resource reference in this slot has completed.
        read_timing();
        flush_snapshot();
        owner_.reset();
        depth_keepalive_.reset();
        for (auto& source : sources_) source.Reset();
        destination_.Reset();
        recorded_ = false;
    }
    float gpu_milliseconds() const { return gpu_ms_; }
    float seam_gpu_milliseconds() const { return seam_gpu_ms_; }
    UINT64 timing_frequency() const { return frequency_; }
    bool timing_ready() const { return queries_ && timestamps_ && frequency_; }

    bool record(ID3D12GraphicsCommandList* commands, ID3D12Resource* source, ID3D12Resource* destination,
                const Layout& layout, const Settings& settings,
                D3D12_RESOURCE_STATES source_state, D3D12_RESOURCE_STATES destination_state,
                std::shared_ptr<const void> owner, UINT64 timestamp_frequency = 0) {
        return record_sources(commands, {source, source, source, source}, destination, layout, settings,
            source_state, destination_state, std::move(owner), timestamp_frequency);
    }

    bool record_sources(ID3D12GraphicsCommandList* commands,
                const std::array<ID3D12Resource*, 4>& sources, ID3D12Resource* destination,
                const Layout& layout, const Settings& settings,
                D3D12_RESOURCE_STATES source_state, D3D12_RESOURCE_STATES destination_state,
                std::shared_ptr<const void> owner, UINT64 timestamp_frequency = 0,
                const DepthInput* depth = nullptr, uint64_t scene_generation = 0, uint32_t history_time_ms = 0) {
        recorded_ = false;
        if (!prepared() || !commands || !destination || !sources[0] || !sources[1] || !sources[2] || !sources[3] || !owner)
            return fail("Unprepared compositor or invalid source/destination ownership");
        if (owner_) return fail("Compositor command slot has not retired");
        if (timing_pending_) return fail("Previous timestamp query has not retired");
        const auto checked_settings = reconcile_settings(settings, settings,
            layout.eye_width,layout.eye_height);
        if (!valid_layout(layout) || checked_settings.rejected || !same_settings(checked_settings.settings, settings))
            return fail("Invalid QuadView layout or debug controls");
        const auto output = destination->GetDesc();
        // B6: compact sources have per-role extents; atlas layouts keep 2W x H for all four.
        const auto extents = source_extents(layout);
        for (size_t index = 0; index != sources.size(); ++index) {
            auto* source = sources[index];
            if (source == destination) return fail("Source aliases the compositor destination");
            const auto input = source->GetDesc();
            if (input.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || output.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
                input.Width != extents[index][0] || input.Height != extents[index][1] ||
                output.Width != layout.eye_width * 2ull || output.Height != layout.eye_height ||
                input.SampleDesc.Count != 1 || output.SampleDesc.Count != 1 ||
                input.DepthOrArraySize != 1 || output.DepthOrArraySize != 1 ||
                (input.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
                !(output.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) || !compatible_source(output.Format, output_format_) ||
                !compatible_source(input.Format, source_format_)) return fail("Source or destination texture does not match prepared QuadView layout/formats");
        }

        ShaderConstants constants{};
        constants.eye_and_atlas[0] = layout.eye_width; constants.eye_and_atlas[1] = layout.eye_height;
        constants.eye_and_atlas[2] = layout.atlas_width; constants.eye_and_atlas[3] = layout.atlas_height;
        for (unsigned view = 0; view < 4; ++view) {
            // Tri-view: both eyes read the one shared centre context (view 0).
            const auto rect = color_source_rect(layout,view == 1 && layout.shared_context ? 0 : view);
            constants.rectangles[view][0] = rect.x; constants.rectangles[view][1] = rect.y;
            constants.rectangles[view][2] = rect.width; constants.rectangles[view][3] = rect.height;
        }
        for (unsigned eye = 0; eye != 2; ++eye) {
            const auto& crop = layout.focus_crops[eye];
            constants.crops[eye][0] = crop.u0; constants.crops[eye][1] = crop.v0;
            constants.crops[eye][2] = crop.u1; constants.crops[eye][3] = crop.v1;
        }
        for (unsigned eye = 0; eye != 2; ++eye)
            for (unsigned i = 0; i != 12; ++i) constants.context_h[eye][i] = layout.context_h[eye][i];
        constants.context_source[1] = layout.shared_context ? 0u : 1u;
        constants.options[0] = settings.feather_fraction;
        constants.options[1] = static_cast<float>(settings.diagnostic_view);
        const bool output_srgb = output_format_ == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
                                 output_format_ == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
        const bool encoded_unorm = source_format_ == DXGI_FORMAT_B8G8R8A8_UNORM ||
                                   source_format_ == DXGI_FORMAT_R8G8B8A8_UNORM;
        constants.options[2] = output_srgb && encoded_unorm ? 1.f : 0.f;
        constants.options[3] = settings.debug_border ? 1.f : 0.f;
        constants.sharpen[0] = settings.sharpen_strength;
        constants.sharpen[1] = 1.f + 2.f + (encoded_unorm ? 4.f : 0.f);
        constants.sharpen[2] = settings.sharpen_max_change;
        constants.sharpen[3] = .02f;
        // B8: initial stereo-matched defaults for portable compositor tests.
        // The post-B7 B8 backend patch replaces these with independent saved eye settings.
        constants.sharpen_eye[0] = settings.sharpen_strength;
        constants.sharpen_eye[1] = settings.sharpen_link_right ? settings.sharpen_strength : settings.sharpen_right_strength;
        constants.sharpen_eye[2] = settings.sharpen_max_change;
        constants.sharpen_eye[3] = settings.sharpen_link_right ? settings.sharpen_max_change : settings.sharpen_right_max_change;
        // Requested and bound are independent: missing/invalid depth must still
        // produce the explicit diagnostic, including non-shared layouts.
        constants.depth_options[1] = depth && depth->show ? 1u : 0u;
        bool depth_bound = false;
        if (depth && (depth->reproject || depth->show) && !depth->texture) last_depth_state().store(3u, std::memory_order_relaxed);
        if (depth && depth->texture && layout.shared_context && (depth->reproject || depth->show)) {
            const auto d = depth->texture->GetDesc();
            const bool finite = std::isfinite(depth->shift[0]) && std::isfinite(depth->shift[1]) &&
                std::isfinite(depth->shift[2]) && std::isfinite(depth->shift[3]);
            const bool format_ok = (d.Format == DXGI_FORMAT_R32_TYPELESS && depth->srv_format == DXGI_FORMAT_R32_FLOAT) ||
                (d.Format == DXGI_FORMAT_R32G8X24_TYPELESS && depth->srv_format == DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS);
            if (d.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && format_ok &&
                depth->rect[2] && depth->rect[3] && finite &&
                uint64_t(depth->rect[0]) + depth->rect[2] <= d.Width && uint64_t(depth->rect[1]) + depth->rect[3] <= d.Height) {
                for (unsigned i = 0; i != 4; ++i) { constants.depth_shift[i] = depth->shift[i]; constants.depth_rect[i] = depth->rect[i]; }
                // B11: missing jitter is treated as zero (sub-texel error on the
                // low-resolution periphery depth) instead of silently disabling the warp.
                const bool jitter_ok=depth->jitter_valid && std::isfinite(depth->jitter_uv[0]) && std::isfinite(depth->jitter_uv[1]) &&
                    std::abs(depth->jitter_uv[0]) < 0.25f && std::abs(depth->jitter_uv[1]) < 0.25f;
                constants.depth_options[0] = depth->reproject && layout.depth_geometry_valid ? 1u : 0u;
                last_depth_state().store(!depth->reproject ? 4u : layout.depth_geometry_valid ? 1u : 2u, std::memory_order_relaxed);
                for (unsigned eye=0;eye<2;++eye) for (unsigned axis=0;axis<4;++axis)
                    constants.depth_eye_origin[eye][axis]=layout.depth_eye_origin[eye][axis];
                for (unsigned axis=0;axis<4;++axis) {
                    constants.depth_projection[axis]=layout.depth_projection[axis];
                    constants.depth_coefficients[axis]=layout.depth_coefficients[axis];
                }
                constants.depth_jitter[0]=jitter_ok ? depth->jitter_uv[0] : 0.f;
                constants.depth_jitter[1]=jitter_ok ? depth->jitter_uv[1] : 0.f;
                constants.depth_options[2] = 1u; // validated depth is bound
                depth_bound = true;
            }
        }
        constants.seam[0] = static_cast<float>(settings.seam_mode);
        constants.seam[1] = settings.seam_strength;
        constants.seam[2] = settings.seam_max_gain;
        // Approximate EV control in encoded UNORM; no per-pixel pow. Adaptive
        // estimates themselves compare/apply in the exact same sampled domain.
        constants.seam[3] = std::exp2(settings.seam_brightness_ev / (encoded_unorm ? 2.2f : 1.f));
        constants.seam_options[0] = settings.seam_color_strength;
        constants.seam_options[1] = settings.seam_transition_px;
        constants.seam_options[2] = settings.seam_debug ? 1.f : 0.f;
        constants.seam_options[3] = depth && depth->reproject && layout.shared_context &&
            !constants.depth_options[0] ? 0.f : 1.f;
        constants.edge_v2[0]=settings.edge_reach_px;
        constants.edge_v2[1]=settings.edge_fast_px;
        constants.edge_v2[2]=settings.edge_rate;
        constants.edge_v2[3]=settings.edge_hysteresis;
        // Epoch includes appearance/settings and source geometry, never gaze or
        // elapsed time. Crops are checked against previous GPU state separately.
        uint32_t epoch=2166136261u;
        const auto hash_word=[&](uint32_t word) { epoch=(epoch^word)*16777619u; };
        hash_word(static_cast<uint32_t>(scene_generation));
        hash_word(static_cast<uint32_t>(scene_generation>>32u));
        const auto hash_float=[&](float value) { uint32_t bits; std::memcpy(&bits,&value,sizeof(bits)); hash_word(bits); };
        hash_word(settings.seam_mode);
        hash_word(settings.focus_lift_enabled);
        hash_float(settings.focus_brightness); hash_float(settings.focus_lift_strength);
        hash_float(settings.focus_corner_gain); hash_float(settings.focus_lift_onset); hash_float(settings.focus_lift_power);
        for (float v : constants.sharpen_eye) hash_float(v);
        hash_float(settings.edge_rate); hash_float(settings.edge_hysteresis);
        hash_float(settings.edge_reach_px); hash_float(settings.edge_fast_px); hash_float(settings.seam_strength);
        hash_float(settings.seam_transition_px); hash_float(settings.feather_fraction);
        hash_float(settings.ambient_radius_px); hash_float(settings.ambient_inside_px);
        hash_word(settings.ambient_time_ms);
        hash_word(layout.shared_context);
        for (const auto& rect : constants.rectangles) for (auto v : rect) hash_word(v);
        hash_word(layout.eye_width); hash_word(layout.eye_height);
        for (auto* resource : sources) { const auto desc=resource->GetDesc(); hash_word(static_cast<uint32_t>(desc.Width)); hash_word(desc.Height); }
        constants.edge_history[0]=epoch;
        constants.edge_history[1]=history_time_ms ? history_time_ms : static_cast<uint32_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
        constants.edge_history[2]=(settings.seam_mode==4 || settings.seam_mode==5 || settings.seam_mode==6) &&
            edge_history_ && edge_history_->device.Get()==device_.Get() ? 1u : 0u;
        constants.edge_history[3]=settings.ambient_time_ms;
        constants.seam_local[0] = settings.seam_radius_px;
        constants.seam_local[1] = settings.seam_local_strength;
        constants.seam_local[2] = settings.legacy_inward_anchor_px;
        constants.seam_local[3] = settings.legacy_inward_feather ? 1.f : 0.f;
        constants.focus_lift[0]=settings.focus_lift_enabled ? 1.f : 0.f;
        constants.focus_lift[1]=settings.focus_brightness;
        constants.focus_lift[2]=settings.focus_corner_gain-1.f;
        constants.focus_lift[3]=settings.focus_lift_onset;
        constants.focus_profile[0]=settings.focus_lift_power;
        constants.focus_profile[1]=settings.focus_lift_strength;
        constants.focus_profile[2]=settings.ambient_radius_px;
        constants.focus_profile[3]=settings.ambient_inside_px;
        std::memcpy(mapped_, &constants, sizeof(constants));
        D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
        srv.Format = source_format_;
        srv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
        srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        srv.Texture2D.MipLevels = 1;
        // Tri-view never renders source 1: alias its slot to source 0 so it is
        // neither sampled nor transitioned from a state it may not be in.
        auto active = sources;
        if (layout.shared_context) active[1] = sources[0];
        auto descriptor = srv_heap_->GetCPUDescriptorHandleForHeapStart();
        const auto stride = device_->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        for (auto* source : active) {
            device_->CreateShaderResourceView(source, &srv, descriptor);
            descriptor.ptr += stride;
        }
        D3D12_SHADER_RESOURCE_VIEW_DESC depth_srv = srv;
        depth_srv.Format = depth_bound ? depth->srv_format : DXGI_FORMAT_R32_FLOAT;
        depth_srv.Texture2D.PlaneSlice = 0;
        device_->CreateShaderResourceView(depth_bound ? depth->texture : nullptr, &depth_srv, descriptor);
        depth_keepalive_ = depth_bound ? depth->keepalive : nullptr;
        D3D12_RENDER_TARGET_VIEW_DESC rtv_description{};
        rtv_description.Format = output_format_;
        rtv_description.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
        const auto rtv = rtv_heap_->GetCPUDescriptorHandleForHeapStart();
        device_->CreateRenderTargetView(destination, &rtv_description, rtv);
        owner_ = std::move(owner);
        for (size_t i = 0; i != 4; ++i) sources_[i] = sources[i];
        destination_ = destination;
        // Strength zero is visually neutral; skip statistics work unless the
        // confidence diagnostic explicitly needs these values.
        const bool analyze = settings.seam_mode >= 2 &&
            (settings.seam_strength > 0.f || settings.seam_debug) &&
            settings.diagnostic_view == 0 && !(depth && depth->show);
        const auto sample_state = analyze ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE
                                         : D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
        for (size_t i = 0; i != 4; ++i) {
            bool duplicate = false;
            for (size_t j = 0; j < i; ++j) duplicate = duplicate || active[j] == active[i];
            if (!duplicate) barrier(commands, active[i], source_state, sample_state);
        }
        barrier(commands, destination, destination_state, D3D12_RESOURCE_STATE_RENDER_TARGET);
        ID3D12DescriptorHeap* heaps[]{srv_heap_.Get()};
        commands->SetDescriptorHeaps(1, heaps);
        const bool timed=settings.gpu_timing && timestamp_frequency &&
            timestamp_frequency==frequency_ && timing_ready();
        if (timed) {
            timed_seam_active_ = analyze;
            commands->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
        }
        if (analyze) {
            barrier(commands, seam_stats_.Get(), D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            commands->SetPipelineState(seam_pipeline_.Get());
            commands->SetComputeRootSignature(root_.Get());
            commands->SetComputeRootConstantBufferView(0, constants_->GetGPUVirtualAddress());
            commands->SetComputeRootDescriptorTable(1, srv_heap_->GetGPUDescriptorHandleForHeapStart());
            auto uav = srv_heap_->GetGPUDescriptorHandleForHeapStart();
            uav.ptr += UINT64(6) * stride;
            commands->SetComputeRootDescriptorTable(2, uav);
            auto* history=constants.edge_history[2] ? edge_history_->buffer.Get() : seam_stats_.Get();
            commands->SetComputeRootUnorderedAccessView(3,history->GetGPUVirtualAddress());
            if (constants.edge_history[2]) {
                D3D12_RESOURCE_BARRIER order{}; order.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;
                order.UAV.pResource=history; commands->ResourceBarrier(1,&order);
            }
            commands->Dispatch(2, 1, 1);
            if (constants.edge_history[2]) {
                D3D12_RESOURCE_BARRIER order{}; order.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;
                order.UAV.pResource=history; commands->ResourceBarrier(1,&order);
            }
            // The transition orders UAV writes before the pixel SRV read.
            barrier(commands, seam_stats_.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        }
        if (timed) commands->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
        commands->SetPipelineState(pipeline_.Get());
        commands->SetGraphicsRootSignature(root_.Get());
        commands->SetGraphicsRootConstantBufferView(0, constants_->GetGPUVirtualAddress());
        commands->SetGraphicsRootDescriptorTable(1, srv_heap_->GetGPUDescriptorHandleForHeapStart());
        const D3D12_VIEWPORT viewport{0, 0, static_cast<float>(layout.eye_width * 2), static_cast<float>(layout.eye_height), 0, 1};
        const D3D12_RECT scissor{0, 0, static_cast<LONG>(layout.eye_width * 2), static_cast<LONG>(layout.eye_height)};
        commands->RSSetViewports(1, &viewport);
        commands->RSSetScissorRects(1, &scissor);
        commands->OMSetRenderTargets(1, &rtv, FALSE, nullptr);
        commands->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        commands->DrawInstanced(3, 1, 0, 0);
        if (timed) {
            commands->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2);
            commands->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,3,timestamps_.Get(),0);
            timing_pending_=true;
        }
        if (analyze) for (size_t i = 0; i != 4; ++i) {
            bool duplicate = false;
            for (size_t j = 0; j < i; ++j) duplicate = duplicate || active[j] == active[i];
            if (!duplicate) barrier(commands, active[i], sample_state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        }
        if (snapshot_.empty() && snapshot_requested().exchange(false))
            capture_snapshot(commands, active, destination, depth_bound ? depth : nullptr, layout, constants);
        for (size_t i = 0; i != 4; ++i) {
            bool duplicate = false;
            for (size_t j = 0; j < i; ++j) duplicate = duplicate || active[j] == active[i];
            if (!duplicate) barrier(commands, active[i], D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, source_state);
        }
        barrier(commands, destination, D3D12_RESOURCE_STATE_RENDER_TARGET, destination_state);
        recorded_ = true;
        error_ = "";
        return true;
    }

private:
    bool fail(const char* message) { error_ = message; return false; }

    template <typename Constants>
    void capture_snapshot(ID3D12GraphicsCommandList* commands, const std::array<ID3D12Resource*, 4>& active,
                          ID3D12Resource* destination, const DepthInput* depth, const Layout& layout, const Constants& constants) {
        struct Source { ID3D12Resource* resource; D3D12_RESOURCE_STATES state; const char* name; };
        std::vector<Source> list{{destination, D3D12_RESOURCE_STATE_RENDER_TARGET, "eyes_final"},
                                 {active[0], D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, "src0_periphery"},
                                 {active[2], D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, "src2_fovea_left"},
                                 {active[3], D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, "src3_fovea_right"}};
        if (depth && depth->texture) list.push_back({depth->texture, D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE, "periphery_depth"});
        std::ostringstream info;
        info << "TriView B11 snapshot\neye " << layout.eye_width << "x" << layout.eye_height
             << " shared_context " << layout.shared_context << " native_local " << layout.native_local
             << " context_scale " << layout.context_scale << "\n";
        for (size_t i = 0; i != 4; ++i)
            info << "view" << i << " x " << layout.views[i].x << " y " << layout.views[i].y << " w " << layout.views[i].width << " h " << layout.views[i].height << "\n";
        for(size_t role=0;role!=4;++role) {
            const auto color_rect=color_source_rect(layout,role==1 && layout.shared_context ? 0 : role);
            info << "color_rect" << role << " " << color_rect.x << " " << color_rect.y << " " << color_rect.width << " " << color_rect.height << "\n";
        }
        info << "shader_seam"; for(float v:constants.seam) info << " " << v;
        info << "\nshader_blend_sharpen"; for(float v:constants.options) info << " " << v;
        for(float v:constants.sharpen_eye) info << " " << v;
        info << "\n";
        for (size_t e = 0; e != 2; ++e) {
            const auto& c = layout.focus_crops[e];
            info << "focus_crop" << e << " " << c.u0 << " " << c.v0 << " " << c.u1 << " " << c.v1 << "\ncontext_h" << e;
            for (float v : layout.context_h[e]) info << " " << v;
            info << "\ndepth_eye_origin" << e;
            for (float v : layout.depth_eye_origin[e]) info << " " << v;
            info << "\n";
        }
        info << "context_projection"; for (double v : layout.context_projection) info << " " << v;
        info << "\ndepth_geometry_valid " << layout.depth_geometry_valid << "\ndepth_projection";
        for (float v : layout.depth_projection) info << " " << v;
        info << "\ndepth_coefficients"; for (float v : layout.depth_coefficients) info << " " << v;
        info << "\nshader depth_options"; for (auto v : constants.depth_options) info << " " << v;
        info << "\nshader depth_rect"; for (auto v : constants.depth_rect) info << " " << v;
        info << "\nshader depth_jitter"; for (auto v : constants.depth_jitter) info << " " << v;
        info << "\nsource_format " << int(source_format_) << " output_format " << int(output_format_) << "\n";
        D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_READBACK; heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        std::vector<SnapshotItem> items;
        for (const auto& source : list) {
            if (!source.resource) continue;
            const auto desc = source.resource->GetDesc();
            SnapshotItem item{}; UINT64 total{};
            device_->GetCopyableFootprints(&desc, 0, 1, 0, &item.footprint, &item.rows, &item.row_bytes, &total);
            if (!total || total > (UINT64(1) << 31)) continue;
            D3D12_RESOURCE_DESC buffer{};
            buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; buffer.Width = total;
            buffer.Height = buffer.DepthOrArraySize = buffer.MipLevels = 1; buffer.SampleDesc.Count = 1;
            buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
            if (FAILED(device_->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer, D3D12_RESOURCE_STATE_COPY_DEST,
                    nullptr, IID_PPV_ARGS(&item.buffer)))) continue;
            item.name = source.name;
            info << source.name << " format " << int(desc.Format) << " " << desc.Width << "x" << desc.Height << "\n";
            barrier(commands, source.resource, source.state, D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION from{}, to{};
            from.pResource = source.resource; from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX; from.SubresourceIndex = 0;
            to.pResource = item.buffer.Get(); to.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; to.PlacedFootprint = item.footprint;
            commands->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
            barrier(commands, source.resource, D3D12_RESOURCE_STATE_COPY_SOURCE, source.state);
            items.push_back(std::move(item));
        }
        snapshot_ = std::move(items);
        snapshot_text_ = info.str();
    }

    // Slot retired => the readback copies completed. Files are written off-thread.
    void flush_snapshot() {
        if (snapshot_.empty()) return;
        auto items = std::move(snapshot_); snapshot_.clear();
        auto text = std::move(snapshot_text_);
        const auto dir = snapshot_directory();
        std::thread([items = std::move(items), text = std::move(text), dir]() {
            std::error_code ec;
            const auto base = dir.empty() ? std::filesystem::path{"."} : dir;
            std::filesystem::create_directories(base, ec);
            char stamp[32]{};
            const auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
            std::tm local{}; localtime_s(&local, &now);
            std::strftime(stamp, sizeof(stamp), "%Y%m%d-%H%M%S", &local);
            unsigned ok = 0;
            for (const auto& item : items) ok += write_snapshot_dds(base / (std::string("triview_") + stamp + "_" + item.name + ".dds"), item);
            std::ofstream(base / (std::string("triview_") + stamp + "_info.txt")) << text;
            snapshots_written().fetch_add(1);
            std::scoped_lock l(snapshot_mutex());
            last_snapshot_message_storage() = std::string(stamp) + ": " + std::to_string(ok) + "/" + std::to_string(items.size()) +
                " images saved to " + base.string();
        }).detach();
    }

    void read_timing() {
        if (!timing_pending_ || !timestamps_ || !frequency_) return;
        gpu_ms_=-1.f;
        seam_gpu_ms_=-1.f;
        D3D12_RANGE range{0,sizeof(UINT64)*3};
        UINT64* values{};
        if (SUCCEEDED(timestamps_->Map(0,&range,reinterpret_cast<void**>(&values)))) {
            if (values[2]>=values[1] && values[1]>=values[0]) {
                gpu_ms_=static_cast<float>(double(values[2]-values[0])*1000.0/double(frequency_));
                // No adaptive dispatch -> no seam-analysis work; ignore the
                // timestamp gap that would otherwise include setup overhead.
                seam_gpu_ms_=timed_seam_active_ ?
                    static_cast<float>(double(values[1]-values[0])*1000.0/double(frequency_)) : 0.f;
                last_seam_analysis_milliseconds().store(seam_gpu_ms_, std::memory_order_relaxed);
            }
            D3D12_RANGE no_write{0,0};
            timestamps_->Unmap(0,&no_write);
        }
        timing_pending_=false;
        timed_seam_active_=false;
    }
    void setup_timing(ID3D12Device* device, UINT64 frequency) {
        if (!device || !frequency || (queries_ && timestamps_ && frequency_==frequency)) return;
        queries_.Reset(); timestamps_.Reset(); frequency_=0; timing_pending_=false; gpu_ms_=-1.f; seam_gpu_ms_=-1.f; timed_seam_active_=false;
        D3D12_QUERY_HEAP_DESC query{};
        query.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
        query.Count=3;
        if (FAILED(device->CreateQueryHeap(&query,IID_PPV_ARGS(&queries_)))) return;
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type=D3D12_HEAP_TYPE_READBACK;
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC buffer{};
        buffer.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width=sizeof(UINT64)*3;
        buffer.Height=buffer.DepthOrArraySize=buffer.MipLevels=1;
        buffer.SampleDesc.Count=1;
        buffer.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&buffer,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&timestamps_)))) {
            queries_.Reset();
            return;
        }
        frequency_=frequency;
        queries_->SetName(L"QuadView slot timestamp queries");
        timestamps_->SetName(L"QuadView slot timestamp readback");
    }
    static bool compatible_source(DXGI_FORMAT resource, DXGI_FORMAT view) {
        if (resource == view) return true;
        if (resource == DXGI_FORMAT_R8G8B8A8_TYPELESS) return view == DXGI_FORMAT_R8G8B8A8_UNORM || view == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
        if (resource == DXGI_FORMAT_B8G8R8A8_TYPELESS) return view == DXGI_FORMAT_B8G8R8A8_UNORM || view == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        if (resource == DXGI_FORMAT_R10G10B10A2_TYPELESS) return view == DXGI_FORMAT_R10G10B10A2_UNORM;
        if (resource == DXGI_FORMAT_R16G16B16A16_TYPELESS) return view == DXGI_FORMAT_R16G16B16A16_FLOAT;
        return false;
    }
    static bool valid_layout(const Layout& layout) {
        if (!layout.eye_width || !layout.eye_height || layout.eye_width > 8192 || layout.eye_height > 8192 ||
            layout.atlas_width != layout.eye_width * 2 || layout.atlas_height != layout.eye_height) return false;
        for (const auto& c : layout.focus_crops) {
            if (!(std::isfinite(c.u0) && std::isfinite(c.v0) && std::isfinite(c.u1) && std::isfinite(c.v1)) ||
                c.u0 < 0.f || c.v0 < 0.f || c.u1 > 1.f || c.v1 > 1.f || c.u1 <= c.u0 || c.v1 <= c.v0) return false;
        }
        for (unsigned i = 0; i < 4; ++i) {
            const auto& rect = layout.views[i];
            if (!rect.width || !rect.height || uint64_t(rect.x) + rect.width > layout.atlas_width ||
                uint64_t(rect.y) + rect.height > layout.atlas_height) return false;
            if (layout.native_local) {
                // B6: each rectangle lives in its own target; it must fit that target.
                const auto extents = source_extents(layout);
                if (uint64_t(rect.x) + rect.width > extents[i][0] || uint64_t(rect.y) + rect.height > extents[i][1]) return false;
                continue;
            }
            for (unsigned j = 0; j < i; ++j) {
                const auto& other = layout.views[j];
                if (uint64_t(rect.x) < uint64_t(other.x) + other.width && uint64_t(other.x) < uint64_t(rect.x) + rect.width &&
                    uint64_t(rect.y) < uint64_t(other.y) + other.height && uint64_t(other.y) < uint64_t(rect.y) + rect.height) return false;
            }
        }
        return true;
    }
    static void barrier(ID3D12GraphicsCommandList* commands, ID3D12Resource* resource,
                         D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
        if (before == after) return;
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition.pResource = resource;
        barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        barrier.Transition.StateBefore = before; barrier.Transition.StateAfter = after;
        commands->ResourceBarrier(1, &barrier);
    }
    ComPtr<ID3D12Device> device_;
    ComPtr<ID3D12RootSignature> root_;
    ComPtr<ID3D12PipelineState> pipeline_;
    ComPtr<ID3D12PipelineState> seam_pipeline_;
    ComPtr<ID3D12DescriptorHeap> srv_heap_, rtv_heap_;
    ComPtr<ID3D12Resource> constants_, destination_, timestamps_;
    ComPtr<ID3D12Resource> seam_stats_;
    std::shared_ptr<EdgeHistoryState> edge_history_; // retained through slot retirement and session teardown
    std::array<ComPtr<ID3D12Resource>, 4> sources_;
    ComPtr<ID3D12QueryHeap> queries_;
    void* mapped_{};
    std::shared_ptr<const void> depth_keepalive_{};
    std::shared_ptr<const void> owner_;
    std::vector<SnapshotItem> snapshot_;
    std::string snapshot_text_;
    DXGI_FORMAT source_format_{DXGI_FORMAT_UNKNOWN}, output_format_{DXGI_FORMAT_UNKNOWN};
    const char* error_{"Compositor not prewarmed"};
    bool recorded_{};
    bool timing_pending_{};
    bool timed_seam_active_{}; // pending timestamp interval includes CSSeam
    UINT64 frequency_{};
    float gpu_ms_{-1.f};
    float seam_gpu_ms_{-1.f};
};

} // namespace uevr::quadview::dx12

```

## FILE src/mods/vr/QuadViewDelivery.hpp (611 lines)
```cpp
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <type_traits>

namespace uevr::quadview {

// Independent family -> render-thread -> RHI tail -> executed-owner ledger.
// It carries exactly one four-view family; it does not reuse DuoView's
// primary/secondary two-source pairing or Mono pose path.
template <class Packet, size_t Capacity = 16>
class Delivery {
public:
    // Bounded, ownership-free view used by the on-demand diagnostics export.
    // A busy result means this ledger was not sampled.
    struct DiagnosticsSnapshot {
        uint64_t generation{};
        uint32_t source_slots{};
        uint32_t incomplete_source_slots{};
        uint32_t pending_engine_tickets{};
        bool engine_tracking_overflowed{};
        bool busy{};
    };
    static_assert(std::is_trivially_copyable_v<DiagnosticsSnapshot>);

    struct Source {
        std::shared_ptr<const Packet> packet{};
        uint64_t generation{}, serial{};
        uint32_t engine_frame{}; // BeginRenderViewFamily-assigned frame after binding; pre-engine value is diagnostic only.
        uint64_t pose_frame_token{}; // Frozen OpenXR frame token carried by this source.
        uintptr_t family{}, target{}, scene{};
        // The GT BeginRenderViewFamily callback binds the pre-engine producer
        // registration to Unreal's current frame number while the original
        // FSceneViewFamily and its four FSceneView pointers are still present.
        // The RT callback may receive renderer-owned FViewInfo copies, so it
        // matches the bound frame/target/scene tuple rather than view addresses.
        std::array<uintptr_t, 4> view_ids{};
        bool engine_frame_bound{};
        explicit operator bool() const { return packet && generation && serial && family && target && scene; }
        bool same_owner(const Source& other) const {
            return packet == other.packet && generation == other.generation && serial == other.serial &&
                engine_frame == other.engine_frame && pose_frame_token == other.pose_frame_token && family == other.family &&
                target == other.target && scene == other.scene && view_ids == other.view_ids &&
                engine_frame_bound == other.engine_frame_bound;
        }
    };

    struct EngineTicket {
        uint64_t generation{}, serial{};
        uint32_t engine_frame{};
        uintptr_t family{}, target{}, scene{}, command{};
        bool render_seen{}, tail_hooked{};
        explicit operator bool() const {
            return generation && serial && engine_frame != 0xffffffffu && family && target && scene;
        }
        bool same_owner(const EngineTicket& other) const {
            return generation == other.generation && serial == other.serial &&
                engine_frame == other.engine_frame && family == other.family &&
                target == other.target && scene == other.scene;
        }
    };

    enum class EngineRegistrationStatus : uint8_t {
        invalid_ticket,
        stale_generation,
        duplicate_same_owner,
        ambiguous_rt_key,
        capacity_exhausted,
        accepted,
    };

    struct EngineRegistrationResult {
        EngineRegistrationStatus status{EngineRegistrationStatus::invalid_ticket};
        // Occupancy is measured after the registration attempt against the
        // active ledger; oldest_serial is zero when no ticket is pending.
        size_t pending{};
        size_t capacity{Capacity};
        uint64_t oldest_serial{};
    };

    bool register_engine_family(EngineTicket ticket) {
        const auto result = register_engine_family_detailed(ticket);
        return result.status == EngineRegistrationStatus::accepted ||
            result.status == EngineRegistrationStatus::duplicate_same_owner;
    }

    EngineRegistrationResult register_engine_family_detailed(EngineTicket ticket) {
        std::scoped_lock lock{mutex_};
        const auto summarize = [this](EngineRegistrationStatus status) {
            EngineRegistrationResult result{};
            result.status = status;
            result.capacity = Capacity;
            for (const auto& slot : engine_slots_) {
                if (!slot.ticket) continue;
                ++result.pending;
                if (!result.oldest_serial || slot.ticket.serial < result.oldest_serial)
                    result.oldest_serial = slot.ticket.serial;
            }
            return result;
        };

        if (!ticket) return summarize(EngineRegistrationStatus::invalid_ticket);
        if (!advance(ticket.generation))
            return summarize(EngineRegistrationStatus::stale_generation);
        for (const auto& slot : engine_slots_) {
            if (!slot.ticket) continue;
            if (slot.ticket.same_owner(ticket))
                return summarize(EngineRegistrationStatus::duplicate_same_owner);
            // Two distinct GT families with identical RT matching keys cannot
            // be resolved safely once Unreal copies the family to FViewInfo.
            // Reject the second registration before any source is published.
            if (slot.ticket.generation == ticket.generation &&
                slot.ticket.engine_frame == ticket.engine_frame &&
                slot.ticket.target == ticket.target &&
                slot.ticket.scene == ticket.scene) {
                // An actual second family might still queue GPU work. With
                // no unique render-thread key we must retain an explicit
                // unknown-owner marker and forbid premature mode teardown.
                engine_overflow_generation_ = ticket.generation;
                return summarize(EngineRegistrationStatus::ambiguous_rt_key);
            }
        }
        for (auto& slot : engine_slots_) {
            if (!slot.ticket) {
                slot.ticket = ticket;
                return summarize(EngineRegistrationStatus::accepted);
            }
        }
        engine_overflow_generation_ = ticket.generation;
        return summarize(EngineRegistrationStatus::capacity_exhausted);
    }

    std::optional<EngineTicket> render_engine_family(
        uint64_t generation, uint32_t frame, uintptr_t target, uintptr_t scene) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation) || !target || !scene) return {};
        EngineSlot* match{};
        for (auto& slot : engine_slots_) {
            auto& ticket = slot.ticket;
            if (!ticket || ticket.generation != generation || ticket.engine_frame != frame ||
                ticket.target != target || ticket.scene != scene || ticket.render_seen) continue;
            if (match) return {};
            match = &slot;
        }
        if (!match) return {};
        match->ticket.render_seen = true;
        return match->ticket;
    }

    bool tail_hooked_engine_family(const EngineTicket& ticket, uintptr_t command) {
        std::scoped_lock lock{mutex_};
        auto* slot = find_engine(ticket);
        if (!slot || !slot->ticket.render_seen || slot->ticket.tail_hooked || !command) return false;
        slot->ticket.command = command;
        slot->ticket.tail_hooked = true;
        return true;
    }

    bool tail_hooked_engine_family(const EngineTicket& ticket, const Source& source, uintptr_t command) {
        std::scoped_lock lock{mutex_};
        auto* engine = find_engine(ticket);
        if (!engine || !engine->ticket.render_seen || engine->ticket.tail_hooked || !command) return false;
        Slot* producer{};
        if (source) {
            producer = find(source);
            if (!producer || !producer->render_seen || producer->tail_hooked ||
                source.generation != ticket.generation || source.serial != ticket.serial ||
                source.engine_frame != ticket.engine_frame || source.family != ticket.family ||
                source.target != ticket.target || source.scene != ticket.scene) return false;
        }
        engine->ticket.command = command;
        engine->ticket.tail_hooked = true;
        if (producer) { producer->command = command; producer->tail_hooked = true; }
        return true;
    }

    bool executed_engine_family(const EngineTicket& ticket, uintptr_t command) {
        std::scoped_lock lock{mutex_};
        auto* slot = find_engine(ticket);
        if (!slot || !slot->ticket.tail_hooked || slot->ticket.command != command) return false;
        *slot = {};
        return true;
    }

    bool executed_engine_family(const EngineTicket& ticket, const Source& source,
                                uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        auto* engine = find_engine(ticket);
        if (!engine || !engine->ticket.tail_hooked || engine->ticket.command != command || !thread) return false;
        Slot* producer{};
        if (source) {
            producer = find(source);
            if (!producer || !producer->tail_hooked || producer->command != command || producer->executed ||
                source.generation != ticket.generation || source.serial != ticket.serial ||
                source.engine_frame != ticket.engine_frame || source.family != ticket.family ||
                source.target != ticket.target || source.scene != ticket.scene) return false;
        }
        if (producer) {
            producer->thread = thread;
            producer->executed = true;
            for (auto& older : slots_) {
                if (&older != producer && older.source && older.executed &&
                    older.source.generation == source.generation && older.source.serial < source.serial &&
                    older.source.target == source.target && !older.submitted) older = {};
            }
        }
        *engine = {};
        return true;
    }

    bool engine_commands_retired(uint64_t generation) const {
        std::scoped_lock lock{mutex_};
        if (engine_overflow_generation_ == generation) return false;
        for (const auto& slot : engine_slots_) {
            if (slot.ticket && slot.ticket.generation == generation) return false;
        }
        for (const auto& slot : slots_) {
            if (slot.source && slot.source.generation == generation && !slot.executed) return false;
        }
        return true;
    }

    size_t pending_engine_commands(uint64_t generation) const {
        std::scoped_lock lock{mutex_};
        size_t count{};
        for (const auto& slot : engine_slots_)
            if (slot.ticket && slot.ticket.generation == generation) ++count;
        return count;
    }

    bool engine_tracking_overflowed(uint64_t generation) const {
        std::scoped_lock lock{mutex_};
        return engine_overflow_generation_ == generation;
    }

    DiagnosticsSnapshot diagnostics_snapshot(uint64_t generation = 0) const {
        DiagnosticsSnapshot result{};
        result.generation = generation;
        std::unique_lock<std::mutex> lock;
        try { lock = std::unique_lock<std::mutex>{mutex_, std::try_to_lock}; }
        catch (...) { result.busy = true; return result; }
        if (!lock.owns_lock()) {
            result.busy = true;
            return result;
        }
        for (const auto& slot : slots_) {
            if (!slot.source || (generation && slot.source.generation != generation)) continue;
            ++result.source_slots;
            if (!slot.executed) ++result.incomplete_source_slots;
        }
        for (const auto& slot : engine_slots_) {
            if (slot.ticket && (!generation || slot.ticket.generation == generation))
                ++result.pending_engine_tickets;
        }
        result.engine_tracking_overflowed = engine_overflow_generation_ != 0 &&
            (!generation || engine_overflow_generation_ == generation);
        return result;
    }

    // Publish the validated assigned frame and source in one ledger insertion.
    // Separate family() + bind_engine_frame() calls allow a render-thread race.
    bool register_bound(Source source) {
        if (!source || source.engine_frame == 0xffffffffu) return false;
        for (size_t i = 0; i < source.view_ids.size(); ++i) {
            if (!source.view_ids[i]) return false;
            for (size_t j = 0; j < i; ++j) if (source.view_ids[i] == source.view_ids[j]) return false;
        }
        source.engine_frame_bound = true;
        return family(std::move(source));
    }

    bool family(Source source) {
        std::scoped_lock lock{mutex_};
        if (!source || !advance(source.generation)) return false;
        // A newer family can be queued while an older RHI command still owns
        // the atlas. Preserve the old executed candidate until the newer draw
        // actually executes; execution below is the point at which reuse can
        // invalidate the earlier contents.
        for (auto& slot : slots_) {
            if (!slot.source) continue;
            if (slot.source.same_owner(source)) return false;
            // A duplicated GT registration with a different packet/serial but
            // the same actual UE frame/target/scene would make render() see
            // two eligible owners and reject both. Refuse the conflicting
            // source at publication, preserving the first valid owner.
            if (source.engine_frame_bound && slot.source.engine_frame_bound &&
                slot.source.generation == source.generation &&
                slot.source.engine_frame == source.engine_frame &&
                slot.source.target == source.target &&
                slot.source.scene == source.scene) return false;
        }
        for (auto& slot : slots_) {
            if (!slot.source) {
                slot.source = std::move(source);
                return true;
            }
        }
        Slot* recoverable{};
        for (auto& slot : slots_) {
            if (slot.source && !slot.tail_hooked && !slot.executed && !slot.submitted &&
                (recoverable == nullptr || slot.source.serial < recoverable->source.serial)) {
                recoverable = &slot;
            }
        }
        if (recoverable != nullptr) {
            *recoverable = {};
            recoverable->source = std::move(source);
            return true;
        }
        return false;
    }


    // Game thread observes a fully constructed UE family before the outer
    // BeginRenderingViewFamilies hook registers its immutable source packet.
    // Stage the engine-assigned frame now, and consume it only against the
    // same original family/scene/target and all four original view pointers.
    bool observe_gt_frame(uint64_t generation, uint64_t draw_serial, uintptr_t family,
                          uintptr_t target, uintptr_t scene,
                          const std::array<uintptr_t, 4>& views,
                          uint32_t engine_frame) {
        if (!generation || !draw_serial || !family || !target || !scene || engine_frame == 0xffffffffu)
            return false;
        for (size_t i = 0; i < views.size(); ++i) {
            if (!views[i]) return false;
            for (size_t j = 0; j < i; ++j) if (views[i] == views[j]) return false;
        }
        std::scoped_lock lock{mutex_};
        if (!advance(generation)) return false;
        FrameTicket* slot{};
        for (auto& ticket : frame_tickets_) {
            if (ticket.generation == generation && ticket.family == family) {
                // A Family pointer can be recycled. Invalidate the older GT
                // observation rather than allowing it to identify a new draw.
                slot = &ticket;
                break;
            }
        }
        if (!slot) {
            for (auto& ticket : frame_tickets_) {
                if (!ticket.generation) { slot = &ticket; break; }
            }
        }
        if (!slot) {
            // These are GT-only observations, not GPU packet owners. Expire
            // the oldest unclaimed observation when the bounded ring fills.
            for (auto& ticket : frame_tickets_) {
                if (!slot || ticket.ordinal < slot->ordinal) slot = &ticket;
            }
        }
        if (!slot) return false;
        *slot = FrameTicket{generation, draw_serial, family, target, scene, views, engine_frame, ++ticket_clock_};
        return true;
    }

    std::optional<uint32_t> take_observed_gt_frame(
        uint64_t generation, uint64_t draw_serial, uintptr_t family, uintptr_t target,
        uintptr_t scene, const std::array<uintptr_t, 4>& views) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation) || !draw_serial || !family || !target || !scene) return {};
        FrameTicket* matched{};
        for (auto& ticket : frame_tickets_) {
            if (ticket.generation != generation || ticket.draw_serial != draw_serial || ticket.family != family ||
                ticket.target != target || ticket.scene != scene ||
                ticket.views != views) continue;
            if (matched) return {}; // Never choose between ambiguous owners.
            matched = &ticket;
        }
        if (!matched) return {};
        const auto frame = matched->engine_frame;
        *matched = {};
        return frame;
    }

    // Called from the game-thread ISceneViewExtension callback after Unreal
    // has assigned FSceneViewFamily::FrameNumber and before FSceneRenderer
    // copies the family/views. The serial plus original-family/view identities
    // make this a one-to-one binding even when UE reuses object addresses.
    // A conflicting already-bound tuple is rejected instead of leaving the RT
    // callback to guess between two owners.
    std::optional<Source> bind_engine_frame(uint64_t generation, uint64_t serial,
                                            uintptr_t family, uintptr_t target, uintptr_t scene,
                                            const std::array<uintptr_t, 4>& views,
                                            uint32_t engine_frame) {
        if (!generation || !serial || !family || !target || !scene || engine_frame == 0xffffffffu) return {};
        for (size_t i = 0; i < views.size(); ++i) {
            if (!views[i]) return {};
            for (size_t j = 0; j < i; ++j) if (views[i] == views[j]) return {};
        }

        std::scoped_lock lock{mutex_};
        if (!advance(generation)) return {};

        Slot* match{};
        for (auto& slot : slots_) {
            const auto& source = slot.source;
            if (!source || source.generation != generation || source.serial != serial ||
                source.family != family || source.target != target || source.scene != scene ||
                source.view_ids != views) continue;
            if (match != nullptr) return {};
            match = &slot;
        }
        if (match == nullptr || match->render_seen || match->source.engine_frame_bound) return {};

        for (const auto& slot : slots_) {
            const auto& source = slot.source;
            if (&slot != match && source && source.generation == generation && source.engine_frame_bound &&
                source.engine_frame == engine_frame && source.target == target && source.scene == scene) {
                return {};
            }
        }

        match->source.engine_frame = engine_frame;
        match->source.engine_frame_bound = true;
        return match->source;
    }

    std::optional<Source> render(uint64_t generation, uint32_t frame,
                                 uintptr_t family, uintptr_t target, uintptr_t scene) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation) || !family || !target || !scene) return {};
        Slot* match{};
        for (auto& slot : slots_) {
            if (slot.source && slot.source.generation == generation && slot.source.engine_frame_bound &&
                // Unreal may pass a renderer-owned copy of FSceneViewFamily to
                // the render thread. Resolve it by the exact frame bound on the
                // original GT family, target and scene; keep source.family as
                // provenance only.
                slot.source.engine_frame == frame &&
                slot.source.target == target && slot.source.scene == scene) {
                if (match != nullptr) return {}; // Multiple matching owners are ambiguous.
                match = &slot;
            }
        }
        if (match == nullptr || match->render_seen) return {};
        match->render_seen = true;
        return match->source;
    }

    bool tail_hooked(const Source& source, uintptr_t command) {
        std::scoped_lock lock{mutex_};
        auto* slot = find(source);
        if (!slot || !slot->render_seen || !command || slot->tail_hooked) return false;
        slot->command = command;
        slot->tail_hooked = true;
        return true;
    }

    bool executed(const Source& source, uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        auto* slot = find(source);
        if (!slot || !slot->tail_hooked || slot->command != command || !thread || slot->executed) return false;
        slot->thread = thread;
        slot->executed = true;
        // A later execution to the same source target proves that its contents
        // have replaced every older unsubmitted image in that atlas. Retire
        // those candidates only now, not when the game thread merely queues a
        // newer family. Submitted sources retain their command-slot owner until
        // explicit retirement.
        for (auto& older : slots_) {
            if (&older != slot && older.source && older.executed &&
                older.source.generation == source.generation &&
                older.source.serial < source.serial &&
                older.source.target == source.target && !older.submitted) {
                older = {};
            }
        }
        return true;
    }

    // Called at the first executed write of a new isolated quartet. Retire only
    // older unsubmitted pixels; pending engine tickets still drain normally.
    void invalidate_reused_target(uint64_t generation, uintptr_t target, uint64_t serial) {
        std::scoped_lock lock{mutex_};
        for (auto& slot : slots_) if (slot.source && slot.executed && !slot.submitted &&
            slot.source.generation == generation && slot.source.target == target && slot.source.serial < serial)
            slot = {};
    }

    // Select the newest exact source owner whose RHI command executed on the
    // submission thread. Never match against an independently sampled UE or XR
    // frame counter: the selected packet carries the two frozen eye poses that
    // must accompany its atlas. Selection is a peek until XR accepts the copy.
    std::optional<Source> select(uint64_t generation, uint32_t submit_thread) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation) || !submit_thread) return {};
        Slot* match{};
        for (auto& slot : slots_) {
            if (slot.source && slot.source.generation == generation &&
                slot.executed && slot.thread == submit_thread && !slot.submitted) {
                if (match == nullptr || slot.source.serial > match->source.serial) {
                    match = &slot;
                } else if (slot.source.serial == match->source.serial) {
                    return {}; // Do not guess between duplicate producers for one draw.
                }
            }
        }
        if (!match) return {};
        return match->source;
    }

    // Call only after the OpenXR copy callback recorded commands and the copy
    // was accepted. A temporary slot miss leaves the exact source retryable.
    bool submitted(const Source& source, uintptr_t destination) {
        std::scoped_lock lock{mutex_};
        auto* slot = find(source);
        if (!slot || !slot->executed || slot->submitted || !destination) return false;
        slot->submitted = true;
        slot->destination = destination;
        return true;
    }

    bool execution_evidence(const Source& source, uintptr_t& command, uint32_t& thread) const {
        std::scoped_lock lock{mutex_};
        const auto* slot = find(source);
        if (!slot || !slot->tail_hooked || !slot->executed) return false;
        command = slot->command;
        thread = slot->thread;
        return command != 0 && thread != 0;
    }

    bool retire(uint64_t generation, uint64_t serial) {
        std::scoped_lock lock{mutex_};
        for (auto& slot : slots_) {
            if (slot.source && slot.source.generation == generation && slot.source.serial == serial) {
                slot = {};
                return true;
            }
        }
        return false;
    }

    void retire_generation(uint64_t generation) {
        std::scoped_lock lock{mutex_};
        for (auto& slot : slots_) {
            if (slot.source && slot.source.generation == generation) slot = {};
        }
        for (auto& ticket : frame_tickets_) {
            if (ticket.generation == generation) ticket = {};
        }
        for (auto& slot : engine_slots_) {
            if (slot.ticket.generation == generation) slot = {};
        }
        if (engine_overflow_generation_ == generation) engine_overflow_generation_ = 0;
        if (generation >= generation_) generation_ = generation;
    }

    void retire_all() {
        std::scoped_lock lock{mutex_};
        for (auto& slot : slots_) slot = {};
        for (auto& ticket : frame_tickets_) ticket = {};
        for (auto& slot : engine_slots_) slot = {};
        ticket_clock_ = 0;
        engine_overflow_generation_ = 0;
        generation_ = 0;
    }

private:
    struct EngineSlot { EngineTicket ticket{}; };
    struct FrameTicket {
        uint64_t generation{}, draw_serial{};
        uintptr_t family{}, target{}, scene{};
        std::array<uintptr_t, 4> views{};
        uint32_t engine_frame{};
        uint64_t ordinal{};
    };
    struct Slot {
        Source source{};
        uintptr_t command{}, destination{};
        uint32_t thread{};
        bool render_seen{}, tail_hooked{}, executed{}, submitted{};
    };
    Slot* find(const Source& source) {
        for (auto& slot : slots_) if (slot.source && slot.source.same_owner(source)) return &slot;
        return nullptr;
    }
    const Slot* find(const Source& source) const {
        for (const auto& slot : slots_) if (slot.source && slot.source.same_owner(source)) return &slot;
        return nullptr;
    }
    EngineSlot* find_engine(const EngineTicket& ticket) {
        for (auto& slot : engine_slots_) if (slot.ticket && slot.ticket.same_owner(ticket)) return &slot;
        return nullptr;
    }
    bool advance(uint64_t generation) {
        if (!generation || generation < generation_) return false;
        if (generation != generation_) {
            for (auto& slot : slots_) slot = {};
            for (auto& ticket : frame_tickets_) ticket = {};
            for (auto& slot : engine_slots_) slot = {};
            ticket_clock_ = 0;
            engine_overflow_generation_ = 0;
            generation_ = generation;
        }
        return true;
    }
    mutable std::mutex mutex_;
    uint64_t generation_{};
    uint64_t ticket_clock_{};
    std::array<FrameTicket, Capacity> frame_tickets_{};
    std::array<EngineSlot, Capacity> engine_slots_{};
    std::array<Slot, Capacity> slots_{};
    uint64_t engine_overflow_generation_{};
};

} // namespace uevr::quadview

```

## FILE src/mods/vr/QuadViewDepthContinuity.hpp (38 lines)
```cpp
#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include "QuadViewNgxSelect.hpp"

namespace uevr::quadview::ngx::continuity {

struct Candidate {
    uint64_t sequence{};
    uint32_t width{}, height{};
    uint32_t age_ms{};
    bool submitted{}, valid_evaluation{}, has_texture{};
    bool foreign_queue{}, fence_complete{};
};

inline bool protectable(const Candidate& c, uint32_t width, uint32_t height) noexcept {
    return c.submitted && c.valid_evaluation && c.has_texture &&
        matches_periphery(c.width,c.height,width,height) && c.age_ms < 250 &&
        (!c.foreign_queue || c.fence_complete);
}

template<class Range>
size_t newest_protected(const Range& candidates, uint32_t width, uint32_t height) noexcept {
    size_t best = std::numeric_limits<size_t>::max();
    uint64_t sequence = 0;
    for (size_t i = 0; i < candidates.size(); ++i) {
        const auto& c = candidates[i];
        if (protectable(c, width, height) && (best == std::numeric_limits<size_t>::max() || c.sequence > sequence)) {
            best = i;
            sequence = c.sequence;
        }
    }
    return best;
}

} // namespace uevr::quadview::ngx::continuity

```

## FILE src/mods/vr/QuadViewDepthIdentity.hpp (92 lines)
```cpp
#pragma once
#include <array>
#include <cstdint>
#include <chrono>
#include <mutex>
#include <unordered_map>
namespace uevr::quadview::ngx {
// A producer identity, never a lookup by dimensions or current global GT key.
// The adapter may publish it only while executing one authenticated role-0 tail.
struct DepthOwner {
    uint64_t generation{}, serial{}, target_set{};
    uint32_t engine_frame{}, role{~0u}, output_width{}, output_height{};
    std::array<double,16> projection{};
    std::array<float,2> jitter{};
    bool unambiguous{}, ngx_input_state_known{};
    bool valid() const noexcept {
        return generation && serial && target_set && role==0 && output_width && output_height &&
            unambiguous;
    }
    bool same_source(const DepthOwner& other) const noexcept {
        return generation==other.generation && serial==other.serial && target_set==other.target_set &&
            engine_frame==other.engine_frame && role==other.role;
    }
    bool matches(const DepthOwner& other) const noexcept {
        return valid() && other.valid() && same_source(other) &&
            output_width==other.output_width && output_height==other.output_height &&
            projection==other.projection;
    }
    friend bool operator==(const DepthOwner&,const DepthOwner&)=default;
};
class DepthOwnerScope {
public:
    explicit DepthOwnerScope(const DepthOwner& owner) noexcept : previous_(current_) {
        current_=owner.valid() ? &owner : nullptr;
    }
    ~DepthOwnerScope() { current_=previous_; }
    DepthOwnerScope(const DepthOwnerScope&)=delete;
    static const DepthOwner* current() noexcept { return current_; }
private:
    const DepthOwner* previous_{};
    static inline thread_local const DepthOwner* current_{};
};
// Kept separate from the snapshot-data lock: no data lock crosses a driver
// call, but Reset cannot overtake Execute's post-call submission bookkeeping.
class DepthSubmissionSequence {
public:
    auto acquire() { return std::unique_lock<std::recursive_mutex>(mutex_); }
    auto try_acquire() { return std::unique_lock<std::recursive_mutex>(mutex_,std::try_to_lock); }
private:
    std::recursive_mutex mutex_;
};
// Access is serialized by PeripheryDepth's mutex. An object pointer identifies
// a command-list object; only pointer + epoch identifies its recorded commands.
class DepthRecordingEpochs {
public:
    uint64_t current(uintptr_t list) {
        const auto found=epochs_.find(list);
        if(found!=epochs_.end()) return found->second;
        if(!list || epochs_.size()>=256) return 0;
        return epochs_.emplace(list,++next_epoch_).first->second;
    }
    uint64_t reset(uintptr_t list) {
        const auto found=epochs_.find(list);
        return found==epochs_.end() ? 0 : (found->second=++next_epoch_);
    }
    template<class Keep> void prune(Keep keep) {
        for(auto it=epochs_.begin();it!=epochs_.end();) {
            if(!keep(it->first)) it=epochs_.erase(it); else ++it;
        }
    }
    bool matches(uintptr_t list,uint64_t epoch) const {
        const auto it=epochs_.find(list);
        return epoch && it!=epochs_.end() && it->second==epoch;
    }
private:
    std::unordered_map<uintptr_t,uint64_t> epochs_{};
    uint64_t next_epoch_{};
};
inline bool depth_capture_in_window(std::chrono::steady_clock::time_point captured,
        std::chrono::steady_clock::time_point packet_born,std::chrono::steady_clock::time_point now) {
    return packet_born.time_since_epoch().count()>0 && captured>=packet_born && captured<=now &&
        now-captured<std::chrono::milliseconds(250);
}
// UINT64_MAX is D3D12's device-removal sentinel, never completion proof.
inline bool depth_copy_complete(uint64_t completed,uint64_t required) noexcept {
    return required && completed!=~uint64_t{} && completed>=required;
}
inline bool depth_slot_reusable(bool pending,bool submitted,uint64_t completed,uint64_t required,
                                long references) noexcept {
    return references==1 && !pending && (!submitted || depth_copy_complete(completed,required));
}
}

```

## FILE src/mods/vr/QuadViewFamilyRouting.hpp (302 lines)
```cpp
#pragma once

#include <array>
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <span>
#include <type_traits>
#include <utility>

namespace uevr::quadview {

struct FamilyIdentity {
    uintptr_t family{}, scene{}, target{};
    std::array<uintptr_t,16> views{};
    uint8_t view_count{};
    bool readable{};
};

struct FrozenFamilyIdentity {
    uintptr_t family{}, scene{}, target{};
    std::array<uintptr_t,4> views{};
};

enum class FamilyRouteStatus : uint8_t {
    main_family,
    auxiliary_only,
    malformed_batch,
    malformed_main,
    ambiguous_main,
};

struct FamilyRoute {
    FamilyRouteStatus status{FamilyRouteStatus::malformed_batch};
    size_t index{};
    explicit operator bool() const { return status == FamilyRouteStatus::main_family; }
};

struct PartialFamilyIdentity {
    uintptr_t family{}, scene{}, target{};
    std::array<uintptr_t,16> views{};
    uint8_t view_count{};
};

enum class PartialFamilyRouteStatus : uint8_t { auxiliary_only, possible_main, malformed_batch };

inline bool valid_frozen_identity(const FrozenFamilyIdentity& expected) {
    if (!expected.family || !expected.scene || !expected.target) return false;
    for (size_t i=0;i<expected.views.size();++i) {
        if (!expected.views[i]) return false;
        for (size_t j=0;j<i;++j) if (expected.views[j] == expected.views[i]) return false;
    }
    return true;
}

inline bool same_frozen_view_order(const FamilyIdentity& candidate,
                                   const FrozenFamilyIdentity& expected) {
    if (candidate.view_count != expected.views.size()) return false;
    for (size_t i=0;i<expected.views.size();++i)
        if (candidate.views[i] != expected.views[i]) return false;
    return true;
}

inline bool same_frozen_view_set(const FamilyIdentity& candidate,
                                 const FrozenFamilyIdentity& expected) {
    if (candidate.view_count != expected.views.size()) return false;
    std::array<bool,4> matched{};
    for (size_t i=0;i<expected.views.size();++i) {
        bool found{};
        for (size_t j=0;j<expected.views.size();++j) {
            if (!matched[j] && candidate.views[i] == expected.views[j]) {
                matched[j]=true; found=true; break;
            }
        }
        if (!found) return false;
    }
    return true;
}

inline bool shares_frozen_view(const FamilyIdentity& candidate,
                               const FrozenFamilyIdentity& expected) {
    const auto count = candidate.view_count < candidate.views.size()
        ? candidate.view_count : candidate.views.size();
    for (size_t i=0;i<count;++i)
        for (const auto view : expected.views)
            if (view && candidate.views[i] == view) return true;
    return false;
}

inline PartialFamilyRouteStatus classify_partial_main_family(
    std::span<const FamilyIdentity> candidates,const PartialFamilyIdentity& partial) {
    if (candidates.empty() || partial.view_count > partial.views.size())
        return PartialFamilyRouteStatus::malformed_batch;
    bool possible_main{};
    for (const auto& candidate:candidates) {
        if (!candidate.readable || !candidate.family || candidate.view_count > candidate.views.size())
            return PartialFamilyRouteStatus::malformed_batch;
        if (partial.family && candidate.family == partial.family) possible_main=true;
        if (partial.target && candidate.target == partial.target &&
            (!partial.scene || candidate.scene == partial.scene)) possible_main=true;
        if (partial.scene && !partial.target && candidate.scene == partial.scene) possible_main=true;
        if (!partial.family && !partial.scene && !partial.target && !partial.view_count &&
            candidate.view_count == 4) possible_main=true;
        const auto count = candidate.view_count < candidate.views.size()
            ? candidate.view_count : candidate.views.size();
        for (size_t i=0;i<count;++i)
            for (size_t j=0;j<partial.view_count;++j)
                if (candidate.views[i] && candidate.views[i] == partial.views[j]) possible_main=true;
    }
    return possible_main ? PartialFamilyRouteStatus::possible_main :
        PartialFamilyRouteStatus::auxiliary_only;
}

// Recovery authenticates an engine family, never a publishable source. The
// original engine callback must run to establish its assigned frame and RHI
// owner even when construction/pose evidence cannot yet authorize four views.
inline FamilyRoute route_drain_family(std::span<const FamilyIdentity> candidates,
                                      const PartialFamilyIdentity& partial) {
    if (candidates.empty() || !partial.target || partial.view_count > partial.views.size())
        return {FamilyRouteStatus::malformed_batch,0};
    size_t selected{}, matches{};
    for (size_t i=0;i<candidates.size();++i) {
        const auto& c=candidates[i];
        if (!c.readable || !c.family || c.view_count>c.views.size())
            return {FamilyRouteStatus::malformed_batch,i};
        if (c.target!=partial.target) continue;
        if (!c.scene || !c.view_count || c.view_count>4 ||
            (partial.family && c.family!=partial.family) ||
            (partial.scene && c.scene!=partial.scene))
            return {FamilyRouteStatus::malformed_main,i};
        for (size_t a=0;a<c.view_count;++a) {
            if (!c.views[a]) return {FamilyRouteStatus::malformed_main,i};
            for (size_t b=0;b<a;++b) if(c.views[a]==c.views[b])
                return {FamilyRouteStatus::malformed_main,i};
        }
        for (size_t a=0;a<partial.view_count;++a) {
            if (!partial.views[a] || std::find(c.views.begin(),c.views.begin()+c.view_count,
                    partial.views[a])==c.views.begin()+c.view_count)
                return {FamilyRouteStatus::malformed_main,i};
        }
        selected=i; ++matches;
    }
    if (matches>1) return {FamilyRouteStatus::ambiguous_main,selected};
    return {matches ? FamilyRouteStatus::main_family : FamilyRouteStatus::auxiliary_only,selected};
}

inline FamilyRoute route_current_main_family(std::span<const FamilyIdentity> candidates,
                                             const FamilyIdentity& expected) {
    if (candidates.empty() || !expected.readable || !expected.family || !expected.scene ||
        !expected.target || expected.view_count == 0 || expected.view_count > expected.views.size())
        return {FamilyRouteStatus::malformed_batch,0};
    for (size_t i=0;i<expected.view_count;++i) {
        if (!expected.views[i]) return {FamilyRouteStatus::malformed_main,0};
        for (size_t j=0;j<i;++j) if (expected.views[j] == expected.views[i])
            return {FamilyRouteStatus::malformed_main,0};
    }
    size_t selected{};
    size_t exact_count{};
    bool suspect_main{};
    for (size_t i=0;i<candidates.size();++i) {
        const auto& candidate=candidates[i];
        if (!candidate.readable || !candidate.family || candidate.view_count > candidate.views.size())
            return {FamilyRouteStatus::malformed_batch,i};
        const bool same_views = candidate.view_count == expected.view_count &&
            std::equal(expected.views.begin(),expected.views.begin()+expected.view_count,candidate.views.begin());
        if (candidate.family == expected.family) {
            if (candidate.scene != expected.scene || candidate.target != expected.target || !same_views)
                return {FamilyRouteStatus::malformed_main,i};
            selected=i;
            ++exact_count;
            continue;
        }
        bool shares{};
        const auto count = candidate.view_count < candidate.views.size()
            ? candidate.view_count : candidate.views.size();
        for (size_t a=0;a<count;++a)
            for (size_t b=0;b<expected.view_count;++b)
                if (candidate.views[a] == expected.views[b]) shares=true;
        if (shares || (candidate.scene == expected.scene && candidate.target == expected.target))
            suspect_main=true;
    }
    if (exact_count > 1 || (exact_count != 0 && suspect_main))
        return {FamilyRouteStatus::ambiguous_main,selected};
    if (suspect_main) return {FamilyRouteStatus::malformed_main,0};
    if (exact_count == 1) return {FamilyRouteStatus::main_family,selected};
    return {FamilyRouteStatus::auxiliary_only,0};
}

// Selects only the unique family authenticated by the frozen construction
// snapshot. Other valid families are auxiliaries and remain in the caller's
// original batch. A candidate that looks like a copied or damaged main family
// fails closed instead of falling through to a legacy view-count heuristic.
inline FamilyRoute route_main_family(std::span<const FamilyIdentity> candidates,
                                     const FrozenFamilyIdentity& expected) {
    if (candidates.empty() || !valid_frozen_identity(expected))
        return {FamilyRouteStatus::malformed_batch,0};
    FamilyIdentity identity{};
    identity.family=expected.family; identity.scene=expected.scene; identity.target=expected.target;
    identity.view_count=4; identity.readable=true;
    std::copy(expected.views.begin(),expected.views.end(),identity.views.begin());
    return route_current_main_family(candidates,identity);
}

// Temporarily presents one frozen main view/target to the engine while keeping
// the outer auxiliary batch intact. The owner uses this once around all four
// callbacks; nested callbacks observe the selected singleton and cannot steal
// restoration ownership.
template<class View, class Target, class Context, class Getter, class Setter>
class ScopedMainFamilyMutation {
public:
    ScopedMainFamilyMutation(View* data, size_t capacity, int32_t& count, Context& context,
                             Getter getter, Setter setter)
        : data_{data}, capacity_{capacity}, count_{&count}, context_{&context},
          getter_{getter}, setter_{setter}, original_count_{count} {
        if (!data_ || capacity_ < original_.size() || original_count_ != static_cast<int32_t>(original_.size()))
            return;
        for (size_t i=0;i<original_.size();++i) original_[i]=data_[i];
        original_target_=getter_(*context_);
        valid_=true;
    }
    ScopedMainFamilyMutation(const ScopedMainFamilyMutation&)=delete;
    ScopedMainFamilyMutation& operator=(const ScopedMainFamilyMutation&)=delete;
    ~ScopedMainFamilyMutation() { restore(); }

    explicit operator bool() const { return valid_; }

    bool select_single(View view, Target target) {
        if (!valid_ || !view || !target) return false;
        data_[0]=view;
        *count_=1;
        setter_(*context_,target);
        return getter_(*context_) == target;
    }

    void restore() {
        if (!valid_) return;
        for (size_t i=0;i<original_.size();++i) data_[i]=original_[i];
        *count_=original_count_;
        setter_(*context_,original_target_);
        valid_=false;
    }

private:
    View* data_{};
    size_t capacity_{};
    int32_t* count_{};
    Context* context_{};
    Getter getter_;
    Setter setter_;
    std::array<View,4> original_{};
    Target original_target_{};
    int32_t original_count_{};
    bool valid_{};
};

enum class MainFamilyDispatchStatus : uint8_t {
    complete,
    invalid_storage,
    preparation_failed,
    selection_failed,
    callback_validation_failed,
};

struct MainFamilyDispatchResult {
    MainFamilyDispatchStatus status{MainFamilyDispatchStatus::invalid_storage};
    uint8_t completed{};
    explicit operator bool() const { return status == MainFamilyDispatchStatus::complete; }
};

template<class View, class Target, class Context, class Getter, class Setter,
         class Before, class FirstBatch, class Singleton, class Validate>
MainFamilyDispatchResult dispatch_main_views(
    View* data, size_t capacity, int32_t& count, Context& context,
    const std::array<View,4>& views, const std::array<Target,4>& targets,
    Getter getter, Setter setter, Before before, FirstBatch first_batch,
    Singleton singleton, Validate validate, uint8_t skip_mask=0) {
    ScopedMainFamilyMutation<View,Target,Context,Getter,Setter> mutation{
        data,capacity,count,context,getter,setter};
    if (!mutation) return {MainFamilyDispatchStatus::invalid_storage,0};
    uint8_t completed{};
    for (size_t slot=0;slot<views.size();++slot) {
        // Tri-view: a constructed but unrendered view (never slot 0, which
        // carries the original batch and its auxiliary families).
        if (slot!=0 && (skip_mask & (1u<<slot))) continue;
        if (!before(slot)) return {MainFamilyDispatchStatus::preparation_failed,completed};
        if (!mutation.select_single(views[slot],targets[slot]))
            return {MainFamilyDispatchStatus::selection_failed,completed};
        if (slot==0) first_batch();
        else singleton();
        if (!validate(slot)) return {MainFamilyDispatchStatus::callback_validation_failed,completed};
        ++completed;
    }
    return {MainFamilyDispatchStatus::complete,completed};
}

template<class View, class Context, class Getter, class Setter>
ScopedMainFamilyMutation(View*,size_t,int32_t&,Context&,Getter,Setter)
    -> ScopedMainFamilyMutation<View,
        std::remove_cvref_t<decltype(std::declval<Getter>()(std::declval<Context&>()))>,
        Context,Getter,Setter>;

} // namespace uevr::quadview

```

## FILE src/mods/vr/QuadViewFocusLift.hpp (23 lines)
```cpp
#pragma once
#include <algorithm>
#include <cmath>

namespace uevr::quadview::focus_lift {
// Robust fit to 52,584 flat-gray sky samples. These are source-domain gain
// parameters, not an assertion about the game's underlying postprocess.
inline constexpr float default_corner_gain = 1.14799273f;
inline constexpr float default_onset = .46940367f;
inline constexpr float default_power = .92386647f;

struct Profile {
    float brightness{1.f}, strength{1.f};
    float corner_gain{default_corner_gain}, onset{default_onset}, power{default_power};
};

inline float gain(float u, float v, const Profile& p = {}) {
    const float x=2.f*u-1.f, y=2.f*v-1.f;
    const float r2=(std::clamp)((x*x+y*y)*.5f,0.f,1.f);
    const float t=(std::clamp)((r2-p.onset)/(1.f-p.onset),0.f,1.f);
    return p.brightness*(1.f+(p.corner_gain-1.f)*p.strength*std::pow(t,p.power));
}
} // namespace uevr::quadview::focus_lift

```

## FILE src/mods/vr/QuadViewFramePacket.hpp (91 lines)
```cpp
#pragma once

#include "QuadViewProducer.hpp"
#include <array>
#include <cmath>
#include <memory>
#include <utility>

namespace uevr::quadview {

struct RuntimeEye {
    uint64_t frame_token{};
    std::array<float, 4> orientation{};
    std::array<float, 3> position{};
    std::array<float, 4> fov{};
    std::array<float, 16> projection{};
    bool valid{};
};

struct RhiExecutionEvidence {
    uint64_t engine_frame{};
    uintptr_t family{}, target{}, scene{}, command{};
    uint32_t thread{};
    bool family_observed{}, tail_hooked{}, command_executed{};

    bool valid_for(const Snapshot& snapshot) const {
        return family_observed && tail_hooked && command_executed &&
            engine_frame == snapshot.engine_frame && family == snapshot.family &&
            target == snapshot.target && scene == snapshot.scene && command != 0 && thread != 0;
    }
};

// Immutable source/pose ownership boundary consumed by the D3D12 submit path.
// source_owner is expected to retain the actual RHI resource wrapper (for
// example, an object containing a ComPtr<ID3D12Resource>) until command-slot
// fence retirement. The portable contract cannot claim GPU completion.
struct FramePacket {
    std::shared_ptr<const Snapshot> producer;
    std::shared_ptr<const void> source_owner;
    uintptr_t source_resource{};
    uint64_t runtime_frame{};
    RhiExecutionEvidence execution{};
    uint64_t serial{};
    std::array<RuntimeEye, 2> eyes{};

    bool valid() const {
        if (!producer || !producer->histories_complete() || !source_owner ||
            source_resource == 0 || serial == 0 || serial != producer->key.draw_serial ||
            !execution.valid_for(*producer)) return false;
        for (const auto& eye : eyes) {
            if (!eye.valid || eye.frame_token != runtime_frame) return false;
            double norm = 0.0;
            for (float v : eye.orientation) {
                if (!std::isfinite(v)) return false;
                norm += static_cast<double>(v) * v;
            }
            if (std::abs(norm - 1.0) > 0.01) return false;
            for (float v : eye.position) if (!std::isfinite(v)) return false;
            const auto& f = eye.fov;
            if (!(std::isfinite(f[0]) && std::isfinite(f[1]) &&
                  std::isfinite(f[2]) && std::isfinite(f[3]) &&
                  f[0] < -0.001f && f[1] > 0.001f &&
                  f[2] > 0.001f && f[3] < -0.001f)) return false;
            bool projection_nonzero = false;
            for (float v : eye.projection) {
                if (!std::isfinite(v)) return false;
                projection_nonzero = projection_nonzero || std::abs(v) > 1.0e-8f;
            }
            if (!projection_nonzero) return false;
        }
        return true;
    }
};

inline std::shared_ptr<const FramePacket> bind_frame_packet(
    std::shared_ptr<const Snapshot> producer,
    uintptr_t source_resource,
    std::shared_ptr<const void> source_owner,
    uint64_t runtime_frame,
    RhiExecutionEvidence execution,
    std::array<RuntimeEye, 2> eyes)
{
    const auto serial = producer ? producer->key.draw_serial : 0;
    auto packet = std::make_shared<FramePacket>(FramePacket{
        std::move(producer), std::move(source_owner), source_resource,
        runtime_frame, execution, serial, std::move(eyes)});
    if (!packet->valid()) return {};
    return packet;
}

} // namespace uevr::quadview

```

## FILE src/mods/vr/QuadViewGaze.hpp (183 lines)
```cpp
#pragma once

// Stereo adaptation of the published v186.1 DuoView gaze mapping. The CAPI
// ray is recovered once in head space; each eye then applies its own optical
// rotation and its own full projection matrix before the crop is frozen.
#include "DuoViewGaze.hpp"
#include "QuadViewGeometry.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <optional>

namespace uevr::quadview::gaze {

using Quaternion = std::array<float, 4>; // OpenXR x, y, z, w
using Projection = std::array<float, 16>; // GLM/OpenXR column-major projection

inline bool valid_perspective_projection(const Projection& p) {
    for (const float v : p) if (!std::isfinite(v)) return false;
    // UEVR's +Z-forward perspective has a nonzero focal scale, positive
    // forward clip-w, and no homogeneous identity term. This rejects the
    // finite all-zero/identity matrices observed before the first XR update.
    return std::abs(p[0])>1.0e-6f && std::abs(p[5])>1.0e-6f &&
        p[11]>.01f && std::abs(p[15])<1.0e-4f;
}

inline std::optional<Quaternion> normalize(Quaternion q) {
    float length2{};
    for (const float v : q) {
        if (!std::isfinite(v)) return {};
        length2 += v * v;
    }
    if (!std::isfinite(length2) || length2 < .0001f) return {};
    const float inverse = 1.f / std::sqrt(length2);
    for (auto& v : q) v *= inverse;
    return q;
}

inline Quaternion multiply(const Quaternion& a, const Quaternion& b) {
    return {
        a[3]*b[0] + a[0]*b[3] + a[1]*b[2] - a[2]*b[1],
        a[3]*b[1] - a[0]*b[2] + a[1]*b[3] + a[2]*b[0],
        a[3]*b[2] + a[0]*b[1] - a[1]*b[0] + a[2]*b[3],
        a[3]*b[3] - a[0]*b[0] - a[1]*b[1] - a[2]*b[2]
    };
}

// qHead maps head-space directions into stage space; qEye maps eye-local
// directions into stage space. qHead^-1*qEye is therefore the eye rotation in
// head coordinates, which the production optical_ray helper transposes.
inline std::optional<std::array<float, 9>> eye_rotation_in_head(
    Quaternion head, Quaternion eye)
{
    head = normalize(head).value_or(Quaternion{});
    eye = normalize(eye).value_or(Quaternion{});
    if (head == Quaternion{} || eye == Quaternion{}) return {};
    const Quaternion head_inverse{-head[0], -head[1], -head[2], head[3]};
    const auto q = normalize(multiply(head_inverse, eye));
    if (!q) return {};
    const auto [x, y, z, w] = *q;
    // Column-major, matching OpenXR/GLM storage expected by the exact
    // v186.1 optical_ray helper. It transposes this eye-local-to-head matrix.
    return std::array<float, 9>{
        1.f-2.f*(y*y+z*z), 2.f*(x*y+z*w), 2.f*(x*z-y*w),
        2.f*(x*y-z*w), 1.f-2.f*(x*x+z*z), 2.f*(y*z+x*w),
        2.f*(x*z+y*w), 2.f*(y*z-x*w), 1.f-2.f*(x*x+y*y)
    };
}

// This is the same projective mapping used by v186.1's PSVR2 Reader, exposed
// here as a portable helper so both eyes can use their own full matrix.
inline std::optional<duoview::UV> projection_uv(
    const duoview::Ray& ray, const Projection& p)
{
    if (!std::isfinite(ray.right) || !std::isfinite(ray.up) ||
        !std::isfinite(ray.forward) || ray.forward <= .1f) return {};
    for (const float v : p) if (!std::isfinite(v)) return {};
    const float x = p[0]*ray.right + p[4]*ray.up + p[8]*ray.forward;
    const float y = p[1]*ray.right + p[5]*ray.up + p[9]*ray.forward;
    const float w = p[3]*ray.right + p[7]*ray.up + p[11]*ray.forward;
    if (!std::isfinite(w) || w <= .01f) return {};
    const float u = (x/w + 1.f)*.5f;
    const float v = (1.f - y/w)*.5f;
    if (!std::isfinite(u) || !std::isfinite(v)) return {};
    return duoview::UV{std::clamp(u, 0.f, 1.f), std::clamp(v, 0.f, 1.f)};
}

struct Tangents { float left{}, right{}, up{}, down{}; };

inline std::optional<Tangents> tangents_from_fov(
    float angle_left, float angle_right, float angle_up, float angle_down) {
    if (!std::isfinite(angle_left) || !std::isfinite(angle_right) ||
        !std::isfinite(angle_up) || !std::isfinite(angle_down) ||
        angle_left >= angle_right || angle_down >= angle_up ||
        std::abs(angle_left) >= 1.55f || std::abs(angle_right) >= 1.55f ||
        std::abs(angle_up) >= 1.55f || std::abs(angle_down) >= 1.55f) return {};
    const float left=std::tan(angle_left), right=std::tan(angle_right);
    const float top=std::tan(angle_up), bottom=std::tan(angle_down);
    if (!std::isfinite(left) || !std::isfinite(right) ||
        !std::isfinite(top) || !std::isfinite(bottom) ||
        right-left < .01f || top-bottom < .01f) return {};
    return Tangents{left,right,top,bottom};
}

inline std::optional<Projection> projection_from_tangents(Tangents t) {
    if (!std::isfinite(t.left) || !std::isfinite(t.right) ||
        !std::isfinite(t.up) || !std::isfinite(t.down) ||
        t.right-t.left < .01f || t.up-t.down < .01f) return {};
    Projection p{};
    p[0]=2.f/(t.right-t.left); p[5]=2.f/(t.up-t.down);
    p[8]=-(t.right+t.left)/(t.right-t.left); p[9]=-(t.up+t.down)/(t.up-t.down);
    p[10]=1.f; p[11]=1.f; p[14]=.01f;
    return p;
}

// OpenXR applies UEVR's horizontal and vertical projection overrides to the
// same raw per-eye FOV pair before building runtime matrices. These mode IDs
// intentionally match VR::{HORIZONTAL,VERTICAL}_PROJECTION_OVERRIDE.
inline std::optional<std::array<Projection,2>> projections_from_fovs(
    const std::array<Tangents,2>& raw, int32_t horizontal_mode, int32_t vertical_mode) {
    if (horizontal_mode<0 || horizontal_mode>2 || vertical_mode<0 || vertical_mode>2) return {};
    auto effective=raw;
    if (horizontal_mode==1) {
        const float outer=(std::max)({-raw[0].left,raw[0].right,-raw[1].left,raw[1].right});
        effective[0].left=effective[1].left=-outer;
        effective[0].right=effective[1].right=outer;
    } else if (horizontal_mode==2) {
        const float outer=(std::max)(-raw[0].left,raw[1].right);
        const float inner=(std::max)(raw[0].right,-raw[1].left);
        effective[0].left=-outer; effective[0].right=inner;
        effective[1].left=-inner; effective[1].right=outer;
    }
    if (vertical_mode==1) {
        const float half=(std::max)({raw[0].up,-raw[0].down,raw[1].up,-raw[1].down});
        effective[0].up=effective[1].up=half;
        effective[0].down=effective[1].down=-half;
    } else if (vertical_mode==2) {
        const float top=(std::max)(raw[0].up,raw[1].up);
        const float bottom=(std::max)(-raw[0].down,-raw[1].down);
        effective[0].up=effective[1].up=top;
        effective[0].down=effective[1].down=-bottom;
    }
    const auto left=projection_from_tangents(effective[0]);
    const auto right=projection_from_tangents(effective[1]);
    if (!left || !right) return {};
    return std::array<Projection,2>{*left,*right};
}

// Build the full default OpenXR-style +Z projection from one eye FOV.
inline std::optional<Projection> projection_from_fov(
    float angle_left, float angle_right, float angle_up, float angle_down) {
    const auto tangent=tangents_from_fov(angle_left,angle_right,angle_up,angle_down);
    return tangent ? projection_from_tangents(*tangent) : std::nullopt;
}

inline std::optional<duoview::UV> project_head_ray(
    const duoview::Ray& head_ray, Quaternion head_orientation,
    Quaternion eye_orientation, const Projection& full_eye_projection)
{
    const auto rotation = eye_rotation_in_head(head_orientation, eye_orientation);
    if (!rotation) return {};
    const auto eye_ray = duoview::optical_ray(head_ray, *rotation);
    if (!eye_ray) return {};
    return projection_uv(*eye_ray, full_eye_projection);
}

inline std::optional<std::array<duoview::UV, 2>> project_stereo_head_ray(
    const duoview::Ray& head_ray, Quaternion head_orientation,
    const std::array<Quaternion, 2>& eye_orientations,
    const std::array<Projection, 2>& full_eye_projections)
{
    std::array<duoview::UV, 2> result{};
    for (size_t eye = 0; eye != 2; ++eye) {
        const auto uv = project_head_ray(head_ray, head_orientation,
                                        eye_orientations[eye], full_eye_projections[eye]);
        if (!uv) return {};
        result[eye] = *uv;
    }
    return result;
}

} // namespace uevr::quadview::gaze

```

## FILE src/mods/vr/QuadViewGeometry.hpp (465 lines)
```cpp
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <optional>
#include <utility>
#include "QuadViewNgxSelect.hpp"

namespace uevr::quadview {

struct Rect {
    uint32_t x{}, y{}, width{}, height{};
    friend bool operator==(const Rect&, const Rect&) = default;
};

struct Crop {
    float u0{}, v0{}, u1{1.f}, v1{1.f};
    friend bool operator==(const Crop&, const Crop&) = default;
};

struct FocusPoint {
    float u{.5f}, v{.5f};
};

struct Layout {
    // Engine view order is explicitly zero based:
    // 0 left context, 1 right context, 2 left focus, 3 right focus.
    std::array<Rect, 4> views{};
    uint32_t eye_width{}, eye_height{}, atlas_width{}, atlas_height{};
    // Each runtime eye projects the same head-space gaze ray through its own
    // optical rotation and asymmetric full-eye frustum. Keep both crops in
    // the immutable draw layout; one shared center is not stereo gaze.
    std::array<Crop, 2> focus_crops{};
    float context_scale{};
    // Tri-view: view 0 is ONE centre context shared by both eyes (union FOV of
    // both eye frusta); view 1 is still constructed but never rendered.
    bool shared_context{};
    // Projection entries written into view 0: m[0][0], m[2][0], m[1][1], m[2][1].
    std::array<double, 4> context_projection{};
    // Tri-view B6 compact sources: every role renders into its OWN small native
    // target and `views` hold target-local rectangles (see apply_native_local).
    // false = the original shared 2W x H atlas rectangles.
    bool native_local{};
    // Tri-view B7: periphery depth reprojection shift per eye (see periphery_depth_shift).
    std::array<float, 4> depth_shift{};
    // Exact perspective reprojection: eye origins expressed in the frozen
    // context camera basis and units. Homographies supply each rotated eye ray.
    bool depth_geometry_valid{};
    std::array<std::array<float,4>,2> depth_eye_origin{};
    std::array<float,4> depth_projection{}; // ax,bx,ay,by
    std::array<float,4> depth_coefficients{}; // A=m22,B=m32,C=m23,strength

    // Per eye: 3x3 homography (rows padded to 4) from eye uv to context uv:
    // h = H * (u, v, 1), context uv = h.xy / h.z. Identity for four views.
    std::array<std::array<float, 12>, 2> context_h{{{1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f},
                                                    {1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f}}};
};

// Turns a four-view layout into tri-view. Projections are column-major, +Z
// forward, clip w = m[2][3] * z; per axis an eye maps view tangent t to NDC as
// a*t + b. The shared context has the LEFT eye's orientation (the centre camera
// keeps the left optical rotation). Eye orientations are OpenXR stage
// quaternions (x, y, z, w); when given, the right eye's frustum is rotated into
// the left-eye frame before the union, and each eye samples the context
// through an exact-at-infinity homography (no equal-orientation assumption).
inline bool apply_shared_context(Layout& layout, const std::array<float, 16>& left,
                                 const std::array<float, 16>& right,
                                 const std::array<float, 4>* left_orientation = nullptr,
                                 const std::array<float, 4>* right_orientation = nullptr) {
    using M3 = std::array<std::array<double, 3>, 3>;
    const auto mul = [](const M3& x, const M3& y) {
        M3 r{};
        for (int i = 0; i != 3; ++i) for (int j = 0; j != 3; ++j)
            for (int k = 0; k != 3; ++k) r[i][j] += x[i][k] * y[k][j];
        return r;
    };
    const auto from_quaternion = [](const std::array<float, 4>& q) {
        const double x = q[0], y = q[1], z = q[2], w = q[3];
        return M3{{{1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)},
                   {2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)},
                   {2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)}}};
    };
    M3 rotation[2]{{{{1, 0, 0}, {0, 1, 0}, {0, 0, 1}}}, {{{1, 0, 0}, {0, 1, 0}, {0, 0, 1}}}};
    if (left_orientation && right_orientation) {
        for (const auto* q : {left_orientation, right_orientation}) {
            const double n = double((*q)[0]) * (*q)[0] + double((*q)[1]) * (*q)[1] +
                             double((*q)[2]) * (*q)[2] + double((*q)[3]) * (*q)[3];
            if (!std::isfinite(n) || std::abs(n - 1.) > 1.e-2) return false;
        }
        const auto l = from_quaternion(*left_orientation), r = from_quaternion(*right_orientation);
        M3 lt{};
        for (int i = 0; i != 3; ++i) for (int j = 0; j != 3; ++j) lt[i][j] = l[j][i];
        auto rel = mul(lt, r); // right-eye local -> left-eye local (OpenXR, -Z forward)
        for (int i = 0; i != 3; ++i) for (int j = 0; j != 3; ++j)
            if ((i == 2) != (j == 2)) rel[i][j] = -rel[i][j]; // to +Z forward: S*rel*S
        rotation[1] = rel;
    }
    const std::array<const std::array<float, 16>*, 2> eyes{&left, &right};
    double a[2][2]{}, b[2][2]{}; // [eye][axis]
    double lo[2]{1.e30, 1.e30}, hi[2]{-1.e30, -1.e30};
    for (size_t e = 0; e != 2; ++e) {
        const auto& p = *eyes[e];
        const double w = p[11];
        if (!std::isfinite(w) || std::abs(w) < 1.e-6) return false;
        const double raw_a[2]{p[0], p[5]}, raw_b[2]{p[8], p[9]};
        double t[2][2]{};
        for (size_t axis = 0; axis != 2; ++axis) {
            a[e][axis] = raw_a[axis] / w;
            b[e][axis] = raw_b[axis] / w;
            if (!std::isfinite(a[e][axis]) || !std::isfinite(b[e][axis]) || std::abs(a[e][axis]) < 1.e-6) return false;
            t[axis][0] = (-1. - b[e][axis]) / a[e][axis];
            t[axis][1] = (1. - b[e][axis]) / a[e][axis];
        }
        // A projective map keeps the frustum convex: its tangent bounds lie at the corners.
        for (int cx = 0; cx != 2; ++cx) for (int cy = 0; cy != 2; ++cy) {
            const double d[3]{t[0][cx], t[1][cy], 1.};
            double c[3]{};
            for (int i = 0; i != 3; ++i) for (int k = 0; k != 3; ++k) c[i] += rotation[e][i][k] * d[k];
            if (!(c[2] > 1.e-3)) return false;
            for (size_t axis = 0; axis != 2; ++axis) {
                lo[axis] = (std::min)(lo[axis], c[axis] / c[2]);
                hi[axis] = (std::max)(hi[axis], c[axis] / c[2]);
            }
        }
    }
    double ca[2]{}, cb[2]{};
    for (size_t axis = 0; axis != 2; ++axis) {
        if (!(hi[axis] - lo[axis] > 1.e-6)) return false;
        ca[axis] = (a[0][axis] > 0. ? 2. : -2.) / (hi[axis] - lo[axis]);
        cb[axis] = -1. - ca[axis] * (ca[axis] > 0. ? lo[axis] : hi[axis]);
    }
    // u: ndc = 2u - 1 (right).  v: ndc = 1 - 2v (texture rows go down).
    const M3 context{{{ca[0] * .5, 0., (cb[0] + 1.) * .5}, {0., -ca[1] * .5, (1. - cb[1]) * .5}, {0., 0., 1.}}};
    auto homographies = layout.context_h; // commit only after both eyes validate
    for (size_t e = 0; e != 2; ++e) {
        const M3 eye_to_tangent{{{2. / a[e][0], 0., (-1. - b[e][0]) / a[e][0]},
                                 {0., -2. / a[e][1], (1. - b[e][1]) / a[e][1]}, {0., 0., 1.}}};
        const auto h = mul(context, mul(rotation[e], eye_to_tangent));
        for (int i = 0; i != 3; ++i) for (int j = 0; j != 3; ++j) {
            if (!std::isfinite(h[i][j])) return false;
            homographies[e][i * 4 + j] = static_cast<float>(h[i][j]);
        }
    }
    layout.context_h = homographies;
    const double w = left[11];
    layout.context_projection = {ca[0] * w, cb[0] * w, ca[1] * w, cb[1] * w};
    layout.shared_context = true;
    return true;
}

class LayoutLatch {
public:
    std::optional<Layout> get(uint64_t generation, uint64_t serial) const {
        if (generation_ != generation || serial_ != serial) return {};
        return layout_;
    }

    std::optional<Layout> freeze(uint64_t generation, uint64_t serial, Layout candidate) {
        if (!generation || !serial) return {};
        if (const auto current = get(generation, serial)) return current;
        generation_ = generation;
        serial_ = serial;
        layout_ = std::move(candidate);
        return layout_;
    }

    void reset() { generation_ = serial_ = 0; layout_.reset(); }

private:
    uint64_t generation_{}, serial_{};
    std::optional<Layout> layout_{};
};

inline std::optional<Layout> make_layout(
    uint32_t eye_width, uint32_t eye_height,
    float crop_width = .50f, float crop_height = .50f,
    float context_scale = .20f, float focus_density = 1.f,
    std::array<FocusPoint, 2> focus = {})
{
    if (!eye_width || !eye_height || eye_width > 8192 || eye_height > 8192 ||
        !std::isfinite(crop_width) || !std::isfinite(crop_height) ||
        !std::isfinite(context_scale) || !std::isfinite(focus_density) ||
        crop_width < .05f || crop_width > 1.f || crop_height < .05f || crop_height > 1.f ||
        context_scale < .05f || context_scale > .5f || focus_density < .25f || focus_density > 4.f ||
        std::any_of(focus.begin(), focus.end(), [](const FocusPoint& p) {
            return !std::isfinite(p.u) || !std::isfinite(p.v) || p.u < 0.f || p.u > 1.f || p.v < 0.f || p.v > 1.f;
        })) return {};

    const auto rounded = [](float value) {
        return static_cast<uint32_t>((std::max)(1.0f, std::round(value)));
    };
    auto context_width = rounded(eye_width * context_scale);
    auto context_height = rounded(eye_height * context_scale);
    const auto focus_width = rounded(eye_width * crop_width * focus_density);
    const auto focus_height = rounded(eye_height * crop_height * focus_density);
    // The pair is packed horizontally within each eye's existing half of the
    // 2W x H render target. The crops preserve each source rectangle's aspect.
    if (uint64_t(context_width) + focus_width > eye_width ||
        context_height > eye_height || focus_height > eye_height) return {};
    // Tri-view B11 (after the fit check, so accepted settings are unchanged): the periphery's DLSS depth is recognised by its output size,
    // so the context must never have (almost) the same size as a fovea. Only in
    // that case it is made slightly smaller (same aspect, same field of view).
    if (const float k = ngx::unique_context_factor(focus_width, focus_height, context_width, context_height); k != 1.f) {
        context_width = rounded(float(context_width) * k);
        context_height = rounded(float(context_height) * k);
    }

    Layout result{};
    result.eye_width = eye_width;
    result.eye_height = eye_height;
    result.atlas_width = eye_width * 2;
    result.atlas_height = eye_height;
    for (uint32_t eye = 0; eye != 2; ++eye) {
        const float cu = std::clamp(focus[eye].u, crop_width * .5f, 1.f - crop_width * .5f);
        const float cv = std::clamp(focus[eye].v, crop_height * .5f, 1.f - crop_height * .5f);
        result.focus_crops[eye] = {cu - crop_width * .5f, cv - crop_height * .5f,
                                   cu + crop_width * .5f, cv + crop_height * .5f};
    }
    result.context_scale = context_scale;
    for (uint32_t eye = 0; eye != 2; ++eye) {
        const auto base_x = eye * eye_width;
        result.views[eye] = {base_x, 0, context_width, context_height};
        result.views[eye + 2] = {base_x + context_width, 0, focus_width, focus_height};
    }
    return result;
}

// Tri-view B7: context-uv shift per unit of reversed-Z device depth for each
// eye seeing the shared centre periphery (layout.context_projection = m00, m20,
// m11, m21). An eye at lateral offset t (same units as near) sees context
// direction tan_inf + t / Z; Z = near / d gives du = 0.5 * m00 * t * d / near.
// Returns {left u, left v, right u, right v}; zero when inputs are invalid.
inline std::array<float, 4> periphery_depth_shift(const Layout& layout, double near_units,
                                                  double half_ipd_units, double strength) {
    const double m00 = layout.context_projection[0];
    if (!layout.shared_context || !std::isfinite(near_units) || !std::isfinite(half_ipd_units) ||
        !std::isfinite(strength) || !std::isfinite(m00) || near_units <= 0.0 || half_ipd_units < 0.0 || m00 <= 0.0)
        return {};
    const double k = 0.5 * m00 * half_ipd_units / near_units * strength;
    if (!std::isfinite(k) || std::abs(k) > 4.0) return {};
    return {static_cast<float>(-k), 0.f, static_cast<float>(k), 0.f};
}

// Freeze the actual render projection and eye origins, never infer an IPD.
// Supports the standard UE perspective form, including finite/infinite far
// planes and asymmetric frusta. Refuse unsupported skew/oblique projections.
inline bool configure_depth_geometry(Layout& layout, const std::array<double,16>& p,
        const std::array<std::array<double,3>,2>& eye_origins, double strength=1.) {
    layout.depth_geometry_valid=false;
    if (!layout.shared_context || !std::isfinite(strength)) return false;
    for (double v:p) if (!std::isfinite(v)) return false;
    for (unsigned i:{1u,2u,3u,4u,6u,7u,12u,13u,15u})
        if (std::abs(p[i])>1.e-9) return false;
    if (std::abs(p[0])<1.e-9 || std::abs(p[5])<1.e-9 || p[14]<=0. || p[11]<=0.) return false;
    for (size_t eye=0;eye<2;++eye) for (size_t axis=0;axis<3;++axis) {
        const double v=eye_origins[eye][axis];
        if (!std::isfinite(v) || std::abs(v)>1.e6) return false;
        layout.depth_eye_origin[eye][axis]=static_cast<float>(v);
    }
    layout.depth_projection={float(p[0]/p[11]),float(p[8]/p[11]),float(p[5]/p[11]),float(p[9]/p[11])};
    layout.depth_coefficients={float(p[10]),float(p[14]),float(p[11]),float(strength)};
    layout.depth_geometry_valid=true;
    return true;
}

// Reference for shader validation. infinity_uv comes from the existing exact
// eye-to-context homography. Device depth is sampled at the iterated source UV.
inline std::array<double,2> reproject_context_ray(const Layout& l, unsigned eye,
        std::array<double,2> infinity_uv, double device_depth) {
    if (!l.depth_geometry_valid || eye>1 || !std::isfinite(device_depth)) return infinity_uv;
    const auto& p=l.depth_projection; const auto& c=l.depth_coefficients;
    const auto& t=l.depth_eye_origin[eye];
    const double inverse_z=(c[2]*device_depth-c[0])/c[1];
    const double rx=(2.*infinity_uv[0]-1.-p[1])/p[0];
    const double ry=(1.-2.*infinity_uv[1]-p[3])/p[2];
    return {infinity_uv[0]+.5*p[0]*(t[0]-rx*t[2])*inverse_z*c[3],
            infinity_uv[1]-.5*p[2]*(t[1]-ry*t[2])*inverse_z*c[3]};
}

// Tri-view B6 compact sources. Width/height of each role's native target.
using SourceExtents = std::array<std::array<uint32_t, 2>, 4>;
// Distinct x-only origins keep all four engine view rectangles unique for every
// setting (the producer identifies a constructed view by its exact rectangle)
// while every rectangle keeps y = 0 like the proven atlas layout:
// context pair x = 0 / 8, focus pair x = 16 / 24. Extents are rounded up to
// 64 px so small slider steps reuse the same targets instead of rebuilding.
inline constexpr uint32_t compact_source_margin = 8;
inline constexpr uint32_t compact_source_granularity = 64;

// Engine construction rectangles retain their role-identifying origins.
// A standalone Native Stereo Fix family's final color image is presented at
// texture origin; these are different coordinate contracts. Snapshot B35-125:
// 2030x1614 color at (0,0), although engine roles start at x16/x24.
inline Rect color_source_rect(const Layout& layout, size_t role) {
    auto rect=layout.views[role];
    if(layout.native_local) { rect.x=0; rect.y=0; }
    return rect;
}

inline SourceExtents source_extents(const Layout& layout) {
    SourceExtents extents{};
    for (size_t i = 0; i != 4; ++i) {
        if (!layout.native_local) {
            extents[i] = {layout.atlas_width, layout.atlas_height};
            continue;
        }
        const auto& size_from = layout.views[i < 2 ? 0 : 2];
        const auto pad = i < 2 ? compact_source_margin : 3 * compact_source_margin;
        const auto up = [](uint64_t v) {
            return static_cast<uint32_t>((v + compact_source_granularity - 1) / compact_source_granularity * compact_source_granularity);
        };
        extents[i] = {up(uint64_t(size_from.width) + pad), up(size_from.height)};
    }
    return extents;
}

// Converts an atlas layout (from make_layout, optionally tri-view) into
// target-local rectangles. Sizes, crops and homographies are unchanged: the
// homographies map eye uv to context uv, which is rectangle-relative.
// B17: retain logical role 1 for view-family identity while never allocating a
// corresponding physical source. This also applies to unprojected "wanted"
// layouts during B14 resize negotiation (not only frozen shared-context layouts).
inline SourceExtents triview_source_extents(const Layout& layout) {
    auto extents = source_extents(layout);
    extents[1] = {0, 0};
    return extents;
}

inline bool apply_native_local(Layout& layout) {
    if (layout.native_local) return true;
    const auto context = layout.views[0], focus = layout.views[2];
    const auto m = compact_source_margin;
    if (!context.width || !context.height || !focus.width || !focus.height ||
        layout.views[1].width != context.width || layout.views[1].height != context.height ||
        layout.views[3].width != focus.width || layout.views[3].height != focus.height ||
        uint64_t(context.width) + m > layout.atlas_width || uint64_t(focus.width) + 3 * m > layout.atlas_width) return false;
    layout.views[0] = {0, 0, context.width, context.height};
    layout.views[1] = {m, 0, context.width, context.height};
    layout.views[2] = {2 * m, 0, focus.width, focus.height};
    layout.views[3] = {3 * m, 0, focus.width, focus.height};
    layout.native_local = true;
    return true;
}

// Compatibility convenience for center/single-point callers and the geometry
// unit tests. Production stereo gaze uses the two-point overload above.
inline std::optional<Layout> make_layout(
    uint32_t eye_width, uint32_t eye_height,
    float crop_width, float crop_height, float context_scale, float focus_density,
    float focus_u, float focus_v)
{
    const std::array<FocusPoint, 2> both{{{focus_u, focus_v}, {focus_u, focus_v}}};
    return make_layout(eye_width, eye_height, crop_width, crop_height,
                       context_scale, focus_density, both);
}

constexpr bool valid_view_index(int32_t index) { return index >= 0 && index < 4; }
constexpr uint32_t eye_for_view(uint32_t index) { return index & 1u; }
constexpr bool is_focus_view(uint32_t index) { return index >= 2u && index < 4u; }

template <typename Matrix>
inline void apply_focus_crop(Matrix& matrix, const Crop& crop) {
    const auto width = crop.u1 - crop.u0;
    const auto height = crop.v1 - crop.v0;
    if (!(std::isfinite(width) && std::isfinite(height)) || width <= 0.f || height <= 0.f) return;
    const auto x_scale = 1.f / width;
    const auto y_scale = 1.f / height;
    const auto x_shift = (1.f - crop.u0 - crop.u1) * x_scale;
    const auto y_shift = (crop.v0 + crop.v1 - 1.f) * y_scale;
    for (int col = 0; col != 4; ++col) {
        const auto old_x = matrix[col][0];
        const auto old_y = matrix[col][1];
        const auto old_w = matrix[col][3];
        matrix[col][0] = old_x * x_scale + old_w * x_shift;
        matrix[col][1] = old_y * y_scale + old_w * y_shift;
    }
}

// Tri-view B14: one source-target build per SETTLED size change, at most one in
// flight, and the sizes of every published set are known. B12 started a new
// four-target build on every 64 px slider step; each build allocates four render
// targets that only Unreal's garbage collector frees (about once a minute), and
// a build replaced mid-flight could publish with sizes the draw no longer knew.
struct ResizeSizes {
    float crop_width{}, crop_height{}, context_scale{}, foveal_density{};
};
class ResizeGate {
public:
    static constexpr uint64_t settle_ms = 400;      // wanted extents unchanged this long
    static constexpr uint64_t latch_timeout_ms = 35000; // > the 30 s build timeout
    // While a build is in flight it is re-requested at most this often: a build that
    // fails fast must not respawn four targets every frame. Between requests the
    // caller asks for the live extents, which leaves an in-flight build untouched.
    static constexpr uint64_t retry_ms = 2000;
    struct Decision {
        bool hold{};            // draw with `draw` (the published set's sizes)
        ResizeSizes draw{};
        bool request{};         // ask for a build of `request_extents`
        SourceExtents request_extents{};
    };
    // A draw used the published set with these sizes.
    void confirm_live(const SourceExtents& extents, const ResizeSizes& sizes) {
        live_valid_ = true; live_extents_ = extents; live_sizes_ = sizes;
    }
    // B42: minimum pause after a new set was published before the next build is
    // latched (0 = off, B14 behaviour). Survives reset().
    void set_cooldown_ms(uint64_t ms) { cooldown_ms_ = ms; }
    uint64_t cooldown_ms() const { return cooldown_ms_; }
    // B42: the caller refused the latched build (VRAM guard): forget it and let the
    // current wish settle again, so a later, different wish is not blocked for 35 s.
    void cancel_latch() { latched_ = false; seen_ = false; }
    void reset() { const auto c = cooldown_ms_; *this = ResizeGate{}; cooldown_ms_ = c; }
    // published: extents of the set published right now (nullopt = none).
    Decision update(const std::optional<SourceExtents>& published, const SourceExtents& wanted,
                    const ResizeSizes& wanted_sizes, uint64_t now_ms) {
        Decision d{};
        // No published set (world change, mode switch): the caller's normal path
        // requests what it draws; an old in-flight request is not carried over.
        if (!published) { latched_ = false; seen_ = false; return d; }
        if (latched_ && *published == latched_extents_) {
            confirm_live(*published, latched_sizes_);
            latched_ = false;
            published_ms_ = now_ms; // B42 cooldown starts when the new set is live
        }
        if (latched_ && now_ms - latched_ms_ > latch_timeout_ms) latched_ = false;
        if (latched_ && now_ms - requested_ms_ >= retry_ms) {
            d.request = true; d.request_extents = latched_extents_; requested_ms_ = now_ms;
        }
        // Unknown sizes for the published set: no hold (the caller's normal path).
        if (!live_valid_ || *published != live_extents_) { seen_ = false; return d; }
        if (wanted == live_extents_) { seen_ = false; return d; }
        d.hold = true; d.draw = live_sizes_;
        if (!seen_ || wanted != seen_extents_) { seen_ = true; seen_extents_ = wanted; seen_ms_ = now_ms; return d; }
        if (!latched_ && now_ms - seen_ms_ >= settle_ms &&
            (cooldown_ms_ == 0 || now_ms - published_ms_ >= cooldown_ms_)) {
            latched_ = true; latched_extents_ = wanted; latched_sizes_ = wanted_sizes; latched_ms_ = now_ms;
            requested_ms_ = now_ms;
            d.request = true; d.request_extents = wanted;
        }
        return d;
    }
    bool latched() const { return latched_; }
private:
    bool live_valid_{}; SourceExtents live_extents_{}; ResizeSizes live_sizes_{};
    bool latched_{}; SourceExtents latched_extents_{}; ResizeSizes latched_sizes_{}; uint64_t latched_ms_{}, requested_ms_{};
    bool seen_{}; SourceExtents seen_extents_{}; uint64_t seen_ms_{};
    uint64_t cooldown_ms_{}, published_ms_{}; // B42
};

// Tri-view B15: which pose-ring frame answers "where is the head now" (recenter,
// standing origin/height). ID7 renders its roles with their own frame numbers
// (canonical N, then N+1, N+2), and each role render moves the runtime's current
// frame to N+1/N+2. Only N gets a located head pose; with a 6-slot ring and 3
// frames per draw the role slots are never refreshed, so a recenter between
// draws read a pose that could be minutes old. In TriView answer with the newest
// located frame; every other mode keeps the current frame exactly as before.
inline uint32_t current_pose_frame(bool triview, bool located_any, uint32_t current, uint32_t newest_located) {
    return (triview && located_any && current != newest_located) ? newest_located : current;
}
// Wraparound-safe "a is newer than b" for 32-bit frame counters.
inline bool pose_frame_newer(uint32_t a, uint32_t b) { return static_cast<int32_t>(a - b) > 0; }

} // namespace uevr::quadview

```

## FILE src/mods/vr/QuadViewHookTrace.hpp (58 lines)
```cpp
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <mutex>

namespace uevr::quadview {
// Scalar observation only. No source leases, command pointers to dereference,
// retirement decisions, GPU operations or runtime synchronization live here.
struct HookTraceRecord {
    const char* event{"UNKNOWN"};
    const char* reason{"none"};
    const char* detail{"none"};
    uint64_t generation{}, serial{}, owner_generation{}, owner_serial{}, drain{};
    uint32_t frame{}, recorded_frame{};
    uint32_t canonical_frame{};
    unsigned rendered{},hooked{},executed{},written{};
    unsigned role{255};
    int mode{-1}, index{-1}, expected_index{-1}, result{-1};
    uintptr_t family{}, target{}, scene{}, list{}, root{}, tail{}, vtable{}, original_vtable{};
    size_t vtables{}, engines{}, natives{}, drains{};
    size_t pending{};
    bool recorded{}, ours_known{}, ours{}, engine{}, native{}, source{}, duo{};
    uint64_t elapsed_us{};
};
void emit_hook_trace(size_t site,const HookTraceRecord& record);
int hook_trace_mode();

class HookTraceGate {
public:
    struct Decision { bool emit{}; uint64_t count{}; };
    static constexpr size_t site_count=192;
    // Three initial draw serials include both startup atlas draws and the
    // first quartet. Each site is independently bounded, then summarized.
    Decision visit(size_t site,uint64_t generation,uint64_t serial,uint64_t now_ms) {
        if(site>=site_count) return {};
        std::scoped_lock lock{mutex_};
        Epoch* epoch{};
        for(auto& e:epochs_) if(e.used && e.generation==generation) {epoch=&e;break;}
        if(!epoch) {epoch=&epochs_[next_++%epochs_.size()];*epoch={};epoch->used=true;epoch->generation=generation;}
        if(!epoch->first_serial && serial) epoch->first_serial=serial;
        auto& s=epoch->sites[site];
        ++s.count;
        const bool initial=serial && epoch->first_serial && serial>=epoch->first_serial &&
            serial-epoch->first_serial<3 && s.detailed<64;
        if(initial) ++s.detailed;
        const bool emit=initial || !s.emitted || (now_ms>=s.last_ms && now_ms-s.last_ms>=1000);
        if(emit) {s.emitted=true;s.last_ms=now_ms;}
        return {emit,s.count};
    }
private:
    struct Site {uint64_t count{},last_ms{};unsigned detailed{};bool emitted{};};
    struct Epoch {bool used{};uint64_t generation{},first_serial{};std::array<Site,site_count> sites{};};
    std::mutex mutex_{};
    std::array<Epoch,8> epochs_{};
    size_t next_{};
};
}

```

## FILE src/mods/vr/QuadViewNativeDelivery.hpp (830 lines)
```cpp
#pragma once

#include <array>
#include <atomic>
#include <cstdint>
#include <cstddef>
#include <mutex>
#include <optional>
#include <type_traits>

namespace uevr::quadview {

// Engine-only recovery callbacks can coalesce at one deferred Slate tail.
// Retire every authenticated ticket at that actual callback; this container
// cannot authorize source publication and never stands in for a GPU fence.
template<class Delivery> struct EngineDrainBatch {
    using Ticket=typename Delivery::EngineTicket;
    using Source=typename Delivery::Source;
    std::array<Ticket,32> tickets{};
    std::array<Source,32> leases{};
    size_t count{};
    uint64_t newest_serial{};
    uintptr_t tail{};
    bool allows_runtime(uint64_t generation,const Ticket& primary={}) const {
        return (!primary || primary.generation==generation) &&
            (!count || tickets[0].generation==generation);
    }
    bool attach(Delivery& delivery,const Ticket& ticket,uintptr_t command,Source source={}) {
        if (!ticket || !command || (tail && tail!=command)) return false;
        if(source && (source.generation!=ticket.generation || source.serial!=ticket.serial ||
            source.engine_frame!=ticket.engine_frame || source.family!=ticket.family ||
            source.target!=ticket.target || source.scene!=ticket.scene)) return false;
        for(size_t i=0;i<count;++i) if(tickets[i].same_owner(ticket)) {
            if(source && leases[i] && !leases[i].same_owner(source)) return false;
            if(source) leases[i]=std::move(source);
            return true;
        }
        if(count==tickets.size() || (count && tickets[0].generation!=ticket.generation)) return false;
        if(!delivery.tail_hooked_engine_family(ticket,command)) return false;
        tail=command;
        leases[count]=std::move(source);
        tickets[count++]=ticket;
        if(ticket.serial>newest_serial) newest_serial=ticket.serial;
        return true;
    }
    bool execute(Delivery& delivery,uintptr_t command,uint32_t thread,uint64_t generation) const {
        bool result=true;
        for(size_t i=0;i<count;++i) if(tickets[i].generation==generation)
            result=delivery.executed_engine_family(tickets[i],typename Delivery::Source{},command,thread) && result;
        return result;
    }
};

// Identifies one explicitly bracketed Slate-worker drain. The list pointer is
// retained alongside the unique drain token; a reused command-list address in
// a later execute() call therefore cannot establish shared-tail provenance.
class NativeDrainScope {
public:
    struct Identity { uint64_t id{}; uintptr_t immediate_list{}; };

    explicit NativeDrainScope(uintptr_t immediate_list) : previous_{current()} {
        if (immediate_list) {
            auto id=next_id_.fetch_add(1,std::memory_order_relaxed)+1;
            if (!id) id=next_id_.fetch_add(1,std::memory_order_relaxed)+1;
            current_id_=id;
            current_list_=immediate_list;
        } else { current_id_=0; current_list_=0; }
    }
    NativeDrainScope(const NativeDrainScope&)=delete;
    NativeDrainScope& operator=(const NativeDrainScope&)=delete;
    ~NativeDrainScope() { current_id_=previous_.id; current_list_=previous_.immediate_list; }

    static Identity current() { return {current_id_,current_list_}; }

private:
    inline static std::atomic<uint64_t> next_id_{};
    inline static thread_local uint64_t current_id_{};
    inline static thread_local uintptr_t current_list_{};
    Identity previous_{};
};

// Joins per-view renderer owners at the RHI tail that actually executes them.
// A tail can represent several roles only when the generated adapter supplies
// the same validated Slate-worker drain and immediate-list identity.  When
// those identities differ, or two quartets meet at one tail, the owners are
// still drained together but none of their source packets can be published.
template<class Delivery> class NativeDelivery {
public:
    using Source = typename Delivery::Source;
    using EngineTicket = typename Delivery::EngineTicket;

    // Fixed scalar summary; never copies a source, command, or packet owner.
    // Counts are sampled under one try-lock and may independently be busy.
    struct DiagnosticsSnapshot {
        uint64_t generation{};
        uint32_t occupied_slots{};
        uint32_t active_tails{};
        uint32_t shared_tails{};
        uint32_t ambiguous_tails{};
        uint64_t oldest_retained_generation{};
        uint64_t oldest_retained_serial{};
        std::array<uint32_t,4> oldest_retained_pending_count{};
        uint8_t oldest_retained_rendered{};
        uint8_t oldest_retained_hooked{};
        uint8_t oldest_retained_executed{};
        uint8_t oldest_retained_written{};
        bool oldest_retained_completion_latched{};
        bool oldest_retained_publish{};
        bool oldest_retained_overwritten{};
        bool oldest_retained_found{};
        bool busy{};
    };
    static_assert(std::is_trivially_copyable_v<DiagnosticsSnapshot>);

    struct Command {
        Source source{};
        EngineTicket engine{};
        uint64_t target_set{};
        uintptr_t target{};
        uint8_t view{};
        explicit operator bool() const {
            return bool(source) && bool(engine) && target_set && target && view < 4;
        }
    };

    struct TailTicket {
        uintptr_t command{};
        uint64_t id{};
        explicit operator bool() const { return command && id; }
    };

    struct RuntimeEvent {
        uint64_t generation{}, serial{};
        uint32_t frame{};
        explicit operator bool() const { return generation && serial; }
    };

    // Retained by the production RHI adapter from queueing until the original
    // command callback returns. NativeDelivery::reset() can retire ledger
    // slots while the CPU command is still queued, so the callback's map
    // record must independently keep each represented packet alive.
    struct TailOwnerBatch {
        static constexpr size_t capacity = 32; // same bound as live quartet slots
        TailTicket ticket{};
        std::array<Command,capacity> owners{};
        size_t owner_count{};

        bool retain(const Command& owner, TailTicket tail) {
            if (!owner || !tail || (ticket && (ticket.command != tail.command || ticket.id != tail.id)))
                return false;
            if (!ticket) ticket = tail;
            for (size_t i=0; i<owner_count; ++i) {
                const auto& existing=owners[i];
                if (existing.source.same_owner(owner.source) &&
                    existing.engine.same_owner(owner.engine) &&
                    existing.target_set==owner.target_set) return true;
            }
            if (owner_count==owners.size()) return false;
            owners[owner_count++]=owner;
            return true;
        }
    };

    enum class AttachStatus : uint8_t { attached, duplicate, quarantined, overflow, rejected };

    struct AttachResult {
        TailTicket tail{};
        AttachStatus status{AttachStatus::rejected};
        explicit operator bool() const {
            return bool(tail) && (status == AttachStatus::attached ||
                status == AttachStatus::duplicate || status == AttachStatus::quarantined);
        }
        bool publishable() const { return status == AttachStatus::attached || status == AttachStatus::duplicate; }
    };

    struct ExecutionResult {
        bool accepted{};
        bool quarantined{};
        uint32_t sync_frame{};
        uint64_t newest_serial{};
        uint8_t completed_quartets{};
        RuntimeEvent runtime_event{};
    };

    explicit NativeDelivery(Delivery& delivery): delivery_{delivery} {}

    DiagnosticsSnapshot diagnostics_snapshot(uint64_t generation = 0) const {
        DiagnosticsSnapshot result{};
        result.generation = generation;
        std::unique_lock<std::mutex> lock;
        try { lock = std::unique_lock<std::mutex>{mutex_, std::try_to_lock}; }
        catch (...) { result.busy = true; return result; }
        if (!lock.owns_lock()) {
            result.busy = true;
            return result;
        }
        for (const auto& slot : slots_) {
            if (!slot.source || (generation && slot.source.generation != generation)) continue;
            ++result.occupied_slots;
            if (!result.oldest_retained_found ||
                slot.source.generation < result.oldest_retained_generation ||
                (slot.source.generation == result.oldest_retained_generation &&
                 slot.source.serial < result.oldest_retained_serial)) {
                result.oldest_retained_found = true;
                result.oldest_retained_generation = slot.source.generation;
                result.oldest_retained_serial = slot.source.serial;
                result.oldest_retained_rendered = slot.rendered;
                result.oldest_retained_hooked = slot.hooked;
                result.oldest_retained_executed = slot.executed;
                result.oldest_retained_written = slot.written;
                result.oldest_retained_pending_count = slot.pending_count;
                result.oldest_retained_completion_latched = slot.completion_latched;
                result.oldest_retained_publish = slot.publish;
                result.oldest_retained_overwritten = slot.overwritten;
            }
        }
        for (const auto& tail : tails_) {
            if (!tail.command) continue;
            bool belongs = false;
            for (size_t i = 0; i < tail.attachment_count; ++i) {
                const auto& participant = tail.attachments[i];
                if (participant.slot >= slots_.size()) continue;
                const auto& slot = slots_[participant.slot];
                if (slot.owner_id != participant.owner_id || !slot.source ||
                    (generation && slot.source.generation != generation)) continue;
                belongs = true;
                break;
            }
            if (!belongs) continue;
            ++result.active_tails;
            bool shared = tail.attachment_count > 1;
            for (size_t i = 0; !shared && i < tail.attachment_count; ++i) {
                const auto mask = tail.attachments[i].view_mask;
                shared = mask != 0 && (mask & uint8_t(mask - 1)) != 0;
            }
            if (shared) ++result.shared_tails;
            if (tail.ambiguous) ++result.ambiguous_tails;
        }
        return result;
    }

    bool bind(Source source, EngineTicket engine, uint64_t target_set,
              std::array<uintptr_t,4> targets, bool explicit_role_frames = false,
              uint8_t required_roles = 0x0f) {
        if (!source || !engine || !target_set || source.generation != engine.generation ||
            source.serial != engine.serial || source.engine_frame != engine.engine_frame ||
            source.family != engine.family || source.target != engine.target ||
            source.scene != engine.scene) return false;
        source.engine_frame_bound = true;
        // Tri-view renders roles 0,2,3 (0x0d); role 0 always carries the batch.
        if ((required_roles & 0x01) == 0 || (required_roles & ~0x0f) != 0) return false;
        for (size_t i = 0; i < 4; ++i) {
            if ((required_roles & uint8_t(1u << i)) == 0) continue;
            if (!targets[i]) return false;
            for (size_t j = 0; j < i; ++j) {
                if ((required_roles & uint8_t(1u << j)) && targets[i] == targets[j]) return false;
            }
        }
        std::scoped_lock lock{mutex_};
        for (const auto& slot : slots_) if (slot.source &&
            slot.source.generation == source.generation && slot.source.serial == source.serial) return false;
        for (auto& slot : slots_) if (!slot.source) {
            auto owner_id = ++next_owner_id_;
            if (!owner_id) owner_id = ++next_owner_id_;
            slot.source = std::move(source);
            slot.engine = engine;
            slot.target_set = target_set;
            slot.targets = targets;
            slot.explicit_role_frames = explicit_role_frames;
            slot.required = required_roles;
            if (!explicit_role_frames) {
                slot.role_frames.fill(engine.engine_frame);
                slot.roles_bound = required_roles;
            }
            slot.owner_id = owner_id;
            return true;
        }
        return false;
    }

    // Called by the actual GT BeginRenderViewFamily callback, before Unreal
    // copies that singleton. Never infer a role's frame from another role.
    bool bind_role(uint64_t generation, uint64_t serial, size_t view,
                   uint32_t frame, uintptr_t target, uintptr_t scene) {
        if (view >= 4 || frame == UINT32_MAX || !target || !scene) return false;
        std::scoped_lock lock{mutex_};
        Slot* match{};
        for (auto& slot : slots_) if (slot.source && slot.source.generation == generation &&
            slot.source.serial == serial) {
            if (match) return false;
            match = &slot;
        }
        if (!match || !match->explicit_role_frames || match->targets[view] != target ||
            match->source.scene != scene) return false;
        const auto bit = uint8_t(1u << view);
        if (match->roles_bound & bit) {
            if (match->role_frames[view] == frame) return true;
            poison_slot(*match);
            return false;
        }
        match->role_frames[view] = frame;
        match->roles_bound |= bit;
        return true;
    }

    struct RenderTrace {
        // 0 accepted, 1 no role key, 2 ambiguous role key, 3 already rendered,
        // 4 no engine claim, 5 engine identity mismatch. Observation only.
        unsigned reason{1}, role{255};
        uint64_t serial{};
        uint32_t canonical_frame{};
        unsigned rendered{},hooked{},executed{},written{};
        bool engine_claim{},source_claim{},publish{};
    };
    std::optional<Command> render(uint64_t generation, uint32_t frame, uintptr_t target, uintptr_t scene,
                                  RenderTrace* trace=nullptr) {
        if(trace) *trace={};
        std::scoped_lock lock{mutex_};
        Slot* match{};
        size_t view{};
        for (auto& slot : slots_) if (slot.source && slot.source.generation == generation &&
            slot.source.scene == scene) {
            for (size_t i = 0; i < 4; ++i) if (slot.targets[i] == target &&
                (slot.roles_bound & (1u << i)) && slot.role_frames[i] == frame) {
                if (match) { if(trace) trace->reason=2; return {}; }
                match = &slot;
                view = i;
            }
        }
        if (!match) return {};
        if(trace) {
            trace->serial=match->source.serial;trace->canonical_frame=match->source.engine_frame;
            trace->role=unsigned(view);trace->rendered=match->rendered;trace->hooked=match->hooked;
            trace->executed=match->executed;trace->written=match->written;trace->publish=match->publish;
        }
        if(match->rendered & (1u << view)) {if(trace) trace->reason=3;return {};}
        if (!match->rendered) {
            const auto engine = delivery_.render_engine_family(
                generation, match->source.engine_frame, match->source.target, scene);
            const auto source = delivery_.render(
                generation, match->source.engine_frame, match->source.family, match->source.target, scene);
            if(trace) {trace->engine_claim=bool(engine);trace->source_claim=bool(source);}
            if (!engine || !engine->same_owner(match->engine)) {
                if(trace) trace->reason=engine ? 5 : 4;
                return {};
            }
            match->publish = source && source->same_owner(match->source);
        }
        match->rendered |= uint8_t(1u << view);
        if(trace) {trace->reason=0;trace->rendered=match->rendered;trace->publish=match->publish;}
        return Command{match->source, match->engine, match->target_set, target, uint8_t(view)};
    }

    // Compatibility entry point for the existing distinct-tail path and
    // portable ownership tests. Shared tails without an explicit validated
    // drain/list identity are attached as drain-only.
    bool hook(const Command& owner, uintptr_t command) {
        const auto result = hook_batch(owner, command, 0, 0, owner.source.engine_frame);
        return result.status == AttachStatus::attached || result.status == AttachStatus::quarantined;
    }

    AttachResult hook_batch(const Command& owner, uintptr_t command,
                            uint64_t drain_id, uintptr_t immediate_list,
                            uint32_t sync_frame) {
        std::scoped_lock lock{mutex_};
        const auto owner_index = find_index(owner);
        if (!owner || !command || owner_index == slots_.size()) return {};
        auto& owner_slot = slots_[owner_index];
        if (!(owner_slot.rendered & (1u << owner.view))) return {};

        auto* tail = find_tail(command);
        if (!tail) tail = allocate_tail(command, drain_id, immediate_list);
        if (!tail) {
            owner_slot.publish = false;
            owner_slot.overwritten = true;
            return {{}, AttachStatus::overflow};
        }

        const bool has_attachment = tail->attachment_count != 0;
        const bool scope_valid = drain_id != 0 && immediate_list != 0;
        const bool same_scope = scope_valid && tail->drain_id == drain_id &&
            tail->immediate_list == immediate_list;

        auto* participant = find_participant(*tail, owner_index, owner_slot.owner_id);
        if (participant && (participant->view_mask & (1u << owner.view))) {
            return {{command, tail->id}, tail->ambiguous ? AttachStatus::quarantined : AttachStatus::duplicate};
        }

        if (has_attachment && (!same_scope || !tail->scope_valid)) {
            poison_tail(*tail);
        }

        if (has_attachment) {
            for (size_t i = 0; i < tail->attachment_count; ++i) {
                const auto index = tail->attachments[i].slot;
                if (index >= slots_.size()) continue;
                const auto& existing = slots_[index];
                if (!existing.source.same_owner(owner_slot.source) ||
                    existing.target_set != owner_slot.target_set || existing.targets != owner_slot.targets) {
                    poison_tail(*tail);
                    break;
                }
            }
        }

        if (participant == nullptr) {
            if (tail->attachment_count == tail->attachments.size()) {
                poison_tail(*tail);
                owner_slot.publish = false;
                owner_slot.overwritten = true;
                return {{command, tail->id}, AttachStatus::quarantined};
            }
            participant = &tail->attachments[tail->attachment_count++];
            participant->slot = uint8_t(owner_index);
            participant->owner_id = owner_slot.owner_id;
        }

        // One renderer role may not be assigned two independent tails. Keep
        // both owners drainable, but reject content publication for the draw.
        if (owner_slot.hooked & (1u << owner.view)) {
            owner_slot.publish = false;
            owner_slot.overwritten = true;
            participant->view_mask |= uint8_t(1u << owner.view);
        } else {
            participant->view_mask |= uint8_t(1u << owner.view);
        }
        owner_slot.hooked |= uint8_t(1u << owner.view);
        // Tail storage bounds simultaneous pending attachments, but repeated
        // malformed callbacks could otherwise wrap cumulative byte counters.
        // Track only outstanding tails; each execution decrements one.
        if (owner_slot.pending_count[owner.view] == UINT32_MAX) {
            poison_slot(owner_slot);
            return {{command, tail->id}, AttachStatus::overflow};
        }
        ++owner_slot.pending_count[owner.view];
        owner_slot.executed &= uint8_t(~(1u << owner.view));
        if (!scope_valid) {
            tail->scope_valid = false;
            if (tail->attachment_count > 1) poison_tail(*tail);
        }
        // Runtime cadence belongs to the canonical view-3 callback. Other
        // native roles still attach/drain, but never advance OpenXR state.
        if (owner.view == 3 && (!tail->runtime_event ||
            owner_slot.source.generation > tail->runtime_event.generation ||
            (owner_slot.source.generation == tail->runtime_event.generation &&
             owner_slot.source.serial > tail->runtime_event.serial))) {
            tail->runtime_event={owner_slot.source.generation,owner_slot.source.serial,sync_frame};
        }

        if (tail->ambiguous) {
            owner_slot.publish = false;
            owner_slot.overwritten = true;
        }

        latch_completion(owner_slot);
        return {{command, tail->id}, tail->ambiguous ? AttachStatus::quarantined : AttachStatus::attached};
    }

    uint32_t sync_frame(const TailTicket& ticket) const {
        std::scoped_lock lock{mutex_};
        const auto* tail = find_tail(ticket);
        return tail && tail->runtime_event ? tail->runtime_event.frame : 0;
    }

    RuntimeEvent runtime_event(const TailTicket& ticket) const {
        std::scoped_lock lock{mutex_};
        const auto* tail=find_tail(ticket);
        return tail ? tail->runtime_event : RuntimeEvent{};
    }

    bool claim_runtime_event(const TailTicket& ticket,RuntimeEvent& event) {
        std::scoped_lock lock{mutex_};
        const auto* tail=find_tail(ticket);
        if (!tail || !tail->runtime_event) return false;
        const auto candidate=tail->runtime_event;
        if (candidate.generation==last_runtime_generation_ &&
            candidate.serial<=last_runtime_serial_) return false;
        if (candidate.generation<last_runtime_generation_) return false;
        last_runtime_generation_=candidate.generation;
        last_runtime_serial_=candidate.serial;
        event=candidate;
        return true;
    }

    ExecutionResult executed_tail(const TailTicket& ticket, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        auto* tail = find_tail(ticket);
        if (!tail || !thread || tail->executed) return {};
        for (size_t i = 0; i < tail->attachment_count; ++i) {
            const auto index = tail->attachments[i].slot;
            if (index < slots_.size() && slots_[index].owner_id == tail->attachments[i].owner_id &&
                slots_[index].source &&
                slots_[index].thread && slots_[index].thread != thread) return {};
        }
        tail->executed = true;
        ExecutionResult result{};
        result.accepted=true;
        result.quarantined=tail->ambiguous;
        result.sync_frame=tail->runtime_event ? tail->runtime_event.frame : 0;
        result.newest_serial=tail->runtime_event ? tail->runtime_event.serial : 0;
        result.runtime_event=tail->runtime_event;
        for (size_t i = 0; i < tail->attachment_count; ++i) {
            const auto index = tail->attachments[i].slot;
            if (index < slots_.size() && slots_[index].owner_id == tail->attachments[i].owner_id &&
                slots_[index].source) slots_[index].thread = thread;
        }

        if (tail->ambiguous) {
            invalidate_ambiguous_tail(*tail);
        } else {
            for (size_t i = 0; i < tail->attachment_count; ++i) {
                const auto participant = tail->attachments[i];
                if (participant.slot >= slots_.size()) continue;
                auto& slot = slots_[participant.slot];
                if (slot.owner_id != participant.owner_id || !slot.source) continue;
                for (size_t view = 0; view < 4; ++view) {
                    if ((participant.view_mask & (1u << view)) == 0) continue;
                    record_write(participant.slot, view);
                    if (slot.pending_count[view] != 0) {
                        --slot.pending_count[view];
                        if (slot.pending_count[view] == 0) slot.executed |= uint8_t(1u << view);
                    }
                }
            }
        }

        // A poisoned shared tail still drains every owner it actually covers.
        // Its content is untrusted, so role completion advances without
        // creating a selectable packet.
        if (tail->ambiguous) {
            for (size_t i = 0; i < tail->attachment_count; ++i) {
                const auto participant = tail->attachments[i];
                if (participant.slot >= slots_.size()) continue;
                auto& slot = slots_[participant.slot];
                if (slot.owner_id != participant.owner_id || !slot.source) continue;
                for (size_t view = 0; view < 4; ++view) {
                    if ((participant.view_mask & (1u << view)) == 0) continue;
                    if (slot.pending_count[view] != 0) {
                        --slot.pending_count[view];
                        if (slot.pending_count[view] == 0) slot.executed |= uint8_t(1u << view);
                    }
                }
            }
        }

        std::array<bool, 32> seen{};
        for (size_t i = 0; i < tail->attachment_count; ++i) {
            const auto index = tail->attachments[i].slot;
            if (index >= slots_.size() || seen[index] ||
                slots_[index].owner_id != tail->attachments[i].owner_id) continue;
            seen[index] = true;
            auto& slot = slots_[index];
            if (slot.source && slot.executed == slot.required && finish_quartet(slot, thread))
                ++result.completed_quartets;
        }
        *tail = {};
        return result;
    }

    // Existing distinct-tail entry point. It deliberately executes one tail
    // record, which may also contain other validated same-drain attachments.
    bool executed(const Command& owner, uintptr_t command, uint32_t thread) {
        TailTicket ticket{};
        {
            std::scoped_lock lock{mutex_};
            const auto owner_index = find_index(owner);
            const auto* tail = find_tail(command);
            if (!tail || owner_index == slots_.size()) return false;
            const auto* participant = find_participant(*tail, owner_index, slots_[owner_index].owner_id);
            if (!participant || (participant->view_mask & (1u << owner.view)) == 0) return false;
            ticket = {command, tail->id};
        }
        return executed_tail(ticket, thread).accepted;
    }

    void reset() {
        std::scoped_lock lock{mutex_};
        for (auto& slot : slots_) slot = {};
        for (auto& tail : tails_) tail = {};
        for (auto& stamp : content_) stamp = {};
        last_runtime_generation_=last_runtime_serial_=0;
    }

private:
    static constexpr size_t quartet_capacity = 32;
    static constexpr size_t tail_capacity = quartet_capacity * 4;
    static constexpr size_t target_capacity = quartet_capacity * 4;

    struct Slot {
        Source source{};
        EngineTicket engine{};
        uint64_t target_set{}, owner_id{};
        std::array<uintptr_t,4> targets{};
        std::array<uint32_t,4> role_frames{};
        uint8_t roles_bound{};
        bool explicit_role_frames{};
        std::array<uint32_t,4> pending_count{};
        uintptr_t completion_token{};
        uint32_t thread{};
        uint8_t rendered{}, hooked{}, executed{}, written{};
        uint8_t required{0x0f};
        bool overwritten{}, publish{true}, completion_latched{};
    };
    struct Participant { uint8_t slot{}; uint8_t view_mask{}; uint64_t owner_id{}; };
    struct Tail {
        uintptr_t command{};
        uint64_t id{}, drain_id{};
        uintptr_t immediate_list{};
        RuntimeEvent runtime_event{};
        std::array<Participant,quartet_capacity> attachments{};
        uint8_t attachment_count{};
        bool scope_valid{}, ambiguous{}, executed{};
    };
    struct ContentStamp {
        uintptr_t target{};
        uint64_t target_set{}, generation{}, serial{};
        uint32_t engine_frame{};
        uintptr_t family{}, source_target{}, scene{};
        std::array<uintptr_t,4> views{};
        bool valid{};
    };

    size_t find_index(const Command& owner) const {
        if (!owner) return slots_.size();
        for (size_t i = 0; i < slots_.size(); ++i) {
            const auto& slot = slots_[i];
            if (slot.source && slot.source.same_owner(owner.source) &&
                slot.engine.same_owner(owner.engine) && slot.target_set == owner.target_set &&
                owner.view < 4 && slot.targets[owner.view] == owner.target) return i;
        }
        return slots_.size();
    }
    Tail* find_tail(uintptr_t command) {
        for (auto& tail : tails_) if (tail.command == command && !tail.executed) return &tail;
        return nullptr;
    }
    const Tail* find_tail(uintptr_t command) const {
        for (const auto& tail : tails_) if (tail.command == command && !tail.executed) return &tail;
        return nullptr;
    }
    Tail* find_tail(const TailTicket& ticket) {
        for (auto& tail : tails_) if (tail.command == ticket.command && tail.id == ticket.id) return &tail;
        return nullptr;
    }
    const Tail* find_tail(const TailTicket& ticket) const {
        for (const auto& tail : tails_) if (tail.command == ticket.command && tail.id == ticket.id) return &tail;
        return nullptr;
    }
    Tail* allocate_tail(uintptr_t command, uint64_t drain_id,
                        uintptr_t immediate_list) {
        for (auto& tail : tails_) if (!tail.command) {
            auto id = ++next_tail_id_;
            if (!id) id = ++next_tail_id_;
            tail.command = command;
            tail.id = id;
            tail.drain_id = drain_id;
            tail.immediate_list = immediate_list;
            tail.scope_valid = drain_id != 0 && immediate_list != 0;
            return &tail;
        }
        return nullptr;
    }
    Participant* find_participant(Tail& tail, size_t slot, uint64_t owner_id) {
        for (size_t i = 0; i < tail.attachment_count; ++i)
            if (tail.attachments[i].slot == slot && tail.attachments[i].owner_id == owner_id)
                return &tail.attachments[i];
        return nullptr;
    }
    const Participant* find_participant(const Tail& tail, size_t slot, uint64_t owner_id) const {
        for (size_t i = 0; i < tail.attachment_count; ++i)
            if (tail.attachments[i].slot == slot && tail.attachments[i].owner_id == owner_id)
                return &tail.attachments[i];
        return nullptr;
    }
    void poison_slot(Slot& slot) {
        if (!slot.source) return;
        slot.publish = false;
        slot.overwritten = true;
        delivery_.retire(slot.source.generation, slot.source.serial);
    }
    void poison_tail(Tail& tail) {
        tail.ambiguous = true;
        for (size_t i = 0; i < tail.attachment_count; ++i) {
            const auto index = tail.attachments[i].slot;
            if (index < slots_.size() && slots_[index].owner_id == tail.attachments[i].owner_id)
                poison_slot(slots_[index]);
        }
    }
    void latch_completion(Slot& slot) {
        if (slot.completion_latched) return;
        if (slot.hooked != slot.required) return;
        slot.completion_latched = true;
        auto token = ++next_completion_token_;
        if (!token) token = ++next_completion_token_;
        slot.completion_token = static_cast<uintptr_t>(token);
        const bool source_attached = slot.publish && delivery_.tail_hooked_engine_family(
            slot.engine, slot.source, slot.completion_token);
        if (!source_attached) {
            // The ordinary source ledger may have reclaimed this packet after
            // render(). Preserve engine-ticket drainage, but never advertise a
            // completion token as publishable when only the empty fallback fit.
            slot.publish = false;
            slot.overwritten = true;
            if (!delivery_.tail_hooked_engine_family(slot.engine, Source{}, slot.completion_token)) {
                slot.overwritten = true;
            }
        }
    }
    static bool stamp_matches(const ContentStamp& stamp, const Slot& slot) {
        return stamp.valid && stamp.target_set == slot.target_set &&
            stamp.generation == slot.source.generation && stamp.serial == slot.source.serial &&
            stamp.engine_frame == slot.source.engine_frame && stamp.family == slot.source.family &&
            stamp.source_target == slot.source.target && stamp.scene == slot.source.scene &&
            stamp.views == slot.source.view_ids;
    }
    ContentStamp* find_content(uintptr_t target) {
        for (auto& stamp : content_) if (stamp.target == target) return &stamp;
        for (auto& stamp : content_) if (!stamp.target) {
            stamp.target = target;
            return &stamp;
        }
        for (auto& stamp : content_) {
            if (target_is_live(stamp.target)) continue;
            // The source may still be selectable even though its quartet has
            // drained. Evicting provenance must evict that source too, or the
            // Delivery ledger could later return a packet for unknown pixels.
            if (stamp.valid) delivery_.retire(stamp.generation, stamp.serial);
            stamp = {};
            stamp.target = target;
            return &stamp;
        }
        return nullptr;
    }
    const ContentStamp* find_content(uintptr_t target) const {
        for (const auto& stamp : content_) if (stamp.target == target) return &stamp;
        return nullptr;
    }
    bool target_is_live(uintptr_t target) const {
        if (!target) return false;
        for (const auto& slot : slots_) {
            if (!slot.source) continue;
            for (const auto candidate : slot.targets) if (candidate == target) return true;
        }
        return false;
    }
    bool content_matches(const Slot& slot) const {
        for (size_t i = 0; i < slot.targets.size(); ++i) {
            if ((slot.required & (1u << i)) == 0) continue;
            const auto* stamp = find_content(slot.targets[i]);
            if (!stamp || !stamp_matches(*stamp, slot)) return false;
        }
        return true;
    }
    void invalidate_resource(uintptr_t target, const Slot* writer) {
        auto* stamp = find_content(target);
        if (stamp) {
            const bool same_writer = writer && stamp_matches(*stamp, *writer);
            if (stamp->valid && !same_writer)
                delivery_.retire(stamp->generation, stamp->serial);
            stamp->valid = false;
        }
        for (auto& candidate : slots_) {
            if (!candidate.source) continue;
            if (writer && candidate.source.same_owner(writer->source)) continue;
            bool wrote_target{};
            for (size_t i = 0; i < candidate.targets.size(); ++i) {
                if (candidate.targets[i] == target && (candidate.written & (1u << i))) {
                    wrote_target = true;
                    break;
                }
            }
            // A queued quartet has no physical content to invalidate yet.
            // Only a writer that has already touched this target can have
            // become incoherent due to this new write.
            if (!wrote_target) continue;
            poison_slot(candidate);
        }
    }
    void record_write(size_t index, size_t view) {
        auto& writer = slots_[index];
        const auto target = writer.targets[view];
        if (!target) return;
        writer.written |= uint8_t(1u << view);
        invalidate_resource(target, &writer);
        if (!writer.publish || writer.overwritten) {
            delivery_.retire(writer.source.generation, writer.source.serial);
            return;
        }
        auto* stamp = find_content(target);
        if (!stamp) {
            poison_slot(writer);
            return;
        }
        *stamp = ContentStamp{target, writer.target_set, writer.source.generation,
            writer.source.serial, writer.source.engine_frame, writer.source.family,
            writer.source.target, writer.source.scene, writer.source.view_ids, true};
    }
    void invalidate_ambiguous_tail(const Tail& tail) {
        for (size_t i = 0; i < tail.attachment_count; ++i) {
            const auto index = tail.attachments[i].slot;
            if (index >= slots_.size() || slots_[index].owner_id != tail.attachments[i].owner_id ||
                !slots_[index].source) continue;
            auto& slot = slots_[index];
            for (size_t view = 0; view < slot.targets.size(); ++view) {
                if (tail.attachments[i].view_mask & (1u << view))
                    record_write(index, view);
            }
            poison_slot(slot);
        }
    }
    bool finish_quartet(Slot& slot, uint32_t thread) {
        if (!slot.completion_latched || !thread || !slot.completion_token) return false;
        const bool coherent = slot.publish && !slot.overwritten && content_matches(slot);
        const auto source = coherent ? slot.source : Source{};
        const bool retired = delivery_.executed_engine_family(
            slot.engine, source, slot.completion_token, thread);
        if (!coherent) delivery_.retire(slot.source.generation, slot.source.serial);
        if (retired) slot = {};
        return retired;
    }

    Delivery& delivery_;
    mutable std::mutex mutex_{};
    std::array<Slot,quartet_capacity> slots_{};
    std::array<Tail,tail_capacity> tails_{};
    std::array<ContentStamp,target_capacity> content_{};
    uint64_t next_tail_id_{}, next_completion_token_{}, next_owner_id_{};
    uint64_t last_runtime_generation_{},last_runtime_serial_{};
};
}

```

## FILE src/mods/vr/QuadViewNativeRetirementDiagnostics.hpp (74 lines)
```cpp
#pragma once

#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace uevr::quadview {

inline constexpr size_t native_retirement_list_walk_cap = 256;

enum class NativeRetirementPollState : uint8_t {
    unobserved,
    value_observed,
    device_removed,
};

struct NativeRetirementListCount {
    uint32_t count{}; // Lower bound when truncated is true.
    bool truncated{};
};

// A fixed-size, ownership-free snapshot. List caps apply independently to
// pending, staged, in-flight, and ready lists (up to 4 * 256 nodes total).
struct NativeRetirementDiagnostics {
    NativeRetirementListCount pending{};
    NativeRetirementListCount staged{};
    NativeRetirementListCount in_flight{};
    NativeRetirementListCount ready{};
    uintptr_t last_successful_queue{};
    uintptr_t last_successful_device{};
    uintptr_t last_successful_fence{};
    uint64_t last_successful_signal_value{};
    uintptr_t last_poll_fence{};
    uintptr_t last_poll_device{};
    uint64_t last_poll_completed_value{};
    uint64_t last_poll_target_value{};
    NativeRetirementPollState last_poll_state{NativeRetirementPollState::unobserved};
    bool observed{};
    bool busy{};
    bool last_successful_signal_observed{};
};
static_assert(std::is_trivially_copyable_v<NativeRetirementDiagnostics>);

template <class Node, class Next>
NativeRetirementListCount count_native_retirement_list(
    Node* head, Next&& next, size_t cap = native_retirement_list_walk_cap) noexcept {
    NativeRetirementListCount result{};
    if (cap > native_retirement_list_walk_cap) cap = native_retirement_list_walk_cap;
    while (head && result.count < cap) {
        ++result.count;
        head = next(head);
    }
    result.truncated = head != nullptr;
    return result;
}

constexpr NativeRetirementPollState native_retirement_poll_state(
    bool observed, uint64_t completed_value) noexcept {
    if (!observed) return NativeRetirementPollState::unobserved;
    return completed_value == UINT64_MAX
        ? NativeRetirementPollState::device_removed
        : NativeRetirementPollState::value_observed;
}

constexpr const char* to_string(NativeRetirementPollState state) noexcept {
    switch (state) {
    case NativeRetirementPollState::unobserved: return "unobserved";
    case NativeRetirementPollState::value_observed: return "value_observed";
    case NativeRetirementPollState::device_removed: return "device_removed";
    }
    return "unknown";
}

} // namespace uevr::quadview

```

## FILE src/mods/vr/QuadViewNativeTargets.hpp (95 lines)
```cpp
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace uevr::quadview {

// The renderer writes four independent UE-owned targets before a stereo packet
// can be published. Keep the identity proof independent of D3D/UE headers so it
// can be exercised by the portable contract tests.
struct NativeTargetIdentity {
    uintptr_t owner_texture{};
    uintptr_t render_target{};
    uintptr_t rhi_texture{};
    uintptr_t native_resource{};
    uint64_t target_set_generation{};
    uint32_t width{}, height{}, format{};
};

inline bool valid_native_target_quartet(const std::array<NativeTargetIdentity, 4>& targets) {
    const auto& first = targets[0];
    if (!first.owner_texture || !first.render_target || !first.rhi_texture || !first.native_resource ||
        !first.target_set_generation || !first.width || !first.height || !first.format) return false;
    for (size_t i = 0; i != targets.size(); ++i) {
        const auto& target = targets[i];
        if (!target.owner_texture || !target.render_target || !target.rhi_texture || !target.native_resource ||
            target.target_set_generation != first.target_set_generation || target.width != first.width ||
            target.height != first.height || target.format != first.format) return false;
        for (size_t j = 0; j < i; ++j) {
            const auto& prior = targets[j];
            if (target.owner_texture == prior.owner_texture || target.render_target == prior.render_target ||
                target.rhi_texture == prior.rhi_texture || target.native_resource == prior.native_resource) return false;
        }
    }
    return true;
}

// Tri-view B6: same contract as the quartet, but each role has its own
// expected extent (compact sources). Equal extents == the quartet rule.
inline bool valid_native_target_roles(const std::array<NativeTargetIdentity, 4>& targets,
                                      const std::array<std::array<uint32_t, 2>, 4>& extents) {
    const auto& first = targets[0];
    if (!first.target_set_generation || !first.format) return false;
    for (size_t i = 0; i != targets.size(); ++i) {
        const auto& target = targets[i];
        if (!target.owner_texture || !target.render_target || !target.rhi_texture || !target.native_resource ||
            !extents[i][0] || !extents[i][1] || target.width != extents[i][0] || target.height != extents[i][1] ||
            target.target_set_generation != first.target_set_generation || target.format != first.format) return false;
        for (size_t j = 0; j < i; ++j) {
            const auto& prior = targets[j];
            if (target.owner_texture == prior.owner_texture || target.render_target == prior.render_target ||
                target.rhi_texture == prior.rhi_texture || target.native_resource == prior.native_resource) return false;
        }
    }
    return true;
}



// B17: the logical view array still has four indices (0,1,2,3), but slot 1
// is intentionally dormant. Only roles 0 (shared periphery), 2 (left fovea),
// and 3 (right fovea) own UE textures, FRenderTargets and GPU resources.
inline bool valid_native_triview_targets(
    const std::array<NativeTargetIdentity, 4>& targets,
    const std::array<std::array<uint32_t, 2>, 4>& extents) {
    if (extents[1][0] || extents[1][1]) return false;
    const auto& unused = targets[1];
    if (unused.owner_texture || unused.render_target || unused.rhi_texture ||
        unused.native_resource || unused.target_set_generation ||
        unused.width || unused.height || unused.format) return false;

    constexpr std::array<size_t, 3> roles{0, 2, 3};
    const auto& first = targets[0];
    if (!first.target_set_generation || !first.format) return false;
    for (size_t pos = 0; pos < roles.size(); ++pos) {
        const auto i = roles[pos];
        const auto& target = targets[i];
        if (!target.owner_texture || !target.render_target || !target.rhi_texture ||
            !target.native_resource || !extents[i][0] || !extents[i][1] ||
            target.width != extents[i][0] || target.height != extents[i][1] ||
            target.target_set_generation != first.target_set_generation ||
            target.format != first.format) return false;
        for (size_t prev = 0; prev < pos; ++prev) {
            const auto& earlier = targets[roles[prev]];
            if (target.owner_texture == earlier.owner_texture ||
                target.render_target == earlier.render_target ||
                target.rhi_texture == earlier.rhi_texture ||
                target.native_resource == earlier.native_resource) return false;
        }
    }
    return true;
}

} // namespace uevr::quadview

```

## FILE src/mods/vr/QuadViewNgxDepth.hpp (576 lines)
```cpp
#pragma once
// Tri-view B11: capture the DLSS depth input of the PERIPHERY render every frame.
// Hooks (safetyhook, inline): NVSDK_NGX_D3D12_EvaluateFeature(_C) and
// Create/ReleaseFeature(_C) in nvngx_dlss.dll / _nvngx.dll, plus
// ID3D12CommandQueue::ExecuteCommandLists (vtable slot 10) to know when the
// game's command list holding our copy has been submitted. Never interferes
// with DLSS: inputs are restored before the original Evaluate; result is unchanged.
// Approximate candidate selection = DLSS output size: make_layout() keeps the periphery size distinct
// from both foveas (QuadViewNgxSelect.hpp), so only the periphery can match.
// Ordering: the copy is recorded on the game's DIRECT list and the compositor
// draws on the same DIRECT queue later, so a copy whose list was SUBMITTED
// before the compositor's own submission is complete when the GPU reads it.
// Slot reuse still waits for a producer fence and for every compositor lease.
// The depth subrect is copied on the game's own DIRECT command list before
// Evaluate into an owned R32 texture (ALL_SHADER_RESOURCE between uses).
#include <Windows.h>
#include <d3d11.h>
#include <d3d12.h>
#include <wrl/client.h>
#include <safetyhook.hpp>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <utility>
#include <vector>
#include "QuadViewDepthContinuity.hpp"
#include "QuadViewNgxSelect.hpp"
#include "QuadViewDepthIdentity.hpp"

namespace uevr::quadview::ngx {
using Microsoft::WRL::ComPtr;


struct NgxParameters {
    virtual void Set(const char*, unsigned long long) = 0;
    virtual void Set(const char*, float) = 0;
    virtual void Set(const char*, double) = 0;
    virtual void Set(const char*, unsigned int) = 0;
    virtual void Set(const char*, int) = 0;
    virtual void Set(const char*, ID3D11Resource*) = 0;
    virtual void Set(const char*, ID3D12Resource*) = 0;
    virtual void Set(const char*, void*) = 0;
    virtual uint32_t Get(const char*, unsigned long long*) const = 0;
    virtual uint32_t Get(const char*, float*) const = 0;
    virtual uint32_t Get(const char*, double*) const = 0;
    virtual uint32_t Get(const char*, unsigned int*) const = 0;
    virtual uint32_t Get(const char*, int*) const = 0;
    virtual uint32_t Get(const char*, ID3D11Resource**) const = 0;
    virtual uint32_t Get(const char*, ID3D12Resource**) const = 0;
    virtual uint32_t Get(const char*, void**) const = 0;
    virtual void Reset() = 0;
};
inline bool ngx_success(uint32_t r) noexcept { return (r & 0xfff00000u) != 0xbad00000u; }
inline uint32_t ngx_uint(const NgxParameters* p, const char* k) noexcept {
    unsigned int u{};
    if (ngx_success(p->Get(k, &u))) return u;
    int s{};
    return ngx_success(p->Get(k, &s)) && s > 0 ? uint32_t(s) : 0u;
}
inline ID3D12Resource* ngx_resource(const NgxParameters* p, const char* k) noexcept {
    ID3D12Resource* v{};
    return ngx_success(p->Get(k, &v)) ? v : nullptr;
}

struct DepthSnapshot {
    ComPtr<ID3D12Resource> texture;          // owned R32_TYPELESS copy
    ComPtr<ID3D12Resource> source_reference; // retained through producer GPU completion
    // B13: independent per-recording GPU fence; queue signals can finish out of order.
    ComPtr<ID3D12Fence> producer_fence;
    ID3D12GraphicsCommandList* producer_list{}; // comparison only
    ComPtr<ID3D12GraphicsCommandList> pending_list_lease; // prevents pending object address reuse
    uint64_t sequence{}, producer_fence_value{}, list_epoch{};
    std::array<float,2> jitter_pixels{}, jitter_uv{};
    bool jitter_valid{};
    DepthOwner owner{};
    bool valid_evaluation{};
    std::chrono::steady_clock::time_point recorded{}, submitted_at{};
    uint32_t out_w{}, out_h{}, rect[4]{};
    DXGI_FORMAT srv_format{DXGI_FORMAT_R32_FLOAT}; // R32_FLOAT or R32_FLOAT_X8X24_TYPELESS (plane 0)
    bool pending{}, submitted{};
    bool foreign_queue{}; // submitted on a queue other than the compositor's: wait for its fence
};

class PeripheryDepth final {
public:
    // B42: slots and texture payload of the depth snapshot pool (for the VRAM log).
    std::pair<uint32_t, uint64_t> pool_usage() {
        std::scoped_lock lock(mutex_);
        uint64_t bytes = 0;
        for (const auto& slot : pool_) {
            if (!slot || !slot->texture) continue;
            const auto d = slot->texture->GetDesc();
            bytes += d.Width * d.Height * (d.Format == DXGI_FORMAT_R32G8X24_TYPELESS ? 8ull : 4ull);
        }
        return {static_cast<uint32_t>(pool_.size()), bytes};
    }
    static PeripheryDepth& self() { static auto* instance = new PeripheryDepth; return *instance; } // never destroyed

    // Game thread, per draw: expected periphery output size (0 = disabled).
    void set_expected(uint32_t w, uint32_t h) {
        want_w_.store(w, std::memory_order_relaxed); want_h_.store(h, std::memory_order_relaxed);
    }
    // Rare runtime restart only. Tracked foreign-queue copies must actually
    // have completed; the old session's depth snapshots cannot be reused.
    bool restart_quiescent() const {
        if (enabled_.load(std::memory_order_acquire)) return false;
        std::unique_lock lock{mutex_,std::try_to_lock};
        if (!lock.owns_lock()) return false;
        for (const auto& slot:pool_) {
            if (!slot || slot->pending || slot.use_count()!=1) return false;
            if (slot->submitted) {
                if (!slot->producer_fence) return false;
                const auto completed=slot->producer_fence->GetCompletedValue();
                if (!depth_copy_complete(completed,slot->producer_fence_value)) return false;
            }
        }
        return true;
    }
    // B26: the depth pool belongs to the game/D3D12 device, not XrSession,
    // but B21's 250 ms 'latest' policy can otherwise select OLD-session depth
    // immediately after an OpenXR reinitialization. Drop only fully completed
    // and unleased slots. Preserve NVSDK hooks, NGX feature map, device/queue
    // and monotonic recording sequence (these are NOT XR-session objects).
    bool discard_completed_for_new_xr_session() {
        if (enabled_.load(std::memory_order_acquire)) return false;
        std::unique_lock lock{mutex_,std::try_to_lock};
        if (!lock.owns_lock()) return false;
        for (const auto& slot:pool_) {
            if (!slot || slot->pending || slot.use_count()!=1) return false;
            if (slot->submitted) {
                if (!slot->producer_fence) return false;
                if (!depth_copy_complete(slot->producer_fence->GetCompletedValue(),
                                          slot->producer_fence_value)) return false;
            }
        }
        pool_.clear();
        want_w_.store(0,std::memory_order_release);
        want_h_.store(0,std::memory_order_release);
        last_used_age_us_.store(0,std::memory_order_relaxed);
        return true;
    }
    static constexpr bool capture_supported() noexcept { return true; }
    void set_enabled(bool on) {
        enabled_.store(on && capture_supported(), std::memory_order_release);
        // Active capture already prunes on the recording path. Avoid a
        // duplicate pool/fence scan on every Present while capture is on.
        if (on) return;
        std::scoped_lock lock(mutex_);
        prune_locked(want_w_.load(),want_h_.load(),true);
    }

    // Present thread: install hooks lazily (only while Tri-view depth is on).
    void install(ID3D12CommandQueue* queue) {
        if (!enabled_.load(std::memory_order_acquire) || !queue) return;
        std::scoped_lock install_lock(hook_install_mutex_);
        const auto now = std::chrono::steady_clock::now();
        // Missing/delayed NGX exports still retry. Once queue/fence tracking
        // exists, DLL/export discovery need not take the loader lock every
        // Present. This gate never delays recording/submission bookkeeping.
        if (queue_ && execute_ok_ && fence_ && now < next_install_retry_) return;
        next_install_retry_ = now + std::chrono::seconds(1);
        if (!queue_ && queue->GetDesc().Type == D3D12_COMMAND_LIST_TYPE_DIRECT &&
            SUCCEEDED(queue->GetDevice(IID_PPV_ARGS(&device_)))) queue_ = queue;
        if (queue_ && queue_.Get() == queue && !execute_ok_) {
            auto* vtbl = *reinterpret_cast<void***>(queue);
            if (vtbl && vtbl[10]) {
                auto hook = safetyhook::create_inline(vtbl[10], reinterpret_cast<void*>(&execute_commands),
                    safetyhook::InlineHook::StartDisabled);
                if (hook) { execute_ = std::move(hook); if (execute_.enable()) execute_ok_ = true; else execute_.reset(); }
            }
        }
        if (!execute_ok_) return; // never capture without submission tracking
        if (!fence_ && FAILED(device_->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence_)))) return;
        install_group(evals_, eval_ok_, {"NVSDK_NGX_D3D12_EvaluateFeature", "NVSDK_NGX_D3D12_EvaluateFeature_C"},
            {reinterpret_cast<void*>(&evaluate<0>), reinterpret_cast<void*>(&evaluate<1>),
             reinterpret_cast<void*>(&evaluate<2>), reinterpret_cast<void*>(&evaluate<3>),
             reinterpret_cast<void*>(&evaluate<4>), reinterpret_cast<void*>(&evaluate<5>)});
        install_group(creates_, create_ok_, {"NVSDK_NGX_D3D12_CreateFeature", "NVSDK_NGX_D3D12_CreateFeature_C"},
            {reinterpret_cast<void*>(&create<0>), reinterpret_cast<void*>(&create<1>),
             reinterpret_cast<void*>(&create<2>), reinterpret_cast<void*>(&create<3>),
             reinterpret_cast<void*>(&create<4>), reinterpret_cast<void*>(&create<5>)});
        install_group(releases_, release_ok_, {"NVSDK_NGX_D3D12_ReleaseFeature", "NVSDK_NGX_D3D12_ReleaseFeature_C"},
            {reinterpret_cast<void*>(&release<0>), reinterpret_cast<void*>(&release<1>),
             reinterpret_cast<void*>(&release<2>), reinterpret_cast<void*>(&release<3>),
             reinterpret_cast<void*>(&release<4>), reinterpret_cast<void*>(&release<5>)});
    }

    // B21: restore the B15-27 selector, which was stable in the headset.
    // Use only a recently SUBMITTED peripheral snapshot (<=250 ms), not an
    // arbitrary NGX recording timestamp relative to this packet's birth.
    // Render/RHI/present work overlaps, so packet-birth time is not a reliable
    // NGX frame association. Exact depth/color provenance is NOT established.
    // B18 Reset epochs, fence checks and compositor-held leases are retained.
    std::shared_ptr<const DepthSnapshot> latest_recent_submitted() {
        const auto w = want_w_.load(std::memory_order_relaxed), h = want_h_.load(std::memory_order_relaxed);
        if (!enabled_.load(std::memory_order_acquire) || !w || !h) { ++missed_; return {}; }
        const auto now = std::chrono::steady_clock::now();
        std::scoped_lock lock(mutex_);
        std::shared_ptr<DepthSnapshot> best;
        for (const auto& slot : pool_) {
            const uint64_t completed = slot->producer_fence ? slot->producer_fence->GetCompletedValue() : 0;
            if (slot->submitted && depth_copy_complete(completed, slot->producer_fence_value))
                slot->source_reference.Reset();
            if (slot->submitted && slot->valid_evaluation && slot->texture && matches_periphery(slot->out_w, slot->out_h, w, h) &&
                (!slot->foreign_queue || depth_copy_complete(completed, slot->producer_fence_value)) &&
                now >= slot->submitted_at && now - slot->submitted_at < std::chrono::milliseconds(250) && (!best || slot->sequence > best->sequence)) best = slot;
        }
        if (best) { ++used_; last_used_age_us_.store(uint32_t(std::chrono::duration_cast<std::chrono::microseconds>(now - best->submitted_at).count()), std::memory_order_relaxed); }
        else ++missed_;
        return best;
    }

    // Why the last DLSS evaluation was not captured (shown in the menu and log).
    enum Reason : uint32_t { None, NoExpectedSize, OtherSize, NotSuperResolution, NoDepthParameter, BadDepthFormat,
                             OtherDevice, PoolFull, AllocationFailed, NoFence, Exception, RecordingHookUnavailable, SignalFailed };
    static const char* reason_name(uint32_t r) {
        static const char* names[]{"none", "periphery size unknown (not TriView / layout pending)", "other size (fovea or other pass)",
            "not DLSS super resolution", "no Depth parameter", "unsupported depth format/rect", "other D3D12 device",
            "all 12 depth slots busy", "texture allocation failed", "no fence", "exception", "command-list Reset tracking unavailable", "producer queue signal failed; copy quarantined"};
        return r < std::size(names) ? names[r] : "?";
    }

    struct Stats { uint64_t evaluations, matches, captures, submits, used, missed, skips; uint32_t last_out_w, last_out_h, last_in_w, last_in_h, last_format, hooks;
                   bool queue_hook; uint32_t want_w, want_h, other_w, other_h, reason, used_age_us, slots; bool jitter_valid; float jitter_x, jitter_y; uint64_t foreign_queue_submits; };
    Stats stats() const {
        uint32_t hooks = 0, slots = 0; bool queue_hook = false;
        { std::scoped_lock lock(hook_install_mutex_,mutex_); for (bool b : eval_ok_) hooks += b; queue_hook = execute_ok_; slots = uint32_t(pool_.size()); }
        return {evaluations_.load(), matches_.load(), captures_.load(), submits_.load(), used_.load(), missed_.load(), skips_.load(),
                last_out_w_.load(), last_out_h_.load(), last_in_w_.load(), last_in_h_.load(), last_format_.load(), hooks, queue_hook,
                want_w_.load(), want_h_.load(), other_w_.load(), other_h_.load(), last_reason_.load(), last_used_age_us_.load(), slots,
                last_jitter_valid_.load(), last_jitter_x_.load(), last_jitter_y_.load(), foreign_queue_submits_.load()};
    }

private:
    using Hooks = std::array<safetyhook::InlineHook, 6>; // 3 DLLs x 2 exports
    static constexpr size_t MaxSlots = 12;
    mutable std::mutex mutex_;
    mutable std::mutex hook_install_mutex_;
    std::mutex reset_install_mutex_;
    // Serialize CPU submission bookkeeping with Reset. Reset after Execute is
    // legal before GPU completion; it must never erase that submission proof.
    DepthSubmissionSequence submission_sequence_;
    ComPtr<ID3D12CommandQueue> queue_;
    ComPtr<ID3D12Device> device_;
    safetyhook::InlineHook execute_{};
    bool execute_ok_{};
    Hooks evals_{}, creates_{}, releases_{}, resets_{};
    DepthRecordingEpochs recording_epochs_{};
    std::array<bool,6> reset_ok_{};
    std::array<bool, 6> eval_ok_{}, create_ok_{}, release_ok_{};
    ComPtr<ID3D12Fence> fence_;
    uint64_t next_fence_value_{};
    std::unordered_map<uintptr_t, uint32_t> feature_kind_{};
    std::chrono::steady_clock::time_point next_install_retry_{}; // hook_install_mutex_
    std::vector<std::shared_ptr<DepthSnapshot>> pool_{};
    uint64_t next_sequence_{};
    std::atomic<bool> enabled_{false};
    std::atomic<uint32_t> want_w_{}, want_h_{}, last_out_w_{}, last_out_h_{}, last_in_w_{}, last_in_h_{}, last_format_{};
    std::atomic<uint32_t> other_w_{}, other_h_{}, last_reason_{}, last_used_age_us_{};
    std::atomic<bool> last_jitter_valid_{};
    std::atomic<uint64_t> foreign_queue_submits_{};
    std::atomic<float> last_jitter_x_{}, last_jitter_y_{};
    // Release only obsolete, unleased copies with actual producer completion.
    // Pending/discard-unknown recordings remain retained until observed Reset.
    void prune_locked(uint32_t w,uint32_t h,bool disabled) {
        for(auto it=pool_.begin();it!=pool_.end();) {
            const auto& slot=*it;
            const bool obsolete=disabled || slot->out_w!=w || slot->out_h!=h;
            if(!obsolete || slot->pending || slot.use_count()!=1) { ++it;continue; }
            const auto done=slot->submitted && slot->producer_fence
                ? slot->producer_fence->GetCompletedValue() : 0;
            if(depth_slot_reusable(slot->pending,slot->submitted,done,
                    slot->producer_fence_value,slot.use_count())) it=pool_.erase(it);
            else ++it;
        }
    }
    void reject(Reason r) { last_reason_.store(r, std::memory_order_relaxed); ++skips_; }
    std::atomic<uint64_t> evaluations_{}, matches_{}, captures_{}, submits_{}, used_{}, missed_{}, skips_{};
    static inline thread_local unsigned nested_{};
    struct Guard { bool outer{nested_++ == 0}; ~Guard() { --nested_; } };

    static void transition(ID3D12GraphicsCommandList* cmd, ID3D12Resource* r, D3D12_RESOURCE_STATES a, D3D12_RESOURCE_STATES b) {
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition = {r, 0, a, b};
        cmd->ResourceBarrier(1, &barrier);
    }

    std::shared_ptr<DepthSnapshot> inspect(ID3D12GraphicsCommandList* cmd, void* feature, const NgxParameters* p) {
        if (!enabled_.load(std::memory_order_acquire) || !cmd || !feature || !p ||
            cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT) return {};
        ++evaluations_;
        const auto want_w = want_w_.load(std::memory_order_relaxed), want_h = want_h_.load(std::memory_order_relaxed);
        const auto out_w = ngx_uint(p, "OutWidth"), out_h = ngx_uint(p, "OutHeight");
        if (!want_w || !want_h) { last_reason_.store(NoExpectedSize, std::memory_order_relaxed); return {}; }
        if (!matches_periphery(out_w, out_h, want_w, want_h)) {
            other_w_.store(out_w, std::memory_order_relaxed); other_h_.store(out_h, std::memory_order_relaxed);
            last_reason_.store(OtherSize, std::memory_order_relaxed);
            return {};
        }
        if (!install_reset(cmd)) { reject(RecordingHookUnavailable); return {}; }
        {
            std::scoped_lock lock(mutex_);
            const auto found = feature_kind_.find(reinterpret_cast<uintptr_t>(feature));
            // Handles created before our hooks are unknown; the unique periphery
            // size only selects a candidate; the kind filters known non-SR features.
            if (found != feature_kind_.end() && found->second != 1u) { reject(NotSuperResolution); return {}; }
        }
        auto* depth = ngx_resource(p, "Depth");
        if (!depth) { reject(NoDepthParameter); return {}; }
        auto in_w = ngx_uint(p, "DLSS.Render.Subrect.Dimensions.Width");
        auto in_h = ngx_uint(p, "DLSS.Render.Subrect.Dimensions.Height");
        if (!in_w) in_w = ngx_uint(p, "Width");
        if (!in_h) in_h = ngx_uint(p, "Height");
        const auto base_x = ngx_uint(p, "DLSS.Input.Depth.Subrect.Base.X"), base_y = ngx_uint(p, "DLSS.Input.Depth.Subrect.Base.Y");
        const auto desc = depth->GetDesc();
        last_format_.store(static_cast<uint32_t>(desc.Format), std::memory_order_relaxed);
        // UE depth is usually D32 + stencil (R32G8X24, two planes): copy and read plane 0 only.
        const bool planar = desc.Format == DXGI_FORMAT_R32G8X24_TYPELESS || desc.Format == DXGI_FORMAT_D32_FLOAT_S8X24_UINT;
        const bool format_ok = planar || desc.Format == DXGI_FORMAT_R32_FLOAT || desc.Format == DXGI_FORMAT_D32_FLOAT ||
                               desc.Format == DXGI_FORMAT_R32_TYPELESS;
        if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.SampleDesc.Count != 1 || desc.DepthOrArraySize != 1 ||
            desc.MipLevels != 1 || !format_ok || !in_w || !in_h || desc.Width > 16384 || desc.Height > 16384 ||
            uint64_t(base_x) + in_w > desc.Width || uint64_t(base_y) + in_h > desc.Height) { reject(BadDepthFormat); return {}; }
        ++matches_;
        last_out_w_.store(out_w, std::memory_order_relaxed); last_out_h_.store(out_h, std::memory_order_relaxed);
        last_in_w_.store(in_w, std::memory_order_relaxed); last_in_h_.store(in_h, std::memory_order_relaxed);
        // Depth-stencil resources only allow whole-subresource copies.
        const bool full = planar || (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL) != 0;
        const auto copy_format = planar ? DXGI_FORMAT_R32G8X24_TYPELESS : DXGI_FORMAT_R32_TYPELESS;
        const uint32_t w = full ? uint32_t(desc.Width) : in_w, h = full ? desc.Height : in_h;
        ComPtr<ID3D12Device> dev;
        if (FAILED(depth->GetDevice(IID_PPV_ARGS(&dev)))) { reject(OtherDevice); return {}; }
        std::scoped_lock lock(mutex_);
        if (!device_ || dev.Get() != device_.Get()) { reject(OtherDevice); return {}; }
        const auto now = std::chrono::steady_clock::now();
        if (!fence_) { reject(NoFence); return {}; }
        recording_epochs_.prune([&](uintptr_t list) {
            for(const auto& slot:pool_)
                if(slot->pending && reinterpret_cast<uintptr_t>(slot->producer_list)==list) return true;
            return false;
        });
        const auto list_epoch=recording_epochs_.current(reinterpret_cast<uintptr_t>(cmd));
        if(!list_epoch) { reject(PoolFull); return {}; }
        prune_locked(want_w,want_h,false);
        // Preserve the newest depth that latest_recent_submitted() could still
        // return until a newer valid copy is submitted. Otherwise a singleton
        // pool is made unavailable between Record and Submit at ordinary cadence.
        DepthSnapshot* protected_slot=nullptr;
        uint64_t protected_sequence=0;
        for (const auto& candidate : pool_) {
            const uint64_t completed = candidate->producer_fence ? candidate->producer_fence->GetCompletedValue() : 0;
            const auto age = candidate->submitted && now >= candidate->submitted_at
                ? std::chrono::duration_cast<std::chrono::milliseconds>(now - candidate->submitted_at).count() : 250;
            const continuity::Candidate policy_candidate{candidate->sequence,candidate->out_w,candidate->out_h,
                age < 0 ? 0u : age >= 250 ? 250u : static_cast<uint32_t>(age),
                candidate->submitted,candidate->valid_evaluation,
                candidate->texture.Get()!=nullptr,candidate->foreign_queue,
                depth_copy_complete(completed,candidate->producer_fence_value)};
            if (continuity::protectable(policy_candidate,want_w,want_h) &&
                (!protected_slot || candidate->sequence>protected_sequence)) {
                protected_slot=candidate.get();
                protected_sequence=candidate->sequence;
            }
        }
        std::shared_ptr<DepthSnapshot> slot;
        for (auto& candidate : pool_) {
            if (candidate.get()==protected_slot) continue;
            const uint64_t completed = candidate->producer_fence ? candidate->producer_fence->GetCompletedValue() : 0;
            if (!depth_slot_reusable(candidate->pending,candidate->submitted,completed,
                    candidate->producer_fence_value,candidate.use_count())) continue;
            if (!slot || candidate->sequence<slot->sequence) slot=candidate;
        }
        if (!slot) {
            if (pool_.size() >= MaxSlots) { reject(PoolFull); return {}; }
            slot = std::make_shared<DepthSnapshot>(); pool_.push_back(slot);
        }
        if (!slot->producer_fence && FAILED(device_->CreateFence(0, D3D12_FENCE_FLAG_NONE,
                IID_PPV_ARGS(&slot->producer_fence)))) { reject(NoFence); return {}; }
        constexpr auto read = D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE;
        const auto have = slot->texture ? slot->texture->GetDesc() : D3D12_RESOURCE_DESC{};
        if (!slot->texture || have.Width != w || have.Height != h || have.Format != copy_format) {
            // Reallocation only after producer completion and every consumer lease retired.
            slot->texture.Reset();
            D3D12_RESOURCE_DESC td{};
            td.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
            td.Width = w; td.Height = h; td.DepthOrArraySize = 1; td.MipLevels = 1;
            td.Format = copy_format; td.SampleDesc.Count = 1;
            td.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN; td.Flags = D3D12_RESOURCE_FLAG_NONE;
            D3D12_HEAP_PROPERTIES hp{}; hp.Type = D3D12_HEAP_TYPE_DEFAULT;
            if (FAILED(dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &td, read, nullptr, IID_PPV_ARGS(&slot->texture)))) {
                reject(AllocationFailed); return {};
            }
            slot->texture->SetName(L"QuadView::PeripheryNGXDepth");
        }
        // NGX requires its inputs in NON_PIXEL_SHADER_RESOURCE at Evaluate.
        constexpr auto ngx_state = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        // Plane 0 (depth) only; subresource 0 is the depth plane for every accepted format.
        transition(cmd, depth, ngx_state, D3D12_RESOURCE_STATE_COPY_SOURCE);
        transition(cmd, slot->texture.Get(), read, D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_TEXTURE_COPY_LOCATION from{}, to{};
        from.pResource = depth; from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        to.pResource = slot->texture.Get(); to.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        const D3D12_BOX box{base_x, base_y, 0, base_x + in_w, base_y + in_h, 1};
        cmd->CopyTextureRegion(&to, 0, 0, 0, &from, full ? nullptr : &box);
        transition(cmd, slot->texture.Get(), D3D12_RESOURCE_STATE_COPY_DEST, read);
        transition(cmd, depth, D3D12_RESOURCE_STATE_COPY_SOURCE, ngx_state);
        slot->source_reference = depth;
        slot->producer_fence_value=0; slot->valid_evaluation=false;
        float jitter_x{},jitter_y{};
        // NVIDIA guide 3.7.3: offsets are actual viewport displacement in
        // render-resolution pixels, screen axes (+right,+down). To sample a
        // jittered depth input for an unjittered color ray, add that displacement.
        slot->jitter_valid=ngx_success(p->Get("Jitter.Offset.X",&jitter_x)) &&
            ngx_success(p->Get("Jitter.Offset.Y",&jitter_y)) &&
            std::isfinite(jitter_x) && std::isfinite(jitter_y) &&
            std::abs(jitter_x)<=0.5f && std::abs(jitter_y)<=0.5f;
        slot->jitter_pixels=slot->jitter_valid ? std::array<float,2>{jitter_x,jitter_y} : std::array<float,2>{};
        last_jitter_valid_.store(slot->jitter_valid, std::memory_order_relaxed);
        last_jitter_x_.store(slot->jitter_pixels[0], std::memory_order_relaxed); last_jitter_y_.store(slot->jitter_pixels[1], std::memory_order_relaxed);
        slot->jitter_uv={slot->jitter_pixels[0]/in_w,slot->jitter_pixels[1]/in_h};
        slot->producer_list = cmd;
        slot->pending_list_lease=cmd;
        slot->list_epoch = list_epoch;
        slot->sequence = ++next_sequence_;
        slot->recorded = now;
        slot->out_w = out_w; slot->out_h = out_h;
        slot->srv_format = planar ? DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS : DXGI_FORMAT_R32_FLOAT;
        slot->rect[0] = full ? base_x : 0; slot->rect[1] = full ? base_y : 0; slot->rect[2] = in_w; slot->rect[3] = in_h;
        slot->pending = true; slot->submitted = false;
        last_reason_.store(None, std::memory_order_relaxed);
        ++captures_;
        return slot;
    }

    void submitted(ID3D12CommandQueue* queue, UINT count, ID3D12CommandList* const* lists) {
        if (!count || !lists || !queue) return;
        const auto matches = [&](const DepthSnapshot& slot) {
            if (!slot.pending || !recording_epochs_.matches(
                    reinterpret_cast<uintptr_t>(slot.producer_list),slot.list_epoch)) return false;
            for (UINT i = 0; i < count; ++i) if (static_cast<void*>(lists[i]) == static_cast<void*>(slot.producer_list)) return true;
            return false;
        };
        bool any = false;
        for (const auto& slot : pool_) any = any || matches(*slot);
        if (!any) return;
        // Submitters may be wrappers or physically different DIRECT queues.
        // Completion must be tracked per recording, never via a shared global value.
        if (queue->GetDesc().Type != D3D12_COMMAND_LIST_TYPE_DIRECT) { reject(OtherDevice); return; }
        const bool foreign = queue != queue_.Get();
        if (foreign) ++foreign_queue_submits_;
        const auto now = std::chrono::steady_clock::now();
        for (auto& slot : pool_) if (matches(*slot)) {
            if (!slot->producer_fence) { reject(NoFence); continue; }
            const auto value = ++next_fence_value_;
            // An unrelated GPU queue cannot complete this slot's independent fence.
            // Signal failure quarantines the enqueued copy and retains its resources.
            if (FAILED(queue->Signal(slot->producer_fence.Get(), value))) {
                // Execute already queued this copy. A subsequent Reset cannot
                // discard it, and no completion fence exists: quarantine it.
                slot->pending=false;slot->submitted=true;slot->valid_evaluation=false;
                slot->producer_fence_value=0;slot->pending_list_lease.Reset(); reject(SignalFailed); continue;
            }
            slot->pending = false; slot->submitted = true; slot->producer_fence_value = value; slot->foreign_queue = foreign;
            slot->submitted_at = now;slot->pending_list_lease.Reset(); ++submits_;
        }
    }

    // Install before recording the first owned copy. Command-list Reset is
    // vtable slot10 in ID3D12GraphicsCommandList (IUnknown + Object + DeviceChild
    // + CommandList + Close). Observe every later recording on this implementation.
    bool install_reset(ID3D12GraphicsCommandList* cmd) {
        std::scoped_lock install_lock(reset_install_mutex_);
        auto** table=*reinterpret_cast<void***>(cmd);
        if (!table || !table[10]) return false;
        for(unsigned i=0;i<6;++i)
            if(reset_ok_[i] && resets_[i].target()==reinterpret_cast<uint8_t*>(table[10])) return true;
        const std::array<void*,6> callbacks{reinterpret_cast<void*>(&reset_list<0>),
            reinterpret_cast<void*>(&reset_list<1>),reinterpret_cast<void*>(&reset_list<2>),
            reinterpret_cast<void*>(&reset_list<3>),reinterpret_cast<void*>(&reset_list<4>),
            reinterpret_cast<void*>(&reset_list<5>)};
        for(unsigned i=0;i<6;++i) if(!reset_ok_[i]) {
            auto hook=safetyhook::create_inline(table[10],callbacks[i],safetyhook::InlineHook::StartDisabled);
            if(!hook) return false;
            resets_[i]=std::move(hook);
            if(!resets_[i].enable()) { resets_[i].reset(); return false; }
            reset_ok_[i]=true; return true;
        }
        return false;
    }
    template<unsigned N> static HRESULT __stdcall reset_list(ID3D12GraphicsCommandList* list,
            ID3D12CommandAllocator* allocator,ID3D12PipelineState* initial) {
        auto& s=self();
        auto sequencing=s.submission_sequence_.acquire();
        const auto result=s.resets_[N].unsafe_call<HRESULT>(list,allocator,initial);
        if(SUCCEEDED(result)) {
            std::scoped_lock lock(s.mutex_);
            s.recording_epochs_.reset(reinterpret_cast<uintptr_t>(list));
            for(auto& slot:s.pool_) if(slot->pending && slot->producer_list==list) {
                // Successful Reset discarded these unsubmitted commands. No GPU
                // can reference their resources; a later Execute is a new epoch.
                slot->pending=false;slot->submitted=false;slot->valid_evaluation=false;
                slot->producer_list=nullptr;slot->source_reference.Reset();slot->pending_list_lease.Reset();
            }
        }
        return result;
    }

    template <unsigned N> static uint32_t __cdecl evaluate(ID3D12GraphicsCommandList* cmd, void* feature, NgxParameters* p, void* cb) {
        auto& s=self(); Guard guard;
        std::shared_ptr<DepthSnapshot> capture;
        // NVIDIA DLSS Programming Guide section 3.4: input depth is
        // NON_PIXEL_SHADER_RESOURCE at API entry. Restore it before NGX executes.
        if(guard.outer) { try { capture=s.inspect(cmd,feature,p); } catch(...) { s.reject(Exception); } }
        const auto result=s.evals_[N].unsafe_call<uint32_t>(cmd,feature,p,cb);
        if(capture) { std::scoped_lock lock(s.mutex_);capture->valid_evaluation=ngx_success(result); }
        return result;
    }
    template <unsigned N> static uint32_t __cdecl create(ID3D12GraphicsCommandList* cmd, uint32_t kind, const NgxParameters* p, void** feature) {
        auto& s = self(); Guard g;
        const auto result = s.creates_[N].call<uint32_t>(cmd, kind, p, feature);
        if (g.outer && ngx_success(result) && feature && *feature) {
            std::scoped_lock lock(s.mutex_);
            if (s.feature_kind_.size() >= 128) s.feature_kind_.clear();
            s.feature_kind_[reinterpret_cast<uintptr_t>(*feature)] = kind;
        }
        return result;
    }
    template <unsigned N> static uint32_t __cdecl release(void* feature) {
        auto& s = self(); Guard g;
        const auto result = s.releases_[N].call<uint32_t>(feature);
        if (g.outer && ngx_success(result)) { std::scoped_lock lock(s.mutex_); s.feature_kind_.erase(reinterpret_cast<uintptr_t>(feature)); }
        return result;
    }
    static void __stdcall execute_commands(ID3D12CommandQueue* queue, UINT count, ID3D12CommandList* const* lists) {
        auto& s = self();
        auto sequencing=s.submission_sequence_.acquire();
        // The data mutex never encloses the game's submission. Reset is
        // sequenced separately to preserve an already-enqueued copy. A copy is
        // marked submitted only after the original call queued its list, so the
        // compositor's later submission on this queue is ordered after it.
        s.execute_.unsafe_call<void>(queue, count, lists);
        std::scoped_lock lock(s.mutex_);
        s.submitted(queue, count, lists);
    }
    static void install_group(Hooks& hooks, std::array<bool, 6>& installed, std::array<const char*, 2> exports,
                              std::array<void*, 6> callbacks) {
        static const wchar_t* dlls[]{L"nvngx_dlss.dll", L"_nvngx.dll", L"nvngx.dll"};
        for (unsigned dll = 0; dll != 3; ++dll) {
            HMODULE module = GetModuleHandleW(dlls[dll]);
            if (!module) continue;
            for (unsigned e = 0; e != 2; ++e) {
                const unsigned slot = dll * 2 + e;
                if (installed[slot]) continue;
                void* address = reinterpret_cast<void*>(GetProcAddress(module, exports[e]));
                if (!address) continue;
                bool duplicate = false;
                for (unsigned k = 0; k != 6; ++k)
                    if (installed[k] && hooks[k].target() == reinterpret_cast<uint8_t*>(address)) duplicate = true;
                if (duplicate) continue;
                HMODULE pinned{};
                if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_PIN, dlls[dll], &pinned)) continue;
                auto hook = safetyhook::create_inline(address, callbacks[slot], safetyhook::InlineHook::StartDisabled);
                if (!hook) continue;
                hooks[slot] = std::move(hook);
                if (hooks[slot].enable()) installed[slot] = true; else hooks[slot].reset();
            }
        }
    }
};
} // namespace uevr::quadview::ngx

```

## FILE src/mods/vr/QuadViewNgxSelect.hpp (38 lines)
```cpp
#pragma once
// Tri-view B11: portable periphery-depth selection rules (unit-tested on Linux).
//
// Identity: the periphery is the only DLSS evaluation whose output size equals
// the shared context view. make_layout() guarantees the two foveas never have
// a size inside the conflict window (see unique_context_factor), so an output
// size match is unambiguous; no timing or thread ownership is involved.
#include <cstdint>

namespace uevr::quadview::ngx {
namespace detail {
// a within pct percent of b, or within px pixels (UE may align view rects).
inline bool close(uint64_t a, uint64_t b, uint64_t pct, uint64_t px) {
    const uint64_t d = a > b ? a - b : b - a;
    return d <= px || d * 100 <= b * pct;
}
} // namespace detail

// A DLSS output (out) is the periphery when both axes are within 3 % / 4 px.
inline bool matches_periphery(uint32_t out_w, uint32_t out_h, uint32_t want_w, uint32_t want_h) {
    if (!out_w || !out_h || !want_w || !want_h) return false;
    return detail::close(out_w, want_w, 3, 4) && detail::close(out_h, want_h, 3, 4);
}

// A fovea size this close to the context could be confused with it.
inline bool focus_conflicts_context(uint32_t focus_w, uint32_t focus_h, uint32_t ctx_w, uint32_t ctx_h) {
    if (!focus_w || !focus_h || !ctx_w || !ctx_h) return false;
    return detail::close(ctx_w, focus_w, 6, 8) && detail::close(ctx_h, focus_h, 6, 8);
}

// Uniform scale for the context so that it can never match a fovea: 1 when no
// conflict, else the context width becomes 93 % of the fovea width (aspect kept,
// the geometry depends on the projection, not on the pixel count).
inline float unique_context_factor(uint32_t focus_w, uint32_t focus_h, uint32_t ctx_w, uint32_t ctx_h) {
    if (!focus_conflicts_context(focus_w, focus_h, ctx_w, ctx_h)) return 1.f;
    return 0.93f * float(focus_w) / float(ctx_w);
}
} // namespace uevr::quadview::ngx

```

## FILE src/mods/vr/QuadViewPSVR2Gaze.hpp (137 lines)
```cpp
#pragma once
#include <algorithm>

// ID7 adapter for the exact v186.1 PSVR2 Toolkit ABI and validation rules.
// It deliberately returns the recovered calibrated HEAD-space ray so the
// caller can project it once per true stereo eye. ID6's reader stays intact.
#include "DuoViewPSVR2Gaze.hpp"
#include <atomic>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>

#ifdef _MSC_VER
#pragma comment(lib, "Advapi32.lib")
#endif

namespace uevr::quadview::psvr2 {

using Ray = duoview::Ray;
using Status = duoview::psvr2::Status;
using ReadFn = duoview::psvr2::ReadFn;
using InitFn = duoview::psvr2::InitFn;

struct Counters {
    uint64_t fresh{}, reused{}, invalid{}, expired{}, unavailable{};
    uint32_t age_ms{};
    bool available{}, active{};
};

class Reader {
public:
    void set_recovery_controls(uint32_t hold_ms, uint32_t reacquire_samples) {
        std::scoped_lock lock{mutex_};
        recovery_.controls(hold_ms, reacquire_samples);
    }

    bool active() const { return active_.load(std::memory_order_acquire); }
    bool available() const { return available_.load(std::memory_order_acquire); }

    Counters counters() const {
        return {fresh_.load(std::memory_order_relaxed), reused_.load(std::memory_order_relaxed),
            invalid_.load(std::memory_order_relaxed), expired_.load(std::memory_order_relaxed),
            unavailable_.load(std::memory_order_relaxed), age_ms_.load(std::memory_order_relaxed),
            available_.load(std::memory_order_relaxed), active_.load(std::memory_order_relaxed)};
    }

    // Call once per ID7 draw transaction. Eye projection must not call this.
    std::optional<Ray> read_ray() {
        std::scoped_lock lock{mutex_};
        const uint64_t now = GetTickCount64();
        // B12 (DuoView v207 parity): back off 1 s, 2 s, 4 s ... 30 s while the Toolkit is
        // missing, so DLL/registry/file probing does not hitch the game thread every second.
        if (!read_ && now >= next_attempt_) {
            initialize();
            retry_ms_ = (std::min)(retry_ms_ * 2, uint64_t{30000});
            next_attempt_ = now + retry_ms_;
        }
        if (!read_) {
            unavailable_.fetch_add(1, std::memory_order_relaxed);
            active_.store(false, std::memory_order_release);
            return {};
        }
        Status candidate{};
        const bool fresh = read_(&candidate, 0);
        const auto sample = fresh ? duoview::psvr2::calibrated_ray(candidate) : std::optional<Ray>{};
        const bool invalid = fresh && !sample.has_value();
        if (invalid) invalid_.fetch_add(1, std::memory_order_relaxed);
        const auto held = recovery_.update(now, sample, invalid);
        if (sample && !invalid) fresh_.fetch_add(1, std::memory_order_relaxed);
        if (!held) {
            age_ms_.store(UINT32_MAX, std::memory_order_relaxed);
            expired_.fetch_add(1, std::memory_order_relaxed);
            active_.store(false, std::memory_order_release);
            return {};
        }
        age_ms_.store(recovery_.age_ms(now), std::memory_order_relaxed);
        if (!fresh || invalid) reused_.fetch_add(1, std::memory_order_relaxed);
        active_.store(true, std::memory_order_release);
        return held;
    }

private:
    void initialize() {
        if (!module_) {
            module_ = GetModuleHandleW(L"psvr2_toolkit_capi.dll");
            wchar_t path[32768]{};
            const DWORD n = GetEnvironmentVariableW(L"PSVR2TK_CAPI_PATH", path, 32768);
            if (!module_ && n && n < 32768)
                module_ = LoadLibraryExW(path, nullptr,
                    LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
            if (!module_) try {
                std::ifstream file(std::filesystem::temp_directory_path() / "psvr2tk_capi_path.txt");
                std::string dir;
                if (file && std::getline(file, dir) && !dir.empty()) {
                    const auto candidate = std::filesystem::path(dir) / "psvr2_toolkit_capi.dll";
                    module_ = LoadLibraryExW(candidate.c_str(), nullptr,
                        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
                }
            } catch (...) {}
            if (!module_) {
                wchar_t steam[32768]{};
                DWORD bytes = sizeof(steam);
                if (RegGetValueW(HKEY_CURRENT_USER, L"Software\\Valve\\Steam", L"SteamPath",
                    RRF_RT_REG_SZ, nullptr, steam, &bytes) == ERROR_SUCCESS) {
                    const std::wstring candidate = std::wstring(steam) +
                        L"\\steamapps\\common\\PlayStation VR2 App\\SteamVR_Plug-In\\bin\\win64\\psvr2_toolkit_capi.dll";
                    module_ = LoadLibraryExW(candidate.c_str(), nullptr,
                        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
                }
            }
            if (!module_) module_ = LoadLibraryW(L"psvr2_toolkit_capi.dll");
        }
        if (!module_) return;
        auto init = reinterpret_cast<InitFn>(GetProcAddress(module_, "psvr2_toolkit_init"));
        auto read = reinterpret_cast<ReadFn>(GetProcAddress(module_, "psvr2_toolkit_gaze_status"));
        if (init && read && init() == 0) {
            read_ = read;
            available_.store(true,std::memory_order_release);
        }
    }

    mutable std::mutex mutex_{};
    std::atomic<bool> active_{false};
    std::atomic<bool> available_{false};
    std::atomic<uint64_t> fresh_{0}, reused_{0}, invalid_{0}, expired_{0}, unavailable_{0};
    std::atomic<uint32_t> age_ms_{UINT32_MAX};
    HMODULE module_{};
    ReadFn read_{};
    uint64_t next_attempt_{};
    uint64_t retry_ms_{500};
    duoview::RayRecovery recovery_{};
};

} // namespace uevr::quadview::psvr2

```

## FILE src/mods/vr/QuadViewProducer.hpp (339 lines)
```cpp
#pragma once

#include "QuadViewGeometry.hpp"
#include "QuadViewSettings.hpp"
#include <array>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <unordered_map>

namespace uevr::quadview {

struct Key {
    uint64_t generation{}, draw_serial{};
    friend bool operator==(const Key&, const Key&) = default;
};

struct KeyHash {
    size_t operator()(Key key) const noexcept {
        const auto mixed = key.generation ^ (key.draw_serial + 0x9e3779b97f4a7c15ull +
            (key.generation << 6) + (key.generation >> 2));
        return static_cast<size_t>(mixed);
    }
};

struct ViewRecord {
    uintptr_t view{}, state{};
    Rect rect{};
    // Exact matrix fingerprint captured from FSceneViewInitOptions.
    uint64_t projection_hash{};
    bool valid{};
};

struct CameraPose {
    std::array<double, 3> rotation{};
    std::array<double, 3> position{};
    bool valid{};
};

struct GazeEvidence {
    uint64_t sample_tick{};
    uint64_t fresh{},reused{},invalid{},expired{},unavailable{};
    uint32_t age_ms{};
    bool sampled{},ray_valid{},reader_available{},reader_active{};
};

struct Snapshot {
    Key key{};
    uint64_t engine_frame{};
    uintptr_t family{}, scene{}, target{};
    Layout layout{};
    Settings settings{};
    uint64_t settings_revision{};
    GazeEvidence gaze{};
    std::array<ViewRecord, 4> views{};
    std::array<uint64_t, 4> expected_projection_hashes{};
    std::array<std::array<double, 16>, 4> projections{};
    std::array<CameraPose, 2> context_cameras{};
    uint8_t constructor_mask{};
    uint8_t expected_projection_mask{};
    uint8_t projection_matrix_mask{};
    uint8_t camera_mask{};
    bool family_valid{};
    uint64_t hook_rect_calls{}, hook_projection_calls{};

    // Renderer dispatch precedes the engine GT family callback. Construction
    // can be complete while main_family has not yet authenticated that family.
    bool construction_complete() const {
        if (constructor_mask != 0x0f || expected_projection_mask != 0x0f ||
            projection_matrix_mask != 0x0f || camera_mask != 0x03) return false;
        for (uint32_t i = 0; i != 4; ++i) {
            if (!views[i].valid || views[i].state == 0 || views[i].projection_hash == 0 ||
                views[i].projection_hash != expected_projection_hashes[i]) return false;
            bool nonzero = false;
            for (double value : projections[i]) {
                if (!std::isfinite(value)) return false;
                nonzero = nonzero || std::abs(value) > 1.0e-12;
            }
            if (!nonzero) return false;
            for (uint32_t j = i + 1; j != 4; ++j) {
                if (views[i].state == views[j].state) return false;
            }
        }
        return true;
    }

    bool histories_complete() const {
        return family_valid && construction_complete();
    }

    bool camera_complete() const {
        if (camera_mask != 0x03) return false;
        for (const auto& camera : context_cameras) {
            if (!camera.valid) return false;
            for (double v : camera.rotation) if (!std::isfinite(v)) return false;
            for (double v : camera.position) if (!std::isfinite(v)) return false;
        }
        return true;
    }
};

// A per-draw producer ledger. Hook calls and four distinct same-family states
// are captured independently of compositor command-record diagnostics.
class Producer {
public:
    bool begin(Key key, uint64_t engine_frame, uintptr_t target, uintptr_t scene, Layout layout,
               Settings settings = {}, uint64_t settings_revision = 1, GazeEvidence gaze = {}) {
        if (key.generation == 0 || key.draw_serial == 0 ||
            !layout.eye_width || !layout.eye_height || layout.atlas_width != layout.eye_width * 2) return false;
        std::scoped_lock lock{mutex_};
        // View constructors run synchronously with viewport drawing. A failed,
        // incomplete prior draw is safe to discard when the next draw starts.
        // Completed records remain until their render-slot owner retires them.
        for (auto it = pending_.begin(); it != pending_.end();) {
            if (it->first.generation != key.generation || it->first.draw_serial != key.draw_serial) {
                it = pending_.erase(it);
            } else {
                ++it;
            }
        }
        // A Delivery source owns its immutable Snapshot independently. Keep
        // the producer lookup bounded even if a runtime never accepts a copy.
        // This does not invalidate any queued/executed packet's shared owner.
        for (auto it = completed_.begin(); it != completed_.end();) {
            if (!(it->first == key)) {
                compositor_records_.erase(it->first);
                it = completed_.erase(it);
            } else {
                ++it;
            }
        }
        if (pending_.contains(key) || completed_.contains(key) ||
            pending_.size() + completed_.size() >= max_live_packets) return false;
        Snapshot snapshot{};
        snapshot.key = key;
        snapshot.engine_frame = engine_frame;
        snapshot.target = target;
        snapshot.scene = scene;
        snapshot.layout = layout;
        snapshot.settings = settings;
        snapshot.settings_revision = settings_revision;
        snapshot.gaze = gaze;
        pending_.emplace(key, std::move(snapshot));
        return true;
    }

    bool rectangle_call(Key key, int32_t index) {
        std::scoped_lock lock{mutex_};
        auto* snapshot = find_pending(key);
        if (snapshot == nullptr) return false;
        if (!valid_view_index(index)) return false;
        ++snapshot->hook_rect_calls;
        return true;
    }

    bool projection_call(Key key, int32_t index, uint64_t expected_projection_hash,
                         const std::array<double, 16>& projection) {
        std::scoped_lock lock{mutex_};
        auto* snapshot = find_pending(key);
        if (snapshot == nullptr || !valid_view_index(index) || expected_projection_hash == 0) return false;
        bool nonzero = false;
        for (double value : projection) {
            if (!std::isfinite(value)) return false;
            nonzero = nonzero || std::abs(value) > 1.0e-12;
        }
        if (!nonzero) return false;
        ++snapshot->hook_projection_calls;
        snapshot->expected_projection_hashes[static_cast<size_t>(index)] = expected_projection_hash;
        snapshot->expected_projection_mask |= static_cast<uint8_t>(1u << index);
        snapshot->projections[static_cast<size_t>(index)] = projection;
        snapshot->projection_matrix_mask |= static_cast<uint8_t>(1u << index);
        return true;
    }

    std::optional<std::array<double, 16>> projection_matrix(Key key, uint32_t index) const {
        std::scoped_lock lock{mutex_};
        const auto found = pending_.find(key);
        if (found == pending_.end() || index >= 4 ||
            (found->second.expected_projection_mask & static_cast<uint8_t>(1u << index)) == 0) return {};
        return found->second.projections[index];
    }

    // Only the two context callbacks own view-offset side effects. Focus
    // indices copy these completed, post-mod cameras and must not call the
    // full offset path a second time.
    bool camera(Key key, uint32_t view_index, CameraPose pose) {
        std::scoped_lock lock{mutex_};
        auto* snapshot = find_pending(key);
        if (snapshot == nullptr || view_index > 1 || !pose.valid) return false;
        for (double v : pose.rotation) if (!std::isfinite(v)) return false;
        for (double v : pose.position) if (!std::isfinite(v)) return false;
        snapshot->context_cameras[view_index] = pose;
        snapshot->camera_mask |= static_cast<uint8_t>(1u << view_index);
        return true;
    }

    std::optional<CameraPose> context_camera(Key key, uint32_t view_index) const {
        std::scoped_lock lock{mutex_};
        const auto found = pending_.find(key);
        if (found == pending_.end() || view_index > 1 ||
            (found->second.camera_mask & static_cast<uint8_t>(1u << view_index)) == 0) return {};
        return found->second.context_cameras[view_index];
    }

    bool constructed(Key key, uintptr_t family, uintptr_t scene, uintptr_t target,
                     uintptr_t view, uintptr_t state, Rect rect, uint64_t projection_hash) {
        std::scoped_lock lock{mutex_};
        auto* snapshot = find_pending(key);
        if (snapshot == nullptr || !family || !scene || !target || !view || !state || !projection_hash ||
            (snapshot->scene != 0 && scene != snapshot->scene) ||
            (snapshot->target != 0 && target != snapshot->target)) return false;
        const auto index = view_index_for_rect(snapshot->layout, rect);
        if (!index) return false;
        if ((snapshot->expected_projection_mask & static_cast<uint8_t>(1u << *index)) == 0 ||
            snapshot->expected_projection_hashes[*index] != projection_hash) return false;
        if (snapshot->family != 0 && snapshot->family != family) return false;
        if ((snapshot->constructor_mask & static_cast<uint8_t>(1u << *index)) != 0) return false;
        for (uint32_t i = 0; i != 4; ++i) {
            if (i == *index) continue;
            if (snapshot->views[i].state == state || snapshot->views[i].view == view) return false;
        }
        snapshot->family = family;
        snapshot->scene = scene;
        snapshot->target = target;
        snapshot->views[*index] = {view, state, rect, projection_hash, true};
        snapshot->constructor_mask |= static_cast<uint8_t>(1u << *index);
        return true;
    }

    bool main_family(Key key, uint64_t engine_frame, uintptr_t family, uintptr_t scene, uintptr_t target,
                     const std::array<uintptr_t, 4>& views) {
        std::scoped_lock lock{mutex_};
        auto* snapshot = find_pending(key);
        if (snapshot == nullptr || family == 0 || family != snapshot->family || scene != snapshot->scene || target != snapshot->target ||
            (snapshot->engine_frame != 0 && engine_frame != 0 && snapshot->engine_frame != engine_frame)) return false;
        std::array<bool, 4> matched{};
        for (const auto view : views) {
            if (!view) return false;
            bool found = false;
            for (uint32_t i = 0; i != 4; ++i) {
                if (snapshot->views[i].valid && snapshot->views[i].view == view && !matched[i]) {
                    matched[i] = true;
                    found = true;
                    break;
                }
            }
            if (!found) return false;
        }
        for (bool found : matched) if (!found) return false;
        snapshot->engine_frame = engine_frame;
        snapshot->family_valid = true;
        if (!snapshot->camera_complete() || !snapshot->histories_complete()) return false;
        completed_.emplace(key, std::make_shared<const Snapshot>(*snapshot));
        pending_.erase(key);
        return true;
    }

    // Records only the app-side compositor command submission. It does not
    // claim that the four scene views rasterized or that the GPU completed.
    bool note_compositor_record(Key key, uintptr_t source, uintptr_t command_list) {
        std::scoped_lock lock{mutex_};
        const auto frozen = completed_.find(key);
        if (frozen == completed_.end() || !source || !command_list) return false;
        auto& evidence = compositor_records_[key];
        ++evidence.submits;
        evidence.last_source_resource = source;
        evidence.last_command_list = command_list;
        return true;
    }

    std::optional<Snapshot> snapshot(Key key) const {
        std::scoped_lock lock{mutex_};
        if (const auto frozen = completed_.find(key); frozen != completed_.end()) return *frozen->second;
        if (const auto pending = pending_.find(key); pending != pending_.end()) return pending->second;
        return {};
    }

    std::shared_ptr<const Snapshot> frozen(Key key) const {
        std::scoped_lock lock{mutex_};
        const auto found = completed_.find(key);
        return found == completed_.end() ? nullptr : found->second;
    }

    bool retire(Key key) {
        std::scoped_lock lock{mutex_};
        compositor_records_.erase(key);
        const auto pending_removed = pending_.erase(key);
        const auto completed_removed = completed_.erase(key);
        return pending_removed != 0 || completed_removed != 0;
    }

    void retire_generation(uint64_t generation) {
        std::scoped_lock lock{mutex_};
        for (auto it = pending_.begin(); it != pending_.end();) {
            if (it->first.generation == generation) it = pending_.erase(it);
            else ++it;
        }
        for (auto it = completed_.begin(); it != completed_.end();) {
            if (it->first.generation == generation) {
                compositor_records_.erase(it->first);
                it = completed_.erase(it);
            } else {
                ++it;
            }
        }
    }

    void retire_all() {
        std::scoped_lock lock{mutex_};
        pending_.clear();
        completed_.clear();
        compositor_records_.clear();
    }

    struct CompositorEvidence { uint64_t submits{}; uintptr_t last_source_resource{}, last_command_list{}; };
    std::optional<CompositorEvidence> compositor_evidence(Key key) const {
        std::scoped_lock lock{mutex_};
        if (const auto found = compositor_records_.find(key); found != compositor_records_.end()) return found->second;
        return {};
    }

private:
    static constexpr size_t max_live_packets = 8;
    Snapshot* find_pending(Key key) {
        const auto found = pending_.find(key);
        return found == pending_.end() ? nullptr : &found->second;
    }
    static std::optional<uint32_t> view_index_for_rect(const Layout& layout, Rect rect) {
        for (uint32_t i = 0; i != 4; ++i) if (layout.views[i] == rect) return i;
        return {};
    }
    mutable std::mutex mutex_;
    std::unordered_map<Key, Snapshot, KeyHash> pending_;
    std::unordered_map<Key, std::shared_ptr<const Snapshot>, KeyHash> completed_;
    std::unordered_map<Key, CompositorEvidence, KeyHash> compositor_records_;
};

} // namespace uevr::quadview

```

## FILE src/mods/vr/QuadViewResourceReuse.hpp (42 lines)
```cpp
#pragma once
#include <array>
#include <cstdint>
#include <cstddef>
#include <memory>

namespace uevr::quadview {
using NativeResourceExtents = std::array<std::array<uint32_t,2>,4>;
struct NativeResourceReusePlan {
    uint8_t reuse_mask{};
    uint64_t new_color_bytes{}; // BGRA8 payload estimate, excluding driver/engine auxiliaries.
    bool reuses(size_t role) const { return role<4 && (reuse_mask & uint8_t(1u<<role)); }
};
inline NativeResourceReusePlan plan_native_resource_reuse(
    bool same_world, bool complete_and_live,
    const NativeResourceExtents& old_extents, const NativeResourceExtents& requested) {
    NativeResourceReusePlan result{};
    for (size_t role : std::array<size_t,3>{0,2,3}) {
        const auto& e=requested[role];
        if (!e[0] || !e[1]) continue;
        if (same_world && complete_and_live && old_extents[role]==e)
            result.reuse_mask |= uint8_t(1u<<role);
        else result.new_color_bytes += uint64_t(e[0])*e[1]*4;
    }
    return result;
}
inline bool valid_resource_publication(uint64_t publication, uint64_t snapshot_publication,
                                       uint64_t allocation) {
    return publication && publication==snapshot_publication && allocation && allocation<=publication;
}
// Copy the publication record while retaining the exact physical owner lease.
// Never mutate an old snapshot: packets can still hold it while a replacement builds.
template<typename Snapshot>
std::shared_ptr<Snapshot> republish_resource_snapshot(const std::shared_ptr<const Snapshot>& source,
                                                     uint64_t publication) {
    if (!source || !valid_resource_publication(publication,publication,source->resource_allocation_generation) ||
        publication<=source->generation) return {};
    auto snapshot=std::make_shared<Snapshot>(*source);
    snapshot->generation=publication;
    return snapshot;
}
} // namespace uevr::quadview

```

## FILE src/mods/vr/QuadViewRetirement.hpp (19 lines)
```cpp
#pragma once

#include <cstdint>

namespace uevr::quadview {

// Presentation resource reconfiguration may proceed while new engine view
// owners continue to arrive. A rendering-mode transition must drain them.
enum class RetirementScope : std::uint8_t {
    presentation,
    mode_transition,
};

constexpr bool requires_engine_retirement(RetirementScope scope) noexcept {
    // Treat unknown enum values conservatively as mode-transition scope.
    return scope != RetirementScope::presentation;
}

} // namespace uevr::quadview

```

## FILE src/mods/vr/QuadViewSettings.hpp (238 lines)
```cpp
#pragma once

#include "QuadViewGeometry.hpp"
#include "QuadViewFocusLift.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace uevr::quadview {

// Stereo-specific subset of the published v186.1 DuoView controls. Settings
// that only affect ID6's two-source capture or XR output path are not exposed
// here; every retained value is frozen with the ID7 source transaction.
struct Settings {
    float crop_width{.50f}, crop_height{.50f};
    float context_scale{.20f};
    float foveal_density{1.f};
    float feather_fraction{.08f};
    float sharpen_strength{1.f};
    bool focus_lift_enabled{false};
    float focus_brightness{1.f};
    float focus_lift_strength{1.f};
    float focus_corner_gain{focus_lift::default_corner_gain};
    float focus_lift_onset{focus_lift::default_onset};
    float focus_lift_power{focus_lift::default_power};
    uint32_t seam_mode{0}; // Off=0, Manual=1, Adaptive=2
    float seam_strength{.85f};
    float seam_max_gain{.20f};
    float seam_brightness_ev{};
    float seam_color_strength{.5f};
    float seam_local_strength{.5f};
    float seam_radius_px{120.f};
    float seam_transition_px{};
    float edge_reach_px{240.f};
    float edge_fast_px{32.f};
    float edge_rate{.15f}; // sample-domain RGB units per second, no amplitude ceiling
    float edge_hysteresis{.004f};
    bool legacy_inward_feather{true}; // B38: restore B27 raw-context inward feather
    float legacy_inward_anchor_px{12.f}; // color-continuity strip next to crop
    float ambient_radius_px{48.f}; // B39: pooled along-edge width (output px)
    float ambient_inside_px{32.f}; // inward sample reach (output px)
    uint32_t ambient_time_ms{350u}; // temporal RGB average time constant
    bool seam_debug{};
    bool gpu_timing{};
    bool debug_border{};
    bool eye_tracked{true};
    uint32_t diagnostic_view{}; // 0 composite, 1 context, 2 focus, 3 layout colors
    bool stabilize_crop{true};
    float guard_fraction{.05f};
    uint32_t gaze_quant_pixels{2};
    int32_t gaze_hold_ms{350};
    int32_t gaze_reacquire_samples{2};
    float gaze_offset_u{}, gaze_offset_v{};
    float gaze_micro_gain{};
    float gaze_breakout_radius{.035f};
    float gaze_still_radius{.008f};
    uint32_t gaze_relock_samples{3};
    float sharpen_max_change{.10f}; // B5 legacy key retained for left eye
    bool sharpen_link_right{true}; // legacy config: left settings on both eyes
    float sharpen_right_strength{1.f};
    float sharpen_right_max_change{.10f};
};

enum Reject : uint32_t {
    reject_width=1u<<0, reject_height=1u<<1, reject_context=1u<<2,
    reject_density=1u<<3, reject_feather=1u<<4, reject_sharpen=1u<<5,
    reject_diagnostic=1u<<6, reject_guard=1u<<7, reject_quant=1u<<8,
    reject_hold=1u<<9, reject_reacquire=1u<<10, reject_offset_u=1u<<11,
    reject_offset_v=1u<<12, reject_micro=1u<<13, reject_breakout=1u<<14,
    reject_still=1u<<15, reject_relock=1u<<16, reject_sharpen_max=1u<<17, reject_sharpen_right=1u<<18, reject_sharpen_right_max=1u<<19
};

inline constexpr uint32_t reject_focus_lift=1u<<20;
inline constexpr uint32_t reject_seam=1u<<21;

struct Reconciled {
    Settings settings{};
    uint32_t rejected{};
    bool dimension_fallback{};
};

inline Reconciled reconcile_settings(const Settings& requested, const Settings& current,
                                    uint32_t output_width, uint32_t output_height) {
    Reconciled result{current, 0, false};
    auto& out = result.settings;
    const auto valid = [](float value, float lo, float hi) {
        return std::isfinite(value) && value >= lo && value <= hi;
    };
    const auto valid_quality = [=](const Settings& value) {
        return make_layout(output_width, output_height, value.crop_width, value.crop_height,
            value.context_scale, value.foveal_density).has_value();
    };

    const bool previous_quality_invalid=!valid_quality(out);
    if (previous_quality_invalid) {
        out.crop_width=.50f;
        out.crop_height=.50f;
        out.context_scale=.20f;
        out.foveal_density=1.f;
        result.dimension_fallback=true;
        result.rejected|=reject_width|reject_height|reject_context|reject_density;
        if (!valid_quality(out)) {
            out.crop_width=.05f;
            out.crop_height=.05f;
            out.context_scale=.05f;
            out.foveal_density=.25f;
        }
    }

    if (valid_quality(requested)) {
        out.crop_width=requested.crop_width;
        out.crop_height=requested.crop_height;
        out.context_scale=requested.context_scale;
        out.foveal_density=requested.foveal_density;
        result.dimension_fallback=false;
        result.rejected&=~(reject_width|reject_height|reject_context|reject_density);
    } else {
        const auto quality_field = [&](float value, float lo, float hi,
                                       uint32_t mask, float Settings::* field) {
            Settings attempt=out;
            attempt.*field=value;
            if (valid(value,lo,hi) && valid_quality(attempt)) {
                out.*field=value;
                result.rejected&=~mask;
            } else result.rejected|=mask;
        };
        quality_field(requested.crop_width,.05f,1.f,reject_width,&Settings::crop_width);
        quality_field(requested.crop_height,.05f,1.f,reject_height,&Settings::crop_height);
        quality_field(requested.foveal_density,.25f,4.f,reject_density,&Settings::foveal_density);
        quality_field(requested.context_scale,.05f,.50f,reject_context,&Settings::context_scale);
        result.dimension_fallback=previous_quality_invalid;
    }

    out.sharpen_link_right=requested.sharpen_link_right;
    out.debug_border=requested.debug_border;
    out.gpu_timing=requested.gpu_timing;
    out.eye_tracked=requested.eye_tracked;
    out.stabilize_crop=requested.stabilize_crop;
    out.focus_lift_enabled=requested.focus_lift_enabled;
    out.seam_debug=requested.seam_debug;
    out.legacy_inward_feather=requested.legacy_inward_feather;
    const auto scalar = [&](float value,float lo,float hi,uint32_t mask,float Settings::* field) {
        if (valid(value,lo,hi)) out.*field=value;
        else result.rejected|=mask;
    };
    const auto integer = [&](int32_t value,int32_t lo,int32_t hi,uint32_t mask,int32_t Settings::* field) {
        if (value>=lo && value<=hi) out.*field=value;
        else result.rejected|=mask;
    };
    const auto unsigned_integer = [&](uint32_t value,uint32_t lo,uint32_t hi,uint32_t mask,uint32_t Settings::* field) {
        if (value>=lo && value<=hi) out.*field=value;
        else result.rejected|=mask;
    };
    scalar(requested.feather_fraction,0.f,.45f,reject_feather,&Settings::feather_fraction);
    scalar(requested.sharpen_strength,0.f,10.f,reject_sharpen,&Settings::sharpen_strength);
    scalar(requested.sharpen_right_strength,0.f,10.f,reject_sharpen_right,&Settings::sharpen_right_strength);
    scalar(requested.sharpen_max_change,.05f,.40f,reject_sharpen_max,&Settings::sharpen_max_change);
    scalar(requested.sharpen_right_max_change,.05f,.40f,reject_sharpen_right_max,&Settings::sharpen_right_max_change);
    scalar(requested.focus_brightness,.8f,1.3f,reject_focus_lift,&Settings::focus_brightness);
    scalar(requested.focus_lift_strength,0.f,2.f,reject_focus_lift,&Settings::focus_lift_strength);
    scalar(requested.focus_corner_gain,1.f,1.5f,reject_focus_lift,&Settings::focus_corner_gain);
    scalar(requested.focus_lift_onset,0.f,.9f,reject_focus_lift,&Settings::focus_lift_onset);
    scalar(requested.focus_lift_power,.5f,3.f,reject_focus_lift,&Settings::focus_lift_power);
    scalar(requested.edge_reach_px,16.f,1024.f,reject_seam,&Settings::edge_reach_px);
    scalar(requested.edge_fast_px,1.f,256.f,reject_seam,&Settings::edge_fast_px);
    scalar(requested.edge_rate,.001f,4.f,reject_seam,&Settings::edge_rate);
    scalar(requested.edge_hysteresis,0.f,.05f,reject_seam,&Settings::edge_hysteresis);
    scalar(requested.legacy_inward_anchor_px,2.f,64.f,reject_seam,&Settings::legacy_inward_anchor_px);
    scalar(requested.ambient_radius_px,8.f,128.f,reject_seam,&Settings::ambient_radius_px);
    scalar(requested.ambient_inside_px,8.f,96.f,reject_seam,&Settings::ambient_inside_px);
    unsigned_integer(requested.ambient_time_ms,50u,1500u,reject_seam,&Settings::ambient_time_ms);
    scalar(requested.seam_strength,0.f,1.f,reject_seam,&Settings::seam_strength);
    scalar(requested.seam_max_gain,.01f,.5f,reject_seam,&Settings::seam_max_gain);
    scalar(requested.seam_brightness_ev,-.5f,.5f,reject_seam,&Settings::seam_brightness_ev);
    scalar(requested.seam_color_strength,0.f,1.f,reject_seam,&Settings::seam_color_strength);
    scalar(requested.seam_local_strength,0.f,1.f,reject_seam,&Settings::seam_local_strength);
    scalar(requested.seam_radius_px,16.f,512.f,reject_seam,&Settings::seam_radius_px);
    scalar(requested.seam_transition_px,0.f,64.f,reject_seam,&Settings::seam_transition_px);
    unsigned_integer(requested.seam_mode,0u,6u,reject_seam,&Settings::seam_mode);
    scalar(requested.guard_fraction,0.f,.05f,reject_guard,&Settings::guard_fraction);
    scalar(requested.gaze_offset_u,-.25f,.25f,reject_offset_u,&Settings::gaze_offset_u);
    scalar(requested.gaze_offset_v,-.25f,.25f,reject_offset_v,&Settings::gaze_offset_v);
    scalar(requested.gaze_micro_gain,0.f,1.f,reject_micro,&Settings::gaze_micro_gain);
    unsigned_integer(requested.diagnostic_view,0u,3u,reject_diagnostic,&Settings::diagnostic_view);
    unsigned_integer(requested.gaze_quant_pixels,0u,16u,reject_quant,&Settings::gaze_quant_pixels);
    unsigned_integer(requested.gaze_relock_samples,1u,10u,reject_relock,&Settings::gaze_relock_samples);
    integer(requested.gaze_hold_ms,50,2000,reject_hold,&Settings::gaze_hold_ms);
    integer(requested.gaze_reacquire_samples,1,4,reject_reacquire,&Settings::gaze_reacquire_samples);

    const bool valid_breakout=valid(requested.gaze_breakout_radius,.005f,.25f);
    const bool valid_still=valid(requested.gaze_still_radius,0.f,.05f);
    if (valid_breakout && valid_still && requested.gaze_still_radius<requested.gaze_breakout_radius) {
        out.gaze_breakout_radius=requested.gaze_breakout_radius;
        out.gaze_still_radius=requested.gaze_still_radius;
    } else {
        if (valid_breakout && out.gaze_still_radius<requested.gaze_breakout_radius)
            out.gaze_breakout_radius=requested.gaze_breakout_radius;
        else result.rejected|=reject_breakout;
        if (valid_still && requested.gaze_still_radius<out.gaze_breakout_radius)
            out.gaze_still_radius=requested.gaze_still_radius;
        else result.rejected|=reject_still;
    }
    return result;
}

inline bool same_settings(const Settings& a, const Settings& b) {
    return a.crop_width==b.crop_width && a.crop_height==b.crop_height &&
        a.context_scale==b.context_scale && a.foveal_density==b.foveal_density &&
        a.feather_fraction==b.feather_fraction && a.sharpen_strength==b.sharpen_strength && a.sharpen_max_change==b.sharpen_max_change &&
        a.sharpen_link_right==b.sharpen_link_right &&
        a.sharpen_right_strength==b.sharpen_right_strength &&
        a.sharpen_right_max_change==b.sharpen_right_max_change &&
        a.focus_lift_enabled==b.focus_lift_enabled && a.focus_brightness==b.focus_brightness &&
        a.focus_lift_strength==b.focus_lift_strength && a.focus_corner_gain==b.focus_corner_gain &&
        a.focus_lift_onset==b.focus_lift_onset && a.focus_lift_power==b.focus_lift_power &&
        a.edge_reach_px==b.edge_reach_px && a.edge_fast_px==b.edge_fast_px &&
        a.edge_rate==b.edge_rate && a.edge_hysteresis==b.edge_hysteresis &&
        a.legacy_inward_feather==b.legacy_inward_feather &&
        a.legacy_inward_anchor_px==b.legacy_inward_anchor_px &&
        a.ambient_radius_px==b.ambient_radius_px &&
        a.ambient_inside_px==b.ambient_inside_px &&
        a.ambient_time_ms==b.ambient_time_ms &&
        a.seam_mode==b.seam_mode && a.seam_strength==b.seam_strength &&
        a.seam_max_gain==b.seam_max_gain && a.seam_brightness_ev==b.seam_brightness_ev &&
        a.seam_color_strength==b.seam_color_strength && a.seam_local_strength==b.seam_local_strength &&
        a.seam_radius_px==b.seam_radius_px && a.seam_transition_px==b.seam_transition_px &&
        a.seam_debug==b.seam_debug &&
        a.gpu_timing==b.gpu_timing &&
        a.debug_border==b.debug_border && a.eye_tracked==b.eye_tracked &&
        a.diagnostic_view==b.diagnostic_view && a.stabilize_crop==b.stabilize_crop &&
        a.guard_fraction==b.guard_fraction && a.gaze_quant_pixels==b.gaze_quant_pixels &&
        a.gaze_hold_ms==b.gaze_hold_ms && a.gaze_reacquire_samples==b.gaze_reacquire_samples &&
        a.gaze_offset_u==b.gaze_offset_u && a.gaze_offset_v==b.gaze_offset_v &&
        a.gaze_micro_gain==b.gaze_micro_gain && a.gaze_breakout_radius==b.gaze_breakout_radius &&
        a.gaze_still_radius==b.gaze_still_radius && a.gaze_relock_samples==b.gaze_relock_samples;
}

} // namespace uevr::quadview

```

## FILE src/mods/vr/QuadViewSnapshot.hpp (31 lines)
```cpp
#pragma once
// Tri-view B11 proof snapshots (shared by the compositor and the menu).
#include <atomic>
#include <cstdint>
#include <filesystem>
#include <mutex>
#include <string>

namespace uevr::quadview::dx12 {
// B11 proof snapshots: one request copies the final double-wide eye image, the
// three source renders and the periphery depth of the NEXT composite into
// CPU readback buffers; after that GPU slot retires, a background thread writes
// them as .dds files (+ an info .txt) into snapshot_directory().
inline std::atomic<bool>& snapshot_requested() { static std::atomic<bool> requested{false}; return requested; }
inline std::atomic<uint32_t>& snapshots_written() { static std::atomic<uint32_t> written{0}; return written; }
inline std::mutex& snapshot_mutex() { static std::mutex m; return m; }
inline std::filesystem::path& snapshot_directory_storage() { static std::filesystem::path dir; return dir; }
inline void set_snapshot_directory(const std::filesystem::path& dir) { std::scoped_lock l(snapshot_mutex()); snapshot_directory_storage() = dir; }
inline std::filesystem::path snapshot_directory() { std::scoped_lock l(snapshot_mutex()); return snapshot_directory_storage(); }
inline std::string& last_snapshot_message_storage() { static std::string m{"none yet"}; return m; }
inline std::string last_snapshot_message() { std::scoped_lock l(snapshot_mutex()); return last_snapshot_message_storage(); }

// B11: what the last composite did with periphery depth (menu/log proof):
// 0 not requested, 1 warping with depth, 2 depth bound but eye geometry invalid,
// 3 requested but no depth copy available, 4 depth bound for show only.
inline std::atomic<uint32_t>& last_depth_state() { static std::atomic<uint32_t> state{0}; return state; }
inline const char* depth_state_name(uint32_t s) {
    static const char* names[]{"not requested", "warping", "depth bound but eye geometry invalid", "no depth copy", "show only"};
    return s < 5 ? names[s] : "?";
}
} // namespace uevr::quadview::dx12

```

## FILE src/mods/vr/QuadViewStatus.hpp (54 lines)
```cpp
#pragma once
#include <cstdint>
#include <mutex>

namespace uevr::quadview {
enum class DisplayState { transitioning, unavailable, waiting_targets, waiting_submit, active, stalled };
struct StatusFacts {
    uint64_t generation{}, tick{};
    bool transitioning{}, unavailable{}, targets_ready{};
};
class StatusTracker {
public:
    struct Submission { uint64_t generation{}, serial{}, tick{}; };
    // No wall-clock inference of ownership: only a successful fresh XR submit
    // supplies all three fields in one transaction.
    bool submitted(uint64_t generation, uint64_t serial, uint64_t tick) {
        std::scoped_lock lock(mutex_);
        if (!generation || !serial || generation < last_.generation) return false;
        if (generation == last_.generation && (serial <= last_.serial || tick < last_.tick)) return false;
        last_ = {generation, serial, tick};
        return true;
    }
    Submission snapshot(uint64_t generation) {
        std::scoped_lock lock(mutex_);
        if (generation > last_.generation) last_ = {generation, 0, 0};
        return last_;
    }
    DisplayState state(const StatusFacts& facts) {
        const auto last = snapshot(facts.generation);
        if (facts.unavailable) return DisplayState::unavailable;
        if (facts.transitioning) return DisplayState::transitioning;
        const bool same = last.generation == facts.generation && last.serial != 0;
        // A fresh submission is authoritative even if a new draw is currently
        // acquiring targets. Held continuity images never refresh this clock.
        if (same && facts.tick >= last.tick && facts.tick - last.tick < 1000) return DisplayState::active;
        if (!facts.targets_ready) return DisplayState::waiting_targets;
        return same ? DisplayState::stalled : DisplayState::waiting_submit;
    }
private:
    std::mutex mutex_;
    Submission last_{};
};
inline const char* display_state_text(DisplayState state) {
    switch (state) {
    case DisplayState::transitioning: return "Changing rendering mode";
    case DisplayState::unavailable: return "Unavailable";
    case DisplayState::waiting_targets: return "Waiting for source targets";
    case DisplayState::waiting_submit: return "Waiting for first fresh XR submission";
    case DisplayState::active: return "Active: fresh stereo image submitted";
    case DisplayState::stalled: return "Stalled: no fresh XR submission for 1 second";
    }
    return "Waiting";
}
}

```

## FILE src/mods/vr/QuadViewStatusPanel.hpp (16 lines)
```cpp
#pragma once
#include "imgui.h"
#include "QuadViewStatus.hpp"
namespace uevr::quadview {
// Production and headless tests use the same container. All variable-height
// diagnostics belong inside it; following controls have a fixed cursor origin.
template <typename Details>
inline void draw_status_panel(DisplayState state, bool triview, Details&& details) {
    ImGui::Text("%s status: %s", triview ? "TriView" : "QuadView", display_state_text(state));
    const bool visible = ImGui::BeginChild("##QuadViewStatusDetails",
        ImVec2(0.f, ImGui::GetTextLineHeightWithSpacing() * 7.f), true,
        ImGuiWindowFlags_NoScrollWithMouse); // Mouse wheel belongs to the existing parent menu.
    if (visible) details();
    ImGui::EndChild();
}
}

```

## FILE src/mods/vr/QuadViewViewDemand.hpp (64 lines)
```cpp
#pragma once

#include <cstdint>
#include <mutex>
#include <optional>

namespace uevr::quadview {

constexpr bool source_admission_open(bool quadview_selected, bool transition_pending) {
    return quadview_selected && !transition_pending;
}

constexpr unsigned desired_view_count(bool quadview_selected, bool hooks_ready,
                                      bool inside_post_init, bool transition_pending = false) {
    if (inside_post_init || transition_pending || !quadview_selected || !hooks_ready) return 2;
    return 4;
}

struct DrawDemand {
    uint64_t generation{}, serial{}, request_token{};
    unsigned view_count{2};
    bool quadview_selected{};
    bool source_admission{};
};

// Selection and transition state are sampled once at viewport-draw entry.
// Every view callback in that draw sees this same demand even if UI state
// changes between callbacks; the next draw observes the pending transition.
class DrawDemandLatch {
public:
    DrawDemand begin(uint64_t generation, uint64_t serial, bool selected, bool pending,
                     uint64_t request_token = 0) {
        std::scoped_lock lock{mutex_};
        current_ = DrawDemand{generation, serial, request_token, desired_view_count(selected, true, false, pending),
                              selected, source_admission_open(selected, pending)};
        if (current_->view_count != 4) current_->source_admission = false;
        return *current_;
    }

    std::optional<DrawDemand> get(uint64_t generation, uint64_t serial) const {
        std::scoped_lock lock{mutex_};
        if (!current_ || current_->generation != generation || current_->serial != serial) return {};
        return current_;
    }

    bool transition_closed(uint64_t generation, uint64_t serial, uint64_t request_token,
                          bool selected, bool pending) const {
        if (!selected) return true;
        const auto demand = get(generation, serial);
        return pending && demand && demand->request_token == request_token &&
            demand->view_count == 2 && !demand->source_admission;
    }

    void reset() {
        std::scoped_lock lock{mutex_};
        current_.reset();
    }

private:
    mutable std::mutex mutex_{};
    std::optional<DrawDemand> current_{};
};

} // namespace uevr::quadview

```

## FILE src/mods/vr/TriViewAdmission.hpp (22 lines)
```cpp
#pragma once
#include <cstdint>
namespace uevr::quadview {
// Native source creation needs renderer/RHI progress. A warm-up family is
// engine-only: render its context once, never the otherwise unused role 1.
// Restore on every exit so Unreal's view/history bookkeeping stays unchanged.
class BootstrapViewCount {
public:
    explicit BootstrapViewCount(int32_t& count) noexcept : count_(count), saved_(count) {
        if (count_ == 4) count_ = 1;
    }
    ~BootstrapViewCount() { count_ = saved_; }
    BootstrapViewCount(const BootstrapViewCount&) = delete;
private:
    int32_t& count_;
    int32_t saved_;
};
constexpr bool native_triview_publishable(bool shared, bool native_local,
                                         uint64_t target_set_generation) noexcept {
    return shared && native_local && target_set_generation != 0;
}
}

```

## FILE src/mods/vr/TriViewEpochGate.hpp (56 lines)
```cpp
#pragma once
#include <atomic>
#include <cstdint>
#include <utility>

namespace uevr::triview {
// One GT writer; nonblocking close while existing XR callbacks drain. New
// callbacks cannot enter between the zero-reader check and world invalidation.
// Nested work on the same thread belongs to its already admitted transaction.
class EpochGate {
public:
    class Read {
    public:
        Read() = default;
        Read(const Read&) = delete;
        Read& operator=(const Read&) = delete;
        Read(Read&& other) noexcept : gate_{std::exchange(other.gate_,nullptr)},
            previous_{other.previous_}, outer_{other.outer_} {}
        ~Read() {
            if (gate_ && outer_) {
                active_=previous_;
                gate_->readers_.fetch_sub(1);
            }
        }
        explicit operator bool() const { return gate_!=nullptr; }
    private:
        friend class EpochGate;
        Read(const EpochGate* gate, const EpochGate* previous, bool outer)
            : gate_{gate}, previous_{previous}, outer_{outer} {}
        const EpochGate* gate_{};
        const EpochGate* previous_{};
        bool outer_{};
    };
    Read read() const {
        if (active_==this) return Read{this,this,false};
        if (closed_.load()) return {};
        readers_.fetch_add(1);
        if (closed_.load()) { readers_.fetch_sub(1); return {}; }
        const auto* previous=active_;
        active_=this;
        return Read{this,previous,true};
    }
    bool try_close() {
        closed_.store(true);
        return readers_.load()==0;
    }
    bool closed() const { return closed_.load(); }
    void open() { closed_.store(false); }
private:
    // Sequential consistency makes admission/close a single total order;
    // relaxed counts would permit both sides to miss the other's operation.
    mutable std::atomic<uint32_t> readers_{};
    std::atomic<bool> closed_{};
    inline static thread_local const EpochGate* active_{};
};
} // namespace uevr::triview

```

## FILE src/mods/vr/TriViewGammaTables.hpp (40 lines)
```cpp
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <mutex>

namespace uevr::quadview {
// Like DuoView's static Native Fix table: Unreal may invoke its resource's
// virtual destructor after the last plugin packet owner has retired. These
// tiny immutable tables outlive all engine resources; they retain no textures.
template<size_t Slots, size_t Capacity = 8> class PersistentGammaTables {
public:
    using Table = std::array<uintptr_t, Slots>;
    const Table* acquire(uintptr_t original_address, const Table& original,
                         size_t gamma_slot, uintptr_t replacement) {
        if (!original_address || !replacement || gamma_slot >= Slots) return nullptr;
        std::scoped_lock lock{mutex_};
        for (const auto& entry : entries_) {
            if (entry.used && entry.address == original_address && entry.slot == gamma_slot &&
                entry.replacement == replacement && entry.original == original) return &entry.hooked;
        }
        for (auto& entry : entries_) {
            if (entry.used) continue;
            entry.address = original_address; entry.slot = gamma_slot; entry.replacement = replacement;
            entry.original = original; entry.hooked = original;
            entry.hooked[gamma_slot] = replacement;
            entry.used = true;
            return &entry.hooked;
        }
        return nullptr; // Bounded storage, never overwrite a published table.
    }
private:
    struct Entry {
        bool used{}; uintptr_t address{}, replacement{}; size_t slot{};
        Table original{}, hooked{};
    };
    std::mutex mutex_{};
    std::array<Entry, Capacity> entries_{};
};
} // namespace uevr::quadview

```

## FILE src/mods/vr/TriViewHold.hpp (44 lines)
```cpp
#pragma once
// B41: TriView-only replacement for uevr::duoview::SubmitContinuity.
// Same interface and rules (no hold before the first submit, no hold across a
// mode/generation or swapchain change), but the hold window is a user setting
// (100..1000 ms, default 250) instead of DuoView's fixed 100 ms. DuoView keeps
// its own class unchanged.
#include <algorithm>
#include <atomic>
#include <cstdint>

namespace uevr::quadview {

class TriViewHold {
public:
    static constexpr uint32_t min_window_ms = 100;
    static constexpr uint32_t max_window_ms = 1000;
    static constexpr uint32_t default_window_ms = 250;

    static void set_window_ms(uint32_t ms) {
        window_ms_.store(std::clamp(ms, min_window_ms, max_window_ms), std::memory_order_relaxed);
    }
    static uint32_t window_ms() { return window_ms_.load(std::memory_order_relaxed); }

    void reset() { ready_ = false; }
    void submitted(uint64_t generation, uint64_t swapchain, uint64_t now_ms) {
        generation_ = generation; swapchain_ = swapchain; submitted_ms_ = now_ms; ready_ = true;
    }
    bool can_hold(uint64_t generation, uint64_t swapchain, uint64_t now_ms) const {
        return ready_ && generation == generation_ && swapchain && swapchain == swapchain_ &&
            now_ms >= submitted_ms_ && now_ms - submitted_ms_ <= window_ms();
    }
    bool ready() const { return ready_; }
    // Milliseconds since the last real (not held) submit; 0 before the first.
    uint64_t age_ms(uint64_t now_ms) const {
        return ready_ && now_ms >= submitted_ms_ ? now_ms - submitted_ms_ : 0;
    }

private:
    static inline std::atomic<uint32_t> window_ms_{default_window_ms};
    uint64_t generation_{}, swapchain_{}, submitted_ms_{};
    bool ready_{};
};

} // namespace uevr::quadview

```

## FILE src/mods/vr/TriViewLocatedPose.hpp (24 lines)
```cpp
#pragma once
#include <cstdint>
#include <optional>
#include <utility>

namespace uevr::triview {
// Caller holds the runtime's pose mutex. Only a successful locate may publish.
// Invalidation preserves the sequence so old draw packets cannot match a new epoch.
template<class T> class LocatedPose {
public:
    void publish(const T& pose) {
        // Copy assignment reuses the two-view vector capacity in PipelineState.
        // Copy-constructing a temporary here would allocate on every locate.
        if (value_) *value_=pose;
        else value_.emplace(pose);
        value_->quadview_locate_serial=++serial_;
    }
    void invalidate() { value_.reset(); }
    const std::optional<T>& get() const { return value_; }
private:
    uint64_t serial_{};
    std::optional<T> value_{};
};
}

```

## FILE src/mods/vr/TriViewVramGuard.hpp (84 lines)
```cpp
#pragma once
// Tri-view B42: keep video memory below a safe share of the DXGI budget.
//
// Headset finding (9-10 Nov 2026): STALKER 2 + TriView BSODs (0x139) when the
// game process fills its VRAM budget (~10 GB on a 12 GB RTX 5070). Our own
// colour targets are small (13-56 MB per set); the growth comes from Unreal's
// per-size scene buffers (G-buffer, Lumen, DLSS histories ...) that each new
// view size allocates while the previous set is still alive. So before every
// new source-target set we estimate its cost per source pixel and refuse the
// build when "used now + estimate" would pass the limit. A refused build keeps
// the current image (TriView keeps drawing the live set).
//
// Pure logic, no D3D: unit-tested by TriViewVramGuardTests.cpp.
#include <array>
#include <cmath>
#include <cstdint>

namespace uevr::quadview::vram {

// Estimated bytes for every source pixel of a NEW set: our colour target (4 B)
// plus a generous allowance for Unreal's per-view-size scene buffers. Calibrate
// from the B42 "[TriView][VRAM] build" log lines (used before/after).
constexpr uint64_t bytes_per_source_pixel = 100;
// Per-eye-pixel cost of a headset resolution change: OpenXR colour swapchain
// (3 images x 4 B), Slate/UI and copy targets (allowance).
constexpr uint64_t bytes_per_eye_pixel = 24;
constexpr float default_limit_percent = 85.f;

using Extents = std::array<std::array<uint32_t, 2>, 4>;

inline uint64_t source_pixels(const Extents& e) {
    uint64_t px = 0;
    for (const auto& one : e) px += uint64_t(one[0]) * one[1];
    return px;
}

// Cost of building a new set with these extents (the old set stays alive until
// the new one is published, so the whole new set counts, not only the growth).
inline uint64_t build_estimate(const Extents& e) { return source_pixels(e) * bytes_per_source_pixel; }

inline uint64_t limit_bytes(uint64_t budget, float limit_percent) {
    if (!std::isfinite(limit_percent)) limit_percent = default_limit_percent;
    if (limit_percent < 50.f) limit_percent = 50.f;
    if (limit_percent > 98.f) limit_percent = 98.f;
    return uint64_t(double(budget) * double(limit_percent) / 100.0);
}

// budget == 0: no DXGI reading yet -> allow (never block TriView on missing data).
inline bool allows(uint64_t used, uint64_t budget, uint64_t estimate, float limit_percent) {
    if (budget == 0 || estimate == 0) return true;
    return used + estimate <= limit_bytes(budget, limit_percent);
}

// TriView source pixels (one shared periphery + two foveas) for an eye size and
// the menu fractions; mirrors make_layout's rounding closely enough for an estimate.
inline uint64_t triview_source_pixels(uint32_t eye_w, uint32_t eye_h, float crop_w, float crop_h,
                                      float context_scale, float density) {
    const auto r = [](double v) { return uint64_t(v < 1.0 ? 1.0 : std::round(v)); };
    const uint64_t ctx = r(eye_w * double(context_scale)) * r(eye_h * double(context_scale));
    const uint64_t fov = r(eye_w * double(crop_w) * density) * r(eye_h * double(crop_h) * density);
    return ctx + 2 * fov;
}

// Cost of switching the headset resolution from (old) to (new) while TriView runs.
inline uint64_t resolution_switch_estimate(uint32_t old_w, uint32_t old_h, uint32_t new_w, uint32_t new_h,
                                           float crop_w, float crop_h, float context_scale, float density) {
    // The low-resolution set stays alive until the new one is published, so the
    // whole new set counts, plus the growth of the per-eye resources.
    const uint64_t src_new = triview_source_pixels(new_w, new_h, crop_w, crop_h, context_scale, density);
    const uint64_t eye_new = uint64_t(new_w) * new_h * 2, eye_old = uint64_t(old_w) * old_h * 2;
    return src_new * bytes_per_source_pixel + (eye_new > eye_old ? (eye_new - eye_old) * bytes_per_eye_pixel : 0);
}

// B42: fewer distinct view sizes. Unreal keeps scene buffers per view size, so
// every 1-2 % slider step used to allocate a new set. Fractions snap to 0.05.
inline float snap_fraction(float v, float lo, float hi, float step = .05f) {
    if (!std::isfinite(v)) return v;
    float s = std::round(v / step) * step;
    if (s < lo) s = lo;
    if (s > hi) s = hi;
    return s;
}

} // namespace uevr::quadview::vram

```

## SHADER quadview/QuadViewComposite.hlsl (807 lines)
```hlsl
Texture2D<float4> ContextLeftSource : register(t0);
Texture2D<float4> ContextRightSource : register(t1);
Texture2D<float4> FocusLeftSource : register(t2);
Texture2D<float4> FocusRightSource : register(t3);
Texture2D<float> PeripheryDepth : register(t4); // B7: DLSS depth input of the periphery render (reversed-Z)
StructuredBuffer<float4> SeamMatch : register(t5); // per eye: global + eight boundary gains
SamplerState LinearClamp : register(s0);

cbuffer QuadViewConstants : register(b0) {
    uint4 EyeAndAtlas;
    uint4 ContextLeft;
    uint4 ContextRight;
    uint4 FocusLeft;
    uint4 FocusRight;
    float4 CropUvLeft;
    float4 CropUvRight;
    float4 Options;
    float4 Sharpen; // legacy strength, flags, legacy max change, FXAA bias
    float4 SharpenEye; // left strength, right strength, left max change, right max change
    float4 ContextHLeft[3];  // tri-view: h = H * (uv, 1), context uv = h.xy / h.z (identity for four views)
    float4 ContextHRight[3];
    uint4 ContextSource;     // x left eye, y right eye (tri-view: both 0)
    float4 DepthShift;       // B7: context-uv shift per unit reversed-Z depth (left u, v, right u, v)
    uint4 DepthRect;         // B7: depth texel rectangle of the periphery render (x, y, w, h)
    uint4 DepthOptions;      // B9: x = reproject, y = show requested, z = validated depth bound
    float4 DepthEyeOrigin[2];
    float4 DepthProjection;
    float4 DepthCoefficients;
    float4 DepthJitter;
    float4 Seam;        // mode, strength, maximum relative auto gain, manual sample-domain gain
    float4 SeamOptions; // color strength, reserved rendered-edge pixels, confidence debug, alignment usable
    float4 SeamLocal;   // outward residual radius in output pixels, local strength, reserved
    float4 FocusLift;    // enabled, overall brightness, corner gain minus one, onset r^2
    float4 EdgeV2; // broad reach, fast reach, RGB slew/sec, hysteresis inner threshold
    uint4 EdgeHistory; // generation/settings epoch, timestamp ms, shared history enabled, reserved
    float4 FocusProfile; // exponent, anti-vignette strength, reserved
};

struct VertexOut {
    float4 position : SV_POSITION;
};

VertexOut VSMain(uint vertexId : SV_VertexID) {
    const float2 uv = float2((vertexId << 1) & 2, vertexId & 2);
    VertexOut result;
    result.position = float4(uv * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
    return result;
}

// B6: every source is normalised by its OWN texture size (compact per-role
// targets); for the shared atlas or full-size targets this equals EyeAndAtlas.zw.
float2 SourceSize(uint sourceIndex) {
    uint width = 1u, height = 1u;
    [branch] if (sourceIndex == 0u) ContextLeftSource.GetDimensions(width, height);
    else if (sourceIndex == 1u) ContextRightSource.GetDimensions(width, height);
    else if (sourceIndex == 2u) FocusLeftSource.GetDimensions(width, height);
    else FocusRightSource.GetDimensions(width, height);
    return float2(max(width, 1u), max(height, 1u));
}

float2 AtlasUvKnownSize(float2 atlasSize, uint4 rectangle, float2 uv) {
    const float2 origin = float2(rectangle.xy);
    const float2 extent = float2(rectangle.zw);
    const float2 texel = clamp(origin + saturate(uv) * extent,
                              origin + 0.5, origin + extent - 0.5);
    return texel / atlasSize;
}

float2 AtlasUv(uint sourceIndex, uint4 rectangle, float2 uv) {
    return AtlasUvKnownSize(SourceSize(sourceIndex), rectangle, uv);
}

float2 ContextUv(uint eye, float2 eyeUv) {
    const float3 p = float3(eyeUv, 1.0);
    float3 h;
    [flatten] if (eye == 0) h = float3(dot(ContextHLeft[0].xyz, p), dot(ContextHLeft[1].xyz, p), dot(ContextHLeft[2].xyz, p));
    else h = float3(dot(ContextHRight[0].xyz, p), dot(ContextHRight[1].xyz, p), dot(ContextHRight[2].xyz, p));
    return h.xy / max(h.z, 1.0e-4);
}

// Source depth is matched to this context frame. Jitter converts unjittered
// DLSS color UV into the corresponding raw depth sample location.
float PeripheryDepthAt(float2 uv) {
    const float2 p = float2(DepthRect.xy) + saturate(uv + DepthJitter.xy) * float2(DepthRect.zw);
    const uint2 last = DepthRect.xy + max(DepthRect.zw, 1u) - 1u;
    return saturate(PeripheryDepth.Load(int3(min(uint2(p), last), 0)));
}

float InverseDepthAt(float2 uv) {
    return (DepthCoefficients.z * PeripheryDepthAt(uv) - DepthCoefficients.x) / DepthCoefficients.y;
}

// B12: the eye ray is marched through the periphery depth, from near to far, in
// inverse-depth steps; the first surface it meets is what this eye sees. B7-B11
// used a 4-step fixed point that, for close objects (hands, gun: up to ~7 % of
// the periphery width of disparity), stayed on the mono position and showed a
// second, unshifted copy of the arm. Where the eye sees background that the
// periphery camera could not (behind a near object), `fill` is set and the
// caller blends a soft background sample instead of stretching the edge.
// Verified offline against the real fovea of a B11 game snapshot.
float2 WarpContextUv(uint eye, float2 contextUv, out float fill) {
    float2 uv = contextUv; // single exit: fxc /WX rejects early returns here (X4000)
    fill = 0.0;
    [branch] if (DepthOptions.x != 0u) {
        const float3 t = DepthEyeOrigin[eye].xyz;
        const float2 ray = float2((2.0 * contextUv.x - 1.0 - DepthProjection.y) / DepthProjection.x,
                                 (1.0 - 2.0 * contextUv.y - DepthProjection.w) / DepthProjection.z);
        // context-uv shift per unit of inverse depth (full eye translation incl. forward/vertical)
        const float2 k = float2(0.5 * DepthProjection.x, -0.5 * DepthProjection.z) * (t.xy - ray * t.z) * DepthCoefficients.w;
        // nearest surface searched: 8 world units (~8 cm), or the near plane if farther
        const float sMax = min(abs(DepthCoefficients.z / DepthCoefficients.y), 0.125);
        const float ds = sMax / 3.0;
        float2 previousUv = contextUv + k * sMax;
        float previousF = -1.0, previousInverse = 0.0;
        bool found = false;
        [loop] for (uint i = 0; i <= 3u && !found; ++i) {
            const float s = sMax - ds * float(i);
            const float2 c = contextUv + k * s;
            const bool inside = all(c >= 0.0) && all(c <= 1.0);
            const float inverseZ = inside ? InverseDepthAt(c) : 0.0;
            const float f = inverseZ - s;
            [branch] if (inside && f >= 0.0) {
                found = true;
                if (i == 0u || previousF <= -0.5) {
                    // Never blend with the previous out-of-bounds ray.
                    uv = c;
                } else if (previousF > -0.5 && inverseZ > previousInverse * 1.25 + 2.0 * ds) {
                    // depth jumps in front of the ray: hidden background, fill softly
                    uv = contextUv + k * (s + 4.0 * ds);
                    fill = 1.0;
                } else {
                    uv = lerp(previousUv, c, saturate(previousF / min(previousF - f, -1.0e-6)));
                }
            }
            previousF = inside ? f : -1.0;
            previousUv = c;
            previousInverse = inverseZ;
        }
    }
    return uv;
}

// Explicit SM5 resource selection keeps each source independent, including sharpening taps.
float4 ReadSource(uint sourceIndex, float2 uv) {
    float4 color = float4(0.0, 0.0, 0.0, 1.0);
    [branch] if (sourceIndex == 0u) color = ContextLeftSource.SampleLevel(LinearClamp, uv, 0.0);
    else if (sourceIndex == 1u) color = ContextRightSource.SampleLevel(LinearClamp, uv, 0.0);
    else if (sourceIndex == 2u) color = FocusLeftSource.SampleLevel(LinearClamp, uv, 0.0);
    else color = FocusRightSource.SampleLevel(LinearClamp, uv, 0.0);
    return color;
}

float FocusWeight(float2 uv, float4 crop) {
    if (any(uv < crop.xy) || any(uv > crop.zw)) return 0.0;
    const float2 cropExtent = crop.zw - crop.xy;
    const float2 distanceToEdge = min(uv - crop.xy, crop.zw - uv) / cropExtent;
    const float feather = clamp(Options.x, 0.0, 0.49);
    if (feather == 0.0) return 1.0;
    const float edge = saturate(min(distanceToEdge.x, distanceToEdge.y) / feather);
    return edge * edge * (3.0 - 2.0 * edge);
}

static const float3 GlamLuma = float3(0.2126, 0.7152, 0.0722);

float3 GlamDecode(float3 color) {
    if (((uint)Sharpen.y & 4u) == 0u) return color;
    const float3 low = color / 12.92;
    const float3 high = pow(abs(color + 0.055) / 1.055, 2.4);
    return lerp(low, high, float3(color.r > 0.04045, color.g > 0.04045, color.b > 0.04045));
}

float3 GlamEncode(float3 color) {
    if (((uint)Sharpen.y & 4u) == 0u) return color;
    const float3 low = color * 12.92;
    const float3 high = 1.055 * pow(abs(color), 1.0 / 2.4) - 0.055;
    return lerp(low, high, float3(color.r > 0.0031308, color.g > 0.0031308, color.b > 0.0031308));
}

float3 ReadFocus(uint sourceIndex, uint4 rect, float2 focusUv, float2 tapScale, float2 pixelOffset, float2 sourceSize) {
    // Share crop/output normalization across the six sharpening taps.
    // AtlasUv still clamps taps to this eye's focus rectangle.
    const float2 local = focusUv + pixelOffset * tapScale;
    return GlamDecode(ReadSource(sourceIndex, AtlasUvKnownSize(sourceSize, rect, local)).rgb);
}

float3 GlamSharpenFocus(uint sourceIndex, uint4 rect, float2 focusUv, float2 tapScale, float3 center,
                        float strength, float maxChange, float2 sourceSize) {
    // Fused v186.1 Glamarye Bigger-radius four-diagonal filter with its
    // FXAA-style edge guard and maximum-change limiter. No separate pass.
    const float3 c = GlamDecode(center);
    const float radius = 1.4;
    const float3 ne = ReadFocus(sourceIndex, rect, focusUv, tapScale, float2( radius,  radius), sourceSize);
    const float3 sw = ReadFocus(sourceIndex, rect, focusUv, tapScale, float2(-radius, -radius), sourceSize);
    const float3 se = ReadFocus(sourceIndex, rect, focusUv, tapScale, float2( radius, -radius), sourceSize);
    const float3 nw = ReadFocus(sourceIndex, rect, focusUv, tapScale, float2(-radius,  radius), sourceSize);
    float3 smoothed = (ne + nw) + (se + sw);
    smoothed = clamp((smoothed + c) / 5.0, c * 0.5, c * 2.0);
    smoothed = min(smoothed, 1.0);

    const float dy = dot(GlamLuma, abs((ne + nw) - (se + sw)));
    const float dx = dot(GlamLuma, abs((ne + se) - (nw + sw)));
    const bool horizontal = dy > dx;
    float3 n2 = horizontal ? ne + nw : ne + se;
    float3 s2 = horizontal ? se + sw : nw + sw;
    n2 *= 0.5; s2 *= 0.5;
    const float2 west = horizontal ? float2(-3.5, 0.0) : float2(0.0, 3.5);
    const float2 east = horizontal ? float2( 3.5, 0.0) : float2(0.0,-3.5);
    const float3 ww = ReadFocus(sourceIndex, rect, focusUv, tapScale, west, sourceSize);
    const float3 ee = ReadFocus(sourceIndex, rect, focusUv, tapScale, east, sourceSize);
    const float3 d1 = abs((ww - n2) - (ee - s2));
    const float3 d2 = abs((ee - n2) - (ww - s2));
    const float3 totalDiff = d1 + d2 + 0.00004;
    const float3 maxDiff = max(d1, d2) + 0.00001 - Sharpen.w * sqrt(max(smoothed, 0.0));
    const float edgeRatio = max(2.0 * dot(GlamLuma, maxDiff / totalDiff) - 1.0, 0.0);

    const float3 diffRGB = 2.0 * c + (ne + nw + se + sw)
        - 3.0 * (max(max(ne,nw),max(se,sw)) + min(min(ne,nw),min(se,sw)));
    const float diff = dot(GlamLuma, diffRGB);
    float3 possible = min(smoothed, c * 0.5);
    possible = min(possible, 1.0 - max(smoothed, c));
    possible = clamp(possible, 0.00001, maxChange);
    float3 change = diff / (1.0 / max(strength, 0.00001) + abs(diff) / possible);
    change *= (1.0 - edgeRatio);
    return GlamEncode(c + change);
}

float4 ReadContext(uint eye, uint contextSource, uint4 contextRect, float2 eyeUv) {
    // Fully opaque native fovea pixels never need this context homography.
    const float2 contextUv = ContextUv(eye, eyeUv);
    float fill = 0.0;
    const float2 uv = WarpContextUv(eye, contextUv, fill);
    float4 color = float4(0.0, 0.0, 0.0, 1.0);
    [branch] if (DepthOptions.y != 0u) {
        const float v = pow(PeripheryDepthAt(uv), 0.25);
        color = float4(v, v, v, 1.0);
    } else if (fill > 0.0) {
        // B12: soft 3x5 background average (2-texel spacing) hides row streaks in disocclusions
        // One resource-dimension query per disocclusion pixel, not once per tap.
        const float2 sourceSize = SourceSize(contextSource);
        const float2 tap = 2.0 / max(float2(contextRect.zw), 1.0);
        float4 sum = float4(0.0, 0.0, 0.0, 0.0);
        [unroll] for (int y = -2; y <= 2; ++y)
            [unroll] for (int x = -1; x <= 1; ++x)
                sum += ReadSource(contextSource, AtlasUvKnownSize(sourceSize, contextRect, uv + float2(x, y) * tap));
        color = sum / 15.0;
    } else {
        color = ReadSource(contextSource, AtlasUv(contextSource, contextRect, uv));
    }
    return color;
}

// Optional manual compensation, independent of seam mode. The calibrated radial
// mask lifts corners without changing the neutral center.
// This is brightness-only compensation, not recovery of clipped/lost details.
float3 CorrectFocusColor(float3 color, float2 focusUv) {
    [branch] if (FocusLift.x > 0.5) {
        const float2 q=focusUv*2.0-1.0;
        const float r2=saturate(dot(q,q)*0.5);
        float gain=FocusLift.y;
        // The calibrated interior has t=0: do not execute pow() there.
        // Uniform brightness remains effective inside the neutral mask.
        [branch] if (r2 > FocusLift.w && FocusLift.z*FocusProfile.y > 0.0) {
            const float t=saturate((r2-FocusLift.w)/max(1.0-FocusLift.w,0.1));
            gain *= 1.0+FocusLift.z*FocusProfile.y*pow(t,FocusProfile.x);
        }
        color=max(color*gain,0.0);
    }
    return color;
}

// Appearance changes affect only sampled peripheral colors. Estimate and apply
// in the same source-sample domain; preserve B28's final output encoding. This
// costs one multiply per channel, without per-output-pixel gamma conversions.
// B35: both analysis and display use this exact post-NR/SR, sharpened,
// anti-vignette-corrected reference. No changes to B31 CorrectFocusColor.
float4 DisplayFocus(uint eye, uint4 rect, float2 focusUv, float4 crop) {
    const float2 size = SourceSize(2u + eye);
    float4 f = ReadSource(2u + eye, AtlasUvKnownSize(size, rect, focusUv));
    const float strength = eye == 0u ? SharpenEye.x : SharpenEye.y;
    const float change = eye == 0u ? SharpenEye.z : SharpenEye.w;
    [branch] if (strength > 0.0) {
        const float2 taps = 1.0 / (float2(EyeAndAtlas.xy) * (crop.zw - crop.xy));
        f.rgb = GlamSharpenFocus(2u + eye, rect, focusUv, taps, f.rgb, strength, change, size);
    }
    f.rgb = CorrectFocusColor(f.rgb, focusUv);
    return f;
}

// Project onto the closest *displayed* focus border, including noninteger
// crops. Pixel centers are used, not a context-footprint-dependent inset.
float2 EdgeAnchor(float2 uv, float4 crop, out uint side, out float along) {
    const float2 size = float2(EyeAndAtlas.xy);
    const float2 lo = (ceil(crop.xy * size - 0.5) + 0.5) / size;
    const float2 hi = (ceil(crop.zw * size - 0.5) - 0.5) / size;
    float2 p = clamp(uv, lo, hi);
    const float4 d = abs(float4(uv.y-lo.y, uv.x-hi.x, uv.y-hi.y, uv.x-lo.x)) * size.yxyx;
    side = 0u;
    float best = d.x;
    if (d.y < best) { side=1u; best=d.y; }
    if (d.z < best) { side=2u; best=d.z; }
    if (d.w < best) side=3u;
    // Outside the rectangle, clamping already gives the nearest border.
    // Infinite-line distances are only valid for points inside the crop.
    if (uv.y < lo.y) side=0u;
    else if (uv.y > hi.y) side=2u;
    else if (uv.x > hi.x) side=1u;
    else if (uv.x < lo.x) side=3u;
    if (side == 0u) p.y=lo.y;
    else if (side == 1u) p.x=hi.x;
    else if (side == 2u) p.y=hi.y;
    else p.x=lo.x;
    const float2 a = saturate((p-lo)/max(hi-lo,1.0/size));
    along = side == 0u ? a.x : side == 1u ? a.y : side == 2u ? 1.0-a.x : 1.0-a.y;
    return p;
}

// Low-frequency RGB residual from corresponding positions on the displayed
// border. Tangential taps do not move the analysis inward from the seam.
// Validity is geometric/finite; large valid color differences are never capped.
bool EdgeDifference(uint eye, float2 anchor, uint side, float4 crop, out float3 delta) {
    const uint4 fr = eye == 0u ? FocusLeft : FocusRight;
    const uint4 cr = eye == 0u ? ContextLeft : ContextRight;
    const uint cs = eye == 0u ? ContextSource.x : ContextSource.y;
    const float2 size = float2(EyeAndAtlas.xy);
    const float2 lo = (ceil(crop.xy*size-0.5)+0.5)/size;
    const float2 hi = (ceil(crop.zw*size-0.5)-0.5)/size;
    float2 tangent = (side & 1u) == 0u ? float2(2.0/size.x,0.0) : float2(0.0,2.0/size.y);
    // Both adjoining sides share one corner reference, without tangent bias.
    if ((anchor.x <= lo.x || anchor.x >= hi.x) && (anchor.y <= lo.y || anchor.y >= hi.y)) tangent=0.0;
    delta=0.0;
    bool valid = SeamOptions.w > 0.5;
    [unroll] for (int i=-1;i<=1;++i) {
        const float2 p = clamp(anchor+float(i)*tangent,lo,hi);
        float fill=0.0;
        const float2 cu=WarpContextUv(eye,ContextUv(eye,p),fill);
        const float2 fu=(p-crop.xy)/(crop.zw-crop.xy);
        const float3 f=DisplayFocus(eye,fr,fu,crop).rgb;
        const float3 c=ReadSource(cs,AtlasUv(cs,cr,cu)).rgb;
        valid=valid && fill==0.0 && all(cu>=0.0) && all(cu<=1.0) && all(isfinite(f)) && all(isfinite(c));
        delta+=(f-c)*(i==0 ? 0.5 : 0.25);
    }
    return valid;
}

// B39: spatially pool 15 INWARD samples at each of 32 knots per eye.
// No pixel-by-pixel correction, no additional pass or per-frame storage.
bool AmbientEdgeDifference(uint eye,float2 anchor,uint side,float4 crop,out float3 delta) {
    const uint4 fr=eye==0u ? FocusLeft : FocusRight;
    const uint4 cr=eye==0u ? ContextLeft : ContextRight;
    const uint cs=eye==0u ? ContextSource.x : ContextSource.y;
    const float2 size=float2(EyeAndAtlas.xy);
    const float2 lo=(ceil(crop.xy*size-0.5)+0.5)/size;
    const float2 hi=(ceil(crop.zw*size-0.5)-0.5)/size;
    const float2 inward=side==0u ? float2(0.0,1.0) :
                        side==1u ? float2(-1.0,0.0) :
                        side==2u ? float2(0.0,-1.0) : float2(1.0,0.0);
    const float2 tangent=float2(inward.y,-inward.x);
    float3 sum=0.0; float accepted=0.0;
    [unroll] for (int depth=0;depth<3;++depth) {
        const float d=FocusProfile.w*(0.25+0.375*float(depth));
        [unroll] for (int i=-2;i<=2;++i) {
            const float along=0.5*float(i)*FocusProfile.z;
            const float2 p=clamp(anchor+(inward*d+tangent*along)/size,lo,hi);
            const float2 fu=(p-crop.xy)/(crop.zw-crop.xy);
            float fill=0.0;
            const float2 cu=WarpContextUv(eye,ContextUv(eye,p),fill);
            [branch] if (fill==0.0 && all(cu>=0.0) && all(cu<=1.0)) {
                const float3 f=DisplayFocus(eye,fr,fu,crop).rgb;
                const float3 c=ReadSource(cs,AtlasUv(cs,cr,cu)).rgb;
                [branch] if (all(isfinite(f)) && all(isfinite(c))) {
                    sum+=f-c; accepted+=1.0;
                }
            }
        }
    }
    delta=sum/max(accepted,1.0);
    return SeamOptions.w>0.5 && accepted>=8.0;
}

float EdgeFade(float distance, float reach) {
    const float t=saturate(distance/max(reach,1.0));
    return 1.0-t*t*(3.0-2.0*t);
}

float4 MatchEdgeV2(uint eye, float2 uv, float4 crop, float4 color) {
    // Unit plateau includes the first exterior pixel centers for fractional
    // crops too: do not attenuate correction between the two displayed sides.
    const float2 outside=max(max(max(crop.xy-uv,uv-crop.zw),0.0)*float2(EyeAndAtlas.xy)-1.0,0.0);
    const float distance=length(outside);
    [branch] if ((Seam.y > 0.0 || SeamOptions.z > 0.5) && distance < EdgeV2.x && (SeamOptions.w > 0.5 || Seam.x > 5.5)) {
    uint side=0u; float along=0.0;
    const float2 anchor=EdgeAnchor(uv,crop,side,along);
    const float k=float(side*8u)+along*8.0;
    const uint i=((uint)floor(k))%32u, j=(i+1u)%32u;
    const uint base=18u+eye*64u;
    const float4 a=SeamMatch[base+i*2u+1u], b=SeamMatch[base+j*2u+1u];
    const float3 stable=lerp(a.rgb,b.rgb,frac(k));
    const float slow=EdgeFade(distance,EdgeV2.x);
    const float fast=EdgeFade(distance,min(EdgeV2.y,EdgeV2.x));
    float3 target=stable;
    bool valid=true;
    [branch] if (fast > 0.0 && Seam.x<4.5) valid=EdgeDifference(eye,anchor,side,crop,target);
    // At distance zero slow=fast=1: history cancels exactly. Farther out
    // only the slew-limited broad field remains. No focus pixels are blurred.
    // V3 never copies instantaneous border pixels. Its entire field comes
    // from spatially pooled + temporally averaged GPU knots.
    float3 correction=slow*stable+fast*(target-stable);
    [branch] if (Seam.x>4.5) {
        valid=a.a>0.5 && b.a>0.5;
        correction=slow*stable;
    }
    color.rgb=max(color.rgb+Seam.y*(valid ? correction : slow*stable),0.0);
    [branch] if (SeamOptions.z > 0.5) color.rgb=valid ? float3(0.05,0.7,0.05) : float3(0.7,0.05,0.05);
    }
    return color;
}

float3 SeamSideGain(uint baseIndex, uint side, float along, float3 fallback) {
    const float4 a = SeamMatch[baseIndex + 1u + side * 2u];
    const float4 b = SeamMatch[baseIndex + 2u + side * 2u];
    const float t = saturate(along * 2.0 - 0.5);
    return lerp(lerp(fallback, a.rgb, a.a), lerp(fallback, b.rgb, b.a), t);
}

float4 MatchContext(uint eye, float2 uv, float4 crop, float4 color) {
    [branch] if (Seam.x > 2.5) color=MatchEdgeV2(eye,uv,crop,color);
    else if (Seam.x > 0.5) {
        float3 gain = 1.0;
        float confidence = 0.0;
        [branch] if (Seam.x > 1.5 && (Seam.y > 0.0 || SeamOptions.z > 0.5)) {
            const uint baseIndex = eye * 9u;
            const float4 match = SeamMatch[baseIndex];
            gain = lerp(1.0, match.rgb, match.a);
            confidence = match.a;
            const float2 outside = max(max(crop.xy - uv, uv - crop.zw), 0.0) * float2(EyeAndAtlas.xy);
            const float distanceSq = dot(outside, outside);
            // Reject distant pixels before evaluating the square root.
            [branch] if (SeamLocal.y > 0.0 && distanceSq < SeamLocal.x*SeamLocal.x) {
                const float2 along = saturate((uv - crop.xy) / (crop.zw - crop.xy));
                const float4 d = abs(float4(uv.y - crop.y, uv.x - crop.z, uv.y - crop.w, uv.x - crop.x)) *
                                 float4(EyeAndAtlas.y, EyeAndAtlas.x, EyeAndAtlas.y, EyeAndAtlas.x);
                const float4 weights = 1.0 / (1.0 + d * d);
                const float3 local = (SeamSideGain(baseIndex, 0u, along.x, gain) * weights.x +
                                      SeamSideGain(baseIndex, 1u, along.y, gain) * weights.y +
                                      SeamSideGain(baseIndex, 2u, along.x, gain) * weights.z +
                                      SeamSideGain(baseIndex, 3u, along.y, gain) * weights.w) / dot(weights, float4(1.0, 1.0, 1.0, 1.0));
                const float t = saturate(sqrt(distanceSq) / max(SeamLocal.x, 1.0));
                gain = lerp(gain, local, SeamLocal.y * (1.0 - t * t * (3.0 - 2.0 * t)));
            }
        }
        gain = lerp(1.0, gain * Seam.w, Seam.y);
        color.rgb = max(color.rgb * gain, 0.0);
        [branch] if (SeamOptions.z > 0.5)
            color.rgb = lerp(float3(0.7, 0.05, 0.05), float3(0.05, 0.7, 0.05), confidence);
    }
    return color;
}

float SeamFocusWeight(float2 uv, float4 crop) {
    // Off and Edge V2 preserve B31 standard feather. Legacy matching keeps the complete
    // rendered fovea sharp at transition=0. An optional transition reserves
    // existing edge pixels; it does not claim additional rendered coverage.
    if (Seam.x < 0.5 || Seam.x > 2.5) return FocusWeight(uv, crop);
    if (any(uv < crop.xy) || any(uv > crop.zw)) return 0.0;
    const float2 extentPx = (crop.zw - crop.xy) * float2(EyeAndAtlas.xy);
    const float width = min(SeamOptions.y, 0.49 * min(extentPx.x, extentPx.y));
    if (width <= 0.0) return 1.0;
    const float2 edgePx = min(uv - crop.xy, crop.zw - uv) * float2(EyeAndAtlas.xy);
    const float t = saturate(min(edgePx.x, edgePx.y) / width);
    return t * t * (3.0 - 2.0 * t);
}

float4 ScenePixel(VertexOut input) {
    const uint eye = min((uint)input.position.x / EyeAndAtlas.x, 1u);
    const float2 eyeUv = float2(input.position.x - eye * EyeAndAtlas.x,
                               input.position.y) / float2(EyeAndAtlas.xy);
    const uint4 contextRect = eye == 0 ? ContextLeft : ContextRight;
    const uint contextSource = eye == 0 ? ContextSource.x : ContextSource.y;
    const uint4 focusRect = eye == 0 ? FocusLeft : FocusRight;
    const float4 crop = eye == 0 ? CropUvLeft : CropUvRight;
    const uint debugMode = (uint)Options.y;
    const float weight = debugMode == 0u ? SeamFocusWeight(eyeUv, crop) : FocusWeight(eyeUv, crop);

    if (debugMode == 3) {
        const float3 contextColor = eye == 0 ? float3(0.8, 0.1, 0.1) : float3(0.1, 0.8, 0.1);
        const float3 focusColor = eye == 0 ? float3(0.1, 0.2, 1.0) : float3(1.0, 0.8, 0.1);
        return float4(lerp(contextColor, focusColor, weight), 1.0);
    }

    // The context sample is unnecessary under opaque focus. In the default
    // 50% crop this skips a texture fetch for most focused pixels, including
    // pixels using the fused Glamarye filter. Keep diagnostics exact.
    if (debugMode == 1)
        return ReadContext(eye, contextSource, contextRect, eyeUv);
    if (weight <= 0.0) {
        if (debugMode == 2) return float4(0.04, 0.04, 0.04, 1.0);
        return MatchContext(eye, eyeUv, crop, ReadContext(eye, contextSource, contextRect, eyeUv));
    }

    const float2 focusUv = (eyeUv - crop.xy) / (crop.zw - crop.xy);
    // Share the same source extent across center and all six sharpening taps.
    const float2 focusSourceSize = SourceSize(2u + eye);
    float4 focus = ReadSource(2u + eye, AtlasUvKnownSize(focusSourceSize, focusRect, focusUv));
    const float eyeStrength = eye == 0u ? SharpenEye.x : SharpenEye.y;
    const float eyeMaxChange = eye == 0u ? SharpenEye.z : SharpenEye.w;
    [branch] if (eyeStrength > 0.0) {
        const float2 tapScale = 1.0 / (float2(EyeAndAtlas.xy) * (crop.zw - crop.xy));
        focus.rgb = GlamSharpenFocus(2u + eye, focusRect, focusUv, tapScale, focus.rgb, eyeStrength, eyeMaxChange, focusSourceSize);
    }
    if (debugMode == 0u) focus.rgb = CorrectFocusColor(focus.rgb, focusUv);
    float4 output = focus;
    [branch] if (debugMode != 2 && weight < 1.0) {
        // B38: preserve B27's original uncorrected context within most of the
        // inward feather. B37's corrected context remains untouched outside.
        const float4 rawContext = ReadContext(eye, contextSource, contextRect, eyeUv);
        float4 context = MatchContext(eye, eyeUv, crop, rawContext);
        [branch] if (Seam.x > 2.5 && SeamLocal.w > 0.5) {
            const float2 insidePx = min(eyeUv - crop.xy, crop.zw - eyeUv) * float2(EyeAndAtlas.xy);
            const float distance = max(min(insidePx.x, insidePx.y), 0.0);
            const float t = saturate(distance / max(SeamLocal.z, 1.0));
            const float anchor = 1.0 - t*t*(3.0 - 2.0*t);
            context = lerp(rawContext, context, anchor);
        }
        output = lerp(context, focus, weight);
    }
    if (Options.w > 0.5) {
        const float2 edgePx = min(eyeUv - crop.xy, crop.zw - eyeUv) * float2(EyeAndAtlas.xy);
        if (min(edgePx.x, edgePx.y) < 1.0) output.rgb = float3(1.0, 0.75, 0.0);
    }
    return output;
}

// Keep one initialized return path: legacy FXC rejects nested early diagnostic
// returns as potentially uninitialized output under /WX.
float4 CompositePixel(VertexOut input) {
    float4 color = float4(0.0, 0.0, 0.0, 1.0);
    [branch] if (DepthOptions.y != 0u) {
        if (DepthOptions.z == 0u) {
            const uint checker = ((uint(input.position.x) / 8u) + (uint(input.position.y) / 8u)) & 1u;
            color = checker != 0u ? float4(1, 0, 1, 1) : float4(0, 0, 0, 1);
        } else {
            const uint eye = min((uint)input.position.x / EyeAndAtlas.x, 1u);
            const float2 eyeUv = float2(input.position.x - eye * EyeAndAtlas.x,
                input.position.y) / float2(EyeAndAtlas.xy);
            const float v = pow(PeripheryDepthAt(ContextUv(eye, eyeUv)), 0.25);
            color = float4(v, v, v, 1);
        }
    } else {
        color = ScenePixel(input);
    }
    return color;
}

// Preserve the baseline copy's color encoding when a typed UNORM atlas is
// drawn into an sRGB runtime texture. The RTV performs the inverse encoding.
float4 PSMain(VertexOut input) : SV_TARGET0 {
    float4 color = CompositePixel(input);
    if (Options.z > 0.5) {
        const float3 low = color.rgb / 12.92;
        const float3 high = pow(max((color.rgb + 0.055) / 1.055, 0.0), 2.4);
        color.rgb = float3(color.r <= 0.04045 ? low.r : high.r,
                           color.g <= 0.04045 ? low.g : high.g,
                           color.b <= 0.04045 ? low.b : high.b);
    }
    return color;
}

#ifdef SEAM_COMPUTE
RWStructuredBuffer<float4> SeamOutput : register(u0);
RWStructuredBuffer<float4> EdgeState : register(u1); // shared on one pinned submission queue
groupshared float4 SeamFocusSums[128];
groupshared float4 SeamContextSums[128];

// Four low-frequency patch samples, solely for analysis: displayed focus
// samples are never blurred. Use the actual same context homography/depth
// warp as composition and reject out-of-bounds/disocclusion-filled samples.
bool SeamPatch(uint eye, float2 center, float4 crop, out float3 focus, out float3 context) {
    focus = 0.0; context = 0.0;
    const uint4 cr = eye == 0u ? ContextLeft : ContextRight;
    const uint4 fr = eye == 0u ? FocusLeft : FocusRight;
    const uint cs = eye == 0u ? ContextSource.x : ContextSource.y;
    const float2 patch = 1.25 / max(float2(cr.zw), 1.0);
    float loF = 1.0e10, hiF = -1.0e10, loC = 1.0e10, hiC = -1.0e10;
    bool valid = true; // CSSeam exits uniformly before probes on invalid alignment.
    [unroll] for (uint i = 0u; i < 4u; ++i) {
        const float2 p = center + float2((i & 1u) == 0u ? -1.0 : 1.0, (i & 2u) == 0u ? -1.0 : 1.0) * patch;
        float fill = 0.0;
        const float2 cu = WarpContextUv(eye, ContextUv(eye, p), fill);
        valid = valid && all(p > crop.xy) && all(p < crop.zw) && all(cu >= 0.0) && all(cu <= 1.0) && fill == 0.0;
        const float2 focusUv = (p - crop.xy) / (crop.zw - crop.xy);
        const float3 f = CorrectFocusColor(ReadSource(2u + eye, AtlasUv(2u + eye, fr, focusUv)).rgb, focusUv);
        const float3 c = ReadSource(cs, AtlasUv(cs, cr, cu)).rgb;
        focus += f; context += c;
        const float lf = dot(f, GlamLuma), lc = dot(c, GlamLuma);
        loF = min(loF, lf); hiF = max(hiF, lf);
        loC = min(loC, lc); hiC = max(hiC, lc);
    }
    focus *= 0.25; context *= 0.25;
    const float lf = dot(focus, GlamLuma), lc = dot(context, GlamLuma);
    // Exclude black, clipped highlights and unstable/high-gradient boundaries.
    // Broad luminance outliers cannot be repaired by a bounded color gain.
    valid = valid && min(lf, lc) > 0.03 && max(lf, lc) < 0.95 &&
        max(hiF - loF, hiC - loC) < 0.25 && lf > 0.5 * lc && lf < 2.0 * lc;
    return valid;
}

// One lane owns each knot, no inter-lane history dependencies. A shared UAV
// barrier before/after dispatch orders updates in actual queue execution order.
void UpdateEdgeV2(uint eye,uint lane) {
    if (lane >= 32u) return;
    const float4 crop=eye==0u ? CropUvLeft : CropUvRight;
    const uint side=lane/8u;
    const float t=float(lane%8u)/8.0;
    float2 p=side==0u ? float2(lerp(crop.x,crop.z,t),crop.y) :
             side==1u ? float2(crop.z,lerp(crop.y,crop.w,t)) :
             side==2u ? float2(lerp(crop.z,crop.x,t),crop.w) :
                        float2(crop.x,lerp(crop.w,crop.y,t));
    uint unusedSide=0u; float unusedAlong=0.0;
    p=EdgeAnchor(p,crop,unusedSide,unusedAlong);
    float3 target;
    const bool valid=Seam.x>4.5 ? AmbientEdgeDifference(eye,p,side,crop,target) :
                                  EdgeDifference(eye,p,side,crop,target);
    const uint h=(eye*32u+lane)*3u;
    float3 stable=valid ? target : 0.0;
    bool tracking=false;
    [branch] if (EdgeHistory.z != 0u) {
        const uint4 stamp=asuint(EdgeState[h+2u]);
        const uint elapsed=EdgeHistory.y-stamp.y;
        const float4 previousCrop=EdgeState[h+1u];
        // Spatial pooling covers a broad neighborhood. Retain ambient history
        // through small gaze motion rather than flashing to a new raw estimate.
        // B37 exact-border modes keep the original 0.5px provenance reset.
        const float4 cropDelta=abs(previousCrop-crop)*float4(EyeAndAtlas.xy,EyeAndAtlas.xy);
        const float motionTolerance=Seam.x>4.5 ? max(1.0,min(FocusProfile.z*0.25,12.0)) : 0.5;
        const bool reset=stamp.w!=0x35ed6e01u || stamp.x!=EdgeHistory.x || elapsed>250u ||
            any(cropDelta>motionTolerance);
        [branch] if (!reset && valid) {
            const float4 old=EdgeState[h];
            stable=old.rgb;
            const float3 delta=target-stable;
            const float error=max(abs(delta.x),max(abs(delta.y),abs(delta.z)));
            tracking=old.a>0.5 ? error>EdgeV2.w : error>2.0*EdgeV2.w;
            if (tracking) {
                const float seconds=float(elapsed)*0.001;
                float3 step=delta;
                // Time-domain averaging of spatially pooled RGB residuals.
                // Keep B37's rate limit too: no abrupt broad-field jumps.
                [branch] if (Seam.x>4.5)
                    step*=float(elapsed)/(float(max(EdgeHistory.w,1u))+float(elapsed));
                stable+=clamp(step,-EdgeV2.z*seconds,EdgeV2.z*seconds);
            }
        }
        // Invalid geometry resets immediately; no stale-world/occlusion hold.
        EdgeState[h]=float4(stable,tracking ? 1.0 : 0.0);
        EdgeState[h+1u]=crop;
        EdgeState[h+2u]=asfloat(uint4(EdgeHistory.x,EdgeHistory.y,0u,valid ? 0x35ed6e01u : 0u));
    }
    const uint outIndex=18u+eye*64u+lane*2u;
    SeamOutput[outIndex]=float4(valid ? target : 0.0,valid ? 1.0 : 0.0);
    SeamOutput[outIndex+1u]=float4(stable,valid ? 1.0 : 0.0);
}

// B40: 128 spatial sampling locations (4 per knot x 32) but only 32
// persistent temporal correction knots per eye. Group values use per-channel
// trimmed means, so a single bright/dark/color outlier cannot dominate.
void UpdateEdgeB40(uint eye, uint lane) {
    if (lane >= 32u) return;
    const float4 crop=eye==0u ? CropUvLeft : CropUvRight;
    const uint side=lane/8u;
    const float segment=float(lane%8u);
    float3 q0=0.0, q1=0.0, q2=0.0, q3=0.0;
    uint count=0u;
    [loop] for (uint sub=0u;sub<4u;++sub) {
        // Four sub-anchors cover a substantial part of each of the 32
        // interpolated boundary segments, with no temporal sampling jitter.
        const float t=saturate((segment+(float(sub)-1.5)*0.25)/8.0);
        float2 p=side==0u ? float2(lerp(crop.x,crop.z,t),crop.y) :
                 side==1u ? float2(crop.z,lerp(crop.y,crop.w,t)) :
                 side==2u ? float2(lerp(crop.z,crop.x,t),crop.w) :
                            float2(crop.x,lerp(crop.w,crop.y,t));
        uint anchorSide=0u; float anchorAlong=0.0;
        p=EdgeAnchor(p,crop,anchorSide,anchorAlong);
        float3 sampleDelta=0.0;
        [branch] if (AmbientEdgeDifference(eye,p,side,crop,sampleDelta)) {
            if (count==0u) q0=sampleDelta;
            else if (count==1u) q1=sampleDelta;
            else if (count==2u) q2=sampleDelta;
            else q3=sampleDelta;
            ++count;
        }
    }
    // Group-of-four trimmed mean, or a componentwise median with three
    // usable sub-anchors. This rejects isolated RGB outliers, not just luma.
    const bool valid=count>=2u;
    float3 target=0.0;
    if (count==4u) {
        target=0.5*(q0+q1+q2+q3-
            min(min(q0,q1),min(q2,q3))-max(max(q0,q1),max(q2,q3)));
    } else if (count==3u) {
        target=q0+q1+q2-min(q0,min(q1,q2))-max(q0,max(q1,q2));
    } else if (count==2u) {
        target=0.5*(q0+q1);
    }

    const uint h=(eye*32u+lane)*3u;
    float3 stable=valid ? target : 0.0;
    if (EdgeHistory.z!=0u) {
        const uint4 stamp=asuint(EdgeState[h+2u]);
        const bool initialized=stamp.w==0x40b04001u;
        // Only allocation/startup initializes history. Motion, scene epochs,
        // crop geometry, invalid samples and long frame gaps NEVER reset it.
        stable=initialized ? EdgeState[h].rgb : float3(0.0,0.0,0.0);
        const uint elapsed=initialized ? EdgeHistory.y-stamp.y : 16u;
        const uint dt=min(elapsed,50u); // a stalled frame must not jump
        if (valid && dt>0u) {
            const float tau=float(max(EdgeHistory.w,50u));
            const float alpha=float(dt)/(tau+float(dt));
            const float limit=(100.0/tau)*(float(dt)*0.001);
            // Single time-domain EMA with bounded per-frame rate. A preset
            // controls both response and slew; no secondary temporal buffer.
            stable+=clamp((target-stable)*alpha,float3(-limit,-limit,-limit),float3(limit,limit,limit));
        }
        EdgeState[h]=float4(stable,1.0);
        EdgeState[h+1u]=crop; // diagnostic only; NEVER used to invalidate
        EdgeState[h+2u]=asfloat(uint4(EdgeHistory.x,EdgeHistory.y,0u,0x40b04001u));
    }
    const uint outIndex=18u+eye*64u+lane*2u;
    SeamOutput[outIndex]=float4(target,valid ? 1.0 : 0.0);
    // Hold and DISPLAY the previous correction even with invalid new
    // geometry; no instantaneous raw target can bypass the temporal path.
    SeamOutput[outIndex+1u]=float4(stable,1.0);
}

[numthreads(128, 1, 1)]
// Groups contain eight independent 16-sample boundary segments. Reuse their
// reductions for a global estimate instead of sampling the image again.
void CSSeam(uint3 group : SV_GroupID, uint lane : SV_GroupIndex) {
    const uint eye = group.x;
    [branch] if (Seam.x > 5.5) { UpdateEdgeB40(eye,lane); return; }
    [branch] if (Seam.x > 2.5) { UpdateEdgeV2(eye,lane); return; }
    // Alignment usability is uniform across both dispatch groups. All lanes
    // return together, before any groupshared barrier or texture/depth probe.
    // Initialize every record, including after an earlier valid frame.
    [branch] if (SeamOptions.w <= 0.5) {
        if (lane < 9u) SeamOutput[eye * 9u + lane] = float4(1.0, 1.0, 1.0, 0.0);
        return;
    }
    const float4 crop = eye == 0u ? CropUvLeft : CropUvRight;
    const uint side = lane / 32u;
    const float along = (float(lane % 32u) + 0.5) / 32.0;
    // Inset far enough to fit a patch at the peripheral sampling footprint.
    const uint4 cr = eye == 0u ? ContextLeft : ContextRight;
    const float2 inset = min(2.5 / max(float2(cr.zw), 1.0) + 8.0 / float2(EyeAndAtlas.xy),
                             (crop.zw - crop.xy) * 0.3);
    float2 p = lerp(crop.xy + inset, crop.zw - inset, along);
    if (side == 0u) p.y = crop.y + inset.y;
    else if (side == 1u) p.x = crop.z - inset.x;
    else if (side == 2u) p.y = crop.w - inset.y;
    else p.x = crop.x + inset.x;
    float3 f, c;
    const bool valid = SeamPatch(eye, p, crop, f, c);
    SeamFocusSums[lane] = valid ? float4(f, 1.0) : 0.0;
    SeamContextSums[lane] = valid ? float4(c, 1.0) : 0.0;
    GroupMemoryBarrierWithGroupSync();
    [unroll] for (uint stride = 8u; stride > 0u; stride >>= 1u) {
        if ((lane % 16u) < stride) {
            SeamFocusSums[lane] += SeamFocusSums[lane + stride];
            SeamContextSums[lane] += SeamContextSums[lane + stride];
        }
        GroupMemoryBarrierWithGroupSync();
    }
    if ((lane % 16u) == 0u) {
        const float3 sf = SeamFocusSums[lane].rgb, sc = SeamContextSums[lane].rgb;
        const float count = SeamFocusSums[lane].a;
        const float lumGain = dot(sf, GlamLuma) / max(dot(sc, GlamLuma), 1.0e-5);
        const float3 rgbGain = float3(sc.r > count * 0.03 ? sf.r / max(sc.r, 1.0e-5) : lumGain,
                                     sc.g > count * 0.03 ? sf.g / max(sc.g, 1.0e-5) : lumGain,
                                     sc.b > count * 0.03 ? sf.b / max(sc.b, 1.0e-5) : lumGain);
        const float3 gain = clamp(lerp(lumGain.xxx, rgbGain, SeamOptions.x), 1.0 - Seam.z, 1.0 + Seam.z);
        SeamOutput[eye * 9u + 1u + lane / 16u] = float4(count > 4.0 ? gain : float3(1.0, 1.0, 1.0), saturate((count - 4.0) / 8.0));
    }
    GroupMemoryBarrierWithGroupSync();
    if (lane < 8u) {
        SeamFocusSums[lane] = SeamFocusSums[lane * 16u];
        SeamContextSums[lane] = SeamContextSums[lane * 16u];
    }
    GroupMemoryBarrierWithGroupSync();
    [unroll] for (uint reduceStride = 4u; reduceStride > 0u; reduceStride >>= 1u) {
        if (lane < reduceStride) {
            SeamFocusSums[lane] += SeamFocusSums[lane + reduceStride];
            SeamContextSums[lane] += SeamContextSums[lane + reduceStride];
        }
        GroupMemoryBarrierWithGroupSync();
    }
    if (lane == 0u) {
        const float3 sf = SeamFocusSums[0].rgb, sc = SeamContextSums[0].rgb;
        const float count = SeamFocusSums[0].a;
        const float lumGain = dot(sf, GlamLuma) / max(dot(sc, GlamLuma), 1.0e-5);
        const float3 rgbGain = float3(sc.r > count * 0.03 ? sf.r / max(sc.r, 1.0e-5) : lumGain,
                                     sc.g > count * 0.03 ? sf.g / max(sc.g, 1.0e-5) : lumGain,
                                     sc.b > count * 0.03 ? sf.b / max(sc.b, 1.0e-5) : lumGain);
        const float3 gain = clamp(lerp(lumGain.xxx, rgbGain, SeamOptions.x), 1.0 - Seam.z, 1.0 + Seam.z);
        const float confidence = saturate((count - 8.0) / 40.0);
        SeamOutput[eye * 9u] = float4(count > 8.0 ? gain : float3(1.0, 1.0, 1.0), confidence);
    }
}
#endif

```
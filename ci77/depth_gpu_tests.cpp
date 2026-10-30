// Exercise the actual production PSStabilizeDepth shader on D3D11 WARP.
#define NOMINMAX
#include <d3d11.h>
#include <d3dcompiler.h>
#include <d3d11shader.h>
#include <wrl/client.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace {
constexpr UINT Width = 32;
constexpr UINT Height = 16;
constexpr size_t PixelCount = size_t(Width) * Height;
constexpr size_t ConstantBytes = 512;

void need(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

void hr(HRESULT result, const char* operation) {
    need(SUCCEEDED(result), operation);
}

ComPtr<ID3DBlob> compile(const std::string& source, const char* file,
                         const char* entry, const char* target) {
    ComPtr<ID3DBlob> bytecode, errors;
    const HRESULT result = D3DCompile(source.data(), source.size(), file, nullptr,
        D3D_COMPILE_STANDARD_FILE_INCLUDE, entry, target,
        D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_OPTIMIZATION_LEVEL3,
        0, &bytecode, &errors);
    if (FAILED(result) && errors)
        std::cerr << static_cast<const char*>(errors->GetBufferPointer()) << '\n';
    hr(result, "compile production stabilization shader");
    return bytecode;
}

using Matrix = std::array<float, 16>;

Matrix identity_matrix() {
    return {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
}

// Maps eye (x,y,z,1) to clip (x,y,1,z), giving raw device Z = 1/z.
Matrix reciprocal_projection() {
    return {1,0,0,0, 0,1,0,0, 0,0,0,1, 0,0,1,0};
}

struct Parameters {
    std::array<float, 4> active_rect{0.f, 0.f, float(Width), float(Height)};
    std::array<float, 4> previous_rect{0.f, 0.f, float(Width), float(Height)};
    std::array<float, 4> current_range_jitter{0.f, 1.f, 0.f, 0.f};
    std::array<float, 4> previous_range_weight{0.f, 1.f, 0.f, 0.f};
    std::array<float, 4> edge_tolerances{0.01f, 0.f, 0.5f, 0.f};
    Matrix current_eye_from_clip{reciprocal_projection()};
    Matrix previous_clip_from_current_eye{reciprocal_projection()};
    Matrix previous_eye_from_clip{reciprocal_projection()};
    Matrix current_eye_from_previous_eye{identity_matrix()};
    Matrix current_clip_from_current_eye{reciprocal_projection()};
    std::array<float, 4> current_projection{0.f, 1.f, 1.f, 0.f};
    std::array<float, 4> previous_projection{0.f, 1.f, 1.f, 0.f};
};

class StabilizeFixture final {
    ComPtr<ID3D11Device> device_;
    ComPtr<ID3D11DeviceContext> context_;
    ComPtr<ID3D11PixelShader> pixel_shader_;
    ComPtr<ID3D11VertexShader> vertex_shader_;
    ComPtr<ID3D11Buffer> constants_;
    ComPtr<ID3D11Texture2D> current_, previous_, output_, readback_;
    ComPtr<ID3D11ShaderResourceView> current_srv_, previous_srv_;
    ComPtr<ID3D11RenderTargetView> output_rtv_;
    ComPtr<ID3D11RasterizerState> rasterizer_;
    ComPtr<ID3D11ShaderReflection> reflection_;
    ID3D11ShaderReflectionConstantBuffer* config_{};
    std::array<unsigned char, ConstantBytes> constant_data_{};

    void set_bytes(const char* variable, const void* data, size_t bytes) {
        D3D11_SHADER_VARIABLE_DESC desc{};
        hr(config_->GetVariableByName(variable)->GetDesc(&desc), variable);
        need(size_t(desc.StartOffset) + bytes <= constant_data_.size(),
             "constant variable exceeds buffer");
        std::memcpy(constant_data_.data() + desc.StartOffset, data, bytes);
    }

    void set_vec4(const char* variable, const std::array<float, 4>& value) {
        set_bytes(variable, value.data(), sizeof(value));
    }

    void set_matrix(const char* variable, const Matrix& value) {
        set_bytes(variable, value.data(), sizeof(value));
    }

    void set_constants(const Parameters& p) {
        constant_data_.fill(0);
        set_matrix("CurrentEyeFromClip", p.current_eye_from_clip);
        set_matrix("PreviousClipFromCurrentEye", p.previous_clip_from_current_eye);
        set_matrix("PreviousEyeFromClip", p.previous_eye_from_clip);
        set_matrix("CurrentEyeFromPreviousEye", p.current_eye_from_previous_eye);
        set_matrix("CurrentClipFromCurrentEye", p.current_clip_from_current_eye);
        set_vec4("ActiveRect", p.active_rect);
        set_vec4("CurrentProjection", p.current_projection);
        set_vec4("PreviousProjection", p.previous_projection);
        set_vec4("CurrentRangeJitter", p.current_range_jitter);
        set_vec4("PreviousRangeWeight", p.previous_range_weight);
        set_vec4("EdgeTolerances", p.edge_tolerances);
        set_vec4("PreviousRect", p.previous_rect);
        context_->UpdateSubresource(constants_.Get(), 0, nullptr,
                                    constant_data_.data(), 0, 0);
    }

public:
    explicit StabilizeFixture(const std::filesystem::path& shader_path) {
        std::ifstream input(shader_path, std::ios::binary);
        need(bool(input), "production stabilization shader missing");
        const std::string source((std::istreambuf_iterator<char>(input)), {});
        const auto pixel_bytecode = compile(source, shader_path.string().c_str(),
                                            "PSStabilizeDepth", "ps_5_0");
        static constexpr char VertexSource[] = R"(
            struct VertexOut { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
            VertexOut VSMain(uint id : SV_VertexID) {
                VertexOut o;
                float2 p=float2((id<<1)&2,id&2);
                o.uv=p;
                o.pos=float4(p*float2(2,-2)+float2(-1,1),0,1);
                return o;
            })";
        const auto vertex_bytecode = compile(VertexSource, "WARP probe", "VSMain", "vs_5_0");

        D3D_FEATURE_LEVEL feature_level{};
        hr(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION,
            &device_, &feature_level, &context_), "create D3D11 WARP device");
        (void)feature_level;
        hr(device_->CreatePixelShader(pixel_bytecode->GetBufferPointer(),
            pixel_bytecode->GetBufferSize(), nullptr, &pixel_shader_), "create stabilization PS");
        hr(device_->CreateVertexShader(vertex_bytecode->GetBufferPointer(),
            vertex_bytecode->GetBufferSize(), nullptr, &vertex_shader_), "create fullscreen VS");

        hr(D3DReflect(pixel_bytecode->GetBufferPointer(), pixel_bytecode->GetBufferSize(),
            IID_PPV_ARGS(&reflection_)), "reflect stabilization PS");
        config_ = reflection_->GetConstantBufferByName("StabilizeDepthConfig");
        D3D11_SHADER_BUFFER_DESC config_desc{};
        hr(config_->GetDesc(&config_desc), "reflect stabilization constants");
        need(config_desc.Size == 432, "stabilization b0 ABI is not 432 bytes");

        D3D11_BUFFER_DESC buffer_desc{};
        buffer_desc.ByteWidth = UINT(ConstantBytes);
        buffer_desc.Usage = D3D11_USAGE_DEFAULT;
        buffer_desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        hr(device_->CreateBuffer(&buffer_desc, nullptr, &constants_), "create b0");

        D3D11_TEXTURE2D_DESC texture_desc{};
        texture_desc.Width = Width;
        texture_desc.Height = Height;
        texture_desc.MipLevels = 1;
        texture_desc.ArraySize = 1;
        texture_desc.Format = DXGI_FORMAT_R32_FLOAT;
        texture_desc.SampleDesc.Count = 1;
        texture_desc.Usage = D3D11_USAGE_DEFAULT;
        texture_desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        hr(device_->CreateTexture2D(&texture_desc, nullptr, &current_), "create current depth");
        hr(device_->CreateTexture2D(&texture_desc, nullptr, &previous_), "create history depth");
        hr(device_->CreateShaderResourceView(current_.Get(), nullptr, &current_srv_), "create current SRV");
        hr(device_->CreateShaderResourceView(previous_.Get(), nullptr, &previous_srv_), "create history SRV");

        texture_desc.BindFlags = D3D11_BIND_RENDER_TARGET;
        hr(device_->CreateTexture2D(&texture_desc, nullptr, &output_), "create output depth");
        hr(device_->CreateRenderTargetView(output_.Get(), nullptr, &output_rtv_), "create output RTV");
        texture_desc.Usage = D3D11_USAGE_STAGING;
        texture_desc.BindFlags = 0;
        texture_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        hr(device_->CreateTexture2D(&texture_desc, nullptr, &readback_), "create readback texture");

        D3D11_RASTERIZER_DESC raster_desc{};
        raster_desc.FillMode = D3D11_FILL_SOLID;
        raster_desc.CullMode = D3D11_CULL_NONE;
        raster_desc.DepthClipEnable = TRUE;
        hr(device_->CreateRasterizerState(&raster_desc, &rasterizer_), "create rasterizer");
    }

    std::vector<float> render(const std::vector<float>& current,
                              const std::vector<float>& previous,
                              const Parameters& parameters) {
        need(current.size() == PixelCount && previous.size() == PixelCount,
             "incorrect input plane size");
        set_constants(parameters);
        context_->UpdateSubresource(current_.Get(), 0, nullptr, current.data(),
                                    Width * UINT(sizeof(float)), 0);
        context_->UpdateSubresource(previous_.Get(), 0, nullptr, previous.data(),
                                    Width * UINT(sizeof(float)), 0);

        ID3D11RenderTargetView* rtv = output_rtv_.Get();
        context_->OMSetRenderTargets(1, &rtv, nullptr);
        const D3D11_VIEWPORT viewport{0.f, 0.f, float(Width), float(Height), 0.f, 1.f};
        context_->RSSetViewports(1, &viewport);
        context_->RSSetState(rasterizer_.Get());
        context_->IASetInputLayout(nullptr);
        context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context_->VSSetShader(vertex_shader_.Get(), nullptr, 0);
        context_->PSSetShader(pixel_shader_.Get(), nullptr, 0);
        ID3D11Buffer* cb = constants_.Get();
        context_->PSSetConstantBuffers(0, 1, &cb);
        ID3D11ShaderResourceView* srvs[]{current_srv_.Get(), previous_srv_.Get()};
        context_->PSSetShaderResources(0, 2, srvs);
        context_->Draw(3, 0);
        context_->CopyResource(readback_.Get(), output_.Get());

        D3D11_MAPPED_SUBRESOURCE mapped{};
        hr(context_->Map(readback_.Get(), 0, D3D11_MAP_READ, 0, &mapped), "map output depth");
        std::vector<float> result(PixelCount);
        for (UINT y = 0; y < Height; ++y) {
            const auto* row = static_cast<const unsigned char*>(mapped.pData) + size_t(y) * mapped.RowPitch;
            std::memcpy(result.data() + size_t(y) * Width, row, size_t(Width) * sizeof(float));
        }
        context_->Unmap(readback_.Get(), 0);
        ID3D11ShaderResourceView* empty[]{nullptr, nullptr};
        context_->PSSetShaderResources(0, 2, empty);
        context_->OMSetRenderTargets(0, nullptr, nullptr);
        return result;
    }
};

float plane_z(float ndc_x, float ndc_y) {
    // Eye-space plane z = 8 + 0.04*x + 0.025*y, intersected by a pinhole ray.
    return 8.f / (1.f - 0.04f * ndc_x - 0.025f * ndc_y);
}

std::vector<float> jittered_plane(float jitter_x, float jitter_y,
                                  const std::array<float, 4>& rect) {
    std::vector<float> raw(PixelCount, 0.25f);
    const float x0 = rect[0], y0 = rect[1], w = rect[2], h = rect[3];
    for (UINT y = 0; y < Height; ++y) {
        for (UINT x = 0; x < Width; ++x) {
            const float u = (float(x) + 0.5f - jitter_x - x0) / w;
            const float v = (float(y) + 0.5f - jitter_y - y0) / h;
            const float z = plane_z(2.f * u - 1.f, 1.f - 2.f * v);
            raw[size_t(y) * Width + x] = 1.f / z;
        }
    }
    return raw;
}

std::vector<float> constant_depth(float z) {
    return std::vector<float>(PixelCount, 1.f / z);
}

float at(const std::vector<float>& image, UINT x, UINT y) {
    return image[size_t(y) * Width + x];
}

float z_from_raw(float raw) { return 1.f / raw; }

void test_jittered_sloped_plane(StabilizeFixture& fixture) {
    Parameters p;
    p.active_rect = {2.f, 1.f, 28.f, 14.f};
    p.edge_tolerances = {0.5f, 0.f, 0.5f, 0.f};
    p.current_range_jitter[2] = .25f;
    p.current_range_jitter[3] = -.25f;
    const auto positive = fixture.render(jittered_plane(.25f, -.25f, p.active_rect),
                                         constant_depth(100.f), p);
    p.current_range_jitter[2] = -.25f;
    p.current_range_jitter[3] = .25f;
    const auto negative = fixture.render(jittered_plane(-.25f, .25f, p.active_rect),
                                         constant_depth(100.f), p);
    float max_phase_error = 0.f;
    float max_analytic_error = 0.f;
    for (UINT y = 3; y < 13; ++y) {
        for (UINT x = 4; x < 28; ++x) {
            const float u = (float(x) + 0.5f - p.active_rect[0]) / p.active_rect[2];
            const float v = (float(y) + 0.5f - p.active_rect[1]) / p.active_rect[3];
            const float expected = 1.f / plane_z(2.f * u - 1.f, 1.f - 2.f * v);
            const float a = at(positive, x, y), b = at(negative, x, y);
            max_phase_error = (std::max)(max_phase_error, std::abs(a - b));
            max_analytic_error = (std::max)(max_analytic_error, (std::max)(std::abs(a - expected), std::abs(b - expected)));
        }
    }
    need(max_phase_error < 2.e-5f, "opposite jitter phases did not align the sloped plane");
    need(max_analytic_error < 2.e-4f, "jittered plane departed from analytic canonical depth");
    // Full-allocation output must retain raw source depth outside the active rect.
    need(at(positive, 0, 0) == at(jittered_plane(.25f, -.25f, p.active_rect), 0, 0),
         "inactive allocation border was not preserved");
}

void test_step_has_no_fictional_intermediate_z(StabilizeFixture& fixture) {
    Parameters p;
    p.current_range_jitter[2] = .5f;
    p.edge_tolerances = {.01f, 0.f, .5f, 0.f};
    std::vector<float> step(PixelCount);
    for (UINT y = 0; y < Height; ++y)
        for (UINT x = 0; x < Width; ++x)
            step[size_t(y) * Width + x] = x < 16 ? .5f : .1f; // Z=2 / Z=10
    const auto result = fixture.render(step, constant_depth(100.f), p);
    need(std::abs(at(result, 15, 8) - .5f) < 1.e-6f,
         "equal-support foreground/background step did not prefer nearer surface");
    need(std::abs(at(result, 16, 8) - .1f) < 1.e-6f,
         "background side of depth step changed");
    for (const float raw : result)
        need(std::abs(raw - .5f) < 1.e-6f || std::abs(raw - .1f) < 1.e-6f,
             "spatial filtering invented an intermediate device depth");
}

void test_temporal_weight_reduces_same_surface_noise(StabilizeFixture& fixture) {
    Parameters p;
    p.previous_range_weight[2] = .5f;
    p.previous_range_weight[3] = 1.f;
    p.edge_tolerances = {.5f, 0.f, .5f, 0.f};
    const auto current = constant_depth(10.2f);
    const auto previous = constant_depth(10.f);
    const auto result = fixture.render(current, previous, p);
    const float z = z_from_raw(at(result, 12, 8));
    need(z < 10.2f && z > 10.f, "same-surface temporal history was not blended");
    need(std::abs(z - 10.1f) < .01f, "temporal weight did not reduce same-surface depth noise");

    // The production near-field cutoff should disable history even when the
    // previous surface is otherwise compatible and would blend without it.
    Parameters near_parameters;
    near_parameters.previous_range_weight[2] = .9f;
    near_parameters.previous_range_weight[3] = 1.f;
    near_parameters.edge_tolerances = {1.f, 0.f, .5f, 80.f};
    const auto near_current = constant_depth(50.f);
    const auto near_previous = constant_depth(49.5f);
    const auto near_result = fixture.render(near_current, near_previous, near_parameters);
    need(std::abs(at(near_result, 12, 8) - at(near_current, 12, 8)) < 1.e-6f,
         "near-field cutoff did not bypass otherwise compatible temporal history");
}

void test_new_foreground_rejects_old_background(StabilizeFixture& fixture) {
    Parameters p;
    p.previous_range_weight[2] = .9f;
    p.previous_range_weight[3] = 1.f;
    p.edge_tolerances = {.05f, 0.f, .5f, 0.f};
    const auto result = fixture.render(constant_depth(2.f), constant_depth(10.f), p);
    need(std::abs(at(result, 12, 8) - .5f) < 1.e-6f,
         "old background history contaminated a new foreground depth");
}

void test_history_holds_supported_foreground_endpoint_at_edge(StabilizeFixture& fixture) {
    Parameters p;
    p.current_range_jitter[2] = .6f; // source footprint: 0.4 foreground, 0.6 background
    p.edge_tolerances = {5.f, 0.f, 1.5f, 80.f}; // centimeter tolerance and production near cutoff
    const float backgroundRaw=1.f/1000.f,foregroundRaw=1.f/500.f;
    std::vector<float> current(PixelCount, backgroundRaw); // background Z=1000cm
    for (UINT y = 0; y < Height; ++y)
        current[size_t(y) * Width + 15] = foregroundRaw; // foreground Z=500cm
    const auto previous_foreground = constant_depth(500.f);

    p.previous_range_weight[2] = .9f;
    p.previous_range_weight[3] = 0.f;
    const auto spatial_only = fixture.render(current, previous_foreground, p);
    need(std::abs(at(spatial_only, 15, 8) - backgroundRaw) < 1.e-6f,
         "current spatial footprint did not select the 0.6-support background");

    p.previous_range_weight[3] = 1.f;
    const auto retained = fixture.render(current, previous_foreground, p);
    need(std::abs(at(retained, 15, 8) - foregroundRaw) < 1.e-6f,
         "history did not retain the supported foreground endpoint at the edge");
    need(std::abs(at(retained, 16, 8) - backgroundRaw) < 1.e-6f,
         "history retained foreground where the current footprint has no foreground support");
}

void test_invalid_sky_support_does_not_fill_foreground(StabilizeFixture& fixture) {
    Parameters p;
    p.current_range_jitter[2] = .1f; // 0.9 invalid/sky, 0.1 valid foreground
    p.edge_tolerances = {.01f, 0.f, .5f, 0.f};
    std::vector<float> current(PixelCount, 0.f); // raw zero is invalid/sky for 1/Z
    for (UINT y = 0; y < Height; ++y)
        current[size_t(y) * Width + 16] = .5f;
    const auto result = fixture.render(current, constant_depth(100.f), p);
    need(std::abs(at(result, 15, 8)) < 1.e-7f,
         "low-support foreground filled a footprint dominated by invalid sky");
}

void test_camera_reprojection_tracks_motion(StabilizeFixture& fixture) {
    constexpr float translation = 3.f;
    constexpr float plane_slope = .08f;
    std::vector<float> current(PixelCount), previous(PixelCount);
    for (UINT y = 0; y < Height; ++y) {
        for (UINT x = 0; x < Width; ++x) {
            const float ndc_x = 2.f * (float(x) + .5f) / float(Width) - 1.f;
            const float z_current = 8.f / (1.f - plane_slope * ndc_x);
            const float z_previous = (8.f - plane_slope * translation) /
                                     (1.f - plane_slope * ndc_x);
            current[size_t(y) * Width + x] = 1.f / (z_current + .03f);
            previous[size_t(y) * Width + x] = 1.f / z_previous;
        }
    }
    Parameters p;
    p.previous_range_weight[2] = .75f;
    p.previous_range_weight[3] = 1.f;
    p.edge_tolerances = {.05f, 0.f, .5f, 0.f};
    p.previous_clip_from_current_eye[3] = translation; // previous eye X = current X + translation
    p.current_eye_from_previous_eye[3] = -translation;
    const auto reprojected = fixture.render(current, previous, p);

    Parameters no_camera_motion = p;
    no_camera_motion.previous_clip_from_current_eye = reciprocal_projection();
    no_camera_motion.current_eye_from_previous_eye = identity_matrix();
    const auto not_reprojected = fixture.render(current, previous, no_camera_motion);
    constexpr UINT x = 10, y = 8;
    need(std::abs(at(not_reprojected, x, y) - at(current, x, y)) < 1.e-6f,
         "misprojected history was not rejected");
    need(at(reprojected, x, y) > at(not_reprojected, x, y) + 1.e-5f,
         "camera reprojection did not find the same moving-screen surface");
}

void test_reset_bypasses_history(StabilizeFixture& fixture) {
    Parameters p;
    p.previous_range_weight[2] = .75f;
    p.previous_range_weight[3] = 0.f;
    p.edge_tolerances = {.5f, 0.f, .5f, 0.f};
    const auto current = constant_depth(10.2f);
    const auto old_history = constant_depth(10.f);
    const auto reset_result = fixture.render(current, old_history, p);
    p.previous_range_weight[3] = 1.f;
    const auto valid_history_result = fixture.render(current, old_history, p);
    need(std::abs(at(reset_result, 12, 8) - at(current, 12, 8)) < 1.e-6f,
         "history reset changed current depth");
    need(std::abs(at(valid_history_result, 12, 8) - at(reset_result, 12, 8)) > 1.e-5f,
         "reset fixture did not distinguish temporal history from current-only output");
}
} // namespace

int main(int argc, char** argv) try {
    need(argc == 2, "usage: depth_gpu_tests DuoViewDepthStabilization.hlsl");
    StabilizeFixture fixture(std::filesystem::absolute(argv[1]));
    test_jittered_sloped_plane(fixture);
    test_step_has_no_fictional_intermediate_z(fixture);
    test_temporal_weight_reduces_same_surface_noise(fixture);
    test_new_foreground_rejects_old_background(fixture);
    test_history_holds_supported_foreground_endpoint_at_edge(fixture);
    test_invalid_sky_support_does_not_fill_foreground(fixture);
    test_camera_reprojection_tracks_motion(fixture);
    test_reset_bypasses_history(fixture);
    std::cout << "PASS actual PSStabilizeDepth on D3D11 WARP: jitter, edges, temporal rejection, motion reprojection, reset\n";
    return 0;
} catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
}

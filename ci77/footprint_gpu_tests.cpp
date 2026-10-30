// D3D11 WARP regression for the production VSSurface/PSSurface pair.
// Usage: footprint_gpu_tests.exe <production shader> <production shader include dir>
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
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace {
constexpr UINT Width = 32;
constexpr UINT Height = 16;
constexpr size_t PixelCount = size_t(Width) * size_t(Height);

void need(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

void hr(HRESULT result, const char* operation) {
    need(SUCCEEDED(result), operation);
}

class IncludeRoot final : public ID3DInclude {
    std::filesystem::path root_;
public:
    explicit IncludeRoot(std::filesystem::path root) : root_(std::move(root)) {}

    HRESULT __stdcall Open(D3D_INCLUDE_TYPE, LPCSTR file_name, LPCVOID,
                           LPCVOID* data, UINT* bytes) override {
        try {
            const auto path = root_ / file_name;
            std::ifstream input(path, std::ios::binary);
            if (!input) return E_FAIL;
            const std::string contents((std::istreambuf_iterator<char>(input)), {});
            if (contents.size() > size_t(std::numeric_limits<UINT>::max())) return E_FAIL;
            auto* copy = new char[contents.size()];
            std::memcpy(copy, contents.data(), contents.size());
            *data = copy;
            *bytes = static_cast<UINT>(contents.size());
            return S_OK;
        } catch (...) {
            return E_FAIL;
        }
    }

    HRESULT __stdcall Close(LPCVOID data) override {
        delete[] static_cast<const char*>(data);
        return S_OK;
    }
};

ComPtr<ID3DBlob> compile(const std::string& source, const std::string& source_name,
                         const char* entry, const char* target, ID3DInclude* include) {
    ComPtr<ID3DBlob> bytecode, errors;
    const HRESULT result = D3DCompile(source.data(), source.size(), source_name.c_str(),
        nullptr, include, entry, target,
        D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_OPTIMIZATION_LEVEL3,
        0, &bytecode, &errors);
    if (FAILED(result) && errors)
        std::cerr << static_cast<const char*>(errors->GetBufferPointer()) << '\n';
    hr(result, entry);
    return bytecode;
}

using Matrix = std::array<float, 16>;
using Vec4 = std::array<float, 4>;
using UInt4 = std::array<UINT, 4>;

Matrix reciprocal_projection() {
    // Eye (x,y,z,1) -> clip (x,y,1,z); device depth is 1/z.
    return {1,0,0,0, 0,1,0,0, 0,0,0,1, 0,0,1,0};
}

Matrix target_projection(float horizontal_translation) {
    // P * Translate(source eye into target eye). A negative X translation
    // moves source geometry left in the target image for a target eye at +X.
    return {1,0,0,horizontal_translation,
            0,1,0,0,
            0,0,0,1,
            0,0,1,0};
}

struct Constants {
    std::array<UINT, 2> output_size{Width, Height};
    std::array<UINT, 2> atlas_size{Width, Height};
    UInt4 fovea_rect{0, 0, Width, Height};
    UInt4 periphery_rect{0, 0, Width, Height};
    Vec4 crop_uv{0.f, 0.f, 1.f, 1.f};
    float feather_fraction{};
    UINT debug_border{};
    UINT debug_view_mode{};
    float reserved{};
    std::array<UINT, 2> native_fovea_dimensions{Width, Height};
    std::array<UINT, 2> native_periphery_dimensions{Width, Height};
    std::array<UINT, 2> output_offset{};
    float sharpen_strength{};
    float sharpen_max_change{};
    float sharpen_fxaa_bias{};
    UINT sharpen_flags{};
    std::array<float, 2> right_depth_jitter_uv{};
    Vec4 right_projection{0.f, 1.f, 1.f, 0.f};
    Vec4 stereo_eye_x{1.f, 0.f, 0.f, 1.f};
    Vec4 stereo_check{0.1f, 0.f, 1.f, 0.f};
    Vec4 left_projection{0.f, 1.f, 1.f, 0.f};
    Vec4 left_depth_rect{0.f, 0.f, float(Width), float(Height)};
    Vec4 right_depth_rect{0.f, 0.f, float(Width), float(Height)};
    Vec4 depth_ranges{0.f, 1.f, 0.f, 1.f};

    Matrix source_eye_from_clip{reciprocal_projection()};
    Matrix target_clip_from_source_eye{target_projection(0.f)};
    Matrix target_full_clip_from_source_eye{target_projection(0.f)};
    Matrix target_eye_from_clip{reciprocal_projection()};
    Matrix source_clip_from_target_eye{reciprocal_projection()};
    UInt4 mesh_config{Width, Height, 1u, 33u}; // left source; target depth; stable target check
    Vec4 mesh_edge{0.1f, 0.f, 0.1f, 2000.f};
    Vec4 mesh_visibility{0.1f, 0.f, 1.f, 0.f}; // absolute, relative, clip C, clip D
    Vec4 mesh_jitter{};
    Vec4 mesh_quality{0.1f, 0.f, 1.f, 0.f};
};

class ConstantWriter final {
    ID3D11ShaderReflection* reflection_{};
    ID3D11ShaderReflectionConstantBuffer* buffer_{};
    std::vector<uint8_t> bytes_;
public:
    ConstantWriter() = default;

    void initialize(ID3D11ShaderReflection* reflection, const char* buffer_name,
                    UINT expected_size) {
        reflection_ = reflection;
        buffer_ = reflection_->GetConstantBufferByName(buffer_name);
        need(buffer_ != nullptr, "shader constant buffer missing");
        D3D11_SHADER_BUFFER_DESC desc{};
        hr(buffer_->GetDesc(&desc), buffer_name);
        need(desc.Size == expected_size, "unexpected shader constant-buffer ABI");
        bytes_.resize(desc.Size);
    }

    void clear() { std::fill(bytes_.begin(), bytes_.end(), uint8_t(0)); }

    template <typename T>
    void set(const char* name, const T& value) {
        D3D11_SHADER_VARIABLE_DESC desc{};
        hr(buffer_->GetVariableByName(name)->GetDesc(&desc), name);
        need(size_t(desc.StartOffset) + sizeof(T) <= bytes_.size(),
             "constant variable exceeds reflected buffer");
        std::memcpy(bytes_.data() + desc.StartOffset, &value, sizeof(T));
    }

    const std::vector<uint8_t>& bytes() const { return bytes_; }
};

struct Image {
    std::vector<std::array<float, 4>> color;
    std::vector<float> depth;
};

class SurfaceFixture final {
    ComPtr<ID3D11Device> device_;
    ComPtr<ID3D11DeviceContext> context_;
    ComPtr<ID3D11VertexShader> vertex_shader_;
    ComPtr<ID3D11PixelShader> pixel_shader_;
    ComPtr<ID3D11Buffer> b0_;
    ComPtr<ID3D11Buffer> b1_;
    ComPtr<ID3D11Texture2D> source_color_;
    ComPtr<ID3D11Texture2D> left_depth_;
    ComPtr<ID3D11Texture2D> right_depth_;
    ComPtr<ID3D11Texture2D> output_;
    ComPtr<ID3D11Texture2D> output_depth_;
    ComPtr<ID3D11Texture2D> color_readback_;
    ComPtr<ID3D11Texture2D> depth_readback_;
    ComPtr<ID3D11ShaderResourceView> source_srv_;
    ComPtr<ID3D11ShaderResourceView> left_depth_srv_;
    ComPtr<ID3D11ShaderResourceView> right_depth_srv_;
    ComPtr<ID3D11RenderTargetView> output_rtv_;
    ComPtr<ID3D11DepthStencilView> output_dsv_;
    ComPtr<ID3D11SamplerState> sampler_;
    ComPtr<ID3D11RasterizerState> rasterizer_;
    ComPtr<ID3D11DepthStencilState> depth_state_;
    ComPtr<ID3D11ShaderReflection> pixel_reflection_;
    ConstantWriter composite_constants_;
    ConstantWriter surface_constants_;

    static D3D11_BUFFER_DESC constant_desc(UINT size) {
        D3D11_BUFFER_DESC desc{};
        desc.ByteWidth = (size + 15u) & ~15u;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        return desc;
    }

    void set_constants(const Constants& c) {
        composite_constants_.clear();
        composite_constants_.set("OutputSize", c.output_size);
        composite_constants_.set("AtlasSize", c.atlas_size);
        composite_constants_.set("FoveaRect", c.fovea_rect);
        composite_constants_.set("PeripheralRect", c.periphery_rect);
        composite_constants_.set("CropUv", c.crop_uv);
        composite_constants_.set("FeatherFraction", c.feather_fraction);
        composite_constants_.set("DebugBorder", c.debug_border);
        composite_constants_.set("DebugViewMode", c.debug_view_mode);
        composite_constants_.set("_reserved", c.reserved);
        composite_constants_.set("NativeFoveaDimensions", c.native_fovea_dimensions);
        composite_constants_.set("NativePeripheryDimensions", c.native_periphery_dimensions);
        composite_constants_.set("OutputOffset", c.output_offset);
        composite_constants_.set("SharpenStrength", c.sharpen_strength);
        composite_constants_.set("SharpenMaxChange", c.sharpen_max_change);
        composite_constants_.set("SharpenFXAABias", c.sharpen_fxaa_bias);
        composite_constants_.set("SharpenFlags", c.sharpen_flags);
        composite_constants_.set("RightDepthJitterUV", c.right_depth_jitter_uv);
        composite_constants_.set("StereoDepthZ", c.right_projection);
        composite_constants_.set("StereoEyeX", c.stereo_eye_x);
        composite_constants_.set("StereoCheck", c.stereo_check);
        composite_constants_.set("StereoLeftDepthZ", c.left_projection);
        composite_constants_.set("LeftDepthRect", c.left_depth_rect);
        composite_constants_.set("RightDepthRect", c.right_depth_rect);
        composite_constants_.set("DepthViewportRanges", c.depth_ranges);
        context_->UpdateSubresource(b0_.Get(), 0, nullptr,
                                    composite_constants_.bytes().data(), 0, 0);

        surface_constants_.clear();
        surface_constants_.set("SourceEyeFromClip", c.source_eye_from_clip);
        surface_constants_.set("TargetClipFromSourceEye", c.target_clip_from_source_eye);
        surface_constants_.set("TargetFullClipFromSourceEye", c.target_full_clip_from_source_eye);
        surface_constants_.set("TargetEyeFromClip", c.target_eye_from_clip);
        surface_constants_.set("SourceClipFromTargetEye", c.source_clip_from_target_eye);
        surface_constants_.set("MeshConfig", c.mesh_config);
        surface_constants_.set("MeshEdge", c.mesh_edge);
        surface_constants_.set("MeshVisibility", c.mesh_visibility);
        surface_constants_.set("MeshJitter", c.mesh_jitter);
        surface_constants_.set("MeshQuality", c.mesh_quality);
        context_->UpdateSubresource(b1_.Get(), 0, nullptr,
                                    surface_constants_.bytes().data(), 0, 0);
    }

    void upload_depth(ID3D11Texture2D* texture, const std::vector<float>& values) {
        context_->UpdateSubresource(texture, 0, nullptr, values.data(),
                                    Width * UINT(sizeof(float)), 0);
    }

    static D3D11_TEXTURE2D_DESC texture_desc(DXGI_FORMAT format, UINT bind_flags,
                                              D3D11_USAGE usage = D3D11_USAGE_DEFAULT,
                                              UINT cpu_access = 0) {
        D3D11_TEXTURE2D_DESC desc{};
        desc.Width = Width;
        desc.Height = Height;
        desc.MipLevels = 1;
        desc.ArraySize = 1;
        desc.Format = format;
        desc.SampleDesc.Count = 1;
        desc.Usage = usage;
        desc.BindFlags = bind_flags;
        desc.CPUAccessFlags = cpu_access;
        return desc;
    }

public:
    SurfaceFixture(const std::filesystem::path& shader_path,
                   const std::filesystem::path& include_root)
    {
        std::ifstream input(shader_path, std::ios::binary);
        need(bool(input), "production surface shader missing");
        const std::string source((std::istreambuf_iterator<char>(input)), {});
        IncludeRoot includes(include_root);
        const std::string source_name = shader_path.string();
        const auto vs = compile(source, source_name, "VSSurface", "vs_5_0", &includes);
        const auto ps = compile(source, source_name, "PSSurface", "ps_5_0", &includes);

        D3D_FEATURE_LEVEL feature_level{};
        hr(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION,
            &device_, &feature_level, &context_), "create D3D11 WARP device");
        (void)feature_level;
        hr(device_->CreateVertexShader(vs->GetBufferPointer(), vs->GetBufferSize(),
            nullptr, &vertex_shader_), "create production VSSurface");
        hr(device_->CreatePixelShader(ps->GetBufferPointer(), ps->GetBufferSize(),
            nullptr, &pixel_shader_), "create production PSSurface");
        hr(D3DReflect(ps->GetBufferPointer(), ps->GetBufferSize(),
            IID_PPV_ARGS(&pixel_reflection_)), "reflect production PSSurface");

        D3D11_SHADER_BUFFER_DESC b0_desc{}, b1_desc{};
        hr(pixel_reflection_->GetConstantBufferByName("DuoViewCompositeConfig")->GetDesc(&b0_desc), "reflect composite b0");
        hr(pixel_reflection_->GetConstantBufferByName("SurfaceConfig")->GetDesc(&b1_desc), "reflect surface b1");
        need(b0_desc.Size == 240u && b1_desc.Size == 400u,
             "production b0/b1 shader ABI changed");
        D3D11_BUFFER_DESC desc = constant_desc(b0_desc.Size);
        hr(device_->CreateBuffer(&desc, nullptr, &b0_), "create composite b0");
        desc = constant_desc(b1_desc.Size);
        hr(device_->CreateBuffer(&desc, nullptr, &b1_), "create surface b1");
        composite_constants_.initialize(pixel_reflection_.Get(), "DuoViewCompositeConfig", 240u);
        surface_constants_.initialize(pixel_reflection_.Get(), "SurfaceConfig", 400u);

        const std::vector<std::array<float, 4>> colors = [] {
            std::vector<std::array<float, 4>> pixels(PixelCount, {0.f, 0.f, 1.f, 1.f});
            for (UINT y = 0; y < Height; ++y)
                pixels[size_t(y) * Width + 16u] = {1.f, 0.f, 0.f, 1.f};
            return pixels;
        }();
        auto color_desc = texture_desc(DXGI_FORMAT_R32G32B32A32_FLOAT,
                                       D3D11_BIND_SHADER_RESOURCE);
        D3D11_SUBRESOURCE_DATA color_data{};
        color_data.pSysMem = colors.data();
        color_data.SysMemPitch = Width * UINT(sizeof(colors[0]));
        hr(device_->CreateTexture2D(&color_desc, &color_data, &source_color_), "create native color");
        hr(device_->CreateShaderResourceView(source_color_.Get(), nullptr, &source_srv_), "create native color SRV");

        const auto depth_desc = texture_desc(DXGI_FORMAT_R32_FLOAT, D3D11_BIND_SHADER_RESOURCE);
        hr(device_->CreateTexture2D(&depth_desc, nullptr, &left_depth_), "create left source depth");
        hr(device_->CreateTexture2D(&depth_desc, nullptr, &right_depth_), "create right source depth");
        hr(device_->CreateShaderResourceView(left_depth_.Get(), nullptr, &left_depth_srv_), "create left depth SRV");
        hr(device_->CreateShaderResourceView(right_depth_.Get(), nullptr, &right_depth_srv_), "create right depth SRV");

        const auto output_desc = texture_desc(DXGI_FORMAT_R32G32B32A32_FLOAT,
                                               D3D11_BIND_RENDER_TARGET);
        hr(device_->CreateTexture2D(&output_desc, nullptr, &output_), "create color output");
        hr(device_->CreateRenderTargetView(output_.Get(), nullptr, &output_rtv_), "create color RTV");
        const auto depth_output_desc = texture_desc(DXGI_FORMAT_D32_FLOAT,
                                                     D3D11_BIND_DEPTH_STENCIL);
        hr(device_->CreateTexture2D(&depth_output_desc, nullptr, &output_depth_), "create hardware depth output");
        hr(device_->CreateDepthStencilView(output_depth_.Get(), nullptr, &output_dsv_), "create hardware DSV");
        const auto color_readback_desc = texture_desc(DXGI_FORMAT_R32G32B32A32_FLOAT,
                                                       0, D3D11_USAGE_STAGING,
                                                       D3D11_CPU_ACCESS_READ);
        hr(device_->CreateTexture2D(&color_readback_desc, nullptr, &color_readback_), "create color readback");
        const auto depth_readback_desc = texture_desc(DXGI_FORMAT_D32_FLOAT, 0,
                                                       D3D11_USAGE_STAGING,
                                                       D3D11_CPU_ACCESS_READ);
        hr(device_->CreateTexture2D(&depth_readback_desc, nullptr, &depth_readback_), "create depth readback");

        D3D11_SAMPLER_DESC sampler_desc{};
        sampler_desc.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
        sampler_desc.AddressU = D3D11_TEXTURE_ADDRESS_CLAMP;
        sampler_desc.AddressV = D3D11_TEXTURE_ADDRESS_CLAMP;
        sampler_desc.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
        sampler_desc.MaxLOD = D3D11_FLOAT32_MAX;
        hr(device_->CreateSamplerState(&sampler_desc, &sampler_), "create linear clamp sampler");

        D3D11_RASTERIZER_DESC raster_desc{};
        raster_desc.FillMode = D3D11_FILL_SOLID;
        raster_desc.CullMode = D3D11_CULL_NONE;
        raster_desc.DepthClipEnable = TRUE;
        hr(device_->CreateRasterizerState(&raster_desc, &rasterizer_), "create rasterizer");

        D3D11_DEPTH_STENCIL_DESC depth_state_desc{};
        depth_state_desc.DepthEnable = TRUE;
        depth_state_desc.DepthWriteMask = D3D11_DEPTH_WRITE_MASK_ALL;
        depth_state_desc.DepthFunc = D3D11_COMPARISON_GREATER_EQUAL;
        hr(device_->CreateDepthStencilState(&depth_state_desc, &depth_state_), "create reversed-Z depth state");
    }

    Image render(Constants constants, const std::vector<float>& left,
                 const std::vector<float>& right, UINT vertex_count) {
        need(left.size() == PixelCount && right.size() == PixelCount,
             "incorrect source depth extent");
        set_constants(constants);
        upload_depth(left_depth_.Get(), left);
        upload_depth(right_depth_.Get(), right);

        const float clear_color[4]{0.f, 0.f, 0.f, 0.f};
        context_->ClearRenderTargetView(output_rtv_.Get(), clear_color);
        context_->ClearDepthStencilView(output_dsv_.Get(), D3D11_CLEAR_DEPTH,
                                        0.f, 0);
        ID3D11RenderTargetView* rtv = output_rtv_.Get();
        context_->OMSetRenderTargets(1, &rtv, output_dsv_.Get());
        context_->OMSetDepthStencilState(depth_state_.Get(), 0);
        const D3D11_VIEWPORT viewport{0.f, 0.f, float(Width), float(Height), 0.f, 1.f};
        context_->RSSetViewports(1, &viewport);
        context_->RSSetState(rasterizer_.Get());
        context_->IASetInputLayout(nullptr);
        context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context_->VSSetShader(vertex_shader_.Get(), nullptr, 0);
        context_->PSSetShader(pixel_shader_.Get(), nullptr, 0);
        ID3D11Buffer* cbs[]{b0_.Get(), b1_.Get()};
        context_->VSSetConstantBuffers(0, 2, cbs);
        context_->PSSetConstantBuffers(0, 2, cbs);
        ID3D11ShaderResourceView* srvs[]{source_srv_.Get(), source_srv_.Get(),
            left_depth_srv_.Get(), right_depth_srv_.Get(), nullptr, nullptr};
        context_->VSSetShaderResources(0, 6, srvs);
        context_->PSSetShaderResources(0, 6, srvs);
        ID3D11SamplerState* samplers[]{sampler_.Get()};
        context_->PSSetSamplers(0, 1, samplers);
        context_->Draw(vertex_count, 0);

        context_->OMSetRenderTargets(0, nullptr, nullptr);
        ID3D11ShaderResourceView* empty_srvs[6]{};
        context_->VSSetShaderResources(0, 6, empty_srvs);
        context_->PSSetShaderResources(0, 6, empty_srvs);
        context_->CopyResource(color_readback_.Get(), output_.Get());
        context_->CopyResource(depth_readback_.Get(), output_depth_.Get());

        Image result{};
        result.color.resize(PixelCount);
        result.depth.resize(PixelCount);
        D3D11_MAPPED_SUBRESOURCE color_map{};
        hr(context_->Map(color_readback_.Get(), 0, D3D11_MAP_READ, 0, &color_map), "map color output");
        for (UINT y = 0; y < Height; ++y) {
            const auto* row = static_cast<const uint8_t*>(color_map.pData) + size_t(y) * color_map.RowPitch;
            std::memcpy(result.color.data() + size_t(y) * Width, row,
                        size_t(Width) * sizeof(result.color[0]));
        }
        context_->Unmap(color_readback_.Get(), 0);
        D3D11_MAPPED_SUBRESOURCE depth_map{};
        hr(context_->Map(depth_readback_.Get(), 0, D3D11_MAP_READ, 0, &depth_map), "map hardware depth output");
        for (UINT y = 0; y < Height; ++y) {
            const auto* row = static_cast<const uint8_t*>(depth_map.pData) + size_t(y) * depth_map.RowPitch;
            std::memcpy(result.depth.data() + size_t(y) * Width, row,
                        size_t(Width) * sizeof(float));
        }
        context_->Unmap(depth_readback_.Get(), 0);
        return result;
    }
};

const std::array<float, 4>& color_at(const Image& image, UINT x, UINT y) {
    return image.color[size_t(y) * Width + x];
}

float depth_at(const Image& image, UINT x, UINT y) {
    return image.depth[size_t(y) * Width + x];
}

void test_measured_stripe_survives_and_reprojects(SurfaceFixture& fixture) {
    std::vector<float> depth(PixelCount, 0.001f); // 1000 cm background
    for (UINT y = 0; y < Height; ++y)
        depth[size_t(y) * Width + 16u] = 0.01f; // measured 100 cm, one-pixel stripe

    Constants mesh{};
    mesh.mesh_config = {Width, Height, 1u, 33u}; // bit 32 plus target-depth check bit 1
    const Image culled = fixture.render(mesh, depth, depth,
        (Width - 1u) * (Height - 1u) * 6u);
    need(color_at(culled, 16u, 8u)[0] < 0.1f,
         "mixed-depth triangle mesh unexpectedly retained the one-pixel foreground");

    Constants footprint{};
    footprint.mesh_config = {Width + 1u, Height + 1u, 1u, 97u}; // 32 | 64 | target-depth bit
    const UINT footprint_vertices = Width * Height * 6u;
    const Image preserved = fixture.render(footprint, depth, depth, footprint_vertices);
    const auto& fg = color_at(preserved, 16u, 8u);
    need(fg[0] > 0.98f && fg[1] < 0.02f && fg[2] < 0.02f,
         "pixel-footprint topology lost the measured foreground color");
    need(std::abs(depth_at(preserved, 16u, 8u) - 0.01f) < 1.e-5f,
         "hardware depth did not retain the measured foreground depth");
    for (const UINT x : {15u, 17u}) {
        const auto& neighbor = color_at(preserved, x, 8u);
        need(neighbor[2] > 0.98f && neighbor[0] < 0.02f,
             "pixel footprint invented foreground outside its measured texel");
        need(std::abs(depth_at(preserved, x, 8u) - 0.001f) < 1.e-5f,
             "hardware depth introduced a value between the measured surfaces");
    }

    // A 6.4 cm eye translation at 100 cm produces 1.024 output pixels of
    // disparity with this 32-pixel, unit-x-scale projection.
    footprint.target_clip_from_source_eye = target_projection(-6.4f);
    footprint.target_full_clip_from_source_eye = target_projection(-6.4f);
    const Image stereo = fixture.render(footprint, depth, depth, footprint_vertices);
    const auto& shifted = color_at(stereo, 15u, 8u);
    need(shifted[0] > 0.95f && shifted[2] < 0.05f,
         "stereo baseline did not move the measured stripe by its projected disparity");
    need(color_at(stereo, 16u, 8u)[0] < 0.1f &&
         depth_at(stereo, 16u, 8u) <= 0.00101f,
         "stereo foreground remained at its old pixel or invented foreground depth");
    need(std::abs(depth_at(stereo, 15u, 8u) - 0.01f) < 1.e-5f,
         "stereo hardware depth disagrees with the reprojected source surface");
}

void test_target_foreground_veto(SurfaceFixture& fixture) {
    std::vector<float> source(PixelCount, 0.001f); // 1000 cm left background
    std::vector<float> target(PixelCount, 0.01f);  // 100 cm measured target foreground
    Constants config{};
    config.mesh_config = {Width + 1u, Height + 1u, 1u, 96u}; // surfel topology, target veto disabled
    const UINT footprint_vertices = Width * Height * 6u;
    const Image unprotected = fixture.render(config, source, target, footprint_vertices);
    // Native color still contains the independent red stripe. Visibility is
    // controlled by geometry depth, so assert coverage and the actual D32 Z.
    need(color_at(unprotected, 16u, 8u)[3] > 0.98f &&
         std::abs(depth_at(unprotected, 16u, 8u) - 0.001f) < 1.e-6f,
         "target-depth control did not render the source background geometry");

    config.mesh_config[3] = 97u; // enable TargetCertainlyOccludes (bit 1)
    const Image protected_image = fixture.render(config, source, target, footprint_vertices);
    const auto& pixel = color_at(protected_image, 16u, 8u);
    need(pixel[0] < 0.01f && pixel[1] < 0.01f && pixel[2] < 0.01f,
         "certainly nearer target depth failed to veto unsupported background geometry");
    need(std::abs(depth_at(protected_image, 16u, 8u)) < 1.e-7f,
         "vetoed geometry unexpectedly wrote hardware depth");
}
} // namespace

int main(int argc, char** argv) try {
    need(argc == 3, "usage: footprint_gpu_tests.exe <production shader> <include dir>");
    SurfaceFixture fixture(argv[1], argv[2]);
    test_measured_stripe_survives_and_reprojects(fixture);
    test_target_foreground_veto(fixture);
    std::cout << "PASS: actual VSSurface/PSSurface WARP footprint topology, measured depth, stereo disparity, target occlusion\n";
    return 0;
} catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
}

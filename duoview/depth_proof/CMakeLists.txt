cmake_minimum_required(VERSION 3.20)
project(uevr_depth_proof_warp_test LANGUAGES CXX)

if(NOT WIN32)
    message(FATAL_ERROR "The depth proof WARP test requires Windows and D3D12.")
endif()

add_executable(depth_proof_warp_test depth_proof_warp_test.cpp)
target_compile_features(depth_proof_warp_test PRIVATE cxx_std_20)
target_link_libraries(depth_proof_warp_test PRIVATE d3d12 dxgi)

if(MSVC)
    target_compile_options(depth_proof_warp_test PRIVATE /W4 /permissive- /EHsc)
endif()

enable_testing()
add_test(NAME depth_proof_warp_test COMMAND depth_proof_warp_test)

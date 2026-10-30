#include "DuoViewCaptureArchive.hpp"
#include <cassert>
#include <iostream>
#include <vector>
using namespace uevr::duoview::capture75;
int main(int argc,char** argv) {
    const auto dir=argc>1?std::filesystem::path(argv[1]):std::filesystem::temp_directory_path();
    std::filesystem::create_directories(dir);
    assert(crc32(reinterpret_cast<const uint8_t*>("123456789"),9)==0xcbf43926u);
    Zip zip(dir/"portable_archive_test.zip",1024);
    assert(zip.add("exact.bin",{0,1,0,255,127}));
    assert(!zip.add("../escape",{}));
    std::vector<Payload> too_big{{"oversized",std::vector<uint8_t>(2048)}};
    assert(!zip.fits(too_big,64));
    const std::string manifest="{\"test\":true}";
    assert(zip.add("manifest.json",std::vector<uint8_t>(manifest.begin(),manifest.end())));
    assert(zip.finish());
    assert(std::filesystem::file_size(dir/"portable_archive_test.zip")<=1024);
    std::cout<<"PASS portable ZIP CRC, exact size accounting, traversal rejection and EOCD writing\n";
}

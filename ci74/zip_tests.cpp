#define NOMINMAX
#include "DuoViewSequenceRecorder.hpp"
#include <cassert>
#include <fstream>
#include <iterator>
#include <filesystem>
int main(){
    using namespace uevr::duoview::sequence;
    assert(crc32(reinterpret_cast<const uint8_t*>("123456789"),9)==0xcbf43926u);
    auto path=std::filesystem::temp_directory_path()/"duoview-ci74-zip-smoke.zip";
    {
        Zip zip(path);assert(zip.ok());
        std::string data="{\"test\":true}";
        std::vector<uint8_t> payload(data.begin(),data.end());
        assert(zip.add("manifest.json",payload));assert(zip.finish());
    }
    std::ifstream file(path,std::ios::binary);
    assert(bool(file));char prefix[4]{};file.read(prefix,4);
    assert(prefix[0]=='P'&&prefix[1]=='K'&&prefix[2]==3&&prefix[3]==4);
    file.close(); // Windows requires closing the read handle before removal.
    std::filesystem::remove(path);
    return 0;
}

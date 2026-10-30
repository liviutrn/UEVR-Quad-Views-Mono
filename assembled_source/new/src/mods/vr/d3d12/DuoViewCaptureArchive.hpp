#pragma once
// Portable, bounded ZIP_STORED writer. Plane payloads are already lossless PNG.
#include <cstdint>
#include <cstddef>
#include <fstream>
#include <filesystem>
#include <string>
#include <vector>
#include <limits>
#include <cmath>
#include <sstream>
#include <iomanip>

namespace uevr::duoview::capture75 {
constexpr uint64_t MaxZipBytes=20ull*1024ull*1024ull;
inline uint32_t crc32(const uint8_t* p,size_t n) {
    uint32_t crc=0xffffffffu;
    for(size_t i=0;i<n;++i){crc^=p[i];for(unsigned k=0;k<8;++k)crc=(crc>>1)^((crc&1u)?0xedb88320u:0u);}
    return ~crc;
}
struct Payload {std::string name;std::vector<uint8_t> bytes;};
class Zip {
    struct Entry {std::string name;uint32_t crc{},size{},offset{};};
    std::ofstream stream_;
    std::vector<Entry> entries_;
    uint64_t local_bytes_{},central_bytes_{},limit_;
    bool finished_{};
    void u16(uint16_t n){const char b[]{char(n),char(n>>8)};stream_.write(b,2);local_bytes_+=2;}
    void u32(uint32_t n){u16(uint16_t(n));u16(uint16_t(n>>16));}
    void bytes(const void* p,size_t n){if(n)stream_.write(static_cast<const char*>(p),std::streamsize(n));local_bytes_+=n;}
public:
    explicit Zip(const std::filesystem::path& path,uint64_t limit=MaxZipBytes):stream_(path,std::ios::binary),limit_(limit){}
    bool ok() const{return bool(stream_)&&!finished_;}
    uint64_t projected_size()const{return local_bytes_+central_bytes_+22;}
    bool fits(const std::vector<Payload>& next,size_t manifest_bytes)const {
        uint64_t size=projected_size()+30+46+2*13+manifest_bytes; // manifest.json
        for(const auto& p:next)size+=30+46+2*p.name.size()+p.bytes.size();
        return size<=limit_&&entries_.size()+next.size()+1<65535;
    }
    bool add(const std::string& name,const std::vector<uint8_t>& data) {
        if(!ok()||name.empty()||name.size()>65535||data.size()>UINT32_MAX||entries_.size()>=65534||
           name.find("..")!=std::string::npos||name.front()=='/'||name.find('\\')!=std::string::npos||
           projected_size()+30+46+2*name.size()+data.size()>limit_)return false;
        Entry e{name,crc32(data.data(),data.size()),uint32_t(data.size()),uint32_t(local_bytes_)};
        u32(0x04034b50);u16(20);u16(0);u16(0);u16(0);u16(0);
        u32(e.crc);u32(e.size);u32(e.size);u16(uint16_t(name.size()));u16(0);
        bytes(name.data(),name.size());bytes(data.data(),data.size());
        entries_.push_back(e);central_bytes_+=46+name.size();return bool(stream_);
    }
    bool finish() {
        if(!ok()||projected_size()>limit_)return false;
        const uint32_t central_offset=uint32_t(local_bytes_);
        for(const auto& e:entries_) {
            u32(0x02014b50);u16(20);u16(20);u16(0);u16(0);u16(0);u16(0);
            u32(e.crc);u32(e.size);u32(e.size);u16(uint16_t(e.name.size()));
            u16(0);u16(0);u16(0);u16(0);u32(0);u32(e.offset);bytes(e.name.data(),e.name.size());
        }
        const uint32_t central_size=uint32_t(local_bytes_-central_offset);
        u32(0x06054b50);u16(0);u16(0);u16(uint16_t(entries_.size()));u16(uint16_t(entries_.size()));
        u32(central_size);u32(central_offset);u16(0);
        stream_.flush();const bool good=bool(stream_)&&local_bytes_<=limit_;stream_.close();finished_=true;return good;
    }
};
inline std::string number(double value) {
    if(!std::isfinite(value))return "null";
    std::ostringstream out;out<<std::setprecision(17)<<value;return out.str();
}
inline std::string quote(const std::string& value) {
    std::string out="\"";
    const char* hex="0123456789abcdef";
    for(unsigned char c:value) {
        if(c=='"'||c=='\\'){out+='\\';out+=char(c);}
        else if(c<32){out+="\\u00";out+=hex[c>>4];out+=hex[c&15];}
        else out+=char(c);
    }
    return out+'"';
}
}

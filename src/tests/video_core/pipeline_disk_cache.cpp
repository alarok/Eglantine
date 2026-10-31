// SPDX-License-Identifier: GPL-3.0-or-later

#include <array>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
#include <catch2/catch_test_macros.hpp>

#include "common/common_types.h"
#include "video_core/shader_environment.h"

// These tests write the file by hand. The layout is the one that GenericEnvironment::Serialize
// writes and that tools/nx2/debug/pipecache.py reads from real caches.
namespace {
constexpr u32 VERSION = 7;
constexpr u32 STAGE_COMPUTE = 5;
constexpr size_t KEY_SIZE = 24;

template <typename T>
void Put(std::string& out, T value) {
    out.append(reinterpret_cast<const char*>(&value), sizeof(value));
}

std::string Header(u32 version = VERSION) {
    std::string out{"yuzucach"};
    Put<u32>(out, version);
    return out;
}

std::string ComputeRecord() {
    std::string out;
    Put<u32>(out, 1);  // environment count
    Put<u64>(out, 16); // code size
    for (int table = 0; table < 4; ++table) {
        Put<u64>(out, 0);
    }
    // Local memory, texture bound, start address, lowest, highest, viewport transform.
    for (int field = 0; field < 6; ++field) {
        Put<u32>(out, 0);
    }
    Put<u32>(out, STAGE_COMPUTE);
    out.append(16, '\0');       // code
    out.append(16, '\0');       // workgroup size and shared memory size
    out.append(KEY_SIZE, 'k');
    return out;
}

// One file for each test case. The destructor removes it, also after a failed REQUIRE.
struct CacheFile {
    explicit CacheFile(const char* name) : path{std::filesystem::temp_directory_path() / name} {}
    ~CacheFile() {
        std::error_code ignored;
        std::filesystem::remove(path, ignored);
    }

    void Write(const std::string& bytes) const {
        std::ofstream file(path, std::ios::binary | std::ios::trunc);
        file.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    }

    size_t Load() const {
        size_t records = 0;
        VideoCommon::LoadPipelines(
            std::stop_token{}, path, VERSION,
            [&](std::ifstream& file, VideoCommon::FileEnvironment) {
                std::array<char, KEY_SIZE> key;
                file.read(key.data(), key.size());
                ++records;
            },
            [](std::ifstream&, std::vector<VideoCommon::FileEnvironment>) {
                FAIL("this file has only compute records");
            });
        return records;
    }

    std::filesystem::path path;
};

TEST_CASE("Pipeline disk cache keeps the complete records when the last record is cut",
          "[video_core][disk_cache]") {
    const CacheFile cache{"eden-test-cut-record.bin"};
    const std::string record = ComputeRecord();
    const std::string complete = Header() + record + record;
    // A process that stops during a write can leave any length of the last record.
    for (size_t cut = 1; cut < record.size(); ++cut) {
        INFO("bytes of the last record: " << cut);
        cache.Write(complete + record.substr(0, cut));
        REQUIRE(cache.Load() == 2);
        REQUIRE(std::filesystem::exists(cache.path));
        REQUIRE(std::filesystem::file_size(cache.path) == complete.size());
        // The next boot and the next append must see a clean file.
        REQUIRE(cache.Load() == 2);
    }
}

TEST_CASE("Pipeline disk cache does not change a complete file", "[video_core][disk_cache]") {
    const CacheFile cache{"eden-test-complete.bin"};
    const std::string record = ComputeRecord();
    const std::string complete = Header() + record + record + record;
    cache.Write(complete);
    REQUIRE(cache.Load() == 3);
    REQUIRE(std::filesystem::file_size(cache.path) == complete.size());
}

TEST_CASE("Pipeline disk cache removes a file with no valid header", "[video_core][disk_cache]") {
    const CacheFile cache{"eden-test-header.bin"};
    const std::string record = ComputeRecord();
    SECTION("cut header") {
        cache.Write(Header().substr(0, 5));
    }
    SECTION("other magic") {
        cache.Write("notacach" + Header().substr(8) + record);
    }
    SECTION("other version") {
        cache.Write(Header(VERSION + 1) + record);
    }
    REQUIRE(cache.Load() == 0);
    REQUIRE(!std::filesystem::exists(cache.path));
}
} // Anonymous namespace

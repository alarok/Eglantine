// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <catch2/catch_test_macros.hpp>

#include <cstddef>
#include <filesystem>
#include <fstream>
#include <random>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

#include "common/common_types.h"
#include "common/fs/path_util.h"
#include "core/file_sys/vfs/vfs_real.h"
#include "core/loader/deconstructed_rom_directory.h"

namespace {

namespace fs = std::filesystem;

constexpr std::string_view IconBytes = "icon bytes";

// A control.nacp holds 16 language entries of 0x300 bytes first. Each entry starts with its name.
std::string MakeNacp(std::string_view name) {
    constexpr std::size_t NacpSize = 0x4000;
    std::string nacp(NacpSize, '\0');
    nacp.replace(0, name.size(), name);
    return nacp;
}

void WriteFile(const fs::path& path, std::string_view data) {
    fs::create_directories(path.parent_path());
    std::ofstream{path, std::ios::binary}.write(data.data(), std::streamsize(data.size()));
}

class TempDir {
public:
    TempDir()
        : root{fs::temp_directory_path() /
               ("eglantine-loose-dump-" + std::to_string(std::random_device{}()))} {
        fs::create_directories(root);
    }
    ~TempDir() {
        std::error_code ignored;
        fs::remove_all(root, ignored);
    }

    const fs::path root;
};

Loader::AppLoader_DeconstructedRomDirectory OpenLoader(FileSys::RealVfsFilesystem& vfs,
                                                       const fs::path& main) {
    WriteFile(main, "main");
    return Loader::AppLoader_DeconstructedRomDirectory{
        vfs.OpenFile(Common::FS::PathToUTF8String(main), FileSys::OpenMode::Read)};
}

} // namespace

TEST_CASE("A base dump reads its sidecars from the game folder", "[loader]") {
    const TempDir temp;
    const auto game = temp.root / "Some Game";
    WriteFile(game / "control.nacp", MakeNacp("Title From Sidecar"));
    WriteFile(game / "icon.png", IconBytes);

    FileSys::RealVfsFilesystem vfs;
    auto loader = OpenLoader(vfs, game / "base" / "exefs" / "main");

    std::string title;
    REQUIRE(loader.ReadTitle(title) == Loader::ResultStatus::Success);
    REQUIRE(title == "Title From Sidecar");

    std::vector<u8> icon;
    REQUIRE(loader.ReadIcon(icon) == Loader::ResultStatus::Success);
    REQUIRE(std::string_view{reinterpret_cast<const char*>(icon.data()), icon.size()} == IconBytes);
}

TEST_CASE("A base dump ignores sidecars above its game folder", "[loader]") {
    const TempDir temp;
    const auto library = temp.root / "Library";
    WriteFile(library / "control.nacp", MakeNacp("Title Of Another Game"));
    WriteFile(library / "icon.png", IconBytes);

    FileSys::RealVfsFilesystem vfs;
    auto loader = OpenLoader(vfs, library / "Some Game" / "base" / "exefs" / "main");

    std::string title;
    REQUIRE(loader.ReadTitle(title) == Loader::ResultStatus::ErrorNoControl);

    std::vector<u8> icon;
    REQUIRE(loader.ReadIcon(icon) == Loader::ResultStatus::ErrorNoIcon);
}

TEST_CASE("A base dump finds its RomFS next to the ExeFS", "[loader]") {
    const TempDir temp;
    const auto game = temp.root / "Some Game";
    WriteFile(game / "base" / "romfs" / "data.bin", "romfs bytes");

    FileSys::RealVfsFilesystem vfs;
    auto loader = OpenLoader(vfs, game / "base" / "exefs" / "main");

    // The game list builds this loader for every candidate and needs only the title, so the
    // RomFS is indexed on the first caller that asks for it.
    std::string title;
    REQUIRE(loader.ReadTitle(title) == Loader::ResultStatus::ErrorNoControl);

    FileSys::VirtualFile romfs;
    REQUIRE(loader.ReadRomFS(romfs) == Loader::ResultStatus::Success);
    REQUIRE(romfs != nullptr);
}

TEST_CASE("A base dump without a RomFS reports that it has none", "[loader]") {
    const TempDir temp;
    const auto game = temp.root / "Some Game";

    FileSys::RealVfsFilesystem vfs;
    auto loader = OpenLoader(vfs, game / "base" / "exefs" / "main");

    FileSys::VirtualFile romfs;
    REQUIRE(loader.ReadRomFS(romfs) == Loader::ResultStatus::ErrorNoRomFS);
}

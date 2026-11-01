// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <memory>
#include <string_view>
#include <vector>

#include <catch2/catch_test_macros.hpp>

#include "core/file_sys/ips_layer.h"
#include "core/file_sys/vfs/vfs_vector.h"

TEST_CASE("IPSwitch applies the escape character in string patches", "[file_sys]") {
    constexpr std::string_view patch_text = "@enabled\n00000001 \"A\\eB\"\n";
    const auto patch = std::make_shared<FileSys::VectorVfsFile>(
        std::vector<u8>(patch_text.begin(), patch_text.end()), "patch.pchtxt");
    const auto input = std::make_shared<FileSys::VectorVfsFile>(std::vector<u8>(5, 0), "input");

    const FileSys::IPSwitchCompiler compiler{patch};
    const auto output = compiler.Apply(input);
    REQUIRE(output);
    CHECK(output->ReadAllBytes() == std::vector<u8>{0, 'A', 0x1b, 'B', 0});
}

// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <catch2/catch_test_macros.hpp>

#include <filesystem>
#include <fstream>
#include <random>
#include <string>
#include <system_error>

#include "common/fs/fs.h"
#include "common/fs/fs_types.h"

namespace {

namespace fs = std::filesystem;

class TempTree {
public:
    TempTree()
        : root{fs::temp_directory_path() /
               ("eglantine-fs-iterate-" + std::to_string(std::random_device{}()))} {
        fs::create_directories(root);
        for (const char* const name : {"a", "b", "c"}) {
            std::ofstream{root / name};
        }
    }
    ~TempTree() {
        std::error_code ignored;
        fs::remove_all(root, ignored);
    }

    const fs::path root;
};

} // namespace

TEST_CASE("IterateDirEntries halts when the callback returns false", "[common][fs]") {
    const TempTree tree;
    int visited = 0;
    Common::FS::IterateDirEntries(
        tree.root,
        [&visited](const fs::directory_entry&) {
            ++visited;
            return false;
        },
        Common::FS::DirEntryFilter::File);
    REQUIRE(visited == 1);
}

TEST_CASE("IterateDirEntriesRecursively halts when the callback returns false", "[common][fs]") {
    const TempTree tree;
    int visited = 0;
    Common::FS::IterateDirEntriesRecursively(
        tree.root,
        [&visited](const fs::directory_entry&) {
            ++visited;
            return false;
        },
        Common::FS::DirEntryFilter::File);
    REQUIRE(visited == 1);
}

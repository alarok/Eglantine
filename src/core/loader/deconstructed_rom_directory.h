// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

// SPDX-FileCopyrightText: Copyright 2018 yuzu Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <optional>
#include <string>
#include "common/common_types.h"
#include "core/file_sys/control_metadata.h"
#include "core/file_sys/program_metadata.h"
#include "core/loader/loader.h"

namespace Core {
class System;
}

namespace Loader {

/**
 * This class loads a "deconstructed ROM directory", which are the typical format we see for Switch
 * game dumps. The path should be a "main" NSO, which must be in a directory that contains the other
 * standard ExeFS NSOs (e.g. rtld, sdk, etc.). It will automatically find and load these.
 * Furthermore, it will look for the first .romfs file (optionally) and use this for the RomFS.
 */
class AppLoader_DeconstructedRomDirectory final : public AppLoader {
public:
    explicit AppLoader_DeconstructedRomDirectory(FileSys::VirtualFile main_file, bool override_update_ = false);
    // Overload to accept exefs directory. Must contain 'main' and 'main.npdm'
    explicit AppLoader_DeconstructedRomDirectory(FileSys::VirtualDir directory, bool override_update_ = false);

    /**
     * Identifies whether or not the given file is a deconstructed ROM directory.
     *
     * @param dir_file The file to verify.
     *
     * @return FileType::DeconstructedRomDirectory, or FileType::Error
     *         if the file is not a deconstructed ROM directory.
     */
    static FileType IdentifyType(const FileSys::VirtualFile& dir_file);

    FileType GetFileType() const override {
        return IdentifyType(file);
    }

    LoadResult Load(Kernel::KProcess& process, Core::System& system) override;

    ResultStatus ReadRomFS(FileSys::VirtualFile& out_dir) override;
    ResultStatus ReadIcon(std::vector<u8>& out_buffer) override;
    ResultStatus ReadProgramId(u64& out_program_id) override;
    ResultStatus ReadTitle(std::string& title) override;
    ResultStatus ReadControlData(FileSys::NACP& control) override;
    ResultStatus ReadDisplayVersion(std::string& version) override;
    bool IsRomFSUpdatable() const override;

    ResultStatus ReadNSOModules(Modules& out_modules) override;

private:
    /// Returns the RomFS of this dump, and indexes it on the first call. A game list scan builds
    /// an AppLoader for every candidate, and indexing a large dump walks every file of romfs/, so
    /// the walk waits until a caller asks for the RomFS.
    FileSys::VirtualFile BuildRomFS();

    FileSys::ProgramMetadata metadata;
    FileSys::VirtualFile romfs_file; ///< The .romfs file next to main, if the dump holds one
    FileSys::VirtualDir romfs_dir;   ///< The romfs/ directory next to exefs/, if the dump holds one
    FileSys::VirtualFile romfs;      ///< The indexed RomFS, built by BuildRomFS()
    bool romfs_built{};
    FileSys::VirtualDir dir;

    std::vector<u8> icon_data;
    std::string name;
    std::optional<FileSys::NACP> control; ///< control.nacp next to the dump, if it has one
    std::string romfs_version;            ///< "1.8.0" from the RomFS's Product.180 tables, if any
    u64 title_id{};
    bool override_update;

    Modules modules;
};

} // namespace Loader

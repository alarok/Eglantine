// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

// SPDX-FileCopyrightText: Copyright 2018 yuzu Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <algorithm>
#include <charconv>
#include <chrono>
#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

#include <QCryptographicHash>
#include <QDateTime>
#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QRegularExpression>
#include <QSettings>

#include "common/fs/fs.h"
#include "common/fs/path_util.h"
#include "common/net/nintendo_store.h"
#include "common/settings.h"
#include "core/core.h"
#include "core/file_sys/card_image.h"
#include "core/file_sys/content_archive.h"
#include "core/file_sys/control_metadata.h"
#include "core/file_sys/fs_filesystem.h"
#include "core/file_sys/nca_metadata.h"
#include "core/file_sys/patch_manager.h"
#include "core/file_sys/registered_cache.h"
#include "core/file_sys/submission_package.h"
#include "core/loader/loader.h"

#include "qt_common/config/uisettings.h"
#include "qt_common/qt_common.h"

#include "qt_common/game_list/game_list_p.h"

#include "qt_common/game_list/model.h"
#include "qt_common/game_list/worker.h"

namespace {

QString GetGameListCachedObject(const std::string& filename, const std::string& ext,
                                const std::function<QString()>& generator) {
    if (!UISettings::values.cache_game_list || filename == "0000000000000000") {
        return generator();
    }

    const auto path =
        Common::FS::PathToUTF8String(Common::FS::GetEdenPath(Common::FS::EdenPath::CacheDir) /
                                     "game_list" / fmt::format("{}.{}", filename, ext));

    void(Common::FS::CreateParentDirs(path));

    if (!Common::FS::Exists(path)) {
        const auto str = generator();

        QFile file{QString::fromStdString(path)};
        if (file.open(QFile::WriteOnly)) {
            file.write(str.toUtf8());
        }

        return str;
    }

    QFile file{QString::fromStdString(path)};
    if (file.open(QFile::ReadOnly)) {
        return QString::fromUtf8(file.readAll());
    }

    return generator();
}

std::pair<std::vector<u8>, std::string> GetGameListCachedObject(
    const std::string& filename, const std::string& ext,
    const std::function<std::pair<std::vector<u8>, std::string>()>& generator) {
    if (!UISettings::values.cache_game_list || filename == "0000000000000000") {
        return generator();
    }

    const auto game_list_dir =
        Common::FS::GetEdenPath(Common::FS::EdenPath::CacheDir) / "game_list";
    const auto jpeg_name = fmt::format("{}.jpeg", filename);
    const auto app_name = fmt::format("{}.appname.txt", filename);

    const auto path1 = Common::FS::PathToUTF8String(game_list_dir / jpeg_name);
    const auto path2 = Common::FS::PathToUTF8String(game_list_dir / app_name);

    void(Common::FS::CreateParentDirs(path1));

    if (!Common::FS::Exists(path1) || !Common::FS::Exists(path2)) {
        const auto [icon, nacp] = generator();

        QFile file1{QString::fromStdString(path1)};
        if (!file1.open(QFile::WriteOnly)) {
            LOG_ERROR(Frontend, "Failed to open cache file.");
            return generator();
        }

        if (!file1.resize(icon.size())) {
            LOG_ERROR(Frontend, "Failed to resize cache file to necessary size.");
            return generator();
        }

        if (file1.write(reinterpret_cast<const char*>(icon.data()), icon.size()) !=
            s64(icon.size())) {
            LOG_ERROR(Frontend, "Failed to write data to cache file.");
            return generator();
        }

        QFile file2{QString::fromStdString(path2)};
        if (file2.open(QFile::WriteOnly)) {
            file2.write(nacp.data(), nacp.size());
        }

        return std::make_pair(icon, nacp);
    }

    QFile file1(QString::fromStdString(path1));
    QFile file2(QString::fromStdString(path2));

    if (!file1.open(QFile::ReadOnly)) {
        LOG_ERROR(Frontend, "Failed to open cache file for reading.");
        return generator();
    }

    if (!file2.open(QFile::ReadOnly)) {
        LOG_ERROR(Frontend, "Failed to open cache file for reading.");
        return generator();
    }

    std::vector<u8> vec(file1.size());
    if (file1.read(reinterpret_cast<char*>(vec.data()), vec.size()) !=
        static_cast<s64>(vec.size())) {
        return generator();
    }

    const auto data = file2.readAll();
    return std::make_pair(vec, data.toStdString());
}

void GetMetadataFromControlNCA(const FileSys::PatchManager& patch_manager, const FileSys::NCA& nca,
                               std::vector<u8>& icon, std::string& name) {
    std::tie(icon, name) = GetGameListCachedObject(
        fmt::format("{:016X}", patch_manager.GetTitleID()), {}, [&patch_manager, &nca] {
            const auto [nacp, icon_f] = patch_manager.ParseControlNCA(nca);
            return std::make_pair(icon_f->ReadAllBytes(), nacp->GetApplicationName());
        });
}

bool HasSupportedFileExtension(const std::string& file_name) {
    const QFileInfo file = QFileInfo(QString::fromStdString(file_name));
    return QtCommon::supported_file_extensions.contains(file.suffix(), Qt::CaseInsensitive);
}

bool IsExtractedNCAMain(const std::string& file_name) {
    return QFileInfo(QString::fromStdString(file_name)).fileName() == QStringLiteral("main");
}

QString FormatGameName(const std::string& physical_name) {
    const QString physical_name_as_qstring = QString::fromStdString(physical_name);
    const QFileInfo file_info(physical_name_as_qstring);

    if (IsExtractedNCAMain(physical_name)) {
        return file_info.dir().path();
    }

    return physical_name_as_qstring;
}

QDir ExtractedGameDirectory(const std::string& physical_name) {
    QDir directory = QFileInfo(QString::fromStdString(physical_name)).dir();
    if (directory.dirName().compare(QStringLiteral("exefs"), Qt::CaseInsensitive) != 0 ||
        !directory.cdUp()) {
        return QFileInfo(QString::fromStdString(physical_name)).dir();
    }
    if (directory.dirName().compare(QStringLiteral("updates"), Qt::CaseInsensitive) == 0 ||
        directory.dirName().compare(QStringLiteral("base"), Qt::CaseInsensitive) == 0) {
        directory.cdUp();
    } else {
        QDir parent = directory;
        if (parent.cdUp() &&
            parent.dirName().compare(QStringLiteral("updates"), Qt::CaseInsensitive) == 0 &&
            parent.cdUp()) {
            directory = parent;
        }
    }
    return directory;
}

// A loose dump can hold hundreds of thousands of files, so each scan must not add them up again.
// The cache lives with the game metadata: the Refresh button removes it. A new dump of the game
// changes the date of its main file.
std::size_t ExtractedGameSize(const std::string& physical_name,
                              const std::atomic_bool& stop_requested) {
    const QString directory = ExtractedGameDirectory(physical_name).absolutePath();
    const auto cache_path =
        Common::FS::GetEdenPath(Common::FS::EdenPath::CacheDir) / "game_list" / "folder_sizes.ini";
    QSettings cache{QString::fromStdString(Common::FS::PathToUTF8String(cache_path)),
                    QSettings::IniFormat};
    const QString key = QString::fromLatin1(
        QCryptographicHash::hash(directory.toUtf8(), QCryptographicHash::Md5).toHex());
    const qint64 stamp =
        QFileInfo(QString::fromStdString(physical_name)).lastModified().toMSecsSinceEpoch();
    if (cache.value(key + QStringLiteral("/stamp")).toLongLong() == stamp) {
        return static_cast<std::size_t>(cache.value(key + QStringLiteral("/size")).toULongLong());
    }

    QDirIterator files{directory, QDir::Files | QDir::Hidden | QDir::System | QDir::NoSymLinks,
                       QDirIterator::Subdirectories};
    std::size_t size = 0;
    while (!stop_requested && files.hasNext()) {
        files.next();
        const auto file_size = files.fileInfo().size();
        if (file_size > 0) {
            size += static_cast<std::size_t>(file_size);
        }
    }
    if (!stop_requested) {
        cache.setValue(key + QStringLiteral("/stamp"), stamp);
        cache.setValue(key + QStringLiteral("/size"), static_cast<qulonglong>(size));
    }
    return size;
}

// Walks a game folder and its subfolders. A loose dump's romfs holds the files of that game and no
// other game, so the walk does not enter it.
template <typename Callback>
void WalkGameFolder(const std::filesystem::path& root, Callback&& callback) {
    namespace fs = std::filesystem;
    std::error_code error;
    fs::recursive_directory_iterator entry{root, fs::directory_options::skip_permission_denied,
                                           error};
    const fs::recursive_directory_iterator end;
    while (!error && entry != end) {
        const fs::path path = entry->path();
        std::error_code ignored;
        if (entry->is_directory(ignored) && path.filename() == "romfs" &&
            fs::is_directory(path.parent_path() / "exefs", ignored)) {
            entry.disable_recursion_pending();
        }
        if (!callback(path)) {
            return;
        }
        entry.increment(error);
    }
}

// Returns the number of a folder named after an internal update version, such as 458752.
std::optional<u64> ParseVersionFolder(const std::string& name) {
    u64 number = 0;
    const char* const end = name.data() + name.size();
    const auto [ptr, ec] = std::from_chars(name.data(), end, number);
    if (name.empty() || ec != std::errc{} || ptr != end) {
        return std::nullopt;
    }
    return number;
}

// A game folder holds its base dump in <game>/base and complete updates in <game>/updates/<N>.
// The list shows only the newest of these dumps, so each game has one row.
bool HasNewerLooseDump(const std::filesystem::path& main_path) {
    const auto exefs = main_path.parent_path();
    if (exefs.filename() != "exefs") {
        return false;
    }

    const auto dump_dir = exefs.parent_path();
    const auto game_or_updates = dump_dir.parent_path();
    const auto dump_name = Common::FS::PathToUTF8String(dump_dir.filename());

    std::optional<u64> own_version;
    std::filesystem::path updates;
    if (dump_name == "base") {
        updates = game_or_updates / "updates";
        if (Common::FS::IsFile(updates / "exefs" / "main")) {
            return true;
        }
    } else {
        own_version = ParseVersionFolder(dump_name);
        if (!own_version.has_value() || game_or_updates.filename() != "updates") {
            return false;
        }
        updates = game_or_updates;
    }

    if (!Common::FS::IsDir(updates)) {
        return false;
    }

    bool found_newer = false;
    Common::FS::IterateDirEntries(
        updates,
        [&](const std::filesystem::path& entry) {
            const auto version =
                ParseVersionFolder(Common::FS::PathToUTF8String(entry.filename()));
            if (version.has_value() && (!own_version || *version > *own_version) &&
                Common::FS::IsFile(entry / "exefs" / "main")) {
                found_newer = true;
            }
            return true;
        },
        Common::FS::DirEntryFilter::Directory);
    return found_newer;
}

std::filesystem::path StoreCachePath(u64 title_id, std::string_view extension) {
    return Common::FS::GetEdenPath(Common::FS::EdenPath::CacheDir) / "game_list" /
           fmt::format("{:016X}.store.{}", title_id, extension);
}

std::optional<Common::Net::StoreMetadata> ReadStoreCache(u64 title_id) {
    QFile name_file{QString::fromStdString(
        Common::FS::PathToUTF8String(StoreCachePath(title_id, "txt")))};
    QFile icon_file{QString::fromStdString(
        Common::FS::PathToUTF8String(StoreCachePath(title_id, "jpeg")))};
    if (!name_file.open(QFile::ReadOnly) || !icon_file.open(QFile::ReadOnly)) {
        return std::nullopt;
    }

    const QByteArray name = name_file.readAll();
    const QByteArray icon = icon_file.readAll();
    return Common::Net::StoreMetadata{name.toStdString(),
                                      std::vector<u8>(icon.cbegin(), icon.cend())};
}

void WriteStoreCache(u64 title_id, const Common::Net::StoreMetadata& metadata) {
    const auto name_path = StoreCachePath(title_id, "txt");
    void(Common::FS::CreateParentDirs(name_path));

    QFile icon_file{QString::fromStdString(
        Common::FS::PathToUTF8String(StoreCachePath(title_id, "jpeg")))};
    QFile name_file{QString::fromStdString(Common::FS::PathToUTF8String(name_path))};
    if (!icon_file.open(QFile::WriteOnly) || !name_file.open(QFile::WriteOnly)) {
        LOG_ERROR(Frontend, "Failed to open the store cache files of {:016X}", title_id);
        return;
    }
    icon_file.write(reinterpret_cast<const char*>(metadata.icon.data()),
                    static_cast<qint64>(metadata.icon.size()));
    name_file.write(metadata.name.data(), static_cast<qint64>(metadata.name.size()));
}

// Returns the cached store data of a title, or requests it once. The game list runs one worker at
// a time, so the lookup needs no lock.
std::optional<Common::Net::StoreMetadata> FindStoreMetadata(u64 title_id,
                                                            const std::atomic_bool& stop) {
    if (title_id == 0) {
        return std::nullopt;
    }
    if (auto cached = ReadStoreCache(title_id)) {
        return cached;
    }

    static Common::Net::StoreLookup lookup{Common::Net::FetchStoreUrl};
    auto metadata = lookup.Find(title_id, stop);
    if (metadata) {
        WriteStoreCache(title_id, *metadata);
    }
    return metadata;
}

QString FormatPatchNameVersions(const FileSys::PatchManager& patch_manager,
                                Loader::AppLoader& loader, bool updatable = true) {
    QString out;
    FileSys::VirtualFile update_raw;
    loader.ReadUpdateRaw(update_raw);
    for (const auto& patch : patch_manager.GetPatches(update_raw)) {
        const bool is_update = patch.name == "Update";
        if (!updatable && is_update) {
            continue;
        }

        const QString type =
            QString::fromStdString(patch.enabled ? patch.name : "[D] " + patch.name);

        if (patch.version.empty()) {
            out.append(QStringLiteral("%1\n").arg(type));
        } else {
            auto ver = patch.version;

            // Display container name for packed updates
            if (is_update && ver == "PACKED") {
                ver = Loader::GetFileTypeString(loader.GetFileType());
            }

            out.append(QStringLiteral("%1 (%2)\n").arg(type, QString::fromStdString(ver)));
        }
    }

    out.chop(1);
    return out;
}

QList<QStandardItem*> MakeGameListEntry(const std::string& path, const std::string& name,
                                        const std::size_t size, const std::vector<u8>& icon,
                                        Loader::AppLoader& loader, u64 program_id,
                                        const PlayTime::PlayTimeManager& play_time_manager,
                                        const FileSys::PatchManager& patch,
                                        const QString& dump_version = {}) {
    auto const file_type = loader.GetFileType();
    auto const file_type_string = QString::fromStdString(Loader::GetFileTypeString(file_type));

    QString patch_versions = GetGameListCachedObject(
        fmt::format("{:016X}", patch.GetTitleID()), "pv.txt", [&patch, &loader] {
            return FormatPatchNameVersions(patch, loader, loader.IsRomFSUpdatable());
        });

    // The cache is keyed by title ID, and two dumps of one title can differ, so it must not keep
    // the version of a dump.
    if (!dump_version.isEmpty()) {
        const QString version = QObject::tr("Version (%1)").arg(dump_version);
        patch_versions = patch_versions.isEmpty()
                             ? version
                             : QStringLiteral("%1\n%2").arg(version, patch_versions);
    }

    u64 play_time = play_time_manager.GetPlayTime(program_id);
    return QList<QStandardItem*>{
        new GameListItemPath(FormatGameName(path), icon, QString::fromStdString(name),
                             file_type_string, program_id, play_time, patch_versions,
                             dump_version),
        new GameListItem(file_type_string),
        new GameListItemSize(size),
        new GameListItemPlayTime(play_time),
        new GameListItem(patch_versions),
    };
}
} // Anonymous namespace

// Loose ExeFS dumps (<game>/exefs/main, <game>/base/exefs/main and <game>/updates[/N]/exefs/main)
// have no control data, so they are named after their game folder.
QString LooseExeFSName(const std::string& physical_name) {
    if (!IsExtractedNCAMain(physical_name)) {
        return {};
    }

    QString name = ExtractedGameDirectory(physical_name).dirName();
    // Dump tools often add the title ID: "Some Game [0400000000000000]".
    static const QRegularExpression title_id{QStringLiteral(R"(\s*\[[0-9A-Fa-f]{16}\]$)")};
    return name.remove(title_id);
}

QString LooseDumpTitle(const std::string& physical_name, u64 title_id) {
    const QString folder_name = LooseExeFSName(physical_name);
    if (folder_name.isEmpty() || !UISettings::values.store_game_metadata.GetValue()) {
        return folder_name;
    }

    const auto cached = ReadStoreCache(title_id);
    return cached && !cached->name.empty() ? QString::fromStdString(cached->name) : folder_name;
}

QString LooseDumpVersion(const std::string& physical_name, Loader::AppLoader& loader) {
    if (LooseExeFSName(physical_name).isEmpty()) {
        return {};
    }

    std::string version;
    if (loader.ReadDisplayVersion(version) == Loader::ResultStatus::Success && !version.empty()) {
        return QString::fromStdString(version);
    }

    QDir dir = QFileInfo(QString::fromStdString(physical_name)).dir();
    if (!dir.cdUp()) {
        return {};
    }
    const QString folder = dir.dirName();
    if (!ParseVersionFolder(folder.toStdString()).has_value() || !dir.cdUp() ||
        dir.dirName().compare(QStringLiteral("updates"), Qt::CaseInsensitive) != 0) {
        return {};
    }
    return QStringLiteral("v%1").arg(folder);
}

GameListWorker::GameListWorker(FileSys::VirtualFilesystem vfs_,
                               FileSys::ManualContentProvider* provider_,
                               QVector<UISettings::GameDir>& game_dirs_,
                               const PlayTime::PlayTimeManager& play_time_manager_,
                               Core::System& system_)
    : vfs{std::move(vfs_)}, provider{provider_}, game_dirs{game_dirs_},
      play_time_manager{play_time_manager_},
      system{system_} {
    // We want the game list to manage our lifetime.
    setAutoDelete(false);
}

GameListWorker::~GameListWorker() {
    this->disconnect();
    Stop();
}

void GameListWorker::Stop() {
    if (!stop_requested.exchange(true)) {
        processing_completed.Wait();
    }
}

void GameListWorker::ProcessEvents(GameListModel* model) {
    // An event may spin a nested event loop that replaces this worker, in which case stop.
    while (model->current_worker.get() == this) {
        std::function<void(GameListModel*)> func;
        {
            // Lock queue to protect concurrent modification.
            std::scoped_lock lk(lock);

            // If we can't pop a function, return.
            if (queued_events.empty()) {
                return;
            }

            // Pop a function.
            func = std::move(queued_events.back());
            queued_events.pop_back();
        }

        // Run the function.
        func(model);
    }
}

template <typename F>
void GameListWorker::RecordEvent(F&& func) {
    {
        // Lock queue to protect concurrent modification.
        std::scoped_lock lk(lock);

        // Add the function into the front of the queue.
        queued_events.emplace_front(std::move(func));
    }

    // Data now available.
    emit DataAvailable();
}

void GameListWorker::AddTitlesToGameList(GameListDir* parent_dir) {
    using namespace FileSys;

    const auto& cache = system.GetContentProviderUnion();

    auto installed_games = cache.ListEntriesFilterOrigin(std::nullopt, TitleType::Application,
                                                         ContentRecordType::Program);

    if (parent_dir->type() == static_cast<int>(GameListItemType::SdmcDir)) {
        installed_games = cache.ListEntriesFilterOrigin(
            ContentProviderUnionSlot::SDMC, TitleType::Application, ContentRecordType::Program);
    } else if (parent_dir->type() == static_cast<int>(GameListItemType::UserNandDir)) {
        installed_games = cache.ListEntriesFilterOrigin(
            ContentProviderUnionSlot::UserNAND, TitleType::Application, ContentRecordType::Program);
    } else if (parent_dir->type() == static_cast<int>(GameListItemType::SysNandDir)) {
        installed_games = cache.ListEntriesFilterOrigin(
            ContentProviderUnionSlot::SysNAND, TitleType::Application, ContentRecordType::Program);
    }

    for (const auto& [slot, game] : installed_games) {
        if (slot == ContentProviderUnionSlot::FrontendManual) {
            continue;
        }

        const auto file = cache.GetEntryUnparsed(game.title_id, game.type);
        std::unique_ptr<Loader::AppLoader> loader = Loader::GetLoader(system, file);
        if (!loader) {
            continue;
        }

        std::vector<u8> icon;
        std::string name;
        u64 program_id = 0;
        const auto result = loader->ReadProgramId(program_id);

        if (result != Loader::ResultStatus::Success) {
            continue;
        }

        const PatchManager patch{program_id, system.GetFileSystemController(),
                                 system.GetContentProvider()};
        LOG_INFO(Frontend, "PatchManager initiated for id {:X}", program_id);
        const auto control = cache.GetEntry(game.title_id, ContentRecordType::Control);
        if (control != nullptr) {
            GetMetadataFromControlNCA(patch, *control, icon, name);
        }

        auto entry = MakeGameListEntry(file->GetFullPath(), name, file->GetSize(), icon, *loader,
                                       program_id, play_time_manager, patch);
        RecordEvent([=](GameListModel* model) { model->AddEntry(entry, parent_dir); });
    }
}

void GameListWorker::ScanFileSystem(ScanTarget target, const std::string& dir_path, bool deep_scan,
                                    GameListDir* parent_dir) {
    const auto process_candidate = [this, target,
                                    parent_dir](const std::filesystem::path& path) {
        const auto physical_name = Common::FS::PathToUTF8String(path);
        if (target == ScanTarget::PopulateGameList && IsExtractedNCAMain(physical_name) &&
            HasNewerLooseDump(path)) {
            return;
        }

        const auto file = vfs->OpenFile(physical_name, FileSys::OpenMode::Read);
        if (!file) {
            return;
        }

        auto loader = Loader::GetLoader(system, file);
        if (!loader) {
            return;
        }

        const auto file_type = loader->GetFileType();
        if (file_type == Loader::FileType::Unknown || file_type == Loader::FileType::Error) {
            return;
        }

        if (target == ScanTarget::PopulateGameList &&
            (file_type == Loader::FileType::XCI || file_type == Loader::FileType::XCZ ||
             file_type == Loader::FileType::NSP || file_type == Loader::FileType::NSZ) &&
            !Loader::IsBootableGameContainer(file, file_type)) {
            return;
        }

        u64 program_id = 0;
        const auto res2 = loader->ReadProgramId(program_id);

        if (target == ScanTarget::FillManualContentProvider) {
            if (res2 == Loader::ResultStatus::Success && file_type == Loader::FileType::NCA) {
                provider->AddEntry(FileSys::TitleType::Application,
                                   FileSys::GetCRTypeFromNCAType(FileSys::NCA{file}.GetType()),
                                   program_id, file);
            } else if (Settings::values.ext_content_from_game_dirs.GetValue() &&
                       (file_type == Loader::FileType::XCI ||
                        file_type == Loader::FileType::XCZ ||
                        file_type == Loader::FileType::NSP ||
                        file_type == Loader::FileType::NSZ)) {
                void(provider->AddEntriesFromContainer(file));
            }
        } else {
            std::vector<u64> program_ids;
            loader->ReadProgramIds(program_ids);

            const auto addEntry = [this, physical_name,
                                   parent_dir](std::unique_ptr<Loader::AppLoader>& app_loader,
                                               const u64 id) {
                std::vector<u8> icon;
                [[maybe_unused]] const auto res1 = app_loader->ReadIcon(icon);

                std::string name = " ";
                const auto res3 = app_loader->ReadTitle(name);
                const bool needs_name =
                    res3 != Loader::ResultStatus::Success || name.empty() || name == " ";

                QString dump_version;
                if (IsExtractedNCAMain(physical_name) &&
                    !LooseExeFSName(physical_name).isEmpty()) {
                    if (UISettings::values.store_game_metadata.GetValue() &&
                        (needs_name || icon.empty())) {
                        if (const auto store = FindStoreMetadata(id, stop_requested)) {
                            if (icon.empty()) {
                                icon = store->icon;
                            }
                            if (needs_name) {
                                name = store->name;
                            }
                        }
                    }
                    if (name.empty() || name == " ") {
                        name = LooseExeFSName(physical_name).toStdString();
                    }

                    dump_version = LooseDumpVersion(physical_name, *app_loader);
                    if (dump_version.isEmpty()) {
                        dump_version = QObject::tr("Unknown");
                    }
                }

                const FileSys::PatchManager patch{id, system.GetFileSystemController(),
                                                  system.GetContentProvider()};

                const auto size = app_loader->GetFileType() == Loader::FileType::DeconstructedRomDirectory
                    ? ExtractedGameSize(physical_name, stop_requested)
                    : Common::FS::GetSize(physical_name);
                if (stop_requested) return;
                auto entry = MakeGameListEntry(physical_name, name, size, icon, *app_loader,
                                               id, play_time_manager, patch, dump_version);

                RecordEvent([=](GameListModel* model) { model->AddEntry(entry, parent_dir); });
            };

            if (res2 == Loader::ResultStatus::Success && program_ids.size() > 1 &&
                (file_type == Loader::FileType::XCI || file_type == Loader::FileType::XCZ ||
                 file_type == Loader::FileType::NSP || file_type == Loader::FileType::NSZ)) {
                for (const auto id : program_ids) {
                    // dravee suggested this, only viable way to
                    // not show sub-games in qlaunch for now.
                    if ((id & 0xFFF) != 0) {
                        continue;
                    }
                    loader = Loader::GetLoader(system, file, id);
                    if (!loader) {
                        continue;
                    }

                    addEntry(loader, id);
                }
            } else {
                addEntry(loader, program_id);
            }
        }
    };

    const auto callback = [this, target,
                           &process_candidate](const std::filesystem::path& path) -> bool {
        if (stop_requested) return false;
        if (Common::FS::IsDir(path)) {
            watch_list.append(QString::fromStdString(Common::FS::PathToUTF8String(path)));
        } else {
            // The provider pass takes only containers, so it skips the slow loader of a loose
            // dump.
            const auto name = Common::FS::PathToUTF8String(path);
            if (HasSupportedFileExtension(name) ||
                (target == ScanTarget::PopulateGameList && IsExtractedNCAMain(name))) {
                process_candidate(path);
            }
        }
        return true;
    };
    if (deep_scan) {
        WalkGameFolder(std::filesystem::path{Common::FS::ToU8String(dir_path)}, callback);
    } else {
        Common::FS::IterateDirEntries(dir_path, callback, Common::FS::DirEntryFilter::File);
        const auto scan_exefs = [&](const QDir& directory) {
            const auto main = directory.filePath(QStringLiteral("main"));
            if (target == ScanTarget::PopulateGameList && QFileInfo::exists(main)) {
                process_candidate(std::filesystem::path{Common::FS::ToU8String(main.toStdString())});
            }
            watch_list.append(directory.absolutePath());
        };
        const auto scan_title = [&](const QDir& title) {
            const QDir updates{title.filePath(QStringLiteral("updates"))};
            auto versions = updates.entryList(QDir::Dirs | QDir::NoDotAndDotDot);
            std::sort(versions.begin(), versions.end(), [](const QString& a, const QString& b) {
                return a.toULongLong() > b.toULongLong();
            });
            for (const auto& version : versions) {
                const QDir exefs{updates.filePath(version + QStringLiteral("/exefs"))};
                if (QFileInfo::exists(exefs.filePath(QStringLiteral("main")))) {
                    scan_exefs(exefs);
                    return;
                }
            }
            for (const auto* relative : {"updates/exefs", "exefs", "base/exefs"}) {
                const QDir exefs{title.filePath(QString::fromLatin1(relative))};
                if (QFileInfo::exists(exefs.filePath(QStringLiteral("main")))) {
                    scan_exefs(exefs);
                    return;
                }
            }
        };
        const QDir root{QString::fromStdString(dir_path)};
        scan_title(root);
        for (const auto& child : root.entryList(QDir::Dirs | QDir::NoDotAndDotDot)) {
            if (stop_requested) {
                break;
            }
            if (child != QStringLiteral("exefs") && child != QStringLiteral("romfs") &&
                child != QStringLiteral("updates") && child != QStringLiteral("base")) {
                scan_title(QDir{root.filePath(child)});
            }
        }
    }
}

void GameListWorker::run() {
    const auto scan_start = std::chrono::steady_clock::now();
    watch_list.clear();
    provider->ClearAllEntries();

    const auto DirEntryReady = [&](GameListDir* game_list_dir) {
        RecordEvent([=](GameListModel* model) { model->AddDirEntry(game_list_dir); });
    };

    for (UISettings::GameDir& game_dir : game_dirs) {
        if (stop_requested) {
            break;
        }

        GameListDir* game_list_dir;
        bool scan = false;

        if (game_dir.path == std::string("SDMC")) {
            game_list_dir = new GameListDir(game_dir, GameListItemType::SdmcDir);
        } else if (game_dir.path == std::string("UserNAND")) {
            game_list_dir = new GameListDir(game_dir, GameListItemType::UserNandDir);
        } else if (game_dir.path == std::string("SysNAND")) {
            game_list_dir = new GameListDir(game_dir, GameListItemType::SysNandDir);
        } else {
            const QString qpath = QString::fromStdString(game_dir.path);
            if (QDir(qpath).exists()) {
                watch_list.append(qpath);
            }

            game_list_dir = new GameListDir(game_dir);
            scan = true;
        }

        DirEntryReady(game_list_dir);
        if (scan) {
            ScanFileSystem(ScanTarget::FillManualContentProvider, game_dir.path, game_dir.deep_scan,
                           game_list_dir);
            ScanFileSystem(ScanTarget::PopulateGameList, game_dir.path, game_dir.deep_scan,
                           game_list_dir);
        } else {
            AddTitlesToGameList(game_list_dir);
        }
    }

    LOG_INFO(Frontend, "Game list scan took {} ms",
             std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() -
                                                                   scan_start)
                 .count());
    RecordEvent([this](GameListModel* model) { model->DonePopulating(watch_list); });
    processing_completed.Set();
}

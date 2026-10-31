// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

// SPDX-FileCopyrightText: Copyright 2018 yuzu Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <atomic>
#include <deque>
#include <memory>
#include <string>

#include <QList>
#include <QObject>
#include <QRunnable>
#include <QString>

#include "common/thread.h"
#include "core/file_sys/registered_cache.h"
#include "frontend_common/play_time_manager.h"
#include "qt_common/config/uisettings.h"

namespace Core {
class System;
}

class GameListDir;
class GameListModel;
class QStandardItem;

namespace FileSys {
class NCA;
class VfsFilesystem;
} // namespace FileSys

namespace Loader {
class AppLoader;
}

/// Returns the game name of a loose ExeFS dump, or an empty string for any other path.
QString LooseExeFSName(const std::string& physical_name);

/// Returns the name of a loose ExeFS dump: the cached store name if the store setting is on, or
/// else the game folder name. Returns an empty string for any other path.
QString LooseDumpTitle(const std::string& physical_name, u64 title_id);

/// Returns the version of a loose ExeFS dump: the loader value, or v<N> from an updates/<N> folder.
/// Returns an empty string if neither exists. The v<N> value is for display only.
QString LooseDumpVersion(const std::string& physical_name, Loader::AppLoader& loader);

/**
 * Asynchronous worker object for populating the game list.
 * Communicates with other threads through Qt's signal/slot system.
 */
class GameListWorker : public QObject, public QRunnable {
    Q_OBJECT

public:
    explicit GameListWorker(std::shared_ptr<FileSys::VfsFilesystem> vfs_,
                            FileSys::ManualContentProvider* provider_,
                            QVector<UISettings::GameDir>& game_dirs_,
                            const PlayTime::PlayTimeManager& play_time_manager_,
                            Core::System& system_);
    ~GameListWorker() override;

    /// Starts the processing of directory tree information.
    void run() override;

public:
    /**
     * Synchronously processes any events queued by the worker.
     *
     * AddDirEntry is called on the model for every discovered directory.
     * AddEntry is called on the model for every discovered program.
     * DonePopulating is called on the model when processing completes.
     */
    void ProcessEvents(GameListModel* model);

signals:
    void DataAvailable();

private:
    template <typename F>
    void RecordEvent(F&& func);

private:
    void AddTitlesToGameList(GameListDir* parent_dir);

    enum class ScanTarget {
        FillManualContentProvider,
        PopulateGameList,
    };

    void ScanFileSystem(ScanTarget target, const std::string& dir_path, bool deep_scan,
                        GameListDir* parent_dir);

    std::shared_ptr<FileSys::VfsFilesystem> vfs;
    FileSys::ManualContentProvider* provider;
    QVector<UISettings::GameDir>& game_dirs;
    const PlayTime::PlayTimeManager& play_time_manager;

    QStringList watch_list;

    std::mutex lock;
    std::condition_variable cv;
    std::deque<std::function<void(GameListModel*)>> queued_events;
    std::atomic_bool stop_requested = false;
    Common::Event processing_completed;

    Core::System& system;
};

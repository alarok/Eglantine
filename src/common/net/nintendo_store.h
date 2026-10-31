// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include <atomic>
#include <chrono>
#include <functional>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <vector>

#include "common/common_types.h"

namespace Common::Net {

struct StoreProduct {
    std::string name;
    /// The path of the square icon on assets.nintendo.com, as a 256x256 JPEG.
    std::string icon_path;
};

struct StoreMetadata {
    std::string name;
    std::vector<u8> icon;
};

enum class StoreFetchStatus {
    Success,
    /// The server answered with an error, such as 404 for an unknown title.
    Rejected,
    /// The request did not reach a server.
    Unreachable,
    /// The stop flag ended the request.
    Cancelled,
};

using StoreFetcher = std::function<StoreFetchStatus(
    const std::string& host, const std::string& path, const std::atomic_bool& stop,
    std::string& out_body)>;

/// Reads the name and the square icon of the product on a store page. The page is the only source.
/// It is not a documented API, so this returns nothing if the page changes its structure.
std::optional<StoreProduct> ParseStoreProductPage(std::string_view page);

/// Requests a URL with short timeouts. The default fetcher of a game list lookup.
StoreFetchStatus FetchStoreUrl(const std::string& host, const std::string& path,
                               const std::atomic_bool& stop, std::string& out_body);

/// Finds the name and icon of a title in the Nintendo store. A failed request can block the caller
/// for some seconds, so it limits the repeated requests. It is not thread-safe.
class StoreLookup {
public:
    explicit StoreLookup(StoreFetcher fetcher_);

    std::optional<StoreMetadata> Find(u64 title_id, const std::atomic_bool& stop);

private:
    StoreFetcher fetcher;
    std::set<u64> missing_titles;
    std::chrono::steady_clock::time_point next_network_try{};
};

} // namespace Common::Net

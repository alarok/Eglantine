// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <algorithm>
#include <exception>
#include <utility>

#include <boost/algorithm/string/replace.hpp>
#include <fmt/format.h>
#include <nlohmann/json.hpp>

#include "common/httplib.h"
#include "common/logging.h"
#include "common/net/nintendo_store.h"

#ifdef YUZU_BUNDLED_OPENSSL
#include <openssl/cert.h>
#endif

namespace Common::Net {

namespace {

constexpr std::string_view StorePageHost = "https://ec.nintendo.com";
constexpr std::string_view IconHost = "https://assets.nintendo.com";
constexpr std::string_view IconQuality = "q_auto/f_auto";
constexpr std::string_view IconFormat = "f_jpg,q_90,w_256";
constexpr auto NetworkRetryDelay = std::chrono::minutes{5};

// Decodes the JSON string that starts at `start`. `out_end` receives the position of its closing
// quote.
std::optional<std::string> ReadJsonString(std::string_view page, std::size_t start,
                                          std::size_t& out_end) {
    auto end = start;
    while (end < page.size() && page[end] != '"') {
        end += page[end] == '\\' ? 2 : 1;
    }
    if (end >= page.size()) {
        return std::nullopt;
    }
    out_end = end;

    try {
        return nlohmann::json::parse(fmt::format("\"{}\"", page.substr(start, end - start)))
            .get<std::string>();
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

} // Anonymous namespace

std::optional<StoreProduct> ParseStoreProductPage(std::string_view page) {
    constexpr std::string_view product_key = R"("product":{"name":")";
    constexpr std::string_view nsuid_key = R"(,"nsuid":")";
    constexpr std::string_view next_product_key = R"("__typename":"Product",)";
    constexpr std::string_view icon_key =
        R"x(productImage({\"shape\":\"square\"})":{"__typename":"CloudinaryAsset","url":")x";

    const auto product = page.find(product_key);
    if (product == page.npos) {
        return std::nullopt;
    }

    std::size_t name_end = 0;
    auto name = ReadJsonString(page, product + product_key.size(), name_end);
    if (!name || name->empty()) {
        return std::nullopt;
    }
    boost::replace_all(*name, "\xE2\x84\xA2", ""); // Trademark sign
    boost::replace_all(*name, "\xC2\xAE", "");     // Registered sign

    const auto nsuid_pos = page.find(nsuid_key, name_end);
    if (nsuid_pos == page.npos) {
        return std::nullopt;
    }
    std::size_t nsuid_end = 0;
    const auto nsuid = ReadJsonString(page, nsuid_pos + nsuid_key.size(), nsuid_end);
    if (!nsuid || nsuid->empty()) {
        return std::nullopt;
    }

    // The page holds entries for related products too. The icon must be inside the entry of the
    // product of this page.
    const auto entry = page.find(fmt::format(R"("nsuid":"{}","name")", *nsuid));
    if (entry == page.npos) {
        return std::nullopt;
    }
    const auto next_product = page.find(next_product_key, entry);
    const auto icon = page.find(icon_key, entry);
    if (icon == page.npos || (next_product != page.npos && icon > next_product)) {
        return std::nullopt;
    }

    std::size_t icon_end = 0;
    const auto icon_url = ReadJsonString(page, icon + icon_key.size(), icon_end);
    if (!icon_url || !icon_url->starts_with(fmt::format("{}/", IconHost)) ||
        icon_url->find(IconQuality) == std::string::npos) {
        return std::nullopt;
    }

    auto icon_path = icon_url->substr(IconHost.size());
    boost::replace_first(icon_path, IconQuality, IconFormat);
    return StoreProduct{std::move(*name), std::move(icon_path)};
}

StoreFetchStatus FetchStoreUrl(const std::string& host, const std::string& path,
                               const std::atomic_bool& stop, std::string& out_body) {
    try {
        httplib::Client client{host};
        client.set_connection_timeout(5);
        client.set_read_timeout(10);
        client.set_write_timeout(5);
        client.set_follow_location(true);
#ifdef YUZU_BUNDLED_OPENSSL
        client.load_ca_cert_store(kCert, sizeof(kCert));
#endif

        httplib::Request request{
            .method = "GET",
            .path = path,
        };
        request.download_progress = [&stop](std::size_t, std::size_t) { return !stop.load(); };

        const auto result = client.send(request);
        if (!result) {
            LOG_INFO(Frontend, "Store request to {}{} failed: {}", host, path,
                     httplib::to_string(result.error()));
            return result.error() == httplib::Error::Canceled ? StoreFetchStatus::Cancelled
                                                              : StoreFetchStatus::Unreachable;
        }
        if (result->status >= 400) {
            LOG_INFO(Frontend, "Store request to {}{} returned {}", host, path, result->status);
            return StoreFetchStatus::Rejected;
        }

        out_body = result->body;
        return StoreFetchStatus::Success;
    } catch (const std::exception& e) {
        LOG_WARNING(Frontend, "Store request to {}{} failed: {}", host, path, e.what());
        return StoreFetchStatus::Unreachable;
    }
}

StoreLookup::StoreLookup(StoreFetcher fetcher_) : fetcher{std::move(fetcher_)} {}

std::optional<StoreMetadata> StoreLookup::Find(u64 title_id, const std::atomic_bool& stop) {
    if (missing_titles.contains(title_id) ||
        std::chrono::steady_clock::now() < next_network_try) {
        return std::nullopt;
    }

    // Returns true if the caller can go on. Records the failure if not.
    const auto check = [this, title_id](StoreFetchStatus status) {
        switch (status) {
        case StoreFetchStatus::Success:
            return true;
        case StoreFetchStatus::Rejected:
            missing_titles.insert(title_id);
            return false;
        case StoreFetchStatus::Unreachable:
            next_network_try = std::chrono::steady_clock::now() + NetworkRetryDelay;
            return false;
        case StoreFetchStatus::Cancelled:
            return false;
        }
        return false;
    };

    std::string page;
    const auto page_path = fmt::format("/apps/{:016X}/US", title_id);
    if (!check(fetcher(std::string{StorePageHost}, page_path, stop, page))) {
        return std::nullopt;
    }

    const auto product = ParseStoreProductPage(page);
    if (!product) {
        LOG_INFO(Frontend, "The store page of {:016X} has no usable product entry", title_id);
        missing_titles.insert(title_id);
        return std::nullopt;
    }

    std::string icon;
    if (!check(fetcher(std::string{IconHost}, product->icon_path, stop, icon))) {
        return std::nullopt;
    }

    return StoreMetadata{product->name, std::vector<u8>(icon.begin(), icon.end())};
}

} // namespace Common::Net

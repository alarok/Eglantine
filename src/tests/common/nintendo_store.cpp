// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <catch2/catch_test_macros.hpp>

#include <atomic>
#include <string>
#include <vector>

#include "common/net/nintendo_store.h"

using namespace Common::Net;

namespace {

// These excerpts keep the structure of the Donkey Kong Bananza page from 2026-10-31.
constexpr const char* OwnEntry =
    R"("Product:{\"sku\":\"7100096809\"}":{"__typename":"Product","nsuid":"70010000096809",)"
    R"("name":"Donkey Kong™ Bananza","x":1,"productImage":{"url":"https://example.com/wide"},)";
constexpr const char* OwnIcon =
    R"x("productImage({\"shape\":\"square\"})":{"__typename":"CloudinaryAsset","url":)x"
    R"("https://assets.nintendo.com/image/fetch/q_auto/f_auto/https://atum.example/own_1024"},)";
constexpr const char* OtherEntry =
    R"("Product:{\"sku\":\"7100119859\"}":{"__typename":"Product","nsuid":"70010000119859",)"
    R"x("name":"Other Game","productImage({\"shape\":\"square\"})":{"__typename":)x"
    R"("CloudinaryAsset","url":"https://assets.nintendo.com/image/upload/q_auto/f_auto/other"},)";
constexpr const char* PageProduct =
    R"("pageCategory":"Store:Products","product":{"name":"Donkey Kong™ Bananza",)"
    R"("sku":"7100096809","nsuid":"70010000096809"}},)";

std::string PageWith(std::initializer_list<const char*> parts) {
    std::string page;
    for (const char* const part : parts) {
        page += part;
    }
    return page;
}

// Answers requests from a fixed script and records them.
struct FakeStore {
    StoreFetchStatus page_status = StoreFetchStatus::Success;
    StoreFetchStatus icon_status = StoreFetchStatus::Success;
    std::string page = PageWith({PageProduct, OtherEntry, OwnEntry, OwnIcon, OtherEntry});
    std::vector<std::string> requests;

    StoreFetcher Fetcher() {
        return [this](const std::string& host, const std::string& path, const std::atomic_bool&,
                      std::string& out) {
            requests.push_back(host + path);
            if (host == "https://ec.nintendo.com") {
                out = page;
                return page_status;
            }
            out = "jpeg bytes";
            return icon_status;
        };
    }
};

} // namespace

TEST_CASE("A store page gives the name and icon of its own product", "[common][net]") {
    const auto page = PageWith({PageProduct, OtherEntry, OwnEntry, OwnIcon, OtherEntry});
    const auto product = ParseStoreProductPage(page);
    REQUIRE(product.has_value());
    REQUIRE(product->name == "Donkey Kong Bananza");
    REQUIRE(product->icon_path == "/image/fetch/f_jpg,q_90,w_256/https://atum.example/own_1024");
}

TEST_CASE("A store page does not borrow the icon of a related product", "[common][net]") {
    const auto page = PageWith({PageProduct, OwnEntry, OtherEntry});
    REQUIRE_FALSE(ParseStoreProductPage(page).has_value());
}

TEST_CASE("A page without a product entry gives no result", "[common][net]") {
    REQUIRE_FALSE(ParseStoreProductPage("<html>Not found</html>").has_value());
    REQUIRE_FALSE(ParseStoreProductPage(PageWith({OwnEntry, OwnIcon})).has_value());
}

TEST_CASE("A store page cannot send the icon request to another host", "[common][net]") {
    const std::string page =
        std::string{PageProduct} + OwnEntry +
        R"x("productImage({\"shape\":\"square\"})":{"__typename":"CloudinaryAsset",)x"
        R"("url":"https://evil.example/q_auto/f_auto/x"},)";
    REQUIRE_FALSE(ParseStoreProductPage(page).has_value());
}

TEST_CASE("A lookup requests the store page of the title ID and then the icon", "[common][net]") {
    const std::atomic_bool stop{false};
    FakeStore store;
    StoreLookup lookup{store.Fetcher()};
    const auto metadata = lookup.Find(0x040074A01BF12000, stop);
    REQUIRE(metadata.has_value());
    REQUIRE(metadata->name == "Donkey Kong Bananza");
    REQUIRE(metadata->icon == std::vector<u8>{'j', 'p', 'e', 'g', ' ', 'b', 'y', 't', 'e', 's'});
    REQUIRE(store.requests ==
            std::vector<std::string>{
                "https://ec.nintendo.com/apps/040074A01BF12000/US",
                "https://assets.nintendo.com/image/fetch/f_jpg,q_90,w_256/"
                "https://atum.example/own_1024"});
}

TEST_CASE("A lookup stops all requests for a time after a network failure", "[common][net]") {
    const std::atomic_bool stop{false};
    FakeStore store;
    store.page_status = StoreFetchStatus::Unreachable;
    StoreLookup lookup{store.Fetcher()};
    REQUIRE_FALSE(lookup.Find(1, stop).has_value());
    REQUIRE_FALSE(lookup.Find(2, stop).has_value());
    REQUIRE(store.requests.size() == 1);
}

TEST_CASE("A lookup asks once for a title that the store does not have", "[common][net]") {
    const std::atomic_bool stop{false};
    FakeStore store;
    store.page_status = StoreFetchStatus::Rejected;
    StoreLookup lookup{store.Fetcher()};
    REQUIRE_FALSE(lookup.Find(1, stop).has_value());
    REQUIRE_FALSE(lookup.Find(1, stop).has_value());
    REQUIRE(store.requests.size() == 1);

    // Other titles still get a request.
    REQUIRE_FALSE(lookup.Find(2, stop).has_value());
    REQUIRE(store.requests.size() == 2);
}

TEST_CASE("A cancelled lookup can run again", "[common][net]") {
    const std::atomic_bool stop{false};
    FakeStore store;
    store.page_status = StoreFetchStatus::Cancelled;
    StoreLookup lookup{store.Fetcher()};
    REQUIRE_FALSE(lookup.Find(1, stop).has_value());

    store.page_status = StoreFetchStatus::Success;
    REQUIRE(lookup.Find(1, stop).has_value());
}

TEST_CASE("A closed port is a network failure", "[common][net]") {
    const std::atomic_bool stop{false};
    std::string body;
    REQUIRE(FetchStoreUrl("http://127.0.0.1:1", "/", stop, body) ==
            StoreFetchStatus::Unreachable);
}

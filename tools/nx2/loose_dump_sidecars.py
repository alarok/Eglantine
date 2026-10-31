#!/usr/bin/env python3
# Write control.nacp and icon.png into the game folder of a loose dump. The emulator shows them in
# the game list and in the window title. The title ID comes from main.npdm. The name and the square
# icon come from the Nintendo store page of that title ID.
#
# Usage: loose_dump_sidecars.py <game folder> [--version X.Y.Z] [--name NAME] [--force]
#
# Give --version only if you know the version. The game receives this value from GetDisplayVersion.
# Without it, the emulator reads the version from the RomFS, or shows v<N> from updates/<N>.
import argparse
import pathlib
import re
import struct
import sys
import urllib.request

APPS_URL = "https://ec.nintendo.com/apps/{:016X}/US"
USER_AGENT = {"User-Agent": "Mozilla/5.0"}
PRODUCT = re.compile(r'"product":\{"name":"([^"]+)","sku":"\d+","nsuid":"(\d+)"\}')
SQUARE_ICON = re.compile(
    r'productImage\(\{\\"shape\\":\\"square\\"\}\)":\{"__typename":"CloudinaryAsset","url":"([^"]+)"')
NACP_SIZE = 0x4000
NACP_VERSION_OFFSET = 0x3060
LANGUAGE_COUNT = 16
LANGUAGE_ENTRY_SIZE = 0x300
NAME_SIZE = 0x200


def find_npdm(game):
    candidates = [game / "exefs", game / "base" / "exefs"]
    candidates += sorted((game / "updates").glob("*/exefs"))
    candidates += [game]
    for folder in candidates:
        if (folder / "main.npdm").is_file():
            return folder / "main.npdm"
    sys.exit(f"No main.npdm in the known layouts of {game}")


def read_title_id(npdm):
    data = npdm.read_bytes()
    aci_offset = struct.unpack_from("<I", data, 0x70)[0]
    if data[:4] != b"META" or data[aci_offset:aci_offset + 4] != b"ACI0":
        sys.exit(f"{npdm} is not a valid NPDM file")
    return struct.unpack_from("<Q", data, aci_offset + 0x10)[0]


def fetch(url):
    request = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read()


def read_store_page(title_id):
    page = fetch(APPS_URL.format(title_id)).decode("utf8", "replace")
    product = PRODUCT.search(page)
    if product is None:
        sys.exit(f"The store has no product page for {title_id:016X}")
    name = re.sub("[™®]", "", product.group(1))
    # The first match after the product entry belongs to this product. Other matches are related
    # products on the same page.
    entry = page.find(f'"nsuid":"{product.group(2)}","name"')
    icon = SQUARE_ICON.search(page, entry) if entry >= 0 else None
    if icon is None:
        sys.exit(f"The store page of {title_id:016X} has no square icon")
    return name, icon.group(1)


def make_nacp(name, version):
    nacp = bytearray(NACP_SIZE)
    encoded_name = name.encode("utf8")[:NAME_SIZE - 1]
    for index in range(LANGUAGE_COUNT):
        offset = index * LANGUAGE_ENTRY_SIZE
        nacp[offset:offset + len(encoded_name)] = encoded_name
    encoded_version = version.encode("ascii")[:0xF]
    nacp[NACP_VERSION_OFFSET:NACP_VERSION_OFFSET + len(encoded_version)] = encoded_version
    return bytes(nacp)


def write_new(path, data, force):
    if path.exists() and not force:
        print(f"keep {path} (use --force to replace it)")
        return
    path.write_bytes(data)
    print(f"wrote {path} ({len(data)} bytes)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("game", type=pathlib.Path)
    parser.add_argument("--version", default="")
    parser.add_argument("--name")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")

    title_id = read_title_id(find_npdm(args.game))
    name, icon_url = read_store_page(title_id)
    name = args.name or name
    print(f"{title_id:016X} {name} version={args.version or '(not set)'}")

    icon = fetch(icon_url.replace("q_auto/f_auto", "f_png,w_512"))
    if not icon.startswith(b"\x89PNG"):
        sys.exit(f"The icon is not a PNG file: {icon_url}")

    write_new(args.game / "control.nacp", make_nacp(name, args.version), args.force)
    write_new(args.game / "icon.png", icon, args.force)


if __name__ == "__main__":
    main()

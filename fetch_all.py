# -*- coding: utf-8 -*-
"""Fetch daily hot video topics and write normalized JSON files."""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


DATA_DIR = Path("data")
COVERS_DIR = DATA_DIR / "covers"
BEIJING_TZ = timezone(timedelta(hours=8))

# Shared opener with a cookie jar so Bilibili returns a buvid3 cookie before
# search calls (greatly reduces -412 risk-control responses on shared runners).
COOKIE_JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIE_JAR))
_OPENER_READY = False

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)

# Xiaohongshu's feed hands out a single shared promo badge PNG for every row,
# not a real cover; treat it (and empty covers) as "no cover".
GENERIC_COVER_MARKERS = ("picasso-static.xiaohongshu.com",)

# Platforms whose hot list is a keyword/topic rank with no bundled artwork.
# We enrich these rows with a real video-frame thumbnail from a keyword search.
COVER_ENRICH_SOURCES = ("kuaishou", "xiaohongshu")


SOURCES = [
    {
        "id": "douyin",
        "name": "抖音",
        "urls": [
            "https://v2.xxapi.cn/api/douyinhot",
            "{API_BASE}/douyin",
        ],
    },
    {
        "id": "kuaishou",
        "name": "快手",
        "urls": [
            "https://api.tcslw.cn/api/hotlist/kuaishou",
            "{API_BASE}/kuaishou",
        ],
    },
    {
        "id": "xiaohongshu",
        "name": "小红书",
        "urls": [
            "https://uapis.cn/api/v1/misc/hotboard?type=xiaohongshu",
            "{XIAOHONGSHU_API_URL}",
            "{API_BASE}/xiaohongshu",
        ],
    },
]


def now_iso() -> str:
    return datetime.now(BEIJING_TZ).isoformat(timespec="seconds")


def build_url(template: str) -> str | None:
    api_base = os.getenv("API_BASE", "https://api-hot.imsyy.top").rstrip("/")
    values = {
        "API_BASE": api_base,
        "XIAOHONGSHU_API_URL": os.getenv("XIAOHONGSHU_API_URL", "").strip(),
    }
    url = template.format(**values)
    return url if url.startswith("http") else None


def fetch_json(url: str, referer: str = "") -> Any:
    headers = {
        "User-Agent": UA,
        "Accept": "application/json,text/plain,*/*",
    }
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with OPENER.open(req, timeout=25) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def warm_up_bilibili() -> None:
    global _OPENER_READY
    if _OPENER_READY:
        return
    try:
        req = urllib.request.Request(
            "https://www.bilibili.com/",
            headers={"User-Agent": UA, "Accept": "text/html"},
        )
        with OPENER.open(req, timeout=20) as resp:
            resp.read(2048)
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    _OPENER_READY = True


def bili_cover_url(keyword: str) -> str:
    """Return a real Bilibili video-frame thumbnail URL for a search keyword."""
    keyword = (keyword or "").strip()
    if not keyword:
        return ""
    warm_up_bilibili()
    try:
        url = (
            "https://api.bilibili.com/x/web-interface/search/all/v2?keyword="
            + urllib.parse.quote(keyword)
        )
        payload = fetch_json(url, referer="https://www.bilibili.com/")
        for block in (payload.get("data") or {}).get("result") or []:
            if block.get("result_type") != "video":
                continue
            for video in block.get("data") or []:
                pic = video.get("pic")
                if not pic:
                    continue
                pic = str(pic)
                if pic.startswith("//"):
                    pic = "https:" + pic
                pic = pic.replace("http://", "https://", 1)
                # Small cropped webp so each downloaded file stays light.
                return pic + "@480w_270h_1c.webp"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        print(f"  bili search miss for {keyword!r}: {exc}")
    return ""


def download_cover(source_id: str, keyword: str) -> str:
    """Download a real cover into data/covers/ and return its relative path.

    Bilibili's image CDN rejects hotlinking from github.io, so the image is
    fetched server-side (no Referer) and served same-origin with the site.
    """
    url = bili_cover_url(keyword)
    if not url:
        return ""
    try:
        # No Referer header is sent here, which is what the CDN allows.
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
            content_type = resp.headers.get("Content-Type", "")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"  cover download failed for {keyword!r}: {exc}")
        return ""
    if not data or len(data) < 512:
        return ""
    ext = "webp" if "webp" in content_type else ("png" if "png" in content_type else "jpg")
    name = hashlib.sha1(f"{source_id}|{keyword}".encode("utf-8")).hexdigest()[:16] + "." + ext
    (COVERS_DIR / name).write_bytes(data)
    return f"./data/covers/{name}"


def is_real_cover(cover: str) -> bool:
    cover = (cover or "").strip()
    if not cover:
        return False
    return not any(marker in cover for marker in GENERIC_COVER_MARKERS)


def prepare_covers_dir() -> None:
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    for existing in COVERS_DIR.glob("*"):
        if existing.is_file():
            existing.unlink()


def enrich_covers(platforms: list[dict[str, Any]]) -> None:
    cache: dict[str, str] = {}
    for platform in platforms:
        if platform["id"] not in COVER_ENRICH_SOURCES:
            continue
        for item in platform["items"]:
            if is_real_cover(item.get("cover", "")):
                continue
            title = item.get("title", "")
            if title not in cache:
                cache[title] = download_cover(platform["id"], title)
                time.sleep(0.4)
            if cache[title]:
                item["cover"] = cache[title]


def extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    data = payload.get("data") or payload.get("result") or payload.get("list")
    if isinstance(data, dict):
        data = data.get("list") or data.get("items") or data.get("data")

    return data if isinstance(data, list) else []


def first_text(item: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def first_number(item: dict[str, Any], keys: list[str]) -> int | float | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            parsed = parse_hot_number(value)
            if parsed is not None:
                return parsed
    return None


def parse_hot_number(value: str) -> int | float | None:
    text = value.strip().replace(",", "")
    if not text:
        return None

    multiplier = 1
    lower = text.lower()
    if text.endswith("亿"):
        multiplier = 100000000
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10000
        text = text[:-1]
    # Some platforms return English unit suffixes, e.g. xiaohongshu "947.5w"
    # (w = 万), or "1.2kw"/"3.4k". Order matters: "kw" must precede "w"/"k".
    elif lower.endswith("kw"):
        multiplier = 10000
        text = text[:-2]
    elif lower.endswith("w"):
        multiplier = 10000
        text = text[:-1]
    elif lower.endswith("k"):
        multiplier = 1000
        text = text[:-1]

    text = text.replace("热度", "").strip()
    if text.replace(".", "", 1).isdigit():
        number = float(text) if "." in text else int(text)
        return int(number * multiplier)
    return None


def cover_url(item: dict[str, Any]) -> str:
    direct = first_text(item, ["cover", "pic", "image", "thumbnail", "coverUrl"])
    if direct:
        return direct

    word_cover = item.get("word_cover")
    if isinstance(word_cover, dict):
        urls = word_cover.get("url_list")
        if isinstance(urls, list) and urls:
            return str(urls[0])

    return ""


def item_url(source_id: str, title: str, item: dict[str, Any]) -> str:
    direct = first_text(item, ["url", "link", "share_url", "video_url", "jump_url"])
    if direct:
        return direct

    if source_id == "douyin" and title:
        return f"https://www.douyin.com/search/{urllib.parse.quote(title)}"
    if source_id == "kuaishou" and title:
        return f"https://www.kuaishou.com/search/video?searchKey={urllib.parse.quote(title)}"
    if source_id == "xiaohongshu" and title:
        return f"https://www.xiaohongshu.com/search_result?keyword={urllib.parse.quote(title)}"
    return ""


def normalize(source: dict[str, str], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for index, item in enumerate(items[:50], 1):
        title = first_text(item, ["title", "word", "name", "keyword", "sentence", "desc"])
        if not title:
            continue

        hot = first_number(item, ["hot", "hot_value", "heat", "score", "views", "view_count"])
        normalized.append(
            {
                "rank": int(first_number(item, ["rank", "position", "index"]) or index),
                "title": title,
                "hot": hot,
                "hotText": first_text(item, ["hotText", "hot_desc", "hot_word", "label_desc"]),
                "url": item_url(source["id"], title, item),
                "cover": cover_url(item),
                "source": source["id"],
                "sourceName": source["name"],
                "raw": item,
            }
        )
    return normalized


def fetch_source(source: dict[str, Any]) -> dict[str, Any]:
    errors = []
    for template in source["urls"]:
        url = build_url(template)
        if not url:
            continue
        try:
            print(f"Fetching {source['name']} from {url}")
            payload = fetch_json(url)
            items = extract_items(payload)
            normalized = normalize(source, items)
            if normalized:
                return {
                    "id": source["id"],
                    "name": source["name"],
                    "updatedAt": now_iso(),
                    "status": "ok",
                    "items": normalized,
                    "error": "",
                    "sourceUrl": url,
                }
            errors.append(f"{url}: empty data")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            errors.append(f"{url}: {exc}")
        time.sleep(1)

    return {
        "id": source["id"],
        "name": source["name"],
        "updatedAt": now_iso(),
        "status": "error",
        "items": [],
        "error": " | ".join(errors) or "No endpoint configured",
        "sourceUrl": "",
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    prepare_covers_dir()
    platforms = [fetch_source(source) for source in SOURCES]

    # Give kuaishou / xiaohongshu rows a real video-frame cover when available.
    enrich_covers(platforms)

    for platform in platforms:
        write_json(DATA_DIR / f"{platform['id']}.json", platform)

    all_items = []
    for platform in platforms:
        all_items.extend(platform["items"])
    all_items.sort(key=lambda item: item.get("hot") or 0, reverse=True)

    summary = {
        "updatedAt": now_iso(),
        "timezone": "Asia/Shanghai",
        "platforms": platforms,
        "items": all_items[:150],
    }
    write_json(DATA_DIR / "all.json", summary)

    print("Done.")
    for platform in platforms:
        covered = sum(1 for item in platform["items"] if item.get("cover"))
        print(
            f"- {platform['name']}: {platform['status']} "
            f"({len(platform['items'])} items, {covered} with cover)"
        )
        if platform["error"]:
            print(f"  {platform['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

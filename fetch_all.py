# -*- coding: utf-8 -*-
"""Fetch daily hot video topics with AI enrichment and write normalized JSON files."""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


DATA_DIR = Path("data")
COVERS_DIR = DATA_DIR / "covers"
HISTORY_DIR = DATA_DIR / "history"
HISTORY_KEEP_DAYS = 14
BEIJING_TZ = timezone(timedelta(hours=8))

COOKIE_JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIE_JAR))
_OPENER_READY = False

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)

GENERIC_COVER_MARKERS = ("picasso-static.xiaohongshu.com",)
COVER_ENRICH_SOURCES = ("kuaishou", "xiaohongshu")

# AI config
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "").strip() or "deepseek-chat"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

MODE = os.getenv("MODE", "").strip().lower()

CATEGORIES = ["社会民生", "娱乐", "科技", "体育", "财经", "生活", "其他"]

KEYWORD_MAP = {
    "社会民生": ["地震", "洪水", "台风", "暴雨", "火灾", "事故", "失踪", "遇难", "政策", "法规", "教育部", "卫健委", "公安部"],
    "娱乐": ["官宣", "结婚", "离婚", "恋情", "演唱会", "综艺", "电视剧", "电影", "演员", "歌手", "明星", "八卦"],
    "科技": ["AI", "人工智能", "芯片", "手机", "iPhone", "华为", "小米", "互联网", "算法", "火箭", "航天", "卫星"],
    "体育": ["亚运会", "奥运会", "世界杯", "男篮", "女篮", "足球", "篮球", "乒乓球", "羽毛球", "电竞", "IG", "JDG"],
    "财经": ["股市", "基金", "理财", "银行", "保险", "房价", "油价", "金价", "GDP", "通胀", "利率"],
    "生活": ["美食", "旅游", "拍照", "穿搭", "美甲", "护肤", "减肥", "健身", "宠物", "萌宠", "手工"],
}


def now_iso() -> str:
    return datetime.now(BEIJING_TZ).isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")


def build_url(template: str) -> str | None:
    api_base = os.getenv("API_BASE", "https://api-hot.imsyy.top").rstrip("/")
    values = {"API_BASE": api_base, "XIAOHONGSHU_API_URL": os.getenv("XIAOHONGSHU_API_URL", "").strip()}
    url = template.format(**values)
    return url if url.startswith("http") else None


def fetch_json(url: str, referer: str = "") -> Any:
    headers = {"User-Agent": UA, "Accept": "application/json,text/plain,*/*"}
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
        req = urllib.request.Request("https://www.bilibili.com/", headers={"User-Agent": UA, "Accept": "text/html"})
        with OPENER.open(req, timeout=20) as resp:
            resp.read(2048)
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    _OPENER_READY = True


def bili_cover_url(keyword: str) -> str:
    keyword = (keyword or "").strip()
    if not keyword:
        return ""
    warm_up_bilibili()
    try:
        url = "https://api.bilibili.com/x/web-interface/search/all/v2?keyword=" + urllib.parse.quote(keyword)
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
                return pic + "@480w_270h_1c.webp"
    except Exception as exc:
        print(f"  bili cover miss for {keyword!r}: {exc}")
    return ""


def download_cover(source_id: str, keyword: str) -> str:
    url = bili_cover_url(keyword)
    if not url:
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
            content_type = resp.headers.get("Content-Type", "")
    except Exception as exc:
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


def deepseek_chat(messages: list[dict], temperature: float = 0.3, max_tokens: int = 2000, timeout: int = 60) -> str:
    if not DEEPSEEK_API_KEY:
        return ""
    try:
        payload = json.dumps({"model": DEEPSEEK_MODEL, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}).encode()
        req = urllib.request.Request(DEEPSEEK_URL, data=payload, headers={"User-Agent": UA, "Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        print(f"DeepSeek API error: {e}")
        return ""


def rule_category(title: str) -> str:
    t = title.lower()
    scores = {cat: 0 for cat in CATEGORIES}
    for cat, kws in KEYWORD_MAP.items():
        for kw in kws:
            if kw.lower() in t:
                scores[cat] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "其他"


def ai_annotate(items: list[dict]) -> None:
    # Assign default categories first
    for it in items:
        it.setdefault("summary", "")
        it.setdefault("category", rule_category(it.get("title", "")))
    if not DEEPSEEK_API_KEY:
        return
    # Batch annotate in chunks of 20
    for i in range(0, len(items), 20):
        chunk = items[i : i + 20]
        titles = [{"idx": j, "title": it["title"]} for j, it in enumerate(chunk)]
        prompt = (
            "为以下热点标题生成一句话摘要（20字内）并分类。返回JSON数组，每项：{\"idx\":数字,\"summary\":\"字符串\",\"category\":\"社会民生|娱乐|科技|体育|财经|生活|其他\"}。\n\n"
            + "\n".join(f"{j}. {it['title']}" for j, it in enumerate(titles))
        )
        content = deepseek_chat([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=1500)
        if not content:
            continue
        # Extract JSON array from response
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if not match:
            continue
        try:
            rows = json.loads(match.group(0))
            for row in rows:
                idx = row.get("idx")
                if isinstance(idx, int) and 0 <= idx < len(chunk):
                    if "summary" in row:
                        chunk[idx]["summary"] = str(row["summary"]).strip()[:80]
                    if "category" in row and row["category"] in CATEGORIES:
                        chunk[idx]["category"] = row["category"]
        except json.JSONDecodeError:
            pass
        time.sleep(0.5)


def save_history_snapshot(platforms: list[dict]) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    today = today_str()
    path = HISTORY_DIR / f"{today}.json"
    minimal = {"date": today, "platforms": [{"id": p["id"], "name": p["name"], "count": len(p["items"]), "items": [{"title": it["title"], "hot": it.get("hot")} for it in p["items"]]} for p in platforms]}
    path.write_text(json.dumps(minimal, ensure_ascii=False, indent=2), encoding="utf-8")
    # Prune old files
    files = sorted(HISTORY_DIR.glob("*.json"), key=lambda f: f.name, reverse=True)
    for old in files[HISTORY_KEEP_DAYS:]:
        old.unlink()


def generate_weekly_report() -> dict:
    files = sorted(HISTORY_DIR.glob("*.json"), key=lambda f: f.name, reverse=True)[:14]
    if len(files) < 2:
        return {"error": "insufficient history", "report": "历史数据不足，无法生成趋势报告。"}
    history = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    # Compute topic frequency change
    topic_counts = {}
    for day in history:
        for p in day.get("platforms", []):
            for it in p.get("items", []):
                t = it["title"]
                topic_counts[t] = topic_counts.get(t, 0) + 1
    top_rising = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    # Generate narrative with LLM or fallback
    if DEEPSEEK_API_KEY:
        prompt = f"基于以下热点话题出现频次数据，生成一份200字以内的中文周报摘要，语气专业但亲切：\n{top_rising}"
        narrative = deepseek_chat([{"role": "user", "content": prompt}], temperature=0.4, max_tokens=500)
    else:
        narrative = f"本周共追踪到{len(topic_counts)}个热点话题。出现频次最高的包括：{', '.join([t for t,_ in top_rising[:5]])}。"
    return {"generated_at": now_iso(), "days_covered": len(files), "top_topics": top_rising, "report": narrative}


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
                return {"id": source["id"], "name": source["name"], "updatedAt": now_iso(), "status": "ok", "items": normalized, "error": "", "sourceUrl": url}
            errors.append(f"{url}: empty data")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
        time.sleep(1)
    return {"id": source["id"], "name": source["name"], "updatedAt": now_iso(), "status": "error", "items": [], "error": " | ".join(errors) or "No endpoint configured", "sourceUrl": ""}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    prepare_covers_dir()
    platforms = [fetch_source(source) for source in SOURCES]
    enrich_covers(platforms)
    ai_annotate(all_items := [item for platform in platforms for item in platform["items"]])
    save_history_snapshot(platforms)
    for platform in platforms:
        write_json(DATA_DIR / f"{platform['id']}.json", platform)
    all_items.sort(key=lambda item: item.get("hot") or 0, reverse=True)
    summary = {"updatedAt": now_iso(), "timezone": "Asia/Shanghai", "platforms": platforms, "items": all_items[:150]}
    write_json(DATA_DIR / "all.json", summary)
    # Weekly report on Monday or forced
    do_weekly = MODE in ("weekly", "both") or (MODE == "" and datetime.now(BEIJING_TZ).weekday() == 0)
    if do_weekly:
        report = generate_weekly_report()
        write_json(DATA_DIR / "weekly.json", report)
        print(f"Weekly report generated at {report.get('generated_at', 'N/A')}")
    print("Done.")
    for platform in platforms:
        covered = sum(1 for item in platform["items"] if item.get("cover"))
        print(f"- {platform['name']}: {platform['status']} ({len(platform['items'])} items, {covered} with cover)")
        if platform["error"]:
            print(f"  {platform['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""
第 1 步 · 第 1 个脚本：拉取抖音热榜
---------------------------------
目标：跑通这一段，你能在屏幕上看到当天抖音 Top 10 热搜。
跑法：在终端执行  python fetch_douyin.py
"""
import json
import urllib.request

# 这是抖音热榜接口（实测可用，无需注册、无需 key）
URL = "https://v2.xxapi.cn/api/douyinhot"


def main():
    # 1. 发请求
    print("正在拉取抖音热榜...")
    with urllib.request.urlopen(URL, timeout=15) as resp:
        raw = resp.read().decode("utf-8")

    # 2. 解析 JSON
    data = json.loads(raw)
    items = data.get("data", [])

    if not items:
        print("没拿到数据，接口可能变了，换备用方案。")
        return

    # 3. 打印前 10 条
    print(f"\n=== 抖音热榜 Top {min(10, len(items))} ===")
    for i, it in enumerate(items[:10], 1):
        word = it.get("word", "无标题")
        hot = it.get("hot_value", 0)
        # 热度值格式化成「万」
        hot_str = f"{hot/10000:.1f}万" if hot else "未知"
        print(f"{i:>2}. {word}  🔥 {hot_str}")

    # 4. 顺手存成文件，下一步要用
    with open("douyin_today.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print("\n已保存到 douyin_today.json")


if __name__ == "__main__":
    main()

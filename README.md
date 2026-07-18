# 今日热视频热榜

一个静态网站，每天北京时间 09:00 通过 GitHub Actions 自动采集热榜数据，并展示抖音、快手、小红书等平台的热视频话题。

## 本地运行

```bash
python fetch_all.py
python -m http.server 8080
```

浏览器打开：

```text
http://localhost:8080
```

## 自动更新

`.github/workflows/daily.yml` 已配置定时任务：

- 每天北京时间 09:00 自动运行
- 支持在 GitHub Actions 页面手动触发
- 自动生成并提交 `data/*.json`

## 数据源

当前已接入：

- 抖音
- 快手

小红书公开稳定接口较少，脚本已预留 `XIAOHONGSHU_API_URL`：

1. 在 GitHub 仓库进入 `Settings`
2. 打开 `Secrets and variables` -> `Actions`
3. 新增 secret：`XIAOHONGSHU_API_URL`
4. 填入可返回 JSON 热榜数据的接口地址

配置后，GitHub Actions 会在下次运行时自动采集小红书数据。

const state = { data: null, platform: "all", query: "", };
const platformNames = { all: "全部平台", douyin: "抖音", kuaishou: "快手", xiaohongshu: "小红书", };
const hotList = document.querySelector("#hotList");
const emptyState = document.querySelector("#emptyState");
const resultCount = document.querySelector("#resultCount");
const boardTitle = document.querySelector("#boardTitle");
const updatedAt = document.querySelector("#updatedAt");
const platformStatus = document.querySelector("#platformStatus");
const itemTemplate = document.querySelector("#itemTemplate");
const statusTemplate = document.querySelector("#statusTemplate");

// --- Cover helpers -------------------------------------------------------
// Douyin items ship a real video cover (word_cover). Kuaishou / Xiaohongshu
// hot lists are keyword topics with no video artwork, and the Xiaohongshu
// feed only returns a shared generic "热" badge PNG. For those we render a
// deterministic per-item SVG cover so every card has a picture.
const GENERIC_COVER_MARKERS = ["picasso-static.xiaohongshu.com"];
const PLATFORM_STYLES = {
  douyin: { label: "抖音", sub: "热视频" },
  kuaishou: { label: "快手", sub: "热榜话题" },
  xiaohongshu: { label: "小红书", sub: "热榜话题" },
};
function hashText(text) {
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) % 360;
  }
  return hash;
}
function escapeXml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function buildCoverDataUri(item) {
  const style = PLATFORM_STYLES[item.source] || { label: item.sourceName || "热榜", sub: "" };
  const hue = hashText(item.title || style.label);
  const hue2 = (hue + 42) % 360;
  const initial = (item.title || style.label).trim().slice(0, 1) || "热";
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200" viewBox="0 0 320 200">` +
    `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">` +
    `<stop offset="0" stop-color="hsl(${hue} 82% 22%)"/>` +
    `<stop offset="1" stop-color="hsl(${hue2} 85% 46%)"/>` +
    `</linearGradient></defs>` +
    `<rect width="320" height="200" fill="url(#g)"/>` +
    `<text x="18" y="188" font-family="sans-serif" font-size="150" font-weight="700" fill="rgba(255,255,255,0.16)">${escapeXml(initial)}</text>` +
    `<text x="22" y="46" font-family="sans-serif" font-size="26" font-weight="700" fill="#ffffff">${escapeXml(style.label)}</text>` +
    `<text x="22" y="76" font-family="sans-serif" font-size="15" fill="rgba(255,255,255,0.85)">${escapeXml(style.sub)}</text>` +
    `</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
function resolveCover(item) {
  const cover = (item.cover || "").trim();
  const isGeneric = !cover || GENERIC_COVER_MARKERS.some((marker) => cover.includes(marker));
  return isGeneric ? buildCoverDataUri(item) : cover;
}
// ------------------------------------------------------------------------

function formatHot(value, text) { if (text) return text; if (!value) return "热度未知"; if (value >= 100000000) return `${(value / 100000000).toFixed(1)} 亿热度`; if (value >= 10000) return `${(value / 10000).toFixed(1)} 万热度`; return `${value} 热度`; }
function formatTime(value) { if (!value) return "等待更新"; const date = new Date(value); if (Number.isNaN(date.getTime())) return value; return `更新于 ${date.toLocaleString("zh-CN", { hour12: false })}`; }
function filteredItems() { const keyword = state.query.trim().toLowerCase(); const items = state.data?.items ?? []; return items.filter((item) => { const platformMatched = state.platform === "all" || item.source === state.platform; const queryMatched = !keyword || item.title.toLowerCase().includes(keyword); return platformMatched && queryMatched; }); }
function renderStatus() { platformStatus.replaceChildren(); const platforms = state.data?.platforms ?? []; platforms.forEach((platform) => { const node = statusTemplate.content.firstElementChild.cloneNode(true); node.classList.toggle("is-error", platform.status !== "ok"); node.querySelector("strong").textContent = platform.name; node.querySelector("span").textContent = platform.status === "ok" ? "正常" : "待配置"; node.querySelector("p").textContent = platform.status === "ok" ? `${platform.items.length} 条话题，${formatTime(platform.updatedAt)}` : platform.error || "暂时没有可用数据源"; platformStatus.append(node); }); }
function renderList() { const items = filteredItems(); hotList.replaceChildren(); boardTitle.textContent = platformNames[state.platform] ?? "全部平台"; resultCount.textContent = `${items.length} 条`; emptyState.hidden = items.length > 0; items.forEach((item, index) => { const node = itemTemplate.content.firstElementChild.cloneNode(true); node.querySelector(".rank").textContent = index + 1; node.querySelector(".source").textContent = item.sourceName; node.querySelector(".hot").textContent = formatHot(item.hot, item.hotText); node.querySelector("h3").textContent = item.title; const thumb = node.querySelector(".thumb"); const cover = resolveCover(item); if (cover) { thumb.style.backgroundImage = `url("${cover}")`; } const link = node.querySelector("a"); if (item.url) { link.href = item.url; } else { link.remove(); } hotList.append(node); }); }
function render() { updatedAt.textContent = formatTime(state.data?.updatedAt); renderStatus(); renderList(); }
async function loadData() { try { const response = await fetch("./data/all.json", { cache: "no-store" }); if (!response.ok) throw new Error(`HTTP ${response.status}`); state.data = await response.json(); } catch (error) { state.data = { updatedAt: "", platforms: [ { id: "douyin", name: "抖音", status: "error", items: [], error: "数据文件还未生成" }, { id: "kuaishou", name: "快手", status: "error", items: [], error: "数据文件还未生成" }, { id: "xiaohongshu", name: "小红书", status: "error", items: [], error: "数据文件还未生成" }, ], items: [], }; console.error(error); } render(); }
document.querySelector("#platformTabs").addEventListener("click", (event) => { const button = event.target.closest("button[data-platform]"); if (!button) return; state.platform = button.dataset.platform; document.querySelectorAll(".tab").forEach((tab) => { tab.classList.toggle("is-active", tab === button); }); renderList(); });
document.querySelector("#searchInput").addEventListener("input", (event) => { state.query = event.target.value; renderList(); });
loadData();

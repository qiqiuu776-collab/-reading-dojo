# -*- coding: utf-8 -*-
"""
ReadingDojo - Daily English News
抓取英文新闻RSS → 日期过滤 → 飞书推送链接+标题+简介（英文）
你自己读链接，获取观点
"""
import os, json, urllib.request, time, io, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

# Fix Windows encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    os.system('chcp 65001 >nul 2>&1')

# ==== 配置 ====
import os
  FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK")
  if not FEISHU_WEBHOOK:
      print("Error: FEISHU_WEBHOOK environment variable not set")
      exit(1)
DATA_DIR = Path("D:/ReadingDojo/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 英文RSS源（已验证可访问）
# ⚠️ Reuters/Economist 在中国网络下被封，无法直接访问
RSS_FEEDS = {
    "TechCrunch":      "https://techcrunch.com/feed/",
    "WIRED":           "https://www.wired.com/feed/rss",
    "Bloomberg Mkts":  "https://feeds.bloomberg.com/markets/news.rss",
    "Financial Times":  "https://www.ft.com/rss/home",
    "CNN World":       "http://rss.cnn.com/rss/edition_world.rss",
    "NPR News":        "https://feeds.npr.org/1001/rss.xml",
    "Ars Technica":     "https://feeds.arstechnica.com/arstechnica/index",
    "BBC World":       "https://feeds.bbci.co.uk/news/world/rss.xml",
    "BBC Tech":        "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "MIT Tech Review":  "https://www.technologyreview.com/feed/",
    "SCMP":            "https://www.scmp.com/rss/91/feed",
    "Hacker News":     "https://news.ycombinator.com/rss",
}

# 筛选关键词（你觉得哪些话题值得读）
FILTER_KEYWORDS = [
    "AI", "artificial intelligence", "machine learning",
    "startup", "venture capital", "funding", "IPO",
    "e-commerce", "retail", "consumer", "market",
    "China", "Asia", "Southeast Asia",
    "trade", "tariff", "supply chain",
    "climate", "energy", "sustainability",
    "regulation", "policy", "government",
    "social media", "platform", "digital",
    "fintech", "payment", "banking",
    "logistics", "shipping",
]
EXCLUDE = ["sport", "celebrity", "entertainment", "gossip", "football", "soccer"]

# 只保留最近多少小时内的新闻
MAX_AGE_HOURS = 48


# ==== 日期解析 ====
def parse_date(pub_date_str):
    """解析 RFC 822 / ISO 格式的日期，返回 datetime 或 None"""
    if not pub_date_str:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(pub_date_str)
    except Exception:
        pass
    # 尝试其他格式
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%d %b %Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(pub_date_str[:25], fmt).replace(tzinfo=timezone.utc)
        except:
            pass
    return None


# ==== 核心功能 ====
def fetch_rss(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ReadingDojo/1.0)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")

def parse_rss(xml_content, source):
    articles = []
    try:
        root = ET.fromstring(xml_content)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            # 清理HTML
            desc = re.sub(r"<[^>]+>", "", desc).strip()
            desc = desc.replace("<![CDATA[", "").replace("]]>", "").strip()
            if title and link and len(title) > 15:
                articles.append({
                    "title": title,
                    "link": link,
                    "description": desc[:180] if desc else "",
                    "source": source,
                    "pub_date": pub
                })
    except Exception as e:
        print(f"  [FAIL] {source}: {e}")
    return articles

def should_include(article):
    title_lower = article["title"].lower()
    for kw in EXCLUDE:
        if kw in title_lower:
            return False
    for kw in FILTER_KEYWORDS:
        if kw.lower() in title_lower:
            return True
    return False

def is_recent(article, max_hours=MAX_AGE_HOURS):
    """判断新闻是否在时间窗口内"""
    pub_date = parse_date(article.get("pub_date", ""))
    if pub_date is None:
        return True  # 没有日期的先保留

    # 转换为本地时间比较
    now = datetime.now(timezone.utc)
    age = now - pub_date

    # 处理时区偏移（有些日期可能是未来时间，比如时区错误）
    if age.total_seconds() < -86400:  # 未来超过24小时，可能是解析错误
        return False
    if age.total_seconds() > max_hours * 3600:
        return False
    return True

def format_date(pub_date_str):
    """把 RFC 822 日期转成可读格式"""
    d = parse_date(pub_date_str)
    if d:
        return d.strftime("%m/%d")
    return ""


# ==== 飞书推送 ====
def push_to_feishu(articles):
    print(f"  [3/4] 飞书推送 ({len(articles)} 条)...")

    article_elements = []
    for i, art in enumerate(articles, 1):
        pub = format_date(art.get("pub_date", ""))
        time_tag = f" [{pub}]" if pub else ""

        desc = art.get("description", "")
        if len(desc) > 120:
            desc = desc[:120].rsplit(" ", 1)[0] + "..."

        content = f"**{i}. {art['title']}**{time_tag}\n\n"
        if desc:
            content += f"_{desc}_\n\n"
        content += f"[Read article]({art['link']})\n"
        content += f"---\n"

        article_elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": content}
        })

    # 分割成多批（飞书卡片每批有限制）
    batch_size = 10
    batches = [article_elements[i:i+batch_size] for i in range(0, len(article_elements), batch_size)]

    sources_list = list(RSS_FEEDS.keys())
    total_sent = 0
    for batch_idx, batch in enumerate(batches):
        header_text = f"ReadingDojo Daily | {datetime.now().strftime('%m/%d')}"
        if len(batches) > 1:
            header_text += f" ({batch_idx+1}/{len(batches)})"

        card_payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "text": header_text},
                    "template": "blue"
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "lark_md",
                        "content": f"**{len(articles)} articles | last {MAX_AGE_HOURS}h**\n_Click the link to read. Form your own views._"}},
                    {"tag": "hr"},
                    *batch,
                    {"tag": "hr"},
                    {"tag": "div", "text": {"tag": "lark_md",
                        "content": f"_ReadingDojo {datetime.now().strftime('%H:%M')}_"}}
                ]
            }
        }

        data = json.dumps(card_payload).encode("utf-8")
        req = urllib.request.Request(FEISHU_WEBHOOK, data=data,
                                    headers={"Content-Type": "application/json"})
        for attempt in range(3):
            try:
                resp = urllib.request.urlopen(req, timeout=20)
                result = json.loads(resp.read().decode("utf-8", errors="replace"))
                if result.get("code") == 0 or result.get("StatusCode") == 0:
                    total_sent += len(batch)
                    break
            except Exception as e:
                if attempt == 2:
                    print(f"  批次{batch_idx+1}失败: {e}")

    print(f"  -> 飞书推送: {total_sent}/{len(articles)} 条成功")
    return total_sent


# ==== 导出 ====
def export_to_file(articles):
    lines = []
    lines.append(f"ReadingDojo Daily | {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"Filtered: last {MAX_AGE_HOURS} hours only")
    lines.append(f"Total: {len(articles)} articles")
    lines.append(f"{'='*60}")
    lines.append("")

    for i, art in enumerate(articles, 1):
        pub = format_date(art.get("pub_date", ""))
        lines.append(f"[{i}] {art['title']}{f' [{pub}]' if pub else ''}")
        lines.append(f"    Source: {art['source']}")
        if art.get("description"):
            lines.append(f"    Preview: {art['description'][:120]}")
        lines.append(f"    Link: {art['link']}")
        lines.append("")

    txt_path = DATA_DIR / f"news_links_{datetime.now().strftime('%Y%m%d')}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    json_path = DATA_DIR / f"articles_{datetime.now().strftime('%Y%m%d')}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    print(f"  -> 已保存: {txt_path.name}")


# ==== 主程序 ====
def main():
    print(f"\n{'='*60}")
    print(f"  ReadingDojo - Daily English News")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 1. 抓新闻
    print(f"  [1/4] Fetching RSS feeds...")
    all_articles, seen = [], set()
    for source, url in RSS_FEEDS.items():
        try:
            print(f"    {source:20s}...", end=" ", flush=True)
            xml = fetch_rss(url)
            arts = parse_rss(xml, source)
            new_count = 0
            for a in arts:
                if a["link"] not in seen:
                    seen.add(a["link"])
                    all_articles.append(a)
                    new_count += 1
            print(f"+{new_count}")
        except Exception as e:
            print(f"FAIL ({str(e)[:40]})")
        time.sleep(0.3)

    # 2. 关键词过滤
    print(f"\n  [2/4] Filtering...")
    filtered = [a for a in all_articles if should_include(a)]

    # 3. 日期过滤（只保留最近48小时）
    filtered = [a for a in filtered if is_recent(a, MAX_AGE_HOURS)]

    # 每个来源最多取3条
    by_source = {}
    for a in filtered:
        by_source.setdefault(a["source"], []).append(a)

    selected = []
    for src in by_source:
        selected.extend(by_source[src][:3])

    # 按日期排序（最新的在前）
    def get_pub_date(art):
        d = parse_date(art.get("pub_date", ""))
        return d if d else datetime.min.replace(tzinfo=timezone.utc)
    selected.sort(key=get_pub_date, reverse=True)
    selected = selected[:20]

    print(f"    {len(all_articles)} fetched -> {len([a for a in all_articles if should_include(a)])} matched")
    print(f"    -> {len(filtered)} within {MAX_AGE_HOURS}h -> {len(selected)} selected (top 20)")
    print()

    if not selected:
        print("  No recent articles matched. Check your FILTER_KEYWORDS.")
        return

    # 3. 飞书推送
    push_to_feishu(selected)

    # 4. 保存
    print(f"\n  [4/4] Saving...")
    export_to_file(selected)

    print(f"\n{'='*60}")
    print(f"  Done. {len(selected)} articles pushed.")
    print(f"  Data: D:/ReadingDojo/data/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

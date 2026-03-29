#!/usr/bin/env python3
"""
update_papers.py
从 Hugging Face Daily Papers 爬取近 7 天的论文，按 upvote 排序取 top 15
更新 data/papers.json
"""
import json
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_FILE = ROOT / "data" / "papers.json"


def get_recent_dates(days: int = 7) -> list[str]:
    """获取最近 N 天的日期列表"""
    dates = []
    today = datetime.now(timezone(timedelta(hours=8)))
    for i in range(days):
        d = today - timedelta(days=i)
        dates.append(d.strftime("%Y-%m-%d"))
    return dates


def fetch_papers_by_date(date_str: str) -> list[dict]:
    """从 Hugging Face 获取某一天的论文列表"""
    url = f"https://huggingface.co/papers?date={date_str}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")
        return parse_papers_from_html(html, date_str)
    except Exception as e:
        print(f"  Error fetching {date_str}: {e}")
        return []


def parse_papers_from_html(html: str, date_str: str) -> list[dict]:
    """从 HTML 中解析论文数据"""
    papers = []

    # HF papers 页面结构：每个论文项包含标题、arXiv ID、upvotes
    # 查找论文块 - 使用更精确的模式

    # 模式1: 论文标题和链接
    # 查找包含 arxiv.org/abs/ 的链接和对应的标题
    title_pattern = r'<a[^>]*href="https://arxiv\.org/abs/([^"]+)"[^>]*>\s*<h3[^>]*>(.*?)</h3>'

    # 查找 upvote 数
    upvote_pattern = r'<span[^>]*>(\d+)\s*</span>\s*upvotes?'

    # 更直接的方式：查找所有文章块
    # 每篇文章通常包含在 article 或类似的容器中
    article_blocks = re.findall(
        r'<article[^>]*>(.*?)</article>',
        html,
        re.DOTALL
    )

    if not article_blocks:
        # 尝试其他模式：查找包含 arxiv 链接的区域
        article_blocks = re.findall(
            r'<a[^>]*href="https://arxiv\.org/abs/[^"]+"[^>]*>.*?</a>.*?<span[^>]*>\d+\s*</span>\s*upvotes?',
            html,
            re.DOTALL
        )

    for block in article_blocks:
        # 提取 arXiv ID
        arxiv_match = re.search(r'arxiv\.org/abs/([^"\s]+)', block)
        if not arxiv_match:
            continue
        arxiv_id = arxiv_match.group(1)

        # 提取标题
        title_match = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.DOTALL)
        title = ""
        if title_match:
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()

        # 提取 upvotes
        upvote_match = re.search(r'(\d+)\s*<span[^>]*>\s*upvote|upvote[^>]*>(\d+)', block, re.IGNORECASE)
        upvotes = 0
        if upvote_match:
            upvotes = int(upvote_match.group(1) or upvote_match.group(2) or 0)

        # 备用：在其他格式中查找 upvotes
        if upvotes == 0:
            upvote_match2 = re.search(r'>(\d+)\s*</span>\s*<span[^>]*>\s*upvotes?', block, re.IGNORECASE)
            if upvote_match2:
                upvotes = int(upvote_match2.group(1))

        if arxiv_id and title:
            papers.append({
                "id": arxiv_id,
                "title": title,
                "upvotes": upvotes,
                "date": date_str,
            })

    return papers


def classify_direction(title: str, arxiv_id: str = "") -> str:
    """根据标题和ID分类论文方向"""
    text = f"{title} {arxiv_id}".lower()

    if "agent" in text:
        return "Agent"
    if any(kw in text for kw in ["memory", "context", "token", "long context"]):
        return "长上下文"
    if any(kw in text for kw in ["multimodal", "vision", "image", "video", "visual"]):
        return "多模态"
    if any(kw in text for kw in ["reasoning", "thinking", "chain", "cot", "logic"]):
        return "推理"
    if any(kw in text for kw in ["safety", "red-team", "align", "alignment", "harmless"]):
        return "安全"
    if any(kw in text for kw in ["diffusion", "generation", "synthesis", "synthetic"]):
        return "图像生成"
    if any(kw in text for kw in ["speech", "audio", "tts", "voice", "sound"]):
        return "语音生成"
    if any(kw in text for kw in ["science", "biology", "protein", "drug", "molecule"]):
        return "AI for Science"
    if any(kw in text for kw in ["distillation", "training", "rlhf", "rl ", "finetune", "pretrain"]):
        return "训练方法"

    return "前沿方法"


def get_significance(upvotes: int) -> str:
    """根据 upvotes 判断重要性"""
    if upvotes >= 500:
        return "hot"
    if upvotes >= 100:
        return "breakthrough"
    if upvotes >= 30:
        return "notable"
    return "emerging"


def fetch_paper_details(arxiv_id: str) -> dict:
    """获取论文详细信息（从 arXiv）"""
    try:
        url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml = resp.read().decode("utf-8")

        # 提取摘要
        summary_match = re.search(r'<summary>(.*?)</summary>', xml, re.DOTALL)
        summary = ""
        if summary_match:
            summary = re.sub(r'\s+', ' ', summary_match.group(1)).strip()[:300]

        # 提取作者
        authors = re.findall(r'<name>(.*?)</name>', xml)
        authors_str = ", ".join(authors[:3]) if authors else "Unknown"
        if len(authors) > 3:
            authors_str += " et al."

        # 提取机构（从摘要或作者信息）
        # arXiv API 不提供机构，返回空

        return {
            "summary": summary,
            "authors": authors_str,
            "institution": "",
        }
    except Exception as e:
        print(f"    Error fetching details for {arxiv_id}: {e}")
        return {
            "summary": "",
            "authors": "",
            "institution": "",
        }


def main():
    print("📚 抓取 Hugging Face Daily Papers...")

    # 获取最近 7 天的日期
    dates = get_recent_dates(7)
    print(f"  检查日期: {dates}")

    all_papers = []
    seen_ids = set()

    for date_str in dates:
        print(f"\n  正在获取 {date_str} 的论文...")
        papers = fetch_papers_by_date(date_str)
        print(f"    找到 {len(papers)} 篇论文")

        for p in papers:
            if p["id"] in seen_ids:
                continue
            seen_ids.add(p["id"])
            all_papers.append(p)

    print(f"\n  共计 {len(all_papers)} 篇论文（去重后）")

    if not all_papers:
        print("  ⚠️ 没有找到论文，保留旧数据")
        return

    # 按 upvotes 排序，取 top 15
    all_papers.sort(key=lambda x: x["upvotes"], reverse=True)
    top_papers = all_papers[:15]

    # 构建输出
    output_papers = []
    for p in top_papers:
        print(f"    - {p['title'][:60]}... ({p['upvotes']} upvotes)")

        # 获取详细信息
        details = fetch_paper_details(p["id"])

        # 分类
        direction = classify_direction(p["title"], p["id"])
        significance = get_significance(p["upvotes"])

        # 构造输出格式
        output_papers.append({
            "id": p["id"],
            "title": p["title"],
            "url": f"https://arxiv.org/abs/{p['id']}",
            "direction": direction,
            "significance": significance,
            "breakthrough": details["summary"] or f"arXiv paper {p['id']} on {direction}",
            "tags": [direction],
            "authors": details["authors"],
            "institution": details["institution"],
            "hf_upvotes": p["upvotes"],
            "github_stars": None,
            "date": p["date"],
        })

    # 构建输出结构
    today = datetime.now(timezone(timedelta(hours=8)))
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    week_range = f"{week_start.strftime('%m/%d')}-{week_end.strftime('%m/%d')}"

    output = {
        "updated_at": today.strftime("%Y-%m-%d"),
        "week_range": week_range,
        "papers": output_papers,
        "direction_summary": {
            "headline": f"本周热点: {output_papers[0]['direction'] if output_papers else 'N/A'}",
            "emerging_directions": list(set(p["direction"] for p in output_papers))[:5]
        }
    }

    # 写入文件
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 已写入 {DATA_FILE} ({len(output_papers)} 篇论文)")


if __name__ == "__main__":
    main()

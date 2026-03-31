#!/usr/bin/env python3
"""
update_papers.py
解析由外部 fetch 写入 /tmp/hf_papers_YYYY-MM-DD.txt 的 HF Daily Papers 文本，
排序信号：HF upvote（60%）+ GitHub stars（40%）加权，取 top 15
更新 data/papers.json

网络层由 OpenClaw 小白通过 web_fetch 完成，本脚本只做解析+排序+写 JSON。
"""
import json
import math
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_FILE = ROOT / "data" / "papers.json"
TMP_DIR = Path("/tmp")


def get_recent_dates(days: int = 7) -> list[str]:
    dates = []
    today = datetime.now(timezone(timedelta(hours=8)))
    for i in range(days):
        d = today - timedelta(days=i)
        dates.append(d.strftime("%Y-%m-%d"))
    return dates


def parse_papers_from_text(text: str, date_str: str) -> list[dict]:
    """从 web_fetch 返回的纯文本中解析论文"""
    papers = []
    seen = set()

    # 找所有 HF paper 链接（含 arxiv ID）
    # 格式示例: https://huggingface.co/papers/2603.25716
    hf_ids = re.findall(r'huggingface\.co/papers/([\d]{4}\.\d+)', text)

    # 找 upvote 数字（紧跟在标题前的独立数字行）
    # 文本格式: submitter\n\nN\n\nTitle\n
    lines = text.split('\n')
    lines = [l.strip() for l in lines if l.strip()]

    # 构建 id->upvote 映射：找数字行，往后找标题
    id_upvote = {}
    for i, hf_id in enumerate(hf_ids):
        if hf_id in seen:
            continue
        seen.add(hf_id)
        # 在文本中找这个 id 附近的数字作为 upvote
        # 搜索模式：id 前后几行里的独立数字
        idx = text.find(hf_id)
        snippet = text[max(0, idx-200):idx+500]
        nums = re.findall(r'\b(\d{1,4})\b', snippet)
        upvotes = 0
        if nums:
            # 取最大的合理数字（1-9999）作为 upvote 候选
            candidates = [int(n) for n in nums if 1 <= int(n) <= 9999]
            if candidates:
                upvotes = max(candidates)

        # 找标题：在 id 后面的文本里找最长的非数字行
        after = text[idx+len(hf_id):idx+len(hf_id)+600]
        title_candidates = re.findall(r'([A-Z][^\n]{15,120})', after)
        title = title_candidates[0].strip() if title_candidates else ""

        if hf_id and title:
            papers.append({
                "id": hf_id,
                "title": title,
                "upvotes": upvotes,
                "date": date_str,
            })

    return papers


def fetch_github_stars(repo_url: str) -> int:
    """从 GitHub API 抓取 stars 数"""
    try:
        match = re.search(r'github\.com/([^/\s"]+/[^/\s"]+)', repo_url)
        if not match:
            return 0
        repo_path = match.group(1).rstrip('/')
        api_url = f"https://api.github.com/repos/{repo_path}"
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/vnd.github+json",
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("stargazers_count", 0)
    except Exception:
        return 0


def fetch_paper_details(arxiv_id: str) -> dict:
    """从 arXiv API 获取摘要和作者"""
    try:
        url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml = resp.read().decode("utf-8")
        summary_match = re.search(r'<summary>(.*?)</summary>', xml, re.DOTALL)
        summary = ""
        if summary_match:
            summary = re.sub(r'\s+', ' ', summary_match.group(1)).strip()[:300]
        authors = re.findall(r'<name>(.*?)</name>', xml)
        authors_str = ", ".join(authors[:3]) if authors else ""
        if len(authors) > 3:
            authors_str += " et al."
        return {"summary": summary, "authors": authors_str}
    except Exception:
        return {"summary": "", "authors": ""}


def classify_direction(title: str) -> str:
    text = title.lower()
    if "agent" in text:
        return "Agent"
    if any(k in text for k in ["memory", "context", "token", "long context"]):
        return "长上下文"
    if any(k in text for k in ["multimodal", "vision", "image", "video", "visual"]):
        return "多模态"
    if any(k in text for k in ["reasoning", "thinking", "chain", "cot", "logic"]):
        return "推理"
    if any(k in text for k in ["safety", "align", "harmless", "red-team"]):
        return "安全"
    if any(k in text for k in ["diffusion", "generation", "synthesis"]):
        return "图像生成"
    if any(k in text for k in ["speech", "audio", "tts", "voice"]):
        return "语音生成"
    if any(k in text for k in ["science", "biology", "protein", "drug", "molecule"]):
        return "AI for Science"
    if any(k in text for k in ["distillation", "training", "rlhf", "finetune", "pretrain"]):
        return "训练方法"
    return "前沿方法"


def get_significance(upvotes: int, github_stars: int = 0) -> str:
    if upvotes >= 500 or github_stars >= 5000:
        return "hot"
    if upvotes >= 100 or github_stars >= 1000:
        return "breakthrough"
    if upvotes >= 30 or github_stars >= 200:
        return "notable"
    return "emerging"


def compute_score(upvotes: int, github_stars: int) -> float:
    return math.log1p(upvotes) * 0.6 + math.log1p(github_stars) * 0.4


def main():
    print("📚 解析 HF Daily Papers（from /tmp/hf_papers_*.txt）...")

    dates = get_recent_dates(7)
    all_papers = []
    seen_ids = set()

    for date_str in dates:
        tmp_file = TMP_DIR / f"hf_papers_{date_str}.txt"
        if not tmp_file.exists():
            print(f"  ⚠️  {date_str}: 文件不存在，跳过")
            continue
        text = tmp_file.read_text(encoding="utf-8")
        papers = parse_papers_from_text(text, date_str)
        print(f"  {date_str}: 解析到 {len(papers)} 篇")
        for p in papers:
            if p["id"] in seen_ids:
                continue
            seen_ids.add(p["id"])
            all_papers.append(p)

    if not all_papers:
        print("  ⚠️  没有可用数据，保留旧 papers.json")
        return

    # 粗筛 top 30（按 upvote），补充 GitHub stars，加权排序
    all_papers.sort(key=lambda x: x["upvotes"], reverse=True)
    candidates = all_papers[:30]

    print(f"\n  补充 GitHub stars（前 30 篇）...")
    for p in candidates:
        # GitHub stars：从文本中提取 github.com 链接（如果有）
        tmp_file = TMP_DIR / f"hf_papers_{p['date']}.txt"
        github_url = ""
        stars = 0
        if tmp_file.exists():
            text = tmp_file.read_text()
            idx = text.find(p["id"])
            if idx >= 0:
                snippet = text[idx:idx+500]
                gh_match = re.search(r'github\.com/([^/\s"]+/[^/\s"]+)', snippet)
                if gh_match:
                    github_url = f"https://github.com/{gh_match.group(1)}"
                    stars = fetch_github_stars(github_url)
        p["github_url"] = github_url
        p["github_stars"] = stars
        p["score"] = compute_score(p["upvotes"], stars)
        print(f"    {p['id']}: upvote={p['upvotes']} stars={stars} score={p['score']:.2f}")

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_papers = candidates[:15]

    output_papers = []
    for p in top_papers:
        print(f"    ✓ {p['title'][:60]}...")
        details = fetch_paper_details(p["id"])
        direction = classify_direction(p["title"])
        output_papers.append({
            "id": p["id"],
            "title": p["title"],
            "url": f"https://arxiv.org/abs/{p['id']}",
            "github_url": p.get("github_url", ""),
            "direction": direction,
            "significance": get_significance(p["upvotes"], p["github_stars"]),
            "breakthrough": details["summary"] or f"arXiv {p['id']}",
            "tags": [direction],
            "authors": details["authors"],
            "institution": "",
            "hf_upvotes": p["upvotes"],
            "github_stars": p["github_stars"],
            "score": round(p["score"], 2),
            "date": p["date"],
        })

    today = datetime.now(timezone(timedelta(hours=8)))
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    output = {
        "updated_at": today.strftime("%Y-%m-%d"),
        "week_range": f"{week_start.strftime('%m/%d')}-{week_end.strftime('%m/%d')}",
        "papers": output_papers,
        "direction_summary": {
            "headline": f"本周热点: {output_papers[0]['direction'] if output_papers else 'N/A'}",
            "emerging_directions": list(dict.fromkeys(p["direction"] for p in output_papers))[:5]
        }
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 写入 {DATA_FILE}（{len(output_papers)} 篇）")


if __name__ == "__main__":
    main()

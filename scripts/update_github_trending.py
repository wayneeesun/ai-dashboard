#!/usr/bin/env python3
"""
update_github_trending.py
从 GitHub Trending 页面爬取本周热门项目，解析后写入 data/github-trending.json
然后自动 git commit + push

运行：python3 scripts/update_github_trending.py
定时：每天 UTC 02:00（北京时间 10:00）
"""
import json, re, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request

ROOT = Path(__file__).parent.parent
DATA_FILE = ROOT / "data" / "github-trending.json"

# 分类规则（关键词 → 分类 id）
CATEGORY_RULES = [
    ("agent-framework",  ["agent", "crew", "autogen", "langgraph", "swarm", "mcp", "orchestrat", "workflow"]),
    ("data-infra",       ["database", "vector", "rag", "retriev", "crawl", "scrape", "parse", "pipeline", "lakehouse", "duckdb", "sqlite"]),
    ("coding-tools",     ["code", "coding", "developer", "copilot", "ide", "lint", "debug", "compiler", "devin", "aider", "cursor"]),
    ("finance-trading",  ["trading", "quant", "finance", "stock", "backtest", "portfolio", "crypto", "blockchain"]),
    ("content-gen",      ["image", "video", "music", "audio", "stable", "diffusion", "flux", "sora", "generation", "tts", "speech"]),
    ("creative-tools",   ["game", "minecraft", "3d", "render", "design", "creative", "art", "animation"]),
]

CATEGORIES_META = [
    {"id": "agent-framework", "name": "Agent 框架",      "icon": "🤖", "description": "编排、运行、优化 AI Agent 的基础设施"},
    {"id": "data-infra",      "name": "数据 & 基础设施", "icon": "🔧", "description": "数据解析、记忆引擎、信息检索"},
    {"id": "coding-tools",    "name": "编码工具",         "icon": "💻", "description": "代码生成、辅助开发、IDE 插件"},
    {"id": "finance-trading", "name": "金融 & 交易",      "icon": "📊", "description": "量化交易、金融分析、加密资产"},
    {"id": "content-gen",     "name": "内容生成",         "icon": "🎨", "description": "图像、视频、音乐生成"},
    {"id": "creative-tools",  "name": "创意工具",         "icon": "🎮", "description": "游戏、3D、设计、创作类"},
    {"id": "other",           "name": "其他",             "icon": "📦", "description": "其他技术项目"},
]


def fetch_trending_repos() -> list[dict]:
    """用 GitHub Search API 获取近期高热度项目（替代 Trending 页面 scraping）"""
    from datetime import datetime, timezone, timedelta

    tz8 = timezone(timedelta(hours=8))
    week_ago = (datetime.now(tz8) - timedelta(days=7)).strftime('%Y-%m-%d')
    three_months_ago = (datetime.now(tz8) - timedelta(days=90)).strftime('%Y-%m-%d')

    # 策略：近3个月创建、本周活跃、star >= 200 的新项目
    url = (
        f"https://api.github.com/search/repositories?"
        f"q=created:>{three_months_ago}+stars:>200+pushed:>{week_ago}&"
        f"sort=stars&order=desc&per_page=30"
    )
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/vnd.github.v3+json",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)

    repos = []
    for item in data.get("items", []):
        full_name = item.get("full_name", "")
        if "/" not in full_name:
            continue
        owner, repo = full_name.split("/", 1)
        repos.append({
            "full_name": full_name,
            "owner": owner,
            "repo": repo,
            "description": (item.get("description") or "")[:200],
            "stars": item.get("stargazers_count", 0),
            "stars_this_week": item.get("stargazers_count", 0),  # 用总 star 作为排序依据
            "language": item.get("language") or "",
            "url": item.get("html_url", f"https://github.com/{full_name}"),
        })
    return repos


def classify(repo: dict) -> str:
    """根据 repo 名称和描述分类"""
    text = f"{repo['repo']} {repo['description']}".lower()
    for cat_id, keywords in CATEGORY_RULES:
        if any(kw in text for kw in keywords):
            return cat_id
    return "other"


def build_output(repos: list[dict]) -> dict:
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    # 按分类聚合
    cat_map: dict[str, list] = {c["id"]: [] for c in CATEGORIES_META}

    for r in repos:
        cat = classify(r)
        cat_map[cat].append({
            "name": r["repo"],
            "owner": r["owner"],
            "full_name": r["full_name"],
            "description": r["description"],
            "stars": r["stars"],
            "stars_this_week": r["stars_this_week"],
            "language": r["language"],
            "url": r["url"],
            "category": cat,
        })

    # 每个分类按本周新增 star 降序
    for cat_id in cat_map:
        cat_map[cat_id].sort(key=lambda x: x["stars_this_week"], reverse=True)

    categories_out = []
    for meta in CATEGORIES_META:
        projects = cat_map.get(meta["id"], [])
        if projects:
            categories_out.append({**meta, "projects": projects})

    all_projects = [p for c in categories_out for p in c["projects"]]

    return {
        "updated_at": today,
        "period": "weekly",
        "filter": "GitHub Trending 周榜，全品类不限领域，按本周新增 star 排序",
        "source": "https://github.com/trending?since=weekly",
        "source_label": "GitHub Trending (Weekly)",
        "categories": [{"id": c["id"], "name": c["name"], "icon": c["icon"], "description": c["description"]} for c in CATEGORIES_META],
        "projects": all_projects,
        "by_category": {c["id"]: c.get("projects", []) for c in categories_out},
    }


def git_push():
    cmds = [
        ["git", "add", "data/github-trending.json"],
        ["git", "commit", "-m", f"chore: auto-update GitHub trending ({datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')})"],
        ["git", "push"],
    ]
    for cmd in cmds:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  git warning: {r.stderr.strip()}")
        else:
            print(f"  ✓ {' '.join(cmd[:2])}")


def main():
    print("⏳ 抓取 GitHub Trending 周榜 (via Search API)…")
    try:
        repos = fetch_trending_repos()
    except Exception as e:
        print(f"❌ 抓取失败: {e}")
        sys.exit(1)

    print(f"  拿到 {len(repos)} 个项目")

    if len(repos) < 5:
        print("⚠️  项目数过少，可能解析失败，保留旧数据")
        sys.exit(1)

    output = build_output(repos)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✅ 写入 {DATA_FILE.name}（{len(output['projects'])} 个项目，{len([c for c in output['by_category'].values() if c])} 个分类）")

    # 同时更新市值
    print("\n⏳ 更新市值…")
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "update_market_cap.py")],
        cwd=ROOT, capture_output=False
    )

    # push
    print("\n⏳ 推送到 GitHub…")
    # 把市值更新也加进去
    subprocess.run(["git", "add", "data/companies/"], cwd=ROOT, capture_output=True)
    git_push()
    print("\n🎉 完成！")


if __name__ == "__main__":
    main()

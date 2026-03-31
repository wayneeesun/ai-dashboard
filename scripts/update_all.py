#!/usr/bin/env python3
"""
update_all.py
主调度脚本：每日运行，同步更新所有数据并推送到 GitHub
"""
import json
import os
import base64
import urllib.request
import urllib.error
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# GitHub API 配置
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "wayneeesun/ai-dashboard"
BRANCH = "main"

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
STATUS_FILE = DATA_DIR / "update_status.json"


def push_file(fpath_relative: str, base_dir: Path):
    """使用 GitHub Contents API 推送文件"""
    full = base_dir / fpath_relative
    with open(full, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    url = f"https://api.github.com/repos/{REPO}/contents/{fpath_relative}?ref={BRANCH}"
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req)
        sha = json.loads(resp.read())["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            sha = None
        else:
            raise

    body = {
        "message": f"auto update {fpath_relative} ({datetime.now().strftime('%Y-%m-%d')})",
        "content": content,
        "branch": BRANCH
    }
    if sha:
        body["sha"] = sha

    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/{fpath_relative}",
        data=json.dumps(body).encode(),
        headers=headers,
        method="PUT"
    )
    urllib.request.urlopen(req)
    print(f"  ✓ pushed {fpath_relative}")


def get_today_str():
    """获取今天的日期字符串"""
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def load_update_status():
    """加载更新状态文件"""
    if STATUS_FILE.exists():
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"sectors": {}}


def save_update_status(status):
    """保存更新状态文件"""
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def update_status(sector_id: str, status_code: str = "ok", note: str = ""):
    """更新指定栏目的状态"""
    status = load_update_status()
    if "sectors" not in status:
        status["sectors"] = {}

    status["sectors"][sector_id] = {
        "last_updated": get_today_str(),
        "status": status_code,
        "note": note
    }
    save_update_status(status)
    print(f"  ✓ updated status for {sector_id}")


# === 市值更新逻辑（从 update_market_cap.py 提取）===

# ticker → (stooq symbol, shares_outstanding_bn, currency, hkd_to_usd)
COMPANIES = {
    # 美国互联网 (shares in 亿股)
    "meta":       ("META.US",   25.6,  "USD", 1.0),
    "google":     ("GOOGL.US", 121.1,  "USD", 1.0),
    "amazon":     ("AMZN.US",  106.2,  "USD", 1.0),
    "applovin":   ("APP.US",    33.1,  "USD", 1.0),
    "pinterest":  ("PINS.US",   14.7,  "USD", 1.0),
    "reddit":     ("RDDT.US",    2.3,  "USD", 1.0),

    # 中国互联网（港股换算 USD，HKD/USD≈0.128；shares 单位：亿股）
    "tencent":    ("700.HK",    95.57, "HKD", 0.128),
    "alibaba":    ("9988.HK",  213.7,  "HKD", 0.128),
    "meituan":    ("3690.HK",  163.7,  "HKD", 0.128),
    "pdd":        ("PDD.US",   139.3,  "USD", 1.0),
    "baidu":      ("BIDU.US",   13.9,  "USD", 1.0),
    "jd":         ("JD.US",     16.0,  "USD", 1.0),

    # 半导体
    "nvidia":     ("NVDA.US",  244.4,  "USD", 1.0),
    "tsmc":       ("TSM.US",    25.9,  "USD", 1.0),
    "broadcom":   ("AVGO.US",   46.6,  "USD", 1.0),
    "amd":        ("AMD.US",   161.5,  "USD", 1.0),
    "sandisk":    ("SNDK.US",   23.2,  "USD", 1.0),
    "micron":     ("MU.US",    111.0,  "USD", 1.0),

    # 软件
    "microsoft":  ("MSFT.US",   74.3,  "USD", 1.0),
    "shopify":    ("SHOP.US",  126.8,  "USD", 1.0),
    "oracle":     ("ORCL.US",  274.4,  "USD", 1.0),
    "servicenow": ("NOW.US",    20.3,  "USD", 1.0),
    "snowflake":  ("SNOW.US",   33.2,  "USD", 1.0),
    "cloudflare": ("NET.US",    33.0,  "USD", 1.0),
}


def fetch_price(symbol: str) -> float | None:
    """从 Stooq 获取股价"""
    url = f"https://stooq.com/q/l/?s={symbol.lower()}&f=sd2t2ohlcv&h&e=csv"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            lines = resp.read().decode().strip().split("\n")
        if len(lines) < 2:
            return None
        parts = lines[1].split(",")
        close = float(parts[6])
        return close
    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return None


def fmt_market_cap(usd_bn: float) -> str:
    if usd_bn >= 1000:
        return f"${usd_bn/1000:.1f}T"
    return f"${usd_bn:.0f}B"


def update_market_cap():
    """更新市值数据"""
    print("\n📊 更新市值...")
    results = {}

    for company_id, (symbol, shares, currency, fx) in COMPANIES.items():
        price = fetch_price(symbol)
        if price is None:
            print(f"  SKIP {company_id}: no price")
            results[company_id] = None
            continue

        mktcap_local = price * shares * 1e8   # 本币
        mktcap_usd_bn = mktcap_local * fx / 1e9

        fmt = fmt_market_cap(mktcap_usd_bn)
        results[company_id] = {
            "market_cap_usd_bn": round(mktcap_usd_bn, 1),
            "market_cap_fmt": fmt,
            "price": price,
            "currency": currency,
            "symbol": symbol,
        }
        print(f"  {company_id:12s} {symbol:10s} price={price:8.2f} mktcap={fmt}")

    # 写回各公司 JSON
    updated = 0
    for company_id, mc_data in results.items():
        if mc_data is None:
            continue
        fpath = DATA_DIR / "companies" / f"{company_id}.json"
        if not fpath.exists():
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            company = json.load(f)

        # 找 key_metrics，没有就创建
        profile = company.setdefault("profile", {})
        metrics = profile.setdefault("key_metrics", {})
        metrics["market_cap"] = mc_data["market_cap_fmt"]
        metrics["market_cap_usd_bn"] = mc_data["market_cap_usd_bn"]
        metrics["price"] = mc_data["price"]
        metrics["price_currency"] = mc_data["currency"]
        metrics["updated_at"] = get_today_str()

        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(company, f, ensure_ascii=False, indent=2)
        updated += 1

    print(f"  ✓ 更新 {updated} 个公司文件")

    # 更新各板块状态
    update_status("us-internet", "ok", "市值已更新")
    update_status("cn-internet", "ok", "市值已更新")
    update_status("semiconductor", "ok", "市值已更新")
    update_status("software", "ok", "市值已更新")
    update_status("ai-native", "ok", "市值已更新")

    return updated > 0


# === GitHub Trending 更新 ===

def update_github_trending():
    """更新 GitHub Trending"""
    print("\n📦 更新 GitHub Trending...")
    
    # 调用 update_github_trending.py 的逻辑
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import update_github_trending as gh
        # 设置 DATA_FILE 路径
        gh.DATA_FILE = DATA_DIR / "github-trending.json"
        # 获取数据
        repos = gh.fetch_trending_repos()
        print(f"  拿到 {len(repos)} 个项目")
        
        if len(repos) < 5:
            print("  ⚠️ 项目数过少，可能解析失败")
            return False
        
        output = gh.build_output(repos)
        with open(DATA_DIR / "github-trending.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"  ✓ 写入 github-trending.json")
        
        update_status("github-trend", "ok")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False
    finally:
        sys.path.pop(0)


# === YouTubers 更新 ===

def update_youtubers():
    """更新 YouTubers"""
    print("\n🎬 更新 YouTubers...")
    
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import update_youtubers as yt
        yt.DATA_FILE = DATA_DIR / "youtubers.json"
        yt.main()
        update_status("voices", "ok")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False
    finally:
        sys.path.pop(0)


# === Papers 更新 ===

def update_papers():
    """更新论文导读"""
    print("\n📝 更新论文导读...")
    
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import update_papers as papers
        papers.ROOT = ROOT
        papers.DATA_FILE = DATA_DIR / "papers.json"
        papers.main()
        update_status("paper-reading", "ok")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False
    finally:
        sys.path.pop(0)


# === 主函数 ===

def main():
    print("=" * 50)
    print(f"🚀 开始每日更新 - {get_today_str()}")
    print("=" * 50)

    files_to_push = []
    
    # 1. 更新市值
    if update_market_cap():
        # 收集所有更新的公司文件
        for company_id in COMPANIES.keys():
            fpath = f"data/companies/{company_id}.json"
            if (DATA_DIR / "companies" / f"{company_id}.json").exists():
                files_to_push.append(fpath)
        files_to_push.append("data/update_status.json")

    # 2. 更新 GitHub Trending
    if update_github_trending():
        files_to_push.append("data/github-trending.json")
        files_to_push.append("data/update_status.json")

    # 3. 更新 YouTubers（Voices 板块）
    if update_youtubers():
        files_to_push.append("data/youtubers.json")
        files_to_push.append("data/voices_x.json")
        files_to_push.append("data/update_status.json")

    # 4. 更新论文（每天尝试，/tmp/hf_papers_*.txt 由小白 fetch 写入）
    papers_file = DATA_DIR / "papers.json"
    tmp_files = list(Path("/tmp").glob("hf_papers_*.txt"))
    if tmp_files:
        if update_papers():
            files_to_push.append("data/papers.json")
            files_to_push.append("data/update_status.json")
    else:
        print("\n📝 论文导读（跳过，/tmp 无 hf_papers_*.txt，需先由小白 fetch）")

    # 去重
    files_to_push = list(dict.fromkeys(files_to_push))

    # 5. 推送到 GitHub
    if files_to_push:
        print(f"\n🚀 推送到 GitHub...")
        print(f"  将要推送: {files_to_push}")
        for fpath in files_to_push:
            try:
                push_file(fpath, ROOT)
            except Exception as e:
                print(f"  ❌ 推送失败 {fpath}: {e}")
    else:
        print("\n✅ 没有文件需要推送")

    print("\n" + "=" * 50)
    print("🎉 每日更新完成!")
    print("=" * 50)


if __name__ == "__main__":
    main()

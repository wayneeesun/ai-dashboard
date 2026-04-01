#!/usr/bin/env python3
"""
update_market_cap.py
拉取上市公司实时股价（via Stooq），结合本地 shares_outstanding，
计算市值并写回 data/companies/*.json
运行：python3 scripts/update_market_cap.py
"""
import json, os, requests, time
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data" / "companies"

# ticker → (stooq symbol, shares_outstanding_bn, currency, hkd_to_usd)
# shares_outstanding 单位：亿股
# 港股市值最终换算成 USD（HKD/USD ≈ 0.128）
COMPANIES = {
    # 美国互联网 (shares in 亿股)
    # 数据来源：Yahoo Finance / CompaniesMarketCap / MacroTrends，截至2026年3月
    "meta":       ("META.US",   25.3,  "USD", 1.0),    # 2.53B shares
    "google":     ("GOOGL.US", 120.73, "USD", 1.0),    # 12.073B shares
    "amazon":     ("AMZN.US",  106.56, "USD", 1.0),    # 10.656B shares
    "applovin":   ("APP.US",     3.38, "USD", 1.0),    # 338M shares
    "pinterest":  ("PINS.US",    6.68, "USD", 1.0),    # 668M shares
    "reddit":     ("RDDT.US",    2.06, "USD", 1.0),    # 206M shares

    # 中国互联网（港股换算 USD，HKD/USD≈0.128；shares 单位：亿股）
    "tencent":    ("700.HK",    95.57, "HKD", 0.128),  # 9,557M shares
    "alibaba":    ("9988.HK",  213.7,  "HKD", 0.128),  # 21,370M shares
    "meituan":    ("3690.HK",  163.7,  "HKD", 0.128),  # 16,370M shares
    "pdd":        ("PDD.US",    14.2,  "USD", 1.0),    # 1.42B shares
    "baidu":      ("BIDU.US",    3.40, "USD", 1.0),    # 340M shares
    "jd":         ("JD.US",     14.5,  "USD", 1.0),    # 1.45B shares (ADR)

    # 半导体
    "nvidia":     ("NVDA.US",  243.04, "USD", 1.0),    # 24.304B shares
    "tsmc":       ("TSM.US",    51.9,  "USD", 1.0),    # 5.19B ADR shares
    "broadcom":   ("AVGO.US",   47.4,  "USD", 1.0),    # 4.74B shares
    "amd":        ("AMD.US",    16.3,  "USD", 1.0),    # 1.63B shares
    "sandisk":    ("SNDK.US",    2.32, "USD", 1.0),    # 232M shares (SanDisk post-split)
    "micron":     ("MU.US",     11.1,  "USD", 1.0),    # 1.11B shares

    # 软件
    "microsoft":  ("MSFT.US",   74.3,  "USD", 1.0),    # 7.43B shares
    "shopify":    ("SHOP.US",   13.1,  "USD", 1.0),    # 1.31B shares
    "oracle":     ("ORCL.US",   28.76, "USD", 1.0),    # 2.876B shares
    "servicenow": ("NOW.US",    10.5,  "USD", 1.0),    # 1.05B shares
    "snowflake":  ("SNOW.US",    3.42, "USD", 1.0),    # 342M shares
    "cloudflare": ("NET.US",     3.18, "USD", 1.0),    # 318M shares
}

# 港股特殊处理（已在 COMPANIES 中统一为亿股，此 dict 废弃）
HK_SHARES_MN = {}

def fetch_price(symbol: str) -> float | None:
    url = f"https://stooq.com/q/l/?s={symbol.lower()}&f=sd2t2ohlcv&h&e=csv"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        lines = r.text.strip().split("\n")
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

def main():
    results = {}

    for company_id, (symbol, shares, currency, fx) in COMPANIES.items():
        price = fetch_price(symbol)
        if price is None:
            print(f"  SKIP {company_id}: no price")
            results[company_id] = None
            continue

        # 特殊处理港股 shares（单位 mn → 亿）
        if company_id in HK_SHARES_MN:
            shares_actual = HK_SHARES_MN[company_id] / 100  # mn → 亿
        else:
            shares_actual = shares  # 已经是亿股

        mktcap_local = price * shares_actual * 1e8   # 本币，元
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
        time.sleep(0.3)  # 避免限速

    # 写回各公司 JSON
    updated = 0
    for company_id, mc_data in results.items():
        fpath = DATA_DIR / f"{company_id}.json"
        if not fpath.exists() or mc_data is None:
            continue
        with open(fpath) as f:
            company = json.load(f)

        # 找 key_metrics，没有就创建
        profile = company.setdefault("profile", {})
        metrics = profile.setdefault("key_metrics", {})
        metrics["market_cap"] = mc_data["market_cap_fmt"]
        metrics["market_cap_usd_bn"] = mc_data["market_cap_usd_bn"]
        metrics["price"] = mc_data["price"]
        metrics["price_currency"] = mc_data["currency"]
        metrics["updated_at"] = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d")

        with open(fpath, "w") as f:
            json.dump(company, f, ensure_ascii=False, indent=2)
        updated += 1

    print(f"\n✅ 更新 {updated} 个公司文件")

if __name__ == "__main__":
    main()

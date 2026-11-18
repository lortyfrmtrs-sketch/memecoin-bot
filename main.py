#!/usr/bin/env python3
"""
Valk's Insider Bot  v4.1.0
Early Hunter + Reputation edition.

Goal: Catch high-quality coins in the true early zone (roughly 5k–40k MC)
that still have realistic room to run toward 200–500k, while strongly
rejecting late/extended coins that damage reputation.

Improvements in 4.1:
- More aggressive discovery (more Solana pages + slightly faster cycle)
- Hard MC ceiling $85k (still blocks 6-figure late calls)
- Strong preference for under 40 min + under $35k
- Still rejects already-pumped profiles hard
- High safety standards kept
"""

import os
import re
import json
import time
import threading
import requests
from datetime import datetime, timezone
from collections import Counter

# ======================================================
# CONFIGURATION
# ======================================================
BOT_NAME = "Valk's Insider Bot"
CREDIT = "Created by @valk_ on Fomo"
VERSION = "4.1.0"

# ---- Discord webhooks (keep this file PRIVATE) ----
WEBHOOK_URL = "https://discord.com/api/webhooks/1571990911737405582/gk8RqKJdRWjOSahlwoJ1jwgLeGTycEsYipFkYJaidcvUb2mgtv8uGPjBNM888r49wfqp"
WEBHOOKS = {
    "callouts": WEBHOOK_URL,
    "legit":    "https://discord.com/api/webhooks/1572179140071788584/VkNt0IGCHgf4n5VQIcZpVdkV2SVbSyL-kQiqhW-9LUP0_EZoyOIJPLEbb7zGdGv4ByQn",
    "exit":     "https://discord.com/api/webhooks/1572181849743163534/EOfiZofRjTm7tMfB_c6dSqAZX33Q25aCNVuFwzzyoi-mOXsrDalgM3G0g7SgvoaOjyYC",
    "profit":   "https://discord.com/api/webhooks/1572181743602241628/hyY_K931H6dEC8NTd5N5yIuy8ulXok3P9WDXzSVAhsPvozGCILgVSl8_8CoUoCTOWVaq",
    "updates":  "https://discord.com/api/webhooks/1572187465547255898/zl1XiPtRaCXFylwk84rqllawjUsRTngaY4wFh6Y2uRYsBh1y6cbmwdOIILvTOwnLfCYO",
    "rejected": "https://discord.com/api/webhooks/1572214932437467290/YDHnjzY-Qye0WLTyZGX7otrFTVDRwXypvbNyTt-6nuRbQelBeullgrfvjWyxXCvwvCVQ",
    "results":  "https://discord.com/api/webhooks/1572558043541938297/97Rv4OO0feG5RGzv4lYBiVOrGr8NaQQZDb7FZ59L9H6rDp3-sfPPF4M_tQocYeT2YmUZ",
}

CHECK_INTERVAL = 14                  # faster cycle
REALERT_AFTER = 4 * 3600
RECHECK_REJECTED_AFTER = 420
MAX_DEEP_CHECKS_PER_SCAN = 38
STATUS_EVERY = 15 * 60
SEND_STATUS = True
SEND_RESULT_UPDATES = True
VERSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bot_version")

# ---- Bullish filters — TRUE EARLY HUNTER ----
MIN_PAIR_AGE_MIN = 5
MAX_PAIR_AGE_MIN = 110               # slightly wider than 4.0 but still early
MIN_LIQUIDITY_USD = 4_800
MIN_VOLUME_24H = 5_200
MIN_MARKET_CAP = 4_000
MAX_MARKET_CAP = 85_000              # hard ceiling — still kills 6-figure late calls
MIN_TXNS_24H = 42
MIN_LIQ_TO_MCAP = 0.055
MIN_BUY_SELL_RATIO_H1 = 1.18
MAX_24H_PUMP_PCT = 320
MAX_VOL_TO_LIQ = 45
MIN_SCORE = 72

# ---- Legit filters — HIGH SAFETY ----
MIN_LEGIT_SCORE = 76
MAX_RUGCHECK_SCORE = 28
MAX_TOP10_HOLDER_PCT = 36
MIN_HOLDERS = 75
MAX_INSIDERS_TOP10 = 1
MAX_CREATOR_PCT = 5.0
MAX_TRANSFER_FEE_PCT = 3
MIN_LP_LOCKED_PCT = 55
MAX_TAX_PCT = 6
MIN_SOCIAL_LINKS = 1
REQUIRE_WEBSITE_AND_SOCIAL = False
REQUIRE_LIVE_SITE = False
REQUIRE_NARRATIVE = False
MIN_DESC_LEN = 10
REQUIRE_SAFETY_DATA = True

# ---- Live monitor ----
WATCH_EVERY = 2
CONFIRM_SECONDS = 3.5
CONFIRM_MAX_LIQ_DROP = 0.19
CONFIRM_MAX_PRICE_DROP = 0.19
MONITOR_HOURS = 5
EXIT_LIQ_DROP = 0.25
EXIT_PRICE_DROP = 0.29
PEAK_PULLBACK = 0.19
TAKE_PROFIT_X = (2, 3, 5, 10)
CHECKPOINTS_H = (0.25, 1, 6, 24)

CHAINS = {"solana", "base", "ethereum", "bsc"}
GECKO_NETWORKS = {"solana": "solana", "base": "base", "eth": "ethereum", "bsc": "bsc"}
GECKO_NEW_PAGES = {"solana": 9, "base": 3, "eth": 2, "bsc": 2}   # more Solana discovery
GOPLUS_CHAIN = {"ethereum": "1", "bsc": "56", "base": "8453"}
GMGN_CHAIN = {"solana": "sol", "base": "base", "ethereum": "eth", "bsc": "bsc"}
CHAIN_ICON = {"solana": "◎", "base": "🔵", "ethereum": "⟠", "bsc": "🟡"}
SEARCH_TERMS = (
    "pump", "pumpfun", "meme", "pepe", "dog", "cat", "ai agent", "trump", "bonk", "frog",
    "moon", "inu", "elon", "wojak", "chad", "baby", "king", "cult", "goat", "sol",
    "agent", "neiro", "mog", "popcat", "wif", "bome", "mew", "gigachad", "based",
    "ai", "robot", "solana", "base", "new", "launch"
)

RED_WORDS = [
    "guaranteed", "risk free", "risk-free", "no risk", "can't lose", "cant lose", "presale",
    "claim airdrop", "connect wallet", "send sol", "send eth", "double your", "ponzi",
    "pump and dump", "rug", "rugpull", "rug pull", "honeypot", "100x guaranteed", "free money",
]
RED_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in RED_WORDS) + r")\b", re.I)

THEMES = {
    "Animal meme": {"dog", "doge", "cat", "kitty", "frog", "pepe", "shib", "inu", "monkey", "ape", "bear", "bull",
                    "penguin", "hamster", "rabbit", "duck", "fox", "wolf", "bird", "fish", "whale", "pig", "cow",
                    "horse", "panda", "tiger", "lion", "bonk", "wif", "hippo", "goat", "cheems", "pup", "puppy",
                    "neiro", "mog", "popcat", "mew"},
    "Politics / public figure": {"trump", "maga", "biden", "elon", "musk", "president", "election", "vote", "congress"},
    "Tech / automation": {"ai", "agent", "agents", "gpt", "bot", "robot", "neural", "quantum", "cyber", "tech", "agi"},
    "Internet culture": {"meme", "viral", "brainrot", "skibidi", "sigma", "rizz", "npc", "gigachad", "chad", "wojak",
                         "based", "tiktok", "anime", "gaming", "gamer", "vibes"},
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ValkInsiderBot/4.1)", "Accept": "application/json"}
DEX = "https://api.dexscreener.com"
GECKO = "https://api.geckoterminal.com/api/v2"
FOOTER = f"{BOT_NAME} • {CREDIT}"

DEFAULT_STATE = {"alerted": {}, "rejected": {}, "tracked": {}, "pending": {},
                 "stats": {"n": 0, "wins": 0, "sum": 0.0, "x2": 0},
                 "scans": 0, "alerts": 0, "last_status": 0, "last_reject_post": 0}
state = json.loads(json.dumps(DEFAULT_STATE))
profile_desc = {}


# ======================================================
# HELPERS
# ======================================================
def num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def trunc(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def get_json(url, params=None, retries=3, timeout=11):
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 429:
                sleep_for = 2.8 * (attempt + 1)
                print(f"  rate limited, sleeping {sleep_for:.1f}s")
                time.sleep(sleep_for)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code >= 500:
                time.sleep(1.3)
                continue
            return None
        except Exception as e:
            print(f"  request error {url[:70]}...: {e}")
            time.sleep(0.9 + attempt * 0.4)
    return None


def fmt_usd(n):
    if n >= 1e9: return f"${n/1e9:.2f}B"
    if n >= 1e6: return f"${n/1e6:.2f}M"
    if n >= 1e3: return f"${n/1e3:.1f}K"
    return f"${n:.2f}"


def fmt_age(m):
    if m is None: return "?"
    if m < 60: return f"{m:.0f}m"
    if m < 1440: return f"{m/60:.1f}h"
    return f"{m/1440:.1f}d"


def score_bar(score, n=10):
    filled = max(0, min(n, round(score / 100 * n)))
    return "█" * filled + "░" * (n - filled)


# ======================================================
# 1) FIND COINS — more aggressive discovery
# ======================================================
def from_dexscreener_lists():
    found = set()
    for path in ("/token-profiles/latest/v1", "/token-boosts/latest/v1", "/token-boosts/top/v1",
                 "/community-takeovers/latest/v1"):
        data = get_json(DEX + path)
        if isinstance(data, list):
            for t in data:
                chain, addr = t.get("chainId"), t.get("tokenAddress")
                if chain in CHAINS and addr:
                    found.add((chain, addr))
                    if t.get("description"):
                        profile_desc[f"{chain}:{addr}"] = t["description"]
        time.sleep(0.35)
    return found


def from_geckoterminal():
    found = set()
    for net, chain in GECKO_NETWORKS.items():
        jobs = [("trending_pools", 1)] + [("new_pools", pg) for pg in range(1, GECKO_NEW_PAGES[net] + 1)]
        for kind, page in jobs:
            data = get_json(f"{GECKO}/networks/{net}/{kind}", params={"page": page})
            if not data:
                continue
            for pool in data.get("data", []):
                try:
                    base_id = pool["relationships"]["base_token"]["data"]["id"]
                    found.add((chain, base_id.split("_", 1)[1]))
                except Exception:
                    continue
            time.sleep(0.55)
    return found


def from_dexscreener_search():
    found = set()
    for q in SEARCH_TERMS:
        data = get_json(f"{DEX}/latest/dex/search", params={"q": q})
        if data:
            for p in data.get("pairs", []) or []:
                chain = p.get("chainId")
                addr = (p.get("baseToken") or {}).get("address")
                if chain in CHAINS and addr:
                    found.add((chain, addr))
        time.sleep(0.25)
    return found


def fetch_pairs(candidates, pause=0.25):
    by_chain = {}
    for chain, addr in candidates:
        by_chain.setdefault(chain, []).append(addr)
    best = {}
    for chain, addrs in by_chain.items():
        for i in range(0, len(addrs), 30):
            data = get_json(f"{DEX}/tokens/v1/{chain}/{','.join(addrs[i:i + 30])}",
                            retries=2 if pause else 1, timeout=10 if pause else 6)
            if isinstance(data, list):
                for p in data:
                    addr = (p.get("baseToken") or {}).get("address")
                    if not addr:
                        continue
                    key = f"{chain}:{addr}"
                    liq = (p.get("liquidity") or {}).get("usd") or 0
                    if key not in best or liq > ((best[key].get("liquidity") or {}).get("usd") or 0):
                        best[key] = p
            if pause:
                time.sleep(pause)
    return best


# ======================================================
# 2) BULLISH CHECK — EARLY HUNTER
# ======================================================
def evaluate(pair, nsrc=1):
    liq = num((pair.get("liquidity") or {}).get("usd"))
    mcap = num(pair.get("marketCap") or pair.get("fdv"))
    vol24 = num((pair.get("volume") or {}).get("h24"))
    vol1 = num((pair.get("volume") or {}).get("h1"))
    pc = pair.get("priceChange") or {}
    ch5, ch1, ch6, ch24 = num(pc.get("m5")), num(pc.get("h1")), num(pc.get("h6")), num(pc.get("h24"))
    tx = pair.get("txns") or {}
    b5, s5 = num((tx.get("m5") or {}).get("buys")), num((tx.get("m5") or {}).get("sells"))
    b1, s1 = num((tx.get("h1") or {}).get("buys")), num((tx.get("h1") or {}).get("sells"))
    b24, s24 = num((tx.get("h24") or {}).get("buys")), num((tx.get("h24") or {}).get("sells"))
    created = pair.get("pairCreatedAt")
    age_min = (time.time() * 1000 - created) / 60000 if created else None

    if liq < MIN_LIQUIDITY_USD:
        return None
    if not (MIN_MARKET_CAP <= mcap <= MAX_MARKET_CAP):
        return None
    if age_min is None or age_min < MIN_PAIR_AGE_MIN or age_min > MAX_PAIR_AGE_MIN:
        return None

    # === Strong protection against late / already-pumped coins ===
    if mcap > 32_000 and ch6 > 95:
        return None
    if mcap > 42_000 and ch24 > 180:
        return None
    if mcap > 55_000 and (ch6 > 70 or ch1 > 45):
        return None
    if ch1 >= 120 and mcap > 28_000:
        return None
    if ch5 >= 48 and mcap > 25_000:
        return None

    # Age-aware volume & txns
    min_vol = MIN_VOLUME_24H
    min_tx = MIN_TXNS_24H
    if age_min is not None and age_min < 16:
        min_vol = max(2600, MIN_VOLUME_24H * 0.48)
        min_tx = max(26, MIN_TXNS_24H * 0.48)
    elif age_min is not None and age_min < 28:
        min_vol = max(3600, MIN_VOLUME_24H * 0.68)
        min_tx = max(34, MIN_TXNS_24H * 0.68)

    if vol24 < min_vol:
        return None
    if (b24 + s24) < min_tx:
        return None
    if mcap and liq / mcap < MIN_LIQ_TO_MCAP:
        return None
    if liq and vol24 / liq > MAX_VOL_TO_LIQ:
        return None
    if ch24 > MAX_24H_PUMP_PCT or ch1 < -9 or ch24 < -38:
        return None
    if liq > 0 and vol1 > 0 and vol1 / liq > 9:
        return None

    ratio1 = b1 / max(s1, 1)
    ratio24 = b24 / max(s24, 1)
    ratio5 = b5 / max(s5, 1)

    if ratio1 < MIN_BUY_SELL_RATIO_H1 or ratio24 < 0.82:
        return None
    if (b5 + s5) >= 9 and ratio5 < 0.68:
        return None
    if b24 > 85 and s24 == 0:
        return None

    # --- Score (rewards true early hard) ---
    score = 0
    score += min(26, ratio1 * 11)
    score += min(11, ratio5 * 5) if (b5 + s5) >= 4 else 0
    score += min(10, max(0, (ratio24 - 1) * 16))
    score += 10 if ch5 >= 3 else (6 if ch5 >= 0 else 0)
    score += 11 if ch1 >= 8 else (7 if ch1 > 0 else 0)
    score += 5 if ch6 > 0 else 0
    score += 7 if 8 <= ch24 <= 250 else (3 if ch24 > 0 else 0)

    vol_accel = (vol1 * 24 / max(vol24, 1)) if vol24 else 0
    score += min(12, vol_accel * 6)

    liq_ratio = liq / max(mcap, 1)
    score += min(11, liq_ratio * 115)
    score += 6 if liq >= 13_000 else (3 if liq >= 7_000 else 0)

    info = pair.get("info") or {}
    score += 5 if info.get("socials") else 0
    score += 3 if info.get("websites") else 0

    # Age is the biggest lever for 5k→500k potential
    if age_min is not None:
        if 5 <= age_min <= 20:
            score += 19
        elif 20 < age_min <= 35:
            score += 12
        elif 35 < age_min <= 55:
            score += 6
        else:
            score += 1

    # Lower MC gets clear bonus
    if mcap < 15_000:
        score += 9
    elif mcap < 28_000:
        score += 5
    elif mcap > 55_000:
        score -= 7

    score += min(9, (nsrc - 1) * 4)

    if ch1 > 75 or ch5 > 28:
        score = min(score, 83)
    if mcap > 50_000:
        score = min(score, 81)

    return min(94, round(score)), {
        "liq": liq, "mcap": mcap, "vol24": vol24, "ch1": ch1, "ch6": ch6, "ch24": ch24,
        "ratio1": ratio1, "ratio5": ratio5, "age_min": age_min, "txns": b24 + s24, "nsrc": nsrc,
    }


# ======================================================
# 3) LEGIT CHECK
# ======================================================
def fetch_ipfs_json(uri):
    if not uri:
        return {}
    uri = uri.replace("ipfs://", "https://ipfs.io/ipfs/")
    data = get_json(uri, retries=0, timeout=6)
    return data if isinstance(data, dict) else {}


CRITICAL_DANGER = re.compile(
    r"honeypot|rug|mint.?authority|freeze.?authority|black.?list|pausable|ownership.?change|"
    r"can.?take.?back|hidden.?owner|proxy|upgradeable|malicious", re.I
)


def rugcheck_solana(mint):
    data = get_json(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")
    if not data:
        return {"ok": False, "reasons": ["RugCheck unavailable"], "facts": None, "desc": "", "image": ""}

    reasons = []
    risks = data.get("risks") or []
    danger = [r.get("name", "?") for r in risks if str(r.get("level", "")).lower() == "danger"]
    warn = [r.get("name", "?") for r in risks if str(r.get("level", "")).lower() == "warn"]

    if data.get("rugged"):
        reasons.append("already rugged")

    critical = [d for d in danger if CRITICAL_DANGER.search(d)]
    if critical:
        reasons.append("critical risk: " + ", ".join(critical[:3]))

    raw_score = data.get("score_normalised")
    risk_score = num(raw_score) if raw_score is not None else None
    if risk_score is not None and risk_score > MAX_RUGCHECK_SCORE:
        reasons.append(f"risk score {risk_score:.0f}")

    mint_ren = not data.get("mintAuthority")
    freeze_ren = not data.get("freezeAuthority")
    if not mint_ren:
        reasons.append("mint authority NOT renounced")
    if not freeze_ren:
        reasons.append("freeze authority NOT renounced")

    holders = data.get("topHolders") or []
    top10 = sum(num(h.get("pct")) for h in holders[:10])
    top1 = num(holders[0].get("pct")) if holders else 0.0
    if top10 > MAX_TOP10_HOLDER_PCT:
        reasons.append(f"top 10 hold {top10:.0f}%")
    if top1 >= 17:
        reasons.append(f"top wallet holds {top1:.0f}% (too concentrated)")
    insiders = sum(1 for h in holders[:10] if h.get("insider"))
    if insiders > MAX_INSIDERS_TOP10:
        reasons.append(f"{insiders} insider/linked wallets in top 10")
    insider_network = num(data.get("graphInsidersDetected")) > 0 or bool(data.get("insiderNetworks"))
    if insider_network:
        reasons.append("insider network detected")
    bundle_flags = [n for n in danger + warn if re.search(r"bundl|snip|insider|cluster", n, re.I)]
    if bundle_flags and not insider_network:
        reasons.append("bundle/sniper flag: " + ", ".join(bundle_flags[:2]))

    total_holders = int(num(data.get("totalHolders")))
    if total_holders and total_holders < MIN_HOLDERS:
        reasons.append(f"only {total_holders} holders")

    creator_pct = None
    supply = num((data.get("token") or {}).get("supply"))
    if supply and data.get("creatorBalance") is not None:
        pct = num(data.get("creatorBalance")) / supply * 100
        if 0 <= pct <= 100:
            creator_pct = pct
    if creator_pct is not None and creator_pct > MAX_CREATOR_PCT:
        reasons.append(f"creator still holds {creator_pct:.0f}%")

    tf = num((data.get("transferFee") or {}).get("pct")) if isinstance(data.get("transferFee"), dict) else 0.0
    if tf > MAX_TRANSFER_FEE_PCT:
        reasons.append(f"transfer fee {tf:.0f}%")

    lp_locked, lp_seen = 0.0, False
    for m in data.get("markets") or []:
        lp = m.get("lp") or {}
        if lp:
            lp_seen = True
            lp_locked = max(lp_locked, num(lp.get("lpLockedPct")))
    if lp_seen and lp_locked < MIN_LP_LOCKED_PCT:
        reasons.append(f"only {lp_locked:.0f}% of liquidity locked/burned")

    meta = data.get("fileMeta") or {}
    desc, image = meta.get("description"), meta.get("image")
    if not desc:
        uri_meta = fetch_ipfs_json((data.get("tokenMeta") or {}).get("uri"))
        desc, image = uri_meta.get("description"), image or uri_meta.get("image")

    facts = {"mint_ren": mint_ren, "freeze_ren": freeze_ren, "lp_locked": lp_locked if lp_seen else None,
             "holders": total_holders, "top10": top10, "top1": top1, "creator_pct": creator_pct,
             "insiders": insiders, "insider_network": insider_network, "bundle_flags": bundle_flags,
             "risk_score": risk_score, "transfer_fee": tf, "warnings": warn}
    return {"ok": not reasons, "reasons": reasons, "facts": facts, "desc": desc or "", "image": image or ""}


def goplus_check(chain, addr):
    data = get_json(f"https://api.gopluslabs.io/api/v1/token_security/{GOPLUS_CHAIN[chain]}",
                    params={"contract_addresses": addr})
    res = ((data or {}).get("result") or {}).get(addr.lower())
    if not res:
        return {"ok": False, "reasons": ["GoPlus unavailable"], "facts": None, "desc": "", "image": ""}

    reasons = []
    buy, sell = num(res.get("buy_tax")) * 100, num(res.get("sell_tax")) * 100
    if res.get("is_honeypot") == "1":
        reasons.append("HONEYPOT")
    if buy > MAX_TAX_PCT or sell > MAX_TAX_PCT:
        reasons.append(f"tax {buy:.0f}%/{sell:.0f}%")
    open_source = res.get("is_open_source") != "0"
    if not open_source:
        reasons.append("unverified contract")
    for k, label in (("hidden_owner", "hidden owner"), ("can_take_back_ownership", "ownership reclaimable"),
                     ("owner_change_balance", "owner can change balances"), ("is_blacklisted", "blacklist function"),
                     ("transfer_pausable", "transfers pausable"), ("cannot_sell_all", "cannot sell all"),
                     ("is_mintable", "mintable")):
        if res.get(k) == "1":
            reasons.append(label)
    holders = int(num(res.get("holder_count")))
    if holders < MIN_HOLDERS:
        reasons.append(f"only {holders} holders")
    creator = num(res.get("creator_percent")) * 100
    if creator > MAX_CREATOR_PCT:
        reasons.append(f"creator holds {creator:.0f}%")
    top = [h for h in (res.get("holders") or [])[:10] if str(h.get("is_contract")) != "1"]
    top10 = sum(num(h.get("percent")) * 100 for h in top)
    if top10 > MAX_TOP10_HOLDER_PCT:
        reasons.append(f"top wallets hold {top10:.0f}%")
    lp_locked = sum(num(h.get("percent")) * 100 for h in (res.get("lp_holders") or []) if str(h.get("is_locked")) == "1")
    owner = (res.get("owner_address") or "").lower()
    owner_ren = owner in ("", "0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead")

    facts = {"buy_tax": buy, "sell_tax": sell, "open_source": open_source, "owner_ren": owner_ren,
             "holders": holders, "top10": top10, "creator_pct": creator, "lp_locked": lp_locked}
    return {"ok": not reasons, "reasons": reasons, "facts": facts, "desc": "", "image": ""}


def fetch_site_blurb(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        html = r.text[:110_000]
        title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        desc = re.search(r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]+content=["\'](.*?)["\']', html, re.I | re.S)
        parts = [re.sub(r"\s+", " ", x.group(1)).strip() for x in (title, desc) if x]
        return " — ".join(parts)[:280]
    except Exception:
        return ""


def site_alive(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=6, allow_redirects=True)
        return r.status_code < 400 and len(r.text) > 120
    except Exception:
        return False


def copycat_check(pair):
    chain = pair["chainId"]
    base = pair.get("baseToken") or {}
    sym = (base.get("symbol") or "").lower()
    name = (base.get("name") or "").lower()
    addr = base.get("address")
    my_liq = num((pair.get("liquidity") or {}).get("usd"))
    my_created = pair.get("pairCreatedAt") or 0
    data = get_json(f"{DEX}/latest/dex/search", params={"q": base.get("symbol") or base.get("name")})
    if data is None:
        return "couldn't verify originality" if REQUIRE_SAFETY_DATA else None
    for p in data.get("pairs", []) or []:
        b = p.get("baseToken") or {}
        if b.get("address") == addr:
            continue
        if (b.get("symbol") or "").lower() != sym and (b.get("name") or "").lower() != name:
            continue
        their_liq = num((p.get("liquidity") or {}).get("usd"))
        their_created = p.get("pairCreatedAt") or 0
        label = f"{b.get('name')} (${b.get('symbol')}) {str(b.get('address'))[:6]}…"
        if p.get("chainId") == chain:
            if their_liq > my_liq * 1.5:
                return f"copycat: bigger coin with same name exists: {label}"
            if their_created and their_created < my_created - 3_600_000 and their_liq >= MIN_LIQUIDITY_USD * 0.4:
                return f"copycat: older coin with same name exists: {label}"
        elif their_liq > 80_000 and their_created and their_created < my_created - 86_400_000:
            return f"impersonating established coin: {label}"
    return None


def read_coin(name, symbol, desc, site_blurb):
    text = " ".join([name or "", symbol or "", desc or "", site_blurb or ""]).lower()
    words = set(re.findall(r"[a-z0-9]+", text))
    labels = [label for label, kw in THEMES.items() if words & kw]
    bonus, bits = 0, []
    if labels:
        bonus += 4
        bits.append("/".join(labels) + " theme")
    else:
        bits.append("no clear theme")
    if len((desc or "").strip()) >= 30:
        bonus += 3
        bits.append("clear description")
    if site_blurb:
        bonus += 2
        bits.append("live website")
    d = (desc or "").strip()
    letters = sum(c.isalpha() for c in d)
    if len(d) > 20 and (d.count("!") > 5 or (letters and sum(c.isupper() for c in d) / letters > 0.70)):
        bonus -= 4
        bits.append("shilly wording")
    return " • ".join(bits), bonus


def build_legit(chain, f, extra):
    s = 0
    lines = []

    def item(group, label, val, got, mx):
        nonlocal s
        s += got
        lines.append(("✅" if got >= mx * 0.65 else "⚠️", label, val, group))

    if chain == "solana":
        lp = f["lp_locked"]
        item("contract", "Mint authority", "renounced" if f["mint_ren"] else "NOT renounced", 10 if f["mint_ren"] else 0, 10)
        item("contract", "Freeze authority", "renounced" if f["freeze_ren"] else "NOT renounced", 10 if f["freeze_ren"] else 0, 10)
        item("contract", "Liquidity locked/burned", "n/a" if lp is None else f"{lp:.0f}%",
             5 if lp is None else (15 if lp >= 90 else 10 if lp >= 60 else 4 if lp >= 40 else 0), 15)
        rs = f["risk_score"]
        item("contract", "RugCheck risk score", "n/a" if rs is None else f"{rs:.0f}/100 (lower is safer)",
             5 if rs is None else (10 if rs <= 12 else 7 if rs <= 25 else 2 if rs <= 35 else 0), 10)
        lines.append(("✅" if f["transfer_fee"] <= 1 else "⚠️", "Transfer fee", f"{f['transfer_fee']:.0f}%", "contract"))
        h = f["holders"]
        item("holders", "Holders", str(h), 10 if h >= 350 else 7 if h >= 120 else 4 if h >= 70 else 0, 10)
        t10 = f["top10"]
        item("holders", "Top 10 wallets", f"{t10:.0f}% (largest {f['top1']:.0f}%)",
             10 if t10 <= 28 else 7 if t10 <= 36 else 3 if t10 <= 46 else 0, 10)
        cp = f["creator_pct"]
        item("holders", "Creator holding", "n/a" if cp is None else f"{cp:.1f}%",
             5 if cp is None else (10 if cp <= 3 else 6 if cp <= 6 else 2 if cp <= 10 else 0), 10)
        ins = f["insiders"] + (1 if f["insider_network"] else 0) + len(f.get("bundle_flags") or [])
        item("holders", "Insiders / bundles", "none detected" if ins == 0 else f"{ins} flagged",
             10 if ins == 0 else 4 if ins == 1 else 0, 10)
        if f.get("warnings"):
            lines.append(("⚠️", "RugCheck warnings", ", ".join(f["warnings"][:3]), "contract"))
    else:
        tax = max(f["buy_tax"], f["sell_tax"])
        item("contract", "Honeypot test", "passed (can sell)", 15, 15)
        item("contract", "Buy / sell tax", f"{f['buy_tax']:.0f}% / {f['sell_tax']:.0f}%",
             10 if tax <= 3 else 5 if tax <= 7 else 0, 10)
        item("contract", "Contract source", "verified" if f["open_source"] else "unverified", 10 if f["open_source"] else 0, 10)
        item("contract", "Ownership", "renounced" if f["owner_ren"] else "owner active", 10 if f["owner_ren"] else 3, 10)
        item("contract", "Dangerous functions", "none (mint / blacklist / pause / hidden owner)", 10, 10)
        lp = f["lp_locked"]
        item("contract", "Liquidity locked", f"{lp:.0f}%", 5 if lp >= 55 else 2 if lp >= 25 else 0, 5)
        h = f["holders"]
        item("holders", "Holders", str(h), 10 if h >= 350 else 7 if h >= 120 else 4 if h >= 70 else 0, 10)
        t10 = f["top10"]
        item("holders", "Top wallets (excl. contracts)", f"{t10:.0f}%",
             10 if t10 <= 28 else 7 if t10 <= 36 else 3 if t10 <= 46 else 0, 10)
        cp = f["creator_pct"]
        item("holders", "Creator holding", f"{cp:.1f}%", 5 if cp <= 3 else 3 if cp <= 6 else 1 if cp <= 10 else 0, 5)

    item("project", "Website", "live" if extra["site_ok"] else ("present" if extra.get("has_site") else "none"),
         3 if extra["site_ok"] else (1 if extra.get("has_site") else 0), 3)
    item("project", "Social accounts", str(extra["socials"]), 4 if extra["socials"] >= 1 else 0, 4)
    item("project", "Description", "clear" if extra["desc_ok"] else "thin / meme", 4 if extra["desc_ok"] else 2, 4)
    item("project", "Copycat check", "original", 5, 5)
    return s, lines


def deep_check(pair, d):
    chain = pair["chainId"]
    base = pair.get("baseToken") or {}
    addr = base.get("address")
    key = f"{chain}:{addr}"

    safety = rugcheck_solana(addr) if chain == "solana" else goplus_check(chain, addr)
    if not safety["ok"] or not safety["facts"]:
        if "unavailable" in (safety.get("reasons") or [""])[0].lower():
            print(f"  ⚠ safety data unavailable for {base.get('symbol')}, skipping this cycle")
            return False, "safety data temporarily unavailable", None
        return False, "; ".join(safety["reasons"]) or "no safety data", None

    mcap = d.get("mcap") or 0
    facts = safety["facts"]
    if mcap < 22_000:
        if facts.get("creator_pct") is not None and facts["creator_pct"] > 6:
            return False, f"low-MC creator still holds {facts['creator_pct']:.0f}%", None
        if facts.get("top10") and facts["top10"] > 40:
            return False, f"low-MC top10 holds {facts['top10']:.0f}%", None
        if facts.get("insider_network"):
            return False, "low-MC + insider network", None
        if facts.get("holders") and facts["holders"] < 85:
            return False, f"low-MC only {facts['holders']} holders", None

    fake = copycat_check(pair)
    if fake:
        return False, fake, None

    info = pair.get("info") or {}
    sites = [w.get("url") for w in info.get("websites") or [] if w.get("url")]
    socials = [s.get("url") for s in info.get("socials") or [] if s.get("url")]

    if len(sites) + len(socials) < MIN_SOCIAL_LINKS:
        return False, "no website/socials (can't verify it's real)", None

    site_ok = bool(sites) and site_alive(sites[0])
    if REQUIRE_LIVE_SITE and sites and not site_ok:
        return False, "website doesn't load", None

    desc = (profile_desc.get(key) or safety.get("desc") or "").strip()
    site_blurb = fetch_site_blurb(sites[0]) if sites and len(desc) < MIN_DESC_LEN + 12 else ""
    context = " ".join([base.get("name", ""), base.get("symbol", ""), desc, site_blurb])
    hit = RED_RE.findall(context)
    if hit:
        return False, "scammy wording: " + ", ".join(sorted(set(h.lower() for h in hit))[:3]), None
    about_len = max(len(desc), len(site_blurb))
    if REQUIRE_NARRATIVE and about_len < MIN_DESC_LEN:
        return False, "can't tell what the coin is about", None

    narr, bonus = read_coin(base.get("name"), base.get("symbol"), desc, site_blurb)
    legit, lines = build_legit(chain, safety["facts"], {
        "site_ok": site_ok, "has_site": bool(sites),
        "socials": len(socials), "desc_ok": about_len >= MIN_DESC_LEN
    })
    if legit < MIN_LEGIT_SCORE:
        return False, f"legit score {legit} below {MIN_LEGIT_SCORE}", None

    image = info.get("imageUrl") or safety.get("image") or ""
    return True, "ok", {
        "legit": legit, "lines": lines, "desc": desc, "site_blurb": site_blurb,
        "narr": narr, "bonus": bonus, "image": image, "sites": sites, "socials": socials
    }


# ======================================================
# 4) DISCORD
# ======================================================
def tier(score):
    if score >= 85: return "🔱 S-TIER"
    if score >= 75: return "🥇 A-TIER"
    return "🥈 B-TIER"


def risk_label(legit):
    if legit >= 86: return "VERY LOW RISK"
    if legit >= 76: return "LOW RISK"
    return "MODERATE RISK"


def trade_links(pair):
    chain = pair["chainId"]
    addr = (pair.get("baseToken") or {}).get("address")
    pa = pair.get("pairAddress") or addr
    links = [f"[DexScreener]({pair.get('url')})"]
    if chain == "solana":
        links += [
            f"[Axiom](https://axiom.trade/meme/{pa})",
            f"[Photon](https://photon-sol.tinyastro.io/en/lp/{pa})",
            f"[BullX](https://neo.bullx.io/terminal?chainId=1399811149&address={addr})",
            f"[Pump.fun](https://pump.fun/coin/{addr})",
            f"[Birdeye](https://birdeye.so/token/{addr}?chain=solana)",
            f"[RugCheck](https://rugcheck.xyz/tokens/{addr})",
        ]
    else:
        links.append(f"[Birdeye](https://birdeye.so/token/{addr}?chain={chain})")
    links.append(f"[GMGN](https://gmgn.ai/{GMGN_CHAIN[chain]}/token/{addr})")
    return " • ".join(links)


def official_links(pair, deep):
    links = [f"[Website]({u})" for u in deep["sites"][:1]]
    for s in (pair.get("info") or {}).get("socials") or []:
        if s.get("url"):
            links.append(f"[{str(s.get('type', 'link')).title()}]({s['url']})")
    return " • ".join(links[:5])


def build_embed(pair, score, d, deep):
    base = pair.get("baseToken") or {}
    chain = pair.get("chainId", "?")
    addr = base.get("address", "?")
    price = num(pair.get("priceUsd"))
    about = deep["desc"] or deep["site_blurb"] or "Meme / community coin — no long description"

    stats = (
        "```\n"
        f"PRICE     ${price:.8g}\n"
        f"MCAP      {fmt_usd(d['mcap']):<9} LIQ   {fmt_usd(d['liq'])}\n"
        f"VOLUME    {fmt_usd(d['vol24']):<9} AGE   {fmt_age(d['age_min'])}\n"
        f"1H        {d['ch1']:+.0f}%{'':<6} 6H    {d['ch6']:+.0f}%\n"
        f"BUY/SELL  {d['ratio1']:.2f}x (1h)  {d['ratio5']:.2f}x (5m)\n"
        "```"
    )
    head = (f"**{base.get('name', '?')}** (${base.get('symbol', '?')})\n"
            f"```{addr}```"
            "*Hold to copy • paste into Fomo, Axiom or Photon search*\n\n")
    desc = (head + f"{tier(score)}  •  {CHAIN_ICON.get(chain, '•')} **{chain.upper()}**  •  `{pair.get('dexId', '?')}`\n"
            f"`{score_bar(score)}`  📈 **BULLISH {score}/100**\n"
            f"`{score_bar(deep['legit'])}`  🛡️ **LEGIT {deep['legit']}/100** • {risk_label(deep['legit'])}\n{stats}")

    short = "\n".join(f"{i} {label}: {val}" for i, label, val, _ in deep["lines"][:7])
    fields = [
        {"name": "📝 What it's about", "value": trunc(about, 600), "inline": False},
        {"name": "🧭 Narrative", "value": trunc(deep["narr"], 250), "inline": False},
        {"name": "🛡️ Legit check (full report in Legit Checker channel)", "value": trunc(short, 900), "inline": False},
        {"name": "⚡ Quick trade", "value": trunc(trade_links(pair), 1000), "inline": False},
    ]
    links = official_links(pair, deep)
    if links:
        fields.append({"name": "🌐 Official", "value": links, "inline": False})
    fields.append({
        "name": "🎯 Plan (not advice)",
        "value": (f"Entry ref `${price:.8g}` • Invalidation −30% `${price*0.7:.8g}`\n"
                  f"Seen on {d['nsrc']} source(s). Size small, take profit in stages.\n"
                  f"📊 Bot track record: {stats_line()}\n"
                  f"👁️ Watched every {WATCH_EVERY}s: EXIT and take-profit alerts follow."),
        "inline": False
    })
    embed = {
        "author": {"name": f"{BOT_NAME}  •  🔥 LIVE CALL"},
        "title": f"{base.get('name', '?')}  (${base.get('symbol', '?')})",
        "url": pair.get("url"),
        "description": desc,
        "color": 0x00FF99 if score >= 85 else (0x2ECC71 if score >= 75 else 0x3498DB),
        "fields": fields,
        "footer": {"text": FOOTER + " • Nothing is guaranteed • DYOR"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if deep["image"]:
        embed["thumbnail"] = {"url": deep["image"]}
    header = (pair.get("info") or {}).get("header")
    if header:
        embed["image"] = {"url": header}
    return embed


def build_legit_embed(pair, score, d, deep):
    base = pair.get("baseToken") or {}
    chain = pair.get("chainId", "?")
    addr = base.get("address", "?")
    groups = {"contract": [], "holders": [], "project": []}
    for icon, label, val, grp in deep["lines"]:
        groups[grp].append(f"{icon} **{label}:** {val}")
    market = [
        f"✅ **Bullish score:** {score}/100 ({tier(score)})",
        f"✅ **Buy/sell pressure:** {d['ratio1']:.2f}x (1h) • {d['ratio5']:.2f}x (5m)",
        f"✅ **Liquidity:** {fmt_usd(d['liq'])} ({d['liq'] / max(d['mcap'], 1) * 100:.0f}% of mcap)",
        f"✅ **Volume:** {fmt_usd(d['vol24'])} • {d['txns']:.0f} txns",
        f"✅ **Age:** {fmt_age(d['age_min'])}",
        f"✅ **Live watch:** stayed healthy for {CONFIRM_SECONDS}s at 2s checks",
    ]
    fields = [
        {"name": "🔐 Contract & liquidity", "value": trunc("\n".join(groups["contract"]), 1000), "inline": False},
        {"name": "👥 Holders & bundles", "value": trunc("\n".join(groups["holders"]), 1000), "inline": False},
        {"name": "🧾 Project", "value": trunc("\n".join(groups["project"]) + f"\n🧭 {deep['narr']}", 1000), "inline": False},
        {"name": "📈 Market health", "value": trunc("\n".join(market), 1000), "inline": False},
        {"name": "⚡ Quick trade", "value": trunc(trade_links(pair), 1000), "inline": False},
    ]
    embed = {
        "author": {"name": f"{BOT_NAME}  •  🛡️ LEGIT CHECKER"},
        "title": f"PASSED: {base.get('name', '?')}  (${base.get('symbol', '?')})",
        "url": pair.get("url"),
        "description": (f"```{addr}```"
                        f"`{score_bar(deep['legit'])}`  🛡️ **LEGIT SCORE {deep['legit']}/100** • {risk_label(deep['legit'])}\n"
                        f"{CHAIN_ICON.get(chain, '•')} **{chain.upper()}** • `{pair.get('dexId', '?')}`\n"
                        "*No coin is risk-free. This is a health check, not a guarantee.*"),
        "color": 0x3498DB,
        "fields": fields,
        "footer": {"text": FOOTER},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if deep["image"]:
        embed["thumbnail"] = {"url": deep["image"]}
    return embed


def send_embeds(embeds, content=None, channel="callouts"):
    url = WEBHOOKS.get(channel) or WEBHOOK_URL
    ok = True
    for e in embeds:
        payload = {"username": BOT_NAME, "embeds": [e]}
        if content:
            payload["content"] = content
            content = None
        try:
            r = requests.post(url, json=payload, timeout=14)
            if r.status_code == 429:
                time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
                r = requests.post(url, json=payload, timeout=14)
            if r.status_code in (200, 204):
                print(f"Message sent ({channel})")
            else:
                ok = False
                print(f"Discord error {r.status_code} ({channel}): {r.text[:180]}")
        except Exception as ex:
            ok = False
            print(f"Discord send error ({channel}): {ex}")
        time.sleep(0.38)
    return ok


def send_startup():
    send_embeds([{
        "author": {"name": BOT_NAME},
        "title": "🟢  SYSTEM ONLINE  •  v" + VERSION,
        "description": (
            "```\n"
            "NETWORKS   Solana • Base • Ethereum • BSC\n"
            f"WINDOW     {MIN_PAIR_AGE_MIN}-{MAX_PAIR_AGE_MIN} min old coins\n"
            f"MAX MC     ${MAX_MARKET_CAP:,} hard ceiling\n"
            f"SCAN       every {CHECK_INTERVAL}s\n"
            f"MIN SCORE  Bullish ≥{MIN_SCORE}  •  Legit ≥{MIN_LEGIT_SCORE}\n"
            "MODE       Early Hunter + Reputation\n"
            "```"
        ),
        "color": 0x00FF99,
        "fields": [
            {"name": "🔍 Detection", "value": "More Solana discovery pages + faster cycle. Focused on the real early zone (5k–40k).", "inline": False},
            {"name": "🛡️ Safety + Timing", "value": "Hard $85k MC ceiling • Rejects already-pumped coins • Strong preference for under 40 min • High legit standards", "inline": False},
            {"name": "📊 Accountability", "value": "Every call tracked. Results posted 15m / 1h / 6h / 24h.", "inline": False},
            {"name": "🧪 Debug channel", "value": "Near-misses + scan stats so you can see the bot working.", "inline": False},
        ],
        "footer": {"text": FOOTER + " • only early + clean coins reach callouts"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }])


CHANGELOG = [
    ("🎯 v4.1 Early Hunter", "More aggressive discovery (9 Solana Gecko pages + faster cycle). Hard MC ceiling $85k. Strong preference for under 40 min + under $35k. Still rejects late/extended coins hard."),
    ("🛡️ Reputation protected", "DacityCat-style late calls blocked. Critical rug flags, concentration, creator, and social requirements kept high."),
    ("📈 Still aims for big runners", "Age + low-MC bonuses heavily reward the true 5k–30k zone that can realistically go much higher."),
]


def post_updates_if_new():
    try:
        with open(VERSION_FILE) as f:
            if f.read().strip() == VERSION:
                return
    except Exception:
        pass
    fields = [{"name": n, "value": trunc(v, 1000), "inline": False} for n, v in CHANGELOG]
    ok = send_embeds([{
        "author": {"name": BOT_NAME},
        "title": f"🆕  UPDATE v{VERSION}",
        "description": "Key changes in this release:",
        "color": 0x9B59B6,
        "fields": fields,
        "footer": {"text": FOOTER},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }], channel="updates")
    if ok:
        try:
            with open(VERSION_FILE, "w") as f:
                f.write(VERSION)
        except Exception:
            pass


# ======================================================
# 5) LIVE MONITOR, EXIT / TP & RESULTS
# ======================================================
def stats_line():
    s = state["stats"]
    if not s["n"]:
        return "No finished calls yet."
    return (f"Record: {s['wins']}/{s['n']} positive ({s['wins']/s['n']*100:.0f}%) • "
            f"avg {s['sum']/s['n']:+.0f}% • {s['x2']} hit 2x+")


def label_h(h):
    return f"{int(round(h * 60))}m" if h < 1 else f"{h:g}h"


def finalize(key, change):
    t = state["tracked"].pop(key, None)
    if not t:
        return
    s = state["stats"]
    s["n"] += 1
    s["sum"] += change
    s["wins"] += 1 if change > 0 else 0
    s["x2"] += 1 if change >= 100 else 0


def live_embed(t, title, body, color, tag):
    return {
        "author": {"name": f"{BOT_NAME}  •  {tag}"},
        "title": title,
        "description": f"**{t['name']}** (${t['symbol']})\n```{t['addr']}```{body}",
        "color": color,
        "footer": {"text": FOOTER},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def fire_call(key, pair, final, d, deep):
    now = time.time()
    base = pair.get("baseToken") or {}
    sym = base.get("symbol")
    chain = pair.get("chainId")
    addr = base.get("address")

    fresh_pairs = fetch_pairs([(chain, addr)], pause=0)
    fresh = fresh_pairs.get(key) or pair
    ev = evaluate(fresh, d.get("nsrc", 1))
    if ev:
        final = min(100, ev[0] + deep.get("bonus", 0))
        d = ev[1]
        pair = fresh
        base = pair.get("baseToken") or {}
        sym = base.get("symbol") or sym

    if d.get("mcap", 0) > MAX_MARKET_CAP:
        print(f"  ✗ {sym}: MC moved above hard ceiling ${MAX_MARKET_CAP:,} — aborting call")
        state["rejected"][key] = now
        return

    print(f"  ✓ {sym}: confirmed live + FRESH data, sending call (bullish {final}, legit {deep['legit']}, mcap {fmt_usd(d['mcap'])})")
    state["alerted"][key] = now
    state["alerts"] += 1
    price = num(pair.get("priceUsd"))
    state["tracked"][key] = {
        "symbol": sym, "name": base.get("name"), "chain": pair["chainId"],
        "addr": base.get("address"), "price": price, "liq0": d["liq"],
        "peak": price, "tp": [], "ts": now, "reported": []
    }
    send_embeds([build_embed(pair, final, d, deep)],
                content=f"🚨 **{base.get('name')}** (${sym})  `{base.get('address')}`", channel="callouts")
    send_embeds([build_legit_embed(pair, final, d, deep)], channel="legit")


def check_pending(key, live, now):
    pend = state["pending"].get(key)
    if not pend:
        return
    sym = (pend["pair"].get("baseToken") or {}).get("symbol")
    if now - pend["t0"] > CONFIRM_SECONDS * 5:
        state["pending"].pop(key, None)
        return
    if not live:
        return
    liq = num((live.get("liquidity") or {}).get("usd"))
    price = num(live.get("priceUsd"))
    if (pend["liq0"] and liq < pend["liq0"] * (1 - CONFIRM_MAX_LIQ_DROP)) or \
       (pend["price0"] and price < pend["price0"] * (1 - CONFIRM_MAX_PRICE_DROP)):
        state["pending"].pop(key, None)
        state["rejected"][key] = now
        print(f"  ✗ {sym}: failed live confirmation (liq/price dropping)")
        return
    min_wait = 2.2 if pend.get("deep", {}).get("legit", 0) >= 78 and pend.get("final_est", 70) >= 74 else CONFIRM_SECONDS
    if now - pend["t0"] < min_wait:
        return
    state["pending"].pop(key, None)
    ev = evaluate(live, pend["nsrc"])
    if not ev:
        state["rejected"][key] = now
        print(f"  ✗ {sym}: no longer passes market rules after confirmation")
        return
    final = min(100, ev[0] + pend["deep"]["bonus"])
    if final < MIN_SCORE:
        state["rejected"][key] = now
        print(f"  ✗ {sym}: final score {final} below {MIN_SCORE} after confirmation")
        return
    fire_call(key, live, final, ev[1], pend["deep"])


def check_called(key, t, live):
    if not live or not t.get("price"):
        return
    entry = t["price"]
    price = num(live.get("priceUsd"))
    liq = num((live.get("liquidity") or {}).get("usd"))
    t["peak"] = max(t.get("peak", entry), price)
    if t.get("exit_sent"):
        return
    change = (price / entry - 1) * 100
    liq_drop = (1 - liq / t["liq0"]) if t.get("liq0") else 0
    rugged = liq < 1100 or liq_drop >= 0.58

    if rugged or liq_drop >= EXIT_LIQ_DROP or price <= entry * (1 - EXIT_PRICE_DROP):
        t["exit_sent"] = True
        why = "LIQUIDITY BEING PULLED" if (rugged or liq_drop >= EXIT_LIQ_DROP) else f"PRICE DOWN {abs(change):.0f}% FROM ENTRY"
        send_embeds([live_embed(
            t, f"🚨 EXIT NOW: {t['name']} (${t['symbol']})",
            f"**{why}**\n```\nENTRY  ${entry:.8g}\nNOW    ${price:.8g}  ({change:+.0f}%)\n"
            f"LIQ    {fmt_usd(liq)}  ({-liq_drop * 100:+.0f}% vs call)\n```",
            0xE74C3C, "🚨 EXIT ALERT")],
            content=f"🚨 **EXIT: {t['name']}** (${t['symbol']})  `{t['addr']}`", channel="exit")
        if rugged:
            finalize(key, -100.0)
        return

    for x in TAKE_PROFIT_X:
        if price >= entry * x and x not in t.setdefault("tp", []):
            t["tp"].append(x)
            send_embeds([live_embed(
                t, f"💰 TAKE PROFIT: {t['name']} is {x}x",
                f"```\nENTRY  ${entry:.8g}\nNOW    ${price:.8g}  ({change:+.0f}%)\n```"
                "Consider selling part (e.g. your initial) and letting the rest ride.",
                0xF1C40F, "💰 TAKE PROFIT")],
                content=f"💰 **{x}x: {t['name']}** (${t['symbol']})  `{t['addr']}`", channel="profit")

    peak_gain = (t["peak"] / entry - 1) * 100
    if peak_gain >= 16 and not t.get("pullback_sent") and price <= t["peak"] * (1 - PEAK_PULLBACK):
        t["pullback_sent"] = True
        send_embeds([live_embed(
            t, f"⚠️ PULLBACK: {t['name']} is down {PEAK_PULLBACK * 100:.0f}% from its peak",
            f"```\nPEAK   ${t['peak']:.8g}  ({peak_gain:+.0f}% vs entry)\nNOW    ${price:.8g}  ({change:+.0f}%)\n```"
            "Momentum fading. Consider securing profit.",
            0xE67E22, "⚠️ PULLBACK")], channel="profit")


def monitor_once():
    now = time.time()
    watch = {}
    for key, pend in list(state["pending"].items()):
        watch[key] = (pend["chain"], pend["addr"])
    for key, t in list(state["tracked"].items()):
        if now - t["ts"] <= MONITOR_HOURS * 3600:
            watch[key] = (t["chain"], t["addr"])
    if not watch:
        return
    live = fetch_pairs(watch.values(), pause=0)
    for key in list(state["pending"].keys()):
        check_pending(key, live.get(key), now)
    for key, t in list(state["tracked"].items()):
        if key in watch:
            check_called(key, t, live.get(key))


def monitor_loop():
    while True:
        try:
            monitor_once()
        except Exception as e:
            print(f"Monitor error: {e}")
        time.sleep(WATCH_EVERY)


def track_results():
    now = time.time()
    due = []
    for key, t in list(state["tracked"].items()):
        for h in CHECKPOINTS_H:
            if h not in t["reported"] and now - t["ts"] >= h * 3600:
                due.append((key, t, h))
                break
        if now - t["ts"] > 72 * 3600:
            state["tracked"].pop(key, None)
    if not due:
        return
    pairs = fetch_pairs({(t["chain"], t["addr"]) for _, t, _ in due})
    for key, t, h in due:
        p = pairs.get(key)
        if not p:
            continue
        price = num(p.get("priceUsd"))
        liq = num((p.get("liquidity") or {}).get("usd"))
        pulled = liq < 1100
        change = -100.0 if pulled else ((price / t["price"] - 1) * 100 if t["price"] else 0)
        t["reported"].append(h)
        if h == CHECKPOINTS_H[-1] or pulled:
            finalize(key, change)
        if not SEND_RESULT_UPDATES:
            continue
        icon = "🟢" if change > 0 else "🔴"
        send_embeds([{
            "author": {"name": f"{BOT_NAME}  •  📊 RESULT"},
            "title": f"{icon} {t['name']} (${t['symbol']}): {change:+.0f}% after {label_h(h)}"
                     + ("  ⚠️ LIQUIDITY PULLED" if pulled else ""),
            "description": ("```\n"
                            f"ALERT PRICE  ${t['price']:.8g}\n"
                            f"NOW          ${price:.8g}\n"
                            f"CHANGE       {change:+.1f}%\n"
                            "```"
                            f"`{t['addr']}`\n\n{stats_line()}"),
            "color": 0x2ECC71 if change > 0 else 0xE74C3C,
            "footer": {"text": FOOTER},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }], channel="results")


# ======================================================
# 6) MAIN SCAN + REJECTED REPORTING
# ======================================================
def post_scan_report(candidates, passed_market, deep_checked, rejects, queued):
    now = time.time()
    if now - state.get("last_reject_post", 0) < 65:
        return
    state["last_reject_post"] = now

    reason_counts = Counter()
    near = []
    for r in rejects:
        reason_counts[r["reason"].split(":")[0][:40]] += 1
        if r.get("bullish", 0) >= MIN_SCORE - 6:
            near.append(r)

    lines = [
        f"**Scan #{state['scans']}** • {datetime.now(timezone.utc).strftime('%H:%M UTC')}",
        f"Candidates: **{len(candidates)}** → Market pass: **{passed_market}** → Deep checked: **{deep_checked}**",
        f"Queued for live confirm: **{queued}** • Currently tracking: **{len(state['tracked'])}** • Pending: **{len(state['pending'])}**",
        f"Total calls so far: **{state['alerts']}**",
    ]
    if reason_counts:
        top_reasons = ", ".join(f"{k} ({v})" for k, v in reason_counts.most_common(5))
        lines.append(f"Top reject reasons: {top_reasons}")

    fields = [{"name": "📊 Activity", "value": "\n".join(lines), "inline": False}]

    near = sorted(near, key=lambda x: -x.get("bullish", 0))[:5]
    if near:
        miss_lines = []
        for m in near:
            miss_lines.append(
                f"**{m['sym']}** ({m['chain']}) • bullish {m['bullish']} • {fmt_usd(m.get('mcap', 0))} • "
                f"{fmt_age(m.get('age'))} → `{trunc(m['reason'], 80)}`"
            )
        fields.append({"name": "🟡 Near-misses (high momentum, failed safety)", "value": trunc("\n".join(miss_lines), 1000), "inline": False})
    else:
        fields.append({"name": "🟡 Near-misses", "value": "None this round (or all low score)", "inline": False})

    fields.append({
        "name": "ℹ️ Note",
        "value": "Only coins that pass **early timing + high safety** reach #callouts.",
        "inline": False
    })

    send_embeds([{
        "author": {"name": f"{BOT_NAME}  •  🧪 SCAN REPORT"},
        "title": f"Scan finished — {queued} coin(s) entering live confirmation" if queued else "Scan finished — nothing queued this round",
        "description": "Bot is alive and hunting early quality coins.",
        "color": 0xF39C12 if queued else 0x95A5A6,
        "fields": fields,
        "footer": {"text": FOOTER},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }], channel="rejected")


def check_for_tokens():
    state["scans"] += 1
    sources = [from_dexscreener_lists(), from_geckoterminal(), from_dexscreener_search()]
    candidates = set().union(*sources)
    nsrc = {c: sum(1 for s in sources if c in s) for c in candidates}
    print(f"  {len(candidates)} candidate tokens")
    pairs = fetch_pairs(candidates)
    print(f"  {len(pairs)} pairs fetched")

    now = time.time()
    for k in [k for k, v in list(state["rejected"].items()) if now - v > 2 * 86400]:
        state["rejected"].pop(k, None)

    results = []
    for key, pair in pairs.items():
        if key in state["pending"] or now - state["alerted"].get(key, 0) < REALERT_AFTER:
            continue
        if now - state["rejected"].get(key, 0) < RECHECK_REJECTED_AFTER:
            continue
        chain, addr = key.split(":", 1)
        ev = evaluate(pair, nsrc.get((chain, addr), 1))
        if ev and ev[0] >= MIN_SCORE - 10:
            results.append((ev[0], key, pair, ev[1]))
    results.sort(key=lambda x: x[0], reverse=True)
    print(f"  {len(results)} passed market filters (score ≥ ~{MIN_SCORE-10})")

    rejects = []
    queued, checked = 0, 0
    for score, key, pair, d in results:
        if checked >= MAX_DEEP_CHECKS_PER_SCAN:
            break
        checked += 1
        ok, reason, deep = deep_check(pair, d)
        base = pair.get("baseToken") or {}
        sym = base.get("symbol") or "?"
        final = score
        if ok:
            final = min(100, score + deep["bonus"])
            if final < MIN_SCORE:
                ok, reason = False, f"final score {final} below {MIN_SCORE}"
        if not ok:
            state["rejected"][key] = now
            print(f"  ✗ {sym}: {reason}")
            rejects.append({
                "sym": sym, "chain": pair.get("chainId"), "bullish": score,
                "mcap": d.get("mcap"), "age": d.get("age_min"), "reason": reason
            })
            continue
        print(f"  … {sym}: passed all checks (legit {deep['legit']}), confirming live for {CONFIRM_SECONDS}s")
        state["pending"][key] = {
            "chain": pair["chainId"], "addr": base.get("address"), "pair": pair,
            "deep": deep, "nsrc": d["nsrc"], "t0": now, "liq0": d["liq"],
            "price0": num(pair.get("priceUsd")),
            "final_est": min(100, score + deep.get("bonus", 0))
        }
        queued += 1

    if not queued:
        print("  nothing passed all checks this round")

    post_scan_report(candidates, len(results), checked, rejects, queued)


def status_if_due():
    if not SEND_STATUS:
        return
    now = time.time()
    if now - state["last_status"] >= STATUS_EVERY:
        state["last_status"] = now
        send_embeds([{
            "author": {"name": BOT_NAME},
            "title": "✅  SCANNER RUNNING",
            "description": (
                "```\n"
                f"SCANS     {state['scans']}\n"
                f"CALLS     {state['alerts']}\n"
                f"TRACKING  {len(state['tracked'])}\n"
                f"PENDING   {len(state['pending'])}\n"
                "```" + stats_line()
            ),
            "color": 0x95A5A6,
            "footer": {"text": FOOTER},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }], channel="rejected")


if __name__ == "__main__":
    print(f"Memecoin webhook bot v{VERSION} started...")
    send_startup()
    post_updates_if_new()
    state["last_status"] = time.time()
    threading.Thread(target=monitor_loop, daemon=True).start()
    while True:
        print(f"[{datetime.now()}] Checking...")
        try:
            track_results()
            check_for_tokens()
            status_if_due()
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(CHECK_INTERVAL)

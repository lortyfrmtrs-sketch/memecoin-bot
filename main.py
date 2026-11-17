import os
import re
import json
import time
import threading
import requests
from datetime import datetime, timezone

# ======================================================
# CONFIGURATION
# ======================================================
BOT_NAME = "Valk's Insider Bot"
CREDIT = "Created by @valk_ on Fomo"
VERSION = "3.0.0"                # bump this when you add something new, it posts to the Updates channel

# ---- Discord webhooks (keep this file PRIVATE: anyone holding these URLs can post in your channels) ----
WEBHOOK_URL = "https://discord.com/api/webhooks/1571990911737405582/gk8RqKJdRWjOSahlwoJ1jwgLeGTycEsYipFkYJaidcvUb2mgtv8uGPjBNM888r49wfqp"
WEBHOOKS = {
    "callouts": WEBHOOK_URL,   # original callouts, results, startup
    "legit":    "https://discord.com/api/webhooks/1572179140071788584/VkNt0IGCHgf4n5VQIcZpVdkV2SVbSyL-kQiqhW-9LUP0_EZoyOIJPLEbb7zGdGv4ByQn",
    "exit":     "https://discord.com/api/webhooks/1572181849743163534/EOfiZofRjTm7tMfB_c6dSqAZX33Q25aCNVuFwzzyoi-mOXsrDalgM3G0g7SgvoaOjyYC",
    "profit":   "https://discord.com/api/webhooks/1572181743602241628/hyY_K931H6dEC8NTd5N5yIuy8ulXok3P9WDXzSVAhsPvozGCILgVSl8_8CoUoCTOWVaq",
    "updates":  "https://discord.com/api/webhooks/1572187465547255898/zl1XiPtRaCXFylwk84rqllawjUsRTngaY4wFh6Y2uRYsBh1y6cbmwdOIILvTOwnLfCYO",
}

CHECK_INTERVAL = 60              # seconds between scans
REALERT_AFTER = 12 * 3600        # never repeat the same coin within 12 hours
RECHECK_REJECTED_AFTER = 1800    # re-check a rejected coin after 30 minutes
MAX_DEEP_CHECKS_PER_SCAN = 20    # how many top candidates get the full health check per scan
STATUS_EVERY = 6 * 3600
SEND_STATUS = False              # periodic "scanner running" message (off = only calls)
SEND_RESULT_UPDATES = True       # follow-up results on past calls (15m / 1h / 6h / 24h)
VERSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bot_version")

# ---- Bullish filters (market) ----
MIN_PAIR_AGE_MIN = 45            # skip the riskiest first 45 minutes (most rugs happen early)
MAX_PAIR_AGE_MIN = 240           # skip anything older than 4 hours (too late)
MIN_LIQUIDITY_USD = 15_000
MIN_VOLUME_24H = 25_000
MIN_MARKET_CAP = 40_000
MAX_MARKET_CAP = 5_000_000
MIN_TXNS_24H = 250
MIN_LIQ_TO_MCAP = 0.06
MIN_BUY_SELL_RATIO_H1 = 1.2
MAX_24H_PUMP_PCT = 800           # already ran too hard = too late
MAX_VOL_TO_LIQ = 40              # volume / liquidity above this looks like wash trading
MIN_SCORE = 75                   # final bullish score (0-100) needed to be called

# ---- Legit filters (health check) ----
MIN_LEGIT_SCORE = 75             # final legit score (0-100) needed to be called
MAX_RUGCHECK_SCORE = 40          # Solana: reject above this RugCheck risk score
MAX_TOP10_HOLDER_PCT = 50
MIN_HOLDERS = 100
MAX_INSIDERS_TOP10 = 1           # max insider / linked wallets among the top 10
MAX_CREATOR_PCT = 10             # max % of supply the creator may still hold
MAX_TRANSFER_FEE_PCT = 5
MIN_LP_LOCKED_PCT = 50           # Solana: liquidity must be locked / burned
MAX_TAX_PCT = 10                 # EVM: max buy/sell tax
MIN_SOCIAL_LINKS = 2
REQUIRE_WEBSITE_AND_SOCIAL = True
REQUIRE_LIVE_SITE = True
REQUIRE_NARRATIVE = True
MIN_DESC_LEN = 30                # the bot must be able to read what the coin is about
REQUIRE_SAFETY_DATA = True       # if a checker can't answer, skip the coin

# ---- Live monitor (every 2 seconds) ----
WATCH_EVERY = 2
CONFIRM_SECONDS = 90             # a coin must stay healthy this long under the live watch before it's called
CONFIRM_MAX_LIQ_DROP = 0.10
CONFIRM_MAX_PRICE_DROP = 0.10
MONITOR_HOURS = 6                # keep watching each called coin every 2s for this long
EXIT_LIQ_DROP = 0.25             # EXIT alert if liquidity falls 25% from the call
EXIT_PRICE_DROP = 0.30           # EXIT alert if price is 30% below the entry
PEAK_PULLBACK = 0.20             # warn if price falls 20% from its peak after the call
TAKE_PROFIT_X = (2, 3, 5, 10)
CHECKPOINTS_H = (0.25, 1, 6, 24)

CHAINS = {"solana", "base", "ethereum", "bsc"}
GECKO_NETWORKS = {"solana": "solana", "base": "base", "eth": "ethereum", "bsc": "bsc"}
GECKO_NEW_PAGES = {"solana": 5, "base": 2, "eth": 2, "bsc": 2}
GOPLUS_CHAIN = {"ethereum": "1", "bsc": "56", "base": "8453"}
GMGN_CHAIN = {"solana": "sol", "base": "base", "ethereum": "eth", "bsc": "bsc"}
CHAIN_ICON = {"solana": "◎", "base": "🔵", "ethereum": "⟠", "bsc": "🟡"}
SEARCH_TERMS = ("pump", "pumpfun", "meme", "pepe", "dog", "cat", "ai agent", "trump", "bonk", "frog",
                "moon", "inu", "elon", "wojak", "chad", "baby", "king", "cult", "goat", "sol")

RED_WORDS = [
    "guaranteed", "risk free", "risk-free", "no risk", "can't lose", "cant lose", "presale",
    "claim airdrop", "connect wallet", "send sol", "send eth", "double your", "ponzi",
    "pump and dump", "rug", "rugpull", "rug pull", "honeypot", "100x guaranteed", "free money",
]
RED_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in RED_WORDS) + r")\b", re.I)

THEMES = {
    "Animal meme": {"dog", "doge", "cat", "kitty", "frog", "pepe", "shib", "inu", "monkey", "ape", "bear", "bull",
                    "penguin", "hamster", "rabbit", "duck", "fox", "wolf", "bird", "fish", "whale", "pig", "cow",
                    "horse", "panda", "tiger", "lion", "bonk", "wif", "hippo", "goat", "cheems", "pup", "puppy"},
    "Politics / public figure": {"trump", "maga", "biden", "elon", "musk", "president", "election", "vote", "congress"},
    "Tech / automation": {"ai", "agent", "agents", "gpt", "bot", "robot", "neural", "quantum", "cyber", "tech", "agi"},
    "Internet culture": {"meme", "viral", "brainrot", "skibidi", "sigma", "rizz", "npc", "gigachad", "chad", "wojak",
                         "based", "tiktok", "anime", "gaming", "gamer", "vibes"},
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; scanner/3.0)", "Accept": "application/json"}
DEX = "https://api.dexscreener.com"
GECKO = "https://api.geckoterminal.com/api/v2"
FOOTER = f"{BOT_NAME} • {CREDIT}"

DEFAULT_STATE = {"alerted": {}, "rejected": {}, "tracked": {}, "pending": {},
                 "stats": {"n": 0, "wins": 0, "sum": 0.0, "x2": 0},
                 "scans": 0, "alerts": 0, "last_status": 0}
state = json.loads(json.dumps(DEFAULT_STATE))   # kept in memory while the bot runs
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


def get_json(url, params=None, retries=2, timeout=15):
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 200:
                return r.json()
            return None
        except Exception as e:
            print(f"  request error {url[:60]}...: {e}")
            time.sleep(1.5)
    return None


def fmt_usd(n):
    if n >= 1e9: return f"${n/1e9:.2f}B"
    if n >= 1e6: return f"${n/1e6:.2f}M"
    if n >= 1e3: return f"${n/1e3:.1f}K"
    return f"${n:.2f}"


def fmt_age(m):
    if m < 60: return f"{m:.0f}m"
    if m < 1440: return f"{m/60:.1f}h"
    return f"{m/1440:.1f}d"


def score_bar(score, n=10):
    filled = max(0, min(n, round(score / 100 * n)))
    return "█" * filled + "░" * (n - filled)


# ======================================================
# 1) FIND COINS (everything pump.fun / Axiom / Fomo / Photon / BullX etc. can trade)
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
        time.sleep(0.5)
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
            time.sleep(1.0)
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
        time.sleep(0.4)
    return found


def fetch_pairs(candidates, pause=0.4):
    by_chain = {}
    for chain, addr in candidates:
        by_chain.setdefault(chain, []).append(addr)
    best = {}
    for chain, addrs in by_chain.items():
        for i in range(0, len(addrs), 30):
            data = get_json(f"{DEX}/tokens/v1/{chain}/{','.join(addrs[i:i + 30])}",
                            retries=2 if pause else 0, timeout=15 if pause else 6)
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
# 2) BULLISH CHECK: market filter + momentum score
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

    if liq < MIN_LIQUIDITY_USD or vol24 < MIN_VOLUME_24H:
        return None
    if not (MIN_MARKET_CAP <= mcap <= MAX_MARKET_CAP):
        return None
    if age_min is None or age_min < MIN_PAIR_AGE_MIN or age_min > MAX_PAIR_AGE_MIN:
        return None
    if (b24 + s24) < MIN_TXNS_24H or (mcap and liq / mcap < MIN_LIQ_TO_MCAP):
        return None
    if liq and vol24 / liq > MAX_VOL_TO_LIQ:   # wash-trading pattern
        return None
    if ch24 > MAX_24H_PUMP_PCT or ch1 < -5 or ch24 < -30:
        return None
    ratio1, ratio24, ratio5 = b1 / max(s1, 1), b24 / max(s24, 1), b5 / max(s5, 1)
    if ratio1 < MIN_BUY_SELL_RATIO_H1 or ratio24 < 0.95:
        return None
    if (b5 + s5) >= 10 and ratio5 < 0.8:   # momentum fading right now
        return None
    if b24 > 50 and s24 == 0:              # honeypot-like behaviour
        return None

    score = 0
    score += min(20, ratio1 * 8)                              # buy pressure (1h)
    score += min(8, ratio5 * 3) if (b5 + s5) >= 5 else 0      # buy pressure (5m)
    score += min(10, max(0, (ratio24 - 1) * 20))              # buy pressure (lifetime)
    score += 8 if ch5 >= 0 else 0
    score += 8 if ch1 > 0 else 0
    score += 6 if ch6 > 0 else 0
    score += 6 if 5 <= ch24 <= 400 else (2 if ch24 > 0 else 0)
    score += min(12, (vol1 * 24 / max(vol24, 1)) * 6)         # volume accelerating
    score += min(8, (liq / max(mcap, 1)) * 80)                # liquidity depth
    score += 4 if liq >= 40_000 else 0
    info = pair.get("info") or {}
    score += 4 if info.get("socials") else 0
    score += 4 if info.get("websites") else 0
    score += 10 if 60 <= age_min <= 150 else (5 if age_min <= 240 else 0)   # sweet spot ~1-2h old
    score += min(10, (nsrc - 1) * 5)                          # seen on several sources

    return min(100, round(score)), {
        "liq": liq, "mcap": mcap, "vol24": vol24, "ch1": ch1, "ch6": ch6, "ch24": ch24,
        "ratio1": ratio1, "ratio5": ratio5, "age_min": age_min, "txns": b24 + s24, "nsrc": nsrc,
    }


# ======================================================
# 3) LEGIT CHECK: contract, liquidity, holders, bundles, project, copycats
# ======================================================
def fetch_ipfs_json(uri):
    if not uri:
        return {}
    uri = uri.replace("ipfs://", "https://ipfs.io/ipfs/")
    data = get_json(uri, retries=0, timeout=8)
    return data if isinstance(data, dict) else {}


def rugcheck_solana(mint):
    """Solana health data from RugCheck: authorities, LP lock, holders, creator, insiders/bundles, risks."""
    data = get_json(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")
    if not data:
        return {"ok": False, "reasons": ["RugCheck unavailable"], "facts": None, "desc": "", "image": ""}

    reasons = []
    risks = data.get("risks") or []
    danger = [r.get("name", "?") for r in risks if str(r.get("level", "")).lower() == "danger"]
    warn = [r.get("name", "?") for r in risks if str(r.get("level", "")).lower() == "warn"]
    if data.get("rugged"):
        reasons.append("already rugged")
    if danger:
        reasons.append("danger: " + ", ".join(danger[:3]))
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
    """Ethereum / Base / BSC health data from GoPlus: honeypot, taxes, ownership, holders, LP lock."""
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
        r = requests.get(url, headers=HEADERS, timeout=8)
        html = r.text[:200_000]
        title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        desc = re.search(r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]+content=["\'](.*?)["\']', html, re.I | re.S)
        parts = [re.sub(r"\s+", " ", x.group(1)).strip() for x in (title, desc) if x]
        return " — ".join(parts)[:400]
    except Exception:
        return ""


def site_alive(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
        return r.status_code < 400 and len(r.text) > 200
    except Exception:
        return False


def copycat_check(pair):
    """Authenticity: reject coins copying the name/ticker of a bigger or older coin."""
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
            if their_created and their_created < my_created - 3_600_000 and their_liq >= MIN_LIQUIDITY_USD * 0.5:
                return f"copycat: older coin with same name exists: {label}"
        elif their_liq > 100_000 and their_created and their_created < my_created - 86_400_000:
            return f"impersonating established coin: {label}"
    return None


def read_coin(name, symbol, desc, site_blurb):
    """Reads the coin's theme and description quality. Returns (note, score_bonus)."""
    text = " ".join([name or "", symbol or "", desc or "", site_blurb or ""]).lower()
    words = set(re.findall(r"[a-z0-9]+", text))
    labels = [label for label, kw in THEMES.items() if words & kw]
    bonus, bits = 0, []
    if labels:
        bonus += 3
        bits.append("/".join(labels) + " theme")
    else:
        bits.append("no clear theme")
    if len((desc or "").strip()) >= 60:
        bonus += 3
        bits.append("clear description")
    if site_blurb:
        bonus += 2
        bits.append("live website")
    d = (desc or "").strip()
    letters = sum(c.isalpha() for c in d)
    if len(d) > 30 and (d.count("!") > 3 or (letters and sum(c.isupper() for c in d) / letters > 0.6)):
        bonus -= 5
        bits.append("shilly wording")
    return " • ".join(bits), bonus


def build_legit(chain, f, extra):
    """Legit score (0-100) + the report lines: (icon, label, value, group)."""
    s = 0
    lines = []

    def item(group, label, val, got, mx):
        nonlocal s
        s += got
        lines.append(("✅" if got >= mx * 0.7 else "⚠️", label, val, group))

    if chain == "solana":
        lp = f["lp_locked"]
        item("contract", "Mint authority", "renounced" if f["mint_ren"] else "NOT renounced", 10 if f["mint_ren"] else 0, 10)
        item("contract", "Freeze authority", "renounced" if f["freeze_ren"] else "NOT renounced", 10 if f["freeze_ren"] else 0, 10)
        item("contract", "Liquidity locked/burned", "n/a" if lp is None else f"{lp:.0f}%",
             5 if lp is None else (15 if lp >= 95 else 10 if lp >= 70 else 5 if lp >= 50 else 0), 15)
        rs = f["risk_score"]
        item("contract", "RugCheck risk score", "n/a" if rs is None else f"{rs:.0f}/100 (lower is safer)",
             5 if rs is None else (10 if rs <= 10 else 7 if rs <= 25 else 3 if rs <= 40 else 0), 10)
        lines.append(("✅" if f["transfer_fee"] <= 1 else "⚠️", "Transfer fee", f"{f['transfer_fee']:.0f}%", "contract"))
        h = f["holders"]
        item("holders", "Holders", str(h), 10 if h >= 500 else 7 if h >= 250 else 4 if h >= 100 else 0, 10)
        t10 = f["top10"]
        item("holders", "Top 10 wallets", f"{t10:.0f}% (largest {f['top1']:.0f}%)", 10 if t10 <= 25 else 7 if t10 <= 35 else 3 if t10 <= 50 else 0, 10)
        cp = f["creator_pct"]
        item("holders", "Creator holding", "n/a" if cp is None else f"{cp:.1f}%",
             5 if cp is None else (10 if cp <= 2 else 7 if cp <= 5 else 3 if cp <= 10 else 0), 10)
        ins = f["insiders"] + (1 if f["insider_network"] else 0) + len(f["bundle_flags"])
        item("holders", "Insiders / bundles", "none detected" if ins == 0 else f"{ins} flagged", 10 if ins == 0 else 4 if ins == 1 else 0, 10)
        if f["warnings"]:
            lines.append(("⚠️", "RugCheck warnings", ", ".join(f["warnings"][:3]), "contract"))
    else:
        tax = max(f["buy_tax"], f["sell_tax"])
        item("contract", "Honeypot test", "passed (can sell)", 15, 15)
        item("contract", "Buy / sell tax", f"{f['buy_tax']:.0f}% / {f['sell_tax']:.0f}%", 10 if tax <= 3 else 5 if tax <= 10 else 0, 10)
        item("contract", "Contract source", "verified" if f["open_source"] else "unverified", 10 if f["open_source"] else 0, 10)
        item("contract", "Ownership", "renounced" if f["owner_ren"] else "owner active", 10 if f["owner_ren"] else 4, 10)
        item("contract", "Dangerous functions", "none (mint / blacklist / pause / hidden owner)", 10, 10)
        lp = f["lp_locked"]
        item("contract", "Liquidity locked", f"{lp:.0f}%", 5 if lp >= 70 else 3 if lp >= 30 else 0, 5)
        h = f["holders"]
        item("holders", "Holders", str(h), 10 if h >= 500 else 7 if h >= 250 else 4 if h >= 100 else 0, 10)
        t10 = f["top10"]
        item("holders", "Top wallets (excl. contracts)", f"{t10:.0f}%", 10 if t10 <= 25 else 7 if t10 <= 35 else 3 if t10 <= 50 else 0, 10)
        cp = f["creator_pct"]
        item("holders", "Creator holding", f"{cp:.1f}%", 5 if cp <= 2 else 3 if cp <= 5 else 1 if cp <= 10 else 0, 5)

    item("project", "Website", "live" if extra["site_ok"] else "none", 3 if extra["site_ok"] else 0, 3)
    item("project", "Social accounts", str(extra["socials"]), 2 if extra["socials"] >= 1 else 0, 2)
    item("project", "Description", "clear, readable" if extra["desc_ok"] else "thin", 5 if extra["desc_ok"] else 0, 5)
    item("project", "Copycat check", "original, no older/bigger copy found", 5, 5)
    return s, lines


def deep_check(pair, d):
    """Full health check. Returns (ok, reason, deep). Only coins that pass everything get through."""
    chain = pair["chainId"]
    base = pair.get("baseToken") or {}
    addr = base.get("address")
    key = f"{chain}:{addr}"

    safety = rugcheck_solana(addr) if chain == "solana" else goplus_check(chain, addr)
    if not safety["ok"] or not safety["facts"]:
        return False, "; ".join(safety["reasons"]) or "no safety data", None

    fake = copycat_check(pair)
    if fake:
        return False, fake, None

    info = pair.get("info") or {}
    sites = [w.get("url") for w in info.get("websites") or [] if w.get("url")]
    socials = [s.get("url") for s in info.get("socials") or [] if s.get("url")]
    if len(sites) + len(socials) < MIN_SOCIAL_LINKS:
        return False, "no website/socials (can't verify it's real)", None
    if REQUIRE_WEBSITE_AND_SOCIAL and (not sites or not socials):
        return False, "needs both a website and a social account to count as legit", None
    site_ok = bool(sites) and site_alive(sites[0])
    if REQUIRE_LIVE_SITE and sites and not site_ok:
        return False, "website doesn't load (dead/fake)", None

    desc = (profile_desc.get(key) or safety.get("desc") or "").strip()
    site_blurb = fetch_site_blurb(sites[0]) if sites and len(desc) < MIN_DESC_LEN + 10 else ""
    context = " ".join([base.get("name", ""), base.get("symbol", ""), desc, site_blurb])
    hit = RED_RE.findall(context)
    if hit:
        return False, "scammy wording: " + ", ".join(sorted(set(h.lower() for h in hit))[:3]), None
    about_len = max(len(desc), len(site_blurb))
    if REQUIRE_NARRATIVE and about_len < MIN_DESC_LEN:
        return False, "can't tell what the coin is about (no real description)", None

    narr, bonus = read_coin(base.get("name"), base.get("symbol"), desc, site_blurb)
    legit, lines = build_legit(chain, safety["facts"], {"site_ok": site_ok, "socials": len(socials),
                                                        "desc_ok": about_len >= MIN_DESC_LEN})
    if legit < MIN_LEGIT_SCORE:
        return False, f"legit score {legit} below {MIN_LEGIT_SCORE}", None

    image = info.get("imageUrl") or safety.get("image") or ""
    return True, "ok", {"legit": legit, "lines": lines, "desc": desc, "site_blurb": site_blurb, "narr": narr,
                        "bonus": bonus, "image": image, "sites": sites, "socials": socials}


# ======================================================
# 4) DISCORD (look & feel + routing to the 5 channels)
# ======================================================
def tier(score):
    if score >= 85: return "🔱 S-TIER"
    if score >= 78: return "🥇 A-TIER"
    return "🥈 B-TIER"


def risk_label(legit):
    if legit >= 90: return "VERY LOW RISK"
    if legit >= 80: return "LOW RISK"
    return "MODERATE RISK"


def trade_links(pair):
    chain = pair["chainId"]
    addr = (pair.get("baseToken") or {}).get("address")
    pa = pair.get("pairAddress") or addr
    links = [f"[DexScreener]({pair.get('url')})"]
    if chain == "solana":
        links += [f"[Axiom](https://axiom.trade/meme/{pa})",
                  f"[Photon](https://photon-sol.tinyastro.io/en/lp/{pa})",
                  f"[BullX](https://neo.bullx.io/terminal?chainId=1399811149&address={addr})",
                  f"[Pump.fun](https://pump.fun/coin/{addr})",
                  f"[Birdeye](https://birdeye.so/token/{addr}?chain=solana)",
                  f"[RugCheck](https://rugcheck.xyz/tokens/{addr})"]
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
    """The main callout."""
    base = pair.get("baseToken") or {}
    chain = pair.get("chainId", "?")
    addr = base.get("address", "?")
    price = num(pair.get("priceUsd"))
    about = deep["desc"] or deep["site_blurb"] or "No description provided"

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
        {"name": "🛡️ Legit check (full report in the Legit Checker channel)", "value": trunc(short, 900), "inline": False},
        {"name": "⚡ Quick trade", "value": trunc(trade_links(pair), 1000), "inline": False},
    ]
    links = official_links(pair, deep)
    if links:
        fields.append({"name": "🌐 Official", "value": links, "inline": False})
    fields.append({"name": "🎯 Plan (not advice)",
                   "value": f"Entry ref `${price:.8g}` • Invalidation −30% `${price*0.7:.8g}`\n"
                            f"Seen on {d['nsrc']} source(s). Size small, take profit in stages.\n"
                            f"📊 Bot track record: {stats_line()}\n"
                            f"👁️ Watched every {WATCH_EVERY}s: EXIT and take-profit alerts follow.",
                   "inline": False})
    embed = {
        "author": {"name": f"{BOT_NAME}  •  🔥 LIVE CALL"},
        "title": f"{base.get('name', '?')}  (${base.get('symbol', '?')})",
        "url": pair.get("url"),
        "description": desc,
        "color": 0x00FF99 if score >= 85 else (0x2ECC71 if score >= 78 else 0x3498DB),
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
    """The full health report that goes to the Legit Checker channel."""
    base = pair.get("baseToken") or {}
    chain = pair.get("chainId", "?")
    addr = base.get("address", "?")
    groups = {"contract": [], "holders": [], "project": []}
    for icon, label, val, grp in deep["lines"]:
        groups[grp].append(f"{icon} **{label}:** {val}")
    market = [f"✅ **Bullish score:** {score}/100 ({tier(score)})",
              f"✅ **Buy/sell pressure:** {d['ratio1']:.2f}x (1h) • {d['ratio5']:.2f}x (5m)",
              f"✅ **Liquidity:** {fmt_usd(d['liq'])} ({d['liq'] / max(d['mcap'], 1) * 100:.0f}% of mcap)",
              f"✅ **Volume:** {fmt_usd(d['vol24'])} • {d['txns']:.0f} txns • no wash-trading pattern",
              f"✅ **Age:** {fmt_age(d['age_min'])} (past the first-45-minute danger zone)",
              f"✅ **Live watch:** stayed healthy for {CONFIRM_SECONDS}s at 2s checks"]
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
    for e in embeds:  # one embed per message so images/fields never get squashed
        payload = {"username": BOT_NAME, "embeds": [e]}
        if content:
            payload["content"] = content
            content = None
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 429:
                time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
                r = requests.post(url, json=payload, timeout=15)
            if r.status_code in (200, 204):
                print(f"Message sent ({channel})")
            else:
                ok = False
                print(f"Discord error {r.status_code} ({channel}): {r.text[:200]}")
        except Exception as ex:
            ok = False
            print(f"Discord send error ({channel}): {ex}")
        time.sleep(0.5)
    return ok


def send_discord_message(content: str, title: str = "Memecoin Alert"):
    send_embeds([{
        "author": {"name": BOT_NAME},
        "title": title,
        "description": content,
        "color": 0x00FF99,
        "footer": {"text": FOOTER},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }])


def send_startup():
    send_embeds([{
        "author": {"name": BOT_NAME},
        "title": "🟢  SYSTEM ONLINE",
        "description": (
            "```\n"
            "NETWORKS   Solana • Base • Ethereum • BSC\n"
            f"WINDOW     {MIN_PAIR_AGE_MIN}-{MAX_PAIR_AGE_MIN} min old coins\n"
            f"SCAN       every {CHECK_INTERVAL}s\n"
            "WATCH      every 2s before + after each call\n"
            "```"
        ),
        "color": 0x00FF99,
        "fields": [
            {"name": "🔍 Detection", "value": "pump.fun • PumpSwap • Raydium • Meteora • Uniswap • PancakeSwap, "
                                              "everything Axiom, Fomo, Photon & BullX trade", "inline": False},
            {"name": "🛡️ Legit Checker", "value": "Rug & honeypot checks • holders • bundles/insiders • creator holding • "
                                                  "liquidity lock • copycats • website & socials", "inline": False},
            {"name": "📊 Accountability", "value": "Every call is tracked. Real results are posted 15m, 1h, 6h and 24h "
                                                   "after the alert, with a running record.", "inline": False},
        ],
        "footer": {"text": FOOTER + " • only passed coins are posted"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }])


CHANGELOG = [
    ("🔎 Wider detection", "Scans pump.fun, PumpSwap, Raydium, Meteora, Uniswap and PancakeSwap on Solana, Base, "
                          "Ethereum and BSC, which covers every coin Fomo, Axiom, Photon and BullX trade. More pools "
                          "and search terms are checked each scan."),
    ("🛡️ Legit Checker channel", "Every call gets a full health report with a Legit Score out of 100: mint & freeze "
                                "authority, liquidity lock, holders, top-10 concentration, creator holding, "
                                "insiders/bundles, RugCheck risk, honeypot and tax tests on EVM chains, copycat check, "
                                "live website, socials and a plain-English read of what the coin is about."),
    ("📈 Bullish filter", "Only coins with real momentum are considered: buy pressure over 5m / 1h / 24h, accelerating "
                         "volume, healthy liquidity, no wash-trading pattern, not already pumped."),
    ("👁️ Live watch", "Every coin must stay healthy for 90 seconds under a 2-second live watch before it is called. "
                     "Called coins are watched every 2 seconds for 6 hours."),
    ("🚨 Exit alerts", "Dedicated Exit channel: liquidity pull, 25%+ liquidity drop, or a 30% drop from entry."),
    ("💰 Take-profit alerts", "Dedicated Take Profit channel: alerts at 2x, 3x, 5x and 10x, plus a pullback warning "
                             "when a winner drops 20% from its peak."),
    ("📊 Track record", "Every call is followed up at 15m, 1h, 6h and 24h, and the running win record is shown on "
                       "each new call."),
    ("🎨 Redesign", "New call layout with the token address right next to the name, quick links to Axiom, Photon, "
                   "BullX, Pump.fun, Birdeye, GMGN and DexScreener."),
]


def post_updates_if_new():
    """Posts the changelog to the Updates channel once per VERSION."""
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
        "description": "Everything that's been added to the bot in this release:",
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
# 5) LIVE MONITOR (every 2 seconds), EXIT / TAKE-PROFIT ALERTS & RESULTS
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
    """Count a call in the track record once its outcome is known."""
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
    print(f"  ✓ {sym}: confirmed live, sending call (bullish {final}, legit {deep['legit']})")
    state["alerted"][key] = now
    state["alerts"] += 1
    price = num(pair.get("priceUsd"))
    state["tracked"][key] = {"symbol": sym, "name": base.get("name"), "chain": pair["chainId"],
                             "addr": base.get("address"), "price": price, "liq0": d["liq"],
                             "peak": price, "tp": [], "ts": now, "reported": []}
    send_embeds([build_embed(pair, final, d, deep)],
                content=f"🚨 **{base.get('name')}** (${sym})  `{base.get('address')}`", channel="callouts")
    send_embeds([build_legit_embed(pair, final, d, deep)], channel="legit")


def check_pending(key, live, now):
    """Pre-call confirmation: the coin must stay healthy while we watch it every 2 seconds."""
    pend = state["pending"].get(key)
    if not pend:
        return
    sym = (pend["pair"].get("baseToken") or {}).get("symbol")
    if now - pend["t0"] > CONFIRM_SECONDS * 4:
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
        print(f"  ✗ {sym}: failed live confirmation (liquidity/price dropping)")
        return
    if now - pend["t0"] < CONFIRM_SECONDS:
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
    """Post-call watch: EXIT alert on liquidity pull / dump, take-profit alerts, pullback warning."""
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
    rugged = liq < 2000 or liq_drop >= 0.6

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
                "Consider selling part (e.g. your initial amount) and letting the rest ride.",
                0xF1C40F, "💰 TAKE PROFIT")],
                content=f"💰 **{x}x: {t['name']}** (${t['symbol']})  `{t['addr']}`", channel="profit")

    peak_gain = (t["peak"] / entry - 1) * 100
    if peak_gain >= 20 and not t.get("pullback_sent") and price <= t["peak"] * (1 - PEAK_PULLBACK):
        t["pullback_sent"] = True
        send_embeds([live_embed(
            t, f"⚠️ PULLBACK: {t['name']} is down {PEAK_PULLBACK * 100:.0f}% from its peak",
            f"```\nPEAK   ${t['peak']:.8g}  ({peak_gain:+.0f}% vs entry)\nNOW    ${price:.8g}  ({change:+.0f}%)\n```"
            "Momentum is fading. Consider securing profit.",
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
    live = fetch_pairs(watch.values(), pause=0)    # one light request per chain, no sleeps
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
        pulled = liq < 2000
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
        }])


# ======================================================
# 6) MAIN SCAN
# ======================================================
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
        if ev and ev[0] >= MIN_SCORE - 10:     # leave room for the narrative bonus/penalty
            results.append((ev[0], key, pair, ev[1]))
    results.sort(key=lambda x: x[0], reverse=True)
    print(f"  {len(results)} passed market filters")

    queued, checked = 0, 0
    for score, key, pair, d in results:
        if checked >= MAX_DEEP_CHECKS_PER_SCAN:
            break
        checked += 1
        ok, reason, deep = deep_check(pair, d)
        base = pair.get("baseToken") or {}
        sym = base.get("symbol")
        final = score
        if ok:
            final = min(100, score + deep["bonus"])
            if final < MIN_SCORE:
                ok, reason = False, f"final score {final} below {MIN_SCORE}"
        if not ok:
            state["rejected"][key] = now
            print(f"  ✗ {sym}: {reason}")
            continue
        # passed every static check: now it must stay healthy under the 2-second live watch before it is called
        print(f"  … {sym}: passed all checks (legit {deep['legit']}), confirming live for {CONFIRM_SECONDS}s")
        state["pending"][key] = {"chain": pair["chainId"], "addr": base.get("address"), "pair": pair,
                                 "deep": deep, "nsrc": d["nsrc"], "t0": now, "liq0": d["liq"],
                                 "price0": num(pair.get("priceUsd"))}
        queued += 1
    if not queued:
        print("  nothing passed all checks this round")


def status_if_due():
    if not SEND_STATUS:
        return
    now = time.time()
    if now - state["last_status"] >= STATUS_EVERY:
        state["last_status"] = now
        send_embeds([{
            "author": {"name": BOT_NAME},
            "title": "✅  SCANNER RUNNING",
            "description": ("```\n"
                            f"SCANS     {state['scans']}\n"
                            f"CALLS     {state['alerts']}\n"
                            f"TRACKING  {len(state['tracked'])}\n"
                            "```" + stats_line()),
            "color": 0x95A5A6,
            "footer": {"text": FOOTER},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }])


if __name__ == "__main__":
    print("Memecoin webhook bot started...")
    send_startup()
    post_updates_if_new()
    state["last_status"] = time.time()
    threading.Thread(target=monitor_loop, daemon=True).start()   # live watch every 2 seconds
    while True:
        print(f"[{datetime.now()}] Checking...")
        try:
            track_results()
            check_for_tokens()
            status_if_due()
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(CHECK_INTERVAL)

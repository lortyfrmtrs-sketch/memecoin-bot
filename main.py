import re
import json
import time
import requests
from datetime import datetime, timezone

# ======================================================
# CONFIGURATION
# ======================================================
WEBHOOK_URL = "https://discord.com/api/webhooks/1571990911737405582/gk8RqKJdRWjOSahlwoJ1jwgLeGTycEsYipFkYJaidcvUb2mgtv8uGPjBNM888r49wfqp"

SEND_STATUS = False               # periodic 'scanner running' message (off = only calls)
SEND_RESULT_UPDATES = True       # follow-up results on past calls (15m/1h/6h/24h)
CHECK_INTERVAL = 60              # scan every minute, alerts are sent instantly
REALERT_AFTER = 12 * 3600        # never repeat the same coin within 12 hours
RECHECK_REJECTED_AFTER = 1800    # re-check a rejected coin after 30 minutes
MAX_ALERTS_PER_SCAN = 4
MAX_DEEP_CHECKS_PER_SCAN = 15
STATUS_EVERY = 6 * 3600          # "bot is alive" status message interval

# ---- Market filters (tuned for EARLY coins, ~1 hour old) ----
MIN_PAIR_AGE_MIN = 20            # as early as possible (coins under 40 min are flagged EARLY / higher risk)
MAX_PAIR_AGE_MIN = 240           # skip anything older than 4 hours (too late)
MIN_LIQUIDITY_USD = 15_000
MIN_VOLUME_24H = 25_000
MIN_MARKET_CAP = 40_000
MAX_MARKET_CAP = 5_000_000
MIN_TXNS_24H = 250
MIN_LIQ_TO_MCAP = 0.06
MIN_BUY_SELL_RATIO_H1 = 1.2
MAX_24H_PUMP_PCT = 800           # already ran too hard = too late
MIN_SCORE = 75                   # final 0-100 score needed to alert

# ---- Safety / authenticity filters ----
REQUIRE_SAFETY_DATA = True       # if the safety checkers can't answer, skip the coin
MAX_RUGCHECK_SCORE = 40
MAX_TOP10_HOLDER_PCT = 50
MIN_HOLDERS = 100
MAX_INSIDERS_TOP10 = 1
MAX_TAX_PCT = 10
MIN_SOCIAL_LINKS = 2             # must have a website or social link
REQUIRE_WEBSITE_AND_SOCIAL = True  # legit projects have BOTH a website and a social account
REQUIRE_LIVE_SITE = True         # the website must actually load
MIN_LP_LOCKED_PCT = 50           # Solana: liquidity must be locked/burned (anti-rug)
REQUIRE_NARRATIVE = True         # must have a description or a website

CHAINS = {"solana", "base", "ethereum", "bsc"}
GECKO_NETWORKS = {"solana": "solana", "base": "base", "eth": "ethereum", "bsc": "bsc"}
GOPLUS_CHAIN = {"ethereum": "1", "bsc": "56", "base": "8453"}
GMGN_CHAIN = {"solana": "sol", "base": "base", "ethereum": "eth", "bsc": "bsc"}
CHECKPOINTS_H = (0.25, 1, 6, 24)  # report how past alerts performed: 15m, 1h, 6h, 24h

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

DEFAULT_STATE = {"alerted": {}, "rejected": {}, "tracked": {},
                 "stats": {"n": 0, "wins": 0, "sum": 0.0, "x2": 0},
                 "scans": 0, "alerts": 0, "last_status": 0}
profile_desc = {}


state = json.loads(json.dumps(DEFAULT_STATE))  # kept in memory while the bot runs


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
        for kind, page in (("trending_pools", 1), ("new_pools", 1), ("new_pools", 2), ("new_pools", 3)):
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
    for q in ("pump", "pumpfun", "meme", "pepe", "dog", "cat", "ai agent", "trump", "bonk", "frog"):
        data = get_json(f"{DEX}/latest/dex/search", params={"q": q})
        if data:
            for p in data.get("pairs", []) or []:
                chain = p.get("chainId")
                addr = (p.get("baseToken") or {}).get("address")
                if chain in CHAINS and addr:
                    found.add((chain, addr))
        time.sleep(0.5)
    return found


def fetch_pairs(candidates):
    by_chain = {}
    for chain, addr in candidates:
        by_chain.setdefault(chain, []).append(addr)
    best = {}
    for chain, addrs in by_chain.items():
        for i in range(0, len(addrs), 30):
            chunk = addrs[i:i + 30]
            data = get_json(f"{DEX}/tokens/v1/{chain}/{','.join(chunk)}")
            if isinstance(data, list):
                for p in data:
                    addr = (p.get("baseToken") or {}).get("address")
                    if not addr:
                        continue
                    key = f"{chain}:{addr}"
                    liq = (p.get("liquidity") or {}).get("usd") or 0
                    if key not in best or liq > ((best[key].get("liquidity") or {}).get("usd") or 0):
                        best[key] = p
            time.sleep(0.4)
    return best


# ======================================================
# 2) MARKET FILTER + MOMENTUM SCORE
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
    score += 10 if 30 <= age_min <= 120 else (5 if age_min <= 240 else 0)   # sweet spot ~1h old
    score += min(10, (nsrc - 1) * 5)                          # seen on several sources

    return min(100, round(score)), {
        "liq": liq, "mcap": mcap, "vol24": vol24, "ch1": ch1, "ch6": ch6, "ch24": ch24,
        "ratio1": ratio1, "ratio5": ratio5, "age_min": age_min, "txns": b24 + s24, "nsrc": nsrc,
    }


# ======================================================
# 3) SAFETY, AUTHENTICITY & NARRATIVE
# ======================================================
def fetch_ipfs_json(uri):
    if not uri:
        return {}
    uri = uri.replace("ipfs://", "https://ipfs.io/ipfs/")
    data = get_json(uri, retries=0, timeout=8)
    return data if isinstance(data, dict) else {}


def rugcheck_solana(mint):
    data = get_json(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")
    if not data:
        return {"ok": not REQUIRE_SAFETY_DATA, "note": "RugCheck unavailable"}

    reasons = []
    if data.get("rugged"):
        reasons.append("already rugged")
    danger = [r.get("name", "?") for r in (data.get("risks") or []) if str(r.get("level", "")).lower() == "danger"]
    if danger:
        reasons.append("danger: " + ", ".join(danger[:3]))
    score = data.get("score_normalised")
    if score is not None and num(score) > MAX_RUGCHECK_SCORE:
        reasons.append(f"risk score {score}")
    if data.get("mintAuthority"):
        reasons.append("mint authority NOT renounced")
    if data.get("freezeAuthority"):
        reasons.append("freeze authority NOT renounced")

    holders = data.get("topHolders") or []
    top10 = sum(num(h.get("pct")) for h in holders[:10])
    if top10 > MAX_TOP10_HOLDER_PCT:
        reasons.append(f"top 10 hold {top10:.0f}%")
    insiders = sum(1 for h in holders[:10] if h.get("insider"))
    if insiders > MAX_INSIDERS_TOP10:
        reasons.append(f"{insiders} insider/linked wallets in top 10")
    if num(data.get("graphInsidersDetected")) > 0:
        reasons.append("insider network detected")
    total_holders = int(num(data.get("totalHolders")))
    if total_holders and total_holders < MIN_HOLDERS:
        reasons.append(f"only {total_holders} holders")

    lp_locked = 0
    for m in data.get("markets") or []:
        lp_locked = max(lp_locked, num((m.get("lp") or {}).get("lpLockedPct")))
    lp_seen = any((m.get("lp") or {}) for m in data.get("markets") or [])
    if lp_seen and lp_locked < MIN_LP_LOCKED_PCT:
        reasons.append(f"only {lp_locked:.0f}% of liquidity locked/burned")

    meta = data.get("fileMeta") or {}
    desc, image = meta.get("description"), meta.get("image")
    if not desc:
        uri_meta = fetch_ipfs_json((data.get("tokenMeta") or {}).get("uri"))
        desc, image = uri_meta.get("description"), image or uri_meta.get("image")

    warn = [r.get("name", "?") for r in (data.get("risks") or []) if str(r.get("level", "")).lower() == "warn"]
    note = "Clean ✅" if not warn else "Warnings: " + ", ".join(warn[:3])
    note += f" • Top10: {top10:.0f}% • Holders: {total_holders or '?'} • LP locked: {lp_locked:.0f}% • Mint/Freeze renounced"
    return {"ok": not reasons, "note": "; ".join(reasons) if reasons else note,
            "desc": desc or "", "image": image or ""}


def goplus_check(chain, addr):
    data = get_json(f"https://api.gopluslabs.io/api/v1/token_security/{GOPLUS_CHAIN[chain]}",
                    params={"contract_addresses": addr})
    res = ((data or {}).get("result") or {}).get(addr.lower())
    if not res:
        return {"ok": not REQUIRE_SAFETY_DATA, "note": "GoPlus unavailable"}

    reasons = []
    if res.get("is_honeypot") == "1":
        reasons.append("HONEYPOT")
    if num(res.get("buy_tax")) * 100 > MAX_TAX_PCT or num(res.get("sell_tax")) * 100 > MAX_TAX_PCT:
        reasons.append(f"tax {num(res.get('buy_tax'))*100:.0f}%/{num(res.get('sell_tax'))*100:.0f}%")
    if res.get("is_open_source") == "0":
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
    return {"ok": not reasons,
            "note": "; ".join(reasons) if reasons else
            f"Clean ✅ • Holders: {holders} • Tax {num(res.get('buy_tax'))*100:.0f}%/{num(res.get('sell_tax'))*100:.0f}%",
            "desc": "", "image": ""}


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


def deep_check(pair, d):
    chain = pair["chainId"]
    base = pair.get("baseToken") or {}
    addr = base.get("address")
    key = f"{chain}:{addr}"

    safety = rugcheck_solana(addr) if chain == "solana" else goplus_check(chain, addr)
    if not safety["ok"]:
        return False, safety["note"], None

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
    if REQUIRE_LIVE_SITE and sites and not site_alive(sites[0]):
        return False, "website doesn't load (dead/fake)", None

    desc = (profile_desc.get(key) or safety.get("desc") or "").strip()
    site_blurb = fetch_site_blurb(sites[0]) if sites and len(desc) < 40 else ""

    context = " ".join([base.get("name", ""), base.get("symbol", ""), desc, site_blurb])
    hit = RED_RE.findall(context)
    if hit:
        return False, "scammy wording: " + ", ".join(sorted(set(h.lower() for h in hit))[:3]), None
    if REQUIRE_NARRATIVE and len(desc) < 15 and not sites and not site_blurb:
        return False, "no description or website (anonymous/low effort)", None

    narr, bonus = read_coin(base.get("name"), base.get("symbol"), desc, site_blurb)
    image = info.get("imageUrl") or safety.get("image") or ""
    return True, "ok", {"safety": safety["note"] + " • Authentic ✅ no older/bigger copycat found",
                        "desc": desc, "site_blurb": site_blurb, "narr": narr, "bonus": bonus,
                        "image": image, "sites": sites, "socials": socials}


# ======================================================
# 4) DISCORD (look & feel)
# ======================================================
BOT_NAME = "Valk's Insider Bot"
CHAIN_ICON = {"solana": "◎", "base": "🔵", "ethereum": "⟠", "bsc": "🟡"}


def score_bar(score, n=10):
    filled = max(0, min(n, round(score / 100 * n)))
    return "█" * filled + "░" * (n - filled)


def tier(score):
    if score >= 85: return "🔱 S-TIER"
    if score >= 78: return "🥇 A-TIER"
    return "🥈 B-TIER"


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


def build_embed(pair, score, d, deep):
    base = pair.get("baseToken") or {}
    chain = pair.get("chainId", "?")
    addr = base.get("address", "?")
    price = num(pair.get("priceUsd"))
    early = d["age_min"] < 40
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
            f"`{score_bar(score)}`  **{score}/100**\n{stats}")
    if early:
        desc += "\n⚡ **EARLY ENTRY**: very young coin, higher risk. Keep size small."

    parts = [re.sub(r"\s*✅", "", p).strip() for p in deep["safety"].split(" • ") if p.strip()]
    safety_txt = "\n".join(f"{'⚠️' if p.lower().startswith('warn') else '✅'} {p}" for p in parts[:8])

    fields = [
        {"name": "📝 What it's about", "value": trunc(about, 600), "inline": False},
        {"name": "🧭 Narrative", "value": trunc(deep["narr"], 250), "inline": False},
        {"name": "🛡️ Safety & authenticity", "value": trunc(safety_txt, 600), "inline": False},
        {"name": "⚡ Quick trade", "value": trunc(trade_links(pair), 1000), "inline": False},
    ]
    links = [f"[Website]({u})" for u in deep["sites"][:1]]
    for s in (pair.get("info") or {}).get("socials") or []:
        if s.get("url"):
            links.append(f"[{str(s.get('type', 'link')).title()}]({s['url']})")
    if links:
        fields.append({"name": "🌐 Official", "value": " • ".join(links[:5]), "inline": False})
    fields.append({"name": "🎯 Plan (not advice)",
                   "value": f"Entry ref `${price:.8g}` • Invalidation −30% `${price*0.7:.8g}`\n"
                            f"Seen on {d['nsrc']} source(s). Size small, take profit in stages.",
                   "inline": False})

    color = 0xF1C40F if early else (0x00FF99 if score >= 85 else (0x2ECC71 if score >= 78 else 0x3498DB))
    embed = {
        "author": {"name": f"{BOT_NAME}  •  {'⚡ EARLY CALL' if early else '🔥 LIVE CALL'}"},
        "title": f"{base.get('name', '?')}  (${base.get('symbol', '?')})",
        "url": pair.get("url"),
        "description": desc,
        "color": color,
        "fields": fields,
        "footer": {"text": f"{BOT_NAME} • Nothing is guaranteed • DYOR"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if deep["image"]:
        embed["thumbnail"] = {"url": deep["image"]}
    header = (pair.get("info") or {}).get("header")
    if header:
        embed["image"] = {"url": header}
    return embed


def send_embeds(embeds, content=None):
    ok = True
    for e in embeds:  # one embed per message so images/fields never get squashed
        payload = {"username": BOT_NAME, "embeds": [e]}
        if content:
            payload["content"] = content
            content = None
        try:
            r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
            if r.status_code == 429:
                time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
                r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
            if r.status_code in (200, 204):
                print("Message sent")
            else:
                ok = False
                print(f"Discord error {r.status_code}: {r.text[:200]}")
        except Exception as ex:
            ok = False
            print(f"Discord send error: {ex}")
        time.sleep(0.5)
    return ok


def send_discord_message(content: str, title: str = "Memecoin Alert"):
    send_embeds([{
        "author": {"name": BOT_NAME},
        "title": title,
        "description": content,
        "color": 0x00FF99,
        "footer": {"text": BOT_NAME},
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
            "ALERTS     instant, the moment a coin passes\n"
            "```"
        ),
        "color": 0x00FF99,
        "fields": [
            {"name": "🔍 Detection", "value": "pump.fun • PumpSwap • Raydium • Meteora • Uniswap • PancakeSwap, "
                                              "everything Axiom, Fomo, Photon & BullX trade", "inline": False},
            {"name": "🛡️ Protection", "value": "Rug & honeypot checks • holder/insider analysis • copycat detection "
                                               "• scam-wording filter", "inline": False},
            {"name": "📊 Accountability", "value": "Every call is tracked. Real results are posted 15m, 1h, 6h and 24h "
                                                   "after the alert, with a running win rate.", "inline": False},
        ],
        "footer": {"text": f"{BOT_NAME} • only passed coins are posted"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }])


# ======================================================
# 5) TRACK HOW PAST ALERTS PERFORMED (so you see the real hit rate)
# ======================================================
def stats_line():
    s = state["stats"]
    if not s["n"]:
        return "No 24h results yet."
    return (f"24h record: {s['wins']}/{s['n']} positive ({s['wins']/s['n']*100:.0f}%) • "
            f"avg {s['sum']/s['n']:+.0f}% • {s['x2']} hit 2x+")


def label_h(h):
    return f"{int(round(h * 60))}m" if h < 1 else f"{h:g}h"


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
        if h == CHECKPOINTS_H[-1]:
            s = state["stats"]
            s["n"] += 1
            s["sum"] += change
            s["wins"] += 1 if change > 0 else 0
            s["x2"] += 1 if change >= 100 else 0
            state["tracked"].pop(key, None)
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
            "footer": {"text": BOT_NAME},
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
    for k in [k for k, v in state["rejected"].items() if now - v > 2 * 86400]:
        state["rejected"].pop(k, None)

    results = []
    for key, pair in pairs.items():
        if now - state["alerted"].get(key, 0) < REALERT_AFTER:
            continue
        if now - state["rejected"].get(key, 0) < RECHECK_REJECTED_AFTER:
            continue
        chain, addr = key.split(":", 1)
        ev = evaluate(pair, nsrc.get((chain, addr), 1))
        if ev and ev[0] >= MIN_SCORE - 10:     # leave room for the narrative bonus/penalty
            results.append((ev[0], key, pair, ev[1]))
    results.sort(key=lambda x: x[0], reverse=True)
    print(f"  {len(results)} passed market filters")

    summary = {"candidates": len(candidates), "pairs": len(pairs), "passed_market": len(results),
               "alerts": 0, "misses": []}
    checked = 0
    for score, key, pair, d in results:
        if summary["alerts"] >= MAX_ALERTS_PER_SCAN or checked >= MAX_DEEP_CHECKS_PER_SCAN:
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
            summary["misses"].append((base.get("name") or "?", sym or "?", d["mcap"], reason))
            print(f"  ✗ {sym}: {reason}")
            continue
        print(f"  ✓ {sym}: passed everything ({final})")
        state["alerted"][key] = now
        state["alerts"] += 1
        state["tracked"][key] = {"symbol": sym, "name": base.get("name"), "chain": pair["chainId"],
                                 "addr": base.get("address"), "price": num(pair.get("priceUsd")),
                                 "ts": now, "reported": []}
        # sent immediately, no waiting for the rest of the scan
        send_embeds([build_embed(pair, final, d, deep)],
                    content=f"🚨 **{base.get('name')}** (${sym})  `{base.get('address')}`")
        summary["alerts"] += 1

    if not summary["alerts"]:
        print("  nothing passed all checks this round")
    return summary


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
            "footer": {"text": BOT_NAME},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }])


if __name__ == "__main__":
    print("Memecoin webhook bot started...")
    send_startup()
    state["last_status"] = time.time()
    while True:
        print(f"[{datetime.now()}] Checking...")
        try:
            track_results()
            check_for_tokens()
            status_if_due()
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(CHECK_INTERVAL)

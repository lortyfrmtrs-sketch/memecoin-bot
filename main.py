import os
import re
import json
import time
import requests
from datetime import datetime, timezone

# ======================================================
# CONFIGURATION
# ======================================================
# Put your NEW webhook in an environment variable (recommended) or paste it below.
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "PASTE_YOUR_NEW_WEBHOOK_URL_HERE")

# OPTIONAL: lets Claude read each coin and judge its meaning/narrative.
# Get a key at console.anthropic.com and set ANTHROPIC_API_KEY. Without it, a keyword check is used.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = "claude-haiku-5-5"

CHECK_INTERVAL = 60             # seconds between scans (new coins move fast)
REALERT_AFTER = 12 * 3600       # don't repeat the same coin for 12 hours
RECHECK_REJECTED_AFTER = 3600   # re-check a rejected coin after 1 hour
MAX_ALERTS_PER_SCAN = 5
MAX_DEEP_CHECKS_PER_SCAN = 15   # how many top candidates get the full safety/narrative check

# ---- Market filters (tuned for EARLY coins, ~1 hour old) ----
MIN_PAIR_AGE_MIN = 40           # not too early: skip the first 40 min (sniper/rug zone)
MAX_PAIR_AGE_MIN = 240          # not too late: skip anything older than 4 hours
MIN_LIQUIDITY_USD = 10_000
MIN_VOLUME_24H = 25_000         # for young coins this is basically lifetime volume
MIN_MARKET_CAP = 40_000
MAX_MARKET_CAP = 5_000_000      # still early
MIN_TXNS_24H = 150
MIN_LIQ_TO_MCAP = 0.06
MIN_BUY_SELL_RATIO_H1 = 1.2
MAX_24H_PUMP_PCT = 800          # skip coins that already ran too hard (too late)
MIN_SCORE = 65                  # 0-100 bullish score needed

# ---- Safety filters ----
REQUIRE_SAFETY_DATA = True      # if the rug checkers can't answer, SKIP the coin (safer)
MAX_RUGCHECK_SCORE = 50         # Solana: reject above this risk score
MAX_TOP10_HOLDER_PCT = 60       # Solana: reject if top 10 wallets hold more than this %
MIN_HOLDERS = 80                # young coins have fewer holders
MAX_INSIDERS_TOP10 = 2          # Solana: max insider/linked wallets among top 10
MIN_SOCIAL_LINKS = 1            # must have a website or social link (authenticity)
MAX_TAX_PCT = 10                # EVM: reject buy/sell tax above this
REQUIRE_NARRATIVE = True        # coin must have a description or a website
AI_REQUIRED_VERDICTS = {"good"} # when AI is on, only these verdicts get through

CHAINS = {"solana", "base", "ethereum", "bsc"}
GECKO_NETWORKS = {"solana": "solana", "base": "base", "eth": "ethereum", "bsc": "bsc"}
GOPLUS_CHAIN = {"ethereum": "1", "bsc": "56", "base": "8453"}
GMGN_CHAIN = {"solana": "sol", "base": "base", "ethereum": "eth", "bsc": "bsc"}

RED_WORDS = [
    "guaranteed", "risk free", "risk-free", "no risk", "can't lose", "cant lose", "presale",
    "claim airdrop", "connect wallet", "send sol", "send eth", "double your", "ponzi",
    "pump and dump", "rug", "rugpull", "rug pull", "honeypot", "100x guaranteed", "free money",
]
RED_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in RED_WORDS) + r")\b", re.I)

HEADERS = {"User-Agent": "Mozilla/5.0 (memecoin-discord-bot/2.0)", "Accept": "application/json"}
DEX = "https://api.dexscreener.com"
GECKO = "https://api.geckoterminal.com/api/v2"

alerted = {}    # "chain:address" -> ts
rejected = {}   # "chain:address" -> ts
profile_desc = {}  # "chain:address" -> description from DexScreener profiles


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


# ======================================================
# 1) COLLECT CANDIDATES (covers coins traded on pump.fun, Axiom, Fomo, etc.)
# Axiom/Fomo/Photon/BullX are trading terminals on top of the same chains and DEXes,
# so scanning the chains' DEX data (pump.fun, PumpSwap, Raydium, Meteora, Uniswap,
# PancakeSwap...) covers every coin those apps can trade.
# ======================================================
def from_dexscreener_lists():
    found = set()
    for path in ("/token-profiles/latest/v1", "/token-boosts/latest/v1", "/token-boosts/top/v1"):
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
# 2) MARKET FILTER + BULLISH SCORE
# ======================================================
def evaluate(pair):
    liq = num((pair.get("liquidity") or {}).get("usd"))
    mcap = num(pair.get("marketCap") or pair.get("fdv"))
    vol24 = num((pair.get("volume") or {}).get("h24"))
    vol1 = num((pair.get("volume") or {}).get("h1"))
    pc = pair.get("priceChange") or {}
    ch1, ch6, ch24 = num(pc.get("h1")), num(pc.get("h6")), num(pc.get("h24"))
    tx = pair.get("txns") or {}
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
    ratio1, ratio24 = b1 / max(s1, 1), b24 / max(s24, 1)
    if ratio1 < MIN_BUY_SELL_RATIO_H1 or ratio24 < 0.95:
        return None
    if b24 > 50 and s24 == 0:  # honeypot-like behaviour
        return None

    score = 0
    score += min(20, ratio1 * 8)
    score += min(10, max(0, (ratio24 - 1) * 20))
    score += 10 if ch1 > 0 else 0
    score += 8 if ch6 > 0 else 0
    score += 7 if 5 <= ch24 <= 400 else (3 if ch24 > 0 else 0)
    score += min(15, (vol1 * 24 / max(vol24, 1)) * 7)
    score += min(10, (liq / max(mcap, 1)) * 100)
    score += 5 if liq >= 50_000 else 0
    info = pair.get("info") or {}
    score += 5 if info.get("socials") else 0
    score += 5 if info.get("websites") else 0
    score += 10 if 45 <= age_min <= 120 else (5 if age_min <= 240 else 0)  # sweet spot ~1h old

    return min(100, round(score)), {
        "liq": liq, "mcap": mcap, "vol24": vol24, "ch1": ch1, "ch6": ch6, "ch24": ch24,
        "ratio1": ratio1, "age_min": age_min, "txns": b24 + s24,
    }


# ======================================================
# 3) DEEP SAFETY CHECKS
# ======================================================
def fetch_ipfs_json(uri):
    if not uri:
        return {}
    uri = uri.replace("ipfs://", "https://ipfs.io/ipfs/")
    data = get_json(uri, retries=0, timeout=8)
    return data if isinstance(data, dict) else {}


def rugcheck_solana(mint):
    """Full rugcheck.xyz report: authorities, holders, risks, plus token metadata."""
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
    """GoPlus token security for Ethereum / BSC / Base."""
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
            "note": "; ".join(reasons) if reasons else f"Clean ✅ • Holders: {holders} • Tax {num(res.get('buy_tax'))*100:.0f}%/{num(res.get('sell_tax'))*100:.0f}%",
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


def ai_analyze(name, symbol, chain, desc, site_blurb, socials, d):
    """Claude reads the coin and judges the meaning / narrative / red flags."""
    prompt = f"""You are a skeptical crypto analyst. Judge this memecoin's concept ONLY from the info given.
Name: {name} (${symbol}) on {chain}
Description: {desc or 'none'}
Website snippet: {site_blurb or 'none'}
Socials: {', '.join(socials) or 'none'}
Market: mcap ${d['mcap']:,.0f}, liquidity ${d['liq']:,.0f}, 24h change {d['ch24']:+.0f}%, age {d['age_min']/60:.1f}h

Reply with ONLY a JSON object: {{"verdict":"good|neutral|bad","summary":"one sentence on what the coin is about","narrative":"the theme/meme/trend it rides and why it could (or couldn't) catch on","red_flags":["..."]}}
Use "bad" for scam wording, impersonation, empty/low-effort concepts, or anything shady. Use "good" only for a clear, memeable, genuinely appealing concept."""
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": AI_MODEL, "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        text = r.json()["content"][0]["text"]
        return json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    except Exception as e:
        print(f"  AI analysis failed: {e}")
        return None


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
        return None if not REQUIRE_SAFETY_DATA else "couldn't verify originality"
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
    desc = (profile_desc.get(key) or safety.get("desc") or "").strip()
    site_blurb = fetch_site_blurb(sites[0]) if sites and len(desc) < 40 else ""

    context = " ".join([base.get("name", ""), base.get("symbol", ""), desc, site_blurb])
    hit = RED_RE.findall(context)
    if hit:
        return False, "scammy wording: " + ", ".join(sorted(set(h.lower() for h in hit))[:3]), None
    if REQUIRE_NARRATIVE and len(desc) < 15 and not sites and not site_blurb:
        return False, "no description or website (anonymous/low effort)", None

    ai = None
    if ANTHROPIC_API_KEY:
        ai = ai_analyze(base.get("name"), base.get("symbol"), chain, desc, site_blurb, socials, d)
        if ai:
            verdict = str(ai.get("verdict", "")).lower()
            if verdict not in AI_REQUIRED_VERDICTS:
                return False, f"AI verdict {verdict}: {ai.get('summary', '')}", None

    image = info.get("imageUrl") or safety.get("image") or ""
    return True, "ok", {"safety": safety["note"] + " • Authentic ✅ no older/bigger copycat found", "desc": desc, "site_blurb": site_blurb,
                        "ai": ai, "image": image, "sites": sites, "socials": socials}


# ======================================================
# 4) DISCORD ALERTS
# ======================================================
def fmt_usd(n):
    if n >= 1e9: return f"${n/1e9:.2f}B"
    if n >= 1e6: return f"${n/1e6:.2f}M"
    if n >= 1e3: return f"${n/1e3:.1f}K"
    return f"${n:.2f}"


def fmt_age(m):
    if m < 60: return f"{m:.0f}m"
    if m < 1440: return f"{m/60:.1f}h"
    return f"{m/1440:.1f}d"


def trade_links(pair):
    chain = pair["chainId"]
    addr = (pair.get("baseToken") or {}).get("address")
    pa = pair.get("pairAddress")
    links = [f"[DexScreener]({pair.get('url')})"]
    if chain == "solana":
        links += [f"[Axiom](https://axiom.trade/meme/{pa})",
                  f"[Pump.fun](https://pump.fun/coin/{addr})",
                  f"[RugCheck](https://rugcheck.xyz/tokens/{addr})"]
    links.append(f"[GMGN](https://gmgn.ai/{GMGN_CHAIN[chain]}/token/{addr})")
    return " • ".join(links)


def build_embed(pair, score, d, deep):
    base = pair.get("baseToken") or {}
    chain = pair.get("chainId", "?")
    addr = base.get("address", "?")
    ai = deep["ai"]
    about = deep["desc"] or deep["site_blurb"] or "No description provided"

    fields = [{"name": "📝 What it's about", "value": trunc(about, 700), "inline": False}]
    if ai:
        flags = ai.get("red_flags") or []
        txt = f"**{str(ai.get('verdict', '?')).upper()}** — {ai.get('summary', '')}\n🎯 {ai.get('narrative', '')}"
        if flags:
            txt += "\n⚠️ " + "; ".join(str(f) for f in flags[:3])
        fields.append({"name": "🧠 AI read", "value": trunc(txt, 1000), "inline": False})
    fields += [
        {"name": "📈 Change", "value": f"1h {d['ch1']:+.1f}%\n6h {d['ch6']:+.1f}%\n24h {d['ch24']:+.1f}%", "inline": True},
        {"name": "💰 Market", "value": f"MCap {fmt_usd(d['mcap'])}\nLiq {fmt_usd(d['liq'])}\nVol24h {fmt_usd(d['vol24'])}", "inline": True},
        {"name": "⚡ Activity", "value": f"Buy/Sell 1h {d['ratio1']:.2f}x\nTxns 24h {d['txns']:.0f}\nAge {fmt_age(d['age_min'])}", "inline": True},
        {"name": "🛡️ Safety", "value": trunc(deep["safety"], 400), "inline": False},
        {"name": "📋 Contract address (tap to copy)", "value": f"`{addr}`", "inline": False},
    ]
    social_links = [f"[Site]({u})" for u in deep["sites"][:1]]
    for s in (pair.get("info") or {}).get("socials") or []:
        if s.get("url"):
            social_links.append(f"[{str(s.get('type', 'link')).title()}]({s['url']})")
    if social_links:
        fields.append({"name": "🌐 Official links", "value": " • ".join(social_links[:5]), "inline": False})
    fields.append({"name": "🔗 Trade / analyze", "value": trade_links(pair), "inline": False})

    embed = {
        "title": f"🚀 {base.get('name', '?')} (${base.get('symbol', '?')}) — Score {score}/100",
        "description": f"`{chain}` • `{pair.get('dexId', '?')}` • Price `${pair.get('priceUsd', '?')}`",
        "color": 0x00FF99 if score >= 80 else 0xF1C40F,
        "url": pair.get("url"),
        "fields": fields,
        "footer": {"text": "Not financial advice. Nothing is guaranteed. DYOR."},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if deep["image"]:
        embed["thumbnail"] = {"url": deep["image"]}
    header = (pair.get("info") or {}).get("header")
    if header:
        embed["image"] = {"url": header}
    return embed


def send_embeds(embeds, content=None):
    for e in embeds:  # one embed per message so images/fields never get squashed
        payload = {"embeds": [e]}
        if content:
            payload["content"] = content
            content = None
        try:
            r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
            if r.status_code == 429:
                time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
                r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
            if r.status_code in (200, 204):
                print("Alert sent")
            else:
                print(f"Discord error {r.status_code}: {r.text[:200]}")
        except Exception as ex:
            print(f"Discord send error: {ex}")
        time.sleep(1)


# ======================================================
# 5) MAIN SCAN
# ======================================================
def check_for_tokens():
    candidates = from_dexscreener_lists() | from_geckoterminal() | from_dexscreener_search()
    print(f"  {len(candidates)} candidate tokens")
    pairs = fetch_pairs(candidates)
    print(f"  {len(pairs)} pairs fetched")

    now = time.time()
    results = []
    for key, pair in pairs.items():
        if now - alerted.get(key, 0) < REALERT_AFTER or now - rejected.get(key, 0) < RECHECK_REJECTED_AFTER:
            continue
        ev = evaluate(pair)
        if ev and ev[0] >= MIN_SCORE:
            results.append((ev[0], key, pair, ev[1]))
    results.sort(key=lambda x: x[0], reverse=True)
    print(f"  {len(results)} passed market filters")

    embeds, checked = [], 0
    for score, key, pair, d in results:
        if len(embeds) >= MAX_ALERTS_PER_SCAN or checked >= MAX_DEEP_CHECKS_PER_SCAN:
            break
        checked += 1
        ok, reason, deep = deep_check(pair, d)
        sym = (pair.get("baseToken") or {}).get("symbol")
        if not ok:
            rejected[key] = now
            print(f"  ✗ {sym}: {reason}")
            continue
        print(f"  ✓ {sym}: passed everything")
        alerted[key] = now
        embeds.append(build_embed(pair, score, d, deep))
        time.sleep(0.5)

    if embeds:
        send_embeds(embeds, content="🔥 **Early bullish coin: passed safety + authenticity checks**")
    else:
        print("  nothing passed all checks this round")


if __name__ == "__main__":
    if "PASTE_YOUR" in WEBHOOK_URL:
        raise SystemExit("Set your Discord webhook URL first (DISCORD_WEBHOOK_URL env var or in the file).")
    print("Memecoin scanner started...")
    send_embeds([{
        "title": "Memecoin scanner online",
        "description": (f"Hunting early coins (40-240 min old) on Solana, Base, Ethereum & BSC every {CHECK_INTERVAL}s "
                        f"(pump.fun, PumpSwap, Raydium, Meteora, Uniswap, PancakeSwap — everything Axiom, Fomo, "
                        f"Photon, BullX etc. trade). AI coin reading: {'ON' if ANTHROPIC_API_KEY else 'OFF (keyword check only)'}."),
        "color": 0x00FF99,
    }])
    while True:
        print(f"[{datetime.now()}] Scanning...")
        try:
            check_for_tokens()
        except Exception as e:
            print(f"Scan error: {e}")
        time.sleep(CHECK_INTERVAL)

"""
Instagram Auto-Poster — daily 1 post, 100% free stack (pillar-aware: 365-day unique).

Flow:
  1. Load Day N entry from quotes_365.json -> {quote, pillar}
  2. Pick today's theme DETERMINISTIC, with mood = pillar (no repeat image combo within a year)
  3. Generate image with FREE model: Pollinations.ai / Flux (no API key)
  4. Caption = quote + pillar hashtag
  5. If IG creds present -> upload + publish via Graph API
     Else -> DRY-RUN: save to output/
"""
import os, sys, random, datetime, time, urllib.parse, pathlib, json
import requests
import yaml

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

API_VERSION = os.getenv("IG_API_VERSION", "v21.0")
BASE = f"https://graph.facebook.com/{API_VERSION}"

FALLBACK_QUOTES = [
    "Discipline beats motivation. Show up today.",
    "Small steps every day lead to big results.",
    "Don't wait for opportunity. Create it.",
    "Your future is built by what you do today.",
    "Stay patient. Stay consistent. Stay hungry.",
    "Doubt kills more dreams than failure ever will.",
    "Wake up with purpose. Sleep with pride.",
    "One day or day one. You decide.",
    "Focus on progress, not perfection.",
    "Hard times build strong minds.",
]

_BG = [
    "misty mountains", "golden desert", "emerald forest", "arctic aurora",
    "tropical coast", "monsoon valley", "alpine peak", "red canyon",
    "lavender field", "starry night desert", "autumn highlands", "turquoise lagoon",
]
_LIGHT = ["sunrise glow", "golden hour", "blue hour", "starlight", "soft morning mist"]
_MOOD_FALLBACK = [
    "journey", "courage", "new beginning", "perseverance", "gratitude",
    "focus", "hope", "discipline", "freedom", "resilience",
]


def _combo_pool(subjects, year):
    """Cartesian pool shuffled deterministically by year. len >> 365."""
    from itertools import product
    # NOTE: mood excluded from pool now — mood comes from pillar (JSON).
    # subject x background x lighting still >> 365 (e.g. 5x12x5=300, 10x12x5=600)
    # If subjects list is small, pool is extended by index repetition (see pick_theme).
    pool = list(product(subjects, _BG, _LIGHT))
    rng = random.Random(f"ig-365-{year}")
    rng.shuffle(pool)
    return pool


def unique_fallback_quote(subject, background, lighting, mood, doy, year):
    """Deterministic fallback — always unique because it embeds day + combo."""
    import hashlib
    h = int(hashlib.sha256(f"{year}-{doy}".encode()).hexdigest(), 16)
    worries = [("worries", "wings"), ("fear", "fuel"), ("doubt", "direction"),
               ("noise", "clarity"), ("waiting", "wings"), ("limits", "lessons"),
               ("storms", "stories"), ("weight", "wonder")]
    w1, w2 = worries[(h // 7) % len(worries)]
    lessons = [
        "small steps lift you to endless horizons",
        "steady hearts outlast strong winds",
        "every mile begins with one brave rise",
        "quiet effort moves the highest peaks",
        "today's climb shapes tomorrow's view",
        "rise slow, shine far",
    ]
    lesson = lessons[(h // 13) % len(lessons)]
    tpls = [
        f"A {subject} over {background} at {lighting} reminds you: {lesson} [{mood}].",
        f"{lesson.capitalize()}, like a {subject} over {background} [{lighting} • {mood}].",
        f"Day {doy} of 365 — let a {subject} turn {w1} into {w2} above the {background} [{lighting} • {mood}].",
        f"Beyond the {background} at {lighting}, a {subject} carries {mood} forward.",
        f"Keep going: even a {subject} above {background} at {lighting} starts with first light [{mood}].",
    ]
    return tpls[h % len(tpls)]

def load_config():
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)

def today_seed():
    d = datetime.date.today()
    return d.timetuple().tm_yday, d.isoformat()

# ---- PILLAR-AWARE 365 engine ----
def load_365_quotes():
    """Load quotes_365.json (Day 1..365). Returns {day:int -> {quote:str, pillar:str}}."""
    p = ROOT / "quotes_365.json"
    try:
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        items = data.get("quotes") if isinstance(data, dict) else data
        out = {}
        for x in items:
            try:
                d = int(x.get("day"))
            except Exception:
                continue
            q = (x.get("quote") or "").strip()
            pillar = (x.get("pillar") or "").strip().lower()
            if q:
                out[d] = {"quote": q, "pillar": pillar}
        return out
    except Exception as e:
        print(f"[quotes] could not load quotes_365.json: {e}")
        return {}


def get_day_entry(bank, doy):
    """Day-of-year -> bank entry. Leap Dec 31 (366) reuses Day 365."""
    if not bank:
        return None
    key = doy if doy in bank else ((doy - 1) % 365) + 1
    return bank.get(key)


def pick_theme(cfg, for_date=None, pillar_override=None):
    """Deterministic 365-day unique theme, PILLAR-AWARE.
    mood = pillar from JSON (if given), else fallback pool mood.
    Returns (theme, seed, day_of_year, datestr, ctx).
    Same date -> same result; different dates in same year -> different combo.
    """
    d = for_date or datetime.date.today()
    day_of_year = d.timetuple().tm_yday
    datestr = d.isoformat()
    subjects = cfg.get("themes", ["inspiration"]) or ["inspiration"]
    pool = _combo_pool(subjects, d.year)
    # pool is (subject, background, lighting); cycle with stride so small
    # subject lists still give unique triples across 365 days
    subject, background, lighting = pool[(day_of_year - 1) % len(pool)]
    if len(pool) < 365:
        # extend uniqueness with deterministic background variant index
        variant = ((day_of_year - 1) // max(len(pool), 1)) + 1
        if variant > 1:
            background = f"{background} variant {variant}"
    if pillar_override:
        mood = pillar_override.strip().lower()
    else:
        mood = _MOOD_FALLBACK[(day_of_year - 1) % len(_MOOD_FALLBACK)]
    theme = f"{subject}, {background}, {lighting}, {mood}"
    seed = int(d.strftime("%Y%m%d"))
    ctx = {"subject": subject, "background": background, "lighting": lighting,
           "mood": mood, "pillar": mood, "year": d.year, "doy": day_of_year, "date": datestr}
    return theme, seed, day_of_year, datestr, ctx

def gen_image(cfg, theme, seed, ctx=None):
    w, h = cfg.get("width", 1080), cfg.get("height", 1350)
    tpl = cfg.get("image_prompt_template", "{theme}")
    niche = cfg.get("niche", "")
    ctx = ctx or {}
    doy = ctx.get("doy", "?")
    year = ctx.get("year", "")
    mood = ctx.get("mood", "")
    pillar = ctx.get("pillar", mood)
    try:
        prompt = tpl.format(theme=theme, niche=niche, day_of_year=doy,
                            date=ctx.get("date", ""), background=ctx.get("background", ""),
                            lighting=ctx.get("lighting", ""), mood=mood, pillar=pillar, year=year)
    except KeyError:
        prompt = tpl.replace("{theme}", theme).replace("{niche}", niche)
    # Force uniqueness + pillar grounding even if template ignores extra fields
    uniq = f", unique scene day {doy}/365 {year} {pillar}".strip()
    if uniq not in prompt:
        prompt = f"{prompt}{uniq}"
    # Ground visual mood in pillar
    if pillar and pillar.lower() not in prompt.lower():
        prompt = f"{prompt}, {pillar} mood"
    q = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{q}?width={w}&height={h}&seed={seed}&model=flux&nologo=true"
    print(f"[image] FREE model request: {prompt[:120]}... (pillar={pillar})")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "")
    if "image" not in ctype and len(r.content) < 20000:
        raise RuntimeError(f"Image model returned non-image: {r.text[:300]}")
    p = OUT / f"post-{datetime.date.today().isoformat()}.jpg"
    try:
        from PIL import Image
        import io as _io
        im = Image.open(_io.BytesIO(r.content)).convert("RGB")
        tw, th = w, h
        s = max(tw / im.width, th / im.height)
        im = im.resize((int(im.width * s + 0.5), int(im.height * s + 0.5)))
        x = (im.width - tw) // 2; y = (im.height - th) // 2
        im = im.crop((x, y, x + tw, y + th))
        im.save(p, "JPEG", quality=90)
    except Exception:
        p.write_bytes(r.content)
    print(f"[image] saved {p} ({p.stat().st_size//1024} KB)")
    return p, prompt

def gen_quote(cfg, theme, ctx=None):
    """365 strong quotes file first (QUOTE_SOURCE=file, default), live model optional.
    PILLAR-AWARE: returns (quote, pillar). ctx['pillar'] is set when bank hits.
    """
    ctx = ctx or {}
    doy = ctx.get("doy")
    year = ctx.get("year")
    source = os.getenv("QUOTE_SOURCE", "file").lower()
    if source in ("file", "365", "curated") and doy:
        bank = load_365_quotes()
        entry = get_day_entry(bank, doy)
        if entry:
            q, pillar = entry["quote"], entry.get("pillar", "")
            if pillar:
                ctx["pillar"] = pillar
                ctx["mood"] = pillar  # keep image/caption in sync
            print(f"[text] 365-bank Day {doy} [{pillar}]: {q}")
            return q, pillar
        print("[text] quotes_365.json missing, falling back.")
    prompt = f"Write ONE short original motivational quote (max 20 words) about: {theme}. No hashtags, no quotes around it, just the quote."
    try:
        url = "https://text.pollinations.ai/" + urllib.parse.quote(prompt) + "?model=openai"
        r = requests.get(url, timeout=60, headers={"Accept": "text/plain"})
        r.raise_for_status()
        q = r.text.strip().strip('"').strip()
        if 5 < len(q) < 300 and "pollinations" not in q.lower():
            if doy and year and _quote_already_used(q, year):
                q = f"{q} [Day {doy}/365]"
            print(f"[text] FREE model quote: {q}")
            pillar = ctx.get("pillar", "")
            return q, pillar
        raise ValueError("bad response, using fallback")
    except Exception as e:
        print(f"[text] model unavailable ({e}), using unique fallback quote.")
        pillar = ctx.get("pillar", ctx.get("mood", ""))
        if doy and year:
            return unique_fallback_quote(ctx.get("subject", theme),
                                          ctx.get("background", ""),
                                          ctx.get("lighting", ""),
                                          ctx.get("mood", ""), doy, year), pillar
        random.seed(datetime.date.today().strftime("%Y%m%d"))
        return random.choice(FALLBACK_QUOTES), pillar


def _quote_already_used(quote, year):
    """Check output/posted.log for duplicate quote this year."""
    try:
        p = OUT / "posted.log"
        if not p.exists():
            return False
        prefix = str(year)
        for line in p.read_text(encoding="utf-8").splitlines()[-400:]:
            try:
                j = json.loads(line)
            except Exception:
                continue
            if str(j.get("date", "")).startswith(prefix) and j.get("quote") == quote:
                return True
    except Exception:
        pass
    return False

def build_caption(cfg, quote, day_of_year, ctx=None):
    """Viral hashtag switcher: base + pillar-specific + rotating viral + day tag.
    Keeps 10-12 tags max, deterministic rotation to avoid shadowban."""
    import random as _random
    ctx = ctx or {}
    pillar = (ctx.get("pillar") or ctx.get("mood") or "").strip().lower().replace(" ", "")
    base = list(cfg.get("base_hashtags", cfg.get("hashtags", [])))
    pillar_map = cfg.get("pillar_hashtags", {}) or {}
    # 1) pillar tags (2-3 of them, deterministic by day so same pillar varies)
    ptags = list(pillar_map.get(pillar, [])) if pillar else []
    if ptags:
        _random.Random(f"pillar-{pillar}-{day_of_year}").shuffle(ptags)
        ptags = ptags[:3]
    # 2) viral rotating pool (5 per post, deterministic — never same set 2 days in a row)
    pool = list(cfg.get("viral_pool", []))
    n_viral = int(cfg.get("viral_per_post", 5))
    vtags = []
    if pool:
        _random.Random(f"viral-{ctx.get('year', '')}-{day_of_year}").shuffle(pool)
        vtags = pool[:n_viral]
    # 3) keyword bonus from quote text (adds 1 niche tag when matched)
    ql = quote.lower()
    keyword_tags = {
        "fear": "#fearless", "anxiet": "#anxietyrelief", "money": "#moneymindset",
        "funds": "#moneymindset", "morning": "#morningmotivation", "night": "#nightthoughts",
        "fail": "#failforward", "trust": "#trusttheprocess", "god": "#faith", "pray": "#faith",
        "habit": "#habits", "gym": "#gymmotivation", "workout": "#gymmotivation",
        "focus": "#focus", "dream": "#dreambig", "thank": "#gratitude",
    }
    bonus = []
    for kw, tag in keyword_tags.items():
        if kw in ql and tag not in ptags and tag not in vtags:
            bonus.append(tag)
            break  # max 1 bonus to stay under limit
    # 4) assemble: base + pillar + viral + bonus + day tag, deduped, max 12
    tags_list = []
    for t in base + ptags + vtags + bonus + [f"#day{day_of_year}"]:
        tl = t.lower()
        if tl not in [x.lower() for x in tags_list]:
            tags_list.append(t)
    tags_list = tags_list[:12]
    tags = " ".join(tags_list)
    print(f"[hashtags] pillar={pillar} -> {tags}")
    tpl = cfg.get("caption_template", "{quote}\n{hashtags}\n{pillar}")
    try:
        cap = tpl.format(quote=quote, hashtags=tags, pillar=pillar,
                         day_of_year=day_of_year,
                         date=ctx.get("date", datetime.date.today().isoformat()))
    except KeyError:
        cap = f"{quote}\n{tags}"
    prefix = os.getenv("CAPTION_PREFIX", "").strip()
    if prefix and not cap.startswith(prefix):
        cap = f"{prefix} {cap}" if prefix.endswith("]") else f"{prefix}{cap}"
    return cap

def upload_public(image_path: pathlib.Path) -> str:
    """Instagram API needs a PUBLIC image URL.
    Order: IMGBB -> litterbox -> tmpfiles -> uguu -> catbox -> 0x0
    """
    UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    ibkey = os.getenv("IMGBB_API_KEY", "").strip()
    if ibkey:
        try:
            import base64
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            r = requests.post("https://api.imgbb.com/1/upload",
                              data={"key": ibkey, "image": b64, "name": image_path.stem},
                              headers=UA, timeout=60)
            r.raise_for_status()
            j = r.json()
            url = (j.get("data") or {}).get("url") or (j.get("data") or {}).get("display_url")
            if url and url.startswith("https://"):
                print(f"[upload] imgbb: {url}")
                return url
            print(f"[upload] imgbb bad response: {str(j)[:300]}")
        except Exception as e:
            print(f"[upload] imgbb failed: {e}")
    try:
        with open(image_path, "rb") as f:
            r = requests.post("https://litterbox.catbox.moe/resources/internals/api.php",
                              data={"reqtype": "fileupload", "time": "72h"},
                              files={"fileToUpload": (image_path.name, f, "image/jpeg")},
                              headers=UA, timeout=60)
        r.raise_for_status()
        url = r.text.strip()
        if url.startswith("https://"):
            print(f"[upload] litterbox: {url}")
            return url
        print(f"[upload] litterbox bad response: {url[:200]}")
    except Exception as e:
        print(f"[upload] litterbox failed: {e}")
    try:
        with open(image_path, "rb") as f:
            r = requests.post("https://tmpfiles.org/api/v1/upload",
                              files={"file": (image_path.name, f, "image/jpeg")},
                              headers=UA, timeout=60)
        r.raise_for_status()
        j = r.json()
        url = (j.get("data") or {}).get("url", "")
        if url.startswith("https://tmpfiles.org/"):
            direct = url.replace("https://tmpfiles.org/", "https://tmpfiles.org/dl/")
            print(f"[upload] tmpfiles: {direct}")
            return direct
        print(f"[upload] tmpfiles bad response: {str(j)[:300]}")
    except Exception as e:
        print(f"[upload] tmpfiles failed: {e}")
    try:
        with open(image_path, "rb") as f:
            r = requests.post("https://uguu.se/upload.php",
                              files={"files[]": (image_path.name, f, "image/jpeg")},
                              headers=UA, timeout=60)
        r.raise_for_status()
        j = r.json()
        files = j.get("files") or []
        url = files[0].get("url") if files else ""
        if url and url.startswith("https://"):
            print(f"[upload] uguu: {url}")
            return url
        print(f"[upload] uguu bad response: {r.text[:300]}")
    except Exception as e:
        print(f"[upload] uguu failed: {e}")
    for host in ["catbox", "0x0"]:
        try:
            if host == "catbox":
                with open(image_path, "rb") as f:
                    r = requests.post("https://catbox.moe/user/api.php",
                                      data={"reqtype": "fileupload", "time": "72h"},
                                      files={"fileToUpload": (image_path.name, f, "image/jpeg")},
                                      headers=UA, timeout=60)
                r.raise_for_status()
                url = r.text.strip()
                if url.startswith("https://"):
                    print(f"[upload] catbox: {url}")
                    return url
            else:
                with open(image_path, "rb") as f:
                    r = requests.post("https://0x0.st", files={"file": f}, headers=UA, timeout=60)
                r.raise_for_status()
                url = r.text.strip()
                if url.startswith("https://"):
                    print(f"[upload] 0x0.st: {url}")
                    return url
        except Exception as e:
            print(f"[upload] {host} failed: {e}")
    raise RuntimeError("All free uploads failed. FIX: add free IMGBB_API_KEY secret (https://api.imgbb.com/) — most reliable from GitHub.")

def ig_publish(image_url: str, caption: str, ig_user_id: str, token: str):
    r = requests.post(f"{BASE}/{ig_user_id}/media",
                      data={"image_url": image_url, "caption": caption,
                            "access_token": token}, timeout=60)
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"IG container failed: HTTP {r.status_code} {r.text[:500]}")
    if "id" not in j:
        raise RuntimeError(f"IG container error: {j}")
    creation_id = j["id"]
    print(f"[ig] container {creation_id} created, waiting for processing...")
    for i in range(12):
        time.sleep(10)
        st = requests.get(f"{BASE}/{creation_id}",
                          params={"fields": "status_code", "access_token": token},
                          timeout=30).json()
        code = st.get("status_code")
        print(f"  status check {i+1}: {code}")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"IG media processing failed: {st}")
    r2 = requests.post(f"{BASE}/{ig_user_id}/media_publish",
                       data={"creation_id": creation_id, "access_token": token}, timeout=60)
    j2 = r2.json()
    if "id" not in j2:
        raise RuntimeError(f"IG publish error: {j2}")
    print(f"[ig] ✅ PUBLISHED media id={j2['id']}")
    return j2["id"]

def write_preview(caption, image_path):
    (OUT / f"caption-{datetime.date.today().isoformat()}.txt").write_text(caption, encoding="utf-8")
    html = f"""<html><body style="font-family:sans-serif;max-width:600px;margin:auto">
<h2>Dry-run preview — {datetime.date.today().isoformat()}</h2>
<img src="{image_path.name}" style="width:100%;border-radius:12px">
<pre style="white-space:pre-wrap;background:#f5f5f5;padding:12px;border-radius:8px">{caption}</pre>
</body></html>"""
    (OUT / "preview.html").write_text(html, encoding="utf-8")

def render_quote_overlay(image_path: pathlib.Path, quote: str, ctx=None, cfg=None) -> pathlib.Path:
    """Burn the quote onto the image with clean IG formatting (PIL only, offline)."""
    if os.getenv("QUOTE_ON_IMAGE", "true").lower() in ("0", "false", "no", "off"):
        return image_path
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
        import textwrap
    except Exception as e:
        print(f"[overlay] PIL missing, skipping text-on-image: {e}")
        return image_path
    try:
        ctx = ctx or {}
        cfg = cfg or {}
        doy = ctx.get("doy", datetime.date.today().timetuple().tm_yday)
        mood = (ctx.get("pillar") or ctx.get("mood") or "").upper()
        handle = cfg.get("handle", "")
        footer = f"DAY {doy}/365" + (f"  •  {mood}" if mood else "") + (f"  •  {handle}" if handle else "")
        im = Image.open(image_path).convert("RGB")
        W, H = im.size
        scrim_h = int(H * 0.52)
        scrim = Image.new("L", (1, scrim_h), 0)
        for y in range(scrim_h):
            scrim.putpixel((0, y), int(165 * (y / max(scrim_h - 1, 1)) ** 1.4))
        scrim = scrim.resize((W, scrim_h))
        black = Image.new("RGB", (W, scrim_h), (0, 0, 0))
        im.paste(Image.composite(black, im.crop((0, H - scrim_h, W, H)), scrim), (0, H - scrim_h))
        draw = ImageDraw.Draw(im)

        def _font(bold, size):
            import glob
            cands = [
                f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
                f"/usr/share/fonts/TTF/DejaVuSans{'-Bold' if bold else ''}.ttf",
                f"/usr/share/fonts/truetype/liberation/LiberationSans{'-Bold' if bold else '-Regular'}.ttf",
                f"/usr/share/fonts/truetype/noto/NotoSans{'-Bold' if bold else '-Regular'}.ttf",
            ]
            try:
                extra = sorted(glob.glob("/usr/share/fonts/**/*.ttf", recursive=True))
                pref = [p for p in extra if ("Bold" if bold else "Regular") in p and ("Sans" in p or "Noto" in p or "Liber" in p)]
                cands += pref[:10]
            except Exception:
                pass
            for p in cands:
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    continue
            return ImageFont.load_default()

        margin = int(W * 0.08)
        max_w = W - 2 * margin
        qsize = int(W * 0.057)
        wrapped, qfont = [quote], _font(True, qsize)
        for _ in range(6):
            chars = max(int(max_w / max(qsize * 0.52, 1)), 12)
            wrapped = []
            for para in quote.split("\n"):
                wrapped += textwrap.wrap(para, width=chars) or [""]
            qfont = _font(True, qsize)
            try:
                real_w = max(draw.textlength(l, font=qfont) for l in wrapped) if wrapped else 0
                if real_w > max_w and qsize > 34:
                    qsize -= 6
                    continue
            except Exception:
                pass
            lh = int(qsize * 1.32)
            if lh * len(wrapped) <= int(H * 0.34) or qsize <= 34:
                break
            qsize -= 6
        lh = int(qsize * 1.32)
        block_h = lh * len(wrapped)
        mark_font = _font(True, int(W * 0.12))
        accent = (255, 209, 102)
        footer_font = _font(False, int(W * 0.030))
        footer_h = int(W * 0.030 * 1.6)
        y0 = H - int(H * 0.06) - footer_h - block_h - int(W * 0.10)
        draw.rectangle([margin, y0 - int(W * 0.025), margin + int(W * 0.14), y0 - int(W * 0.025) + 5], fill=accent)
        try:
            draw.text((margin, y0 - int(W * 0.105)), "\u201c", font=mark_font, fill=accent)
        except Exception:
            pass
        y = y0
        for line in wrapped:
            draw.text((margin + 2, y + 2), line, font=qfont, fill=(0, 0, 0))
            draw.text((margin, y), line, font=qfont, fill=(255, 255, 255))
            y += lh
        fy = H - int(H * 0.055)
        draw.text((margin + 1, fy + 1), footer, font=footer_font, fill=(0, 0, 0))
        draw.text((margin, fy), footer, font=footer_font, fill=(240, 240, 240))
        im.save(image_path, "JPEG", quality=92)
        print(f"[overlay] quote burned onto {image_path.name} ({len(wrapped)} lines, size {qsize}) pillar={mood}")
        return image_path
    except Exception as e:
        print(f"[overlay] failed ({e}), posting clean background image.")
        return image_path


def validate_token(token):
    """Fail fast with a clear message if the IG token is expired/invalid."""
    r = requests.get(f"{BASE}/me", params={"fields": "id", "access_token": token},
                       timeout=20).json()
    if "error" in r:
        err = r["error"]
        raise RuntimeError(
            f"IG token invalid/expired: {err.get('message')} "
            f"[code {err.get('code')}/{err.get('error_subcode')}] - "
            "Generate a new long-lived token and update IG_ACCESS_TOKEN secret."
        )
    return True


def verify_365(cfg, year):
    """Offline check: 365 days must give 365 unique themes/quotes/captions/prompts (pillar-aware)."""
    seen_t, seen_q, seen_c, seen_p = set(), set(), set(), set()
    pillars_used = set()
    n = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
    bank = load_365_quotes()
    d = datetime.date(year, 1, 1)
    for _ in range(n):
        entry = get_day_entry(bank, d.timetuple().tm_yday)
        pillar = (entry.get("pillar") if entry else "") or _MOOD_FALLBACK[(d.timetuple().tm_yday - 1) % len(_MOOD_FALLBACK)]
        theme, seed, doy, ds, ctx = pick_theme(cfg, for_date=d, pillar_override=pillar)
        pillars_used.add(pillar)
        tpl = cfg.get("image_prompt_template", "{theme}")
        try:
            base = tpl.format(theme=theme, niche=cfg.get("niche", ""),
                              day_of_year=doy, date=ds, background=ctx["background"],
                              lighting=ctx["lighting"], mood=ctx["mood"],
                              pillar=ctx["pillar"], year=year)
        except KeyError:
            base = tpl.replace("{theme}", theme)
        img_prompt = f"{base}, unique scene day {doy}/365 {year} {ctx['pillar']}"
        q = entry["quote"] if entry else unique_fallback_quote(
            ctx["subject"], ctx["background"], ctx["lighting"], ctx["mood"], doy, year)
        cap = build_caption(cfg, q, doy, ctx)
        seen_t.add(theme); seen_q.add(q); seen_c.add(cap); seen_p.add(img_prompt)
        d += datetime.timedelta(days=1)
    return {"days": n, "unique_themes": len(seen_t), "unique_quotes": len(seen_q),
            "unique_captions": len(seen_c), "unique_image_prompts": len(seen_p),
            "pillars": sorted(pillars_used),
            "all_unique": len(seen_t) == len(seen_q) == len(seen_c) == len(seen_p) == n}


def main():
    if "--verify-365" in sys.argv:
        cfg = load_config()
        idx = sys.argv.index("--verify-365")
        year = int(sys.argv[idx + 1]) if len(sys.argv) > idx + 1 and sys.argv[idx + 1].isdigit() else datetime.date.today().year
        res = verify_365(cfg, year)
        print(res)
        return 0 if res["all_unique"] else 1
    cfg = load_config()

    # 1) PILLAR FIRST: load today's quote entry to drive theme/image/caption
    bank = load_365_quotes()
    today = datetime.date.today()
    doy_now = today.timetuple().tm_yday
    entry = get_day_entry(bank, doy_now)
    pillar_today = (entry.get("pillar") if entry else "") or ""
    if pillar_today:
        print(f"[pillar] Day {doy_now} pillar from JSON: {pillar_today}")
    else:
        print(f"[pillar] WARNING: no pillar found for Day {doy_now}, using fallback mood")

    theme, seed, day_of_year, datestr, ctx = pick_theme(cfg, pillar_override=pillar_today or None)
    # gen_quote re-syncs ctx pillar from bank (authoritative)
    print(f"=== IG auto-post {datestr} | theme: {theme} ===")
    print(f"[365] Day {day_of_year} ctx={ctx}")

    ig_id = os.getenv("IG_USER_ID", "").strip()
    token = os.getenv("IG_ACCESS_TOKEN", "").strip()
    dry = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes") or not (ig_id and token)
    if not dry:
        validate_token(token)

    image_path, used_prompt = gen_image(cfg, theme, seed, ctx)
    quote, pillar = gen_quote(cfg, theme, ctx)
    # ensure ctx carries final pillar for caption/overlay/log
    if pillar:
        ctx["pillar"] = pillar
        ctx["mood"] = pillar
    image_path = render_quote_overlay(image_path, quote, ctx, cfg)
    caption = build_caption(cfg, quote, day_of_year, ctx)
    write_preview(caption, image_path)

    if dry:
        print("\n--- DRY-RUN (no IG creds) ---")
        print(f"[pillar={ctx.get('pillar')}] {quote}")
        print(caption)
        print(f"\nPreview: output/preview.html + {image_path.name}")
        print("To go live: fill IG_USER_ID + IG_ACCESS_TOKEN (see SETUP.md), then DRY_RUN=false")
        return 0

    print("[live] uploading + publishing to Instagram...")
    public_url = os.getenv("IMAGE_URL_OVERRIDE", "").strip() or upload_public(image_path)
    media_id = ig_publish(public_url, caption, ig_id, token)
    with open(OUT / "posted.log", "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": datestr, "theme": theme, "pillar": ctx.get("pillar"),
                            "quote": quote, "caption": caption,
                            "image_url": public_url, "media_id": media_id}) + "\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())

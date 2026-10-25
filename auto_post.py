"""
Instagram Auto-Poster — daily 1 post, 100% free stack (develop: 365-day unique).

Flow:
  1. Pick today's theme (deterministic 365-day plan, no repeat within a year)
  2. Generate image with FREE model: Pollinations.ai / Flux (no API key)
  3. Generate quote/caption with FREE model: Pollinations text (no API key)
  4. If IG creds present -> upload image to public URL + publish via Graph API
     Else -> DRY-RUN: save to output/ for preview (works immediately, zero setup)

Env (see .env.example):
  IG_USER_ID, IG_ACCESS_TOKEN, DRY_RUN (auto=true if creds missing)
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

# ---- 365-day unique engine (deterministic, no repeats within a year) ----
_BG = [
    "misty mountains", "golden desert", "emerald forest", "arctic aurora",
    "tropical coast", "monsoon valley", "alpine peak", "red canyon",
    "lavender field", "starry night desert", "autumn highlands", "turquoise lagoon",
]
_LIGHT = ["sunrise glow", "golden hour", "blue hour", "starlight", "soft morning mist"]
_MOOD = [
    "journey", "courage", "new beginning", "perseverance", "gratitude",
    "focus", "hope", "discipline", "freedom", "resilience",
]


def _combo_pool(subjects, year):
    """Cartesian pool shuffled deterministically by year. len >> 365."""
    from itertools import product
    pool = list(product(subjects, _BG, _LIGHT, _MOOD))
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
    # Every template embeds subject+background+lighting+mood so that
    # unique theme => unique quote. Day is in template 3; others carry
    # lighting+mood which together with subject+background is unique.
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

def pick_theme(cfg, for_date=None):
    """Deterministic 365-day unique theme.
    Returns (theme, seed, day_of_year, datestr, ctx) where ctx has
    subject/background/lighting/mood/year for image+quote builders.
    Same date -> same result; different dates in same year -> different."""
    d = for_date or datetime.date.today()
    day_of_year = d.timetuple().tm_yday
    datestr = d.isoformat()
    subjects = cfg.get("themes", ["inspiration"]) or ["inspiration"]
    pool = _combo_pool(subjects, d.year)
    subject, background, lighting, mood = pool[(day_of_year - 1) % len(pool)]
    theme = f"{subject}, {background}, {lighting}, {mood}"
    seed = int(d.strftime("%Y%m%d"))
    ctx = {"subject": subject, "background": background, "lighting": lighting,
           "mood": mood, "year": d.year, "doy": day_of_year, "date": datestr}
    return theme, seed, day_of_year, datestr, ctx

def gen_image(cfg, theme, seed, ctx=None):
    w, h = cfg.get("width", 1080), cfg.get("height", 1350)
    tpl = cfg.get("image_prompt_template", "{theme}")
    niche = cfg.get("niche", "")
    ctx = ctx or {}
    doy = ctx.get("doy", "?")
    year = ctx.get("year", "")
    mood = ctx.get("mood", "")
    # Build base prompt tolerantly (template may only have {theme}/{niche})
    try:
        prompt = tpl.format(theme=theme, niche=niche, day_of_year=doy,
                            date=ctx.get("date", ""), background=ctx.get("background", ""),
                            lighting=ctx.get("lighting", ""), mood=mood, year=year)
    except KeyError:
        prompt = tpl.replace("{theme}", theme).replace("{niche}", niche)
    # Force uniqueness even if template ignores extra fields
    uniq = f", unique scene day {doy}/365 {year} {mood}".strip()
    if uniq not in prompt:
        prompt = f"{prompt}{uniq}"
    q = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{q}?width={w}&height={h}&seed={seed}&model=flux&nologo=true"
    print(f"[image] FREE model request: {prompt[:90]}...")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "")
    if "image" not in ctype and len(r.content) < 20000:
        raise RuntimeError(f"Image model returned non-image: {r.text[:300]}")
    p = OUT / f"post-{datetime.date.today().isoformat()}.jpg"
    # Normalize to exact IG size (crop-fit) so API never rejects aspect ratio
    try:
        from PIL import Image
        import io as _io
        im = Image.open(_io.BytesIO(r.content)).convert("RGB")
        tw, th = w, h
        # cover-fit: scale then center-crop
        s = max(tw / im.width, th / im.height)
        im = im.resize((int(im.width * s + 0.5), int(im.height * s + 0.5)))
        x = (im.width - tw) // 2; y = (im.height - th) // 2
        im = im.crop((x, y, x + tw, y + th))
        im.save(p, "JPEG", quality=90)
    except Exception:
        p.write_bytes(r.content)
    print(f"[image] saved {p} ({p.stat().st_size//1024} KB)")
    return p, prompt

def load_365_quotes():
    """Load quotes_365.json (Day 1..365) if present. Returns {day:int -> quote:str}."""
    p = ROOT / "quotes_365.json"
    try:
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        items = data.get("quotes") if isinstance(data, dict) else data
        return {int(x.get("day")): x.get("quote", "").strip() for x in items if x.get("quote")}
    except Exception as e:
        print(f"[quotes] could not load quotes_365.json: {e}")
        return {}


def gen_quote(cfg, theme, ctx=None):
    """365 strong quotes file first (QUOTE_SOURCE=file, default), live model optional."""
    ctx = ctx or {}
    doy = ctx.get("doy")
    year = ctx.get("year")
    source = os.getenv("QUOTE_SOURCE", "file").lower()
    if source in ("file", "365", "curated") and doy:
        bank = load_365_quotes()
        # day-of-year maps directly; leap Dec 31 (366) reuses Day 365 bank entry
        q = bank.get(doy) or bank.get(((doy - 1) % 365) + 1)
        if q:
            print(f"[text] 365-bank Day {doy}: {q}")
            return q
        print("[text] quotes_365.json missing, falling back.")
    prompt = f"Write ONE short original motivational quote (max 20 words) about: {theme}. No hashtags, no quotes around it, just the quote."
    try:
        url = "https://text.pollinations.ai/" + urllib.parse.quote(prompt) + "?model=openai"
        r = requests.get(url, timeout=60, headers={"Accept": "text/plain"})
        r.raise_for_status()
        q = r.text.strip().strip('"').strip()
        # guard against long/error responses
        if 5 < len(q) < 300 and "pollinations" not in q.lower():
            # Dedup guard: if this exact quote was already posted this year, vary it
            if doy and year and _quote_already_used(q, year):
                q = f"{q} [Day {doy}/365]"
            print(f"[text] FREE model quote: {q}")
            return q
        raise ValueError("bad response, using fallback")
    except Exception as e:
        print(f"[text] model unavailable ({e}), using unique fallback quote.")
        if doy and year:
            return unique_fallback_quote(ctx.get("subject", theme),
                                          ctx.get("background", ""),
                                          ctx.get("lighting", ""),
                                          ctx.get("mood", ""), doy, year)
        random.seed(datetime.date.today().strftime("%Y%m%d"))
        return random.choice(FALLBACK_QUOTES)


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
    tags = " ".join(cfg.get("hashtags", []))
    # Always append unique day tag so captions can never repeat within a year
    day_tag = f"#day{day_of_year}"
    if day_tag not in tags:
        tags = (tags + f" {day_tag}").strip()
    tpl = cfg.get("caption_template", "{quote}\n{hashtags}")
    cap = tpl.format(quote=quote, hashtags=tags,
                      day_of_year=day_of_year,
                      date=(ctx or {}).get("date", datetime.date.today().isoformat()))
    # Optional prefix for develop runs on the SAME IG account (env CAPTION_PREFIX="[DEV] ")
    prefix = os.getenv("CAPTION_PREFIX", "").strip()
    if prefix and not cap.startswith(prefix):
        cap = f"{prefix} {cap}" if prefix.endswith("]") else f"{prefix}{cap}"
    return cap

def _is_ig_fetchable(url: str) -> bool:
    """IG needs: https + image extension + 200 + Content-Type: image/*.

    Simulates the IG crawler. Used to reject viewer-pages / blocked hosts
    BEFORE calling the Graph API (avoids 9004 / 2207052).
    """
    try:
        if not url.startswith("https://"):
            return False
        # IG requires the URL to look like a file
        if not url.split("?")[0].lower().endswith((".jpg", ".jpeg", ".png")):
            print(f"[upload-check] reject (no image ext): {url}")
            return False
        UA = {"User-Agent": "facebookexternalhit/1.1"}
        r = requests.head(url, headers=UA, timeout=20, allow_redirects=True)
        ctype = r.headers.get("Content-Type", "")
        ok = r.status_code == 200 and "image" in ctype
        print(f"[upload-check] {url} -> {r.status_code} {ctype} {'OK' if ok else 'FAIL'}")
        if not ok:
            # HEAD sometimes lies, confirm with GET
            r2 = requests.get(url, headers=UA, timeout=20, stream=True)
            ctype2 = r2.headers.get("Content-Type", "")
            ok = r2.status_code == 200 and "image" in ctype2
            print(f"[upload-check-retry] {r2.status_code} {ctype2} {'OK' if ok else 'FAIL'}")
            try:
                r2.close()
            except Exception:
                pass
        return ok
    except Exception as e:
        print(f"[upload-check] {url} FAIL: {e}")
        return False


def _imgbb_direct(j: dict) -> str:
    """Prefer true raw file, NOT viewer page.
    ImgBB: data.image.url > data.display_url > data.url (viewer page last).
    """
    d = j.get("data") or {}
    return (
        (d.get("image") or {}).get("url")
        or d.get("display_url")
        or d.get("url")
        or ""
    )

def upload_public(image_path: pathlib.Path) -> str:
    """Instagram API needs a PUBLIC image URL that the IG crawler can fetch.

    FIX for 9004/2207052 "Only photo or video can be accepted":
    - old code trusted first upload success (imgbb i.ibb.co) even when IG
      gets HTML/blocked response instead of image bytes.
    - new code verifies each URL as IG would (facebookexternalhit + image
      Content-Type) and only returns a VERIFIED url.
    Order: catbox (files.catbox.moe, most IG-compatible) -> 0x0.st ->
           imgbb-direct -> litterbox 72h -> uguu -> tmpfiles.
    """
    UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    candidates = []

    def try_upload(name, fn):
        try:
            url = fn()
            url = (url or "").strip()
            print(f"[upload] {name} returned: {url}")
            if url.startswith("https://"):
                if _is_ig_fetchable(url):
                    print(f"[upload] {name} VERIFIED: {url}")
                    return url
                candidates.append(url)
            else:
                print(f"[upload] {name} bad response: {url[:200]}")
        except Exception as e:
            print(f"[upload] {name} failed: {e}")
        return None

    # 1) catbox permanent — most IG-compatible (returns https://files.catbox.moe/xxx.jpg)
    def _catbox():
        with open(image_path, "rb") as f:
            r = requests.post("https://catbox.moe/user/api.php",
                              data={"reqtype": "fileupload"},
                              files={"fileToUpload": (image_path.name, f, "image/jpeg")},
                              headers=UA, timeout=60)
        r.raise_for_status()
        return r.text.strip()
    hit = try_upload("catbox", _catbox)
    if hit:
        return hit

    # 2) 0x0.st — raw bytes, correct Content-Type
    def _zx():
        with open(image_path, "rb") as f:
            r = requests.post("https://0x0.st", files={"file": f}, headers=UA, timeout=60)
        r.raise_for_status()
        return r.text.strip()
    hit = try_upload("0x0.st", _zx)
    if hit:
        return hit

    # 3) ImgBB — free key from https://api.imgbb.com/, add as secret IMGBB_API_KEY
    ibkey = os.getenv("IMGBB_API_KEY", "").strip()
    if ibkey:
        def _ib():
            import base64
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            r = requests.post("https://api.imgbb.com/1/upload",
                              data={"key": ibkey, "image": b64, "name": image_path.stem},
                              headers=UA, timeout=60)
            r.raise_for_status()
            return _imgbb_direct(r.json())
        hit = try_upload("imgbb", _ib)
        if hit:
            return hit
    else:
        print("[upload] imgbb skipped (no IMGBB_API_KEY)")

    # 4) litterbox (catbox temp host, 72h)
    def _litter():
        with open(image_path, "rb") as f:
            r = requests.post("https://litterbox.catbox.moe/resources/internals/api.php",
                              data={"reqtype": "fileupload", "time": "72h"},
                              files={"fileToUpload": (image_path.name, f, "image/jpeg")},
                              headers=UA, timeout=60)
        r.raise_for_status()
        return r.text.strip()
    hit = try_upload("litterbox", _litter)
    if hit:
        return hit

    # 5) uguu.se — keyless
    def _uguu():
        with open(image_path, "rb") as f:
            r = requests.post("https://uguu.se/upload.php",
                              files={"files[]": (image_path.name, f, "image/jpeg")},
                              headers=UA, timeout=60)
        r.raise_for_status()
        j = r.json()
        files = j.get("files") or []
        return files[0].get("url") if files else ""
    hit = try_upload("uguu", _uguu)
    if hit:
        return hit

    # 6) tmpfiles.org — keyless, often NOT IG-fetchable, last resort only
    def _tmp():
        with open(image_path, "rb") as f:
            r = requests.post("https://tmpfiles.org/api/v1/upload",
                              files={"file": (image_path.name, f, "image/jpeg")},
                              headers=UA, timeout=60)
        r.raise_for_status()
        j = r.json()
        url = (j.get("data") or {}).get("url", "")
        if url.startswith("https://tmpfiles.org/"):
            return url.replace("https://tmpfiles.org/", "https://tmpfiles.org/dl/")
        return url
    hit = try_upload("tmpfiles", _tmp)
    if hit:
        return hit

    if candidates:
        # last resort: return first candidate even if check failed (old behavior)
        print(f"[upload] WARNING: no URL passed IG-check, using {candidates[0]} anyway (likely 9004)")
        return candidates[0]
    raise RuntimeError("All free uploads failed/uncrawlable. FIX: check network + set IMGBB_API_KEY (https://api.imgbb.com/). Test URL with: curl -I -A 'facebookexternalhit/1.1' <url>")

def ig_publish(image_url: str, caption: str, ig_user_id: str, token: str):
    # 1. create container
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
    # 2. wait until READY (IG processes image async)
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
    # 3. publish
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
    """Burn the quote onto the image with clean IG formatting (PIL only, offline).
    Returns image_path (overwritten in place). Disable with QUOTE_ON_IMAGE=false.
    """
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
        mood = (ctx.get("mood", "") or "").upper()
        handle = cfg.get("handle", "")  # optional e.g. "@mydaily.rise" in config.yaml
        footer = f"DAY {doy}/365" + (f"  •  {mood}" if mood else "") + (f"  •  {handle}" if handle else "")

        im = Image.open(image_path).convert("RGB")
        W, H = im.size
        # --- bottom gradient scrim for readability ---
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
            # any Sans bold/regular as last resort (offline runners vary)
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

        # --- fit quote size (size-based wrap, works even with fallback font) ---
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
            # refine with real measurement when a scalable font loaded
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
        # opening “ mark
        mark_font = _font(True, int(W * 0.12))
        accent = (255, 209, 102)
        # --- layout: quote block above footer ---
        footer_font = _font(False, int(W * 0.030))
        footer_h = int(W * 0.030 * 1.6)
        y0 = H - int(H * 0.06) - footer_h - block_h - int(W * 0.10)
        # accent line
        draw.rectangle([margin, y0 - int(W * 0.025), margin + int(W * 0.025) + int(W * 0.14) - int(W * 0.025), y0 - int(W * 0.025) + 5], fill=accent)
        try:
            draw.text((margin, y0 - int(W * 0.105)), "\u201c", font=mark_font, fill=accent)
        except Exception:
            pass
        y = y0
        for line in wrapped:
            # shadow then white text for pop on any background
            draw.text((margin + 2, y + 2), line, font=qfont, fill=(0, 0, 0))
            draw.text((margin, y), line, font=qfont, fill=(255, 255, 255))
            y += lh
        # footer
        fy = H - int(H * 0.055)
        draw.text((margin + 1, fy + 1), footer, font=footer_font, fill=(0, 0, 0))
        draw.text((margin, fy), footer, font=footer_font, fill=(240, 240, 240))
        im.save(image_path, "JPEG", quality=92)
        print(f"[overlay] quote burned onto {image_path.name} ({len(wrapped)} lines, size {qsize})")
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
    """Offline check: 365 days must give 365 unique themes/quotes/captions/prompts."""
    seen_t, seen_q, seen_c, seen_p = set(), set(), set(), set()
    n = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
    d = datetime.date(year, 1, 1)
    for _ in range(n):
        theme, seed, doy, ds, ctx = pick_theme(cfg, for_date=d)
        tpl = cfg.get("image_prompt_template", "{theme}")
        try:
            base = tpl.format(theme=theme, niche=cfg.get("niche", ""),
                              day_of_year=doy, date=ds, background=ctx["background"],
                              lighting=ctx["lighting"], mood=ctx["mood"], year=year)
        except KeyError:
            base = tpl.replace("{theme}", theme)
        img_prompt = f"{base}, unique scene day {doy}/365 {year} {ctx['mood']}"
        q = unique_fallback_quote(ctx["subject"], ctx["background"],
                                  ctx["lighting"], ctx["mood"], doy, year)
        tags = " ".join(cfg.get("hashtags", [])) + f" #day{doy}"
        cap = cfg.get("caption_template", "{quote}\n{hashtags}").format(
            quote=q, hashtags=tags, day_of_year=doy, date=ds)
        seen_t.add(theme); seen_q.add(q); seen_c.add(cap); seen_p.add(img_prompt)
        d += datetime.timedelta(days=1)
    return {"days": n, "unique_themes": len(seen_t), "unique_quotes": len(seen_q),
            "unique_captions": len(seen_c), "unique_image_prompts": len(seen_p),
            "all_unique": len(seen_t) == len(seen_q) == len(seen_c) == len(seen_p) == n}


def main():
    if "--verify-365" in sys.argv:
        cfg = load_config()
        year = int(sys.argv[sys.argv.index("--verify-365") + 1]) if len(sys.argv) > 2 else datetime.date.today().year
        res = verify_365(cfg, year)
        print(res)
        return 0 if res["all_unique"] else 1
    cfg = load_config()
    theme, seed, day_of_year, datestr, ctx = pick_theme(cfg)
    print(f"=== IG auto-post {datestr} | theme: {theme} ===")
    print(f"[365] Day {day_of_year} ctx={ctx}")

    ig_id = os.getenv("IG_USER_ID", "").strip()
    token = os.getenv("IG_ACCESS_TOKEN", "").strip()
    dry = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes") or not (ig_id and token)
    if not dry:
        validate_token(token)  # fail fast before image generation/upload

    image_path, used_prompt = gen_image(cfg, theme, seed, ctx)
    quote = gen_quote(cfg, theme, ctx)
    image_path = render_quote_overlay(image_path, quote, ctx, cfg)
    caption = build_caption(cfg, quote, day_of_year, ctx)
    write_preview(caption, image_path)

    if dry:
        print("\n--- DRY-RUN (no IG creds) ---")
        print(caption)
        print(f"\nPreview: output/preview.html + {image_path.name}")
        print("To go live: fill IG_USER_ID + IG_ACCESS_TOKEN (see SETUP.md), then DRY_RUN=false")
        return 0

    print("[live] uploading + publishing to Instagram...")
    public_url = os.getenv("IMAGE_URL_OVERRIDE", "").strip() or upload_public(image_path)
    # Fail fast with clear message instead of cryptic 9004
    if not _is_ig_fetchable(public_url):
        raise RuntimeError(
            f"Image URL not fetchable by IG crawler (will cause 9004): {public_url}. "
            "Check host allows facebookexternalhit + returns image/jpeg."
        )
    media_id = ig_publish(public_url, caption, ig_id, token)
    # log
    with open(OUT / "posted.log", "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": datestr, "theme": theme, "quote": quote,
                            "image_url": public_url, "media_id": media_id}) + "\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())

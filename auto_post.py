"""
Instagram Auto-Poster — daily 1 post, 100% free stack.

Flow:
  1. Pick today's theme (date-seeded rotation, no repeat for 30 days)
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
    "Your only limit is the story you keep telling yourself.",
    "Win the morning, win the day.",
    "Courage starts with showing up.",
    "Dream big. Start small. Act now.",
    "Storms make the strongest trees.",
    "Fall seven times, rise eight.",
    "Energy flows where focus goes.",
    "Be stronger than your strongest excuse.",
    "Great things never came from comfort zones.",
    "The best time to start was yesterday. The next best is now.",
    "Push yourself, because no one else will do it for you.",
    "A little progress each day adds up to big results.",
    "Don't count the days, make the days count.",
    "Success is the sum of small efforts repeated daily.",
    "Your future needs you. Your past doesn't.",
    "Turn your wounds into wisdom.",
    "Be a voice, not an echo.",
    "Stars can't shine without darkness.",
    "Keep going. Everything you need will come to you.",
    "Prove yourself to yourself, not others.",
]

def load_config():
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)

def today_seed():
    d = datetime.date.today()
    return d.timetuple().tm_yday, d.isoformat()

def pick_theme(cfg):
    day_of_year, datestr = today_seed()
    themes = cfg.get("themes", ["inspiration"])
    theme = themes[(day_of_year - 1) % len(themes)]
    seed = int(datetime.date.today().strftime("%Y%m%d"))
    return theme, seed, day_of_year, datestr

def gen_image(cfg, theme, seed):
    w, h = cfg.get("width", 1080), cfg.get("height", 1350)
    tpl = cfg.get("image_prompt_template", "{theme}")
    niche = cfg.get("niche", "")
    prompt = tpl.format(theme=theme, niche=niche)
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

def gen_quote(cfg, theme, day_of_year):
    """Free text model. Theme is unique per day (365 list) + date-seeded seed => unique quote daily."""
    prompt = (f"Write ONE short original motivational quote (max 20 words) about: {theme}. "
              f"It is day {day_of_year} of a 365-day series, make it feel fresh and distinct. "
              "No hashtags, no quotes around it, just the quote.")
    try:
        url = "https://text.pollinations.ai/" + urllib.parse.quote(prompt) + "?model=openai"
        r = requests.get(url, timeout=60, headers={"Accept": "text/plain"})
        r.raise_for_status()
        q = r.text.strip().strip('"').strip()
        # guard against long/error responses
        if 5 < len(q) < 300 and "pollinations" not in q.lower():
            print(f"[text] FREE model quote: {q}")
            return q
        raise ValueError("bad response, using fallback")
    except Exception as e:
        print(f"[text] model unavailable ({e}), using fallback quote.")
        random.seed(f"{datetime.date.today().isoformat()}-{theme}")
        return random.choice(FALLBACK_QUOTES)

def build_caption(cfg, quote, day_of_year):
    tags = " ".join(cfg.get("hashtags", []))
    tpl = cfg.get("caption_template", "{quote}\n{hashtags}")
    return tpl.format(quote=quote, hashtags=tags,
                      day_of_year=day_of_year,
                      date=datetime.date.today().isoformat())

def upload_public(image_path: pathlib.Path) -> str:
    """Instagram API needs a PUBLIC image URL.
    Order: IMGBB (free key, most reliable from GitHub) -> litterbox -> tmpfiles -> uguu -> catbox -> 0x0
    """
    UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    # 1) ImgBB — free key from https://api.imgbb.com/ (1 min signup), add as GitHub Secret IMGBB_API_KEY
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

    # 2) litterbox (catbox temp host, 72h — often works when catbox.moe blocks servers)
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

    # 3) tmpfiles.org — keyless, server-friendly
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

    # 4) uguu.se — keyless
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

    # 5) legacy hosts
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

def fb_publish_page_photo(image_url: str, caption: str, page_id: str, token: str):
    """Post the same image to a Facebook Page feed. Free via Graph API."""
    r = requests.post(f"{BASE}/{page_id}/photos",
                      data={"url": image_url, "caption": caption,
                            "access_token": token}, timeout=60)
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"FB post failed: HTTP {r.status_code} {r.text[:500]}")
    if "id" not in j:
        raise RuntimeError(f"FB post error: {j}")
    post_id = j.get("post_id") or j["id"]
    print(f"[fb] ✅ POSTED to Page {page_id} post_id={post_id}")
    return post_id


def write_preview(caption, image_path):
    (OUT / f"caption-{datetime.date.today().isoformat()}.txt").write_text(caption, encoding="utf-8")
    html = f"""<html><body style="font-family:sans-serif;max-width:600px;margin:auto">
<h2>Dry-run preview — {datetime.date.today().isoformat()}</h2>
<img src="{image_path.name}" style="width:100%;border-radius:12px">
<pre style="white-space:pre-wrap;background:#f5f5f5;padding:12px;border-radius:8px">{caption}</pre>
</body></html>"""
    (OUT / "preview.html").write_text(html, encoding="utf-8")

def main():
    cfg = load_config()
    theme, seed, day_of_year, datestr = pick_theme(cfg)
    print(f"=== IG auto-post {datestr} | theme: {theme} ===")

    image_path, used_prompt = gen_image(cfg, theme, seed)
    quote = gen_quote(cfg, theme, day_of_year)
    caption = build_caption(cfg, quote, day_of_year)
    write_preview(caption, image_path)

    ig_id = os.getenv("IG_USER_ID", "").strip()
    token = os.getenv("IG_ACCESS_TOKEN", "").strip()
    dry = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes") or not (ig_id and token)

    if dry:
        print("\n--- DRY-RUN (no IG creds) ---")
        print(caption)
        print(f"\nPreview: output/preview.html + {image_path.name}")
        print("To go live: fill IG_USER_ID + IG_ACCESS_TOKEN (see SETUP.md), then DRY_RUN=false")
        return 0

    print("[live] uploading + publishing to Instagram...")
    public_url = os.getenv("IMAGE_URL_OVERRIDE", "").strip() or upload_public(image_path)
    media_id = ig_publish(public_url, caption, ig_id, token)

    # ── Facebook cross-post (same image + caption, optional) ──
    fb_page_id = os.getenv("FB_PAGE_ID", "").strip()
    fb_post_id = None
    if fb_page_id:
        try:
            fb_caption = caption  # same caption; hashtags are ignored-nice on FB
            fb_post_id = fb_publish_page_photo(public_url, fb_caption, fb_page_id, token)
        except Exception as e:
            print(f"[fb] ⚠️ skipped: {e}")
    else:
        print("[fb] skipped (set FB_PAGE_ID secret to also post to Facebook Page)")

    # log
    with open(OUT / "posted.log", "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": datestr, "theme": theme, "quote": quote,
                            "image_url": public_url, "media_id": media_id,
                            "fb_post_id": fb_post_id}) + "\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())

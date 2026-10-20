# Instagram Bot — develop branch (365 unique quote-on-image posters)

100% free stack. Daily 1 post. No repeats within a year.

## Files
- `auto_post.py` — main poster: 365-day theme plan + image + quote bank + text-on-image + IG publish
- `quotes_365.json` / `quotes_365.txt` — 365 strong unique quotes (Day 1..365)
- `config.yaml` — niche, themes, sizes, templates, hashtags, handle
- `requirements.txt` — requests, pyyaml, pillow
- `.env.example` — copy to `.env` locally (never commit secrets)
- `.github/workflows/ig-develop.yml` — scheduler alongside main, same secrets
- `run_develop.sh` — local/server runner for develop

## Quick start (local)
```bash
pip install -r requirements.txt
cp .env.example .env   # fill IG_USER_ID + IG_ACCESS_TOKEN for live, or leave for DRY_RUN
python3 auto_post.py --verify-365 2026   # must print all_unique: True
DRY_RUN=true python3 auto_post.py        # builds output/post-*.jpg + preview.html
```

## Live post
```bash
export IG_USER_ID="..." IG_ACCESS_TOKEN="..." IMGBB_API_KEY="..."
DRY_RUN=false python3 auto_post.py
```

## How 365-unique works
- Themes: pool = `themes × 12 backgrounds × 5 lightings × 10 moods`, shuffled by seed `ig-365-{year}`, slot `day_of_year-1`. 365/365 unique (366 leap).
- Quotes: `quotes_365.json[day_of_year]` (file source, default). `QUOTE_SOURCE=live` opts into free text model.
- Image prompt: `theme + "unique scene day N/365 year mood"` + seed `YYYYMMDD` → visibly different daily.
- Caption: quote + hashtags + `#dayN` (+ optional `CAPTION_PREFIX="[DEV] "`).
- Overlay: `render_quote_overlay()` burns quote onto 1080×1350 with gradient scrim. `QUOTE_ON_IMAGE=false` disables.

## Scheduler (alongside main, same secrets)
1. Commit this folder content to `develop`, and `.github/workflows/ig-develop.yml` to BOTH `develop` and `main` (schedule fires from default branch, checks out `develop`).
2. Uses same secrets: `IG_USER_ID`, `IG_ACCESS_TOKEN`, `IMGBB_API_KEY`.
3. Offset cron +10 min vs main to avoid racing the same IG account. `DEV_PREFIX=true` adds `[DEV]` caption prefix so test posts are distinguishable.
4. Manual: Actions → IG develop daily → Run workflow. Artifacts keep jpg + caption + posted.log.

## Push to develop
```bash
git checkout develop
cp -r /path/to/instagram_bot_develop/* .
git add auto_post.py quotes_365.json quotes_365.txt config.yaml requirements.txt .env.example .github/workflows/ig-develop.yml
git commit -m "feat(develop): full 365 quote-on-image kit"
git push origin develop
git checkout main
cp /path/to/instagram_bot_develop/.github/workflows/ig-develop.yml .github/workflows/ig-develop.yml
git add .github/workflows/ig-develop.yml
git commit -m "ci: run develop scheduler alongside main"
git push origin main
```

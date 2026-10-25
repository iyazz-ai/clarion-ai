# Deploying Clarion AI on free tiers

This guide uses four free services. Free-tier terms change often, so check each
provider's current pricing/limits page before you start.

| Piece | Service | Why |
|---|---|---|
| Database | **Neon** (Postgres) | Permanent free tier |
| API | **Render** (Web Service) | Deploys straight from GitHub |
| Website | **Cloudflare Pages** (or Netlify) | Static hosting for the React app |
| Scheduler | **GitHub Actions** | Runs `update_news` every 4 hours, free for public repos |

Known trade-offs: Render's free web service **sleeps after ~15 minutes without
traffic** (the next visit takes about a minute to wake it), and GitHub may start
scheduled runs a few minutes late.

## 0. Before you start

- [ ] Code is on GitHub (see "Push to GitHub" below) and `main` is up to date.
- [ ] You rotated any key/password that was ever pasted anywhere public.
- [ ] You have a **new** Gemini API key just for production.
- [ ] Decide: **public repo** (recommended: scheduled Actions are free and unlimited
      for public repos) or private. Nothing secret is in the repo, only in the
      services' settings.

## 1. Database (Neon)

1. Create a project at neon.tech and copy the **connection string**
   (`postgresql://user:password@host/dbname?sslmode=require`).
2. Keep it secret. It is `DATABASE_URL` below.

## 2. API (Render)

1. Render → **New → Web Service** → connect your GitHub repo.
2. Settings:
   - **Runtime:** Python 3. Add env var `PYTHON_VERSION` = `3.11.9`
   - **Build command:**
     `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
   - **Start command:** `gunicorn backend.wsgi:application`
   - **Instance type:** Free
   - **Health check path:** `/api/health/`
3. Environment variables (Render → Environment):

   | Name | Value |
   |---|---|
   | `DJANGO_SECRET_KEY` | a new long random string |
   | `DEBUG` | `False` |
   | `DATABASE_URL` | the Neon connection string |
   | `ALLOWED_HOSTS` | your Render hostname, e.g. `clarion-api.onrender.com` |
   | `CORS_ALLOWED_ORIGINS` | your website URL (set after step 3) |
   | `CSRF_TRUSTED_ORIGINS` | `https://clarion-api.onrender.com` |
   | `BEHIND_PROXY` | `True` |
   | `SECURE_SSL_REDIRECT` | `True` |
   | `SESSION_COOKIE_SECURE` | `True` |
   | `CSRF_COOKIE_SECURE` | `True` |
   | `SECURE_HSTS_SECONDS` | `31536000` |
   | `ADMIN_URL` | something unguessable, e.g. `manage-k3x9q/` |
   | `GEMINI_API_KEY` | the new production key |

4. Deploy, then open `https://<your-api>.onrender.com/api/health/` - you should see
   `{"status": "ok"}`.

## 3. Website (Cloudflare Pages)

1. Cloudflare dashboard → **Workers & Pages → Create → Pages → Connect to Git**.
2. Settings:
   - **Root directory:** `frontend`
   - **Build command:** `npm run build`
   - **Build output directory:** `dist`
   - **Environment variables:** `VITE_API_URL` = `https://<your-api>.onrender.com`
     and `NODE_VERSION` = `22`
3. Deploy. Copy the site URL, go back to Render and set `CORS_ALLOWED_ORIGINS`
   to it (e.g. `https://clarion.pages.dev`), then redeploy the API.

The build **fails on purpose** if `VITE_API_URL` is missing, so you can never
ship a site that talks to the visitor's own localhost.

## 4. Scheduler (GitHub Actions)

1. GitHub repo → **Settings → Secrets and variables → Actions**.
2. Add **secrets:** `DATABASE_URL`, `DJANGO_SECRET_KEY`, `GEMINI_API_KEY`.
3. Optional **variable:** `GEMINI_MODELS`, e.g.
   `gemini-3.5-flash:18:5,gemini-3.1-flash-lite:480:15`
   (check Google AI Studio → Rate Limit for the real numbers on your account).
4. **Actions → Update news → Run workflow** once by hand. Watch the log: feeds are
   collected, stories grouped, stories summarised.
5. The first runs summarise only 20 stories each; run it a few times by hand to
   fill the feed faster, or wait for the 4-hour schedule.
6. Once this works, **disable the Windows Task Scheduler job** so two
   schedulers are not running.

## 5. Create the admin user (once)

Render's free plan may not give you a shell, so run this on your own PC against
the production database (PowerShell):

```powershell
$env:DATABASE_URL = "<the Neon connection string>"
$env:DJANGO_SECRET_KEY = "anything-for-this-one-command"
python manage.py createsuperuser
Remove-Item Env:DATABASE_URL
```

Then log in at `https://<your-api>.onrender.com/<ADMIN_URL>login/`.

## Push to GitHub (first time)

```powershell
git init
git branch -M main
git config user.name  "Your Name"
git config user.email "<id>+<username>@users.noreply.github.com"   # keeps your real email private
git status          # CHECK: .env must NOT be listed
git add .
git status          # CHECK again
git commit -m "Initial commit: Clarion AI"
```

Create an **empty** repository on github.com (no README, no .gitignore), then:

```powershell
git remote add origin https://github.com/<username>/clarion-ai.git
git push -u origin main
```

A browser window asks you to sign in the first time (GitHub no longer accepts
account passwords on the command line).

If `.env` ever shows up in `git status`, stop: run `git rm --cached .env` first.
If a secret was already committed, rotate it - deleting it later does not remove
it from history.

## Operating it

- **Health:** `/api/health/` (point a free uptime monitor at it; this also keeps
  the free API awake).
- **Logs:** Render dashboard (API) and the GitHub Actions run log (pipeline).
- **Weekly check:** `find_near_duplicates`, `requeue_failed`, and a look at the feed.
- **Backups:** use your database provider's backup/branching features; the data
  can be rebuilt from the feeds, but summaries cost Gemini requests to redo.
- **Gemini terms:** free-tier terms (for example data use and commercial use)
  differ from paid ones. Check Google's current terms before running a public
  product, and consider a small paid plan if you outgrow the free limits.

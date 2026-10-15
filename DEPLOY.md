# Deploying MRIT to mrit.zaneroberge.org

MRIT runs as a **static site**. A scheduled job triggers a rebuild a few times a day;
Cloudflare ingests fresh public data, bakes every screen into JSON (`build_static.py`),
and serves the result. No running server, no AI, no paid data, so the live site costs
nothing per visitor and never touches your Claude usage.

This guide uses **Cloudflare Pages' Git integration**: Cloudflare pulls the repo, runs
the Python build itself, and redeploys on every push. You need **no Node, no CLI tools,
and no API tokens** — everything is done in the GitHub and Cloudflare web dashboards.

Local development is unchanged: `python3 server.py --refresh` still runs the live Python
terminal on port 5200. The static flag (`window.MRIT_STATIC`) is injected only into the
built `dist/`, so the two modes never interfere.

---

## The one-time setup (about 15 minutes, all in the browser)

### 1. Create the GitHub repo and push this folder

This `mrit/` folder becomes its own repo, separate from the personal monorepo. The
database and `config.json` (your FRED key) are gitignored and never leave your machine.

- Go to **github.com → New repository**, name it `mrit`, keep it **Public** (free
  unlimited Actions), create it **empty** (no README).
- The repo is already initialized locally and committed. Connect and push it — GitHub
  shows these exact commands on the new empty repo's page; they look like:

  ```bash
  git -C "mrit" remote add origin https://github.com/<your-username>/mrit.git
  git -C "mrit" push -u origin main
  ```

  Your browser or Git will ask you to sign in to GitHub the first time.

### 2. Connect Cloudflare Pages to the repo

In the Cloudflare dashboard → **Workers & Pages → Create → Pages → Connect to Git**:

- Pick the `mrit` repo.
- **Build settings:**
  - Framework preset: **None**
  - Build command: `python3 build_static.py --refresh`
  - Build output directory: `dist`
- **Environment variables** (Settings → add before the first build): add
  `FRED_API_KEY` with your key. This lights up the growth, market-conditions, and
  housing tiers. (Optional: `BLS_API_KEY`, `EIA_API_KEY`.)
- Save and deploy. Cloudflare's build container has Python 3 and internet access, so it
  runs the ingest and bake on its own. The first build takes a minute or two and prints
  a `*.pages.dev` URL. Open it and confirm the terminal loads.

### 3. Make it autonomous: the scheduled refresh

Cloudflare rebuilds on every push, but to refresh the *data* on a schedule it needs a
nudge. That is what the GitHub Action (`.github/workflows/deploy.yml`) does — it pings a
Cloudflare **deploy hook** a few times a day.

- In the Pages project → **Settings → Builds & deployments → Deploy hooks** → create a
  hook named `scheduled-refresh` on branch `main`. Copy the URL it gives you.
- In the GitHub repo → **Settings → Secrets and variables → Actions → New repository
  secret** → name it exactly `CLOUDFLARE_DEPLOY_HOOK_URL`, paste the hook URL, save.

That is the only secret. From now on the Action fires on its schedule (twice each
weekday, once each weekend day), hits the hook, and Cloudflare rebuilds with fresh data.

### 4. Point the subdomain at it

Pages project → **Custom domains → Set up a domain** → `mrit.zaneroberge.org`. Because
the DNS for `zaneroberge.org` already lives in Cloudflare, the record is added for you
and HTTPS is automatic.

---

## Day-to-day

- **Nothing to do.** The schedule keeps the data fresh on its own.
- **Refresh right now:** GitHub → Actions → "Refresh MRIT" → Run workflow. (Or in
  Cloudflare, Deployments → Retry/Create deployment.)
- **Change the cadence:** edit the `cron:` lines in `.github/workflows/deploy.yml`.
- **Ship a code change:** commit and push; Cloudflare auto-builds and deploys.
- **Preview the exact production build locally:**
  ```bash
  python3 build_static.py --refresh
  cd dist && python3 -m http.server 5250   # open http://127.0.0.1:5250
  ```

## What is live vs modeled

Every number keeps its `LIVE` / `DERIVED` / `MODELED` badge and its real observation
date, because the badge travels with the baked JSON. The only MODELED series are the MBS
coupon-stack shape and the daily-rate estimate; the licensed feeds that have no free
source are handled with clearly-labeled real proxies, not guesses.

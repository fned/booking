# Open Shifts

Your Winter 2027 open-shift site, rebuilt automatically from the booking report PDFs.
Upload new reports into the `reports` folder and, within a few minutes, the site updates itself.

## One-time setup (on a computer, about 10 minutes)

1. Sign in at github.com and create a new repository named `open-shifts`.
   On a free account it has to be **Public** for the website to work.
2. Upload the kit:
   - Unzip `open-shifts-kit.zip`.
   - In the new repository click **uploading an existing file** (or **Add file → Upload files**).
   - Drag in the `build`, `data` and `reports` folders plus `README.md`, then click **Commit changes**.
3. Turn on publishing: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. Add the workflow file (folders starting with a dot are often hidden and skipped when you drag):
   - **Add file → Create new file**.
   - For the name, type exactly `.github/workflows/build.yml`.
   - Open `build-workflow.yml` from the kit, copy everything, and paste it in.
   - Click **Commit changes**. This starts the first build.
5. Open the **Actions** tab and wait for the green tick (2 to 3 minutes).
   Your site is at `https://YOUR-USERNAME.github.io/open-shifts/`.
   On your iPhone open it in Safari, then **Share → Add to Home Screen**.

## Updating the data

1. Open the repository at github.com (in Safari on your phone works too), go into the `reports` folder.
2. **Add file → Upload files**, choose the new report PDFs, **Commit changes**.
3. The **Actions** tab shows the build. When it is green, refresh the site.

Notes:

- Upload any mix of reports: Daily, Weekend, XMAS, March Break, New Years, and the Vacation Tracker.
  The build recognises each one from what is inside it, so file names don't matter.
- For each kind it uses the newest report (by the date and time printed in it).
  A kind you don't upload keeps the figures it already had.
- Older PDFs can stay in `reports`; you can delete them whenever you like.
- If a report can't be read, the build stops with a red cross and **the live site is left as it was**.
  Click the failed run in **Actions** to see which file and why.
- Days Off is not read from PDFs yet; it shows the November 13 figures.

## Privacy

- The repository and the site are public on a free account: anyone with the address can open the site,
  and anyone can browse the repository, including the PDFs you upload.
- The page asks search engines not to list it, but don't post the address anywhere.

## What is in here

| Path | What it is |
|---|---|
| `reports/` | Put the booking report PDFs here. |
| `build/build.py` | Reads the PDFs and builds the page. |
| `build/template.html` | The page design. |
| `build/stations.js` | Station route images. |
| `data/state.json` | The current figures for every sheet, updated by each build. |
| `data/routes.json` | Route order for each run (the PDFs only list routes sorted, without repeats). |
| `.github/workflows/build.yml` | Tells GitHub to build and publish when reports change. |

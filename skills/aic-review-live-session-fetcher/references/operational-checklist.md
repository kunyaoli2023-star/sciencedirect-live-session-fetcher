# AIC live-session operational checklist

Run these commands from the repository root. Replace paths with the local
checkout; never embed a personal drive letter in a public input file.

## Windows Edge

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\launch_edge_clone_remote_debug.ps1 `
  -DirectConnection `
  -DisableExtensions `
  -OneShotProfile `
  -RemoteDebuggingPort 9222 `
  -Url "https://www.sciencedirect.com/"
```

If institutional access depends on a proxy or VPN route, omit
`-DirectConnection`. In the newly opened Edge window, the user must sign in,
pass any challenge, open a representative AIC article, and click `View PDF`.
Keep that window open.

Probe with the repository environment:

```powershell
.\.venv\Scripts\python.exe .\scripts\attach_sciencedirect_remote_debug.py `
  --browser edge `
  --debugger-address 127.0.0.1:9222
```

Test one row before a batch:

```powershell
.\.venv\Scripts\python.exe .\scripts\aic_edge_reuse_fetch.py `
  --input-csv .\examples\input-template.csv `
  --out-dir .\out\aic-test `
  --debug-port 9222 `
  --page-wait-seconds 8 `
  --pdf-wait-seconds 25 `
  --inter-item-sleep-seconds 0 `
  --limit 1
```

Continue only after the test reports `downloaded` and a `valid_pdf` detail.
For a batch, keep the browser open and use at least 5–8 seconds between rows.

## Why the fallback chain matters

ScienceDirect often exposes a short-lived publisher PDF target only after the
article page has evaluated the user's access. The downloader therefore keeps
the article and PDF targets inside the same live browser session. If the
network-resource response is an HTML wrapper, it does not get renamed to PDF;
the Edge viewer Save button and its normal Downloads directory are tried as a
fallback.

The `pdf.sciencedirectassets.com` address is not a durable public link. Do not
store or publish its query string.

## Resume and audit

- Skip a destination that already passes PDF and identity validation.
- Retry only rows without a validated destination.
- Keep OA, institutional browser, and reused-file sources distinct.
- Reject `.html`, `.crdownload`, `.partial`, undersized, unreadable, or
  identity-unverified payloads.
- Finish with a count of candidates, successful PDFs, failures, and duplicate
  DOI groups.

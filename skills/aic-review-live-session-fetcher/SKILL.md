---
name: aic-review-live-session-fetcher
description: Download and audit Automation in Construction papers through a lawful live ScienceDirect browser session, with OA fallback, institutional access, PDF/DOI validation, deduplication, retry, and resumable status tracking.
---

# AIC Review Live-Session Fetcher

Use this skill for *Automation in Construction* literature batches, especially
review, AI, BIM, robotics, multi-agent, collaboration, and construction-
automation papers, when direct HTTP downloading is blocked by institutional
authentication, bot checks, dynamic delivery, or the browser PDF viewer.

The browser session is the source of truth. Reuse the repository's existing
fetcher scripts instead of reimplementing browser access logic.

## Access and copyright boundary

- The user must already have lawful personal, institutional, library, VPN, or
  campus-network access.
- The user manually signs in, completes institutional authentication, and
  passes any bot verification in the same browser session used by the fetcher.
- Never use Sci-Hub, pirate repositories, credential sharing, CAPTCHA solving,
  paywall bypasses, cookie export, or cookie replay.
- Do not publish publisher PDFs, browser profiles, cookies, credentials, signed
  ScienceDirect URLs, or private run logs.

## Required workflow

1. Prepare the corpus. Normalize and deduplicate by DOI before downloading.
   Keep at least `number`, `doi`, `title`, and `note` in a UTF-8 CSV; retain
   ScienceDirect article URLs in `note` when available. For review projects,
   preserve official article type and review subtype as metadata.
2. Try publisher OA and legitimate repository locations first. Validate every
   response; an HTTP 200 HTML login/challenge page is not a PDF.
3. Start a dedicated visible Edge session on Windows using
   `scripts/launch_edge_clone_remote_debug.ps1` with a one-shot profile,
   disabled extensions, and port `9222`. Use `-DirectConnection` only when a
   proxy or campus route is not required.
4. Ask the user to manually authenticate in that new window, pass challenges,
   open one representative article, and click `View PDF` once. Do not assume
   the normal Edge window or Codex in-app tab exposes the same DevTools target.
5. Probe and download one row first. On Windows prefer the project's virtual
   environment (`.venv\\Scripts\\python.exe`) so the WebSocket dependency is
   available. Do not start a full batch until one test PDF is validated.
6. For an already-authorized Edge session, prefer
   `scripts/aic_edge_reuse_fetch.py`. It reuses one existing page target and
   follows the official ScienceDirect route: article page -> `pdfDownload`
   metadata -> publisher PDF target -> retrieval in the live authorized
   context. It falls back to the Edge PDF viewer's official Save button,
   Downloads-directory monitoring, viewer extraction, and network-resource
   retrieval as appropriate.
7. Keep requests serial and normally wait 5–8 seconds between articles. Retry
   only failed rows when possible. A validated local PDF must be skipped on a
   rerun; missing or failed rows remain retryable.
8. Validate the final library and report the status totals. Require a `%PDF-`
   signature, non-trivial stable size, readable page count, and DOI/title
   identity evidence before accepting a file.

## Status and outputs

Maintain a status table with the paper identity, OA state, PDF state, source,
local path, and failure reason. Use explicit states such as
`DOWNLOADED_OA`, `DOWNLOADED_SUBSCRIPTION`, `DOWNLOADED_REUSED`,
`NO_FULLTEXT_FOUND`, `ACCESS_REQUIRED`, and `FAILED`.

Do not report completion until the candidate count, validated PDF count,
invalid-file count, and duplicate-DOI count have been checked. Preserve the
raw batch result CSV for audit, but keep it out of a public repository when it
contains private paths or signed URLs.

Read [the operational checklist](references/operational-checklist.md) for the
exact Windows sequence and recovery actions. Read [the public-release
checklist](references/public-release.md) only when packaging the skill or
downloader for GitHub.

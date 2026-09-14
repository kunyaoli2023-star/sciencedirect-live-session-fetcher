#!/usr/bin/env python3
"""Download ScienceDirect PDFs through an already-authorized Edge CDP session.

This is the Windows/Edge companion to the repository's serial downloader.
Some Edge builds expose /json but return HTTP 500 for /json/new, so this
runner deliberately reuses one existing page target and navigates it. It
never reads or exports cookies and never attempts to bypass an access gate.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from devtools_sciencedirect_serial_fetch import (  # noqa: E402
    DevToolsClient,
    PDF_RE,
    cdp_result,
    choose_article_url,
    fetch_pdf_bytes_via_network_resource,
    fetch_pdf_bytes_from_signed_url,
    extract_pdf_bytes_from_viewer,
    is_pdf_bytes,
    make_target_name,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--debug-port", type=int, default=9222)
    parser.add_argument("--page-id", default="", help="Existing page target to reuse")
    parser.add_argument("--page-wait-seconds", type=int, default=8)
    parser.add_argument("--pdf-wait-seconds", type=int, default=20)
    parser.add_argument("--network-timeout-seconds", type=int, default=60)
    parser.add_argument("--cdp-timeout-seconds", type=int, default=45)
    parser.add_argument("--inter-item-sleep-seconds", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def list_pages(devtools: DevToolsClient) -> list[dict]:
    return devtools.list_pages()


def find_page(devtools: DevToolsClient, page_id: str = "") -> dict:
    pages = list_pages(devtools)
    if page_id:
        for page in pages:
            if page.get("id") == page_id and page.get("webSocketDebuggerUrl"):
                return page
        raise RuntimeError(f"page target disappeared: {page_id}")

    preferred = [
        page
        for page in pages
        if page.get("type") == "page"
        and page.get("webSocketDebuggerUrl")
        and (
            "sciencedirect.com" in (urlparse(page.get("url", "")).netloc or "").lower()
            or "pdf.sciencedirectassets.com" in (urlparse(page.get("url", "")).netloc or "").lower()
        )
    ]
    if preferred:
        return preferred[0]
    fallback = [page for page in pages if page.get("type") == "page" and page.get("webSocketDebuggerUrl")]
    if fallback:
        return fallback[0]
    raise RuntimeError("no reusable Edge page target found")


def redacted_url(url: str) -> str:
    parsed = urlparse(url or "")
    if not parsed.netloc:
        return url or ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def intermediate_pdf_name(row: dict[str, str]) -> str:
    number = row.get("number", "0").strip() or "0"
    doi = re.sub(r"[^A-Za-z0-9._-]+", "_", row.get("doi", "").strip())
    try:
        number = f"{int(number):03d}"
    except ValueError:
        number = re.sub(r"[^A-Za-z0-9_-]+", "_", number)
    return f"{number}_{doi or 'unknown_doi'}.pdf"


def evaluate_page(devtools: DevToolsClient, page: dict, timeout_seconds: int = 45) -> tuple[str, str, str, str]:
    ws_url = page["webSocketDebuggerUrl"]
    current_url = devtools.evaluate(ws_url, "location.href", msg_id=101, timeout=timeout_seconds) or ""
    title = devtools.evaluate(ws_url, "document.title", msg_id=102, timeout=timeout_seconds) or ""
    html = devtools.evaluate(ws_url, "document.documentElement.outerHTML", msg_id=103, timeout=timeout_seconds) or ""
    body_text = devtools.evaluate(ws_url, "document.body ? document.body.innerText : ''", msg_id=104, timeout=timeout_seconds) or ""
    return current_url, title, html, body_text


def navigate(devtools: DevToolsClient, page: dict, url: str, msg_id: int) -> dict:
    return devtools.call(page["webSocketDebuggerUrl"], "Page.navigate", {"url": url}, msg_id=msg_id, timeout=30)


def wait_for_article(
    devtools: DevToolsClient,
    page_id: str,
    page_wait_seconds: int,
    max_wait_seconds: int,
    cdp_timeout_seconds: int,
) -> tuple[dict, str, str, str, str]:
    deadline = time.time() + max_wait_seconds
    time.sleep(max(1, page_wait_seconds))
    while time.time() < deadline:
        page = find_page(devtools, page_id)
        current_url, title, html, body_text = evaluate_page(devtools, page, cdp_timeout_seconds)
        lowered = (current_url + " " + title + " " + body_text[:10000]).lower()
        if (
            "tdm-reservation" in lowered
            or "challenges.cloudflare.com" in lowered
            or "please wait" in title.lower()
            or "id.elsevier.com" in (urlparse(current_url).netloc or "").lower()
        ):
            return page, current_url, title, html, body_text
        if PDF_RE.search(html) or "science/article/" in current_url.lower():
            return page, current_url, title, html, body_text
        time.sleep(1)
    page = find_page(devtools, page_id)
    current_url, title, html, body_text = evaluate_page(devtools, page, cdp_timeout_seconds)
    return page, current_url, title, html, body_text


def wait_for_signed_pdf_page(
    devtools: DevToolsClient,
    page_id: str,
    pii: str,
    wait_seconds: int,
    cdp_timeout_seconds: int,
) -> tuple[dict, str]:
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        page = find_page(devtools, page_id)
        current_url = devtools.evaluate(page["webSocketDebuggerUrl"], "location.href", msg_id=201, timeout=cdp_timeout_seconds) or ""
        host = (urlparse(current_url).netloc or "").lower()
        if "pdf.sciencedirectassets.com" in host and pii.lower() in current_url.lower():
            return page, current_url
        time.sleep(1)

    page = find_page(devtools, page_id)
    current_url = devtools.evaluate(page["webSocketDebuggerUrl"], "location.href", msg_id=202, timeout=cdp_timeout_seconds) or ""
    raise RuntimeError(
        f"ScienceDirect did not expose a signed PDF target for {pii}; "
        f"final_host={(urlparse(current_url).netloc or '')}"
    )


def validate_pdf(path: Path, row: dict[str, str]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file_missing"
    size = path.stat().st_size
    if size < 10_000:
        return False, f"file_too_small:{size}"
    with path.open("rb") as handle:
        head = handle.read(8)
    if not is_pdf_bytes(head):
        return False, "not_pdf_header"

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path), strict=False)
        if len(reader.pages) < 1:
            return False, "pdf_has_no_pages"
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:5])
        page_count = len(reader.pages)
    except Exception as exc:
        return False, f"pdf_parse_failed:{type(exc).__name__}"

    normalized_text = re.sub(r"\s+", " ", text.lower())
    doi = (row.get("doi") or "").strip().lower()
    doi_match = doi in normalized_text
    title_words = [
        word
        for word in re.findall(r"[a-z0-9]+", (row.get("title") or "").lower())
        if len(word) > 3
    ][:12]
    title_hits = sum(1 for word in title_words if word in normalized_text)
    if not doi_match and title_hits < max(4, min(8, len(title_words) // 2)):
        return False, f"identity_unverified:doi_match={doi_match};title_hits={title_hits}/{len(title_words)}"
    return True, f"valid_pdf:size={size};pages={page_count};doi_match={doi_match};title_hits={title_hits}"


def edge_download_directory() -> Path:
    """Return the Downloads directory used by the live Windows Edge profile.

    Edge's built-in PDF viewer uses the browser downloads API for remote PDFs.
    Browser.setDownloadBehavior does not reliably redirect that API on Edge, so
    the downloader watches the user's configured Downloads directory instead.
    """
    profile_root = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(profile_root) / "Downloads"


def snapshot_download_directory(directory: Path) -> dict[str, tuple[int, int]]:
    if not directory.exists():
        return {}
    snapshot: dict[str, tuple[int, int]] = {}
    for path in directory.iterdir():
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[str(path)] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def find_new_pdf_download(
    directory: Path,
    before: dict[str, tuple[int, int]],
    *,
    stable_seconds: float = 1.5,
) -> tuple[Path | None, bytes | None]:
    """Find a newly completed PDF produced by Edge's download API."""
    if not directory.exists():
        return None, None
    candidates: list[Path] = []
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() in {".crdownload", ".partial"}:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        old = before.get(str(path))
        if old is not None and stat.st_mtime_ns <= old[0] and stat.st_size <= old[1]:
            continue
        if stat.st_size < 10_000:
            continue
        candidates.append(path)
    candidates.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
    for path in candidates:
        try:
            first_stat = path.stat()
            with path.open("rb") as handle:
                head = handle.read(8)
            if not is_pdf_bytes(head):
                continue
            time.sleep(stable_seconds)
            second_stat = path.stat()
            if (first_stat.st_size, first_stat.st_mtime_ns) != (
                second_stat.st_size,
                second_stat.st_mtime_ns,
            ):
                continue
            data = path.read_bytes()
        except (OSError, PermissionError):
            continue
        if is_pdf_bytes(data) and len(data) >= 10_000:
            return path, data
    return None, None


def find_edge_pdf_viewer(
    devtools: DevToolsClient,
    parent_page_id: str,
    *,
    wait_seconds: int,
    cdp_timeout_seconds: int,
) -> dict | None:
    """Locate Edge's chrome-extension PDF viewer child target."""
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        candidates = [
            candidate
            for candidate in list_pages(devtools)
            if candidate.get("parentId") == parent_page_id
            and candidate.get("type") == "webview"
            and candidate.get("webSocketDebuggerUrl")
        ]
        for candidate in candidates:
            try:
                ready = devtools.evaluate(
                    candidate["webSocketDebuggerUrl"],
                    "!!document.querySelector('#save')",
                    msg_id=610,
                    timeout=min(cdp_timeout_seconds, 10),
                )
            except Exception:
                ready = False
            if ready:
                return candidate
        time.sleep(1)
    return None


def download_from_edge_pdf_viewer(
    devtools: DevToolsClient,
    parent_page_id: str,
    target: Path,
    row: dict[str, str],
    *,
    wait_seconds: int,
    cdp_timeout_seconds: int,
) -> tuple[bool, str]:
    """Click Edge's official PDF Save button and capture the resulting PDF.

    This is the same publisher PDF that the user sees in Edge.  The signed URL
    and institutional access decision remain inside the live browser session;
    no cookies or tokens are exported to an external HTTP client.
    """
    viewer = find_edge_pdf_viewer(
        devtools,
        parent_page_id,
        wait_seconds=wait_seconds,
        cdp_timeout_seconds=cdp_timeout_seconds,
    )
    if not viewer:
        return False, "edge_pdf_viewer_not_ready"

    download_dir = edge_download_directory()
    download_dir.mkdir(parents=True, exist_ok=True)
    before = snapshot_download_directory(download_dir)
    clicked = devtools.evaluate(
        viewer["webSocketDebuggerUrl"],
        """(() => {
          const button = document.querySelector('#save');
          if (!button) return {ok: false, reason: 'save_button_missing'};
          button.click();
          return {ok: true, title: button.title || ''};
        })()""",
        msg_id=611,
        timeout=min(cdp_timeout_seconds, 15),
    )
    if not clicked or not clicked.get("ok"):
        return False, str((clicked or {}).get("reason", "edge_save_click_failed"))

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        downloaded_path, data = find_new_pdf_download(download_dir, before)
        if data:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            valid, detail = validate_pdf(target, row)
            if valid:
                return True, f"edge_viewer_save:{downloaded_path.name};{detail}"
            try:
                target.unlink()
            except OSError:
                pass
            return False, f"edge_viewer_download_validation_failed:{detail}"
        time.sleep(1)
    return False, "edge_viewer_download_timeout"


def write_results(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "number",
        "title",
        "doi",
        "year",
        "journal",
        "status",
        "pdf_path",
        "source_url",
        "note",
        "formatted",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def process_row(
    devtools: DevToolsClient,
    page_id: str,
    row: dict[str, str],
    pdf_dir: Path,
    args: argparse.Namespace,
) -> dict[str, str]:
    target = pdf_dir / intermediate_pdf_name(row)
    if target.exists():
        valid, detail = validate_pdf(target, row)
        if valid:
            return {**row, "status": "downloaded", "pdf_path": str(target), "source_url": "", "note": f"existing_valid:{detail}"}

    article_url = choose_article_url(row)
    if not article_url:
        return {**row, "status": "no_candidate_url", "pdf_path": "", "source_url": "", "note": "no ScienceDirect URL or DOI"}

    page = find_page(devtools, page_id)
    nav = navigate(devtools, page, article_url, 301)
    if nav.get("error"):
        return {**row, "status": "navigation_failed", "pdf_path": "", "source_url": redacted_url(article_url), "note": str(nav["error"])[:500]}

    page, current_url, title, html, body_text = wait_for_article(
        devtools,
        page_id,
        args.page_wait_seconds,
        max(args.page_wait_seconds + 10, 30),
        args.cdp_timeout_seconds,
    )
    lowered = (current_url + " " + title + " " + body_text[:20000]).lower()
    if (
        "tdm-reservation" in lowered
        or "challenges.cloudflare.com" in lowered
        or "please wait" in title.lower()
        or "id.elsevier.com" in (urlparse(current_url).netloc or "").lower()
    ):
        return {**row, "status": "challenge_or_login", "pdf_path": "", "source_url": redacted_url(current_url), "note": title[:500]}
    if "this content is not included in your subscription" in lowered or "reason=notincluded" in current_url.lower():
        return {**row, "status": "access_not_in_subscription", "pdf_path": "", "source_url": redacted_url(current_url), "note": title[:500]}

    match = PDF_RE.search(html)
    if not match:
        return {**row, "status": "no_pdf_metadata", "pdf_path": "", "source_url": redacted_url(current_url or article_url), "note": "official ScienceDirect pdfDownload metadata not present"}

    md5, pid, pii, pdf_ext, pdf_path = match.groups()
    official_route = f"https://www.sciencedirect.com/{pdf_path}/{pii}{pdf_ext}?md5={md5}&pid={pid}"
    page = find_page(devtools, page_id)
    nav = navigate(devtools, page, official_route, 401)
    if nav.get("error"):
        return {**row, "status": "pdf_navigation_failed", "pdf_path": "", "source_url": redacted_url(official_route), "note": str(nav["error"])[:500]}

    try:
        page, signed_url = wait_for_signed_pdf_page(
            devtools,
            page_id,
            pii,
            args.pdf_wait_seconds,
            args.cdp_timeout_seconds,
        )

        # Edge's built-in PDF viewer exposes the publisher's official Save
        # button.  For remote ScienceDirect PDFs Edge routes this through its
        # downloads API, so capture the completed PDF from the user's normal
        # Downloads folder and validate it before placing it in this run.
        viewer_downloaded, viewer_detail = download_from_edge_pdf_viewer(
            devtools,
            page.get("id", page_id),
            target,
            row,
            wait_seconds=args.pdf_wait_seconds,
            cdp_timeout_seconds=args.cdp_timeout_seconds,
        )
        if viewer_downloaded:
            return {
                **row,
                "status": "downloaded",
                "pdf_path": str(target),
                "source_url": redacted_url(official_route),
                "note": viewer_detail,
            }

        pdf_bytes = None
        method = ""
        # Edge renders a publisher PDF in a child chrome-extension webview.
        # The parent page may expose only the viewer shell to CDP, while the
        # child owns the actual PDFDocument bytes.
        for _ in range(12):
            viewer_pages = [
                candidate
                for candidate in list_pages(devtools)
                if candidate.get("parentId") == page.get("id")
                and candidate.get("type") == "webview"
                and candidate.get("webSocketDebuggerUrl")
            ]
            for viewer in viewer_pages:
                ready = devtools.evaluate(
                    viewer["webSocketDebuggerUrl"],
                    "!!(window.PDFViewerApplication && window.PDFViewerApplication.pdfDocument)",
                    msg_id=250,
                    timeout=min(args.cdp_timeout_seconds, 8),
                )
                if not ready:
                    continue
                pdf_bytes = extract_pdf_bytes_from_viewer(
                    devtools,
                    viewer["webSocketDebuggerUrl"],
                    timeout_seconds=args.pdf_wait_seconds,
                )
                if pdf_bytes and is_pdf_bytes(pdf_bytes):
                    method = "edge_pdf_viewer_getData"
                    break
            if pdf_bytes and is_pdf_bytes(pdf_bytes):
                break
            time.sleep(1)
        for attempt in range(1, 4):
            if pdf_bytes and is_pdf_bytes(pdf_bytes):
                break
            pdf_bytes, method = fetch_pdf_bytes_via_network_resource(
                page["webSocketDebuggerUrl"],
                signed_url,
                timeout_seconds=args.network_timeout_seconds,
            )
            if pdf_bytes and is_pdf_bytes(pdf_bytes):
                break
            # Edge's Network.loadNetworkResource can return a 200 HTML
            # wrapper for the PDF viewer even though the signed publisher URL
            # itself is valid.  Fall back to that short-lived, publisher-issued
            # URL; it carries the access decision already made by ScienceDirect
            # and does not read or export browser cookies.
            pdf_bytes = fetch_pdf_bytes_from_signed_url(signed_url)
            if pdf_bytes and is_pdf_bytes(pdf_bytes):
                method = "signed_url_http_fetch"
                break
            time.sleep(2)

        # The Edge child target can finish loading just after the initial
        # viewer wait.  Retry the visible official Save button once after the
        # parent-target fallbacks; this is especially important when Edge has
        # returned the 348-byte PDF-viewer wrapper to CDP instead of the raw
        # PDF stream.
        if not pdf_bytes or not is_pdf_bytes(pdf_bytes):
            retry_downloaded, retry_detail = download_from_edge_pdf_viewer(
                devtools,
                page.get("id", page_id),
                target,
                row,
                wait_seconds=max(args.pdf_wait_seconds, 30),
                cdp_timeout_seconds=args.cdp_timeout_seconds,
            )
            if retry_downloaded:
                return {
                    **row,
                    "status": "downloaded",
                    "pdf_path": str(target),
                    "source_url": redacted_url(official_route),
                    "note": retry_detail,
                }
            if retry_detail:
                method = retry_detail
        if not pdf_bytes or not is_pdf_bytes(pdf_bytes):
            return {**row, "status": "pdf_bytes_failed", "pdf_path": "", "source_url": redacted_url(official_route), "note": method or "no valid PDF bytes"}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf_bytes)
        valid, detail = validate_pdf(target, row)
        if not valid:
            return {**row, "status": "pdf_validation_failed", "pdf_path": "", "source_url": redacted_url(official_route), "note": detail}
        return {
            **row,
            "status": "downloaded",
            "pdf_path": str(target),
            "source_url": redacted_url(official_route),
            "note": f"{method};{detail}",
        }
    except Exception as exc:
        return {
            **row,
            "status": "pdf_target_failed",
            "pdf_path": "",
            "source_url": redacted_url(official_route),
            "note": f"{type(exc).__name__}: {exc}"[:500],
        }


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_csv)
    out_dir = Path(args.out_dir)
    pdf_dir = out_dir / "pdfs"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if args.limit > 0:
        rows = rows[: args.limit]

    devtools = DevToolsClient(args.debug_port)
    controller = find_page(devtools, args.page_id)
    page_id = controller["id"]
    print(json.dumps({"controller_page_id": page_id, "controller_url": redacted_url(controller.get("url", "")), "rows": len(rows)}, ensure_ascii=False), flush=True)

    results: list[dict[str, str]] = []
    result_path = out_dir / "devtools_results.csv"
    for index, row in enumerate(rows, start=1):
        print(f"[{index}/{len(rows)}] {row.get('doi', '')}", flush=True)
        try:
            result = process_row(devtools, page_id, row, pdf_dir, args)
        except Exception as exc:
            result = {
                **row,
                "status": "runtime_error",
                "pdf_path": "",
                "source_url": redacted_url(row.get("note", "")),
                "note": f"{type(exc).__name__}: {exc}"[:500],
            }
        results.append(result)
        write_results(result_path, results)
        print(f"    -> {result.get('status')}: {result.get('note', '')[:220]}", flush=True)
        if index < len(rows) and args.inter_item_sleep_seconds > 0:
            time.sleep(args.inter_item_sleep_seconds)

    downloaded = sum(1 for row in results if row.get("status") == "downloaded")
    summary = {
        "total_rows": len(results),
        "downloaded": downloaded,
        "missing": len(results) - downloaded,
        "output_dir": str(out_dir),
        "controller_page_id": page_id,
        "inter_item_sleep_seconds": args.inter_item_sleep_seconds,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

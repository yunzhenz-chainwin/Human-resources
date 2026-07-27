#!/usr/bin/env python3
"""Standalone resume de-identification utility.

The module deliberately has no dependency on the TalentHub backend.  It can be
used from the command line or as a small local web page (``--web``).
"""

from __future__ import annotations

import argparse
import cgi
import html
import io
import json
import re
import secrets
import sys
from datetime import datetime
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

PDF_MAX_BYTES = 10 * 1024 * 1024
PDF_MAX_PAGES = 20
PDF_MAX_TEXT_CHARACTERS = 250_000
WEB_MAX_REQUEST_BYTES = PDF_MAX_BYTES + 1 * 1024 * 1024
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".text"}


class ScannedPDFError(ValueError):
    """A PDF has no trustworthy selectable text."""


@dataclass
class Summary:
    input_characters: int
    output_characters: int
    replacements: dict[str, int]


PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "[EMAIL]"),
    ("phone", re.compile(r"(?<!\d)(?:\+?886[-\s]?|0)9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)"), "[PHONE]"),
    ("taiwan_id", re.compile(r"(?<![A-Z0-9])[A-Z][12]\d{8}(?![A-Z0-9])", re.I), "[ID]"),
)


def anonymize(text: str) -> tuple[str, Summary]:
    """Replace common personal identifiers while retaining layout."""
    result = text
    counts: dict[str, int] = {}
    for name, pattern, replacement in PATTERNS:
        result, counts[name] = pattern.subn(replacement, result)

    # Label-aware rules are deliberately conservative; this avoids redacting
    # company/project names that merely happen to look like a person's name.
    name_label = re.compile(
        r"(?im)^(\s*(?:姓名|名字|求職者姓名|應徵者姓名|name)\s*(?:[:：]|\s+)\s*)[^\r\n]+"
    )
    result, counts["name_label"] = name_label.subn(r"\1[NAME]", result)
    address_label = re.compile(
        r"(?im)^(\s*(?:地址|住址|居住地區|所在地|location|address)\s*(?:[:：]|\s+)\s*)[^\r\n]+"
    )
    result, counts["address_label"] = address_label.subn(r"\1[ADDRESS]", result)
    # Common Taiwan address forms when no label is present.
    address = re.compile(
        r"(?<![\w\u4e00-\u9fff])(?:臺|台)[北中南東西]市[^\r\n,，]{2,40}(?:區|鄉|鎮|市)[^\r\n,，]{0,40}"
    )
    result, counts["address"] = address.subn("[ADDRESS]", result)
    return result, Summary(len(text), len(result), counts)


def extract_pdf(data: bytes) -> str:
    if len(data) > PDF_MAX_BYTES:
        raise ValueError(f"PDF 檔案超過 {PDF_MAX_BYTES // (1024 * 1024)} MB 上限")
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError("PDF 解析需要 pypdf，請執行 python -m pip install pypdf") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise ValueError("PDF 受密碼保護，無法安全讀取")
        if len(reader.pages) > PDF_MAX_PAGES:
            raise ValueError(f"PDF 頁數超過 {PDF_MAX_PAGES} 頁上限")
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDF 無法解析，請確認檔案未損壞") from exc
    if len(re.sub(r"\s+", "", text)) < 20:
        raise ScannedPDFError(
            "偵測到掃描型 PDF 或文字層不足。請先使用公司核准的本機 OCR，"
            "再上傳可搜尋 PDF，並由人工確認；請勿使用未核准的第三方 OCR。"
            "本工具不會直接產出去識別結果或送出履歷內容。"
        )
    if len(text) > PDF_MAX_TEXT_CHARACTERS:
        raise ValueError(f"PDF 文字不可超過 {PDF_MAX_TEXT_CHARACTERS} 字")
    return text


def extract_docx(data: bytes) -> str:
    """Extract paragraphs and table cells from a DOCX document."""
    if len(data) > PDF_MAX_BYTES:
        raise ValueError(f"DOCX 檔案不可超過 {PDF_MAX_BYTES // (1024 * 1024)} MB")
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("DOCX 解析需要 python-docx，請執行 python -m pip install python-docx") from exc
    try:
        document = Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append("\t".join(cell.text for cell in row.cells))
        text = "\n".join(parts).strip()
    except Exception as exc:
        raise ValueError("DOCX 無法解析，請確認檔案未損壞") from exc
    if len(text) > PDF_MAX_TEXT_CHARACTERS:
        raise ValueError(f"DOCX 文字不可超過 {PDF_MAX_TEXT_CHARACTERS} 字")
    return text


def extract_text(data: bytes, suffix: str = ".txt") -> str:
    """Decode plain text, accepting UTF-8 (with BOM), UTF-16, or legacy fallback."""
    if len(data) > PDF_MAX_BYTES:
        raise ValueError(f"文字檔不可超過 {PDF_MAX_BYTES // (1024 * 1024)} MB")
    for encoding in ("utf-8-sig", "utf-16", "cp950"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("文字檔編碼無法辨識，請轉成 UTF-8 後再試")
    if len(text) > PDF_MAX_TEXT_CHARACTERS:
        raise ValueError(f"文字不可超過 {PDF_MAX_TEXT_CHARACTERS} 字")
    return text


def read_resume_input(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("不支援的檔案格式；請使用 PDF、DOCX 或 TXT")
    data = path.read_bytes()
    if suffix == ".pdf":
        return extract_pdf(data)
    if suffix == ".docx":
        return extract_docx(data)
    return extract_text(data, suffix)


def _extract_uploaded(filename: str, data: bytes) -> str:
    suffix = Path(filename or "").suffix.casefold()
    if suffix == ".pdf":
        return extract_pdf(data)
    if suffix == ".docx":
        return extract_docx(data)
    if suffix in {".txt", ".text", ""}:
        return extract_text(data, suffix)
    raise ValueError("不支援的檔案格式；請使用 PDF、DOCX 或 TXT")


def main() -> int:
    parser = argparse.ArgumentParser(description="獨立履歷去識別化工具")
    parser.add_argument("input", nargs="?", default="-", help="輸入檔案；- 代表標準輸入")
    parser.add_argument("-o", "--output", help="輸出檔案")
    parser.add_argument("--summary", action="store_true", help="將摘要輸出到 stderr")
    parser.add_argument("--web", action="store_true", help="啟動本機網頁")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.web:
        return serve_web(args.port)
    text = sys.stdin.read() if args.input == "-" else read_resume_input(Path(args.input))
    anonymized, summary = anonymize(text)
    if args.output:
        Path(args.output).write_text(anonymized, encoding="utf-8")
    else:
        sys.stdout.write(anonymized)
    if args.summary:
        print(json.dumps(asdict(summary), ensure_ascii=False), file=sys.stderr)
    return 0


class WebHandler(BaseHTTPRequestHandler):
    _results: dict[str, tuple[str, bytes]] = {}
    _used_names: set[str] = set()

    @classmethod
    def _filename(cls, original: str = "") -> str:
        date = datetime.now().strftime("%Y%m%d")
        stem = Path(original).stem if original else "resume"
        stem = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff._-]+", "_", stem).strip("._") or "resume"
        base = f"{stem}_{date}"
        name = f"{base}.txt"
        index = 1
        while name in cls._used_names:
            name = f"{base}_{index:02d}.txt"
            index += 1
        cls._used_names.add(name)
        return name

    def _page(self, source: str = "", result: str = "", summary: Summary | None = None, error: str = "", download: str = "", filename: str = "") -> bytes:
        summary_html = ""
        if summary:
            summary_html = f"<div class='summary'>共替換 {sum(summary.replacements.values())} 個欄位：{html.escape(str(summary.replacements))}</div>"
        error_html = f"<p class='error'>{html.escape(error)}</p>" if error else ""
        download_html = f"<p><a href='/download/{html.escape(download)}'>下載去識別化檔案（{html.escape(filename)}）</a></p>" if download else ""
        document = f"""<!doctype html><html lang='zh-Hant'><meta charset='utf-8'><title>履歷去識別化</title>
<style>body{{font-family:Arial,sans-serif;max-width:1100px;margin:35px auto;padding:0 20px;color:#234}}h1{{color:#17685e}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}textarea{{width:100%;height:360px;padding:12px;box-sizing:border-box;border:1px solid #bdd4ce;border-radius:8px}}button{{margin-top:12px;padding:11px 20px;background:#087f70;color:white;border:0;border-radius:7px;cursor:pointer}}.summary{{margin:14px 0;padding:12px;background:#eaf7f2;border-radius:7px}}.error{{color:#a33}}small{{color:#607a73}}@media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}</style>
<h1>履歷去識別化</h1><small>獨立 Python 工具，不連接 TalentHub 後台</small>{error_html}<form method='post' enctype='multipart/form-data'><div class='grid'><label>原始履歷<br><input type='file' name='file' accept='.pdf,.docx,.txt,.text,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain'><small>支援 PDF、DOCX、TXT；掃描型 PDF 請先使用核准的本機 OCR</small><textarea name='text' placeholder='請貼上履歷文字'>{html.escape(source)}</textarea></label><label>去識別化結果<br><textarea readonly>{html.escape(result)}</textarea></label></div><button type='submit'>開始去識別化</button></form>{summary_html}</html>"""
        document = document.replace("</textarea></label></div>", "</textarea></label>" + download_html + "</div>")
        return document.encode("utf-8")

    def _send_page(self, status_code: int, body: bytes) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/download/"):
            item = self._results.get(path.rsplit("/", 1)[-1])
            if not item:
                self._send_page(404, self._page(error="下載連結已失效，請重新處理履歷。"))
                return
            filename, payload = item
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        item = self._results.get(token)
        if item:
            filename, payload = item
            self._send_page(200, self._page(result=payload.decode("utf-8"), download=token, filename=filename))
        else:
            self._send_page(200, self._page())

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > WEB_MAX_REQUEST_BYTES:
                raise ValueError(f"請求不可超過 {WEB_MAX_REQUEST_BYTES // (1024 * 1024)} MB")
            raw = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "")
            source = ""
            original_name = ""
            if content_type.startswith("multipart/form-data"):
                form = cgi.FieldStorage(fp=io.BytesIO(raw), headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type})
                source = form.getfirst("text", "")
                upload = form["file"] if "file" in form else (form["pdf"] if "pdf" in form else None)
                if upload is not None and getattr(upload, "filename", "") and getattr(upload, "file", None):
                    original_name = upload.filename
                    source = _extract_uploaded(upload.filename, upload.file.read())
            else:
                source = parse_qs(raw.decode("utf-8"), keep_blank_values=True).get("text", [""])[0]
            result, summary = anonymize(source)
            token = secrets.token_urlsafe(18)
            filename = self._filename(original_name)
            self._results[token] = (filename, result.encode("utf-8"))
            self.send_response(303)
            self.send_header("Location", f"/?token={token}")
            self.end_headers()
            return
        except Exception as exc:
            self._send_page(400, self._page(error=str(exc)))

    def log_message(self, *_args: object) -> None:
        return


def serve_web(port: int) -> int:
    server = ThreadingHTTPServer(("127.0.0.1", port), WebHandler)
    server.daemon_threads = True
    print(f"履歷去識別化工具：http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

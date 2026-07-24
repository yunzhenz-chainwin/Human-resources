#!/usr/bin/env python3
"""Standalone resume de-identification utility.

Usage:
    python resume_anonymizer.py resume.txt -o resume_anonymized.txt
    type resume.txt | python resume_anonymizer.py -

This file intentionally has no dependency on the TalentHub backend or UI.
"""

from __future__ import annotations

import argparse
import cgi
import io
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Summary:
    input_characters: int
    output_characters: int
    replacements: dict[str, int]


PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "[EMAIL]"),
    ("phone", re.compile(r"(?<!\d)(?:\+?886[-\s]?|0)9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)"), "[PHONE]"),
    ("taiwan_id", re.compile(r"(?<![A-Z0-9])[A-Z][12]\d{8}(?![A-Z0-9])", re.I), "[ID]"),
    ("address", re.compile(r"(?:(?:台灣|臺灣)?[\u4e00-\u9fff]{1,4}[縣市][\u4e00-\u9fff]{1,5}[區鄉鎮市][\u4e00-\u9fff0-9\-巷弄號樓室]{2,})"), "[ADDRESS]"),
)


def anonymize(text: str) -> tuple[str, Summary]:
    """Replace common personal identifiers while preserving the resume layout."""
    result = text
    counts: dict[str, int] = {}
    for name, pattern, replacement in PATTERNS:
        result, count = pattern.subn(replacement, result)
        counts[name] = count

    # Names are intentionally conservative: only redact an explicit name label
    # or the first non-empty line, avoiding accidental replacement of employers.
    labelled = re.compile(r"(?im)^(\s*[^:\r\n]{0,16}(?:姓名|名字|name)\s*[:：]\s*)[^\r\n]+")
    result, count = labelled.subn(r"\1[NAME]", result)
    counts["name_label"] = count
    address_labelled = re.compile(r"(?im)^(\s*[^:\r\n]{0,16}(?:地址|居住地區|居住地址|location)\s*[:：]\s*)[^\r\n]+")
    result, count = address_labelled.subn(r"\1[ADDRESS]", result)
    counts["address_label"] = count
    return result, Summary(len(text), len(result), counts)


def extract_pdf(data: bytes) -> str:
    """Extract selectable text from a PDF without connecting to any service."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF 讀取需要 pypdf，請先執行：python -m pip install pypdf") from exc
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if not text:
        raise ValueError("這份 PDF 沒有可擷取的文字，可能是掃描影像；請先做 OCR 或貼上文字。")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="履歷去識別化（獨立工具，不連接 TalentHub 後台）")
    parser.add_argument("input", nargs="?", default="-", help="輸入履歷文字檔；使用 - 代表從標準輸入讀取")
    parser.add_argument("-o", "--output", help="輸出檔案；未指定時輸出到畫面")
    parser.add_argument("--summary", action="store_true", help="輸出 JSON 處理摘要到 stderr")
    parser.add_argument("--web", action="store_true", help="啟動獨立本機網頁介面")
    parser.add_argument("--port", type=int, default=8765, help="網頁介面連接埠（預設 8765）")
    args = parser.parse_args()

    if args.web:
        return serve_web(args.port)

    text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8-sig")
    anonymized, summary = anonymize(text)
    if args.output:
        Path(args.output).write_text(anonymized, encoding="utf-8")
    else:
        sys.stdout.write(anonymized)
    if args.summary:
        print(json.dumps(asdict(summary), ensure_ascii=False), file=sys.stderr)
    return 0


class WebHandler(BaseHTTPRequestHandler):
    def _page(self, source: str = "", result: str = "", summary: Summary | None = None, error: str = "") -> bytes:
        summary_html = ""
        if summary:
            summary_html = f"<div class='summary'>共替換 {sum(summary.replacements.values())} 個欄位：{summary.replacements}</div>"
        error_html = f"<p class='error'>{error}</p>" if error else ""
        html = f"""<!doctype html><html lang='zh-Hant'><meta charset='utf-8'><title>履歷去識別化</title>
<style>body{{font-family:Arial,sans-serif;max-width:1100px;margin:35px auto;padding:0 20px;color:#234}}h1{{color:#17685e}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}textarea{{width:100%;height:360px;padding:12px;box-sizing:border-box;border:1px solid #bdd4ce;border-radius:8px}}button{{margin-top:12px;padding:11px 20px;background:#087f70;color:white;border:0;border-radius:7px;cursor:pointer}}.summary{{margin:14px 0;padding:12px;background:#eaf7f2;border-radius:7px}}.error{{color:#a33}}small{{color:#607a73}}@media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}</style>
<h1>履歷去識別化</h1><small>獨立 Python 工具，不連接 TalentHub 後台</small>{error_html}<form method='post' enctype='multipart/form-data'><div class='grid'><label>原始履歷<br><input type='file' name='pdf' accept='.pdf,application/pdf'><small>可選取 PDF；也可直接貼上文字</small><textarea name='text' placeholder='請貼上履歷文字'>{source}</textarea></label><label>去識別化結果<br><textarea readonly>{result}</textarea></label></div><button type='submit'>開始去識別化</button></form>{summary_html}</html>"""
        return html.encode("utf-8")

    def do_GET(self) -> None:
        body = self._page()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "")
            if content_type.startswith("multipart/form-data"):
                form = cgi.FieldStorage(fp=io.BytesIO(raw), headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type})
                source = form.getfirst("text", "")
                pdf_field = form["pdf"] if "pdf" in form else None
                if pdf_field is not None and getattr(pdf_field, "filename", "") and getattr(pdf_field, "file", None):
                    source = extract_pdf(pdf_field.file.read())
            else:
                source = parse_qs(raw.decode("utf-8"), keep_blank_values=True).get("text", [""])[0]
            result, summary = anonymize(source)
            body = self._page(source, result, summary)
            self.send_response(200)
        except Exception as exc:
            body = self._page(error=str(exc)); self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def serve_web(port: int) -> int:
    server = ThreadingHTTPServer(("127.0.0.1", port), WebHandler)
    server.daemon_threads = True
    print(f"履歷去識別化工具已啟動：http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

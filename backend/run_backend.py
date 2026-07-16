# TalentHub 後端啟動器:確保 OCR 工具(Tesseract / Poppler)在 PATH 上,
# 再啟動 uvicorn。掃描型 PDF 的 OCR 依賴這兩個外部執行檔。
import os

_DEFAULT_OCR_DIRS = [
    r"C:\Program Files\Tesseract-OCR",
    r"C:\Users\Administrator\ocr-tools\poppler-26.02.0\Library\bin",
]
# Allow overriding the OCR tool directories per host via OCR_TOOL_DIRS
# (os.pathsep-separated); fall back to the known local install paths.
_configured = os.environ.get("OCR_TOOL_DIRS")
_OCR_DIRS = [
    directory
    for directory in (_configured.split(os.pathsep) if _configured else _DEFAULT_OCR_DIRS)
    if directory
]
os.environ["PATH"] = os.pathsep.join(_OCR_DIRS) + os.pathsep + os.environ.get("PATH", "")

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8010)

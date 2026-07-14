# TalentHub 後端啟動器:確保 OCR 工具(Tesseract / Poppler)在 PATH 上,
# 再啟動 uvicorn。掃描型 PDF 的 OCR 依賴這兩個外部執行檔。
import os

_OCR_DIRS = [
    r"C:\Program Files\Tesseract-OCR",
    r"C:\Users\Administrator\ocr-tools\poppler-26.02.0\Library\bin",
]
os.environ["PATH"] = os.pathsep.join(_OCR_DIRS) + os.pathsep + os.environ.get("PATH", "")

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8010)

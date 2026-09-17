"""Image intake: QR decode (zbarimg) + OCR (tesseract eng+hin).

Both are CLI subprocesses — installed system tools, no fragile native wheels
(docs/DECISIONS.md §1). Input is re-encoded to PNG via PIL first so JPEG/WEBP/
PNG screenshots all take one path.

ponytail: single OCR pass (psm 3); add a sparse-text second pass (psm 11) if
real-world screenshot recall falls short.
"""
import os
import re
import shutil
import subprocess
import tempfile

from PIL import Image, ImageOps

TESSDATA = os.path.join(os.path.dirname(__file__), "tessdata")
MAX_BYTES = 10 * 1024 * 1024
_MAGIC = {b"\x89PNG": "png", b"\xff\xd8": "jpeg", b"RIFF": "webp", b"GIF8": "gif"}


def _sniff(data: bytes) -> bool:
    return any(data.startswith(m) for m in _MAGIC)


def _to_png(data: bytes) -> Image.Image:
    from io import BytesIO
    im = Image.open(BytesIO(data))
    im = ImageOps.exif_transpose(im)          # phone screenshots carry EXIF rotation
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    return im


def _langs() -> str:
    have = []
    for l in ("eng", "hin"):
        if os.path.exists(os.path.join(TESSDATA, f"{l}.traineddata")):
            have.append(l)
    return "+".join(have) if have else "eng"


def decode_qr(im: Image.Image) -> list[str]:
    """zbarimg --raw; one retry at 2× upscale for small/soft QRs."""
    if shutil.which("zbarimg") is None:
        return []
    out = []
    with tempfile.TemporaryDirectory() as td:
        for attempt, img in enumerate((im, im.resize((im.width * 2, im.height * 2), Image.LANCZOS))):
            p = os.path.join(td, f"q{attempt}.png")
            img.save(p, "PNG")
            try:
                r = subprocess.run(["zbarimg", "--raw", "-q", p],
                                   capture_output=True, text=True, timeout=30)
            except (subprocess.TimeoutExpired, OSError):
                return out
            for line in r.stdout.splitlines():
                line = line.strip()
                if line and line not in out:
                    out.append(line)
            if out:
                break
    return out


def ocr(im: Image.Image) -> str:
    if shutil.which("tesseract") is None:
        return ""
    # upscale small images; tesseract wants ~300dpi-equivalent text height
    if im.width < 1200:
        scale = min(3.0, 1400.0 / max(im.width, 1))
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "o.png")
        im.save(p, "PNG")
        env = dict(os.environ, TESSDATA_PREFIX=TESSDATA)
        try:
            r = subprocess.run(["tesseract", p, "stdout", "-l", _langs(), "--psm", "3"],
                               capture_output=True, text=True, timeout=60, env=env)
        except (subprocess.TimeoutExpired, OSError):
            return ""
    return r.stdout


def process_image(data: bytes) -> dict:
    """One entry point for uploads: {ok, text, qr, error}."""
    if not data or len(data) > MAX_BYTES:
        return {"ok": False, "text": "", "qr": [], "error": "size"}
    if not _sniff(data):
        return {"ok": False, "text": "", "qr": [], "error": "format"}
    try:
        im = _to_png(data)
    except Exception:
        return {"ok": False, "text": "", "qr": [], "error": "decode"}
    qr = decode_qr(im)
    text = ocr(im)
    # QR payloads often contain the handle too; keep both for cross-checking
    return {"ok": True, "text": text, "qr": qr, "error": None}


# --- self-check (uses the real Taurus QR image if present) --------------------
if __name__ == "__main__":
    sample = os.path.join(os.path.dirname(__file__), "..", ".research", "taurus_cf_brk.png")
    if not os.path.exists(sample):
        sample = "/home/any/Desktop/Tushar/.research/taurus_cf_brk.png"
    if os.path.exists(sample):
        r = process_image(open(sample, "rb").read())
        assert r["ok"], r
        assert any("taurus.cf.brk@validaxis" in q for q in r["qr"]), r["qr"]
        print("ocr.py self-check OK — QR decoded:", r["qr"])
    else:
        print("ocr.py self-check SKIPPED (sample image missing)")

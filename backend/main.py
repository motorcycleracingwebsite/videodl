import os
import uuid
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp

app = FastAPI(title="VideoDL API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)


class LinkRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    format_id: str


@app.get("/")
def health_check():
    return {"status": "ok"}


@app.post("/api/analyze")
def analyze(req: LinkRequest):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Impossibile leggere il link: {e}")

    formats = []
    seen = set()
    for f in info.get("formats", []):
        if f.get("vcodec") == "none":
            continue
        height = f.get("height")
        ext = f.get("ext")
        label = f"{height}p" if height else f.get("format_note", f.get("format_id"))
        key = (label, ext)
        if key in seen:
            continue
        seen.add(key)
        formats.append({
            "format_id": f.get("format_id"),
            "label": label,
            "ext": ext,
            "filesize_approx": f.get("filesize") or f.get("filesize_approx"),
            "has_audio": f.get("acodec") != "none",
        })

    def sort_key(fmt):
        try:
            return int(fmt["label"].replace("p", ""))
        except (ValueError, TypeError):
            return -1

    formats.sort(key=sort_key, reverse=True)

    return {
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "formats": formats,
    }


@app.post("/api/download")
def download(req: DownloadRequest):
    job_id = str(uuid.uuid4())
    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    output_template = str(job_dir / "%(title)s.%(ext)s")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "outtmpl": output_template,
        "format": f"{req.format_id}+bestaudio/best",
        "merge_output_format": "mp4",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            filename = ydl.prepare_filename(info)
            if not os.path.exists(filename):
                base, _ = os.path.splitext(filename)
                candidate = base + ".mp4"
                if os.path.exists(candidate):
                    filename = candidate
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Errore durante il download: {e}")

    if not os.path.exists(filename):
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="File non trovato dopo il download")

    return FileResponse(
        path=filename,
        filename=os.path.basename(filename),
        media_type="application/octet-stream",
        background=None,
    )

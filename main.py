Python
import json
import subprocess
import urllib.parse
import re
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Filename", "Content-Type"],
)

def extract_video_id(url: str):
    match = re.search(r'(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=|shorts\/|live\/))([\w-]{11})', url)
    return match.group(1) if match else None

@app.get("/api/youtube-audio")
async def get_audio(url: str = Query(...)):
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="URL khong hop le")

    clean_url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        info_cmd = ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", "--quiet", clean_url]
        proc = subprocess.run(info_cmd, capture_output=True, text=True, timeout=12)
        raw_title = json.loads(proc.stdout).get("title", f"youtube_{video_id}") if proc.returncode == 0 else f"youtube_{video_id}"
    except Exception:
        raw_title = f"youtube_{video_id}"

    safe_title = "".join(c for c in raw_title if c not in r'\/:*?"<>|').strip()[:100] or f"youtube_{video_id}"
    file_name = f"{safe_title}.m4a"
    encoded_name = urllib.parse.quote(file_name)

    # Stream audio trực tiếp từ yt-dlp
    ytdlp_cmd = [
        "yt-dlp",
        "-f", "bestaudio[ext=m4a]/ba/b",
        "-o", "-",
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        clean_url
    ]

    process = subprocess.Popen(ytdlp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def iterfile():
        try:
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            process.kill()

    headers = {
        "Content-Type": "audio/mp4",
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        "X-Filename": encoded_name
    }

    return StreamingResponse(iterfile(), headers=headers)

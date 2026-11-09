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
        raise HTTPException(status_code=400, detail="URL YouTube không hợp lệ")

    clean_url = f"https://www.youtube.com/watch?v={video_id}"

    # 1. Lấy tiêu đề bài hát (dùng client iOS/Android để tránh bot check)
    raw_title = f"youtube_{video_id}"
    try:
        info_cmd = [
            "yt-dlp",
            "--extractor-args", "youtube:player_client=tv_embedded,web_safari",
            "--dump-json",
            "--no-playlist",
            "--no-warnings",
            clean_url
        ]
        proc = subprocess.run(info_cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0 and proc.stdout.strip():
            info = json.loads(proc.stdout)
            raw_title = info.get("title", raw_title)
    except Exception:
        pass

    safe_title = "".join(c for c in raw_title if c not in r'\/:*?"<>|').strip()[:100] or f"youtube_{video_id}"
    file_name = f"{safe_title}.m4a"
    encoded_name = urllib.parse.quote(file_name)

    # 2. Khởi tạo stream audio với cấu hình bypass bot
    ytdlp_cmd = [
        "yt-dlp",
        "--extractor-args", "youtube:player_client=ios,android",
        "-f", "ba[ext=m4a]/ba/b",
        "-o", "-",
        "--no-playlist",
        clean_url
    ]

    process = subprocess.Popen(ytdlp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Đọc trước 64KB đầu tiên để đảm bảo YouTube đã nhả luồng âm thanh
    first_chunk = process.stdout.read(64 * 1024)
    if not first_chunk:
        err_msg = process.stderr.read().decode("utf-8", errors="ignore").strip()
        process.kill()
        print("yt-dlp error:", err_msg)
        last_line = err_msg.split("\n")[-1] if err_msg else "YouTube chặn luồng phát trực tiếp"
        raise HTTPException(status_code=500, detail=f"yt-dlp: {last_line}")

    def iterfile():
        yield first_chunk
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

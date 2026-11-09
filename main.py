import os
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

COOKIE_FILE = "/tmp/youtube_cookies.txt"

def setup_cookie_file():
    raw_cookies = os.getenv("YOUTUBE_COOKIES", "").strip()
    if not raw_cookies:
        print("[COOKIES WARNING] Khong tim thay bien moi truong YOUTUBE_COOKIES!")
        return False

    normalized_lines = []
    cookie_count = 0

    for line in raw_cookies.splitlines():
        line_str = line.strip()
        if not line_str:
            continue
        if line_str.startswith("#"):
            normalized_lines.append(line_str)
            continue

        parts = line_str.split()
        if len(parts) >= 7:
            domain, flag, path, secure, expiration, name = parts[:6]
            value = " ".join(parts[6:])
            normalized_lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expiration}\t{name}\t{value}")
            cookie_count += 1

    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(normalized_lines) + "\n")

    print(f"[COOKIES OK] Da nap {cookie_count} cookies vao file {COOKIE_FILE}")
    return True

setup_cookie_file()

def extract_video_id(url: str):
    match = re.search(r'(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=|shorts\/|live\/))([\w-]{11})', url)
    return match.group(1) if match else None

@app.get("/api/youtube-audio")
async def get_audio(url: str = Query(...)):
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="URL YouTube khong hop le")

    clean_url = f"https://www.youtube.com/watch?v={video_id}"

    has_cookie = os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 50
    if not has_cookie:
        setup_cookie_file()
        has_cookie = os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 50

    cookie_args = ["--cookies", COOKIE_FILE] if has_cookie else []
    # Su dung client ios va tv de tranh co che chan PO Token tren datacenter
    client_args = ["--extractor-args", "youtube:player_client=ios,tv"]

    # 1. Lay tieu de bai hat
    raw_title = f"youtube_{video_id}"
    try:
        info_cmd = [
            "yt-dlp",
            *cookie_args,
            *client_args,
            "--dump-json",
            "--no-playlist",
            clean_url
        ]
        proc = subprocess.run(info_cmd, capture_output=True, text=True, timeout=20)
        if proc.returncode == 0 and proc.stdout.strip():
            info = json.loads(proc.stdout)
            raw_title = info.get("title", raw_title)
        else:
            print("[INFO ERROR]", proc.stderr)
    except Exception as e:
        print("[INFO EXCEPTION]", str(e))

    safe_title = "".join(c for c in raw_title if c not in r'\/:*?"<>|').strip()[:100] or f"youtube_{video_id}"
    file_name = f"{safe_title}.m4a"
    encoded_name = urllib.parse.quote(file_name)

    # 2. Khoi tao luong stream: uu tien ba (bestaudio), tu dong fallback sang b (best mp4)
    ytdlp_cmd = [
        "yt-dlp",
        *cookie_args,
        *client_args,
        "-f", "ba/b",
        "-o", "-",
        "--no-playlist",
        clean_url
    ]

    process = subprocess.Popen(ytdlp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Doc 64KB dau tien
    first_chunk = process.stdout.read(64 * 1024)
    if not first_chunk:
        err_msg = process.stderr.read().decode("utf-8", errors="ignore").strip()
        process.kill()
        print("[STREAM ERROR]", err_msg)

        # In danh sach cac format thuc te dang co de kiem tra
        diag = subprocess.run(["yt-dlp", *cookie_args, *client_args, "-F", clean_url], capture_output=True, text=True, timeout=15)
        print("=== FORMATS CO SAN TRAN SERVER ===")
        print(diag.stdout or diag.stderr)

        last_line = err_msg.split("\n")[-1] if err_msg else "YouTube tu choi truyen audio"
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

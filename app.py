import os, re, uuid, asyncio, subprocess, threading, tempfile, json, urllib.request
from flask import Flask, request, jsonify

app = Flask(__name__)
JOBS = {}
SECRET = os.environ.get("API_SECRET", "")
SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_KEY", "")
BUCKET = os.environ.get("SUPABASE_BUCKET", "videos")
VOICE = os.environ.get("TTS_VOICE", "vi-VN-HoaiMyNeural")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
COLORS = ["0x0f172a", "0x1e1b4b", "0x064e3b", "0x3b0764", "0x7c2d12", "0x0c4a6e"]


def split_sentences(text):
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    out = []
    for p in parts:
        p = p.strip()
        while len(p) > 60:  # keep subtitle lines short
            cut = p.rfind(" ", 0, 60)
            cut = cut if cut > 20 else 60
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            out.append(p)
    return out


def wrap(line, width=22):
    words, lines, cur = line.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def tts(text, path):
    import edge_tts
    asyncio.run(edge_tts.Communicate(text, VOICE, rate="+5%").save(path))


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    return float(r.stdout.strip())


def render(job_id, title, script, tts_fn=tts):
    tmp = tempfile.mkdtemp()
    audio, out = f"{tmp}/a.mp3", f"{tmp}/v.mp4"
    tts_fn(script, audio)
    total = duration(audio)
    sents = split_sentences(script)
    weights = [max(len(s), 1) for s in sents]
    t, filters = 0.0, []
    for i, (s, w) in enumerate(zip(sents, weights)):
        d = total * w / sum(weights)
        tf = f"{tmp}/s{i}.txt"
        open(tf, "w", encoding="utf-8").write(wrap(s))
        filters.append(
            f"drawtext=fontfile={FONT}:textfile={tf}:fontsize=64:fontcolor=white:"
            f"line_spacing=14:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.35:"
            f"boxborderw=24:enable='between(t,{t:.2f},{t + d:.2f})'")
        t += d
    tf = f"{tmp}/title.txt"
    open(tf, "w", encoding="utf-8").write(wrap(title, 26))
    filters.append(f"drawtext=fontfile={FONT}:textfile={tf}:fontsize=52:fontcolor=0xfde047:"
                   f"x=(w-text_w)/2:y=200")
    color = COLORS[hash(job_id) % len(COLORS)]
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=1080x1920:r=24:d={total + 0.5:.2f}",
           "-i", audio, "-vf", ",".join(filters), "-c:v", "libx264", "-preset", "veryfast",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def upload(job_id, path):
    if not (SB_URL and SB_KEY):
        return None
    name = f"{job_id}.mp4"
    req = urllib.request.Request(f"{SB_URL}/storage/v1/object/{BUCKET}/{name}",
                                 data=open(path, "rb").read(), method="POST",
                                 headers={"Authorization": f"Bearer {SB_KEY}", "apikey": SB_KEY,
                                          "Content-Type": "video/mp4", "x-upsert": "true"})
    urllib.request.urlopen(req, timeout=120).read()
    return f"{SB_URL}/storage/v1/object/public/{BUCKET}/{name}"


def work(job_id, title, script):
    try:
        path = render(job_id, title, script)
        JOBS[job_id] = {"status": "done", "url": upload(job_id, path)}
    except Exception as e:
        JOBS[job_id] = {"status": "error", "error": str(e)[:300]}


@app.get("/")
def health():
    return "ok"


@app.post("/render")
def create():
    body = request.get_json(force=True, silent=True) or {}
    if SECRET and body.get("secret") != SECRET:
        return jsonify(error="unauthorized"), 401
    if not body.get("script"):
        return jsonify(error="missing script"), 400
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "running"}
    threading.Thread(target=work, args=(job_id, body.get("title", ""), body["script"]), daemon=True).start()
    return jsonify(id=job_id)


@app.get("/status/<job_id>")
def status(job_id):
    return jsonify(JOBS.get(job_id, {"status": "unknown"}))

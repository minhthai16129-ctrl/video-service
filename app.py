import os, re, uuid, asyncio, subprocess, threading, tempfile, json, urllib.request, urllib.error
from flask import Flask, request, jsonify

app = Flask(__name__)
JOBS = {}
SECRET = os.environ.get("API_SECRET", "")
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")
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
    import edge_tts, time
    last = None
    for attempt in range(4):
        try:
            asyncio.run(edge_tts.Communicate(text, VOICE).save(path))
            if os.path.getsize(path) > 2000:
                return
            last = RuntimeError("empty audio")
        except Exception as e:
            last = e
        time.sleep(3 * (attempt + 1))
    raise last


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    return float(r.stdout.strip())


def fetch_one(i, kw, tmp):
    p = f"{tmp}/img{i}.jpg"
    if PIXABAY_KEY:
        q = urllib.parse.quote(kw.strip())
        req = urllib.request.Request(
            f"https://pixabay.com/api/?key={PIXABAY_KEY}&q={q}&image_type=photo&orientation=vertical&safesearch=true&per_page=6",
            headers={"User-Agent": "Mozilla/5.0"})
        hits = json.loads(urllib.request.urlopen(req, timeout=20).read()).get("hits") or []
        if not hits:
            return None
        url = hits[i % len(hits)].get("largeImageURL") or hits[0]["webformatURL"]
    elif PEXELS_KEY:
        q = urllib.parse.quote(kw.strip())
        req = urllib.request.Request(
            f"https://api.pexels.com/v1/search?query={q}&orientation=portrait&per_page=3&size=medium",
            headers={"Authorization": PEXELS_KEY, "User-Agent": "Mozilla/5.0"})
        photos = (json.loads(urllib.request.urlopen(req, timeout=20).read()).get("photos") or [])
        if not photos:
            return None
        url = photos[0]["src"]["portrait"]
    else:
        prompt = urllib.parse.quote(kw.strip() + ", futuristic technology, cinematic, vertical poster, no text")
        url = f"https://image.pollinations.ai/prompt/{prompt}?width=720&height=1280&nologo=true&seed={i + 7}"
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=40).read()
    if len(data) < 5000:
        return None
    open(p, "wb").write(data)
    return p


def fetch_images(keywords, tmp, n=6, deadline=75):
    if not keywords:
        return []
    from concurrent.futures import ThreadPoolExecutor, wait
    ex = ThreadPoolExecutor(max_workers=4)
    futs = [ex.submit(fetch_one, i, kw, tmp) for i, kw in enumerate(keywords[:n])]
    wait(futs, timeout=deadline)
    ex.shutdown(wait=False, cancel_futures=True)
    out = []
    for f in futs:
        try:
            if f.done() and f.result():
                out.append(f.result())
        except Exception as e:
            print("image fail:", str(e)[:150], flush=True)
    print(f"images ok: {len(out)}/{len(futs)}", flush=True)
    return out


def ass_time(t):
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


def render(job_id, title, script, tts_fn=tts, keywords=None, fetch_fn=fetch_images):
    tmp = tempfile.mkdtemp()
    audio, out, ass = f"{tmp}/a.mp3", f"{tmp}/v.mp4", f"{tmp}/s.ass"
    tts_fn(script, audio)
    total = duration(audio)
    try:
        mixed = f"{tmp}/mix.m4a"
        chord = ("0.5*sin(2*PI*130.81*t)+0.35*sin(2*PI*164.81*t)+0.35*sin(2*PI*196*t)"
                 "+0.2*sin(2*PI*261.63*t*(1+0.002*sin(2*PI*0.2*t)))")
        subprocess.run(["ffmpeg", "-y", "-threads", "1", "-i", audio, "-f", "lavfi", "-i",
                        f"aevalsrc={chord}:s=24000:d={total + 1:.2f}",
                        "-filter_complex",
                        "[1:a]lowpass=f=700,tremolo=f=0.15:d=0.4,volume=0.12,"
                        f"afade=t=in:d=2,afade=t=out:st={max(total - 2, 0):.2f}:d=2[m];"
                        "[0:a][m]amix=inputs=2:duration=first:normalize=0[o]",
                        "-map", "[o]", "-c:a", "aac", "-b:a", "96k", mixed],
                       check=True, capture_output=True)
        audio = mixed
    except Exception as e:
        print("music skipped:", str(e)[:150], flush=True)
    sents = split_sentences(script)
    weights = [max(len(s), 1) for s in sents]
    lines = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 720", "PlayResY: 1280", "WrapStyle: 2", "",
             "[V4+ Styles]",
             "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
             "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,"
             "MarginV,Encoding",
             "Style: Sub,DejaVu Sans,46,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,10,0,5,50,50,0,1",
             "Style: Title,DejaVu Sans,38,&H0047E0FD,&H0047E0FD,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,8,50,50,140,1",
             "", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
    lines.append(f"Dialogue: 0,{ass_time(0)},{ass_time(total + 0.5)},Title,,0,0,0,,{wrap(title, 26).replace(chr(10), chr(92) + 'N')}")
    t = 0.0
    for s, w in zip(sents, weights):
        d = total * w / sum(weights)
        lines.append(f"Dialogue: 1,{ass_time(t)},{ass_time(t + d)},Sub,,0,0,0,,{wrap(s, 20).replace(chr(10), chr(92) + 'N')}")
        t += d
    open(ass, "w", encoding="utf-8").write("\n".join(lines))
    imgs = fetch_fn(keywords or [], tmp)
    sub = f"subtitles={ass}:fontsdir=/usr/share/fonts/truetype/dejavu"
    enc = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-threads", "1",
           "-x264-params", "rc-lookahead=0:sync-lookahead=0:bframes=0", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", out]
    if imgs:
        d = (total + 0.5) / len(imgs)
        nf = max(int(d * 15), 15)
        cmd = ["ffmpeg", "-y", "-threads", "1"]
        for p in imgs:
            cmd += ["-i", p]
        cmd += ["-i", audio]
        parts = []
        for i in range(len(imgs)):
            zoom = f"min(zoom+0.0012,1.2)" if i % 2 == 0 else f"if(eq(on,0),1.2,max(zoom-0.0012,1.0))"
            parts.append(f"[{i}:v]scale=864:1536:force_original_aspect_ratio=increase,crop=864:1536,setsar=1,"
                         f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={nf}:s=720x1280:fps=15,"
                         f"eq=brightness=-0.22:saturation=0.9,"
                         f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(nf / 15 - 0.4, 0):.2f}:d=0.4[v{i}]")
        concat = "".join(f"[v{i}]" for i in range(len(imgs)))
        parts.append(f"{concat}concat=n={len(imgs)}:v=1:a=0[bg];[bg]{sub}[vout]")
        cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", f"{len(imgs)}:a"] + enc
    else:
        color = COLORS[sum(map(ord, job_id)) % len(COLORS)]
        cmd = ["ffmpeg", "-y", "-threads", "1", "-f", "lavfi", "-i",
               f"color=c={color}:s=720x1280:r=15:d={total + 0.5:.2f}", "-i", audio, "-vf", sub,
               "-tune", "stillimage"] + enc
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
    try:
        urllib.request.urlopen(req, timeout=120).read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"upload {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}")
    return f"{SB_URL}/storage/v1/object/public/{BUCKET}/{name}"


RENDER_LOCK = threading.Lock()


RENDER_LOCK = threading.Lock()


def work(job_id, title, script, keywords=None):
    with RENDER_LOCK:
        try:
            print("job start", job_id, keywords, flush=True)
            path = render(job_id, title, script, keywords=keywords)
            JOBS[job_id] = {"status": "done", "url": upload(job_id, path)}
            print("job done", job_id, flush=True)
        except Exception as e:
            err = str(e)
            if hasattr(e, "stderr") and e.stderr:
                err += " | " + e.stderr.decode("utf-8", "ignore")[-300:]
            print("job error", job_id, err[:600], flush=True)
            JOBS[job_id] = {"status": "error", "error": err[:300]}


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
    threading.Thread(target=work, args=(job_id, body.get("title", ""), body["script"], [k for k in re.split(r"[,;\n]", body.get("keywords", "") or "") if k.strip()]), daemon=True).start()
    return jsonify(id=job_id)


@app.get("/status/<job_id>")
def status(job_id):
    return jsonify(JOBS.get(job_id, {"status": "unknown"}))

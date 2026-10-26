"""Bot quản lý kênh: thống kê YouTube, chèn link tiếp thị, gợi ý trả lời bình luận, báo cáo tuần.

Chạy: python bot/bot.py [stats|affiliate|comments|report|draft_posts|publish_posts|all]
Với YouTube bot chỉ ĐỌC bằng khóa API công khai; không đăng, không trả lời, không sửa video.
Bài viết Facebook: bot soạn nháp vào tab "Bai viet" (Chờ duyệt); chỉ đăng bài bạn đã chuyển sang "Chờ đăng".
Mọi kết quả ghi vào Google Sheet để bạn duyệt.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse

import requests

SHEET = os.environ.get("SHEET_ID", "")
YT_KEY = os.environ.get("YOUTUBE_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
SA_JSON = os.environ.get("GOOGLE_SA_JSON", "")
FB_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")
FB_PAGE = os.environ.get("FB_PAGE_ID", "1401373186393078")
FB_API = "https://graph.facebook.com/v21.0"
PIXABAY = os.environ.get("PIXABAY_API_KEY", "")
POST_TAB = "Bai viet"
MAX_POSTS_PER_DAY = int(os.environ.get("MAX_POSTS_PER_DAY", "2"))
MAX_OPEN_DRAFTS = 4
PEAK = ((11 * 60 + 30, 13 * 60), (19 * 60 + 30, 22 * 60))
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
TZ = dt.timezone(dt.timedelta(hours=7))
DISCLOSURE = "(Link tiếp thị liên kết: mình có thể nhận hoa hồng khi bạn mua qua link, giá bạn trả không đổi.) #quảngcáo"
AFF_MARK = "AFF"
BOT_TAG = "[BOT]"

_creds = None


def now():
    return dt.datetime.now(TZ)


# ---------------------------------------------------------------- Google Sheets
def _headers():
    global _creds
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    if _creds is None:
        _creds = service_account.Credentials.from_service_account_info(
            json.loads(SA_JSON), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    if not _creds.valid:
        _creds.refresh(Request())
    return {"Authorization": "Bearer " + _creds.token}


def sheet_get(rng):
    r = requests.get(f"{SHEETS}/{SHEET}/values/{urllib.parse.quote(rng)}", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json().get("values", [])


def sheet_put(rng, values):
    r = requests.put(f"{SHEETS}/{SHEET}/values/{urllib.parse.quote(rng)}", headers=_headers(),
                     params={"valueInputOption": "RAW"}, json={"values": values}, timeout=30)
    r.raise_for_status()


def sheet_append(rng, values):
    r = requests.post(f"{SHEETS}/{SHEET}/values/{urllib.parse.quote(rng)}:append", headers=_headers(),
                      params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                      json={"values": values}, timeout=30)
    r.raise_for_status()


def cell(row, i):
    return row[i] if len(row) > i and row[i] is not None else ""


# ---------------------------------------------------------------- Gemini
def gemini(prompt, json_mode=False, tokens=900):
    if not GEMINI_KEY:
        raise RuntimeError("thiếu GEMINI_API_KEY")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.6, "maxOutputTokens": tokens}}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    last = None
    for attempt in range(3):
        r = requests.post(url, params={"key": GEMINI_KEY}, json=body, timeout=60)
        if r.status_code in (429, 500, 502, 503):
            last = RuntimeError(f"Gemini {r.status_code}")
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    raise last


def gemini_json(prompt):
    text = gemini(prompt, json_mode=True)
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


# ---------------------------------------------------------------- dữ liệu video
def yt_id(post_cell):
    m = re.search(r"youtu\.be/([\w-]{11})", post_cell or "") or re.search(r"[?&]v=([\w-]{11})", post_cell or "")
    return m.group(1) if m else ""


def load_videos():
    rows = sheet_get("'Noi dung'!A2:L300")
    out = []
    for i, r in enumerate(rows):
        if not cell(r, 3):
            continue
        out.append({"row": i + 2, "topic": cell(r, 2), "title": cell(r, 3), "desc": cell(r, 5),
                    "status": cell(r, 8), "post": cell(r, 9), "mark": cell(r, 11), "yt": yt_id(cell(r, 9))})
    return out


def yt_get(path, **params):
    if not YT_KEY:
        raise RuntimeError("thiếu YOUTUBE_API_KEY")
    r = requests.get("https://www.googleapis.com/youtube/v3/" + path, params={**params, "key": YT_KEY}, timeout=30)
    r.raise_for_status()
    return r.json()


def num(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- 1) thống kê
def task_stats():
    vids = [v for v in load_videos() if v["status"] == "Đã đăng" and v["yt"]]
    if not vids:
        print("stats: chưa có video YouTube đã đăng")
        return
    channel_id = ""
    for k in range(0, len(vids), 50):
        chunk = vids[k:k + 50]
        data = yt_get("videos", part="snippet,statistics", id=",".join(v["yt"] for v in chunk))
        by = {it["id"]: it for it in data.get("items", [])}
        for v in chunk:
            it = by.get(v["yt"])
            if not it:
                print("stats: không thấy video", v["yt"])
                continue
            channel_id = channel_id or it["snippet"].get("channelId", "")
            st = it.get("statistics", {})
            sheet_put(f"'Thong ke'!G{v['row']}:H{v['row']}", [[num(st.get("viewCount")), num(st.get("likeCount"))]])
            v["views"] = num(st.get("viewCount"))
    if channel_id:
        ch = yt_get("channels", part="statistics", id=channel_id).get("items", [{}])[0].get("statistics", {})
        hidden = ch.get("hiddenSubscriberCount")
        subs = "" if hidden else num(ch.get("subscriberCount"))
        pct = "" if hidden else f"{min(100, round(subs / 10, 1))}%"
        sheet_put("'Bao cao'!B2:B5", [[now().strftime("%d/%m/%Y %H:%M")], [subs if subs != "" else "ẩn"],
                                      [num(ch.get("viewCount"))], [pct or "ẩn"]])
    print(f"stats: cập nhật {len(vids)} video")


# ---------------------------------------------------------------- 2) tiếp thị liên kết
def load_catalog():
    rows = sheet_get("'Affiliate'!A2:D200")
    cat = []
    for r in rows:
        link = cell(r, 2).strip()
        if link.lower().startswith("http") and cell(r, 1).strip():
            cat.append({"kw": cell(r, 0), "name": cell(r, 1).strip(), "link": link, "net": cell(r, 3)})
    return cat


def affiliate_block(picks):
    lines = ["🛒 Sản phẩm liên quan:"] + [f"• {p['name']}: {p['link']}" for p in picks]
    return "\n\n" + "\n".join(lines) + "\n" + DISCLOSURE


def task_affiliate():
    cat = load_catalog()
    if not cat:
        print("affiliate: danh mục trống (tab Affiliate)")
        return
    todo = [v for v in load_videos() if v["status"] in ("Chờ duyệt", "Chờ đăng") and not v["mark"].startswith(AFF_MARK)]
    listing = "\n".join(f"{i}. {c['name']} (từ khóa: {c['kw']})" for i, c in enumerate(cat))
    done = 0
    for v in todo:
        res = gemini_json(
            "Bạn chọn sản phẩm tiếp thị liên kết cho một video ngắn tiếng Việt.\n"
            f"Chủ đề: {v['topic']}\nTiêu đề: {v['title']}\nMô tả: {v['desc'][:400]}\n\n"
            f"Danh mục sản phẩm:\n{listing}\n\n"
            "Chỉ chọn sản phẩm THẬT SỰ liên quan trực tiếp tới nội dung video và có ích cho người xem. "
            "Không ép chọn: nếu không có thì trả về danh sách rỗng. Tối đa 2 sản phẩm.\n"
            'Trả về JSON đúng dạng: {"picks": [số thứ tự, ...]}')
        idx = [i for i in res.get("picks", []) if isinstance(i, int) and 0 <= i < len(cat)][:2]
        if idx:
            picks = [cat[i] for i in idx]
            sheet_put(f"'Noi dung'!F{v['row']}", [[v["desc"].rstrip() + affiliate_block(picks)]])
            sheet_put(f"'Noi dung'!L{v['row']}", [[AFF_MARK]])
            done += 1
        else:
            sheet_put(f"'Noi dung'!L{v['row']}", [[AFF_MARK + "-khong"]])
    print(f"affiliate: xử lý {len(todo)} video, chèn link cho {done}")


# ---------------------------------------------------------------- 3) gợi ý trả lời bình luận
def task_comments():
    vids = [v for v in load_videos() if v["status"] == "Đã đăng" and v["yt"]]
    if not vids:
        print("comments: chưa có video YouTube đã đăng")
        return
    known = {cell(r, 6) for r in sheet_get("'Binh luan'!A2:H3000")}
    added = 0
    for v in vids:
        try:
            data = yt_get("commentThreads", part="snippet", videoId=v["yt"], maxResults=30, order="time", textFormat="plainText")
        except requests.HTTPError as e:
            print("comments: bỏ qua", v["yt"], e.response.status_code)
            continue
        for th in data.get("items", []):
            top = th["snippet"]["topLevelComment"]
            sn = top["snippet"]
            cid = top["id"]
            if cid in known:
                continue
            if added >= 15:
                break
            text = sn.get("textDisplay", "")[:500]
            res = gemini_json(
                "Bạn thay chủ kênh video ngắn tiếng Việt soạn câu trả lời bình luận. Quy tắc: thân thiện, tự nhiên, "
                "tối đa 200 ký tự, tiếng Việt, không chèn link, không hứa hẹn, không đưa lời khuyên y tế hay đầu tư. "
                "Nếu bình luận là spam, quảng cáo, chửi bới hoặc không đáng trả lời thì bỏ qua.\n"
                f"Video: {v['title']}\nBình luận của {sn.get('authorDisplayName', '')}: {text}\n"
                'Trả về JSON: {"action": "reply" hoặc "skip", "reply": "câu trả lời"}')
            reply = res.get("reply", "") if res.get("action") == "reply" else "(bỏ qua: spam hoặc không cần trả lời)"
            status = "Chờ duyệt" if res.get("action") == "reply" else "Bỏ qua"
            link = f"https://www.youtube.com/watch?v={v['yt']}&lc={cid}"
            sheet_append("'Binh luan'!A:H", [[now().strftime("%d/%m/%Y %H:%M"), v["title"], sn.get("authorDisplayName", ""),
                                              text, reply, link, cid, status]])
            known.add(cid)
            added += 1
    print(f"comments: thêm {added} bình luận mới")


# ---------------------------------------------------------------- 4) báo cáo tuần
def task_report():
    vids = [v for v in load_videos() if v["status"] == "Đã đăng"]
    stats = sheet_get("'Thong ke'!G2:K300")
    rows = []
    for v in vids:
        s = stats[v["row"] - 2] if v["row"] - 2 < len(stats) else []
        total = sum(num(cell(s, i)) for i in (0, 2, 4))
        rows.append((total, num(cell(s, 1)), v["topic"], v["title"]))
    rows = [r for r in rows if r[0] > 0]
    if len(rows) < 3:
        print("report: chưa đủ dữ liệu (cần ít nhất 3 video có lượt xem)")
        sheet_put("'Bao cao'!B8", [["Chưa đủ dữ liệu: cần ít nhất 3 video đã đăng có số liệu."]])
        return
    rows.sort(reverse=True)
    table = "\n".join(f"- {t} lượt xem, {l} like | chủ đề: {tp} | {ti}" for t, l, tp, ti in rows[:20])
    res = gemini_json(
        "Bạn là cố vấn tăng trưởng cho kênh video ngắn tiếng Việt. Dựa trên số liệu dưới đây, viết nhận định ngắn gọn, "
        "chỉ dựa vào số liệu có sẵn, không bịa. Nếu mẫu quá ít, nói rõ là chưa chắc chắn.\n" + table + "\n"
        'Trả về JSON: {"report": "3-5 câu: video và chủ đề tốt nhất, điều nên thay đổi", '
        '"topics": "tối đa 3 chủ đề nên làm thêm tuần tới, ngăn cách bằng dấu phẩy"}')
    stamp = now().strftime("%d/%m/%Y")
    sheet_put("'Bao cao'!A8:B8", [["Báo cáo tuần " + stamp, res.get("report", "")]])
    cur = (sheet_get("'Xu huong'!B2") or [[""]])[0]
    old = cell(cur, 0)
    base = old.split(BOT_TAG)[0].rstrip()
    new = (base + "\n" if base else "") + f"{BOT_TAG} {stamp}: nên làm thêm {res.get('topics', '')}"
    sheet_put("'Xu huong'!B2", [[new]])
    print("report: đã ghi báo cáo và gợi ý chủ đề")

# ---------------------------------------------------------------- 5) bài viết Facebook
# Tab "Bai viet": A Ngày | B Chủ đề | C Nội dung bài | D Từ khóa ảnh | E Link ảnh | F Trạng thái | G Link bài đăng | H Ghi chú
def load_posts():
    rows = sheet_get(f"'{POST_TAB}'!A2:H500")
    return [{"row": i + 2, "date": cell(r, 0), "topic": cell(r, 1), "text": cell(r, 2), "kw": cell(r, 3),
             "img": cell(r, 4), "status": cell(r, 5), "link": cell(r, 6)}
            for i, r in enumerate(rows) if cell(r, 2).strip()]


def fetch_text(url):
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        return re.sub(r"<[^>]+>", " ", r.text)[:3500] if r.ok else ""
    except requests.RequestException:
        return ""


def pixabay_photo(keyword):
    """Trả về link ảnh Pixabay (ảnh dọc/vuông, miễn phí dùng) hoặc rỗng."""
    if not PIXABAY or not keyword:
        return ""
    try:
        r = requests.get("https://pixabay.com/api/", timeout=20, params={
            "key": PIXABAY, "q": keyword, "image_type": "photo", "orientation": "horizontal",
            "safesearch": "true", "per_page": 12, "min_width": 800})
        hits = r.json().get("hits", []) if r.ok else []
    except (requests.RequestException, ValueError):
        return ""
    return hits[0].get("largeImageURL", "") if hits else ""


def task_draft_posts():
    posts = load_posts()
    open_n = sum(1 for p in posts if p["status"] in ("Chờ duyệt", "Chờ đăng"))
    today = now().strftime("%d/%m/%Y")
    made_today = sum(1 for p in posts if p["date"].startswith(today))
    if open_n >= MAX_OPEN_DRAFTS:
        print(f"draft_posts: còn {open_n} bài chờ, chưa soạn thêm")
        return
    if made_today >= MAX_POSTS_PER_DAY + 1:
        print("draft_posts: hôm nay đã soạn đủ")
        return
    trends = fetch_text("https://trends.google.com/trending/rss?geo=VN")
    news = fetch_text("https://news.google.com/rss?hl=vi&gl=VN&ceid=VN:vi")
    hand = (sheet_get("'Xu huong'!B2") or [[""]])[0]
    recent = "\n".join("- " + p["topic"] for p in posts[-15:]) or "(chưa có)"
    res = gemini_json(
        f"Hôm nay là {today}. Bạn quản lý một Fanpage tiếng Việt về mẹo hay, đời sống, mua sắm thông minh, tin thú vị. "
        "Mục tiêu: bài viết ngắn khiến nhiều người bình luận, thích và chia sẻ. Chọn MỘT chủ đề đang được quan tâm "
        "rộng rãi từ dữ liệu bên dưới và viết bài.\n"
        f"Ưu tiên ghi tay của biên tập: {cell(hand, 0)[:600]}\n"
        f"Từ khóa thịnh hành Google Trends VN: {trends}\nTin nổi bật Google News VN: {news}\n"
        f"Các bài gần đây, KHÔNG lặp chủ đề:\n{recent}\n\n"
        "Chọn một dạng bài khác các bài gần đây: câu hỏi gây tranh luận nhẹ, mẹo 3 ý, kể chuyện ngắn, "
        "bình chọn A hay B, sự thật thú vị. Văn nói gần gũi, 400-700 ký tự, xuống dòng cho dễ đọc, 1-3 emoji, "
        "kết bằng câu hỏi mời bình luận, thêm 3-5 hashtag cuối bài. TRÁNH: chính trị, tôn giáo, tai nạn, án mạng, "
        "scandal hay buộc tội người thật, tin đồn, 18+, lời khuyên y tế hoặc đầu tư cụ thể, hứa hẹn kiếm tiền. "
        "Chỉ nêu thông tin có trong dữ liệu hoặc chắc chắn đúng, không bịa số liệu, tên người, trích dẫn. Không dùng markdown.\n"
        'Trả về JSON: {"topic": "chủ đề tối đa 10 từ", "text": "nội dung bài", '
        '"image_keyword": "1-2 từ khóa tiếng Anh đơn giản để tìm ảnh minh họa, hoặc rỗng nếu không cần ảnh"}')
    text = (res.get("text") or "").strip()
    if len(text) < 80:
        print("draft_posts: Gemini trả về bài quá ngắn, bỏ qua")
        return
    kw = (res.get("image_keyword") or "").strip()
    sheet_append(f"'{POST_TAB}'!A:H", [[now().strftime("%d/%m/%Y %H:%M"), res.get("topic", ""), text, kw,
                                        pixabay_photo(kw), "Chờ duyệt", "", ""]])
    print("draft_posts: đã soạn 1 bài nháp (Chờ duyệt)")


def in_peak():
    t = now().hour * 60 + now().minute
    return any(a <= t <= b for a, b in PEAK)


def fb_post(text, img_url):
    """Đăng lên Page. Có ảnh thì tải ảnh về rồi tải lên (không phụ thuộc hotlink). Trả về (id, link)."""
    if not FB_TOKEN:
        raise RuntimeError("thiếu FB_PAGE_TOKEN")
    if img_url:
        try:
            img = requests.get(img_url, timeout=30)
            img.raise_for_status()
            r = requests.post(f"{FB_API}/{FB_PAGE}/photos", timeout=90,
                              data={"caption": text, "published": "true", "access_token": FB_TOKEN},
                              files={"source": ("anh.jpg", img.content, "image/jpeg")})
        except requests.RequestException as e:
            print("publish_posts: lỗi ảnh, đăng bản chữ:", str(e)[:120])
            r = None
        if r is not None:
            if not r.ok:
                raise RuntimeError(f"Facebook {r.status_code}: {r.text[:300]}")
            d = r.json()
            pid = d.get("post_id") or d.get("id", "")
            return pid, f"https://www.facebook.com/{pid}"
    r = requests.post(f"{FB_API}/{FB_PAGE}/feed", data={"message": text, "access_token": FB_TOKEN}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Facebook {r.status_code}: {r.text[:300]}")
    pid = r.json().get("id", "")
    return pid, f"https://www.facebook.com/{pid}"


def task_publish_posts():
    force = os.environ.get("FORCE_PUBLISH") == "1"
    if not force and not in_peak():
        print("publish_posts: ngoài khung giờ đông người xem, để lần sau")
        return
    posts = load_posts()
    today = now().strftime("%d/%m/%Y")
    done_today = sum(1 for p in posts if p["status"] == "Đã đăng" and p["date"].startswith(today))
    queue = [p for p in posts if p["status"] == "Chờ đăng"]
    if not queue:
        print("publish_posts: không có bài nào Chờ đăng")
        return
    if not force and done_today >= MAX_POSTS_PER_DAY:
        print("publish_posts: hôm nay đã đăng đủ số bài")
        return
    p = queue[0]
    try:
        _, link = fb_post(p["text"], p["img"])
        sheet_put(f"'{POST_TAB}'!F{p['row']}:H{p['row']}", [["Đã đăng", link, ""]])
        print("publish_posts: đã đăng", link)
    except Exception as e:
        sheet_put(f"'{POST_TAB}'!F{p['row']}:H{p['row']}", [["Lỗi", "", str(e)[:200]]])
        raise


TASKS = {"stats": task_stats, "affiliate": task_affiliate, "comments": task_comments, "report": task_report,
         "draft_posts": task_draft_posts, "publish_posts": task_publish_posts}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = ["stats", "affiliate", "comments", "draft_posts"] if which == "all" else [which]
    failed = []
    for n in names:
        if n not in TASKS:
            print("không có tác vụ", n)
            failed.append(n)
            continue
        try:
            TASKS[n]()
        except Exception as e:  # một tác vụ lỗi không chặn các tác vụ còn lại
            print(f"LỖI {n}: {type(e).__name__}: {str(e)[:300]}")
            failed.append(n)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

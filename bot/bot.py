"""Bot quản lý kênh: thống kê YouTube, chèn link tiếp thị, gợi ý trả lời bình luận, báo cáo tuần.

Chạy: python bot/bot.py [stats|affiliate|comments|report|all]
Bot chỉ ĐỌC YouTube bằng khóa API công khai; không đăng, không trả lời, không sửa video.
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


TASKS = {"stats": task_stats, "affiliate": task_affiliate, "comments": task_comments, "report": task_report}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = ["stats", "affiliate", "comments"] if which == "all" else [which]
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

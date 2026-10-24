# Cài bot quản lý kênh (làm một lần, khoảng 15 phút, miễn phí)

Bot chạy trên GitHub Actions. Nó chỉ ĐỌC YouTube, không đăng bài, không trả lời bình luận, không sửa video.
Kết quả ghi vào Google Sheet để bạn duyệt.

## Bot làm gì
- Mỗi 6 giờ: lấy lượt xem, like YouTube vào tab Thong ke; chèn link tiếp thị vào mô tả video chưa đăng; gợi ý trả lời bình luận mới vào tab Binh luan.
- Thứ Hai hằng tuần: viết báo cáo vào tab Bao cao và thêm dòng "[BOT] nên làm thêm ..." vào tab Xu huong (ô B2) để video sau chọn chủ đề tốt hơn.

## Bước 1. Tạo dự án Google Cloud
1. Vào https://console.cloud.google.com, tạo dự án mới (tên tùy ý).
2. Menu "APIs & Services" > "Library": bật **YouTube Data API v3** và **Google Sheets API**.

## Bước 2. Khóa YouTube
"APIs & Services" > "Credentials" > "Create credentials" > "API key". Sao chép khóa. Nên giới hạn khóa chỉ dùng YouTube Data API v3.

## Bước 3. Tài khoản dịch vụ để ghi vào Sheet
1. "Credentials" > "Create credentials" > "Service account", đặt tên bất kỳ, bấm Done.
2. Mở tài khoản vừa tạo > tab "Keys" > "Add key" > "Create new key" > JSON. Một file .json được tải về.
3. Mở file, sao chép email dạng `ten@du-an.iam.gserviceaccount.com`.
4. Mở Google Sheet của kênh > Share > dán email đó > quyền **Editor**.

## Bước 4. Khóa Gemini
Vào https://aistudio.google.com/apikey, tạo khóa (gói miễn phí).

## Bước 5. Nhập bí mật vào GitHub
Repo `video-service` > Settings > Secrets and variables > Actions > New repository secret. Tạo 4 mục:
| Tên | Giá trị |
|---|---|
| `SHEET_ID` | `1_Ndf0h7rzrRZ1sFNEEHb_HPvK_Y6Yi8QnS_QqF1uU2Q` |
| `YOUTUBE_API_KEY` | khóa ở bước 2 |
| `GEMINI_API_KEY` | khóa ở bước 4 |
| `GOOGLE_SA_JSON` | dán TOÀN BỘ nội dung file .json ở bước 3 |

Không đưa các giá trị này vào chat hay vào mã nguồn.

## Bước 6. Chạy thử
Tab Actions > "Bot quản lý kênh" > "Run workflow" > chọn `all`. Xem log: dòng "stats:", "affiliate:", "comments:" cho biết bot làm gì.

## Thêm sản phẩm tiếp thị liên kết
Tab `Affiliate` trong Sheet: mỗi dòng một sản phẩm (từ khóa, tên, link, mạng). Bot chỉ chèn sản phẩm thật sự liên quan chủ đề video và luôn thêm dòng ghi chú quảng cáo. Với video đã đăng thì bot không sửa mô tả; link chỉ vào video chưa đăng.

## Lưu ý
- Lịch GitHub có thể trễ vài phút. Repo công khai không giới hạn phút chạy.
- Chỉ dùng link tiếp thị của chính bạn, đúng chính sách từng nền tảng, và luôn có ghi chú quảng cáo.

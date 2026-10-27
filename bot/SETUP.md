# Cài bot quản lý kênh (làm một lần, khoảng 15 phút, miễn phí)

Bot chạy trên GitHub Actions. Nó chỉ ĐỌC YouTube, không đăng bài, không trả lời bình luận, không sửa video.
Kết quả ghi vào Google Sheet để bạn duyệt.

## Bot làm gì
- Bài viết Facebook: mỗi 6 giờ bot soạn một bài nháp vào tab Bai viet (trạng thái Chờ duyệt, tối đa 4 bài chờ). Bạn duyệt bằng cách đổi sang Chờ đăng (hoặc bấm trong trang quản lý). Lúc 12:40 và 20:40 mỗi ngày bot đăng 1 bài Chờ đăng lên Page, tối đa 2 bài mỗi ngày.
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

## Bước 5b. Mã đăng bài Facebook (chỉ cần nếu muốn bot đăng bài chữ/ảnh)
1. Vào https://developers.facebook.com > My Apps > Create App (loại "Business" hoặc "Other"), đặt tên bất kỳ. Giữ app ở chế độ Development, bạn là quản trị viên Page nên dùng được.
2. Vào Tools > Graph API Explorer, chọn app vừa tạo. Ở "Permissions" thêm: `pages_show_list`, `pages_manage_posts`, `pages_read_engagement`. Bấm "Generate Access Token", đăng nhập và chọn đúng Page.
3. Đổi sang mã dài hạn: mở trình duyệt vào
   `https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=MA_NGAN_HAN`
   (APP_ID, APP_SECRET lấy ở Settings > Basic). Kết quả có `access_token` dài hạn.
4. Dùng mã dài hạn đó gọi `https://graph.facebook.com/v21.0/me/accounts?access_token=MA_DAI_HAN`. Trong danh sách, tìm Page "Hội Săn Hời & Review", sao chép `access_token` của Page. Mã Page này không hết hạn.
5. Tạo thêm secret `FB_PAGE_TOKEN` = mã Page đó. (Tùy chọn) `PIXABAY_API_KEY` = khóa Pixabay để bài có ảnh minh họa.
Bot dùng đúng Page có ID `1401373186393078`. Đổi bằng biến `FB_PAGE_ID` nếu cần. Không đưa mã vào chat hay mã nguồn.

## Bước 5c. Tự lấy link Shopee Affiliate (tùy chọn)
1. Đăng nhập https://affiliate.shopee.vn, vào mục **Open API** (menu "Công cụ" hoặc đường dẫn affiliate.shopee.vn/open_api). Nếu chưa dùng được, gửi yêu cầu cấp quyền theo hướng dẫn ngay trên trang đó.
2. Lấy **App ID** và **Secret**.
3. Tạo hai secret trong GitHub: `SHOPEE_APP_ID`, `SHOPEE_SECRET`.
Bot sẽ tìm sản phẩm Shopee liên quan, tạo link rút gọn mang mã của bạn và chèn vào mô tả video/bài viết chưa đăng, kèm ghi chú quảng cáo. Nội dung không có sản phẩm hợp lý (tin tức, cảnh báo lừa đảo...) thì bot không chèn.

## Bước 6. Chạy thử
Tab Actions > "Bot quản lý kênh" > "Run workflow" > chọn `all`. Muốn thử riêng bài viết: chọn `draft_posts` (soạn nháp), sau đó đổi một bài sang Chờ đăng và chọn `publish_posts` (chạy tay thì đăng ngay, không chờ khung giờ). Xem log: dòng "stats:", "affiliate:", "comments:" cho biết bot làm gì.

## Thêm sản phẩm tiếp thị liên kết
Tab `Affiliate` trong Sheet: mỗi dòng một sản phẩm (từ khóa, tên, link, mạng). Bot chỉ chèn sản phẩm thật sự liên quan chủ đề video và luôn thêm dòng ghi chú quảng cáo. Với video đã đăng thì bot không sửa mô tả; link chỉ vào video chưa đăng.

## Lưu ý
- Lịch GitHub có thể trễ vài phút. Repo công khai không giới hạn phút chạy.
- Chỉ dùng link tiếp thị của chính bạn, đúng chính sách từng nền tảng, và luôn có ghi chú quảng cáo.

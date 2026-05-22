# Flow v2

Web app local điều khiển [flow-py](https://github.com/eddie-fqh/flow-py) qua giao diện trình duyệt. App bọc các luồng chính của `flow-py`: đăng nhập Google Flow, kiểm tra credits, sinh video/ảnh, image-to-video, extend, upscale, camera motion/position, insert/remove object, xem workflows và tải kết quả.

---

## 1. Yêu cầu hệ thống

| Mục | Yêu cầu |
|---|---|
| OS | Windows 10/11 hoặc macOS / Linux |
| Python | **3.11+**. Trên Windows, script one-click có thể tự kéo Python portable nếu máy chưa có |
| Git | Cần để clone repo |
| Chromium | Sẽ do Playwright tự tải |
| Tài khoản Google | Đã được cấp quyền truy cập Google Flow (labs.google/fx) |
| Gemini API key | Tuỳ chọn — chỉ cần nếu muốn dùng Prompt AI dùng Gemini thật |

## 2. Chạy nhanh kiểu một phát

### Một launcher chung cho mọi hệ điều hành

Nếu máy đã có Python 3.11+, có thể dùng cùng một launcher trên Windows, macOS và Linux:

```bash
python3 scripts/run_flow_web.py
```

Launcher này tự tạo `.venv`, cài dependency, cài Chromium cho Playwright, mở trình duyệt và chạy app ở `http://127.0.0.1:8000`.
Trên Windows nếu chưa có Python 3.11, dùng script PowerShell bên dưới vì nó có thể tự kéo Python portable.

### Windows

```powershell
git clone https://github.com/ph56jk/flow-v2.git
cd flow-v2
powershell -ExecutionPolicy Bypass -File .\scripts\run_flow_web.ps1
```

Script này sẽ tự:
- chọn ổ còn nhiều chỗ trống hơn để đặt runtime nếu `C:` gần đầy
- tự kéo Python portable nếu máy chưa có Python 3.11 chuẩn
- tạo `.venv` nếu chưa có
- cài dependencies nếu thiếu hoặc vừa pull code mới
- cài Chromium cho Playwright nếu chưa có
- mở app ở `http://127.0.0.1:8000`

Nếu đã có Python 3.11 sẵn, có thể chạy chung cùng macOS/Linux:

```powershell
py -3.11 .\scripts\run_flow_web.py
```

### Windows portable: giải nén là chạy

Nếu không muốn mỗi máy lại tải Python, dependency và Chromium từ đầu, có thể build sẵn một bản portable ngay trên Windows:

```powershell
cd flow-v2
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_portable.ps1
```

Script này sẽ tạo thư mục:

```text
dist\flow-windows-portable
```

Trong đó đã có sẵn:
- Python portable
- dependency Python
- Chromium cho Playwright
- launcher `Flow v2.cmd`

Người dùng cuối chỉ cần:
1. copy hoặc giải nén thư mục đó sang máy Windows khác
2. double click `Flow v2.cmd`

Không cần clone repo, không cần cài Python, không cần chờ tải Chromium lại.

### Windows release zip: đóng gói để gửi cho người khác

Nếu muốn đóng thành một file zip để share:

```powershell
cd flow-v2
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_release.ps1
```

Script này sẽ tạo:

```text
dist\flow-windows-release.zip
```

Người nhận chỉ cần:
1. tải file zip
2. giải nén
3. double click `Flow v2.cmd`

### macOS / Linux

```bash
git clone https://github.com/ph56jk/flow-v2.git
cd flow-v2
chmod +x ./scripts/run_flow_web.sh ./scripts/run_flow_web.command
./scripts/run_flow_web.sh
```

Nếu dùng macOS và thích double-click:
- mở [run_flow_web.command](./scripts/run_flow_web.command)

Script `.sh` hiện gọi launcher Python chung nên hành vi trên macOS/Linux bám cùng một đường chạy với Windows có Python 3.11.

### Test nhanh sau khi cài

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_flow_web_tests.ps1
```

macOS / Linux:

```bash
./scripts/run_flow_web_tests.sh
```

### ⚠️ Windows lưu ý đặc biệt

- **Path cài Chromium KHÔNG được có khoảng trắng.** Thư mục `C:\Users\HAVI GROUP\...` sẽ gây lỗi `side-by-side configuration is incorrect` / `spawn UNKNOWN`. Script `run_flow_web.ps1` sẽ tự chọn path kiểu `D:\pw-flow` hoặc `C:\pw-flow` theo ổ còn trống.
- Cần **Microsoft Visual C++ Redistributable (x64)** mới nhất — Chromium yêu cầu.
- Biến môi trường `Path` **không được có entry rỗng** (dấu `;` thừa cuối chuỗi) vì sẽ gây Node.js `spawn UNKNOWN` khi Playwright launch browser.
- `flow-py` đã được đổi sang tải từ file zip GitHub trực tiếp, nên **không còn bắt buộc phải có Git** chỉ để `pip install` chạy được.
- Các script `.sh` trong repo chỉ dùng cho macOS/Linux. Trên Windows dùng PowerShell hoặc các script `scripts/setup_windows.ps1`, `scripts/run_flow_web.ps1`.
- Google Flow dùng browser automation + reCAPTCHA → **chạy ở chế độ hiện cửa sổ (không headless)** ổn định hơn nhiều so với headless.

---

## 3. Cài đặt thủ công

### 3.1. Clone repo

```bash
git clone https://github.com/ph56jk/flow-v2.git
cd flow-v2
```

### 3.2. Cài Python 3.11 (nếu chưa có)

**Windows (winget):**
```powershell
winget install --id Python.Python.3.11 -e
```

**macOS:**
```bash
brew install python@3.11
```

### 3.3. Cài Microsoft Visual C++ Redistributable (chỉ Windows)

```powershell
winget install --id Microsoft.VCRedist.2015+.x64 -e
```

### 3.4. Tạo venv và cài dependencies

**Windows PowerShell:**
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

**Windows bash / macOS / Linux:**
```bash
python3.11 -m venv .venv
source .venv/bin/activate          # mac/linux
# hoặc: .venv/Scripts/activate     # Windows bash
pip install --upgrade pip
pip install -e .
```

### 3.5. Cài Chromium cho Playwright

**Windows (BẮT BUỘC dùng path không có khoảng trắng):**
```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "C:\pw"
python -m playwright install chromium
```

**macOS / Linux:**
```bash
python -m playwright install chromium
```

---

## 4. Cấu hình

### 4.1. File `.env.local` (ở root repo)

Tạo file `.env.local` với nội dung:

```env
# Không cần env cho thao tác thường ngày:
# nhập trực tiếp trong app ở sidebar App integrations / Trello storage.
# Các biến dưới chỉ còn là fallback nâng cao nếu muốn cấu hình ngoài UI.
# PLAYWRIGHT_BROWSERS_PATH=C:\pw-flow
# GEMINI_API_KEY=AIza...
# GEMINI_MODEL=gemini-2.5-flash
# TELEGRAM_BOT_TOKEN=123456:bot-token
# TELEGRAM_CHAT_ID=@kenh_duyet_anh
# TRELLO_API_KEY=your_trello_key
# TRELLO_TOKEN=your_trello_token
# TRELLO_CARD_ID=trello_card_id_or_short_link
# TRELLO_LIST_ID=trello_list_id
# TRELLO_UPLOAD_MODE=file
```

App sẽ tự nạp file này khi khởi động nếu có, nhưng không bắt buộc. Nếu không tạo Prompt AI sẽ dùng kho skill nội bộ.
Telegram cũng không bắt buộc: nếu chưa cấu hình, app vẫn tạo ảnh bằng Flow và lưu lịch sử như bình thường.
Gemini là tuỳ chọn, chỉ dùng cho phần **AI viết prompt**. Nếu workflow chỉ là Google Sheet/Excel -> Flow -> Telegram/Trello thì chỉ cần tài khoản Flow đã đăng nhập.
Telegram và Playwright path có thể nhập trong sidebar **App integrations** rồi bấm **Lưu app**. Không cần sửa `.env.local`; API key/token được lưu trong state local của app và chỉ trả về frontend dưới dạng trạng thái đã lưu.
Trello cũng là tuỳ chọn: mở dashboard, đi tới **Trello storage**, dán API key/token, nhập board/card/list, chọn cách lưu ảnh rồi bấm **Lưu Trello**. API key lấy ở `https://trello.com/app-key`, token tạo từ link token trên trang đó. Có thể dán board URL như `https://trello.com/b/board123/demo-board`; Trello Source sẽ tự tìm card đầu tiên có attachment ảnh nếu chưa nhập card cụ thể.

### 4.2. Custom giao diện và luồng automation

Trong sidebar **Tùy biến người dùng**, có thể đổi:
- tên app / scenario
- mô tả trên thanh đầu
- nguồn prompt bằng link Google Sheet/CSV, upload `.xlsx/.csv/.tsv`, hoặc paste bảng copy từ Google Sheets
- màu chủ đạo
- tên và ghi chú từng module trong diagram
- Gemini, Telegram, Playwright path và Trello card/list dùng cho bước viết prompt, duyệt và lưu trữ
- bấm từng module để đổi loại, đổi ký hiệu, bật/tắt, thêm, xóa, nhân bản hoặc di chuyển module trong diagram

Khi dùng file/bảng prompt, app tìm cột `Prompt_Content` hoặc `Prompt`, ưu tiên các dòng có `Active = TRUE`, rồi đưa prompt đầu tiên vào ô **Tạo ảnh bằng Flow**.

Giao diện người dùng chính hiện chỉ để lộ dashboard kiểu Make. Các form Studio cũ vẫn được giữ trong code để tái sử dụng logic tạo ảnh/video khi cần, nhưng không còn là luồng thao tác chính của người dùng.

Các tuỳ chỉnh này được lưu trong trình duyệt bằng `localStorage`. Muốn mang sang máy Windows hoặc MacBook khác, bấm **Export** để tải `flow-automation-config.json`, rồi sang máy mới bấm **Import** trong cùng khu vực.

### 4.3. File `~/.flow-py/config.json` (tự sinh sau lần đăng nhập đầu)

Đảm bảo `"headless": false` để cửa sổ Chromium hiện ra và giải reCAPTCHA khi cần:

```json
{
  "headless": false,
  ...
}
```

---

## 5. Chạy app thủ công

**Windows PowerShell:**
```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "C:\pw-flow"
.\.venv\Scripts\Activate.ps1
python -m uvicorn flow_web.main:app --host 127.0.0.1 --port 8000 --reload
```

**Windows bash:**
```bash
PLAYWRIGHT_BROWSERS_PATH="C:\\pw-flow" .venv/Scripts/python.exe -m uvicorn flow_web.main:app --host 127.0.0.1 --port 8000
```

**macOS / Linux:**
```bash
source .venv/bin/activate
uvicorn flow_web.main:app --reload
```

Mở trình duyệt: http://127.0.0.1:8000

---

## 6. Cách dùng lần đầu

1. Mở http://127.0.0.1:8000
2. Dán **Project ID** của Google Flow vào ô Config → bấm **Save Config**
3. Bấm **Sign In With Google Flow** → Chromium sẽ mở ra tab đăng nhập Google
4. Đăng nhập tài khoản Google đã có quyền truy cập Google Flow
5. Sau khi đăng nhập xong, tab Chromium **được giữ nguyên** để dùng tiếp
6. Dùng các form Generate / Edit để tạo video/ảnh
7. Job chạy nền — theo dõi ở card **Luồng gần nhất**

### ⚠️ Khi gặp reCAPTCHA

Google Flow có thể bật reCAPTCHA bất chợt. Khi đó:
- **Nhìn cửa sổ Chromium** đã mở
- Tự tay bấm giải captcha (tích "I'm not a robot" hoặc chọn ảnh)
- Job sẽ tự tiếp tục sau khi captcha được giải

---

## 7. Chạy test

```bash
pip install pytest pytest-asyncio
pytest tests/
```

Hiện có 34 smoke tests cho `flow_web`.

---

## 8. Troubleshooting

| Triệu chứng | Nguyên nhân | Cách fix |
|---|---|---|
| `spawn UNKNOWN` khi launch Chromium | PATH có entry rỗng, hoặc path cài Chromium có khoảng trắng | Xoá `;` thừa cuối `Path`, dùng `scripts/run_flow_web.ps1` hoặc đặt `PLAYWRIGHT_BROWSERS_PATH=C:\pw-flow` rồi cài lại Chromium |
| `side-by-side configuration is incorrect` | Thiếu VC++ Redist hoặc path có khoảng trắng | `winget install Microsoft.VCRedist.2015+.x64` + cài Chromium vào `C:\pw-flow` |
| UI hiện "Chưa đăng nhập" dù đã đăng nhập | `flow-py` check cookies ở vị trí cũ | Patch `_storage.py` để check cả `Default/Network/Cookies` (Chromium mới) |
| "Google Flow chưa chuyển sang chế độ tạo ảnh" | UI tiếng Việt, selector không match "Image" | Đã fix trong `service.py` — nhận cả "Hình ảnh" |
| Tạo ảnh bị treo mãi ở "Kết nối Flow" | Browser cũ còn lock profile hoặc reCAPTCHA chưa giải | `taskkill /F /IM chrome.exe /T`, restart app, giải captcha khi hiện |
| Job hiển thị treo mãi ở UI | Đã fix — frontend chỉ hiện job đang chạy, ẩn failed/completed tự động |

---

## 9. Ghi chú kỹ thuật

- `flow-py` là **browser automation**, không phải official API → Google có thể đổi UI bất cứ lúc nào
- Session và project lưu tại `~/.flow-py/`
- App state lưu tại `data/state.json`
- Trên Windows, tránh tự tay tắt cửa sổ Chromium giữa chừng — để app tự quản lý
- Headless mode không khuyến khích vì reCAPTCHA sẽ luôn fail
- Bản portable/release dành cho Windows dùng `scripts/run_flow_web_portable.ps1`, nên không phụ thuộc `.venv` của máy đích

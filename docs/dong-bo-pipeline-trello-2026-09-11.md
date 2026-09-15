# Đồng bộ pipeline ảnh với 3 worker Trello (11/09/2026)

Bản ERP (agenthavi) tách khỏi flowautomation ở commit `43eb3de` (11/08/2026). Từ đó
bản Trello có 26 commit sửa luồng tạo ảnh (giao diện Flow Agent mới ở flow.google.com,
QA thiết kế, 2K từ giao diện Flow, giữ thẻ, xoay acc, tiết kiệm Gemini). Đợt này
merge toàn bộ `flowautomation@04807a5` vào agenthavi và port lại phần Trello sang ERP.
Kết quả: **bản ERP chạy y như bản Trello, chỉ khác ảnh nguồn lấy từ Task ERP và bộ
ảnh đẩy lên Task ERP.**

## Luồng một thẻ (Auto AI ERP liên tục)

1. Quét Task ERP ở cột nguồn, lấy 1 ảnh nguồn, phân loại rule sản phẩm + đọc "design
   inventory" bằng **một** lượt Gemini (cache theo ảnh trong `data/visual-rule-cache.json`).
   Thẻ đã có ≥ 3 ảnh output (`FLOW_ERP_QA_MIN_GOOD_IMAGES`) hoặc đang có ảnh chờ duyệt
   thì **bỏ qua, không tạo bù**.
2. Mở Flow Agent (UI mới flow.google.com): dẹp banner, tìm nút thêm ingredient ở
   composer, đính ảnh nguồn, gửi prompt có "design replication lock", chờ ảnh tối
   thiểu 7 phút, bấm "Try again" đúng một lần.
3. **QA Gemini** so từng ảnh với ảnh nguồn (`_validate_erp_source_artifacts_before_upload`).
   Ảnh lệch thiết kế bị ghi `dashboard_approvals[i] = rejected / source gemini_qa`,
   không đăng lên thẻ, không tạo bù. Còn < 3 ảnh đạt → job lỗi "Gemini chặn upload ERP",
   batch cho thẻ chạy lại tối đa 2 lần. Gemini không chạy được → job lỗi "Gemini QA không
   chạy được", thẻ giữ nguyên, batch chạy thẻ khác (`FLOW_ERP_QA_STRICT=0` để vẫn đăng).
4. **2K**: tải "Download > 2K Upscaled" cho cả bộ trên giao diện Flow, ghép với từng ảnh
   bằng chữ ký thumbnail (không theo vị trí). Không tải được / ảnh nào không có 2K thật →
   `FlowUiUpscaleUnavailableError`: **giữ thẻ, không đăng ảnh 1K**, bản 1K chép vào
   `downloads/held-2k/<job8>-N.jpg`, batch Auto tự dừng (tín hiệu `khong tra ban 2k`,
   `khong co ban 2k that`, `khong upload duoc ban 2k`). API upsample cũ vẫn là bước
   dự phòng cho ảnh không ghép được.
5. Xóa watermark Gemini (removelogo) như trước, rồi **đăng từng ảnh lên Task ERP** làm
   comment duyệt 👍/👎. Upload file 2K có timeout 180 s (`ERP_UPLOAD_TIMEOUT_S`), thử 3
   lần; vẫn hỏng → giữ thẻ, không đăng link 1K.
6. Người duyệt 👍/👎 trên thẻ → archive dùng lại chính comment đã đăng, chuyển Task
   sang "Đang làm", điền SKU (không đổi so với trước).

## Acc Flow

- Quota Agent/2K bị dính → chặn acc **24 h kể từ lúc dính** (không còn mở ở 0h PT).
- 2 job liên tiếp "The agent failed" trên một acc → chặn acc, đổi acc
  (`FLOW_AGENT_FAILED_SWITCH_THRESHOLD`). Worker chỉ có một acc thì batch tự dừng với
  lỗi 429 "Tất cả Chrome profile Flow đã hết quota Agent".
- Trước khi mở Chrome, xóa cờ crash của profile để không hiện hộp thoại khôi phục.

## Gemini

- `_gemini_post_json`: chờ 429/503 theo `retry in`, hết quota ngày thì đổi sang
  `GEMINI_FALLBACK_MODELS`; ghi token/tiền theo ngày vào `data/gemini-usage.json`,
  xem qua `GET /api/gemini/usage`.
- Thinking budget: QA 512, lượt nhẹ 0 (`GEMINI_QA_THINKING_BUDGET`,
  `GEMINI_LIGHT_THINKING_BUDGET`). AI title tắt mặc định (bản ERP luôn tắt vì mô tả
  Task chỉ được thêm, không sửa).

## Endpoint mới

- `GET /api/flow/agent-ui-debug?probe=...` học lại selector khi Google đổi giao diện.
- `GET /api/gemini/usage` chi phí Gemini trong ngày.
- `POST /api/jobs/{job_id}/retry-erp-upload` tải lại ảnh từ URL Flow, QA lại, lấy 2K,
  đăng lên ERP **không tạo ảnh mới** — dùng cho thẻ bị giữ. Ảnh đã nằm trên thẻ được
  dùng lại, không đăng trùng.

## Lịch sử job

`store.trim_job_history` giữ 50 job mới nhất nhưng **không bao giờ** bỏ job đang chạy,
batch đang sở hữu job con, hoặc job còn nợ ảnh cho thẻ ERP (trần 500).

## Ghép lên nhánh hvg-pc (`agent/prd-agent-improvements-tdd`)

Bản port được ghép lại lên nhánh đang chạy ở hvg-pc (PR #7) thành nhánh
`port/dong-bo-pipeline-trello-tdd`. Chọn theo yêu cầu 11/09:

- Phần Flow Agent UI (gắn ảnh nguồn, phê duyệt, chờ ảnh, tải 2K bằng giao diện) lấy **bản
  Trello** đã chạy ổn trên 3 worker; bản riêng của hvg-pc cho các hàm đó và test của chúng bị
  thay thế. Các việc khác của nhánh (Review Lister, SKU, agent bot, chốt mạng test) giữ nguyên.
- **Bỏ bước xóa watermark** như hvg-pc đã làm 10/09 (ảnh đi thẳng từ Flow lên thẻ).
- **Không đưa ảnh 1K lên thẻ** như Trello: hết 2K thì giữ thẻ, batch dừng, lấy 2K sau bằng
  `retry-erp-upload`. `needs_agent_quota=False` của hvg-pc vẫn giữ: bước 2K (API và giao diện)
  mở Flow được cả khi acc đang bị chặn quota Agent.
- shot_rules lấy bản đồng bộ 09/09 (12 ảnh/sản phẩm), cộng alias thêm tay của hvg-pc
  ('xmas ornament', 'ornament thêu tròn', `alias_phrases` khăn tay thêu).
- Lịch sử job: giữ cách của hvg-pc (giữ lượt đang chạy, lượt còn nợ ảnh, 20 ô cho lượt có ảnh)
  cộng thêm bảo vệ batch đang sở hữu job con.

## Lần đồng bộ sau

Repo này đã có tag `flowauto-head` và commit merge, nên chỉ cần:

```bash
git fetch "C:/Users/HAVI GROUP/Downloads/flowautomation" codex/publish-flow-automation
git merge FETCH_HEAD
```

Xung đột (nếu có) chỉ còn ở phần Trello ↔ ERP tương ứng: `_archive_trello_artifacts`
↔ `publish_erp_review`/`_archive_erp_artifacts`, `_run_continuous_auto_trello_batch` ↔
`_run_continuous_auto_erp_batch`, `_trello_*` ↔ `_erp_*`. Test đối chiếu:
`tests/test_erp_trello_parity.py`.

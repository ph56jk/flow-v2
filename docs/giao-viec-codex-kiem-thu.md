# Giao việc cho Codex: kiểm thử toàn bộ tool

Bản này là **đơn đặt việc**, không phải tài liệu mô tả. Codex đọc xong thì làm
đúng những mục dưới đây rồi viết báo cáo, không sửa mã trừ khi mục nào nói rõ.

## Hàng rào — đọc trước khi làm bất cứ gì

1. **Không chạm vào Etsy thật.** Không gọi bất kỳ API Etsy nào, không mở
   `/api/etsy/browser-copy/enqueue` trên máy thật, không đụng máy ảo `etsy-vn*`.
   Muốn thử nửa Listing thì dựng bản giả (fake `post`/`fetch`) như trong
   `tests/test_listing_bridge.py` đã làm.
2. **Không ghi lên ERP thật.** Mọi lượt thử chạm ERP phải đặt
   `ERP_AGENT_DRY_RUN=1`, và chỉ được dùng board thử `PROJ-0170`.
3. **Không commit, không push.** Sửa gì thì để nguyên trong cây làm việc.
4. Bí mật (token, khoá) chỉ nằm trong biến môi trường. Không in ra báo cáo,
   không chép vào file tạm.

## Việc 1 — chạy hết bộ kiểm thử

```bash
.venv/bin/python -m pytest -q
```

Ghi lại: số test qua, số subtest, thời gian, mã thoát. Mốc hiện tại là
**1352 passed, 2796 subtests, exit 0**. Lệch một con nào cũng phải nói ra và
truy đến tận tên test.

## Việc 2 — soi lại sổ listing hai nấc

Chỗ này vừa sửa xong nên cần một cặp mắt khác. Đọc `flow_web/listing_bridge.py`
và `flow_web/agent_bot.py`, trả lời bằng chứng cứ trong mã:

- `already_listed` bật lúc **giao việc**, `listing_confirmed` bật lúc **bản
  Listing báo xong**. Có đường nào làm hai cái này lẫn nhau không?
- `confirm()` trả `unknown` khi lượt chạy rơi khỏi ảnh chụp hàng đợi. Có nhánh
  nào biến `unknown` thành `failed` (rồi giao lại lần hai) không?
- `card_stage(...)` ở cả hai chỗ gọi có đang đọc `listing_confirmed` không, hay
  còn sót một chỗ đọc `already_listed`?
- Bản Listing báo `failed` thì thẻ có ở lại *Đang review* không, và bot có nói
  lý do ra thành lời không?

## Việc 3 — công thức SKU

Đối chiếu `flow_web/sku.py` với đặc tả:
`mã sản phẩm _ số nhận dạng dự án _ số nhận dạng idea`, ví dụ `BT_1_001` …
`BT_2_051`. Viết một mẩu thử tạm (không thêm vào `tests/`) chạy qua toàn bộ ví
dụ trong đặc tả rồi xoá đi. Nói rõ ví dụ nào lệch, nếu có.

## Việc 4 — đường chat với agent

Không cần chạm ERP. Đọc `flow_web/agent_chat.py` và `flow_web/agent_brain.py`,
trả lời:

- Câu nào thì bảng từ khoá tự quyết, câu nào thì đẩy sang CLI model
  (`_worth_guessing`)?
- Trần `FLOW_AGENT_BRAIN_MAX_CALLS` có chặn được một bảng đang tán gẫu biến
  thành hoá đơn không?
- Ô nào một câu chat được phép sửa, và `action_1` có nằm ngoài danh sách đó không?

## Việc 5 — hai chỗ đã biết là hỏng, xác nhận lại chứ đừng sửa

- **Bản Listing không kéo nổi thẻ ERP.** `POST /report` với `status: completed`
  trả `erp_done_move = {"moved": false, "reason": "move_failed",
  "error": "card_missing_board_id"}`. Cố ý để nguyên: luật cột bên này đã đóng
  thẻ đúng, sửa bên kia là đặt hai người cùng kéo một thẻ.
- **Bot trên máy trung tâm không thấy `PROJ-0170`.** `scope_projects()` trả về
  `['PROJ-0013']` dù cấu hình cho phép cả `PROJ-0170` — ERP chưa thêm bot vào
  *Project User* của board đó. Đây là việc bấm nút trên ERP, không phải việc mã.

## Báo cáo

Viết ra `docs/bao-cao-kiem-thu-codex.md`, tiếng Việt, theo đúng thứ tự việc.
Mỗi kết luận đi kèm `đường/dẫn/tệp.py:dòng`. Chỗ nào không kiểm chứng được thì
nói thẳng là chưa kiểm chứng, đừng đoán.

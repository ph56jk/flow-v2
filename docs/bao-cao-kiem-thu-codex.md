# Báo cáo kiểm thử Codex

Phạm vi thực hiện: chỉ kiểm thử cục bộ và fake transport/client. Không gọi Etsy
thật, không gọi hoặc ghi ERP thật, không mở endpoint enqueue của Listing, không
commit/push. Hai phép mô phỏng có biến `ERP_AGENT_DRY_RUN=1` và không mang token.

## Việc 1 — chạy hết bộ kiểm thử

Đã chạy đúng lệnh `.venv/bin/python -m pytest -q`.

- Kết quả: **1352 passed, 2796 subtests passed, exit 0**, thời gian **444,71 giây**
  (0:07:24). Kết quả khớp tuyệt đối mốc giao việc, nên không có test lệch để
  truy tên. Các kiểm thử riêng cho cơ chế xác nhận Listing nằm tại
  `tests/test_listing_bridge.py:300` và cho sổ hai nấc tại
  `tests/test_agent_bot.py:1448`.

## Việc 2 — sổ listing hai nấc

- **Hai cờ không bị dùng lẫn cho luật đóng thẻ.** `already_listed()` chỉ hỏi
  có dòng bàn giao trong sổ hay chưa (`flow_web/agent_bot.py:1054`); nó được
  ghi ngay khi lượt giao trả về `queue_task_id`, với `confirmed=False`
  (`flow_web/agent_bot.py:1057-1066`, `flow_web/agent_bot.py:2191-2194`).
  Ngược lại, `listing_confirmed()` chỉ đọc khoá `confirmed`
  (`flow_web/agent_bot.py:1068-1081`), và khoá này chỉ được bật khi nhánh
  `done` gọi `confirm_listing()` (`flow_web/agent_bot.py:1088-1097`,
  `flow_web/agent_bot.py:2142-2144`). `already_listed` chỉ chặn giao lần hai
  rồi chuyển sang hỏi lại, không tự đóng thẻ (`flow_web/agent_bot.py:2166-2170`).

- **`unknown` không bị đổi thành `failed`, nên không giao lại lần hai.**
  `confirm()` trả `unknown` khi không có mã hàng đợi hoặc lượt không còn trong
  ảnh chụp (`flow_web/listing_bridge.py:315-335`). Trong bot, chỉ giá trị có
  khoá `failed` mới đi vào nhánh lỗi; mọi trường hợp khác, gồm `unknown`, trở
  thành `waiting` (`flow_web/agent_bot.py:2140-2147`). Dòng bàn giao không bị
  xoá trong cả nhánh hỏng/treo (`flow_web/agent_bot.py:2120-2123`), và test
  fake xác nhận `unknown` không chứa `failed` tại
  `tests/test_listing_bridge.py:338-346`.

- **Hai lời gọi trực tiếp của `card_stage(...)` trong bot đều dùng
  `listing_confirmed`, không dùng `already_listed`.** Lời gọi khi dựng trả lời
  chat dùng `self.state.listing_confirmed(task_id)` tại
  `flow_web/agent_bot.py:1616-1621`; lời gọi trong `pipeline_pass` cũng dùng
  đúng cờ này tại `flow_web/agent_bot.py:2045-2050`. `card_stage` chỉ mở
  `listing_done` khi cả ảnh đã sẵn sàng lẫn đối số `listed` là đúng
  (`flow_web/agent_bot.py:919-930`). Có thêm một lời gọi qua service, và nó
  cũng đọc `AgentBotState.listing_confirmed()` chứ không đọc biên lai bàn giao
  (`flow_web/service.py:12173-12195`).

- **Listing báo `failed` thì thẻ ở lại Đang review và lý do được nói ra ở
  summary/log.** Khi chưa xác nhận, luật cột trả “chờ listing lên shop”, không
  trả cột Hoàn thành (`flow_web/pipeline.py:294-311`); nhánh failed giữ
  `confirmed=False` và trả chính `error/status` (`flow_web/agent_bot.py:2142-2147`).
  Tổng kết ghi thành câu “listing HỎNG bên máy Etsy: …”
  (`flow_web/agent_bot.py:2334-2358`). Đây là lời trong summary/log, không phải
  một bình luận mới trên thẻ. Test fake kiểm tra không giao lại và giữ lỗi
  `chrome_crashed` tại `tests/test_agent_bot.py:1494-1519`.

## Việc 3 — công thức SKU

- Công thức đúng đặc tả: `Sku.text` tạo
  `{mã sản phẩm}_{số dự án}_{idea ba chữ số}`
  (`flow_web/sku.py:199-213`); tài liệu mã giải thích số giữa là dự án và số
  cuối đếm xuyên dự án (`flow_web/sku.py:17-25`).

- Đã tạo tạm `sku_spec_check_tmp.py` ngoài `tests/`, chạy bằng
  `.venv/bin/python sku_spec_check_tmp.py`, nhận `SKU specification examples:
  OK`, rồi xoá ngay. Mẩu thử đã kiểm cả chuỗi và parse của
  `BT_1_001`, `BT_1_002`, `BT_1_003`, `BT_1_050`, `BT_2_051`; đồng thời kiểm
  cấp mã thực tế cho dự án thứ hai sau `BT_1_050`. Không có ví dụ nào lệch.
  Các ví dụ tương ứng cũng được giữ trong test nguồn tại
  `tests/test_sku.py:214-279`.

## Việc 4 — đường chat với agent

- **Bảng từ khoá tự quyết** câu có gán ô hợp lệ (ưu tiên `parse_edits`) và câu
  khớp cụm từ khoá dài nhất trong bảng: dừng/tiếp tục/chạy, SKU, tài khoản,
  listing, trạng thái và trợ giúp (`flow_web/agent_chat.py:72-168`,
  `flow_web/agent_chat.py:393-413`). **Chỉ đẩy sang CLI model** khi người dùng
  gọi đích danh bot và: (1) bảng trả `unknown` hoặc `help`; hoặc (2) bảng trả
  lời không có action nhưng câu có vẻ là một mệnh lệnh. Điều kiện này nằm đúng
  tại `flow_web/agent_bot.py:1724-1743` và được áp dụng tại
  `flow_web/agent_bot.py:1893-1900`. Một câu hỏi thực sự như hỏi SKU/trạng thái
  không có động từ ra lệnh sẽ không gọi model (`tests/test_agent_bot.py:2383-2388`).

- **`FLOW_AGENT_BRAIN_MAX_CALLS` không phải trần toàn cục cho cả board/lượt
  quét.** Nó chặn đúng trong *một lần `chat_pass`*: kiểm tra trần trước khi gọi
  và tăng bộ đếm ở `flow_web/agent_bot.py:1755-1764`; bộ đếm được đặt lại ở đầu
  `chat_pass` (`flow_web/agent_bot.py:1823-1826`). Nhưng `run_once` gọi
  `chat_pass` cho từng cây thẻ trong `mine` (`flow_web/agent_bot.py:2274-2285`),
  nên một board có nhiều cây độc lập có thể dùng tối đa `max_calls` cho mỗi cây.
  Test hiện có chỉ xác nhận trần trong một cây (`tests/test_agent_bot.py:2416-2438`).
  Vì vậy câu trả lời là: **có chặn một cây đang tán gẫu, chưa chặn tuyệt đối cả
  board biến thành hoá đơn**.

- **Một câu chat chỉ sửa được `acc`, `product`, `sku`, `template`; `action_1`
  không nằm trong danh sách.** Danh sách đóng nằm tại
  `flow_web/agent_chat.py:186-195`; `resolve_field` từ chối tên ngoài danh sách
  (`flow_web/agent_chat.py:240-252`). Đường model lặp lại cùng hàng rào qua
  `_clean_edits` (`flow_web/agent_brain.py:248-270`), rồi chỉ gọi hook ghi cho
  các edits đã lọc (`flow_web/agent_bot.py:1684-1687`). Test khẳng định trực tiếp
  `action_1` bị loại ở `tests/test_agent_chat.py:418-428` và cả khi model cố
  trả nó ở `tests/test_agent_brain.py:113-118`.

## Việc 5 — hai chỗ đã biết hỏng (xác nhận, không sửa)

- **Bản Listing không kéo được thẻ ERP:** không thể kiểm chứng lại *endpoint
  Listing thật* `POST /report` trong workspace này: mã xử lý route đó không có
  trong cây hiện tại, và gọi hệ thống Listing/Etsy thật bị Hàng rào cấm. Tôi đã
  dùng fake fetch với đúng payload đã nêu (`completed`, `moved=false`,
  `reason=move_failed`, `error=card_missing_board_id`): `ListingBridge.confirm`
  trả `done=True, card_moved=False`, đúng cách lớp bridge chỉ đọc cờ `moved`
  (`flow_web/listing_bridge.py:337-342`). Điều đã kiểm chứng là phía này vẫn tự
  đóng thẻ sau khi Listing báo xong bằng `listing_confirmed`, nên không sửa
  người kéo thẻ ở bên Listing (`flow_web/agent_bot.py:2142-2144`,
  `flow_web/pipeline.py:294-311`). Giá trị thực tế của `reason/error` từ
  endpoint vẫn **chưa kiểm chứng**.

- **Bot trung tâm không thấy `PROJ-0170`:** đã mô phỏng chính xác ERP chỉ trả
  `PROJ-0013` trong fake client, cấu hình vẫn yêu cầu cả `PROJ-0013` và
  `PROJ-0170`, và `scope_projects()` trả `['PROJ-0013']` (chạy khô, không gọi
  ERP). Đây là đúng hành vi lọc: `scope_projects()` chỉ giữ giao giữa dự án ERP
  cho nhìn thấy và danh sách cấu hình, đồng thời cảnh báo dự án thiếu quyền
  (`flow_web/agent_bot.py:1276-1298`); test cùng nguyên tắc nằm tại
  `tests/test_agent_bot.py:863-873`. Chưa gọi ERP thật nên chưa xác minh được
  trực tiếp thành viên *Project User* trên máy trung tâm; nguyên nhân nêu trong
  đơn việc là phù hợp với mã và phép mô phỏng, và không có sửa mã nào được thực
  hiện.

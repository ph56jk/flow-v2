# PRD — Nhận ảnh idea không để lại thẻ con rỗng

Mốc số dòng: `flow_web/service.py` và `flow_web/agent_bot.py` ở 7ab3f2d
(`origin/agent/hvg-pc-dot9`). Test đỏ: `tests/test_nhan_anh_the_con_rong.py`.
Số liệu log: `briefs/ket-qua-c8-the-con-rong.md` (c8).

**Chỗ tìm hai file `briefs/`**: thư mục `briefs/` nằm **ngoài git repo**, cạnh
các worktree — `/Users/admin/orca/workspaces/agenthavi/briefs/`. Không tìm thấy
bằng `git log` là bình thường, không phải thất lạc. Cả
`ket-qua-c8-the-con-rong.md` lẫn `quyet-dinh-a6-nhan-anh-the-con-rong.md` đều
còn nguyên ở đó (kiểm 12/09).

## 0. Kết luận đọc trước

**Thẻ rỗng có bị loại khỏi fan-out không? Có.**

- `_erp_idea_skip_reason` (service.py:3511–3521) trả
  "thẻ con chưa có nội dung idea (tiêu đề/mô tả trống)" ở 3519–3520 khi
  `_erp_idea_is_blank` đúng.
- `_erp_idea_is_blank` (3169–3178): có ảnh idea riêng
  (`_erp_idea_source_attachment_id`, 3156–3167) thì không trống. Không có thì
  so `_erp_idea_text` (3147–3152, chỉ ghép tiêu đề và mô tả) với
  `ERP_IDEA_MIN_TEXT_CHARS = 8` (3154).
- "Idea 17" có 7 ký tự nên là trống. "Idea 100" có 8 ký tự nên **không** còn
  trống (xem rủi ro).
- Fan-out 4164: `skip_reason = "" if request.include_done else …`. Chỉ
  `repair_erp_idea_children` (22195) truyền `include_done=True` (22302), và chỉ
  cho thẻ có `shortfall` (22270–22283). `_erp_idea_image_shortfall` (3493) trả 0
  khi thẻ chưa có job. Thẻ rỗng không có job nên không lọt đường này.
- Bot chép Thuộc tính vào `meta` (updateTaskMeta, service.py:13915–13918; hook
  agent_bot.py:1486–1491), không vào mô tả. Thẻ rỗng có Thuộc tính vẫn là trống.
  Khớp với 02118: có Thuộc tính mà không có job.
- Bài canh: `FanOutBoQuaTheRongTests` (xanh).

Hệ quả: thẻ rỗng không tốn quota, không sinh ảnh rác. Hại thật có hai:

1. Thẻ "Idea N" trống nằm trên bảng, người phải dọn.
2. Ảnh lẽ ra thành idea thì bị kẹt. Nếu ảnh còn trên thẻ cha và chưa ai nhận,
   lượt sau đẻ thẻ con thứ hai; thẻ đầu vẫn rỗng.

**Số từ c8** (log 8000 trên hvg-pc, 19/08 19:35 → 12/09 15:34, 24 ngày, không có
tệp xoay vòng):

| Chỉ số | Số |
|---|---|
| Dòng "đã thành thẻ con" | 108 |
| Dòng "Không tạo được thẻ con cho ảnh" | 5 |
| — trước `CreateTask` (HTTP 403 khi tải ảnh nguồn, TASK-2026-04628) | 4 |
| — sau `CreateTask` ("The write operation timed out", TASK-2026-00202, 27/08 21:35:47) | 1 |
| Lần gọi `CreateTask` | 109 |
| Tỉ lệ để lại thẻ rỗng | 1/109 ≈ 0,9 % |
| Thẻ con thứ hai cho cùng ảnh | 0 |
| Deadlock, "ERP từ chối upload", 429 trên đường này | 0 |

- Ca 00202: ngay trước đó ERP trả 503 SessionStopped rồi 502. Thẻ nghi rỗng là
  TASK-2026-02118. Chưa đọc ERP để xác nhận (câu hỏi 3).
- Vì sao 00202 không đẻ thẻ thứ hai thì chưa rõ. Suy luận: ảnh đã bị gỡ khỏi
  thẻ cha, hoặc tiến trình khác đã nhận. Chưa có bằng chứng.
- Dải 02118–02127 có 4 thẻ (02119, 02121, 02123, 02126) không có dòng tạo nào
  trong log 8000. Có thể người tạo tay, có thể tiến trình khác (câu hỏi 6).

a6 chuyển lời seller (Trung Anh): #3 (lỗ số, thứ tự trên–dưới lệch) chấp nhận,
không làm. #5 (thử lại deadlock ở client) không làm.

## 1. Phạm vi

**Trong:** `flow_web/service.py`

- `_erp_intake_idea_images` (3871)
- `_erp_create_child_task` (14841)
- `_erp_attach_file_bytes` (19750), `_erp_request_json` (19571)
- `_erp_advance_task_status` (15015)

**Ngoài:**

- #3 lỗ số, #5 thử lại deadlock ở client.
- Dọn thẻ rỗng cũ trên ERP (02118 …). Không xoá thẻ nào.
- Sửa ngưỡng `ERP_IDEA_MIN_TEXT_CHARS`.
- `flow_web/agent_bot.py`: #2 sửa ở service, bot không cần đổi.
- Upload đi trước hàng rào (19766 trước 19586). Có từ trước; câu hỏi 5.

**Ràng buộc:**

- Không thêm lời gọi ERP nào vào đường nhận ảnh. ERP giả trong test ném lỗi với
  mọi lượt graphql lạ, nên thêm lời gọi là đỏ.
- Không nới quyền. Mọi đường gắn tệp khác vẫn rào như cũ. Tham số mới mặc định
  tắt.
- Giữ nguyên đầu câu log cũ: "Không tạo được thẻ con cho ảnh", "đã thành thẻ
  con". c8 đếm theo hai câu này.
- Chỉ hvg-pc chạy autorun. Đợt này không deploy.

## 2. Xếp hạng ưu tiên

| # | cải tiến | rủi ro nếu không làm | lợi ích | công | test đỏ |
|---|---|---|---|---|---|
| 4 | Lượt sau dùng lại thẻ con rỗng | Ảnh còn trên thẻ cha thì đẻ thẻ thứ hai; thẻ rỗng nằm mãi | Hết thẻ trùng; ảnh không kẹt | vừa (~40 dòng) | 5 |
| 1 | Đường nhận ảnh không đọc bảng cho thẻ vừa tạo | Bảng nóng deadlock đúng lúc thẻ mới chưa lên bảng, để lại thẻ rỗng | Bớt một lần đọc bảng mỗi ảnh; bớt một chỗ hỏng sau `CreateTask` | nhỏ | 4 |
| 2 | Log có mã thẻ con; chuyển cột hỏng không job có log | c8 phải đoán 02118 bằng dải số; bot kẹt cột không để lại dấu | Soát được bằng log | nhỏ | 2 |

## 3. #4 — Lượt sau dùng lại thẻ con rỗng

### Hiện trạng

- Khối `try` 3938–3958 chạy: tải ảnh (3939–3941) → `_erp_create_child_task`
  (3942–3944) → `_erp_attach_file_bytes` (3945–3958).
- Hỏng sau 3944 thì thẻ đã có trên ERP mà không có ảnh. Nhánh `except`
  3961–3963 chỉ log rồi `continue`.
- Ba chỗ hỏng sau `CreateTask`:
  - upload (`_erp_upload_file`, 19766);
  - hàng rào thẻ con (`_erp_assert_task_in_project`, 19586);
  - `AddTaskComment` (19638–19645).
- Lượt sau chỉ biết ảnh đã có chủ qua `_erp_idea_intake_claims` (3835–3869):
  bìa, dấu marker, tệp trong bình luận. Thẻ rỗng không mang gì, nên ảnh vẫn
  "chưa nhận" (3933) và `CreateTask` chạy lần hai.
- Docstring 3838–3842 chủ ý không giữ sổ ngoài thẻ.

### Chọn cách (câu c)

> **Đính chính 12/09 — mục này tả cách CŨ, code thật làm cách khác.**
>
> Văn bản dưới đây (dò thẻ rỗng qua sáu điều kiện trên `taskDetail`) là
> phương án ban đầu. Bộ test đỏ `tests/test_nhan_anh_the_con_rong.py` lại
> triển khai một cách khác, và code đã cài theo test: **ghi dấu vào mô tả
> thẻ con**.
>
> Cách đã cài (`flow_web/service.py`): lúc `CreateTask` ghi luôn
> `description=<dấu>` (hằng `ERP_IDEA_INTAKE_MARKER_COMMENT`). Lượt sau,
> `_erp_idea_marked_children` đọc dấu trên mô tả các thẻ con để biết ảnh nào
> đã có thẻ, rồi gắn ảnh vào đúng thẻ đó thay vì đẻ thẻ thứ hai. Dấu được gỡ
> trước khi nội dung tới tay người đọc hoặc tới Gemini/Flow
> (`_erp_idea_text`, `_flow_operator_erp_task_description_note`).
>
> Cách mới **tốt hơn** cách cũ ở đúng chỗ mà bảng rủi ro bên dưới nêu là
> điểm yếu: dấu buộc ảnh với **đúng** thẻ đã tạo cho nó, nên không còn cửa
> nhận nhầm thẻ "Idea N" người tạo tay (câu hỏi 2), và hai tiến trình cũng
> không ghép lệch. Đổi lại, nó cần một chỗ lưu trên thẻ — chính là mô tả.
>
> Giữ nguyên văn bản cũ bên dưới để người sau đọc được lý lẽ đã cân nhắc.
> Phần "Yêu cầu" 1–2 (sáu điều kiện, `child_details`) **không còn áp dụng**;
> các yêu cầu 3–7 vẫn đúng tinh thần.

Chọn **tìm lại thẻ rỗng trong `taskDetail` đã đọc**. Không dùng sổ cục bộ.

| Rủi ro | Sổ cục bộ (ảnh → thẻ con) | Tìm lại qua `taskDetail` (chọn) |
|---|---|---|
| Thêm lời gọi ERP | 0 | 0: `children` (3905–3909) và `taskDetail` từng thẻ con (3911–3921) đã đọc sẵn |
| Xoay vòng, tỉa sổ | Mất dòng là quay lại đẻ thẻ trùng. Phải có luật tỉa riêng (như `state.prune`, agent_bot.py:1318, tỉa theo tuổi) | Không có sổ |
| Khởi động lại | Sổ trong bộ nhớ thì mất. Ghi vào `state.json` thì thêm khoá phải di trú | Dữ liệu nằm trên ERP, không mất |
| Người xoá thẻ rỗng bằng tay | Sổ trỏ vào thẻ đã xoá: gắn ảnh hỏng mãi, hoặc phải đọc lại thẻ (thêm lời gọi) | Thẻ không còn trong `children` nên tạo thẻ mới, đúng ý người |
| Người tạo tay thẻ "Idea N" trống | Không đụng | Có thể nhận nhầm. Giảm bằng điều kiện chặt dưới đây; câu hỏi 2 |
| Hai máy hoặc hai tiến trình | Mỗi nơi một sổ, vẫn đẻ trùng | Cả hai thấy cùng thẻ rỗng. Xấu nhất: hai tệp trên một thẻ, không thêm thẻ. Chỉ hvg-pc chạy autorun; câu hỏi 6 |
| Docstring 3838–3842 | Ngược | Khớp: sự thật nằm trên thẻ |

### Yêu cầu

1. Thẻ con là "thẻ rỗng bot để lại" khi đủ **cả** các điều sau:
   - tiêu đề khớp `^Idea \d+$` (dạng `_erp_idea_intake_subject`, 3722);
   - mô tả, sau khi bỏ HTML, rỗng;
   - `cover_image` rỗng;
   - không có ảnh idea riêng (`_erp_idea_source_attachment_id` rỗng), và không
     bình luận nào có tệp;
   - đang ở cột *Cần làm* (`Open`);
   - không có job trong app (`_erp_child_job_ids` rỗng).

   `meta` được phép có, vì bot chép Thuộc tính xuống sau.
2. Chỉ dùng `child_details` đã đọc ở 3911–3921. Không đọc thêm.
3. Ảnh chưa ai nhận (sau lọc 3933) ghép lần lượt với thẻ rỗng theo thứ tự
   `children`. Mỗi thẻ rỗng nhận tối đa một ảnh mỗi lượt.
4. Ghép được thì bỏ `CreateTask`. Chạy tiếp gắn ảnh → bìa → người phụ trách như
   thẻ mới. Giữ tiêu đề cũ.
5. Log INFO riêng: `Ảnh %s thả trên %s đã gắn vào thẻ con rỗng %s (%s).`
   Không dùng câu "đã thành thẻ con", để c8 tách được hai loại.
6. Thẻ vừa được dùng lại thì không còn tính là thẻ rỗng trong fan-out của lượt
   này: bỏ nó khỏi `child_details` để fan-out đọc tươi. Nên làm; chưa có test.
   code-implementer quyết cách làm.
7. Hỏng khi gắn vào thẻ rỗng thì log như #2. Thẻ vẫn rỗng, lượt sau thử lại.
   Không tạo thẻ mới.

### Tiêu chí nghiệm thu

- `HongSauCreateTaskTests.test_hong_o_upload`, `test_hong_o_hang_rao_the_con`,
  `test_hong_o_add_task_comment`: sau hai lượt, `CreateTask` chạy đúng 1 lần.
  Ảnh nằm trên đúng thẻ đã tạo ở lượt 1.
- `DungLaiTheRongTests.test_the_rong_co_tu_truoc_duoc_dung_lai`: đã có thẻ rỗng
  (như 02118, sau khởi động lại) thì 0 `CreateTask`, ảnh lên thẻ ấy.
- `test_hai_anh_hai_the_rong_moi_the_mot_anh`: lượt 2 có 0 `CreateTask`; hai
  ảnh nằm trên hai thẻ khác nhau.
- Bài canh (xanh hôm nay, phải giữ xanh):
  - lỗi trước `CreateTask` thì lượt sau vẫn tạo thẻ như cũ;
  - thẻ có tiêu đề khác, hoặc đã rời *Cần làm*, không bị dùng lại;
  - ảnh đã có chủ thì không upload gì.

## 4. #1 — Không đọc bảng cho thẻ con vừa tạo, chỉ ở đường nhận ảnh

### Hiện trạng

- `_erp_create_child_task` (14841–14897):
  - project phải nằm trong `_erp_allowed_project_ids()` (14869–14871);
  - thẻ cha phải qua `_erp_assert_task_in_project` (14872);
  - `CreateTask` gửi `project` và `parentTask`;
  - chú thích 14866–14868 đã nói: hàng rào là thẻ cha.
- Ngay sau đó: `_erp_attach_file_bytes` (19750) → `_erp_request_json` (19571) →
  `_erp_assert_task_in_project(child)` (19586) → `_erp_task_project_id` (13671)
  đọc bảng.
- Thẻ vừa tạo thường chưa có trên bảng hay trong memo, nên lần rào này đọc tươi
  một bảng dự án đang nóng. Đây là một trong ba chỗ hỏng sau `CreateTask`
  (brief 49).

### Chứng minh "không nới quyền" (câu b)

1. `project_id` của đường nhận ảnh lấy từ `_erp_task_project_id(parent_id)`
   (4054), tức đọc bảng thật.
2. `_erp_create_child_task` chỉ gọi `CreateTask` sau khi
   `project ∈ _erp_allowed_project_ids()` (14870) và thẻ cha qua hàng rào (14872).
   Thẻ con sinh ra trong đúng project ấy, dưới thẻ cha đã rào.
3. `child_id` dùng ở 3945 là giá trị `CreateTask` trả về (rỗng thì raise ở
   14894). Nó không đến từ dữ liệu người dùng hay bình luận.
4. Vậy thẻ con chắc chắn nằm trong project được phép. Lần rào 19586 cho nó chỉ
   kiểm lại điều đã biết.
5. Các đường khác vẫn qua 19586 vì không truyền tham số mới:
   - `_erp_attach_file_from_url` (19726);
   - `_erp_attach_file_bytes_with_cover_fallback` (13047);
   - `_erp_request_json` gọi thẳng ở 5739, 5777, 5901, 15420, 15665, 15884,
     19712, 19768.

   `_erp_intake_idea_images` chỉ có một chỗ gọi (4087–4088).

### Yêu cầu

1. Thêm tham số từ khoá `created_in_project: str = ""` vào
   `_erp_attach_file_bytes` và `_erp_request_json`. Rỗng thì y như cũ.
2. `_erp_create_child_task` ghi `child_id → project` vào một tập trong bộ nhớ
   của service (ví dụ `_erp_children_created_here`). Chỉ ghi sau khi
   `CreateTask` trả id.
3. Khi `created_in_project` khác rỗng:
   - project không nằm trong `_erp_allowed_project_ids()` thì raise, không gọi
     `AddTaskComment`;
   - thẻ không có trong tập, hoặc có mà khác project, thì đi hàng rào cũ đầy đủ;
   - đủ cả hai thì bỏ `_erp_assert_task_in_project` cho thẻ này.
4. Chỉ `_erp_intake_idea_images` truyền `created_in_project=project_id`, và chỉ
   cho thẻ vừa tạo trong lượt đó. Thẻ rỗng dùng lại (#4) thì không truyền: nó đi
   hàng rào cũ, và lúc đó thẻ đã lên bảng.
5. Khởi động lại thì mất tập, và mọi thẻ rơi về hàng rào cũ. Không lúc nào
   rộng hơn hôm nay.

### Tiêu chí nghiệm thu

- `HangRaoTheConVuaTaoTests.test_nhan_anh_khong_doc_bang_cho_the_vua_tao`: bảng
  chưa liệt kê thẻ mới mà ảnh vẫn lên thẻ, và `_erp_task_project_id` không được
  gọi với mã thẻ con.
- `test_tham_so_moi_mien_doc_bang_cho_the_vua_tao`: có tham số và thẻ nằm trong
  tập thì không đọc bảng, `AddTaskComment` chạy.
- `test_tham_so_moi_van_choi_du_an_ngoai_danh_sach`: `PROJ-9999` thì
  `RuntimeError`, 0 bình luận.
- `test_tham_so_moi_khong_mien_cho_the_khong_do_app_tao`: thẻ không có trong tập
  thì đọc bảng và raise.
- Bài canh (xanh):
  - gọi mặc định vẫn rào (`test_goi_mac_dinh_van_rao_the_ngoai_bang`,
    `test_the_vua_tao_goi_mac_dinh_van_bi_rao`);
  - `_erp_attach_file_from_url` và `_erp_attach_file_bytes_with_cover_fallback`
    vẫn rào;
  - đường nhận ảnh vẫn rào thẻ cha.

## 5. #2 — Log

### Hiện trạng

- 3962: `log.warning("Không tạo được thẻ con cho ảnh %s của %s: %s", name,
  parent_id, exc)`. Thẻ đã tạo mà không có `child_id` trong log. c8 phải đoán
  02118 bằng dải số.
- `_erp_advance_task_status` (15015–15055): nhánh `except` chỉ `append_log` khi
  có `job_id`. Không có job thì im và trả False.
- Đường bot:
  - `_agent_bot_pipeline` (service.py:22687) gọi `advance_erp_pipeline(task_id)`,
    không có job;
  - `advance_erp_pipeline` (15095) gọi `_erp_advance_task_status` ở 15145 và
    không bao giờ ném. Except ngoài 15161–15166 cũng chỉ log khi có job;
  - `pipeline_pass` (agent_bot.py:2813) chỉ `log.warning` khi hook ném
    (2897–2899), mà hook không bao giờ ném;
  - `moved` False thì chỉ `mark_autorun(cooldown)` (2914–2919).
- Kết quả: bot chuyển cột hỏng vì deadlock thì không để lại dòng log nào.

### Yêu cầu

1. Khởi tạo `child_id = ""` trước `try` (3938). Giữ nguyên đầu câu 3962. Khi
   `child_id` khác rỗng, thêm đuôi
   ` (thẻ con <child_id> đã tạo, lượt sau gắn lại ảnh)`. Lỗi trước
   `CreateTask` thì câu như cũ.
2. `_erp_advance_task_status`: `job_id` rỗng mà lỗi thì ghi đúng một
   `log.warning("Không đổi được trạng thái Task %s sang “%s”: %s", target,
   status, humanize_flow_error(str(exc)))`. Có job thì như cũ.
3. Không đổi `agent_bot.py`.

### Tiêu chí nghiệm thu

- `LogTheConTests.test_hong_sau_create_task_log_co_ma_the_con`: đúng một dòng
  mang đầu câu cũ, có tên ảnh, mã thẻ cha, mã thẻ con.
- `ChuyenCotKhongJobTests.test_khong_job_ma_hong_thi_co_dung_mot_dong_log`:
  đúng 1 bản ghi WARNING của `flow_web.service`, có mã thẻ và "Working". Hàm
  trả False, không gọi `append_log`.
- Bài canh:
  - lỗi trước `CreateTask` thì log như cũ;
  - có job thì `append_log` đúng một lần với câu cũ;
  - chuyển được thì không có WARNING.

## Thứ tự làm đề xuất

1. **Đợt 1, một PR: #2 và #1.** Nhỏ, độc lập, bớt nguyên nhân. Test:
   `LogTheConTests`, `ChuyenCotKhongJobTests`, `HangRaoTheConVuaTaoTests`.
   Sau đợt này `test_hong_o_hang_rao_the_con` cũng xanh, vì #1 bỏ chính chỗ
   hỏng ấy.
2. **Đợt 2, một PR: #4.** Test: `HongSauCreateTaskTests`,
   `DungLaiTheRongTests`, `FanOutBoQuaTheRongTests`.

## Danh sách test đi kèm

Chạy từ gốc worktree:
`.venv/bin/python -m unittest tests.test_nhan_anh_the_con_rong -v`.
Hôm nay: 24 bài, 11 đỏ, 13 xanh. Hai bộ canh `tests.test_tach_khi_het_quota`
và `tests.test_quy_trinh_idea_content`: 63 bài, OK.

ERP giả ở tầng thấp (`_erp_graphql`, `_erp_upload_file`,
`_erp_task_project_id`). Nhờ vậy `_erp_create_child_task`,
`_erp_attach_file_bytes`, `_erp_request_json` và hàng rào chạy code thật.
Cài đặt đừng đi vòng qua các tầng giả này.

| Lớp / bài | Mục | Hôm nay | Đỏ vì gì |
|---|---|---|---|
| `HongSauCreateTaskTests.test_hong_o_upload` | #4 | đỏ | Lượt 2 tạo thẻ thứ hai (1 != 2) |
| `…test_hong_o_hang_rao_the_con` | #1, #4 | đỏ | Như trên; xanh sau đợt 1 hoặc đợt 2 |
| `…test_hong_o_add_task_comment` | #4 | đỏ | Như trên |
| `…test_hong_truoc_create_task_thi_luot_sau_van_tao_nhu_cu` | canh #4 | xanh | — |
| `DungLaiTheRongTests.test_the_rong_co_tu_truoc_duoc_dung_lai` | #4 | đỏ | Tạo "Idea 4" thay vì dùng 02118 |
| `…test_hai_anh_hai_the_rong_moi_the_mot_anh` | #4 | đỏ | Lượt 2 tạo thêm hai thẻ (2 != 4) |
| `…test_the_con_nguoi_da_viet_khong_bi_dung_lai` | canh #4 | xanh | — |
| `…test_the_rong_da_bi_keo_sang_cot_khac_khong_bi_dung_lai` | canh #4 | xanh | — |
| `…test_anh_da_co_the_giu_thi_khong_ghi_gi_len_the_rong` | canh #4 | xanh | — |
| `HangRaoTheConVuaTaoTests.test_nhan_anh_khong_doc_bang_cho_the_vua_tao` | #1 | đỏ | Đọc bảng với mã thẻ con vừa tạo |
| `…test_tham_so_moi_mien_doc_bang_cho_the_vua_tao` | #1 | đỏ | TypeError: chưa có `created_in_project` |
| `…test_tham_so_moi_van_choi_du_an_ngoai_danh_sach` | #1 | đỏ | TypeError; có tham số rồi thì phải là RuntimeError |
| `…test_tham_so_moi_khong_mien_cho_the_khong_do_app_tao` | #1 | đỏ | TypeError |
| `…test_nhan_anh_van_rao_the_cha` | canh #1 | xanh | — |
| `…test_goi_mac_dinh_van_rao_the_ngoai_bang` | canh #1 | xanh | — |
| `…test_the_vua_tao_goi_mac_dinh_van_bi_rao` | canh #1 | xanh | — |
| `…test_dinh_kem_tu_url_van_rao` | canh #1 | xanh | — |
| `…test_dinh_kem_co_du_phong_bia_van_rao` | canh #1 | xanh | — |
| `LogTheConTests.test_hong_sau_create_task_log_co_ma_the_con` | #2 | đỏ | Log thiếu mã thẻ con |
| `…test_hong_truoc_create_task_log_nhu_cu` | canh #2 | xanh | — |
| `ChuyenCotKhongJobTests.test_khong_job_ma_hong_thi_co_dung_mot_dong_log` | #2 | đỏ | Không có dòng log nào |
| `…test_co_job_thi_ghi_vao_job_nhu_cu` | canh #2 | xanh | — |
| `…test_khong_job_ma_chuyen_duoc_thi_khong_log_canh_bao` | canh #2 | xanh | — |
| `FanOutBoQuaTheRongTests.test_the_rong_khong_duoc_xep_job` | câu a | xanh | — |

## Rủi ro của chính đợt này

| Rủi ro | Mức | Cách giảm |
|---|---|---|
| #3 (lỗ số, thứ tự lệch) không sửa | thấp | Seller chấp nhận (a6 chuyển lời). Ghi lại để khỏi mở lại |
| #5 không làm: lỗi sau `CreateTask` vẫn xảy ra | thấp | #4 tự lành ở lượt sau; #2 cho thấy trong log |
| Nhận nhầm thẻ "Idea N" trống do người tạo | vừa | Sáu điều kiện chặt ở mục 3; câu hỏi 2 |
| Hai tiến trình cùng gắn vào một thẻ rỗng | thấp | Chỉ hvg-pc chạy autorun. Xấu nhất là hai tệp trên một thẻ, không thêm thẻ; câu hỏi 6 |
| Upload "timed out" mà ERP đã nhận tệp: tệp đỗ trên thẻ, lượt sau upload lại, `addTaskComment` nhận cả hai tệp đang đỗ (13444) | thấp | Chấp nhận hai ảnh giống nhau trên một thẻ. Không thêm lời gọi để dọn |
| Thẻ rỗng nằm lại mãi khi ảnh đã gỡ khỏi thẻ cha | thấp | Ngoài phạm vi. Không xoá tự động |
| Ngưỡng trống: "Idea 100" trở lên (8 ký tự) không còn trống, nên thẻ rỗng số ≥ 100 lọt fan-out và chạy bằng ảnh thẻ cha | vừa | Có từ trước, ngoài phạm vi. #4 làm thẻ rỗng hiếm hơn; câu hỏi 7 |
| Mất tập trong bộ nhớ khi khởi động lại | thấp | Rơi về hàng rào cũ, không rộng hơn hôm nay |
| Upload đi trước hàng rào ở mọi đường (19766 trước 19586): thẻ bị chối vẫn có tệp đỗ, không có bình luận | thấp | Có từ trước; câu hỏi 5 |
| Lượt đầu sau đợt 2 gắn ảnh vào thẻ rỗng cũ (ví dụ 02118) | thấp | Chỉ xảy ra khi có ảnh chưa ai nhận, mà hôm nay chỗ ấy cũng tạo thẻ mới; câu hỏi 3 |

## Câu hỏi cần người quyết

1. Giữ tập trong bộ nhớ của #1 không? Bỏ tập thì #1 dựa vào luồng code
   (chỉ miễn cho `child_id` vừa trả về từ `CreateTask` trong cùng lời gọi), và
   `test_tham_so_moi_khong_mien_cho_the_khong_do_app_tao` phải viết lại trước
   khi cài. Đề xuất: giữ. Ai trả lời: a6.
2. Thẻ "Idea N" trống do người tạo tay có được gắn ảnh không? `taskDetail` có
   trường `owner` không? Hiện chỉ thấy `owner` trên bình luận
   (agent_bot.py:1871, 1893). Nếu có thì thêm điều kiện "owner là tài khoản
   bot". Ai trả lời: người vận hành ERP hoặc seller.
3. Có đọc một `taskDetail` của TASK-2026-02118 và TASK-2026-00202 không? Mục
   đích: xác nhận 02118 rỗng, và ảnh 17ee9ea còn trên thẻ cha hay không. Nếu còn
   và chưa ai nhận thì lượt đầu sau đợt 2 gắn nó vào 02118. Ai trả lời: người
   dùng (được gọi ERP thật).
4. Except ngoài của `advance_erp_pipeline` (15161–15166) cũng im khi không có
   job. Gộp vào #2 không? Đề xuất: có, cùng một kiểu câu log. Ai trả lời: a6.
5. Upload đi trước hàng rào (19766 trước 19586) ở mọi đường gắn tệp. Có mở
   việc riêng không? Ai trả lời: a6.
6. Có tiến trình thứ hai chạy nhận ảnh không? Dấu hiệu: 4 thẻ 02119, 02121,
   02123, 02126 không có dòng tạo trong log 8000. Nghi 8001 hoặc máy khác. Ai trả
   lời: người vận hành hvg-pc.
7. Ngưỡng trống với "Idea 100" trở lên: có mở việc riêng không? Ai trả lời: a6.

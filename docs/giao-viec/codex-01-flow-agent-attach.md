# Giao việc Codex #01 — Sửa chỗ gắn ảnh nguồn vào panel Tác nhân của Google Flow

## Bối cảnh

Ngày 2026-09-04 chạy `/api/erp/idea-batch` cho board XMAS Ornament Thêu Tròn
(PROJ-0018). Ba thẻ con được tạo đúng, ba job ảnh **đều chết cùng một chỗ**:

```
no agent add/upload control
```

Chuỗi trước đó đã chạy đúng: bật Tác nhân → mở panel →
`_ensure_fresh_flow_agent_panel` → `_fill_flow_agent_panel_instruction` (prompt
2003 ký tự, có đủ `PRODUCT_SHOT_RULES['ornament_round']['lock']`). Chết ở bước
cuối: đính ảnh nguồn.

`/api/flow/project-debug` báo phiên Flow khoẻ (803 workflow, 1017 media) nên
**không phải lỗi đăng nhập**. Đây là lỗi tìm phần tử trên DOM.

Nghi vấn: Google Flow đã dời từ `labs.google/fx/vi/tools/flow` sang
`flow.google.com`, DOM đổi theo. Chưa xác nhận được vì mở bằng Chrome trên máy
này thì bị chặn tuổi (`flow.google.com/age-restricted`).

Bản trên máy trung tâm `C:\HaviGroup\flow-v2` có hàm này **giống hệt từng byte**
với bản repo, nên chạy bên đó cũng sẽ chết y như vậy.

## File được ghi

Chỉ `flow_web/service.py` và file test tương ứng trong `tests/`.
Đừng đụng vào file khác — tôi (Claude) đang làm phần vận hành máy trung tâm.

## Chỗ cần sửa

`flow_web/service.py`, hàm `_attach_flow_agent_source_file` (khoảng dòng 27548).
Chuỗi lỗi sinh ra ở nhánh:

```javascript
const target = controls[0];
if (!target) return { ok: false, detail: 'no agent add/upload control' };
```

Heuristic hiện tại chấm điểm nút: `nearBox` (±96px quanh ô prompt) +1000,
`addish` (regex nhãn) +500, `leftish` +120, ngưỡng > 400. Sau đó click rồi
`expect_file_chooser`; hỏng thì rơi về `_set_any_file_input()` quét
`input[type="file"][accept*="image"]` rồi `input[type="file"]`.

## Việc phải làm

1. **Quan trọng nhất — làm cho lần hỏng sau đọc được.** Khi không tìm thấy nút,
   đừng trả về một câu trống rỗng. Hãy thu và ghi log: URL trang lúc đó, số
   `input[type=file]` tìm được, và danh sách ~20 ứng viên nút gần ô prompt kèm
   `tagName`, `aria-label`, `title`, `textContent` cắt ngắn, `getBoundingClientRect`,
   điểm số đã chấm. Không có dữ liệu này thì lần tới vẫn mù.
2. **Nới rộng cách tìm** — thêm các lối vào, đừng bỏ lối cũ:
   - quét cả shadow DOM (`shadowRoot` đệ quy);
   - `input[type=file]` kể cả khi bị ẩn (`display:none`, `hidden`, size 0) —
     `set_input_files` vẫn chạy được trên input ẩn;
   - nhận thêm nhãn tiếng Việt lẫn tiếng Anh: thêm/add/upload/tải lên/đính kèm/
     ảnh/image/media/paperclip/plus;
   - `role="button"` chỉ chứa `<svg>` không có text.
3. **Hạ ngưỡng có kiểm soát**: nếu không nút nào qua 400 thì lấy nút điểm cao
   nhất còn lại thay vì bỏ cuộc — nhưng phải ghi log rõ là đang dùng nhánh dự
   phòng, và vẫn phải xác nhận `file_chooser` mở ra mới coi là thành công.

## Luật cứng (đọc `CLAUDE.md`)

- **Không nới lỏng test để cho xanh.** Assertion đỏ thì sửa code hoặc dừng hỏi.
- Không sửa `.env.local`, `data/state.json*`, `automation_center/runner/*.env`.
- Không `wrangler deploy`.
- Chú thích tiếng Việt, câu ngắn, theo giọng file xung quanh.

## Bằng chứng phải nộp

Chạy **cả năm** bộ test, dán số thật (nền: 1362 / 88 / 198 / 35 / 33):

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
(cd automation_center && ../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')
node --test --experimental-sqlite automation_center/tests/*.test.mjs
(cd _bmad/core/bmad-init/scripts && ../../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')
(cd _bmad/core/bmad-distillator/scripts && ../../../../.venv/bin/python -m pytest tests -q)
```

Bộ cuối là **pytest** thật, `unittest discover` gom 0 bài rồi in OK — xanh giả.
Lệnh node phải giữ nguyên cờ `--experimental-sqlite` và glob `*.test.mjs`.

Cuối cùng viết tóm tắt vào `docs/giao-viec/codex-01-ket-qua.md`: đã sửa gì,
test số bao nhiêu, còn gì chưa chắc.

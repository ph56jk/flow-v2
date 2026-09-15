# Giao việc vòng 3 — dự án chết trên host mới

## Vì sao còn việc sau khi đã đổi host

Đổi host mới chỉ đưa trình duyệt tới đúng nhà. Nhưng **ID dự án đang lưu
cũng đã chết**. Đo thật trên profile đăng nhập của người dùng:

| ID | Ở đâu | Kết quả trên `flow.google.com` |
|---|---|---|
| `a4737705-1551-4900-ad41-e622f15b87db` | state trên Mac | không có trong 21 dự án của dashboard |
| `42f50a6f-5ab5-407b-ade1-eb6c23158377` | `config.project_id` trên máy trung tâm | không có trong 21 dự án của dashboard |

Mở `https://flow.google.com/project/<id đã chết>` thì trang tự nhảy sang
`https://flow.google.com/404?reason=project`.

Trang 404 đó vẫn là một trang HTML bình thường: vẫn có nút, vẫn có nhãn. Cho
nên sau khi vá host, `_enable_flow_agent_mode` và `_attach_flow_agent_source_file`
sẽ **soi nút trên trang 404** rồi báo `no agent add/upload control` — vẫn hỏng,
chỉ khác là lần này chẩn đoán in ra rõ hơn. Người vận hành đọc log vẫn không
biết nguyên nhân thật là "dự án không còn".

## Việc phải làm

1. **Nhận diện trang 404 ngay sau khi `goto`.** Dấu hiệu chắc chắn nhất là URL
   cuối cùng chứa `/404` hoặc `reason=project`. Kiểm tra ở chỗ điều hướng
   (`service.py` quanh 8197, 1692, 20553), trước khi bất kỳ hàm soi nút nào chạy.

2. **Dừng sớm, báo bằng tiếng Việt, nêu đúng nguyên nhân.** Ví dụ:
   `Dự án Flow <id> không còn tồn tại (trang trả 404). Hãy chọn lại dự án trong phần cấu hình.`
   Đừng để job đi tiếp rồi chết ở tầng gắn ảnh — chết sai chỗ thì người ta sửa sai chỗ.

3. **Đừng tự ý tạo dự án mới, cũng đừng tự chọn bừa một dự án khác.** Chọn dự án
   nào là quyết định của người dùng. Việc của code là báo đúng và dừng.

4. **Test đỏ trước.** Ít nhất hai bài: một bài `goto` trả về URL `/404?reason=project`
   thì hàm điều hướng trả `False` kèm chuỗi lỗi có chữ "không còn tồn tại" và có ID;
   một bài URL bình thường thì đi tiếp như cũ.

## Luật vẫn giữ nguyên

- Không nới lỏng test cho xanh.
- Không sửa gì trong `.venv`.
- Đường gọi API vẫn giữ `labs.google` — không đụng.
- Chạy đủ năm bộ, ghi số thật vào `docs/giao-viec/codex-03-ket-qua.md`.

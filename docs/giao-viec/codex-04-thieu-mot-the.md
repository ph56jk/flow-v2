# Giao việc vòng 4 — thả 4 ảnh, chỉ sinh 3 thẻ con

## Hiện tượng

Người dùng thả **4** ảnh idea lên thẻ `TASK-2026-04628` ("Idea Phương").
Bot chỉ tự tạo **3** thẻ con. Thẻ hiển thị `0/3 việc con`. Không có báo lỗi
nào — nên nhìn vào thì tưởng bot chạy đúng.

## Nguyên nhân — đã truy ra trong code, không phải suy đoán

`flow_web/service.py:3109` trong `_erp_intake_idea_images`:

```python
product = self._erp_idea_product_image(parent_detail, images)
dropped = [item for item in images if item is not product]
```

`_erp_idea_product_image` (`service.py:3012`) chọn "ảnh sản phẩm" như sau:

- Thẻ **có ảnh bìa** → ảnh bìa là ảnh sản phẩm. Đúng: người ta đặt bìa là
  một lựa chọn có chủ ý.
- Thẻ **không có ảnh bìa** → `return images[0] if images else {}`, tức là
  **lấy đại tấm ảnh cũ nhất làm ảnh sản phẩm**.

Thẻ "Idea Phương" không có ảnh bìa (trên bảng nó hiện ra không có hình, khác
với Idea 3/4/5). Nên tấm đầu tiên trong 4 tấm bị coi là ảnh sản phẩm và bị
loại khỏi `dropped`. 4 − 1 = 3. Khớp đúng con số người dùng thấy.

Đây là chỗ bộ test hiện tại soi không ra: helper `_board` trong
`tests/test_hvg_erp_integration.py:1665` **luôn** đặt `cover_image` là một tấm
ảnh sản phẩm riêng. Không có bài nào chạy nhánh "thẻ không có bìa" — nhánh
duy nhất đang hỏng.

## Phải sửa thế nào

Không có bìa thì **đừng đoán**. Không đoán được ảnh nào là sản phẩm thì coi
như thẻ cha không có ảnh sản phẩm, và **mọi ảnh đã thả đều thành thẻ con**.

Lý do chọn hướng này chứ không phải hướng ngược lại:

- Đoán sai kiểu hiện tại thì **mất im lặng một ý tưởng** của người dùng —
  không log, không báo, không ai biết. Hỏng kiểu đó là hỏng tệ nhất.
- Đoán sai theo hướng mới thì thừa một thẻ con — thấy ngay trên bảng, xoá
  một cái là xong.
- Đường ảnh nguồn dự phòng cho thẻ con không có ảnh riêng **không đi qua hàm
  này**: `enqueue_erp_idea_jobs` lấy `source_attachments[0]` từ
  `_erp_source_and_flow_output_attachments` (`service.py:3246`). Sửa chỗ này
  không đụng vào đó.

Giữ nguyên nhánh có bìa: bìa vẫn là ảnh sản phẩm, vẫn bị loại khỏi `dropped`.

## Test đỏ trước, ít nhất ba bài

1. `_board` với `cover_image` rỗng và **4** ảnh thả → sinh đúng **4** thẻ con,
   tên `Idea 1`…`Idea 4`, mỗi thẻ mang đúng ảnh của nó và ảnh đó là bìa của nó.
   Bài này phải **đỏ** trên code hiện tại (đang ra 3).
2. `_board` có `cover_image` là ảnh sản phẩm riêng + 2 ảnh thả → vẫn đúng **2**
   thẻ con như cũ. Bài chặn hồi quy, phải xanh cả trước lẫn sau.
3. `_board` có `cover_image` trỏ đúng vào **một trong** các ảnh đã thả →
   tấm đó là sản phẩm, các tấm còn lại thành thẻ con. Chốt lại là bìa vẫn
   thắng, không phải cứ bỏ hết logic bìa đi.

Muốn thì thêm bài thứ tư: `_board` không bìa, đúng **1** ảnh → sinh **1** thẻ
con. Code hiện tại ra 0 thẻ — im lặng, không lỗi. Đó là ca tệ nhất.

## Luật vẫn giữ nguyên

- Không nới lỏng test cho xanh. Không sửa `_board` cũ theo kiểu làm bài cũ
  hết ý nghĩa — thêm tham số/helper mới thì được, đổi kỳ vọng bài cũ thì không.
- Chạy đủ năm bộ, ghi số thật vào `docs/giao-viec/codex-04-ket-qua.md`.

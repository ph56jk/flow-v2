# Kéo thẻ về *Cần làm* thì trả lại tên cũ

## Chuyện đang xảy ra

Bot đánh số xong thì **đổi tên thẻ thành mã**: `Vòng cổ mèo len` biến thành
`OL_1_050`. Tên gốc được cất vào `ten_cu:` trong khối *Thuộc tính* của chính
thẻ, trước khi phá (`service.py`, lượt ghi thuộc tính).

Người vận hành kéo nhầm một thẻ sang *Đang làm* thì bot đánh số ngay — làn
nhanh chỉ mất vài giây. Kéo ngược về *Cần làm* thì **tên vẫn là mã**, và họ
phải mở `ten_cu:` ra chép tay lại. Mỗi lần nhầm là một lần sửa tay.

## Muốn gì

Kéo thẻ về *Cần làm* → tên thẻ **tự về lại tên cũ**.
Kéo lại sang *Đang làm* → tên **tự về lại đúng mã cũ**, không cấp số mới.

Người đặt việc đã chốt: **trả tên, giữ mã trên thẻ**. Mã `custom_sku` và dòng
`ten_cu:` đứng nguyên, không ai đụng vào. Sổ số không dịch, nên không có
đường nào sinh ra mã trùng.

## Luật

1. **Trả tên** khi cả bốn điều cùng đúng: thẻ mang mã; thẻ đang ở *Cần làm*;
   tên thẻ **đúng bằng** mã; `ten_cu:` có chữ. Tên mới là `ten_cu:`.
2. **Đổi lại thành mã** khi: thẻ mang mã; thẻ ở *Đang làm* trở đi; tên thẻ
   **khác** mã; và tên hiện tại **đúng bằng** `ten_cu:`. Đây chính là luật
   `name_left_behind` đang có, nay thêm điều kiện cột.
3. Người gõ một cái tên **thứ ba** vào thì bot không đụng — cả hai chiều. Tên
   người đặt không phải thứ bot được đè lên.
4. Không có `ten_cu:` thì không trả tên: không biết trả về đâu.
5. Không đụng `custom_sku`, không đụng `ten_cu:`, không đụng sổ số. Một lượt
   trả tên chỉ là **một** request đổi tiêu đề.
6. Lượt chạy khô (`dry_run`) không ghi gì; ERP đang chặn (429) thì thẻ vào
   `rename_failed`, lượt sau chữa — giống hệt lượt chữa tên đang có.
7. Thẻ ở *Đã huỷ* không trả tên: cột ấy máy không đụng vào.

## Làn nhanh phải **thấy** được

Đây là chỗ dễ sót. `hot_clusters` chỉ nhặt cụm có thẻ **chưa có mã** ở *Đang
làm*. Thẻ vừa kéo về *Cần làm* thì đã có mã rồi, nên cụm ấy không bao giờ vào
danh sách ứng viên — luật viết xong vẫn không chạy.

Ba chỗ phải mở:

* `restore_clusters(rows, user)` — cụm có thẻ ở *Cần làm*, có mã, tên đúng
  bằng mã, gắn bot. Đọc từ dòng bảng, không tốn request.
* `repair_clusters(rows, user)` — cụm có thẻ ở *Đang làm*, có mã, tên khác mã,
  gắn bot. Cho chiều về.
* `sku_fill_is_due` — cổng đọc cây. Hiện chỉ gật khi có thẻ **chờ mã**; phải
  gật thêm khi có thẻ **chờ chữa tên**, và ở đó mới đọc được `ten_cu:` để áp
  đúng luật 3.

Dòng `taskBoard` không có `ten_cu:`, nên hai hàm cụm trên là **cổng thô**:
chúng chỉ chọn cụm đáng đọc cây. Luật thật chạy sau khi đã có cây.

Cụm đọc cây rồi mà không có gì để ghi thì rơi vào `_stuck` 180 giây như mọi
cụm khác — đó là cái chặn giá, đừng bỏ.

Không sửa `board_is_hot`. Người kéo thẻ là `modified` đổi, `board_stamp` đổi,
bảng tự vào nhịp ấm 5 giây. Bắt bảng nóng vĩnh viễn vì một cái tên lệch là
đốt 4 lượt đọc mỗi phút cho một việc không bao giờ xong.

## Giá

Một thẻ trả tên tốn đúng như một thẻ `wrong` đang tính: một `taskFull` cộng
một lượt đổi tên. `fill_cost(..., wrong=...)` cộng thêm 2 cho mỗi thẻ ấy, nên
chỉ cần đếm chúng vào `wrong` là xong, không phải sửa công thức.

### Đo trên bảng thật trước khi deploy

Chạy `pc_soi_ten_lech.py` (chỉ đọc) trên **cả 29 bảng** của hvg-pc:

- 0 thẻ chờ trả tên.
- 2 thẻ ở *Đang làm* mang tên khác mã, đều trên `PROJ-0013`:
  `TASK-2026-00615` (mã `HA_1_001`, tên `KT_1_001`) và `TASK-2026-00650`
  (mã `HA_5_005`, tên `idea 7`).

Soi tiếp `taskFull` hai thẻ đó: **cả hai đều không có `ten_cu`**. Luật đòi
`subject == ten_cu` mới chữa, nên bot **không đụng** tới chúng. Tức thay đổi
này không đổi tên thẻ thật nào đang có trên hệ thống.

Tải phụ: cụm gốc `TASK-2026-00202` thành ứng viên vĩnh viễn — mỗi 180 giây
một lượt `taskFull` rồi `not written` rồi `_stuck` nghỉ tiếp. Khoảng
0,33 lượt/phút, trên nền 40,7/50. Chấp nhận được; `_stuck` chính là cái giá
đỡ cho mọi cụm bị nhặt nhầm kiểu này.

## Test đỏ

`tests/test_tra_ten_can_lam.py`:

1. Thẻ có mã, ở *Cần làm*, tên bằng mã, có `ten_cu` → `plan.restores` có nó,
   `name_to_restore` bằng `ten_cu`.
2. Cùng thẻ ấy nhưng ở *Đang làm* → **không** trả tên.
3. Thẻ ở *Cần làm*, tên là một chữ thứ ba → không đụng.
4. Thẻ ở *Cần làm*, không có `ten_cu` → không đụng.
5. Thẻ ở *Cần làm*, tên bằng mã → **không** vào `plan.repairs` (chống hồi quy:
   luật cũ sẽ đổi nó lại thành mã, phá đúng tính năng này).
6. Thẻ ở *Đang làm*, tên bằng `ten_cu` → vẫn vào `plan.repairs` như cũ.
7. Thẻ ở *Đã huỷ*, tên bằng mã → không trả tên.
8. `fill_task_skus` gọi đổi tiêu đề đúng **một** lần, đúng tên cũ, và
   **không** ghi lại `custom_sku` hay `ten_cu`.
9. `dry_run=True` → không gọi đổi tiêu đề.
10. ERP chặn 429 giữa lượt → thẻ vào `rename_failed`, không mất tên.
11. `restore_clusters` nhặt đúng cụm gốc từ dòng bảng; thẻ không gắn bot thì bỏ.
12. `repair_clusters` nhặt cụm chiều về.
13. `sku_fill_is_due` gật cho cây chỉ có thẻ chờ trả tên.
14. Làn nhanh: bảng chỉ có thẻ chờ trả tên vẫn ra ứng viên, và giá tính thêm.

## Câu hỏi đã có trả lời

* *Có xoá `ten_cu:` sau khi trả tên không?* — **Không.** Xoá đi thì chiều về
  mất căn cứ: luật 2 cần `ten_cu` để biết cái tên đang đứng đó là của bot hay
  của người.
* *Có trả cả mã về không?* — **Không.** Người đặt việc chọn giữ mã.

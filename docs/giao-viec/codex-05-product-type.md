# Giao việc vòng 5 — thẻ khai `product_type` mà bot không đọc

## Người dùng nói gì

Anh Nguyễn Trung Anh: *"sản phẩm thì khai báo theo cái `product_type` rồi nhé"*
và *"cái sku cũng chưa thấy thay đổi zì"*.

Tức là trên bảng thật, sản phẩm được khai bằng thuộc tính **`product_type`**
trong khối *Thuộc tính* của thẻ, không phải bằng chữ `product`.

## Phần tôi đã sửa xong — ĐỪNG ĐỤNG LẠI

`flow_web/erp_meta.py:67` chỉ đọc `product`, `san_pham`, `sanpham`,
`product_name`, `productname`. Không có `product_type`. Nên `meta.product`
trả rỗng, và `sku.py:1055` bỏ thẻ với lý do *"chưa có product để tra bảng SKU"*.

Tôi đã thêm `product_type`, `producttype`, `loai_san_pham`, `loaisanpham` vào
cuối `PRODUCT_KEYS` — đặt cuối để `product` vẫn thắng khi thẻ mang cả hai — và
đã thêm 3 bài trong `tests/test_erp_meta.py` (đỏ trước, xanh sau).
**File `flow_web/erp_meta.py` và `tests/test_erp_meta.py` là của tôi, đừng sửa.**

## Phần của anh — bộ nhận diện sản phẩm vẫn chưa đọc khối thuộc tính

`_erp_idea_rule_card` (`flow_web/service.py:2691`) dựng cái thẻ mà bộ nhận
diện đọc. Ô `name` được chọn thế này (`service.py:2745`):

```python
"name": next(
    (
        text
        for text in (source_subject, parent_subject, board)
        if self._erp_idea_subject_says_product(text)
    ),
    parent_subject or source_subject,
),
```

Ba nguồn: tên thẻ nguồn, tên thẻ cha, tên bảng. **Không có khối thuộc tính.**
Nên người dùng khai `product_type: Ornament Thêu Tròn` đúng chỗ mà bộ chọn
`PRODUCT_SHOT_RULES` vẫn không thấy, vẫn phải đoán theo tên thẻ và tên bảng.
Đó cũng là lý do bảng `XMAS Tạp Dề` xưa nay không khớp rule nào.

### Phải sửa thế nào

Đặt **sản phẩm đã khai lên đầu** danh sách ưu tiên, trước cả tên thẻ nguồn:

1. `task_meta(source_detail).product` — thẻ tự khai cho chính nó;
2. `task_meta(parent_detail).product` — thẻ cha khai cho cả cụm;
3. rồi mới `source_subject`, `parent_subject`, `board` như cũ.

Lý do thứ tự này: khai tay là câu người ta **cố ý** gõ vào đúng ô dành cho nó.
Tên thẻ và tên bảng chỉ là chỗ đoán. Đoán không được phép thắng lời khai.

Dùng `from .erp_meta import task_meta` — hàm đã có sẵn, đừng viết lại.

Lưu ý: hai giá trị khai tay này **không** phải qua
`_erp_idea_subject_says_product`. Cái hàm đó để lọc xem một cái tên có *tình cờ*
nói ra hàng gì không; lời khai thì không cần lọc — có chữ là dùng.

### Test đỏ trước, ít nhất ba bài

1. Thẻ cha khai `product_type: Ornament Thêu Tròn`, tên thẻ cha là `Idea Phương`
   (không nói ra hàng gì) → `_erp_idea_rule_card` trả `name` là
   `Ornament Thêu Tròn`. Phải **đỏ** trên code hiện tại.
2. Thẻ con tự khai `product_type` khác thẻ cha → thẻ con thắng.
3. Không thẻ nào khai gì → vẫn rơi về tên thẻ / tên bảng đúng như cũ. Bài chặn
   hồi quy, xanh cả trước lẫn sau.

## Còn một câu phải trả lời người dùng, không phải sửa code

*"cái sku cũng chưa thấy thay đổi zì"* — một phần là **đúng thiết kế**, không
phải lỗi:

- `sku.py:1049`: mã chỉ phát cho thẻ **đã sang cột *Đang làm***. Thẻ còn ở
  *Cần làm* nằm ở `plan.skipped`, không phải bị bỏ quên.
- `fill_task_skus` (`service.py:12356`, docstring): **thẻ gốc của cụm không bao
  giờ được cấp mã** — nó là chỗ khai sản phẩm và chỗ chứa ảnh. Anh Trung Anh
  đang nhìn ô `sku` trên chính thẻ `TASK-2026-04628` là thẻ gốc, nên ô đó sẽ
  không bao giờ đầy.

Đừng sửa hai luật này. Chỉ cần chắc rằng sau khi vá `product_type`, thẻ con
kéo sang *Đang làm* thì nhận được mã đúng tiền tố của Ornament Thêu Tròn.

## Luật vẫn giữ nguyên

- Không nới lỏng test cho xanh.
- Chạy đủ năm bộ, ghi số thật vào `docs/giao-viec/codex-05-ket-qua.md`.

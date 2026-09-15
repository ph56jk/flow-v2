# Runbook: đăng duyệt ERP cho một ảnh, không cho cả thẻ

Runbook này trả lời đúng một câu hỏi: **tôi vừa sửa một ảnh, làm sao đăng lại
mỗi ảnh ấy?**

## Câu quan trọng nhất

`POST /api/jobs/<job_id>/erp-review/publish` **gọi trống là lệnh "đăng bù mọi
ảnh còn thiếu"**, không phải lệnh "đăng cái tôi vừa sửa". Muốn hẹp thì phải nói
hẹp, bằng `indices`.

Đây là sự cố thật, không phải lo xa: một lần gọi định thay **một** ảnh đã đăng
**sáu**, đưa thẻ từ 12 tệp đính kèm lên 17. Lý do là
`reopen_watermark_rejections` xoá entry duyệt, nên mọi chỉ số vừa mở lại đều
thoả cả ba điều kiện "hãy đăng tôi": chưa có quyết định, chưa có bình luận,
chưa nằm trên thẻ.

## Cách gọi

Sửa ảnh ở vị trí 3 rồi đăng lại đúng nó:

```sh
curl -sS -X POST "http://127.0.0.1:8000/api/jobs/$job_id/erp-review/publish" \
  -H 'content-type: application/json' \
  -d '{"indices": [3]}'
```

Đăng bù cả lượt — chỉ dùng khi thật sự muốn thế:

```sh
curl -sS -X POST "http://127.0.0.1:8000/api/jobs/$job_id/erp-review/publish" \
  -H 'content-type: application/json' -d '{}'
```

Chỉ số đếm từ **0**, theo đúng thứ tự `job.artifacts`.

## Đọc câu trả lời

```json
{ "published": 1, "skipped": 5, "indices": [3], "failed": 0, "pending": 0 }
```

- `indices` — danh sách đã thu hẹp. **Rỗng nghĩa là bạn vừa ra lệnh đăng bù
  mọi ảnh**, không phải "không đăng gì". Nhìn trường này trước khi nhìn
  `published`.
- `skipped` — số chỉ số đủ điều kiện đăng nhưng bị `indices` loại ra. Con số
  này lớn mà bạn không cố ý thu hẹp thì đang có chuyện.
- `published` / `failed` / `pending` — như cũ.

## Chỉ số sai thì báo lỗi, không im lặng

Chỉ số ngoài `[0, số ảnh)` trả **400** kèm khoảng hợp lệ, và **không đăng gì
cả** — cả lệnh hỏng chứ không đăng một nửa:

```text
Chỉ số ảnh 12 nằm ngoài lượt chạy này (có 5 ảnh, hợp lệ 0..4).
```

Chỉ số không đọc được (chuỗi, `null`) cũng 400. `indices` không phải danh sách
thì 400. `indices` là danh sách **rỗng** thì hiểu như không truyền — tức là
đăng bù tất cả.

## Liên quan

- Cờ `needs_manual_review` chặn đường API nâng 2K, không chặn lệnh đăng này:
  xem `docs/runbook-go-co-manual-review.md`.
- Yêu cầu gốc: A6 trong `tasks/prd-agent-improvements.md`.

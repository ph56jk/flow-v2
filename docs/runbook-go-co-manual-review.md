# Runbook gỡ cờ `needs_manual_review` cho Flow 2K

Runbook này chỉ dành cho người vận hành trong maintenance window. Đừng sửa
`data/state.json` khi `com.havigroup.flow-v2` còn chạy: service giữ snapshot
trong RAM và một lần ghi sau đó có thể ghi đè sửa đổi tay.

## Khi nào cần làm

Một media chỉ được gỡ cờ khi đã xác minh nguyên nhân Flow/reCAPTCHA đã được xử
lý hoặc người vận hành chủ động muốn thử lại. Gỡ record làm lần upscale tự động
kế tiếp của đúng `task_id + job_id + media_id` bắt đầu lại từ 0; vì vậy không
dùng nó chỉ để bỏ qua cảnh báo.

Watcher không ghi một dòng `skipped` riêng ở mỗi chu kỳ. Nó chỉ ghi warning
`Cần xem thủ công` một lần khi record chạm ngưỡng. Vì vậy cần tra state file để
biết media nào còn bị chặn, thay vì suy ra từ việc log im lặng.

## Xác định record cần gỡ

Theo `flow_web/paths.py:19-20`, file mặc định là `data/state.json` (nếu runtime
đặt `FLOW_DATA_DIR` thì dùng `<FLOW_DATA_DIR>/state.json`). Record nằm tại:

```text
jobs[] (job.id == <job_id>)
  .result.flow_upsample_recaptcha.media[
    "<task_id>::<job_id>::<media_id>"
  ]
```

Record đang chặn có `needs_manual_review: true` và `next_retry_at` không rỗng.
Chỉ đọc, không hiển thị toàn bộ state có thể chứa cấu hình nhạy cảm:

```sh
task_id='TASK-2026-02120'
job_id='f19b9b24f4654bac80f2ce37e7485711'
media_id='ecfa92a6-ec9e-45b2-a82e-afeb692eb5ec'
jq --arg job "$job_id" --arg key "$task_id::$job_id::$media_id" \
  '.jobs[] | select(.id == $job) | .result.flow_upsample_recaptcha.media[$key]' \
  data/state.json
```

Ghi lại đủ ba ID. Không gỡ một record nếu ID trong value (`task_id`, `job_id`,
`media_id`) không khớp chính xác với key; đây là hàng rào tránh nhầm job/media.

## Quy trình an toàn bằng script (khuyến nghị)

1. Mở maintenance window và dừng service theo quy trình vận hành được duyệt.
   Trên máy hiện tại, cần đảm bảo `launchctl print
   gui/501/com.havigroup.flow-v2` không còn báo `state = running` trước khi sửa.
   Không chạy hai instance song song.
2. Chạy dry-run. Lệnh này chỉ đọc và in đúng record sẽ bị xoá:

   ```sh
   .venv/bin/python scripts/clear_recaptcha_manual_flag.py \
     "$task_id" "$job_id" "$media_id"
   ```

3. Kiểm tra task/job/media và `next_retry_at` trong output. Nếu đúng, chạy lại
   cùng lệnh với `--apply` **khi service vẫn đang dừng**:

   ```sh
   .venv/bin/python scripts/clear_recaptcha_manual_flag.py \
     "$task_id" "$job_id" "$media_id" --apply
   ```

   `--apply` tự tạo backup cạnh state file theo tên
   `state.json.bak-clear-recaptcha-<UTC timestamp>`, rồi thay state file theo
   kiểu atomic. Không có `--apply` thì script không ghi file.
4. Đọc lại bằng lệnh `jq` ở trên. Key đã gỡ phải trả `null`; các record media
   khác và các phần `erp_review`, artifact, log của job phải còn nguyên.
5. Khởi động lại service theo quy trình vận hành được duyệt, rồi xác nhận
   `launchctl print gui/501/com.havigroup.flow-v2` báo `state = running` với
   PID mới và log không có traceback. Chỉ sau đó theo dõi một watcher pass để
   xác nhận media có thể thử lại theo chính sách hiện hành.

Nếu state nằm nơi khác, dùng `--state-file /đường/dẫn/state.json` cho cả
dry-run và apply. Script không tự dừng, tự restart hay gọi ERP/Flow API.

## Phương án thủ công (chỉ khi script không dùng được)

1. Dừng service và xác nhận không còn process như bước 1 ở trên.
2. Tạo bản sao **sau khi service đã dừng**, ví dụ:

   ```sh
   timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
   cp -p data/state.json "data/state.json.bak-manual-review-${timestamp}"
   ```

3. Trong đúng job, xoá **một entry key đầy đủ** khỏi
   `.result.flow_upsample_recaptcha.media`. Không xoá toàn bộ `jobs[]`,
   `.result`, hay state của media khác. Nếu đây là entry media cuối cùng, có
   thể xoá riêng object `.result.flow_upsample_recaptcha`.
4. Kiểm tra JSON hợp lệ trước khi khởi động lại:

   ```sh
   jq empty data/state.json
   ```

5. Thực hiện bước xác minh và khởi động lại ở bước 4-5 của quy trình script.

Nếu JSON sai, record không rõ, hoặc service chưa dừng hẳn: dừng lại, khôi phục
từ backup thay vì đoán hoặc sửa tiếp. Không dùng `git reset`, không commit/push
để rollback state vận hành.

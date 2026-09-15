# Giao việc cho Codex: xác minh 2 lỗi vận hành vừa sửa/đang treo

Bản này là **đơn đặt việc**, không phải tài liệu mô tả. Codex đọc xong thì làm
đúng những mục dưới đây rồi viết báo cáo, không sửa mã trừ khi mục nào nói rõ.

## Hàng rào — đọc trước khi làm bất cứ gì

1. **Không rewrite lịch sử git** (không amend, không rebase, không
   `reset --hard`), **không commit, không push**. Sửa gì thì để nguyên trong
   cây làm việc.
2. **Không tự điền/đoán `CF_ACCESS_CLIENT_ID`/`CF_ACCESS_CLIENT_SECRET`** trong
   `automation_center/runner/.env`. Đây là bí mật Cloudflare Access thật, chỉ
   người dùng mới được điền. Nếu còn trống thì ghi nhận rồi dừng ở đó, không
   giả lập giá trị. Không sửa nội dung `.env` — chỉ đọc.
3. **TASK-2026-02120 là tác vụ ERP thật đang chạy thật** (ảnh Flow thật, thẻ
   ERP thật). Không tự ý huỷ, xoá, hay sửa trạng thái tác vụ này trên ERP. Chỉ
   được đọc log/mã để chẩn đoán. Nếu chẩn đoán ra cần một hành động thay đổi
   trạng thái thật (huỷ tác vụ, gọi API ERP ghi đè, restart tiến trình
   flow-v2), phải DỪNG và hỏi trước, không tự làm.
4. **Không khởi động lại/sửa launchd job nào** (không `launchctl kickstart`,
   `bootout`, `bootstrap`). Nếu nghĩ cần restart để áp dụng một thay đổi, nói
   rõ trong báo cáo và chờ người dùng tự làm.
5. Nếu gặp bất cứ điều gì mơ hồ hoặc có vẻ rủi ro (có thể ảnh hưởng dữ liệu
   thật, tác vụ thật, hoặc vượt ra ngoài phạm vi 2 việc dưới đây), **DỪNG lại
   và hỏi** thay vì tự đoán.
6. Sau mỗi việc lớn xong, viết ngay 1-2 dòng báo cáo ngắn, không cần chờ xong
   hết mới báo.
7. Khi đã hoàn tất **toàn bộ** (cả Việc 1 và Việc 2, kể cả phần không kiểm
   chứng được), kết thúc câu trả lời bằng đúng dòng: `XONG-TOAN-BO`.

## Việc 1 — Content Image Runner: xác minh bản vá TCC/launchd còn đứng vững

Bối cảnh: job launchd `com.havigroup.content-image-runner` trước đây fail
100% các lần chạy (lỗi TCC/Full Disk Access: launchd tự spawn `/bin/zsh`
không có tiến trình cha nào được cấp Full Disk Access, bị chặn đọc file trong
`~/Documents`). Đã sửa bằng cách bỏ hẳn wrapper zsh, cho launchd gọi thẳng
`.venv/bin/python automation_center/runner/content_image_runner.py` (script
tự nạp `.env` bằng Python, xem
`automation_center/runner/content_image_runner.py:21-57`), và sửa
`runner/.env` dòng `AUTOMATION_RUNNER_LABEL` (thêm dấu ngoặc bao chuỗi có
khoảng trắng, tránh zsh tách từ).

- Đọc `/Users/admin/Library/Logs/havigroup/content-image-runner.log` (chỉ
  đọc, đừng xoá/ghi đè) — xác nhận runner đang chạy ổn định (không
  crash-loop, không còn lỗi zsh/TCC/"can't open input file"). Lỗi duy nhất
  còn được phép còn lại là "Cloudflare Access chặn runner: thiếu hoặc sai
  CF_ACCESS_CLIENT_ID/...". Nếu thấy loại lỗi nào khác xen vào, ghi rõ nguyên
  văn + thời điểm.
- Chạy `launchctl print gui/$(id -u)/com.havigroup.content-image-runner` (chỉ
  đọc trạng thái, không kickstart/bootout) — ghi lại `state`, `pid`,
  `last exit code`.
- Đọc `runner/.env` (chỉ đọc) — xác nhận `CF_ACCESS_CLIENT_ID`/
  `CF_ACCESS_CLIENT_SECRET` còn trống hay đã có giá trị thật.
  - Nếu còn trống: kết luận Việc 1 là "đã hết lỗi TCC, đang chờ người dùng
    điền Cloudflare Access Service Token", dừng ở đây, không giả lập token.
  - Nếu đã có giá trị: theo dõi log thêm khoảng 2-3 phút (không chủ động gọi
    API gì) xem runner có heartbeat/claim thành công không (không còn dòng
    "Runner lỗi: Cloudflare Access..."), ghi lại kết quả.

## Việc 2 — Chẩn đoán vòng lặp kẹt reCAPTCHA của TASK-2026-02120

Bối cảnh: từ khoảng 11:46 ngày 2026-08-31 tới giờ,
`/Users/admin/Library/Logs/havigroup/flow-v2.log` liên tục ghi kiểu:

```
flow/upsampleImage round N attempt 1 media=<id> failed: HTTP 403 on upsampleImage: reCAPTCHA evaluation failed
...
Đăng bù 0 ảnh đã tạo lên TASK-2026-02120.
```

lặp lại mỗi vài phút, luôn đúng 3 media id (`ecfa92a6-ec9e-45b2-a82e-afeb692eb5ec`,
`898d33ba-2d78-4be7-ad13-185804ba7148`, `cb6e4f17-464f-432d-ac1c-4dad03cfcdf7`),
không tiến triển, "Đăng bù" luôn ra 0 ảnh.

Mã liên quan (số dòng có thể đã lệch, tự dò lại bằng grep trong
`flow_web/service.py`):

- dòng ~407-410 — bộ đếm `_flow_upsample_recaptcha_streak`.
- dòng ~16281-16320 — `_flow_upsample_recaptcha_rounds()`. **Đính chính:** chỗ
  này trước ghi cơ chế "give up after streak"
  (`FLOW_UPSAMPLE_RECAPTCHA_GIVE_UP_AFTER`); cái tên ấy gỡ ở `17d860a`. Nay là
  bản ghi bền theo từng media — `FLOW_UPSAMPLE_RECAPTCHA_RESULT_KEY`, ngưỡng
  `FLOW_UPSAMPLE_RECAPTCHA_MANUAL_AFTER_DEFAULT`, cooldown 24h, cờ
  `needs_manual_review`.
- dòng ~16669-16770 — vòng lặp gọi `upsampleImage` theo round/attempt.
- dòng ~17781, ~18380 — logic "Đăng bù" (compensate-publish).

Trả lời kèm bằng chứng trong mã (trích `đường/dẫn/tệp.py:dòng`):

- Cơ chế "give up after streak" có thực sự dừng hẳn việc thử lại 3 media này
  không, hay chỉ giảm số round mỗi lượt gọi, còn tầng cao hơn (job
  scheduler/poll loop) vẫn cứ gọi lại toàn bộ job mỗi vài phút vô thời hạn?
- Có nơi nào đánh dấu tác vụ/media này là "cần người can thiệp" (tạm dừng
  job, thông báo người vận hành, tự bỏ qua ảnh lỗi để job tiến tới ảnh còn
  lại) không? Nếu không, đây có phải khoảng trống thiết kế (job không có
  trần thời gian/tần suất thử toàn cục) không?
- 3 media id này có luôn là cùng 3 ảnh mỗi vòng không (đối chiếu log), hay
  danh sách ảnh đang thử có đổi mà đoạn log ngắn chỉ trùng hợp giống nhau?
- Nếu tìm ra sửa mã an toàn (ví dụ: thêm trần số vòng thử toàn cục cho mỗi
  media/job rồi đánh dấu tác vụ cần xem thủ công thay vì lặp vô hạn) — CHỈ
  viết code trong cây làm việc (không commit/push), giải thích rõ rủi ro/đánh
  đổi trong báo cáo. Nếu có bất kỳ nghi ngờ nào về tác động tới
  TASK-2026-02120 thật hoặc tác vụ khác đang chạy thì DỪNG lại hỏi trước khi
  sửa, không tự quyết.
- Nếu không chắc cách sửa an toàn, chỉ cần chẩn đoán rõ nguyên nhân + đề xuất
  hướng sửa bằng lời, không bắt buộc phải tự sửa mã.

## Việc 3 — Sửa vòng lặp kẹt reCAPTCHA (đã được người dùng duyệt hướng sửa)

Người dùng đã xem báo cáo Việc 2 và **chọn cho triển khai** hướng sửa đã đề
xuất ở cuối báo cáo đó ("Hướng sửa đề xuất (chưa áp dụng)"). Việc 3 này là để
hiện thực hướng đó — vẫn trong cây làm việc, chưa commit/push, và **chưa được
áp dụng lên tiến trình flow-v2 thật đang chạy** (không tự restart launchd).

Yêu cầu, giữ đúng tinh thần đề xuất đã duyệt:

- Thay bộ đếm streak trong RAM (`flow_web/service.py:398-410`, không gắn với
  media/job/task, mất khi restart) bằng một bộ đếm **bền theo
  `task_id + job_id + media_id`**. Tự khảo sát chỗ lưu trạng thái job/task
  hiện có trong repo (vd cạnh nơi lưu `already_listed`/`listing_confirmed` ở
  `flow_web/agent_bot.py`, hoặc kho trạng thái job của `flow_web/pipeline.py`)
  để chọn cách lưu nhất quán với phần còn lại của mã — không tự bịa ra một cơ
  chế lưu trữ mới nếu đã có cái tương tự.
- Sau khi một media bị từ chối reCAPTCHA đủ một ngưỡng nhỏ (tự chọn số hợp lý,
  có thể cấu hình qua biến môi trường — việc này **đã làm xong**, tên thật là
  `FLOW_UPSAMPLE_RECAPTCHA_MANUAL_AFTER_DEFAULT`; bản giao việc gốc gợi ý theo
  phong cách `FLOW_UPSAMPLE_RECAPTCHA_GIVE_UP_AFTER`, cái tên ấy nay không còn
  trong code), **dừng hẳn việc tự động thử
  lại ảnh đó** (không phải chỉ giảm round), gắn cờ `needs_manual_review` và
  `next_retry_at` (cooldown) cho đúng media/job đó.
- Watcher (`autorun_erp_idea_children()` / `repair_erp_idea_children()` ở
  `flow_web/service.py:18184-18361`) phải **tôn trọng cờ/cooldown này trước
  khi gọi `publish_erp_review`** — không được lặp gọi vô hạn cho media đã bị
  đánh dấu.
- Khi cờ được bật lần đầu cho một media, ghi một dòng log/summary rõ ràng để
  người vận hành biết cần xem thủ công (tận dụng kênh log/summary đã có trong
  bot, không cần tạo kênh thông báo mới).
- **Không** tự gọi API ERP để đổi trạng thái `TASK-2026-02120` thật, không
  huỷ/xoá task thật — chỉ sửa mã tự động hoá để các chu kỳ *sau này* (khi
  người dùng tự áp dụng bản vá) hành xử đúng.
- Viết test mới theo đúng khuôn mẫu test hiện có (fake/dry-run, không chạm
  Etsy/ERP thật — xem `tests/test_listing_bridge.py`,
  `tests/test_agent_bot.py`) để chứng minh: (a) sau ngưỡng, media được đánh
  dấu `needs_manual_review` và không bị thử lại nữa; (b) bộ đếm sống sót qua
  một lần "restart" giả lập (khởi tạo lại đối tượng đọc từ nơi lưu bền); (c)
  watcher không gọi `publish_erp_review` cho media đã bị đánh dấu.
- Chạy bộ test liên quan tối thiểu là các file test vừa sửa/thêm; nếu có thời
  gian thì chạy `.venv/bin/python -m pytest -q` toàn bộ (có thể mất vài phút,
  đừng bỏ dở giữa chừng) để chắc không phá test khác. Ghi lại kết quả.
- Nếu trong lúc làm phát hiện quyết định thiết kế nào còn mơ hồ mà báo cáo
  Việc 2 chưa nói rõ (vd ngưỡng bao nhiêu, cooldown bao lâu, lưu ở đâu), tự
  chọn một giá trị/ cách làm hợp lý, giải thích rõ lý do trong báo cáo — không
  cần dừng hỏi cho những lựa chọn kỹ thuật nhỏ này. Chỉ DỪNG hỏi nếu phát hiện
  điều gì có thể ảnh hưởng tới tác vụ ERP thật đang chạy hoặc vượt phạm vi nêu
  trên.

## Cập nhật hàng rào cho Việc 4-7 (người dùng đã duyệt riêng)

Người dùng đã xem báo cáo Việc 3 và **chủ động chọn bỏ giới hạn 3 và 4 ở trên**
riêng cho Việc 5 và Việc 6 dưới đây — nghĩa là được phép `launchctl kickstart`
tiến trình flow-v2 thật và được phép quan sát/đọc dữ liệu thật của
TASK-2026-02120 sau khi restart. Các hàng rào còn lại (1, 2, 6) **vẫn giữ
nguyên**: không rewrite git/commit/push, không tự điền `.env`, báo cáo ngắn sau
mỗi việc. Làm đúng thứ tự Việc 4 → 5 → 6 → 7, **dừng lại sau mỗi việc để chờ
xác nhận đã ổn** thay vì tự chạy tiếp — mỗi việc phải kết thúc bằng marker
riêng ghi rõ dưới mục việc đó.

Quy tắc chung áp dụng cho cả 4 việc: nếu bất cứ lúc nào thấy dấu hiệu bất
thường vượt quá những gì mô tả dưới đây (lỗi khởi động không rõ nguyên nhân,
dữ liệu thật trông sai lệch, hành vi không khớp kỳ vọng) thì **DỪNG ngay, không
tự sửa thêm trên tiến trình thật**, ghi rõ vào báo cáo và kết thúc bằng
`LOI-VIEC-<n>` thay vì `XONG-VIEC-<n>`.

## Việc 4 — Tự rà soát rủi ro bản vá Việc 3 trước khi áp dụng lên tiến trình thật

- Đọc lại toàn bộ diff `flow_web/service.py`, `tests/test_erp_review.py`,
  `tests/test_hvg_erp_integration.py` của Việc 3 với vai trò người review độc
  lập (giả định không phải người viết ra nó).
- Kiểm tra cụ thể: tiến trình flow-v2 thật đang chạy có `data/state.json` sản
  xuất thật (đường dẫn theo `flow_web/paths.py:19-20`) không có field
  `flow_upsample_recaptcha` nào cả (vì code này chưa từng chạy) — xác nhận code
  mới đọc field vắng mặt này có an toàn không (không KeyError, không giả định
  field luôn tồn tại).
- Xác nhận cụ thể hành vi cho 3 media đang kẹt thật của TASK-2026-02120
  (`ecfa92a6-ec9e-45b2-a82e-afeb692eb5ec`,
  `898d33ba-2d78-4be7-ad13-185804ba7148`,
  `cb6e4f17-464f-432d-ac1c-4dad03cfcdf7`): ngay chu kỳ đầu tiên sau khi restart,
  bộ đếm của chúng bắt đầu lại từ 0 (vì chưa có record cũ) hay được tính là đã
  "bị từ chối" ngay? Cần bao nhiêu chu kỳ nữa (ước tính theo chu kỳ 180 giây)
  thì 3 media này chạm ngưỡng 2 và được gắn cờ `needs_manual_review`? Trả lời
  bằng số cụ thể dựa trên đọc code, không đoán mơ hồ.
- Liệt kê rủi ro/edge case còn lại nếu có (race condition giữa nhiều worker,
  ảnh hưởng job khác không phải reCAPTCHA, cách rollback nếu sau restart phát
  hiện lỗi — chỉ mô tả cách rollback, **không thực hiện** ở việc này).
- Việc này **chỉ đọc**, không sửa mã, không đụng launchd/state.json thật.
- Kết thúc bằng `XONG-VIEC-4` nếu không phát hiện rủi ro chặn cần dừng; nếu
  phát hiện rủi ro nghiêm trọng (VD: sẽ lỗi khi thiếu field), kết thúc bằng
  `LOI-VIEC-4`, mô tả rõ, **không tự sửa thêm** — chờ người dùng quyết định.

## Việc 5 — Áp dụng bản vá lên tiến trình flow-v2 thật (chỉ làm nếu Việc 4 kết luận an toàn)

- Trước khi restart: sao lưu `data/state.json` thật sang
  `data/state.json.bak-<UTC timestamp>` (chỉ copy, không sửa bản gốc).
- Ghi lại PID hiện tại của `com.havigroup.flow-v2`
  (`launchctl list | grep com.havigroup.flow-v2`).
- Restart: `launchctl kickstart -k gui/501/com.havigroup.flow-v2`.
- Sau restart, xác nhận: `launchctl print gui/501/com.havigroup.flow-v2` cho
  `state = running` và PID mới khác PID cũ; theo dõi
  `/Users/admin/Library/Logs/havigroup/flow-v2.log` trong ít nhất 60 giây đầu
  để chắc không có traceback/crash lúc khởi động (import lỗi, cú pháp lỗi,
  v.v.).
- Nếu khởi động lỗi/crash-loop: **dừng ngay**, không thử sửa thêm trên tiến
  trình thật, ghi log lỗi đầy đủ vào báo cáo, kết thúc bằng `LOI-VIEC-5`.
- Nếu khởi động ổn: ghi PID cũ/mới, thời điểm restart, và 30-60 dòng log đầu
  sau khi lên vào báo cáo, kết thúc bằng `XONG-VIEC-5`.

## Việc 6 — Theo dõi chu kỳ thật để xác nhận cờ hoạt động (chỉ làm sau khi Việc 5 báo `XONG-VIEC-5`)

- Theo dõi `/Users/admin/Library/Logs/havigroup/flow-v2.log` qua ít nhất 2 chu
  kỳ watcher đầy đủ kể từ lúc restart (chu kỳ mặc định 180 giây theo
  `flow_web/service.py:18184-18193`, nên theo dõi tối thiểu ~7-10 phút,
  `sleep` giữa các lần đọc log thay vì busy-loop).
- Kỳ vọng theo kết luận Việc 4: sau đủ số chu kỳ đã ước tính, 3 media
  reCAPTCHA của TASK-2026-02120 sẽ có record `needs_manual_review=true` và
  watcher không còn gọi `publish_erp_review` lặp lại cho job đó (dòng log kiểu
  cũ `Đăng bù 0 ảnh đã tạo lên TASK-2026-02120.` không còn lặp vô hạn, thay vào
  đó có dòng log/summary mới báo bỏ qua do cờ manual).
- **Chỉ đọc** `data/state.json` thật để xác nhận record xuất hiện đúng key
  `task_id+job_id+media_id`; không sửa file này.
- Ghi vào báo cáo: số chu kỳ đã theo dõi, thời điểm log trước/sau, có đúng kỳ
  vọng không.
- Nếu sau thời gian theo dõi hợp lý (tối đa ~15 phút) mà vẫn lặp vô hạn như cũ
  hoặc xuất hiện lỗi mới không có trong Việc 4: **dừng ngay, không tự sửa gì
  thêm trên tiến trình thật**, ghi rõ, kết thúc bằng `LOI-VIEC-6`.
- Nếu đúng kỳ vọng: kết thúc bằng `XONG-VIEC-6`.

## Việc 7 — Viết runbook gỡ cờ `needs_manual_review` thủ công

- Viết `docs/runbook-go-co-manual-review.md`: mô tả cách xác định record bị cờ
  trong `data/state.json` (đường dẫn field chính xác theo code Việc 3), cách
  gỡ cờ an toàn (dừng service trước khi sửa file, hay qua script riêng), cảnh
  báo rủi ro (luôn backup trước khi sửa, restart lại sau khi sửa để service
  đọc lại state mới), cách kiểm tra kết quả sau khi gỡ.
- Có thể viết kèm script nhỏ `scripts/clear_recaptcha_manual_flag.py` nhận
  `task_id`, `job_id`, `media_id`; mặc định chạy dry-run (chỉ in ra sẽ đổi gì),
  cần cờ `--apply` mới thực sự ghi đè `data/state.json`. Viết test nếu có thời
  gian, tương tự khuôn mẫu test hiện có.
- Việc này không đụng tiến trình đang chạy (chỉ viết file mới), an toàn để làm
  ngay cả khi Việc 5/6 chưa tới lượt.
- Kết thúc bằng `XONG-VIEC-7`.

## Việc 8 — Test vật lý toàn bộ pipeline Flow v2 trên sandbox "test bờm" (người dùng đã chỉ định)

Bối cảnh: người dùng đã xác nhận project **"test bờm"** trên ERP (task cha
**TASK-2026-02149** "Bảng sản phẩm — test bờm (Flow v2)", xem tại
`https://erp.havigroup.llc/hvg/task?project=PROJ-0170&task=TASK-2026-02149`)
là sandbox dành riêng để test, tách biệt hoàn toàn khỏi mọi task khách hàng
thật (XMAS Khăn Tay Thêu Tay, XMAS Ornament Thêu Tròn, TASK-2026-02120, v.v.).
Task cha này phụ trách bởi user test "Kin test agent", có 10 task con:
TASK-2026-02150/02151 ("Idea 1/2 — test bờm", đang "Đang làm"), TASK-2026-02152
("Sản phẩm 1 của idea 1", đang "Đang làm"), TASK-2026-02153..02156, 02158,
02159 ("Sản phẩm ... của idea ...", đang "Cần làm"), TASK-2026-02157 ("Idea 3
— test bờm", đang "Cần làm").

**Phạm vi được duyệt cho Việc 8**: được phép gọi API Flow/ERP thật, tạo ảnh
thật, đăng comment ERP thật — nhưng **CHỈ trong cây TASK-2026-02149** (chính
nó + các task con TASK-2026-02150 → TASK-2026-02159, và task con phát sinh
thêm bên trong cây này nếu automation tự tạo). **Không đụng** tới bất kỳ
project/task nào khác, kể cả các card khác cũng gắn nhãn "test bờm" nhưng
nằm ngoài cây này (vd TASK-2026-02160, "Váy linen thêu vịt — test tạo ảnh") —
nếu cần mở rộng phạm vi thì DỪNG và hỏi trước. Các hàng rào 1, 2, 6 ở đầu văn
bản này vẫn giữ nguyên.

Mục tiêu: chứng minh **toàn bộ pipeline thật** (không chỉ phần retry-cap
reCAPTCHA) chạy được từ đầu tới cuối trên dữ liệu test thật: idea fan-out →
tạo content → tạo ảnh → nâng 2K (`upsampleImage`) → đăng ảnh/summary đúng thẻ
ERP con theo quy ước `[FLOW_V2_REVIEW job#idx]` → dừng đúng ở bước chờ người
duyệt.

Yêu cầu cụ thể:

- Trước tiên **chỉ đọc mã** để xác định cơ chế kích hoạt agent xử lý một thẻ
  ERP: qua lệnh `@bot ...` trong comment (`flow_web/agent_bot.py`), qua
  watcher tự động (`autorun_erp_idea_children()`/`repair_erp_idea_children()`
  ở `flow_web/service.py`), hay cần gọi thủ công. Đọc lại lịch sử
  comment/log của TASK-2026-02150 và TASK-2026-02152 (đang "Đang làm") để
  hiểu chúng đã được xử lý tới đâu trước khi làm gì thêm.
- Chọn **đúng một nhánh** "Cần làm" chưa chạy trong cây (khuyến nghị:
  TASK-2026-02157 "Idea 3 — test bờm" cùng các "Sản phẩm ... của idea 3" con
  của nó) để kích hoạt một lượt chạy từ đầu tới cuối hoàn toàn mới — không
  kích hoạt hàng loạt tất cả nhánh cùng lúc, để dễ theo dõi và dễ rollback
  nếu có sự cố.
- Theo dõi log thật (`/Users/admin/Library/Logs/havigroup/flow-v2.log` và
  `content-image-runner.log`) qua từng bước: tạo content, tạo ảnh, gọi
  `upsampleImage`, và xác nhận ảnh/summary được đăng đúng thẻ ERP con tương
  ứng.
- Nếu gặp lỗi reCAPTCHA thật trong lúc test, xác nhận cơ chế retry-cap
  (Việc 3) cũng hoạt động đúng ở đây — không cần cố tình gây lỗi, chỉ quan
  sát nếu nó tự xảy ra.
- Khi tới bước cần người duyệt (comment chờ trả lời DUYỆT/BỎ theo quy ước),
  **DỪNG lại, không tự trả lời thay người dùng** — ghi rõ thẻ nào đang chờ
  duyệt kèm ID, để người dùng tự vào duyệt nếu muốn đi tiếp tới bước publish.
- Việc 8 là **test vận hành, không phải sửa lỗi**: không sửa mã, trừ khi phát
  hiện lỗi mới thì chỉ ghi nhận + đề xuất, không tự sửa.
- Ghi lại đầy đủ bằng chứng: dòng log, thời điểm, ID thẻ ERP, trạng thái
  trước/sau mỗi bước.
- Nếu bất cứ lúc nào thấy dấu hiệu hành động có thể ảnh hưởng ra ngoài cây
  TASK-2026-02149, hoặc không chắc một thẻ có thuộc phạm vi hay không,
  **DỪNG NGAY và hỏi**, không đoán.
- Kết thúc bằng `XONG-VIEC-8` nếu chạy được trọn một nhánh idea → sản phẩm từ
  đầu tới bước chờ duyệt (hoặc xa hơn nếu tự tin), hoặc `LOI-VIEC-8` nếu gặp
  lỗi/bế tắc không mong đợi.

## Báo cáo

Viết ra `docs/bao-cao-kiem-thu-codex-2.md`, tiếng Việt, theo đúng thứ tự Việc
1 → 7 (thêm mục việc mới vào cuối file mỗi khi xong, không xoá nội dung việc
trước đó). Mỗi kết luận đi kèm `đường/dẫn/tệp.py:dòng`. Chỗ nào không kiểm
chứng được thì nói thẳng là chưa kiểm chứng, đừng đoán. Việc 3 phải liệt kê rõ
những file đã sửa/thêm và trạng thái test.

**Chỉ làm một việc mỗi lượt nhắn**: mỗi khi nhận thêm chỉ thị từ người dùng để
làm Việc tiếp theo (4, 5, 6, hoặc 7), chỉ làm đúng việc đó rồi kết thúc bằng
marker riêng của việc đó (`XONG-VIEC-<n>` hoặc `LOI-VIEC-<n>`), không tự động
chạy tiếp sang việc kế mà không có chỉ thị mới.

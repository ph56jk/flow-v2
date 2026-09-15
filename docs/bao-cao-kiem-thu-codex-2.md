# Báo cáo kiểm thử Codex 2

Thời điểm kiểm tra: 2026-08-31. Phạm vi chỉ đọc log/mã và ghi báo cáo; không
sửa `.env`, không gọi API ERP ghi, không đổi trạng thái `TASK-2026-02120`, và
không thao tác launchd ngoài `launchctl print`.

## Việc 1 — Content Image Runner

**Kết luận:** đã hết lỗi TCC ở lượt chạy hiện tại, đang chờ người dùng điền
Cloudflare Access Service Token.

- `launchctl print gui/501/com.havigroup.content-image-runner` tại lúc kiểm tra
  cho `state = running`, `pid = 19570`, `runs = 1`, và `last exit code =
  (never exited)`. Job gọi thẳng `.venv/bin/python` với
  `automation_center/runner/content_image_runner.py`, không qua zsh wrapper.
  Đây khớp với cơ chế script tự nạp `.env` bằng Python:
  `automation_center/runner/content_image_runner.py:21-27`,
  `automation_center/runner/content_image_runner.py:38-57`.
- Log vẫn giữ lỗi zsh **lịch sử** cuối cùng ở
  `/Users/admin/Library/Logs/havigroup/content-image-runner.log:48091`:
  `/bin/zsh: can't open input file: .../run-content-image-runner.sh`.
  Dòng log này không có timestamp nên không thể xác minh thời điểm chính xác.
  Từ dòng 48092 đến cuối file (48284), chỉ có thông báo poll và lỗi Cloudflare
  Access; không có lỗi zsh/TCC/Full Disk Access/crash xen vào. Vì vậy đây
  không phải crash-loop hiện thời. Phần lỗi Cloudflare được tạo khi thiếu/sai
  token theo `automation_center/runner/content_image_runner.py:84-100`.
- Đã chỉ đọc `automation_center/runner/.env`: cả
  `CF_ACCESS_CLIENT_ID` và `CF_ACCESS_CLIENT_SECRET` đều trống; giá trị bí mật
  không được hiển thị hay sửa. `AUTOMATION_RUNNER_LABEL` đã được quote ở
  `automation_center/runner/.env:5` (hai biến token ở
  `automation_center/runner/.env:8-9`); runner đọc hai biến này tại
  `automation_center/runner/content_image_runner.py:64-67`.

Không theo dõi heartbeat/claim thêm vì hai biến token trống theo điều kiện của
đơn đặt việc. Việc cần người dùng thực hiện là điền Service Token Cloudflare
Access thật vào `.env`, rồi tự khởi động lại job theo quy trình vận hành nếu
cần; báo cáo này không thực hiện restart.

## Việc 2 — Chẩn đoán vòng lặp reCAPTCHA của TASK-2026-02120

**Kết luận:** `FLOW_UPSAMPLE_RECAPTCHA_GIVE_UP_AFTER` không dừng hẳn retry.
Nó chỉ giảm số round của *lần upscale kế tiếp* xuống 1; watcher tầng trên vẫn
chạy vô hạn và lại gọi nhánh đăng bù. Không có trạng thái “cần người can
thiệp” riêng cho lỗi reCAPTCHA/media này, cũng không có trần retry toàn cục
theo media hay task.

- Bộ đếm là biến nhớ trong tiến trình, khởi tạo bằng 0, không gắn với media,
  job hoặc task: `flow_web/service.py:398-410`. Sau hai lần bị từ chối, hàm
  chỉ trả về 1 round thay vì 3: `flow_web/service.py:16281-16312`. Mỗi lần
  upscale lại tính số round mới, tăng streak khi mọi round bị từ chối, và chỉ
  reset streak nếu Flow trả ảnh 2K thành công:
  `flow_web/service.py:16690-16761`. Vì vậy restart tiến trình cũng làm mất
  streak, chứ không tạo một cờ dừng bền vững.
- Sau khi mọi round bị từ chối, code còn thử UI download rồi trả lại JPEG gốc
  nếu không có ảnh 2K: `flow_web/service.py:16659-16782`. Tầng kế tiếp biểu
  diễn kết quả này là `flow_unavailable`, không đánh job là failed hay cần
  can thiệp: `flow_web/service.py:17036-17051`. Khi đăng bù, các artifact còn
  được đưa qua `_upsample_artifacts_bytes` trước khi upload ERP:
  `flow_web/service.py:17899-17931`.
- Watcher được tạo khi app khởi động tại `flow_web/main.py:101-117`, có chu kỳ
  mặc định 180 giây nếu không có cấu hình môi trường khác
  (`flow_web/service.py:18184-18193`), rồi chạy `while True` và gọi
  `autorun_erp_idea_children()` lặp vô hạn
  (`flow_web/service.py:18343-18361`). Mỗi lượt `autorun` luôn gọi
  `repair_erp_idea_children()` trước (`flow_web/service.py:18311-18340`).
  Nhánh repair tìm completed job có artifact rồi lại gọi
  `publish_erp_review()` (`flow_web/service.py:18258-18270`). Trần 3 job chỉ
  áp dụng cho nhánh *top-up thiếu ảnh*, không áp dụng cho nhánh republish này:
  `flow_web/service.py:18214-18219`, `flow_web/service.py:18271-18303`.
- Không tìm thấy nhánh reCAPTCHA nào ghi cờ manual/intervention, pause watcher,
  gửi thông báo vận hành, hoặc bỏ qua riêng media lỗi. Các lần xuất hiện
  reCAPTCHA của upsampler tập trung ở `flow_web/service.py:16279-16761`; chuỗi
  gọi watcher/repair ở trên không kiểm tra cờ reCAPTCHA. Đây là khoảng trống
  thiết kế: không có giới hạn retry bền vững theo `task + job + media`, cũng
  không có cooldown toàn cục sau khi provider từ chối liên tiếp.

### Đối chiếu log

- Từ 11:46:08 đến 17:06:42 ngày 2026-08-31 có **41** chu kỳ kết thúc bằng
  `Đăng bù 0 ảnh đã tạo lên TASK-2026-02120.` Dẫn chứng chu kỳ đầu:
  `/Users/admin/Library/Logs/havigroup/flow-v2.log:41501-41507`; chu kỳ cuối:
  `/Users/admin/Library/Logs/havigroup/flow-v2.log:41829-41835`.
- Cả 41 khoảng log trước dòng “Đăng bù 0” đều có đủ ba media
  `ecfa92a6-ec9e-45b2-a82e-afeb692eb5ec`,
  `898d33ba-2d78-4be7-ad13-185804ba7148`, và
  `cb6e4f17-464f-432d-ac1c-4dad03cfcdf7`. Trong 40 chu kỳ sau chu kỳ đầu,
  chúng là các media reCAPTCHA duy nhất của khoảng tương ứng; chu kỳ đầu có
  log song song của tác vụ khác nên không thể gán các dòng không có task-id
  cho TASK-2026-02120 một cách chắc chắn. Tuy vậy, lặp lại đủ cả ba trong 41
  chu kỳ cho thấy đây không phải trùng hợp của một đoạn log ngắn.
- Ở 16:31 log có một lần app khởi động lại, rồi chu kỳ 16:38 thử 3 round cho
  hai media đầu và 1 round cho media thứ ba
  (`/Users/admin/Library/Logs/havigroup/flow-v2.log:41788-41803`), đúng với
  việc streak là state trong RAM. Báo cáo này không thực hiện và không quy kết
  nguyên nhân của lần restart đó.

### Hướng sửa đề xuất (chưa áp dụng)

Không sửa code: mọi thay đổi ở đây có thể đổi hành vi của
`TASK-2026-02120` thật và các task ERP đang chạy, nên phải có chấp thuận riêng
trước khi triển khai.

Hướng an toàn cần được duyệt là lưu bền bộ đếm theo `task_id + job_id +
media_id`; sau một ngưỡng nhỏ, bỏ qua riêng media bị reCAPTCHA, ghi cờ
`needs_manual_review` và `next_retry_at` có cooldown, đồng thời ghi một thông
báo vận hành rõ ràng. Watcher phải tôn trọng cờ/cooldown đó trước khi gọi
`publish_erp_review`. Đánh đổi: ảnh có thể được gửi lên ở độ phân giải gốc
hoặc bị giữ chờ duyệt, nhưng đổi lại chấm dứt spam API/log và không làm treo
toàn bộ task. Cần quyết định nghiệp vụ về hai lựa chọn này trước khi viết mã.

## Việc 3 — Bản vá vòng lặp reCAPTCHA (chưa áp dụng lên tiến trình thật)

**Kết luận:** đã hiện thực bản vá trong cây làm việc. Không có thao tác ERP,
launchd, `.env`, restart, commit hay push nào được thực hiện.

- Dùng kho bền có sẵn `StateStore`: `JobRecord.result` đã là dữ liệu được
  `StateStore.patch_job()` ghi xuống state file
  (`flow_web/schemas.py:197-214`, `flow_web/store.py:192-207`,
  `flow_web/store.py:342-355`). Bản vá lưu một map
  `flow_upsample_recaptcha.media` với cả khoá và giá trị chứa
  `task_id + job_id + media_id`, nên không tạo state file/cơ chế riêng
  (`flow_web/service.py:16280-16359`).
- Ngưỡng mặc định là **2** lượt upscale bị Flow từ chối hoàn toàn; có thể chỉnh
  bằng `FLOW_UPSAMPLE_RECAPTCHA_MANUAL_AFTER` (1–5). Cooldown mặc định 24 giờ,
  chỉnh bằng `FLOW_UPSAMPLE_RECAPTCHA_COOLDOWN_S` (60 giây–30 ngày)
  (`flow_web/service.py:16299-16313`). Khi chạm ngưỡng, record có
  `needs_manual_review=true`, `next_retry_at`, số lần từ chối và thời điểm;
  đồng thời ghi đúng một warning + job log vận hành
  (`flow_web/service.py:16361-16424`). Cờ manual là sticky: mốc
  `next_retry_at` để người vận hành biết lúc xem lại, **không** tự bật lại
  retry ngầm (`flow_web/service.py:16345-16348`).
- Trước mỗi `upsampleImage`, code kiểm tra record bền; lúc chạm ngưỡng trong
  lượt hiện tại nó cũng bỏ qua UI-download fallback để không phát sinh thêm
  một thử nghiệm tự động (`flow_web/service.py:16825-16920`). Lượt 2K thành
  công vẫn xoá riêng record cũ của media đó
  (`flow_web/service.py:16888-16895`, `flow_web/service.py:16932-16940`).
- Đường publish truyền chính xác `erp_task_id` và `job_id` vào batch upscale;
  đồng thời giữ state mới khi lưu lại `erp_review`, tránh overwrite record
  vừa được batch tạo (`flow_web/service.py:17033-17115`,
  `flow_web/service.py:18054-18170`). Nhánh repair/watcher kiểm tra cờ trước
  `publish_erp_review()` và thêm lý do skip vào summary thay vì gọi lại vô hạn
  (`flow_web/service.py:18445-18482`).

### Test và phạm vi thay đổi

- Đã sửa `flow_web/service.py`, `tests/test_erp_review.py`, và
  `tests/test_hvg_erp_integration.py`; mục báo cáo này là thay đổi thứ tư.
- Test mới chứng minh: (a) sau ngưỡng record có `needs_manual_review` và fake
  Flow không bị gọi lại (`tests/test_erp_review.py:698-724`); (b) khởi tạo lại
  `StateStore`/`FlowWebService` vẫn đọc được cờ bền
  (`tests/test_erp_review.py:726-744`); (c) repair watcher không gọi
  `publish_erp_review` cho job có media đã bị cờ
  (`tests/test_hvg_erp_integration.py:1153-1180`).
- Đã chạy `.venv/bin/python -m pytest -q tests/test_erp_review.py
  tests/test_hvg_erp_integration.py`: **145 passed** trong 5,79 giây.
- Đã thử toàn bộ `.venv/bin/python -m pytest -q`; suite không xanh do 6 lỗi
  setup có sẵn ở `automation_center/tests/test_scope_parity.py`: subprocess
  `node --input-type=module` cho `automation_center/src/worker.js` bị
  `SIGABRT`. Các lỗi này ngoài ba file mã/test của Việc 3 và không được sửa
  trong phạm vi đơn đặt việc; phần còn lại của suite chưa được khẳng định
  xanh từ lần chạy đầy đủ đó.

Giới hạn đã biết: chưa có UI/API để bỏ cờ manual. Một upscale 2K thành công
trước khi chạm ngưỡng sẽ xoá bộ đếm tạm; sau khi đã có cờ manual, retry tự động
không thể tự xoá cờ đó. Người vận hành phải xử lý state/job theo quy trình được
duyệt hoặc tạo lượt chạy mới; báo cáo này không làm một trong hai việc đó.

## Việc 4 — Rà soát rủi ro bản vá trước khi áp dụng

**Kết luận:** không phát hiện lỗi chặn khi state cũ chưa có field mới. Có thể
chuyển sang Việc 5 khi có chỉ thị riêng. Việc rà soát này chỉ đọc mã/diff; không
truy cập `data/state.json` thật, launchd, log mới hay API ERP, và không sửa mã.

- Đã review độc lập các hunk Việc 3 trong `flow_web/service.py`,
  `tests/test_erp_review.py` và `tests/test_hvg_erp_integration.py`. Test dùng
  state file tạm, không phải state production
  (`tests/test_erp_review.py:101-111`,
  `tests/test_hvg_erp_integration.py:55-68`). Ba test chính vẫn bao phủ cờ sau
  ngưỡng, đọc lại sau restart giả lập, và watcher không gọi publish
  (`tests/test_erp_review.py:698-744`,
  `tests/test_hvg_erp_integration.py:1153-1180`). Không chạy lại test ở Việc 4
  vì đây là lượt chỉ-đọc; kết quả chạy trước đó là 145 passed như mục Việc 3.
- Đường dẫn production theo mã là `data/state.json`
  (`flow_web/paths.py:19-20`). Theo giới hạn chỉ-đọc nêu ở Việc 4, **chưa kiểm
  chứng trực tiếp** field `flow_upsample_recaptcha` có vắng trong file thật;
  cũng không đoán nội dung file đó. Tuy nhiên, thiếu field là an toàn: `result`
  có mặc định dict (`flow_web/schemas.py:197-204`), hàm đọc dùng `.get()` và
  fallback `{}` (`flow_web/service.py:16320-16328`), còn lookup một record trả
  `{}` khi chưa có (`flow_web/service.py:16334-16342`). Không có truy cập
  `result["flow_upsample_recaptcha"]` trong đường đọc production. Vì vậy trạng
  thái legacy không có field này không gây `KeyError`.
- Với ba media của `TASK-2026-02120`, record chưa tồn tại được đọc là `{}` —
  tức bộ đếm logic bắt đầu ở **0**, không bị tính sẵn là một lần từ chối. Khi
  một lần upscale có đủ các round đều bị reCAPTCHA từ chối, code mới tăng đúng
  một đơn vị sau vòng round (`flow_web/service.py:16839-16920`); mặc định có 3
  round mỗi lần và ngưỡng manual là 2
  (`flow_web/service.py:16284-16305`). Vì log Việc 2 đã cho thấy cả ba media
  này lặp lại với toàn bộ round bị từ chối, diễn tiến dự kiến là: **chu kỳ
  repair #1: 0 → 1** cho từng media; **chu kỳ repair #2: 1 → 2**, ghi
  `needs_manual_review=true` và `next_retry_at`
  (`flow_web/service.py:16361-16424`). Sau chu kỳ thứ nhất chỉ cần **thêm một**
  chu kỳ; tính từ restart cần tổng cộng **2** lượt repair để chạm cờ.
- Watcher ngủ 180 giây trước lượt đầu và chỉ bắt đầu lần ngủ kế tiếp sau khi
  `autorun_erp_idea_children()` hoàn tất
  (`flow_web/service.py:18385-18394`, `flow_web/service.py:18559-18567`). Do
  đó phần chờ scheduler danh nghĩa tới lúc bắt đầu chu kỳ thứ hai là 360 giây;
  thời gian thực tế lớn hơn 6 phút một lượng bằng thời gian chạy chu kỳ đầu.
  Con số này chỉ áp dụng cho watcher; một lần chạy dashboard/agent khác cũng
  gọi repair sẽ được tính là một pass và có thể làm chạm ngưỡng sớm hơn.
- Sau khi cờ xuất hiện, `repair_erp_idea_children()` đọc state trước
  `publish_erp_review()` và skip cả job; vì vậy watcher không cần một lần
  publish thứ ba để phát hiện lại ba media
  (`flow_web/service.py:18459-18485`). `publish_erp_review()` cũng có guard
  riêng theo media (`flow_web/service.py:18074-18094`) và upsampler có guard
  cuối cùng trước khi gọi Flow (`flow_web/service.py:16825-16834`).

### Rủi ro/edge case còn lại và rollback mô tả

- Khoá reCAPTCHA và `StateStore` chỉ là khoá trong một process
  (`flow_web/service.py:407-410`, `flow_web/store.py:192-207`). Hai process
  flow-v2 đồng thời vẫn có thể đọc-sửa-ghi `state.json` theo snapshot riêng;
  không nên chạy song song hai instance. Với một job launchd duy nhất đây không
  phải lỗi chặn, nhưng là rủi ro vận hành cần giữ nguyên khi áp dụng.
- Khi **một** media của một job đã manual, watcher skip đăng bù **cả job**
  (`flow_web/service.py:18461-18475`). Điều này chấm dứt vòng lặp như yêu cầu,
  nhưng cũng giữ lại các artifact chưa đăng khác của cùng job cho tới khi người
  vận hành xử lý cờ. Các job/task khác không chung `job_id` không bị ảnh hưởng,
  vì record có đủ `task_id + job_id + media_id`
  (`flow_web/service.py:16316-16318`, `flow_web/service.py:16385-16414`).
- Ngay pass chạm ngưỡng, danh sách upload của pass đó đã được lập trước khi
  upscale (`flow_web/service.py:18050-18100`), nên ảnh gốc có thể vẫn được đăng
  trong pass hiện tại; từ watcher kế tiếp job mới bị skip. Đây là đánh đổi đã
  nêu ở Việc 2, không phải một retry 2K bổ sung. Cờ manual là sticky dù qua
  `next_retry_at` (`flow_web/service.py:16345-16348`), nên cần runbook gỡ cờ
  ở Việc 7.
- Nếu sau một lần áp dụng được duyệt phát hiện lỗi, rollback nên là: dừng
  service theo chỉ thị mới, khôi phục bản sao `state.json` được tạo trước
  restart nếu cần, rồi áp dụng một patch đảo có review cho đúng ba file Việc 3
  và khởi động lại theo chỉ thị. Không dùng rewrite history; không thực hiện
  bất kỳ bước rollback nào trong Việc 4.

## Việc 5 — Áp dụng bản vá lên `com.havigroup.flow-v2`

**Kết luận:** khởi động lại thành công; không thấy crash-loop hay lỗi startup
trong 79 giây đầu. Không làm Việc 6/7.

- Trước restart, job ở `state = running`, PID cũ **1286**, `runs = 1`, `last
  exit code = (never exited)`, theo `launchctl print gui/501/com.havigroup.flow-v2`
  lúc 2026-08-31T10:43:46Z. Đã sao lưu nguyên trạng `data/state.json` thành
  `data/state.json.bak-20260831T104357Z` lúc 2026-08-31T10:43:57Z; hai file
  cùng 5.274.135 bytes và cùng mtime trước khi restart. Bản gốc không bị sửa.
- Đã thực hiện đúng lệnh được duyệt `launchctl kickstart -k
  gui/501/com.havigroup.flow-v2` lúc **2026-08-31T10:44:07Z**. Ba giây sau và
  kiểm tra lại lúc 2026-08-31T10:45:26Z, `launchctl print` đều báo
  `state = running`, `runs = 2`, PID mới **97944**. `launchctl list` cũng chỉ
  có một entry PID 97944; `ps -p 1286` không trả về tiến trình, còn PID 97944
  có PPID 1 và chạy đúng `.venv/bin/python -m uvicorn flow_web.main:app`.
  Như vậy PID cũ đã dừng hẳn, không có hai instance flow-v2 song song. Dòng
  `last terminating signal = Terminated: 15` là hệ quả mong đợi của `kickstart
  -k`, không phải crash.
- Log thật sau restart tại
  `/Users/admin/Library/Logs/havigroup/flow-v2.log:41884-41891` có đúng 8 dòng
  trong 79 giây quan sát, không đủ 30 dòng để ghi thêm mà không sang Việc 6:

  ```text
  INFO:     Shutting down
  INFO:     Waiting for application shutdown.
  INFO:     Application shutdown complete.
  INFO:     Finished server process [1286]
  INFO:     Started server process [97944]
  INFO:     Waiting for application startup.
  INFO:     Application startup complete.
  INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
  ```

  Không có `Traceback`, import error, exception hay lần spawn mới trong khoảng
  này. Watcher được tạo khi startup (`flow_web/main.py:100-117`) nhưng chu kỳ
  Idea mặc định chờ 180 giây (`flow_web/service.py:18559-18567`), nên không
  theo dõi hay diễn giải chu kỳ đó ở Việc 5.

## Việc 6 — Theo dõi watcher thật sau restart

**Kết luận:** đạt kỳ vọng. Đã theo dõi hai pass watcher đầy đủ và một cửa sổ
poll sau khi cờ được bật. Ba media của `TASK-2026-02120` đều có record bền
`needs_manual_review=true`; từ poll sau đó không còn retry Flow hay dòng đăng
bù lặp. Không sửa `data/state.json`, không gọi API ERP thủ công và không làm
Việc 7.

- Service vẫn `state = running`, `runs = 2`, PID **97944** lúc
  2026-08-31T10:59:29Z. Các pass được xác định từ log thật sau restart:
  pass 1 bắt đầu 17:47:20 và kết thúc 17:50:37; pass 2 bắt đầu 17:53:45 và kết
  thúc 17:54:23. Đây là hai lượt watcher đầy đủ, cách nhau bởi khoảng ngủ 180
  giây theo `flow_web/service.py:18559-18567`.
- Pass 1 có ba round 403 reCAPTCHA và UI fallback không thấy tile cho từng
  media (`/Users/admin/Library/Logs/havigroup/flow-v2.log:41893-41904`). Đọc
  chọn lọc `data/state.json` lúc 10:50:59Z cho thấy cả ba record cùng job
  `f19b9b24f4654bac80f2ce37e7485711`, đúng key
  `TASK-2026-02120::<job_id>::<media_id>`, `rejected_count=1`,
  `needs_manual_review=false`.
- Pass 2 có thêm đúng ba round 403 cho từng media, sau đó ghi warning
  `Cần xem thủ công` lần lượt lúc 17:53:52, 17:53:58 và 17:54:05
  (`/Users/admin/Library/Logs/havigroup/flow-v2.log:41907-41918`). Đọc state
  chỉ-đọc lúc 10:54:54Z và 10:59:29Z xác nhận ổn định cả ba record:

  | Media | `rejected_count` | `needs_manual_review` | `next_retry_at` |
  | --- | ---: | --- | --- |
  | `ecfa92a6-ec9e-45b2-a82e-afeb692eb5ec` | 2 | `true` | 2026-09-01T10:53:52.437853+00:00 |
  | `898d33ba-2d78-4be7-ad13-185804ba7148` | 2 | `true` | 2026-09-01T10:53:58.767118+00:00 |
  | `cb6e4f17-464f-432d-ac1c-4dad03cfcdf7` | 2 | `true` | 2026-09-01T10:54:04.995281+00:00 |

  Điều này khớp nhánh persist cờ ở `flow_web/service.py:16361-16424`.
- Watcher đã log `Đăng bù 0 ảnh đã tạo lên TASK-2026-02120.` ở cuối pass 1
  (`.../flow-v2.log:41905`) và pass 2 (`.../flow-v2.log:41919`), vì pass 2
  vừa là pass tạo cờ. Lần ngủ kế tiếp bắt đầu sau 17:54:23; đến 17:59:29
  (hơn 2 phút sau mốc poll kế tiếp 17:57:23), log vẫn dừng ở dòng 41919,
  không có `upsampleImage`, 403 hay `Đăng bù` mới cho task này. Mtime của state
  cũng giữ tại 17:54:11. Đây khớp guard watcher: khi có record blocked,
  `repair_erp_idea_children()` không gọi `publish_erp_review()`
  (`flow_web/service.py:18459-18485`).
- Lưu ý quan sát: watcher hiện chỉ log các phần tử `republished`/`topped_up`,
  không log riêng mảng `skipped` (`flow_web/service.py:18594-18603`). Vì vậy
  poll skip sau cờ là im lặng trong `flow-v2.log`; warning `Cần xem thủ công`
  ở dòng 41910/41914/41918 là thông báo vận hành rõ ràng hiện có. Đây là giới
  hạn quan sát, không phải retry hay lỗi mới.

## Việc 7 — Runbook gỡ cờ manual review

**Kết luận:** đã thêm runbook và script hỗ trợ, không đụng tiến trình đang
chạy, launchd, ERP hay `data/state.json` thật.

- [Runbook](runbook-go-co-manual-review.md) mô tả đúng đường dẫn record
  `jobs[].result.flow_upsample_recaptcha.media["task_id::job_id::media_id"]`,
  lệnh `jq` đọc chọn lọc, maintenance window, backup, kiểm tra JSON và restart
  sau khi người vận hành đã kiểm tra (`docs/runbook-go-co-manual-review.md:18-103`).
  Runbook cũng nói rõ watcher không log từng `skipped`; dòng `Cần xem thủ công`
  chỉ xuất hiện lúc mới gắn cờ, nên phải tra `data/state.json` để biết media
  còn bị block (`docs/runbook-go-co-manual-review.md:14-16`).
- Đã thêm `scripts/clear_recaptcha_manual_flag.py`. Script nhận đúng
  `task_id job_id media_id`, mặc định chỉ dry-run và chỉ `--apply` mới ghi
  (`scripts/clear_recaptcha_manual_flag.py:146-190`). Nó kiểm tra key lẫn ba ID
  trong value, từ chối record không manual, tự copy backup rồi atomically thay
  state file; chỉ xoá record mục tiêu, giữ toàn bộ result/ERP data khác
  (`scripts/clear_recaptcha_manual_flag.py:58-143`,
  `scripts/clear_recaptcha_manual_flag.py:192-200`). Script không tự
  stop/restart service hay gọi API.
- Đã thêm test state tạm
  `tests/test_clear_recaptcha_manual_flag.py`: dry-run không đổi byte nào,
  `--apply` chỉ xoá target và tạo backup, và record không manual bị từ chối
  (`tests/test_clear_recaptcha_manual_flag.py:72-110`). Đã chạy
  `.venv/bin/python -m py_compile scripts/clear_recaptcha_manual_flag.py
  tests/test_clear_recaptcha_manual_flag.py`, `git diff --check`, và
  `.venv/bin/python -m pytest -q tests/test_clear_recaptcha_manual_flag.py`:
  **3 passed**. Cảnh báo CRLF duy nhất của `git diff --check` thuộc file PowerShell
  đã có sẵn ngoài phạm vi này; không có lỗi whitespace từ ba file Việc 7.

## Việc 8 — Test vật lý pipeline Flow v2 trên sandbox “test bờm”

**Kết quả: dừng an toàn trước kích hoạt; chưa thể chạy test vật lý.** Không có
thay đổi mã, không gọi endpoint ghi ERP, không khởi động bot/watcher, và không
đụng bất kỳ thẻ nào ngoài cây được chỉ định.

- Đã đọc cơ chế trước khi hành động. `POST /api/erp/idea-batch` gọi trực tiếp
  `enqueue_erp_idea_jobs()` (`flow_web/main.py:182-184`); hàm này chỉ lấy các
  con trực tiếp của `task_id` và có thể lọc bằng `child_task_ids`
  (`flow_web/service.py:2837-3005`). Ngược lại, `/api/agent-bot/run` có thể
  quét board (`flow_web/main.py:270-273`, `flow_web/agent_bot.py:1276-1374`),
  nên không được dùng trong phạm vi một nhánh.
- Lúc **2026-08-31 18:19:53 +07**, truy vấn GraphQL chỉ-đọc (endpoint ERP đã
  cấu hình, không hiển thị credential) xác nhận `TASK-2026-02149` là “Bảng
  sản phẩm — test bờm (Flow v2)”, trạng thái `Open`, có đúng 10 con. Lịch sử
  chỉ-đọc của `TASK-2026-02150` và `TASK-2026-02152` cũng được kiểm tra theo
  yêu cầu: cả hai `Working`; 02150 có comment đổi sang `mockup-03`, 02152 có
  comment `acc: ACC 32`.
- Phát hiện mâu thuẫn phạm vi phải được chủ nhân xác nhận: `TASK-2026-02157`
  (“Idea 3 — test bờm”) là `Open`, cha là `TASK-2026-02149`, nhưng có
  `child_total=0` và không có comment/attachment. Danh sách con trực tiếp của
  `TASK-2026-02149` lại có `TASK-2026-02158` và `TASK-2026-02159` (“Sản phẩm
  1/2 của idea 3”) cùng cấp với 02157, không phải con của 02157. Vì vậy gọi
  endpoint với chỉ `task_id=TASK-2026-02157` sẽ không fan-out gì; còn gọi từ
  root với các ID lọc sẽ là một kiểu kích hoạt khác chưa được mô tả rõ.
- Không có dòng `flow-v2.log`/`content-image-runner.log` nào phát sinh cho
  Việc 8, vì đã dừng trước thao tác ghi theo Hàng rào. Cần quyết định rõ có
  được kích hoạt từ `TASK-2026-02149` với danh sách giới hạn
  `TASK-2026-02158,TASK-2026-02159` hay cần chỉnh lại quan hệ thẻ trên ERP;
  không tự suy đoán hay thay đổi thẻ.

# PRD — Độ bền vận hành cho Agent điều phối (đợt 2)

Tài liệu này nối tiếp `prd-agent-dieu-phoi.md`. Nó **không** mở thêm tính năng
mới; nó vá bốn chỗ hệ thống hỏng **âm thầm** — người dùng mất việc mà không hề
được báo. Mỗi yêu cầu dưới đây đều kèm bằng chứng đọc được từ code hoặc từ dữ
liệu production, không có mục nào là phỏng đoán.

## 0. Nguồn gốc

Ngày 2026-09-01 chạy nghiệm thu **vật lý** trên môi trường thật
(`automation.havigroup.llc` + PC `100.75.125.80`, runner `orchestrator-runner`
online). Luồng hỏi–đáp đạt: yêu cầu dạng câu hỏi đi từ `queued` (08:25:40.423Z)
→ runner nhận (08:25:42.931Z) → `answered` (08:26:06.150Z), không sinh nhánh,
không sinh diff — đúng tiêu chí mục 9. Nhưng quá trình thử cũng lộ ra bốn lỗ
hổng bên dưới.

## 1. Phạm vi

**Trong phạm vi:** mục A, B, C, D, E của tài liệu này.

**Ngoài phạm vi (để đợt sau):** nút revert trên UI (`prd-agent-dieu-phoi.md`
§10.8), đo chi phí token (§10.7), đóng thread (§10.6), xâu chuỗi nhiều bot phụ
thuộc nhau (§10.2). Không đụng tới bốn việc đó trong đợt này.

---

## A. `api()` không được nuốt lỗi thành công giả

### Bằng chứng

`public/app.js:70-75`:

```js
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "content-type": "application/json", ...(options.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "Không thể kết nối Automation Center.");
  return payload;
}
```

Khi response là **2xx nhưng thân không phải JSON** — ví dụ phiên Cloudflare
Access hết hạn và trình duyệt đi theo redirect về trang đăng nhập HTML —
`response.json()` ném, `.catch(() => ({}))` nuốt, `payload` thành `{}`, và vì
`response.ok === true` nên hàm **trả về `{}` như một lần gọi thành công**.

Hậu quả dây chuyền ở `public/app.js:586-599`:

```js
const created = await api(`${base}/threads`, { method: "POST", body: ... });
target = created.thread_id;   // undefined
state.draft = "";             // xoá trắng chữ người dùng vừa gõ
```

`state.draft` bị xoá **trước khi** biết `thread_id` có thật hay không. Người
dùng gõ một yêu cầu dài, bấm Gửi, chữ biến mất, không toast, không lỗi console,
không có gì được gửi đi.

Đối chiếu D1 lúc `2026-09-01T13:15Z`: bảng `agent_threads` chỉ có 3 dòng, dòng
mới nhất là `2026-09-01T08:25:39.606Z`. Bốn lần bấm Gửi sau mốc đó **không tạo
được gì** — đúng như phân tích trên.

### Yêu cầu

- **A1.** `api()` phải phân biệt "thân rỗng hợp lệ" với "thân không đọc được".
  Response `204`/`205`, hoặc `content-length: 0` → trả `{}` là đúng. Ngược lại,
  nếu `content-type` không phải JSON hoặc parse hỏng → **ném lỗi**, không trả
  `{}`.
- **A2.** Nhận diện riêng trường hợp phiên đăng nhập hết hạn và báo đúng bệnh:
  dấu hiệu là `response.redirected === true` với `new URL(response.url).origin
  !== location.origin`, hoặc `content-type` là `text/html`. Thông báo phải nói
  rõ việc cần làm, ví dụ *"Phiên đăng nhập đã hết hạn. Hãy tải lại trang để đăng
  nhập lại."* — không dùng câu chung chung "Không thể kết nối".
- **A3.** `sendAgentMessage()` chỉ được xoá `state.draft` **sau khi** đã có
  `target` hợp lệ (tạo luồng mới thì `created.thread_id` phải là chuỗi không
  rỗng). Gặp lỗi thì giữ nguyên bản nháp để người dùng gửi lại được, không phải
  gõ lại từ đầu.
- **A4.** Nếu `refreshAgent` hoặc chỗ nào khác cũng dựa vào `api()` trả object
  rỗng như tín hiệu hợp lệ thì rà lại cho nhất quán với A1.
- **A5.** Test mới `tests/api_client.test.mjs`, theo đúng lối cắt nguồn của
  `tests/chat_ui.test.mjs` (đọc `public/app.js`, cắt theo tên hàm, chạy bằng
  `new Function`), với `fetch` giả:
  - 2xx + `application/json` hợp lệ → trả payload.
  - 2xx + `text/html` (trang đăng nhập) → **ném**, và thông điệp phải nhắc tới
    phiên đăng nhập.
  - 2xx + `redirected: true` sang origin khác → **ném**.
  - `204` không thân → trả `{}`, không ném.
  - 4xx có `{"error": "..."}` → ném đúng thông điệp của server (giữ hành vi cũ).

---

## B. Watchdog cho yêu cầu sửa code bị kẹt

### Bằng chứng

`runHealthChecks()` (`src/worker.js:1004-1054`) chạy theo cron 5 phút
(`wrangler.jsonc:38`, `src/worker.js:2598`). Nó dọn runner chết và dọn
`bot_runs` mồ côi (dòng 1025-1043), nhưng **không có một nhánh nào cho
`code_change_requests`**.

Hậu quả đang sống trên production: yêu cầu tạo lúc
`2026-08-29T03:08:20.934Z` tới nay vẫn ở trạng thái `planning` — **ba ngày**.
Vì `src/worker.js:1467` chặn tin nhắn mới khi luồng còn yêu cầu
`queued/planning/applying`, luồng `d695f5b0-bf89-4652-a2d7-429afc00a204`
("bạn có thể làm gì để cải tiến cho tool") bị khoá vĩnh viễn: không ai nhắn
tiếp vào đó được nữa, và trang chủ vẫn đếm "1 yêu cầu đang chạy" cho một việc
đã chết từ lâu.

Đây đúng là `prd-agent-dieu-phoi.md` §10.4, và nó không còn là giả định.

### Yêu cầu

- **B1.** Thêm vào `runHealthChecks()` một nhánh dọn `code_change_requests` kẹt,
  **theo đúng khuôn của nhánh `bot_runs` đã có**: đọc các dòng ở trạng thái
  `queued`/`planning`/`applying`, tính thời gian im lặng từ `updated_at`, quá
  ngưỡng thì `UPDATE ... SET status = 'failed'` kèm lý do đọc được, ghi
  `addAudit(env, "watchdog", "code_request.orphaned", ...)`, và mở incident
  (mở-rồi-đóng-ngay như `run_orphaned` đang làm) để có đường báo ra ngoài.
- **B2.** Ngưỡng phải **rộng hơn** thời gian làm việc hợp lệ của runner, nếu
  không watchdog sẽ giết nhầm việc đang chạy đúng. Runner cho phép tối đa 4 vòng
  model × 300s cộng test tối đa 900s (`AGENT_TEST_TIMEOUT_SECONDS`), nên ngưỡng
  không được thấp hơn tổng đó. Đặt ngưỡng thành hằng số có tên, đặt cạnh
  `RUN_ORPHAN_MS`, kèm chú thích giải thích con số lấy từ đâu.
- **B3.** Tách ra một hàm thuần tuý (kiểu `orphanRuns`) để test được ngoài môi
  trường Worker, và thêm nó vào danh sách `export` cuối `src/worker.js`. Chỉ
  **thêm**, không sửa/không bỏ tên nào đang được export.
- **B4.** Test trong `tests/scheduled.test.mjs` (hoặc file mới nếu gọn hơn):
  yêu cầu vừa cập nhật → **không** bị dọn; yêu cầu im lặng quá ngưỡng → bị dọn;
  yêu cầu ở `awaiting_approval` → **không bao giờ** bị dọn (nó đang chờ người,
  không phải chờ máy); yêu cầu đã `applied`/`failed` → không đụng tới.
- **B5.** Không tự chạy lệnh vá dòng dữ liệu đang kẹt trên D1 production. Chỉ
  ghi vào phần mô tả PR đúng câu lệnh SQL đề xuất để chủ nhân tự quyết định chạy
  hay để watchdog tự dọn sau khi deploy.

---

## C. Danh sách trạng thái "bận" lệch giữa Worker và giao diện

### Bằng chứng

- `public/app.js:231` — `const AGENT_BUSY = ["queued", "planning", "applying", "approved"];` (**4** trạng thái)
- `src/worker.js:1467` — `... WHERE thread_id = ? AND status IN ('queued', 'planning', 'applying') ...` (**3** trạng thái)

Giao diện khoá ô nhập khi yêu cầu ở `approved`, nhưng Worker lại nhận tin nhắn
mới ở đúng trạng thái đó. Hai bên nói hai chuyện khác nhau về cùng một quy tắc.
Và **không bên nào** tính `awaiting_approval` — đúng khoảng trống mà
`prd-agent-dieu-phoi.md` §10.3 đã ghi.

### Yêu cầu

- **C1.** Một nguồn sự thật duy nhất: khai báo danh sách trạng thái bận thành
  hằng số có tên trong `src/worker.js`, thêm vào danh sách `export`, và cho
  `public/app.js` dùng đúng danh sách đó thay vì tự liệt kê lại.
- **C2.** Thêm `awaiting_approval` vào danh sách bận, ở **cả hai** phía.
- **C3.** Thông điệp 409 khi luồng bị khoá bởi `awaiting_approval` phải nói được
  lối ra, vì khác với `planning` thì đây là trạng thái chờ **người** chứ không
  chờ máy: đại ý *"Luồng này đang có một yêu cầu chờ duyệt. Hãy duyệt hoặc từ
  chối nó trước khi nhắn tiếp."* Không dùng chung câu "Agent đang xử lý yêu cầu
  trước" vì câu đó sai bệnh và khiến người dùng ngồi đợi vô ích.
- **C4.** Test đối chiếu (giống tinh thần `tests/test_scope_parity.py`, nhưng
  lần này là JS↔JS): khẳng định danh sách trong `public/app.js` và trong
  `src/worker.js` khớp nhau từng phần tử. Thêm một trạng thái ở một bên mà quên
  bên kia thì test phải đỏ.

---

## D. Test hồi quy cho tiền tố `agent:`

### Bằng chứng

`src/worker.js:605`:

```js
const requestedByEmail = actorEmail.startsWith("agent:") ? actorEmail.slice("agent:".length) : actorEmail;
```

Dòng này vá một sự cố production thật. Lúc `2026-09-01T02:35Z`, agent chạy bot
tạo ảnh cho `PROJ-0170` / `TASK-2026-02160` và chết với `FOREIGN KEY constraint
failed` → HTTP 400 → yêu cầu `failed`: nhánh `bot_action`
(`src/worker.js:~1712`) gọi `runBotCommand` với actor `agent:<email>`, còn cột
`bot_runs.requested_by` lại có `REFERENCES users(email)` và không hề tồn tại
người dùng nào mang tiền tố `agent:`. Bản vá đã lên production trong lần deploy
`07:02:11Z` — đã kiểm chứng bằng cách tải bản Worker đang chạy từ Cloudflare và
tìm thấy `requestedByEmail` trong đó.

Nhưng `grep` toàn thư mục `tests/` **không có file nào** nhắc tới tiền tố này.
Một bản vá không có test là một bản vá chờ ngày bị refactor xoá đi, và lần sau
nó lại giết một yêu cầu thật của người dùng thật.

### Yêu cầu

- **D1.** Test khẳng định: actor `agent:a@b.c` → ghi `bot_runs.requested_by` là
  `a@b.c`; actor `a@b.c` (không tiền tố) → giữ nguyên `a@b.c`; chuỗi có chữ
  `agent:` ở **giữa** thì không bị cắt.
- **D2.** Nếu phải thêm `runBotCommand` (hoặc một hàm thuần tuý tách ra từ nó)
  vào danh sách `export` cuối `src/worker.js` để test được thì cứ thêm — chỉ
  thêm, không đổi cái đang có.

---

## E. Đánh dấu các ô mục 9 đã xác minh vật lý

Trong `docs/prd-agent-dieu-phoi.md` §9, đổi `[ ]` thành `[x]` cho **đúng bốn
dòng** dưới đây, và **chỉ bốn dòng đó**:

| Dòng mục 9 | Bằng chứng ngày 2026-09-01 |
|---|---|
| `node --test --experimental-sqlite tests/permissions.test.mjs` xanh | Chạy bằng `/Users/admin/.local/node/bin/node`: 126 passed / 0 failed / 15 suites |
| `python3 tests/test_scope_parity.py` xanh | Chạy xanh |
| Migration `0004_orchestrator_agent.sql` đã áp lên D1 remote, đủ 4 bảng | Truy vấn D1 remote: cả 4 bảng có mặt, migration ghi nhận áp ngày 2026-08-16 |
| Yêu cầu dạng câu hỏi → `answered`, có tin nhắn agent, **không** nhánh/diff | Thử thật: `status=answered`, `branch=""`, diff 0 byte, `files_changed=0`, `lines_changed=0`, `touches_protected=0`, 2 tin nhắn |

**Không** tick dòng về Scheduled Task: heartbeat của `orchestrator-runner` đã
xác minh là sống (dashboard hiện trực tuyến, `SELECT ... FROM runners` thấy
`last_seen_at` cách hiện tại dưới 1 giây), nhưng **tên** Scheduled Task
`HaviGroup Orchestrator Runner` trên PC thì chưa ai mở ra nhìn tận mắt. Dòng đó
để nguyên `[ ]` cho tới khi có người kiểm trên máy.

Cũng cập nhật `docs/prd-agent-dieu-phoi.md` §10: mục 3 và mục 4 nay đã có bản
vá trong đợt này, ghi rõ như lối đã dùng cho các mục đã xong.

---

## 2. Ràng buộc bắt buộc

1. **Git.** Không rewrite history: không rebase, không amend commit cũ, không
   force-push. Không push và không đụng remote `origin` hay `private` — **chỉ**
   push lên remote `agenthavi`. Làm trên một nhánh mới tách từ `main`, **không**
   commit thẳng vào `main`, kết thúc bằng một pull request.
2. **File cấm đụng.** Không sửa, không commit: `.env.local`,
   `automation_center/.dev.vars`, `automation_center/runner/.env`,
   `automation_center/runner/*.env`, `data/state.json`, `data/state.json.bak-*`,
   và mọi file dump state ERP khác.
3. **Không deploy.** Không chạy `wrangler deploy`, không chạy lệnh ghi lên D1
   production. Việc đưa lên production do chủ nhân quyết sau khi xem PR.
4. **Chạy test bằng đường dẫn sạch.** `node` của Homebrew trên máy này hỏng ABI
   simdjson và chết ngay khi khởi động. Dùng đúng lệnh:

   ```
   /Users/admin/.local/node/bin/node --test --experimental-sqlite automation_center/tests/*.test.mjs
   ```

   Thiếu cờ `--experimental-sqlite` sẽ báo thiếu `node:sqlite`. Đó là lỗi thiếu
   cờ, **không** phải lỗi thiếu module — không được đi vá môi trường, không nhồi
   thư viện, không tạo symlink dylib.
5. **Không nới lỏng test để cho xanh.** Nếu một assertion đang đỏ, sửa code cho
   đúng hoặc dừng lại hỏi; không đổi assertion thành dễ hơn.
6. **Gặp chỗ mơ hồ hoặc rủi ro thì DỪNG và hỏi**, đừng tự đoán.

## 3. Nghiệm thu đợt này

- [ ] Toàn bộ `automation_center/tests/*.test.mjs` xanh bằng lệnh ở ràng buộc 4,
      **và** `python3 automation_center/tests/test_scope_parity.py` xanh.
- [ ] Có test mới cho A, B, C, D; mỗi test đều **đỏ trước, xanh sau** khi áp bản
      vá (nêu bằng chứng trong mô tả PR).
- [ ] `git diff --stat` của PR không chứa file nào trong danh sách cấm ở ràng
      buộc 2.
- [ ] Mô tả PR ghi rõ: câu SQL đề xuất cho dòng `planning` đang kẹt (B5), và
      những gì **chưa** làm.
- [ ] Nhánh đã push lên remote `agenthavi`, PR đã mở, `main` không có commit mới
      nào do đợt này tạo ra.

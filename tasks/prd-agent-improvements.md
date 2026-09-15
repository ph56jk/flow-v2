# PRD — Cải tiến Agent (Flow Agent-mode + Agent điều phối)

Tài liệu này gom các cải tiến **cụ thể, khả thi, có bằng chứng đọc được từ
code hoặc từ số đo thật** cho hai mảng agent của repo:

1. `flow_web/agent_brain.py`, `agent_chat.py`, `agent_bot.py` và đường chạy
   Flow Agent-mode trong `flow_web/service.py`;
2. Agent điều phối của `automation_center/` (Worker + runner + web).

Nguồn: `execution-notes.md` (các số đo trên card thật),
`automation_center/docs/prd-agent-dieu-phoi.md`,
`automation_center/docs/prd-do-ben-agent-dieu-phoi.md`,
`tasks/prd-flow-agent-automation-v2.md`, và kết quả review bảo mật vừa xong.

**Mọi mục dưới đây đều dẫn `file:line`.** Mục nào là suy đoán thì ghi rõ là
suy đoán. Mục nào đã có test đỏ đi kèm thì ghi tên test ở cột cuối bảng §2.

---

## 1. Phạm vi

**Trong phạm vi:** A1–A8 (Flow Agent-mode), B1–B5 (Agent điều phối),
C1–C4 (bảo mật, từ review vừa xong).

**Ngoài phạm vi đợt này:**

- Nút revert trên UI cho thay đổi đã `applied` (`prd-agent-dieu-phoi.md` §10.8).
- Đóng thread (`prd-agent-dieu-phoi.md` §10.6).
- Xâu chuỗi nhiều bot phụ thuộc nhau (`prd-agent-dieu-phoi.md` §10.2).
- Bỏ hẳn Google Sheet prompt (`prd-flow-agent-automation-v2.md` Non-Goals).
- Không đổi hành vi duyệt ảnh: dashboard vẫn là chốt người, không tự duyệt.

**Ràng buộc bắt buộc** (giữ nguyên từ `prd-do-ben-agent-dieu-phoi.md` §2):

1. Không rewrite history, không force-push, làm trên nhánh mới tách từ `main`,
   kết thúc bằng pull request.
2. Không sửa/commit `.env.local`, `automation_center/.dev.vars`,
   `automation_center/runner/*.env`, `data/state.json*`.
3. Không `wrangler deploy`, không ghi lên D1 production.
4. Lệnh chạy test (đúng đường dẫn sạch):
   - Python: `python3 -m unittest tests.test_agent_improvements -v`
     (repo dùng `unittest`; `pytest` cũng gom được vì test viết bằng
     `unittest.TestCase`. Máy này **chưa cài** `pytest`.)
   - JS: `/Users/admin/.local/node/bin/node --test --experimental-sqlite automation_center/tests/*.test.mjs`
     (thiếu `--experimental-sqlite` là **thiếu cờ**, không phải thiếu module —
     không đi vá môi trường.)
5. **Không nới lỏng test để cho xanh.** Assertion đỏ thì sửa code, hoặc dừng
   lại hỏi.

---

## 2. Xếp hạng ưu tiên

Xếp theo **rủi ro × lợi ích**, cao xuống thấp. "Đo được" nghĩa là đã có con số
thật trong `execution-notes.md`, không phải ước lượng.

| # | Cải tiến | Rủi ro nếu không làm | Lợi ích | Công | Test đỏ |
|---|---|---|---|---|---|
| C1 | Chặn hẳn connector Telegram ở API settings | **Cao** — kho thông tin xác thực sống cho một connector đã gỡ | Bịt một đường ra ngoài | Nhỏ | `TelegramConnectorRemovedTests` |
| C2 | "Xoá Gemini key" phải nói thật | **Cao** — nút báo đã xoá nhưng khoá vẫn sống từ env | Người dùng tin được cái nút | Nhỏ | `ClearGeminiKeyTellsTheTruthTests` |
| C3 | Bot chỉ nghe người trong danh sách | **Cao** — ai bình luận được là ra lệnh được | Chốt quyền cho bot ERP | Vừa | `BotObeysOnlyAllowedAuthorsTests` |
| C4 | Nút reset custom phải hỏi lại | Vừa — một cú bấm xoá sạch graph, không hoàn tác | Chống mất việc | Nhỏ | `ResetAutomationNeedsConfirmationTests` |
| A1 | Bỏ khoảng chờ chết 45s trong Agent mode | Vừa — **đo được 45s/ý tưởng**, mất trắng | ~30s/card | Nhỏ | `AgentModeDeadWaitTests` |
| A2 | Chờ hộp phê duyệt thoát sớm khi không có hộp | Vừa — **đo được lệch 26s giữa hai lượt** | Tới 40s/card | Vừa | `ApprovalDialogWaitTests` |
| A3 | reCAPTCHA cho 2K phải dùng action của 2K | Vừa — mọi token cho upscale mint bằng `GENERATE` | Có thể là gốc của mọi 403 | Nhỏ | `RecaptchaActionTests` |
| A4 | Thử UI download **trước** khi gắn cờ chờ người | **Cao** — cờ chờ người đang tắt đúng đường cứu được ảnh | Ảnh được cứu thay vì nằm chờ | Vừa | `UiFallbackBeforeManualFlagTests` |
| A5 | Đường cứu 2K bằng UI phải ghi log khi **thành công** | Vừa — đường thật sự cứu ảnh thì vô hình trong log | Đọc log là biết đường nào cứu | Nhỏ | `UiDownloadLogsSuccessTests` |
| A6 | `publish_erp_review` phải nhận danh sách chỉ số | **Cao** — một lần gọi sửa 1 ảnh đã đăng 6 ảnh, 12→17 | Chống làm hỏng thẻ thật | Vừa | `PublishScopedToIndicesTests` |
| A7 | Lượt chạy hỏng 5 giây không được đẩy lịch sử thật ra | Vừa — sự cố quota đã đẩy hết lịch sử thật khỏi dashboard | Chẩn đoán được sự cố | Nhỏ | `HistoryKeepsRealRunsTests` |
| A8 | Subprocess đoán ý không được thừa kế khoá API | **Cao** — CLI chạy theo lời bình luận người lạ, mang cả env | Bịt một đường lộ khoá | Nhỏ | `BrainSubprocessEnvTests` |
| A9 | Trần hỏi model phải có hiệu lực quá một vòng quét | Vừa — trần reset mỗi vòng ⇒ không có trần thật | Chặn hoá đơn chạy | Vừa | `BrainCallBudgetTests` |

*(Phần B — Agent điều phối — nằm ở §4, bảng ưu tiên riêng.)*

---

## 3. Phần A — Flow Agent-mode (`flow_web/`)

### A1. Bỏ khoảng chờ chết 45s trong Agent mode

**Bằng chứng.** `flow_web/service.py:25302-25312`:

```python
network_wait_s = (
    min(ui_timeout_s, self._flow_agent_network_wait_seconds())
    if flow_agent_enabled
    else ui_timeout_s
)
try:
    result = await interceptor.wait_for(
        "batchGenerateImages", timeout=network_wait_s, require_success=True,
    )
```

`_flow_agent_network_wait_seconds()` (`service.py:16478-16495`) trả `45.0` mặc
định. Chính docstring của nó đã ghi: *"In Agent mode this wait almost always
runs out in full: the panel does not produce a successful batchGenerateImages
response."* `execution-notes.md` đo trên **ba card thật**: cả ba đều hết giờ
rồi mới tìm thấy ảnh qua project poll ~10s sau. Đo ở `15`: chờ đúng 15.0s,
poll tìm thấy ảnh ~9s sau, ảnh sạch và 2K — **tiết kiệm 30s, không mất gì**.

**Yêu cầu.**

- **A1.1** Trong Agent mode, mặc định không được là 45. Đặt mặc định
  `FLOW_AGENT_NETWORK_WAIT_SECONDS` xuống **15.0**, giữ nguyên đường env để
  đo lại.
- **A1.2** Cận dưới của kẹp giá trị phải cho phép **0** (bỏ hẳn khoảng chờ),
  không phải `5.0` như hiện nay (`service.py:16493`). Agent mode không sinh
  response ấy thì phải cho phép nói thẳng "đừng chờ".
- **A1.3** Khi `flow_agent_enabled`, thay vì *chờ rồi mới poll*, phải **đua**
  hai đường: `interceptor.wait_for("batchGenerateImages")` và project poll,
  ai xong trước thì lấy. Đường nào thắng phải ghi vào log lượt chạy, để lần
  sau còn đo được.
- **A1.4** Ghi vào log lượt chạy con số thật đã chờ (`waited_s`) chứ không chỉ
  ghi "timeout" — hiện tại `service.py:25316` chỉ ghi chuỗi lỗi.

**Không làm:** không đụng đường không-Agent (`ui_timeout_s` giữ nguyên).

### A2. Chờ hộp phê duyệt phải thoát sớm khi không có hộp nào

**Bằng chứng.** `flow_web/service.py:25289-25292` gọi
`_approve_flow_agent_generation(page, timeout_s=min(45.0, max(10.0, ui_timeout_s / 6)))`.

`_approve_flow_agent_generation` (`service.py:26327-26508`) là một vòng poll
tới `deadline`, và ở `service.py:26496-26499`:

```python
if not ok:
    await asyncio.sleep(0.5)
    continue
```

Khi Flow **đã nhớ** lựa chọn "không hỏi lại" từ lượt trước, hộp phê duyệt
không bao giờ hiện. Vòng lặp vẫn quay đủ `timeout_s` (tới 45s) rồi trả
`False, "approval dialog not visible"`. Đây là **cùng một loại lỗi với A1**:
chờ một thứ đã biết là sẽ không đến. `execution-notes.md` ghi bước này lệch
**26s** giữa hai lượt và **nuốt trọn 30s vừa tiết kiệm được ở A1**.

Đáng chú ý: script trong `page.evaluate` **đã** phân biệt được hai ca — nó trả
`{ok, waiting, detail}` với `waiting: true` nghĩa là *chữ phê duyệt có hiện,
nút thì chưa tìm ra* (`service.py:26469`). Thông tin cần thiết đã có sẵn,
chỉ là chưa ai dùng.

**Yêu cầu.**

- **A2.1** Tách hai ca:
  - `waiting == True` (hộp có hiện, chưa bấm được) → chờ tiếp tới `deadline`,
    y như bây giờ.
  - `waiting == False` liên tiếp qua một cửa sổ ân hạn ngắn
    (hằng số có tên, mặc định **5.0s**) → thoát ngay, trả
    `False, "no approval dialog (Flow đã nhớ lựa chọn)"`.
- **A2.2** Câu trả về phải phân biệt được "Flow không hỏi nữa" với "có hỏi mà
  không bấm được" — hiện cả hai đều rơi về `last_detail`, và log lượt chạy
  (`service.py:25293-25300`) in ra cùng một câu "không thấy hộp phê duyệt".
  Ca thứ nhất là **bình thường**; ca thứ hai là **sự cố cần người xem**.
- **A2.3** Cửa sổ ân hạn phải là hằng số có tên đặt cạnh chỗ dùng, kèm chú
  thích lấy số từ đâu.

### A3. reCAPTCHA cho 2K phải mint bằng action của 2K

**Bằng chứng.** `flow_web/service.py:21447-21461`:

```python
token = await page.evaluate(
    f"""
    async () => {{
        try {{
            return await window.grecaptcha.enterprise.execute(
                '{RECAPTCHA_SITE_KEY}',
                {{ action: 'GENERATE' }}
            );
```

Hàm này được gắn vào `FlowAPI.get_recaptcha_token` (`service.py:21547`) và là
nguồn token cho **cả** sinh ảnh **lẫn** `flow/upsampleImage`. `GENERATE` là
action của việc sinh ảnh, không phải của upscale. reCAPTCHA Enterprise chấm
điểm theo cặp (site key, action); gửi sai action là một lý do rất đời thường
để bị trả `HTTP 403 ... reCAPTCHA evaluation failed` — đúng lỗi đã ăn **mọi**
ảnh chưa được 2K trên card thật (`execution-notes.md`).

**Đây vẫn là giả thuyết chưa xác minh**, và `execution-notes.md` đã ghi việc
cần làm: *"worth capturing what the Flow page itself sends when a human clicks
2K"*. PRD này giữ nguyên thứ tự đó: **đo trước, sửa sau** — nhưng phần *code*
phải sẵn sàng để đổi action mà không phải sửa chuỗi lồng trong f-string.

**Yêu cầu.**

- **A3.1** Tách phần sinh script ra một hàm thuần tuý có tên, nhận `action`:
  `_recaptcha_token_script(action: str) -> str`. Không còn chuỗi `'GENERATE'`
  viết cứng trong thân `_compat_get_recaptcha_token`.
- **A3.2** `get_recaptcha_token` nhận tham số `action` (mặc định `"GENERATE"`
  để đường sinh ảnh không đổi hành vi), và đường upscale
  (`_flow_upsample_client_context`, `service.py:16285-16306`) truyền action
  của mình.
- **A3.3** Tên action của upscale lấy từ env `FLOW_UPSAMPLE_RECAPTCHA_ACTION`,
  mặc định `"GENERATE"` **cho tới khi đo được** cái Flow thật gửi. Nghĩa là
  đợt này **không đổi hành vi**, chỉ mở đường đổi bằng một biến môi trường —
  đúng lối `FLOW_AGENT_NETWORK_WAIT_SECONDS` đã dùng để đo A1.
- **A3.4** Việc đo (bắt request lúc người thật bấm 2K trên trang Flow) là một
  việc **tay**, ghi kết quả vào `execution-notes.md`. Không tự động hoá.

### A4. Đường cứu bằng UI phải được thử **trước** khi gắn cờ chờ người

**Đính chính một chỗ tài liệu đang sai.** `execution-notes.md:20` và
`docs/giao-viec-codex-kiem-thu-2.md:79,121` còn nhắc
`_flow_upsample_rounds_for_next_image` / `FLOW_UPSAMPLE_RECAPTCHA_GIVE_UP_AFTER`.
Hai cái tên đó **không còn trong code**: thêm ở `04b6ee2`, gỡ ở `17d860a`, và
được thay bằng một cơ chế **tốt hơn** — bản ghi bền theo từng media
(`FLOW_UPSAMPLE_RECAPTCHA_RESULT_KEY = "flow_upsample_recaptcha"`,
`service.py:16281`), ngưỡng `FLOW_UPSAMPLE_RECAPTCHA_MANUAL_AFTER_DEFAULT = 2`
(`:16282`), cooldown 24h (`:16283`), cờ `needs_manual_review` và chốt chặn
`_flow_upsample_recaptcha_record_blocks` (`:16345-16348`). PRD này **không đề
nghị khôi phục** hai cái tên cũ; bộ đếm theo lượt chạy ở A4.4 là một cơ chế
khác, nên nó mang một tên khác
(`FLOW_UPSAMPLE_RECAPTCHA_RUN_GIVE_UP_AFTER`). Việc cần làm là **sửa tài liệu
cho khớp code**.

**Vấn đề thật còn lại.** Cơ chế mới và số đo trong `execution-notes.md` đang
nói ngược nhau. `service.py:16909-16918`:

```python
if refused_every_round:
    persisted = await self._record_flow_upsample_recaptcha_rejection(...)
    if self._flow_upsample_recaptcha_record_blocks(persisted):
        # The exact media is now durable state on its job. Do not pay
        # for the UI fallback on the pass that crosses the threshold.
        return jpeg_bytes
```

Và ở đầu hàm, `service.py:16829-16834`, mọi lượt sau đó cũng `return jpeg_bytes`
ngay lập tức. Nghĩa là: **khi một media bị gắn cờ chờ người, đường
`_upsample_image_via_flow_ui_download` không bao giờ được chạy nữa cho media
đó** — kể cả lượt gắn cờ.

Nhưng số đo nói đường ấy chính là đường cứu được ảnh:
*"the retry is not what saves the image; `_upsample_image_via_flow_ui_download`
is."* Vậy cơ chế đang tắt đúng cái thứ hoạt động, ở đúng lúc cần nó nhất.

**Yêu cầu.**

- **A4.1** Thứ tự phải là: hết vòng API → **thử UI download** → chỉ khi UI
  download *cũng* hỏng mới ghi `needs_manual_review`. Bỏ nhánh `return
  jpeg_bytes` ở `service.py:16915-16918`.
- **A4.2** Chốt chặn đầu hàm (`:16829-16834`) phải chỉ chặn **đường API**, không
  chặn đường UI: media đã gắn cờ vẫn được thử UI download một lần mỗi lượt,
  vì đường ấy không tiêu token reCAPTCHA nào.
- **A4.3** Bản ghi bền phải phân biệt hai loại hỏng: `api_refused`
  (reCAPTCHA từ chối, UI cứu được — **không** cần người) và `both_failed`
  (cả hai đường hỏng — **mới** cần người). Hôm nay chỉ có một loại.
- **A4.4** Cắt phí vòng lặp trong một lượt chạy: giữ một bộ đếm **theo lượt
  chạy** (không bền, chỉ trong bộ nhớ) — sau
  `FLOW_UPSAMPLE_RECAPTCHA_RUN_GIVE_UP_AFTER` (mặc định 2) ảnh liên tiếp mà mọi
  vòng đều bị từ chối, những ảnh **còn lại của cùng lượt**
  chỉ mint một token rồi rơi thẳng xuống UI download. Bản ghi bền theo media
  không cứu được chỗ này: media mới thì chưa có bản ghi, nên ảnh nào cũng trả
  đủ 3 vòng cho lần đầu. Trên card 12 ảnh với reCAPTCHA hỏng toàn cục, đó là
  **36 lần mint** (mỗi lần một lượt giành `_browser_session_lock`) cộng
  24 × 2.0s backoff (`FLOW_UPSAMPLE_RECAPTCHA_BACKOFF_S`, `:16279`).
- **A4.5** Một lần upscale API thành công đã reset bản ghi bền
  (`_clear_flow_upsample_recaptcha_rejections`, `:16886`); bộ đếm theo lượt
  chạy ở A4.4 cũng phải reset ở đúng chỗ đó.
- **A4.6** Sửa `execution-notes.md` và `docs/giao-viec-codex-kiem-thu-2.md` để
  không còn nhắc hai cái tên đã gỡ.

**Ghi chú cài đặt — A4.2 từng xanh giả, đã vá bằng phép thử chứ không phải code.**
Code đúng từ đầu: `api_blocked` chỉ đưa `rounds` về 0, đường UI vẫn chạy
(`service.py:17096-17102`). Nhưng phép thử khoá nó,
`test_the_ui_path_is_tried_before_a_media_is_handed_to_a_human`, **không hề
chạm tới chốt chặn**: ở đó đường UI cứu được ảnh mỗi lượt nên bản ghi bền chỉ
là `api_refused`, `api_blocked` không bao giờ bật. Dựng lại hành vi cũ (chặn cả
đường UI khi cờ bật) mà cả lớp vẫn xanh — đó là bằng chứng. Bài mới
`test_media_da_gan_co_cho_nguoi_van_duoc_thu_ui_moi_luot` bật cờ thật trước rồi
mới hỏi, và đột biến ấy giết nó. Bài cũ ở lại, nhưng đổi nhãn về A4.1 cho đúng
việc nó làm.

### A5. Đường cứu 2K bằng UI phải ghi log khi thành công

**Bằng chứng.** `_upsample_image_via_flow_ui_download`
(`service.py:16754-16798`) có bốn nhánh hỏng, cả bốn đều
`log.warning(...)` (`16772`, `16783`, `16796`, và
`"Flow UI 2K download skipped: media tile not found"` ở `16772`).
Nhánh **thành công** — `return await asyncio.to_thread(target_path.read_bytes)`
ở `16795` — không ghi gì cả.

Hậu quả đã sống: `execution-notes.md` ghi *"it does not log on success, which
is why the path is easy to miss"*. Người đọc log thấy 3 dòng 403 rồi im lặng,
kết luận sai là ảnh hỏng, trong khi ảnh đã được cứu.

**Yêu cầu.**

- **A5.1** Ghi log ở nhánh thành công: media id, số byte, và **đường nào đã
  cứu** (`ui_download`).
- **A5.2** `_upsample_image_via_flow` phải ghi vào **log lượt chạy**
  (`store.append_log`), không chỉ `log.warning` của tiến trình, đường nào đã
  cho ra ảnh 2K: `api` hay `ui_download`. Dashboard là nơi người vận hành
  thật sự đọc.
- **A5.3** Không đổi giá trị trả về, không đổi thứ tự fallback.

### A6. `publish_erp_review` phải nhận danh sách chỉ số

**Bằng chứng.** `flow_web/service.py:18033-18076`: hàm duyệt **mọi** artifact
và đăng bất cứ chỉ số nào (a) chưa có quyết định trong `dashboard_approvals`,
(b) chưa có `items[index].comment`, (c) chưa nằm trên thẻ. Không có tham số
nào để thu hẹp.

`reopen_watermark_rejections` (`service.py:18280`) **xoá** entry duyệt
(`approvals.pop(str(index), None)`) rồi `_rearm_erp_delivery_after_reopen`.
Nếu bình luận review của chỉ số đó đã bị xoá khỏi thẻ, chỉ số ấy thoả cả ba
điều kiện và được đăng lại.

Đó chính là sự cố thật trong `execution-notes.md`: *"one call meant to replace
a single image posted six and took the card from 12 attachments to 17."*

**Yêu cầu.**

- **A6.1** `publish_erp_review(job_id, *, indices: Sequence[int] | None = None)`.
  `None` giữ nguyên hành vi cũ (đăng mọi ảnh chưa quyết). Có danh sách thì
  **chỉ** những chỉ số đó được xét — mọi chỉ số khác bỏ qua, kể cả khi đủ
  điều kiện.
- **A6.2** Chỉ số ngoài khoảng `[0, len(artifacts))` → `400`, không âm thầm bỏ.
- **A6.3** Route API tương ứng nhận `indices` (rỗng = tất cả), và tài liệu
  vận hành phải nói rõ: **dùng `indices` khi đang sửa một ảnh**, vì gọi trống
  là lệnh "đăng bù mọi ảnh còn thiếu".
- **A6.4** Kết quả trả về phải kể rõ đã bỏ qua bao nhiêu chỉ số vì không nằm
  trong danh sách.

### A7. Lượt chạy hỏng 5 giây không được đẩy lịch sử thật ra

**Bằng chứng.** `flow_web/store.py:31` `JOB_HISTORY_LIMIT = 50`;
`trim_job_history` (`store.py:62-70`) giữ 50 lượt mới nhất, cộng thêm những
lượt còn *nợ ảnh ERP* (`job_owes_erp_images`, `store.py:35-59`).

Nhưng `job_owes_erp_images` trả `False` khi `not job.artifacts` (`store.py:47`).
Trong sự cố quota ngày 18–19/08 (`execution-notes.md`), watcher và agent bot
mỗi cái fan-out một job cho mỗi thẻ con, **mỗi 3 phút**, mỗi job chết trong
~5 giây ở bước trình duyệt — **không artifact nào**. Sáu thẻ lấp đầy cả 50 ô
trước trưa và đẩy lịch sử thật ra khỏi dashboard, *"which is what made the
failure look like 'nothing runs' instead of 'quota'."*

**Yêu cầu.**

- **A7.1** `trim_job_history` phải giữ riêng một hạn ngạch tối thiểu cho các
  lượt chạy **có artifact** (hằng số có tên, đề xuất
  `JOB_HISTORY_MIN_WITH_ARTIFACTS = 20`): một loạt lượt hỏng không artifact
  không được đẩy hết chúng ra.
- **A7.2** Giữ nguyên `JOB_HISTORY_CEILING = 500` làm trần tuyệt đối.
- **A7.3** Thứ tự mới nhất-trước phải giữ nguyên trong danh sách trả về —
  đây là nguồn cho dashboard, đảo thứ tự là đổi giao diện.
- **A7.4** Không đổi `job_owes_erp_images`: nó đang đúng việc của nó.

### A8. Subprocess đoán ý không được thừa kế khoá API

**Bằng chứng.** `flow_web/agent_brain.py:355-371`:

```python
env={key: value for key, value in os.environ.items() if not key.startswith("ERP_")},
```

Chỉ `ERP_*` bị gỡ. Còn lại đi hết vào tiến trình con: `GEMINI_API_KEY`,
`GOOGLE_API_KEY`, `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`RUNNER_SHARED_SECRET`, mọi thứ trong `.env.local`.

Tiến trình con này chạy vì **một bình luận trên thẻ ERP** — nội dung do người
ngoài viết (§C3). `build_argv` (`agent_brain.py:311-343`) đã khoá tay CLI rất
kỹ (`--allowed-tools ""`, `--strict-mcp-config`, `--sandbox read-only`), nhưng
khoá tay một tiến trình mà vẫn đưa nó cả chùm chìa khoá thì hàng rào chỉ còn
là một lớp.

**Yêu cầu.**

- **A8.1** Đổi từ **danh sách cấm theo tiền tố** sang **luật cấm theo hình
  dạng**: gỡ mọi biến có tên khớp `ERP_*`, `*_API_KEY`, `*_TOKEN`, `*SECRET*`,
  `*PASSWORD*`, `*_KEY`, `AWS_*`, `FLOW_*` (không phân biệt hoa thường).
- **A8.2** Giữ lại rõ ràng những biến CLI **thật sự cần**: `PATH`, `HOME`,
  `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TMP`, `TEMP`, `SystemRoot`,
  `LANG`, `LC_ALL`, và biến đăng nhập của chính CLI nếu có. Danh sách này
  phải là hằng số có tên trong `agent_brain.py`, không rải rác.
- **A8.3** Không log giá trị nào bị gỡ; log **tên** thì được.
- **A8.4** Bảo toàn hành vi hiện tại: `_run_cli` vẫn `timeout`, vẫn `cwd`.

### A9. Trần hỏi model phải có hiệu lực quá một vòng quét

**Bằng chứng.** `BrainConfig.max_calls = 5` (`agent_brain.py:151`) được
`agent_bot.py:1757` áp:

```python
if self._brain_calls >= self.brain_max_calls:
```

Nhưng `self._brain_calls = 0` chạy lại ở `agent_bot.py:1837` và `2289` — tức
là **reset mỗi vòng quét**. Vòng quét chạy mỗi ~3 phút, nên trần thật là
5 lượt × 20 vòng = **100 lượt gọi CLI mỗi giờ**, không trần ngày, không đếm
chi phí. Mỗi lượt là một `subprocess.run` với `timeout_s=120`
(`agent_brain.py:148`), chạy **tuần tự trong vòng quét**: 5 lượt CLI treo là
bảng đứng hình 10 phút.

Đây đúng khoảng trống mà `prd-agent-dieu-phoi.md` §10.7 ghi cho phía
điều phối ("chưa có đo đếm chi phí… chưa có hạn mức ngày"), chỉ khác là ở đây
nó đã có bằng chứng code.

**Yêu cầu.**

- **A9.1** Thêm trần cuốn chiếu theo **giờ** và theo **ngày**
  (`FLOW_AGENT_BRAIN_MAX_CALLS_PER_HOUR`, mặc định 30;
  `FLOW_AGENT_BRAIN_MAX_CALLS_PER_DAY`, mặc định 150), lưu trong
  `AgentBotState` để sống qua khởi động lại — cùng chỗ với
  `already_handled` (`agent_bot.py:1046`).
- **A9.2** Trần theo vòng quét (`max_calls`) giữ nguyên, chồng lên trần mới.
- **A9.3** Chạm trần → ghi log **một** dòng cho mỗi cửa sổ, không mỗi câu một
  dòng, và trả `None` y như bây giờ (rơi về bản hướng dẫn).
- **A9.4** `timeout_s` mặc định 120s cho một lượt là quá dài khi 5 lượt nối
  đuôi trong một vòng quét: hạ mặc định xuống **45s**, giữ env
  `FLOW_AGENT_BRAIN_TIMEOUT` để nới lại.

---

## 4. Phần B — Agent điều phối (`automation_center/`)

Bảng ưu tiên riêng cho phần này:

| # | Cải tiến | Rủi ro nếu không làm | Lợi ích | Công | Test đỏ |
|---|---|---|---|---|---|
| B1 | Ngưỡng watchdog phải bám ngân sách model | **Cao** — watchdog đang giết yêu cầu còn sống | Hết báo hỏng giả | Vừa | `watchdog_budget.test.mjs` |
| B2 | `saveCodeScope` phải chặn glob **bao trùm** file được bảo vệ | **Cao** — cấp `**` là qua được lớp một | Lớp phạm vi có thật | Vừa | `code_scope_covering_glob.test.mjs` |
| B3 | Nhánh `agent/<id>` mồ côi phải được dọn | Vừa — nhánh cũ bị `checkout -B` đè im lặng | Không mất việc âm thầm | Vừa | `orphan_branch_cleanup.test.mjs` |
| B4 | Trần số lệnh bot phải là hằng số dùng chung | Thấp — hai chỗ chép số `5` | Chống trôi Worker↔runner | Nhỏ | `bot_command_limit_parity.test.mjs` |
| B5 | Hạn mức yêu cầu sửa code theo ngày | Vừa — không có trần nào cho model | Chặn hoá đơn chạy | Vừa | `code_request_quota.test.mjs` |

### B1. Ngưỡng watchdog phải bám theo ngân sách model, không phải một số viết tay

**Bằng chứng.** `src/worker.js:877-880`:

```js
// Runner có thể im lặng suốt lúc planning: tối đa 4 vòng model × 300 giây và
// test tối đa 900 giây = 35 phút.  45 phút chừa 10 phút cho git/mạng; đổi
// MAX_ROUNDS, timeout model hoặc timeout test thì phải xét lại ngưỡng này.
const CODE_REQUEST_ORPHAN_MS = 45 * 60 * 1000;
```

Chú thích ấy nói đúng việc phải làm. **Việc đó chưa được làm.** Commit
`976fc70` ("Nới ngân sách một lượt model từ 300s lên 1800s") chỉ sửa
`runner/orchestrator_runner.py` và test Python của nó; `src/worker.js`
không đổi một dòng nào.

Ngân sách thật hôm nay:

| Hằng số | Vị trí | Giá trị |
|---|---|---|
| `OPENAI_TIMEOUT` | `runner/orchestrator_runner.py:111` | `1800` (trước là `300`) |
| `MAX_ROUNDS` | `runner/orchestrator_runner.py:154` | `4` |
| `TEST_TIMEOUT` | `runner/orchestrator_runner.py:82` | `900` |

- Chú thích tính cho: 4×300 + 900 = 2100s = **35 phút** → ngưỡng 45 phút, dư 10.
- Thật sự bây giờ: 4×1800 + 900 = 8100s = **135 phút** so với ngưỡng 45 phút.
- Ngay cả **một** lượt model rồi chạy test: 1800 + 900 = 2700s = **đúng 45 phút**,
  dư **bằng không**.

**Runner thật sự im lặng suốt quãng đó**, không có gì che:

- Heartbeat (`runner/orchestrator_runner.py:237-240`) POST tới
  `/api/runner/heartbeat`, và `runnerHeartbeat` (`src/worker.js:681-689`) chỉ
  `UPDATE` bảng `runners`. Nó **không** chạm
  `code_change_requests.updated_at`, mà `orphanCodeRequests`
  (`src/worker.js:913-919`) chỉ nhìn đúng cột ấy.
- Lần ghi cuối là lúc claim: `status='planning', started_at=?, updated_at=?`
  (`src/worker.js:1673-1677`).
- `plan_change` (`runner/orchestrator_runner.py:1015-1038`) lặp
  `for _ in range(MAX_ROUNDS)` và **không gọi `report()` giữa các vòng** —
  không có `report(..., "planning")` ở bất kỳ đâu trong runner.

Nên `CODE_REQUEST_WATCHDOG_STATUSES` (`src/worker.js:911`, có `planning`) sẽ đóng
yêu cầu thành `failed` với câu "runner ngừng cập nhật" (`src/worker.js:1075-1103`),
mở incident, ghi audit — **trong khi runner vẫn đang chạy**. Sau đó runner báo
`awaiting_approval` và bị Worker từ chối, `R:1237` xoá nhánh, công việc mất
trắng. Đây là một lỗi im lặng đúng nghĩa: người dùng thấy "yêu cầu hỏng",
không thấy "watchdog giết nhầm".

**Không test nào ghim con số này.** `tests/health.test.mjs:24` đọc
`codeRequestOrphanMs` từ `healthThresholds()` rồi test **tương đối** với nó,
nên đổi ngưỡng vẫn xanh. `tests/test_orchestrator_runner_resilience.py:199`
ghim `1800` ở phía Python, không nối sang JS.

**Yêu cầu.**

- **B1.1** `CODE_REQUEST_ORPHAN_MS` phải **suy ra** từ ngân sách, không viết
  tay: `(MAX_ROUNDS × OPENAI_TIMEOUT + TEST_TIMEOUT) × hệ số dư`, hệ số dư
  đề xuất `1.3`. Với số hôm nay: 8100 × 1.3 ≈ **175 phút**.
- **B1.2** Worker không đọc được env của runner, nên ba con số phải thành một
  hằng số công bố ở **một** chỗ trong `src/worker.js`
  (`RUNNER_MODEL_BUDGET = { maxRounds, modelTimeoutS, testTimeoutS }`), và
  phải có **test parity Worker↔runner** đọc
  `runner/orchestrator_runner.py` bằng regex rồi so — đúng lối
  `agent_busy_parity.test.mjs` đã đặt tên cho việc này (*"parity JS↔JS tương
  tự ý nghĩa parity Worker↔runner"*).
- **B1.3** *(khuyến nghị mạnh, rẻ hơn nhiều)* Runner gọi
  `report(request_id, "planning")` sau **mỗi** vòng model
  (`runner/orchestrator_runner.py:1015-1038`). `src/worker.js:1746-1748` đã bump
  `updated_at` cho đường `planning`/`applying`, nên chỉ cần thêm lời gọi.
  Làm được B1.3 thì ngưỡng chỉ cần bao **một** vòng, không phải bốn.
- **B1.4** Chú thích ở `src/worker.js:877-879` phải sửa cho khớp — hôm nay nó ghi
  `300 giây` và `35 phút`, cả hai đều sai.
- **B1.5** Không đụng `RUN_ORPHAN_MS` (`:876`) và `RUNNER_STALE_MS` (`:872`):
  hai cái đó đo việc khác và đang đúng.

### B2. `saveCodeScope` phải chặn cả glob **bao trùm** file được bảo vệ

**Bằng chứng.** `src/worker.js:1644-1645`:

```js
const blocked = globs.filter((glob) => PROTECTED_GLOBS.some((protectedGlob) => protectedGlob === glob));
if (blocked.length) return error(`Không thể cấp phạm vi trùng khít file được bảo vệ: ${blocked.join(", ")}`);
```

`===` là **so khớp chữ**. Cấp `automation_center/src/worker.js` thì bị chặn;
cấp `automation_center/**`, `automation_center/src/*`, hay `**` thì **được**,
dù cả ba đều bao trùm chính file ấy. `prd-agent-dieu-phoi.md` §8 đã ghi nhận
đúng chỗ này.

**Cần nói cho cân bằng:** lớp này thủng nhưng **không phải lớp duy nhất**.
Phía sau còn ba lớp thật sự chặn:

- `auditChangedFiles` (`src/worker.js:1187-1202`) gắn cờ `touches_protected`;
- `src/worker.js:1593-1594` cấm người không phải Owner duyệt thay đổi chạm file
  bảo vệ;
- runner tự chặn: `runner/orchestrator_runner.py:967` loại file bảo vệ khỏi danh sách
  sửa được, `:1032-1034` từ chối đọc nội dung file bảo vệ.

Nên đây là **làm dày hàng rào**, không phải bịt một lỗ đang chảy. Xếp "Cao" vì
lớp một là lớp người vận hành nhìn thấy và tin tưởng khi cấp quyền.

**Yêu cầu.**

- **B2.1** Đổi từ so khớp chữ sang **so khớp bao trùm**: từ chối glob nào
  `matchesAnyGlob(protectedGlob, [glob])` đúng với bất kỳ mục nào trong
  `PROTECTED_GLOBS` — tức là glob xin cấp **khớp được** một đường dẫn được bảo
  vệ.
- **B2.2** Câu lỗi phải nói **glob nào** bao trùm **file bảo vệ nào**, không
  chỉ liệt kê glob. Người bị từ chối cần biết phải thu hẹp thế nào.
- **B2.3** Không đổi `PROTECTED_GLOBS` (`src/worker.js:68-77`) và bản sao phía
  runner (`runner/orchestrator_runner.py:140-149`). Hai danh sách này đang khớp nhau
  và đó là tài sản, đừng làm trôi.
- **B2.4** `OWNER_DEFAULT_SCOPE` (`src/worker.js:81-82`, `allow_globs: ["**"]`)
  **giữ nguyên** — đó là mặc định ngầm cho Owner, không phải quyền được cấp
  qua `saveCodeScope`, và các lớp sau vẫn chặn. Đổi nó là đổi hành vi mặc
  định của cả hệ, ngoài phạm vi đợt này.

### B3. Nhánh `agent/<id>` mồ côi phải được dọn

**Bằng chứng.** `cleanup_branch` (`runner/orchestrator_runner.py:1139-1150`) được gọi
ở sáu chỗ (`:1171`, `:1183`, `:1200`, `:1218`, `:1237`, `:1266`). **Bốn đường
không gọi:**

1. **Merge hỏng lúc apply** (`:1256-1260`): `merge --abort`,
   `checkout BASE_BRANCH`, `report failed` — không `branch -D`.
2. **Huỷ/từ chối muộn** sau khi đã báo `awaiting_approval` (`:1223-1235`):
   Worker cho huỷ ở `awaiting_approval` (`src/worker.js:1580`) và đặt `rejected`
   (`:1596`), nhưng vòng lặp chính của runner (`:1303-1316`) chỉ hỏi
   `/api/runner/code/approved` và `/api/runner/code/claim` — **không bao giờ
   biết** về `cancelled`/`rejected`.
3. **Huỷ trong lúc planning** sau lần kiểm tra `is_cancelled` duy nhất
   (`:1207`): báo `awaiting_approval` khi ấy rơi vào
   `src/worker.js:1738-1739` `return json({ ok: true, idempotent: true, ... })` —
   **không có cờ `blocked`**, nên `:1237` không kích hoạt, và `checkout
   BASE_BRANCH` ở `:1222` đã chạy rồi, nhánh ở lại.
4. **Yêu cầu bị watchdog đóng** (`src/worker.js:1082-1087`): chỉ xảy ra phía
   Worker, runner không được báo.

Hậu quả đã được ghi ngay trong code (`runner/orchestrator_runner.py:1261-1265`): một
yêu cầu sau trùng 12 ký tự đầu của id sẽ `checkout -B` **đè lên** nhánh cũ,
im lặng.

**Yêu cầu.**

- **B3.1** Bọc toàn bộ vòng đời một yêu cầu trong `try/finally`, `finally` gọi
  `cleanup_branch` trừ đúng một ca: đã merge thành công.
- **B3.2** Vòng lặp chính phải biết yêu cầu đã `cancelled`/`rejected`. Hợp
  đồng mà test ghim: `POST /api/runner/code/finished` với
  `{ runner_key, ids: [...] }` trả `{ finished: [{ id, status }] }`, liệt kê
  những id **đã ở trạng thái cuối** trong danh sách runner gửi lên —
  `cancelled`, `rejected`, `failed`, `applied`, `answered`, `bot_done`. Runner
  giữ danh sách nhánh nó đang cầm, hỏi mỗi vòng poll, và `branch -D` những
  nhánh có tên trong câu trả lời. Chọn POST (không phải GET) vì danh sách id
  có thể dài, và để cùng dáng với `/api/runner/code/claim`.
- **B3.3** Khởi động runner phải quét `git branch --list 'agent/*'` và xoá
  nhánh nào không ứng với yêu cầu đang sống. Đây là lưới cuối, bắt được cả ca
  runner bị kill giữa chừng.
- **B3.4** `checkout -B` **không được** đè im lặng: nếu nhánh đã tồn tại thì
  ghi log cảnh báo kèm id yêu cầu cũ trước khi đè.
- **B3.5** Không đổi cách đặt tên nhánh (`f"agent/{request_id[:12]}"`,
  `:1161`) — đổi là làm hỏng mọi nhánh đang có trên máy trung tâm.

**Ghi chú cài đặt — rò số 1 đóng bằng đường khác lời PRD, và cố ý.** Bản cài
đặt **không** gọi `branch -D` trong `except` của `apply_approved`. Merge hỏng
thì nhánh vào sổ `HELD_BRANCHES`, Center xác nhận trạng thái cuối qua
`/api/runner/code/finished` rồi `drop_finished_branches` mới xoá ở vòng poll
kế tiếp. Đổi vì hai lý do đo được:

1. Xoá trong `except` là xoá **trước khi** Center kịp ghi nhận yêu cầu đã
   hỏng. Center chết đúng khoảnh khắc ấy thì nhánh mất mà yêu cầu vẫn treo
   `applying` — không ai dựng lại được.
2. Đường qua sổ đi chung một cửa với ba đường kết thúc kia (B3.2) và được
   `sweep_stale_branches` (B3.3) vớt lại sau một lần `kill -9`. Đường trong
   `except` thì không.

Yêu cầu B3.1 giữ nguyên — `finally` của `handle_request` vẫn là lưới bắt ca
runner ném giữa chừng. Chỗ khác lời chỉ là ca merge hỏng.

### B4. Trần số lệnh bot phải là hằng số dùng chung

**Bằng chứng.** Số `5` được chép ở hai nơi, không nơi nào đặt tên:

- `runner/orchestrator_runner.py:1188`
  `report(request_id, "bot_action", ..., bot_commands=commands[:5])`
- `src/worker.js:1774`
  `const commands = Array.isArray(body.bot_commands) ? body.bot_commands.slice(0, 5) : [];`

Hai bên cắt độc lập. Nới một bên mà quên bên kia thì lệnh bị **cắt lặng** —
không lỗi, không log, người dùng thấy bot làm thiếu việc. Đây đúng loại trôi
mà `agent_busy_parity.test.mjs` được viết ra để bắt.

**Yêu cầu.**

- **B4.1** Đặt tên hằng số ở cả hai phía (`MAX_BOT_COMMANDS_PER_TURN`) và
  **export** phía Worker để test đọc được — `src/worker.js:2634-2651` đã là chỗ
  export sẵn.
- **B4.2** Worker phải **từ chối** payload có nhiều hơn trần, kèm câu lỗi rõ,
  thay vì `slice` im lặng. Runner cắt trước ở `:1188` nên đường bình thường
  không chạm; ca chạm là runner cũ nói chuyện với Worker mới, đúng lúc cần lỗi
  ồn ào.
- **B4.3** Không đổi giá trị `5`, không đổi `BOT_ACTIONS` (`src/worker.js:22`,
  `["run", "pause"]`), không cho lệnh phụ thuộc nhau — chuỗi phụ thuộc là
  §10.2 của PRD cũ, vẫn ngoài phạm vi.

### B5. Hạn mức yêu cầu sửa code theo ngày

**Bằng chứng.** `prd-agent-dieu-phoi.md` §10.7 ghi thiếu đo đếm chi phí; đọc
code thì đúng là **không có gì cả**. Tìm `usage|tokens|prompt_tokens|cost|quota|budget`
trong `src/worker.js`, `runner/orchestrator_runner.py`, `public/app.js` và `migrations/*.sql`:
**không một kết quả nào** liên quan tới token. `call_chatgpt`
(`runner/orchestrator_runner.py:564-587`) gửi payload không có `max_tokens` và
**không bao giờ đọc `body["usage"]`**; `call_claude`/`call_codex` là subprocess
(`:867`, `:914`), càng không đếm gì.

Cái **đang có** là trần cấu trúc, không phải trần chi phí:
`MAX_ROUNDS = 4`, `MAX_CONTEXT_FILES = 400`, `MAX_READ_BYTES = 120_000`,
`MAX_WRITE_BYTES = 400_000` (`:151-154`), một yêu cầu hoạt động mỗi thread
(`src/worker.js:1528-1529`).

Trần theo ngày **đã có sẵn cho lệnh điều khiển bot** và làm rất gọn:
`max_commands_per_day` mặc định 40 (`src/worker.js:49`), kẹp 1..200
(`:1286`/`:1316`), `deny("daily_limit", ...)` (`:1371-1372`),
`countControlCommandsToday` đếm theo ngày Việt Nam (`:1912-1919`). **Yêu cầu
sửa code — thứ thật sự tốn tiền model — thì không có trần nào.**

**Yêu cầu.**

- **B5.1** Thêm trần ngày cho yêu cầu sửa code, **theo đúng khuôn** đã có cho
  lệnh bot: cột cấu hình, kẹp giá trị, `deny("daily_limit", ...)`, đếm theo
  mốc ngày Việt Nam (`vietnamDayStartIso`, đã export ở `:2650`).
- **B5.2** Ghi lại `usage` model khi provider có trả: `call_chatgpt` đọc
  `body.get("usage")` và gửi kèm trong `report(...)`; Worker lưu vào
  `code_change_requests`. Provider CLI không trả thì để trống — **không đoán**.
- **B5.3** Trần đếm theo **yêu cầu**, không theo token: token chỉ để xem lại,
  vì hai trong ba provider không báo token nên trần theo token sẽ lệch tuỳ
  provider.
- **B5.4** Cần **migration mới** cho cột đếm/usage. `automation_center/migrations/**`
  nằm trong `PROTECTED_GLOBS` (`src/worker.js:75`), nên bước này phải do người có
  quyền Owner làm tay, không giao cho agent điều phối tự sửa.

## 5. Phần C — Bảo mật (từ review vừa xong)

### C1. Chặn hẳn connector Telegram ở API settings

**Bằng chứng.** `execution-notes.md` khẳng định: *"Telegram delivery, polling,
and sync API routes have been removed from the active workflow."* Đúng ở
**đường chạy**: `_automation_graph_payload` bỏ module `telegram`
(`service.py:8246-8249`), và runner có thêm một lớp phòng thủ nữa
(`service.py:8322-8332`, `output={"reason": "dashboard_review_replaces_telegram"}`).
`_send_telegram_review_pack` (`service.py:17345`),
`run_telegram_approval_sync_loop` (`17566`) và `sync_telegram_approvals`
(`17578`) **không còn ai gọi** — `grep` toàn repo chỉ thấy định nghĩa.

Nhưng **đường vào thông tin xác thực thì vẫn mở**. `service.py:738-767`:

```python
telegram_bot_token = request.telegram_bot_token.strip()
if not request.clear_telegram_bot_token:
    telegram_bot_token = telegram_bot_token or current.telegram_bot_token
...
    telegram_chat_id=request.telegram_chat_id.strip(),
```

`PUT /api/integrations/settings` vẫn nhận, vẫn lưu vào `data/state.json`, và
`_integration_config_snapshot` (`service.py:783-813`) vẫn **trả ngược ra** cho
trình duyệt `telegram.configured`, `bot_token_saved`, `chat_id`, còn
`_telegram_credentials` (`service.py:17459-17467`) vẫn đọc được cả từ state
lẫn từ `TELEGRAM_BOT_TOKEN` trong env.

Một connector đã gỡ mà vẫn giữ một kho thông tin xác thực sống, cách đường
gửi đúng **một lời gọi hàm**, là một bề mặt không có lý do tồn tại.

**Yêu cầu.**

- **C1.1** `IntegrationConfigUpdateRequest` (`schemas.py:357-368`) bỏ hẳn
  `telegram_bot_token` và `clear_telegram_bot_token`.
- **C1.2** `update_integration_config` không được ghi `telegram_bot_token` hay
  `telegram_chat_id` nữa; giá trị cũ trong state phải bị **xoá trắng** ở lần
  lưu kế tiếp, không phải mang theo.
- **C1.3** Payload nào còn gửi kèm trường Telegram thì trả **400** kèm câu nói
  rõ bệnh, không im lặng bỏ qua — im lặng làm người gọi tưởng đã lưu.
- **C1.4** `_integration_config_snapshot` không trả khối `telegram` nữa.
- **C1.5** Xoá `_send_telegram_review_pack`, `_send_telegram_photo`,
  `_telegram_photo_source`, `_telegram_review_caption`,
  `_telegram_approval_reply_markup`, `run_telegram_approval_sync_loop`,
  `sync_telegram_approvals`, `_sync_telegram_approvals_unlocked`,
  `_parse_telegram_approval_callback`, `_telegram_credentials`,
  `TELEGRAM_API_URL_TEMPLATE` — mã chết không được ở lại cạnh một kho khoá.
- **C1.6** `CreateJobRequest.telegram_enabled` / `telegram_chat_id`
  (`schemas.py:407-408`) bỏ nốt. **Lưu ý:** `telegram_enabled` đang mặc định
  `True`, nên hôm nay đường duy nhất chặn nó là việc không ai gọi hàm gửi.
- **C1.7** Không đụng `automation_center/runner/*` — Telegram ở đó là chuyện
  khác, ngoài phạm vi đợt này.

### C2. Nút "Xoá Gemini key" phải nói thật

**Bằng chứng.** `flow_web/static/app.js:6196`:

```js
elements.automationEnvClearButton?.addEventListener("click", () => saveIntegrationConfig({ clearSecrets: true }));
```

`saveIntegrationConfig` (`flow_web/static/app.js:4580-4615`) gửi `clear_gemini_api_key: true`
và báo *"Đã xóa Gemini key trong app. Các field không nhạy cảm vẫn giữ lại."*

Nhưng `_integration_config_snapshot` (`service.py:774-782`) **dựng khoá lại từ
env** ngay sau đó:

```python
if not gemini_api_key:
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        env_value = os.getenv(env_name, "").strip()
        if env_value:
            gemini_api_key = env_value
            break
```

Nên trên máy có `.env.local` — tức là **máy thật** — bấm nút xong: state trống,
khoá vẫn sống, app vẫn gọi Gemini được, và giao diện vẫn báo đã cấu hình
(`credentials_source: "env"`). Người bấm tin rằng khoá đã đi; nó không đi đâu cả.

Không có `window.confirm` nào trên đường này (`flow_web/static/app.js` chỉ có `confirm` ở
`5555` và `5632`, cả hai cho việc khác).

**Yêu cầu.**

- **C2.1** Sau một lần xoá tường minh, snapshot **không được** rơi về env cho
  lần đọc đó: `configured` phải là `false`, `credentials_source` phải rỗng.
  Cách làm đề xuất: ghi một cờ `gemini_api_key_cleared_at` trong
  `IntegrationConfig` và cho phần fallback env bỏ qua khi cờ ấy mới hơn lần
  lưu env gần nhất.
- **C2.2** Nếu vẫn còn khoá trong env, câu thông báo phải nói đúng bệnh:
  *"Đã xoá khoá trong app. Nhưng máy này còn `GEMINI_API_KEY` trong .env.local
  nên app vẫn gọi được Gemini — xoá nốt trong file nếu muốn dừng hẳn."*
  Không được để nguyên câu "Đã xóa Gemini key trong app."
- **C2.3** Nút xoá phải hỏi lại bằng `window.confirm` trước khi gửi.
- **C2.4** API vẫn không bao giờ trả giá trị khoá ra trình duyệt — giữ nguyên
  hành vi che hiện có, đây không phải chỗ nới.

### C3. Bot ERP chỉ được nghe người trong danh sách

**Bằng chứng.** `flow_web/agent_chat.py:367-392` — `addressed_to_bot` chỉ loại
hai nhóm: bình luận của chính bot (`mine`) và của bot khác (`is_bot`).
**Không có kiểm tra tác giả nào khác.** Ai bình luận được lên thẻ trong
`PROJ-0013` là ra lệnh được cho bot.

Ra lệnh được những gì — `agent_bot.py:1662-1694` (`_apply_chat_action`):

| Lệnh | Hậu quả |
|---|---|
| `ACTION_RUN` | `clear_cooldown` — ép chạy lại automation trên thẻ |
| `ACTION_PAUSE` / `ACTION_RESUME` | dừng / chạy tiếp automation trên thẻ |
| `ACTION_SET` | **ghi thuộc tính lên thẻ ERP** qua `edit_hook` |
| `ACTION_SKU_FILL` / `ACTION_SKU_RENUMBER` | đánh số lại SKU **toàn bộ cây thẻ gốc** |

Cộng thêm `_guess_harder` (`agent_bot.py:1745-1787`): câu nào bảng từ khoá
không hiểu thì **chạy một CLI model trên máy trung tâm**, với nội dung do
người bình luận viết (§A8).

Đối chiếu: phía Agent điều phối có ba lớp giới hạn độc lập
(`prd-agent-dieu-phoi.md` §6) và một luận điểm dứt khoát — *"Ranh giới nằm ở
bảng allowlist… không nằm ở lời nhắc gửi cho ChatGPT."* Bot ERP làm đúng nửa
sau (`_clean_edits`, `agent_brain.py:248-270`, chốt danh sách ô được sửa) và
**bỏ trắng nửa đầu**: không có lớp "ai được nói".

**Yêu cầu.**

- **C3.1** Thêm danh sách tác giả được phép, đọc từ env
  `FLOW_AGENT_BOT_ALLOWED_AUTHORS` (email, phân tách bằng dấu phẩy, không phân
  biệt hoa thường) — cùng lối `AGENT_CHAT_ALLOWED_EMAILS` đã dùng ở
  Automation Center (commit `a99af3b`).
- **C3.2** **Đóng mặc định là sai ở đây.** Danh sách trống nghĩa là *không
  khoá* (giữ nguyên hành vi hôm nay), vì khoá đột ngột sẽ làm bot câm trên
  bảng đang chạy. Nhưng bot phải **ghi log cảnh báo một lần mỗi vòng quét**
  khi đang chạy không khoá, để không ai quên.
- **C3.3** Khi có danh sách: bình luận của người ngoài danh sách → bot **không
  trả lời, không hành động**, chỉ ghi log (tác giả + thẻ). Không trả lời một
  câu từ chối — đó là một đường để người lạ dò xem bot có ở đó không.
- **C3.4** Hàm quyết định phải **thuần tuý và test được ngoài bot**:
  `agent_chat.author_is_allowed(comment, allowed) -> bool`, đọc email từ mọi
  hình dạng ERP trả về (`owner`, `by_email`, `email`, `user`) — cùng cách
  `_mentioned` (`agent_chat.py:303-321`) đã chấp nhận nhiều hình dạng.
- **C3.5** Bình luận **thiếu** thông tin tác giả, khi danh sách đang bật, phải
  bị **từ chối** (fail closed), không phải được cho qua.

### C4. Nút "reset custom" phải hỏi lại

**Bằng chứng.** `flow_web/static/app.js:4253-4258`:

```js
function resetAutomationConfig() {
  state.automation = defaultAutomationConfig();
  saveAutomationConfig(state.automation);
  renderAll();
  showMessage("Đã reset phần custom về mặc định.", "success");
}
```

Gắn thẳng vào nút ở `flow_web/static/app.js:6062`, **không** `confirm`, **không** hoàn tác.
Một cú bấm nhầm xoá sạch graph automation người dùng đã dựng. Cạnh nó có
`importAutomationConfig` (`flow_web/static/app.js:4240-4251`) nên có đường phục hồi *nếu* ai
đó đã export trước — mà không ai export trước một cú bấm nhầm.

**Yêu cầu.**

- **C4.1** `window.confirm` trước khi reset, câu hỏi nói rõ mất gì và có đường
  nào lấy lại (Export).
- **C4.2** Giữ **một** bản chụp cấu hình ngay trước khi reset
  (`localStorage`, khoá riêng), và hiện nút "Hoàn tác" trong thông báo thành
  công cho tới lần render kế tiếp.
- **C4.3** Không đổi `defaultAutomationConfig()`.

---

## 6. Thứ tự làm đề xuất

Chia làm bốn đợt. Mỗi đợt là một pull request riêng, tách từ `main`.

**Đợt 1 — bịt đường ra (nửa ngày).** C1, C2, C4, A8.
Toàn bộ là gỡ bớt bề mặt, không đụng đường chạy nào đang hoạt động. Làm trước
vì rẻ nhất và rủi ro cao nhất.

**Đợt 2 — watchdog và phạm vi (một ngày).** B1, B2.
B1 nên làm **B1.3 trước** (runner báo `planning` mỗi vòng): rẻ hơn nhiều và
làm cho việc chọn ngưỡng ở B1.1 bớt quan trọng.

**Đợt 3 — tốc độ và độ chính xác Flow (một tới hai ngày).** A1, A2, A4, A5.
A1 và A2 phải đo **cùng nhau**: `execution-notes.md` cho thấy 30s tiết kiệm ở
A1 bị A2 nuốt trọn, nên sửa một cái rồi đo thì không kết luận được gì.

**Đợt 4 — hàng rào và trần (một tới hai ngày).** C3, A9, A6, A7, B3, B4, B5.
C3 phải đi kèm việc hỏi chủ bảng xem ai được vào danh sách — đây là mục duy
nhất cần một quyết định của con người trước khi bật.

**A3 không nằm trong đợt nào**: nó chờ một phép đo tay (bắt request lúc người
thật bấm 2K). Phần code của A3 (tách hàm, thêm env) có thể làm ở đợt 3 vì nó
không đổi hành vi.

---

## 7. Danh sách test đi kèm

Toàn bộ test dưới đây **được phép đỏ** cho tới khi mục tương ứng được cài.
Đây là TDD: test tả hành vi mong muốn, không tả hành vi hôm nay.

### `tests/test_agent_improvements.py` (Python, `unittest`)

| Lớp test | Mục | Đỏ vì |
|---|---|---|
| `AgentModeDeadWaitTests` | A1 | mặc định còn 45.0; kẹp dưới còn 5.0 |
| `ApprovalDialogWaitTests` | A2 | vòng poll chạy hết `deadline` |
| `RecaptchaActionTests` | A3 | `_recaptcha_token_script` chưa tồn tại |
| `UiFallbackBeforeManualFlagTests` | A4 | lượt gắn cờ `return jpeg_bytes` sớm |
| `UiDownloadLogsSuccessTests` | A5 | nhánh thành công không ghi gì |
| `PublishScopedToIndicesTests` | A6 | `publish_erp_review` chưa nhận `indices` |
| `HistoryKeepsRealRunsTests` | A7 | `trim_job_history` chưa có hạn ngạch |
| `BrainSubprocessEnvTests` | A8 | chỉ lọc tiền tố `ERP_` |
| `BrainCallBudgetTests` | A9 | bộ đếm reset mỗi vòng quét |
| `TelegramConnectorRemovedTests` | C1 | API còn nhận và lưu token |
| `ClearGeminiKeyTellsTheTruthTests` | C2 | env fallback dựng khoá lại |
| `BotObeysOnlyAllowedAuthorsTests` | C3 | `author_is_allowed` chưa tồn tại |
| `ResetAutomationNeedsConfirmationTests` | C4 | không có `confirm` trên đường reset |

Chạy: `python3 -m unittest tests.test_agent_improvements -v`

### `automation_center/tests/*.test.mjs` (Node, `node:test`)

| File | Mục | Đỏ vì |
|---|---|---|
| `watchdog_budget.test.mjs` | B1 | 45 phút < ngân sách 135 phút |
| `code_scope_covering_glob.test.mjs` | B2 | `saveCodeScope` so khớp `===` |
| `orphan_branch_cleanup.test.mjs` | B3 | bốn đường không gọi `cleanup_branch` |
| `bot_command_limit_parity.test.mjs` | B4 | `5` là số viết tay, chưa export |
| `code_request_quota.test.mjs` | B5 | không có trần ngày cho yêu cầu sửa code |

Chạy: `/Users/admin/.local/node/bin/node --test --experimental-sqlite automation_center/tests/*.test.mjs`

---

## 8. Rủi ro của chính đợt cải tiến này

| Rủi ro | Mức | Cách giảm |
|---|---|---|
| Hạ khoảng chờ (A1) làm rớt ảnh trên mạng chậm | Vừa | Giữ env để nới lại; A1.3 đua hai đường nên khoảng chờ ngắn không còn là điểm chết |
| Bật danh sách tác giả (C3) làm bot câm trên bảng đang chạy | **Cao** | C3.2 mặc định **không** khoá khi danh sách trống; bật có chủ đích |
| Nới ngưỡng watchdog (B1) làm yêu cầu chết thật nằm lâu hơn | Vừa | B1.3 báo `planning` mỗi vòng ⇒ yêu cầu chết thật vẫn bị bắt trong một vòng |
| Chặn glob bao trùm (B2) làm hỏng phạm vi đã cấp | Vừa | Chỉ áp cho lần **cấp mới**; phạm vi đang lưu không bị thu hồi tự động |
| Bỏ mã Telegram (C1.5) đụng đường còn ai đó gọi | Thấp | `grep` xác nhận không còn caller; test C1 ghim điều đó |
| Sửa `publish_erp_review` (A6) đụng đường đăng đang chạy | Vừa | `indices=None` giữ nguyên hành vi cũ, đường cũ không đổi |

---

## 9. Câu hỏi cần người quyết

1. **C3** — ai vào `FLOW_AGENT_BOT_ALLOWED_AUTHORS`? Cần chủ bảng ERP trả lời.
   Không có câu trả lời thì để trống (không khoá) và giữ log cảnh báo.
2. **A4** — cờ `needs_manual_review` hiện tắt cả đường UI download. PRD đề nghị
   đảo lại (thử UI trước, gắn cờ sau). Nếu việc tắt ấy là **cố ý** vì một lý do
   chưa ghi ở đâu, cần biết lý do trước khi sửa.
3. **B1** — chọn B1.1 (nới ngưỡng lên ~175 phút) hay B1.3 (runner báo mỗi vòng)
   hay cả hai? Đề xuất: cả hai, B1.3 trước.
4. **B5.4** — migration nằm trong `PROTECTED_GLOBS`. Ai chạy migration đó?

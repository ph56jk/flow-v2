# Soát đợt A — `agent/prd-agent-improvements-tdd`

# ĐI ĐƯỢC

Đo lần cuối ở worktree sạch tại **`bc87b25`** — cả năm bộ. Một điều kiện, và nó không
phải một chỗ cần sửa: **còn đúng 1 bài node đỏ — B3.1**, và nó là TEST SAI đang chờ người trả lời một câu hỏi hợp đồng (xem
phán quyết ở cuối). Pull request mở được, nhưng phần mô tả không được nói
"test xanh" mà không kể bài ấy.

Bản này đo lại ở `7f86a38` và **thay thế** bản đã commit trong `e337966`
(bản ấy kết luận CHẶN, và chặn đó đã đóng — xem mục dưới). Lịch sử đo:

| Đo tại | Bộ 1 | Việc gì đã xảy ra |
|---|---|---|
| `99de6a4` | 16 bài đỏ | CHẶN: `schemas.py` thiếu field mà code đã đọc |
| `b8b7068` | 1272 xanh | chặn đóng |
| `e337966` | 1275 xanh | 4 mục "nên sửa" được đóng |
| `7f86a38` | **1290 xanh** | chốt mạng vào, +15 bài |
| `fba4c47` | 1290 xanh (không đo lại) | node 33 → 6 → **4** đỏ; một bài node được sửa, đã phán quyết bên dưới |
| `127f10e` | 1290 xanh (không đo lại) | node vẫn **4** đỏ — commit B3.1 không làm bài B3.1 xanh, xem Tồn đọng |
| `777df54` | **1296 xanh** | chốt mạng chặt thêm (+6 bài); node **189/188/1**, chỉ còn B3.1 |
| `3c9fd10` | 1296 xanh | node **189/188/1** (tự đo); bộ 4 **35/35**; bộ 5 lộ ra là chạy rỗng — xem dưới |
| `e889e4b` | 1296 xanh | node **190/189/1** (tự đo) — `fb421ca` thêm 1 bài và siết `PROTECTED_GLOBS`, soát ở dưới |
| `5eb5e04` | **1297 xanh** | node **191/190/1** (tự đo); `PROTECTED_GLOBS` 23 → 29 mẫu |
| `e435a80` | **1301 xanh** | node **191/190/1** (tự đo); `.gitignore` khoá nốt chiều commit — nhưng một bài mới **không cắn được**, xem dưới |
| `7a08fc1` | **1301 xanh** | node **191/190/1** (tự đo, cả năm bộ); bài xanh giả ấy được vá bằng `--no-index` — đã đo là cắn thật |
| `984c9ac` | **1301 xanh** | node **199/198/1** (tự đo); +8 bài khoá "runner chỉ chạm việc của chính nó", mục 9 đóng |
| `bc87b25` | **1306 xanh** | node **199/198/1** (tự đo); mục 5 (đua A1.3 thành bài hành vi), 15, 16, 17 đóng — 19 đột biến tự dựng, 19 lần chết đúng chỗ |

`f032097` landing sau lượt đo cuối và **chỉ** chạm
`.claude/agents/test-reviewer.md` (thêm ràng buộc cứng cho vai soát: không mở
file bí mật, không dán giá trị vào báo cáo, không sửa file cài đặt hay file
test). Không code, không test — nên số đo tại `7f86a38` vẫn còn giá trị. Lượt
soát này làm đúng cả bốn ràng buộc ấy.

Phạm vi giao ban đầu: `git diff e6dd796..HEAD -- flow_web tests CLAUDE.md docs
.claude`. Mọi con số dưới đây đo ở **worktree sạch tại một commit cố định**
(`git worktree add /tmp/wt-hd 7f86a38 --detach`), không đo ở cây làm việc — cây
làm việc di chuyển bảy lần trong lượt soát này. Nền so sánh là `main`
(`976fc70`).

## Số test — đo tại `bc87b25`, cả năm bộ, worktree sạch

| Bộ | Số bài | Xanh | Đỏ | Loại của phần đỏ |
|---|---|---|---|---|
| 1. `tests/` | 1306 | 1306 | **0** | `Ran 1306 tests in 138.265s … OK`; `grep -c OutboundNetworkBlocked` = **0** |
| 2. `automation_center` python | 85 | 85 | **0** | — |
| 3. `automation_center` node | 199 | 198 | **1** | `not ok 80 - phía runner` — 1 TEST SAI (B3.1), chờ người chốt hợp đồng |
| 4. `_bmad/core/bmad-init` | 35 | 35 | **0** | — |
| 5. `_bmad/core/bmad-distillator` | **0 thu được** | — | — | MÔI TRƯỜNG: `No module named pytest`, mã thoát 1. `pyproject.toml:23-26` cho thấy `pytest>=8.0.0` nằm trong extras `dev`, nên đúng lệnh là `.venv/bin/python -m pip install -e '.[dev]'` — lệnh này kéo cả `flow-py` từ GitHub nên cần mạng; máy không có mạng thì `pip install pytest` là đủ cho riêng bộ 5 |

**Không có bài nào loại LỖI CODE.** Bốn bộ chạy được: 1625 bài, 1624 xanh, 1 đỏ.
Bộ 5 vẫn chưa chạy được bài nào trên máy này — con số của nó là 0, không phải xanh.

Cả bộ 1 lẫn bộ 3 đo tại HEAD `777df54`, worktree sạch `/tmp/wt-head`:
`Ran 1296 tests in 137.577s … OK`, `# tests 189 / # pass 188 / # fail 1`, và
`grep -c OutboundNetworkBlocked` = **0** — không bài nào lén gọi ra ngoài.

Nền `main`: bộ 1 là 1220/1220 xanh, bộ 2 là 85/85 xanh, bộ 3 là 143/143 xanh.
Không bài nào đang xanh trên `main` chuyển thành đỏ. Bài đỏ còn lại nằm
trong 2 file test do `e6dd796` thêm; 143 bài node của `main` không bị chạm, và
`git diff e6dd796..7f86a38 -- automation_center/tests` **rỗng** — không dòng
test node nào bị xoá hay sửa để cho xanh.

Bộ 3 đi từ 33 đỏ (`b8b7068`) xuống 6 đỏ (`7f86a38`) mà tổng vẫn là 189: B1, B2,
B5 đã cài xong, không bài nào bị bỏ.

Bảng dưới là ảnh chụp tại `7f86a38`; ba bài B4 trong đó **đã đóng** ở
`777df54`+`2906917`, nên tại `7a08fc1` chỉ còn đúng một dòng đầu còn đỏ.

| File node | Đỏ tại `7f86a38` | Mục | Bài còn đỏ |
|---|---|---|---|
| `orphan_branch_cleanup.test.mjs` | 1 | B3.1 | `apply_approved dọn nhánh cả khi merge hỏng` — **TEST SAI**, xem dưới; **vẫn đỏ tại `7a08fc1`** |
| `bot_command_limit_parity.test.mjs` | 3 | B4 | `Worker xuất MAX_BOT_COMMANDS_PER_TURN` · `runner cắt theo đúng con số đó` · `giá trị vẫn là 5` — **đã xanh từ `2906917`** |
| `watchdog_budget.test.mjs` | 0 | B1 | — (8/8) |
| `code_scope_covering_glob.test.mjs` | 0 | B2 | — (9/9) |
| `code_request_quota.test.mjs` | 0 | B5 | — (11/11) |

## Delta `b8b7068..e337966` — bốn mục "nên sửa" đã đóng **thật**

Câu hỏi được đặt là "đóng thật hay chỉ trông như đóng". Kiểm từng mục, không
đọc commit message thay cho code.

### #1 lỗi của project poll bị nuốt im — **đóng, còn một mép**

`service.py:25247-25260`: nhánh `elif` mới ghi câu lỗi thật vào log lượt chạy
(`"đường project poll hỏng giữa cuộc đua (…); còn lại một mình interceptor."`).
Trước đây nhánh này `continue` trơn.

Mép còn lại, tự kiểm được: câu log nằm sau `elif job_id:`. Gọi hàm với
`job_id=""` và cho project poll nổ → lỗi vẫn mất hẳn, không có `log.warning`
đỡ. Ba chỗ gọi (`service.py:24338, 24414, 24502`) đều truyền `job_id` từ ngoài
xuống nên lượt chạy thật luôn có id; đây là mép, không phải lỗ.

Bài canh nó — `test_a_broken_project_poll_does_not_read_as_a_plain_timeout` —
lại là bài đọc source (`inspect.getsource` + `assertIn`), tức là nó khoá **câu
chữ** trong log chứ không khoá việc `append_log` có được gọi. Đổi lời câu log
là đỏ; chuyển câu log ra ngoài `if job_id` vẫn xanh. Xem #5.

### #2 lượt hỏng chậm hơn trước — **đóng, và phép trừ đúng**

Đây là mục được hỏi kỹ nhất. Ba câu hỏi, ba câu trả lời:

**Có gọi bằng thời gian đã trôi thật không?** Có. `project_poll_budget_s` tính
một lần ở `service.py:25202`, cạnh `wait_started_at` (`:25193`). Trong nhánh
`except`, dòng **đầu tiên** là `waited_s = loop.time() - wait_started_at`
(`:25300`) — một phép đo, không phải hằng số, không phải `0.0` cũ. Lời gọi ở
`:25338` dùng đúng biến ấy. Cuộc đua ở `:25221` nay tiêu chung
`project_poll_budget_s`, không còn tự viết lại `min(120, max(20, …))`.

**Sàn có làm nó dài hơn ngân sách gốc được không?** Không.
`max(floor, budget - max(0, waited))` chỉ vượt `budget` khi `floor > budget`, mà
`budget = min(120, max(20, ui_timeout_s/2)) >= 20` **luôn**, còn `floor = 10.0`.
Quét `ui_timeout_s` từ 0 tới 1000 với `waited` ở 12 giá trị biên (kể cả
`waited` âm — đồng hồ nhảy ngược, đã bị `max(0.0, …)` chặn): không lần nào
`remaining > budget`; tổng hai lần chờ tối đa là 130s khi `budget` là 120s.

**Cái doubling có chỗ nào khác không?** Không, trên đường hỏng. Sáu chỗ gọi
`_wait_for_new_project_images`: `:21187` là hàm khác; `:25216` là cuộc đua;
`:25333` là lần thứ hai đã trừ; `:25386` và `:25402` chỉ tới được khi
interceptor **đã** trả kết quả — tức là đường thành công, không phải đường
"không có ảnh nào".

Còn một khoản chưa được tính, nói cho đủ: `waited_s` chốt ở `:25300`, còn lời
gọi ở `:25338`, và giữa hai chỗ có `_raise_flow_agent_quota_if_visible`,
`_raise_flow_agent_try_again_if_visible` và `_approve_flow_agent_generation(
timeout_s=8.0)`. Phần thời gian ấy không bị trừ. Ước lượng: tổng xấu nhất nay
~140s, so với ~240s của bản `99de6a4` và ~165s của bản trước A1. Là chênh vài
giây, không phải nhân đôi — lời hứa "tiết kiệm 30s một card" nay đúng ở cả hai
chiều.

Bài canh nó — `test_the_race_does_not_make_a_failing_run_slower_than_before` —
là bài **hành vi thật**: nó gọi hàm thuần `remaining_project_poll_budget` và
canh bất đẳng thức `min(waited, budget) + remaining <= budget + floor`, tức là
canh đúng điều bản cũ vi phạm (120 + 120 = 240). Không đọc source.

### #3 body hỏng thành "đăng tất cả" — **đóng**

`main.py:317-345`: đọc `await request.body()`; rỗng (kể cả toàn khoảng trắng)
→ `None` = giữ nguyên nghĩa "đăng bù tất cả"; có mà `json.loads` nổ → **400**;
đọc ra mà không phải object → **400**. Ba nhánh, ba nghĩa khác nhau.

Nguy cơ hồi quy: không. Đã đếm người gọi endpoint
`/api/jobs/{id}/erp-review/publish` trong cả repo — **không có** chỗ nào trong
`flow_web/static/*.js` hay code khác gọi nó; hai chỗ nhắc tới nó là `README.md`
và `execution-notes.md`, cả hai đang cảnh báo *đừng* dùng nó để vá. Endpoint
này chỉ được gọi bằng tay, nên siết chặt không làm hỏng đường nào đang chạy.

Thêm một cái tốt không được nêu trong commit: `await request.body()` nổ khi
client đứt giữa đường thì nay lỗi ấy nổi lên thành 500, chứ không còn bị nuốt
thành "đăng tất cả".

### #4 bộ test A6 chưa khoá được hành vi — **đóng, và đã kiểm bằng đột biến**

Nhắc lại một phân biệt quan trọng cho phần mô tả PR: chỗ này là **test yếu**
có sẵn từ `e6dd796`, **không phải test bị làm yếu đi**. Đợt A không hạ
assertion nào. "Yếu" thì ghi vào việc phải làm; "bị làm yếu" mới là chặn.

`_offline_erp` nay trả các mock ra ngoài, và hai bài đếm số ảnh **thật sự**
được đăng: `call_count == 1` và `result["skipped"] == 2`.

Không tin lời khai, tôi đo bằng đột biến — thay `_erp_review_scope` bằng một
bản luôn trả `None` (đúng hình dạng "bỏ qua `indices`, đăng bù tất cả", tức là
chính sự cố 12 → 17) rồi chạy lại class ấy. Không sửa file nào, chỉ patch lúc
chạy:

```
FAIL: test_it_accepts_a_list_of_indices        AssertionError: 1 != 3
      "xin đăng một chỉ số mà đăng nhiều hơn một ảnh"
FAIL: test_the_result_says_what_it_skipped     AssertionError: 2 != 0
      "ba ảnh xin một thì bỏ qua đúng hai"
```

Bản cũ (`assertIsInstance(result, dict)`) xanh trước đột biến ấy. Nay đỏ. Bài
test đã có răng.

## Mục 6 — chốt mạng: **đóng, không làm bài nào đỏ, không lách được dễ**

`7f86a38` thêm `tests/network_guard.py` + `tests/test_0_network_guard.py`
(15 bài). Ba câu hỏi được đặt:

**Có làm bài xanh nào thành đỏ không?** Không. Bộ 1 ở worktree sạch tại
`7f86a38`: `Ran 1290 tests in 138.071s … OK`. 1275 bài cũ vẫn xanh, +15 bài
mới của chính chốt. Kiểm chéo trước khi chốt landing: chạy toàn bộ 1 tại
`e337966` dưới một chốt socket ngoài (chặn mọi thứ trừ loopback) — cũng không
bài nào đỏ, tức là không có bài nào đang **dựa vào** mạng thật.

**Lách được không?** Đã thử 10 đường, ở worktree sạch:

| Đường | Kết quả |
|---|---|
| `socket.create_connection(("example.com", 80))` | CHẶN |
| `create_connection(("93.184.216.34", 80))` — quay thẳng IP, không DNS | CHẶN |
| `urllib.request.urlopen("http://example.com")` | CHẶN |
| `httpx.get("https://example.com")` | CHẶN |
| `asyncio.open_connection("example.com", 80)` | CHẶN |
| `loop.getaddrinfo` (chạy trong executor thread) | CHẶN |
| `allow_outbound(...)` rồi `loop.getaddrinfo` | CHẶN — cờ là thread-local, không theo sang executor |
| `socket.gethostbyname` | CHẶN |
| `socket.connect_ex` | CHẶN |
| **UDP `sendto(("8.8.8.8", 53))`** — không `connect` | **LỌT** |

Hai khâu (`getaddrinfo`/`gethostbyname` và `connect`/`connect_ex`) là quyết
định đúng: bỏ một trong hai là lọt nửa còn lại, và tôi đã đo được đúng chỗ nửa
kia đỡ hộ (xem "Nên sửa" #b). Không có công tắc env nào tắt được chốt.
`allow_outbound` bắt phải viết lý do và từ chối chuỗi rỗng — nghĩa là lý do
luôn nằm trong diff.

**Chỗ chốt chưa với tới, tự kiểm được.** Chốt bật lúc `test_0_network_guard.py`
được nạp, mà `tests/` không có `__init__.py` nên không có móc nào khác. Đo:

```
python -m unittest tests.test_erp_review   →  socket.getaddrinfo.__name__ == "getaddrinfo"
                                              (chốt KHÔNG bật, 71 bài chạy tự do)
```

Chạy một file lẻ là thao tác hằng ngày, và **đúng là thao tác mà sự cố ERP đã
trốn trong đó**. Không chặn — đường `discover` đầy đủ đã được canh, và fixture
gốc đã sửa — nhưng cần một người nhận. Xem "Nên sửa" #a.

## Một chặn đã có và đã được đóng

Ghi lại để có vết, không phải để đòi thêm việc.

Ở `99de6a4` — commit cuối của phạm vi được giao — `service.py:768,1351` và
`store.py:462` đọc/ghi `IntegrationConfig.gemini_api_key_cleared_at`, mà
`schemas.py` **đã commit** lúc đó không có field ấy. Đo ở worktree sạch:
`AttributeError` 22 lần, **16 bài đang xanh trên `main` chuyển thành đỏ** (15
bài `test_flow_web_smoke`, 1 bài `test_erp_review`), và ba đường chạy thật
cùng trả 500 (`service.py:457` snapshot dashboard, `:773`
`GET /api/integrations/settings`, `:5469` ngữ cảnh trợ lý). Nhánh khi ấy chỉ
trông như chạy được vì `schemas.py` chưa commit của lane C đang đỡ hộ.

`b8b7068` thêm field vào `schemas.py:42`. Kiểm lại ở worktree sạch: 1272/1272
xanh. Chặn đóng.

Bài học cho lần chia việc sau — và `.claude/skills/agent-pipeline/SKILL.md` ở
`e337966` đã ghi thành "Luật 1b", đúng chỗ: một commit đọc field do lane khác
giữ là một commit đỏ cho tới khi lane kia commit, và trong khoảng ấy không ai
biết vì cây làm việc vẫn xanh.

## Bốn bài test bị xoá — **hợp lệ, không phải nới lỏng**

Lý do không phải "vì chúng nói về Telegram" mà là **đối tượng của chúng không
còn tồn tại**: mỗi bài gọi vào một hàm mà `b8b7068` đã gỡ hẳn. Đếm ở
`flow_web/*.py`:

| Bài bị xoá | Gọi vào | Còn không |
|---|---|---|
| `test_telegram_review_pack_uses_app_saved_config` | `_send_telegram_review_pack`, `_send_telegram_photo` | 0 hit |
| `test_sync_telegram_approvals_updates_job_and_approval_node` | `sync_telegram_approvals`, `_telegram_get_updates` | 0 hit |
| `test_telegram_approval_sync_loop_polls_until_cancelled` | `run_telegram_approval_sync_loop` | 0 hit |
| `test_late_telegram_reaction_does_not_flip_completed_approval` | `_apply_telegram_approval` | 0 hit |

Một bài test mà điểm vào đã bị gỡ thì không "giữ lại" được — giữ nó là giữ một
`AttributeError`. Kèm theo, `assertNotIn("telegram", result)` được thêm để ghim
chính việc gỡ. Toàn commit `b8b7068` có 31 assertion bị xoá và **cả 31 đều nằm
trong thân bốn bài trên**; không `skip`, không `expectedFailure`, không con số
nào bị hạ ở bài còn sống.

**Chỗ đáng lo nhất và câu trả lời cho nó.** Bài thứ tư không chỉ nói về
Telegram: nó khoá một luật chung — *một phản hồi muộn không được lật một quyết
định đã xong, và không được gọi lại `_archive_erp_artifacts`*
(`archive.assert_not_called()`). Luật ấy vẫn còn sống trên đường ERP:
`sync_erp_review` vẫn bỏ qua chỉ số đã ở `approved`/`rejected`, và vẫn có bốn
bài riêng đang xanh canh nó — `test_publish_skips_images_that_already_have_a_decision`,
`test_the_archive_never_posts_an_image_to_the_same_card_twice`,
`test_the_same_image_is_never_deleted_twice`,
`test_a_card_a_person_already_closed_is_not_moved`. Không có lỗ hổng nào mở
ra. Nếu đường ERP **không** có những bài đó thì tôi đã báo to chỗ này.

## Bốn chỗ sửa test của đợt A — không chỗ nào nới lỏng

Kiểm từng chỗ, không tin lời khai. Không assertion nào bị xoá hay hạ, không
`skip`. Ba assertion duy nhất bị xoá là ba con số `45.0`/`5.0` ở mục (d), mỗi
cái thay bằng một đẳng thức chặt y như cũ.

**(a) nhãn `media-1` → UUID (A4/A5) — fixture, và nó siết chặt.**
`_normal_flow_media_name` đòi đúng hình UUID; `"media-1"` trả `""` và
`_upsample_image_via_flow` thoát ngay ở chốt đầu hàm. Với nhãn cũ, bốn bài A4
chia hai nửa: hai bài **đỏ** (`tried == []`, `blocked` rỗng) và hai bài xanh
**vờ** (`blocked == []`, `contexts == 0 < 12`). Đổi sang UUID biến hai bài
xanh vờ thành xanh thật và làm hai bài kia đo được. Log lượt chạy in
`media=00000001-… HTTP 403 reCAPTCHA` — đúng đoạn trước đây không bao giờ
chạy.

**(b) `_offline_erp()` (A6) — fixture, và mức nghiêm trọng là thật.**
`_erp_comment` không nằm trên đường đi của `publish_erp_review`; đường đi là
`_erp_assert_task_in_project` → `_erp_task_detail` → `_upsample_artifacts_bytes`
→ `_erp_outgoing_file_bytes` → `_erp_publish_review_comment`. Chạy bản như
giao với socket bị chặn:

```
RuntimeError: OUTBOUND DNS BLOCKED -> erp.havigroup.llc:443
=== OUTBOUND ATTEMPTS ===  DNS erp.havigroup.llc:443
```

`ERP_BASE_URL` viết cứng ở `service.py:258` là ERP **production**. Nói cho
đúng cả hai phía: không lộ bí mật và không ghi được lên thẻ thật, vì fixture
dùng `api_key="test-key"` và `STATE_FILE` bị trỏ vào thư mục tạm nên không đọc
được khoá thật — nó chết ở lần đọc đầu với 401. Nhưng mỗi lượt chạy test là
một loạt request 401 vào ERP doanh nghiệp từ máy lập trình; ERP nào khoá theo
số lần sai thì bộ test tự khoá tài khoản. Và nếu fixture ấy chạy trên máy có
khoá thật trong env, bước kế tiếp trên đường đi là
`_erp_publish_review_comment` — đăng ảnh lên thẻ thật.

Đo lại tại `7f86a38`: cả module `tests.test_agent_improvements` (40 bài) chạy
dưới chốt socket, **0 lần gọi ra ngoài**, xanh hết. Đóng cả fixture lẫn chốt.

**(c) `"kin ơi chạy đi"` → `"@bot ơi chạy đi"` — fixture, và nó siết chặt.**
`TRIGGER_WORDS = ("bot", "agent", "hvg")`; "kin" không thuộc đó, `mentions`
rỗng, nên `addressed_to_bot` trả False cho **mọi** người. Đo thật:

```
"kin ơi chạy đi":  trong danh sách → False   ngoài → False
"@bot ơi chạy đi": trong danh sách → True    ngoài → False
"@bot …", danh sách RỖNG, người ngoài → True   (giữ nguyên hành vi hôm nay)
```

Fixture cũ làm câu khẳng định của bài **đỏ**, còn câu phủ định xanh vì không
có chữ gọi tên chứ không vì hàng rào tác giả.

**(d) `45.0/5.0` → `15.0/0.0` — đổi hợp đồng theo PRD, không nới.**
`tasks/prd-agent-improvements.md:104-108`: A1.1 "mặc định … xuống **15.0**",
A1.2 "cận dưới … phải cho phép **0** … không phải `5.0` như hiện nay". Hai con
số loại trừ nhau. Bài cũ tự ghi lý do treo — *"the default stays put until
that is measured"* — và phép đo đã có. Độ chặt không đổi. Hợp đồng đầy đủ nằm
ở `AgentModeDeadWaitTests` (nay 7 bài), chặt hơn bài cũ. Không bài nào khác
xanh trên `main` đỏ vì con số này; `45.0` không còn ở đâu trong `tests/`.

## Hàng rào quyền và bí mật

Ba chỗ được chỉ định, cả ba **đúng**.

- **A8 `CLI_ENV_ALLOWLIST` (`agent_brain.py`) — chỉ ghi TÊN.** Câu log là
  `log.debug("Không đưa %s biến môi trường sang CLI: %s", len(dropped), ", ".join(sorted(dropped)))`;
  `dropped` chỉ chứa `name`. `_looks_like_a_secret` cũng chỉ nhận `name`.
  Không đường nào giá trị lọt vào log hay câu lỗi. `_run_cli` đổi từ "kế thừa
  mọi thứ trừ `ERP_*`" sang `env=cli_env()` — siết lại, không nới.
- **A9 sổ ngân sách (`agent_bot.py`) — đúng.** Sổ nằm trong `AgentBotState`
  nên sống qua khởi động lại; cửa sổ cuốn chiếu chứ không phải mốc nửa đêm;
  `record_brain_call` ghi **trước** khi gọi CLI nên một lượt treo vẫn bị tính;
  mỗi cửa sổ chỉ nói "hết trần" một lần.
- **C3 `parse_allowed_authors` (`agent_chat.py`) — danh sách rỗng KHÔNG khoá
  ai.** `parse_allowed_authors("")` → `()`; `author_is_allowed(comment, ())`
  → `True`. Không có danh sách mặc định nào bị bịa ra. Khi đang chạy không
  khoá, bot ghi một `log.warning` mỗi lượt quét chứ không im. Thiếu tác giả
  trong lúc *đang* khoá thì từ chối (C3.5). `_note_refused_author` hỏi lại
  `addressed_to_bot` **không kèm danh sách** để chỉ ghi câu thật sự nói với
  bot, và câu log mang `task_id` + email tác giả, **không** mang nội dung
  bình luận.

Thêm hai chỗ mới landing sau bản trước, đã soát riêng phần quyền/bí mật:

- `.claude/skills/agent-pipeline/SKILL.md` ("Luật 1b") **siết** quy trình, không
  chạm `PROTECTED_GLOBS`, không nới quyền ghi của ai.
- `tests/network_guard.py` không đọc, không ghi, không log giá trị biến môi
  trường nào; câu lỗi chỉ mang `host:port`.

## Nên sửa

Không chặn phát hành. Mỗi mục cần một người nhận.

**Đã đóng trong lượt này** — giữ lại để PR đọc được đường đi:

| # | Nội dung | Đóng ở |
|---|---|---|
| 1 | lỗi project poll bị nuốt im | `e95b83e` (còn mép `job_id` rỗng) |
| 2 | lượt hỏng chậm hơn trước (~2P) | `e95b83e` |
| 3 | body hỏng đọc thành "đăng tất cả" | `952ce3c` |
| 4 | bộ test A6 không đếm số ảnh đã đăng | `952ce3c` |
| 6 | bộ test không có hàng rào mạng | `7f86a38` |
| 7 | `_is_loopback` so tiền tố chuỗi | `2906917` — đã đo lại, xem dưới |
| 8 | UDP `sendto` không bị chặn | `2906917` — đã đo lại, xem dưới |

**Còn mở:**

5. ~~**`test_the_agent_path_races_the_poll…` vẫn ghim vào chữ trong source.**~~ **ĐÓNG ở `6516585`** — cuộc đua tách thành `race_interceptor_and_project_poll`, hai bài `assertIn` thành bài hành vi, class đi 7 → 12 bài, bảy đột biến A–G tôi tự dựng lại đều chết đúng bài. Mô tả gốc giữ dưới đây.

   
   `inspect.getsource(...)` + `assertIn("FIRST_COMPLETED")` xanh kể cả khi cuộc
   đua nối dây sai, task bị rò, hay cả hai đường hỏng mà không ai báo. Nay đã
   khá hơn một nửa: phép trừ ngân sách có bài hành vi thật. Nhưng phần *nối
   dây* của cuộc đua — huỷ task, `gather(return_exceptions=True)`, ca cả hai
   đường hỏng — vẫn chỉ có bài đọc source canh, và bài mới của #1 cũng là bài
   đọc source. Cần một bài dựng hai `Future` giả rồi đo hành vi.
6. **(a) Chốt mạng không bật khi chạy một file lẻ.** Đo ở trên:
   `python -m unittest tests.test_erp_review` → `socket.getaddrinfo` chưa bị
   bọc. Cách đóng: thêm `tests/__init__.py` gọi `network_guard.install()` —
   `__init__` được nạp cho **cả** `discover` lẫn `unittest tests.<module>`.
   Kèm một bài canh chính điều ấy, để lần sau ai xoá `__init__.py` thì đỏ.
   Lưu ý `docs/chay-test-toan-du-an.md` đang ghi "`discover -t .` hỏng vì
   `tests/` không có `__init__.py`" — thêm file ấy sẽ đổi câu này, nên sửa doc
   cùng lúc.
7. **(b) `_is_loopback` so tiền tố chuỗi, không so địa chỉ.**
   `_is_loopback("127.0.0.1.example.com")` → `True` (đo thật). Nghĩa là một tên
   máy bắt đầu bằng `127.` đi lọt khâu DNS. Nửa còn lại đỡ được: IP trả về là
   IP công cộng nên `connect` vẫn CHẶN (đã đo với `93.184.216.34`), nên hậu quả
   là **rò một câu truy vấn DNS**, không phải rò kết nối. Cách đóng gọn:
   `ipaddress.ip_address(host).is_loopback` cho phần số, giữ danh sách tên
   riêng cho `localhost`.
8. **(c) UDP `sendto` không bị chặn.** Chốt bọc `connect`/`connect_ex`, mà UDP
   không cần `connect`. Đo thật: `sendto(b"\x00", ("8.8.8.8", 53))` LỌT. Muốn
   ra ngoài đường này phải có IP viết cứng (phân giải tên vẫn bị chặn), và repo
   không có client UDP nào — nên là lỗ hẹp, không phải đường lách sẵn. Đóng
   bằng cách bọc thêm `sendto`/`sendmsg` nếu thấy đáng.
9. **B3.2 không khoá được "chỉ yêu cầu của chính tôi" — fixture chỉ có một
   runner.** Đây là chỗ duy nhất tôi tìm được mà bài B3.2 *sau khi sửa* vẫn
   chưa với tới, và nó là chỗ liên quan tới quyền nên đáng nói. Đo bằng một
   đột biến sạch (bỏ **cả** `runner_key = ?` **cả** tham số bind của nó, để lỗi
   là hành vi chứ không phải lệch số tham số):

   ```
   XANH  fixture NHƯ BÀI TEST (một runner)   → bài KHÔNG bắt được
   ĐỎ    fixture có thêm một runner khác     → bài bắt được
   ```

   Tức là một bản Worker trả yêu cầu của **runner khác** vẫn xanh cả bộ node.
   Không phải lỗi của `fba4c47` — lỗ này có từ `fresh()` trong `e6dd796`, và
   Worker hôm nay **đúng** (tôi đã kiểm độc lập). Chi phí đóng: hai dòng thêm
   một runner thứ hai vào `fresh()`. Nên làm cùng lượt B3 còn lại.
10. **`docs/chay-test-toan-du-an.md` — bảng "số nền" trộn hai thời điểm.** Bảng
   ghi "đo lúc mở nhánh (2026-09-03)" nhưng dòng node ghi "6 đỏ", mà lúc mở
   nhánh là **33 đỏ**; 6 là số của `7f86a38`. Dòng bộ 1 ("1276, 8 đỏ") thì
   đúng là số lúc mở nhánh. PR sẽ trích bảng này, nên nên tách thành hai cột
   hoặc ghi rõ mỗi dòng đo ở commit nào. Bộ 1 nay là 1290, không phải 1276.

11. **`docs/chay-test-toan-du-an.md` (commit `7102d1f`) nói sai một sự thật
   về môi trường, và cái sai ấy đắt.** Commit viết: repo *"không có
   `requirements*.txt` hay `pyproject.toml` nào, nên không chỗ nào khai
   pytest"*. Sai cả hai vế. `pyproject.toml` **có**, ở gốc repo, và nó khai
   pytest ngay trong đó:

   ```toml
   [project.optional-dependencies]
   dev = [
       "pytest>=8.0.0",
   ]
   ```

   Nguồn không những tồn tại mà còn đang nằm sẵn trong `CLAUDE.md:30`:
   `.venv/bin/python -m pip install -e '.[dev]'`. Bộ 5 đỏ vì `.venv` hiện tại
   dựng thiếu extra `[dev]` (`import pytest` → `ModuleNotFoundError`), **không**
   vì thiếu nguồn khai báo.

   Hậu quả tự kiểm được: người dựng máy mới đọc dòng ấy sẽ kết luận bộ 5 không
   sửa được bằng lệnh, rồi làm đúng việc mà chính commit gợi ý — *"viết lại
   bằng unittest là một lượt việc"* — 18 bài, để thay cho một lệnh `pip install`
   đã được ghi sẵn. Đây là **MÔI TRƯỜNG**, và cách dựng lại đúng là một dòng.
   File này không phải `docs/review-*.md` nên tôi không sửa; cần người nhận.

12. **`scripts/chay-test.sh` (commit `4741b44`) đọc một bộ test chết thành
   xanh.** Script không nhìn mã thoát của năm lệnh; nó suy ra kết quả bằng cách
   grep chữ trong log. Bộ nào hỏng **trước khi** in được dòng tổng kết thì
   `Ran N tests` không có, `TONG=0`, `DO=0`, và `if [ "${DO[$i]}" != "0" ]`
   (`:126`) không kích hoạt — `LOI` ở nguyên 0, script in *"Không bộ nào đỏ vì
   code"* và **thoát 0**. Đo thật, không suy luận:

   ```
   $ cd /tmp/nodir && .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
   ImportError: Start directory is not importable: 'tests'
   mã thoát thật = 1
   → script đọc ra: TONG=0  DO=0  XANH=0   ⇒ không tính là lỗi
   ```

   Ca chạm được: chạy sai thư mục, `-s tests` không import được, `.venv` hỏng
   giữa chừng, và với bộ 3 là glob `*.test.mjs` không khớp file nào
   (`TONG[3]:=0` ở `:99` dập tắt luôn). Người ngồi nhìn bảng **có** thấy dòng
   `0 0 0`, nhưng bất cứ thứ gì tiêu thụ mã thoát thì thấy xanh. Cách đóng:
   giữ mã thoát của từng lệnh (`rc=$?`) và coi `rc != 0` kèm `TONG == 0` là
   đỏ thật.

   *Về ngoại lệ pytest mà anh hỏi: ngoại lệ ấy **không** quá rộng.* Nó khớp
   chuỗi chính xác, chỉ áp cho bộ 5, và được hỏi lại lần hai ở `:127`. Chỗ hở
   không nằm ở ngoại lệ hẹp ấy mà ở lỗ 0/0/0 bên trên — lỗ ấy rộng hơn nhiều và
   áp cho **cả năm** bộ. Thêm nữa, theo phát hiện #11 thì ngoại lệ này lẽ ra
   không cần tồn tại: pytest có khai trong `pyproject.toml`, cài vào là bộ 5
   xanh.


   **ĐÓNG ở `3c9fd10` — tôi tự đo, không nhận lời.** Dựng lại đúng ca đã tả
   (`rm -rf tests/` để `-s tests` chết trước khi kịp in dòng tổng kết), chạy
   cả hai bản script trong cùng cây hỏng ấy:

   ```
   bản MỚI (3c9fd10):  1. tests/  0  0  ?   mã thoát 1 nhưng không đọc ra bài đỏ nào
                       CÓ BÀI ĐỎ …                      → mã thoát 1
   bản CŨ  (4741b44):  1. tests/  0  0  0   0 lần bị chốt mạng chặn
                       Không bộ nào đỏ vì code.         → mã thoát 0
   ```

   Nhánh vá ở `chay-test.sh:155`. Bản vá còn đi xa hơn chỗ tôi nêu: thêm một
   nhánh `TONG == 0` bắt luôn ca **chạy 0 bài mà vẫn thoát 0** — đúng cái bẫy
   bộ 5 nằm trong suốt. `${RC[$i]:-0}` mặc định về 0, nhưng cả năm bộ đều có
   bắt mã thoát (`:89, 97, 106, 118, 130`), nên chỗ mặc định ấy chưa hở.

13. **Hàng rào `bb24de4` dựng bằng văn xuôi, chưa có gì đỡ ở tầng thi hành.**
   `PROTECTED_GLOBS` (`worker.js:74-83`) có `automation_center/{src/worker.js,
   migrations,runner,scripts}/**`, nhưng **không** có `.claude/**`, không có
   `CLAUDE.md`, và không có `scripts/**` ở gốc repo. Nghĩa là chính ba loại
   file vừa được dùng để siết quyền — định nghĩa agent, luật chung, và script
   phán xử xanh/đỏ — vẫn nằm trong tầm ghi của một yêu cầu code có phạm vi
   rộng. Điều 5 của `CLAUDE.md` cấm đúng hình dạng này: *"Đừng làm thay đổi nào
   khiến nó tự nới được quyền của chính nó."*

   Chưa có thay đổi nào trong đợt này khai thác chỗ đó, nên **không CHẶN**.
   Nhưng `4741b44` vừa làm nó đắt hơn: từ nay có một file duy nhất trả lời câu
   "cả năm bộ có xanh không", và file ấy sửa được. Đề nghị thêm ba glob
   `.claude/**`, `CLAUDE.md`, `scripts/**` vào `PROTECTED_GLOBS` — sửa
   `worker.js`, tức việc của lane-orch-opus, không phải của tôi.

   **Đã đóng ở `fb421ca`** — ba glob ấy vào đủ, đã soát riêng bên dưới.

14. **`tests/test_luat_cung_repo.py:test_khong_quet_rong_qua_tay` chỉ canh một
   danh sách cố định.** Bốn đường dẫn viết cứng, cả bốn đang được theo dõi.
   Sau `7a08fc1` bài này **cắn được** với file đang theo dõi (đã đo). Nhưng ca
   còn hở là file **chưa** được theo dõi bị một mẫu `.gitignore` mới nuốt:
   `git add -A` sẽ bỏ qua nó không tiếng động, và không bài nào kêu — bài 4
   dùng `git ls-files --cached`, chỉ nhìn thứ đã vào index. Cách đóng phải
   quét cả cây làm việc (`git status --porcelain --ignored` rồi đối chiếu với
   một danh sách trắng), tức một lượt việc chứ không phải một dòng. Lane đã tự
   khai chỗ này trong commit message và PR — ghi lại đây để có người nhận.

15. **Miễn trừ MÔI TRƯỜNG của bộ 5 bắt nhầm cả plugin thiếu.**
   `chay-test.sh:132` hỏi `grep -qE "No module named '?pytest'?"`. Dấu `'?`
   cuối là tuỳ chọn, nên mẫu này khớp **mọi** module thiếu có tên bắt đầu bằng
   `pytest`. Đo:

   ```
   No module named pytest                            → KHỚP  (đúng ý)
   ModuleNotFoundError: No module named 'pytest_asyncio'  → KHỚP  (sai)
   ModuleNotFoundError: No module named 'pytest_cov'      → KHỚP  (sai)
   ModuleNotFoundError: No module named 'yaml'            → không khớp
   ```

   Chạy thật cho hết đường: dựng một `pytest` giả trên `PYTHONPATH` để lệnh
   `-m pytest` **chạy được** rồi chết lúc gom bài với `No module named
   'pytest_asyncio'`, mã thoát 4. Script in
   `5. bmad-distillator  0  0  0  MÔI TRƯỜNG — .venv thiếu extra [dev]` rồi
   `Không bộ nào đỏ vì code.` và **thoát 0**. Câu gợi ý sửa cũng sai: extras
   `dev` chỉ có mỗi `pytest`, cài lại không đỡ được plugin.

   **Chưa phải chuyện đang xảy ra**: bộ 5 hiện không có `conftest.py`, không
   import `pytest_*` nào — đã tìm, không thấy. Nên đây là bẫy chờ, không phải
   lỗi đang chảy máu. **Đừng bỏ hẳn miễn trừ** — máy thiếu `[dev]` mà đọc
   thành đỏ thì người ta sẽ tập thói quen lờ mã thoát, tệ hơn. Chỉ cần neo
   chặt: `grep -qE ": No module named pytest$"` — đã đo, khớp đúng dòng thật
   (`.../python: No module named pytest`) và **không** khớp dạng plugin.

16. **`tom_tat_python` đếm subtest thành bài, nên cột xanh sai.**
   `chay-test.sh:82` lấy `fail` bằng `grep -cE '^(FAIL|ERROR): '`, mà mỗi
   subtest hỏng in một dòng `FAIL:` riêng, trong khi `Ran N tests` đếm theo
   **bài**. Đo trên log thật của `tests.test_luat_cung_repo` với đột biến
   `data/state.json` (1 bài đỏ, 4 subtest):

   ```
   script in:  tổng=4  đỏ=4  xanh=0
   sự thật:    4 bài, 1 đỏ, 3 xanh
   ```

   Sai về phía an toàn (kêu quá, không kêu thiếu) nên không chặn. Nhưng
   `xanh = ran - fail` **âm được**: log 1 bài với 5 subtest đỏ cho
   `tổng=1 đỏ=5 xanh=-4` (đã đo). Một bảng in số âm thì người đọc mất tin vào
   cả bảng, mà bảng này giờ là chỗ duy nhất trả lời "cả năm bộ có xanh không".
   Cách đóng: đọc thẳng `FAILED (failures=F, errors=E)` ở dòng cuối, hoặc kẹp
   `xanh` không xuống dưới 0.

17. ~~**Không bài node nào giữ vế khẳng định của hai đầu API cập nhật.**~~ **ĐÓNG ở `bc87b25`** — M2/M4/M6/M8 có vế khẳng định, đo lại: bốn đầu API hỏng hẳn nay đều làm đỏ đúng bài của mình. Mô tả gốc:

   
   `runnerUpdateRun` (`worker.js:774`) và `runnerUpdateControlRequest`
   (`:2582`) hỏng hẳn — luôn trả 404 — mà cả bộ node vẫn xanh nguyên (đo ở
   dưới). Lỗ có sẵn từ `main`, không phải hồi quy của nhánh này. Cách đóng rẻ:
   thêm vế khẳng định vào M2 và M8 của `runner_scope_isolation.test.mjs`.

### Mục 9 đóng ở `984c9ac` — tự đo cả tám, và một chỗ tôi phải nhận sai

`git show 984c9ac --stat` đúng một file, `automation_center/tests/runner_scope_isolation.test.mjs`,
+235/−0. `worker.js` không bị chạm — đây là lỗ ở bộ test, không phải lỗ ở code.

Nền tôi tự đo tại `984c9ac`: node **199/198/1** (`not ok 80 - phía runner`),
bộ 1 `Ran 1301 … OK` (`OutboundNetworkBlocked` = 0), bộ 2 `Ran 85 … OK`.

Tám đột biến, mỗi lần gỡ đúng một mệnh đề `runner_key = ?` **cùng tham số bind
của nó**, chạy trên bản sao ở `/tmp` (không chạm file repo). Cột cuối là câu
hỏi quan trọng: chết **đúng bài của mình** hay chuông kêu bừa.

| Đột biến | tổng đỏ | bài chết |
|---|---|---|
| M1 `bot_runs claim` `:760` | 2 | `M1 · /api/runner/claim…` |
| M2 `bot_run update` `:779` | 2 | `M2 · /api/runner/runs/{id}…` |
| M3 `code claim` `:1790` | 2 | `M3 · /api/runner/code/claim…` |
| M4 `code finished` `:1868` | **3** | `M4 · …` + `id của runner khác không trả lời…` + `runner hỏi được yêu cầu nào đã kết thúc` |
| M5 `code approved` `:1884` | 2 | `M5 · …` |
| M6 `code update` `:1900` | 2 | `M6 · …` |
| M7 `control claim` `:2528` | 2 | `M7 · …` |
| M8 `control update` `:2589` | 2 | `M8 · …` |

Mọi dòng "tổng đỏ = 2" là B3.1 (đỏ sẵn) cộng đúng một bài mới. Không đột biến
nào làm đỏ bài của người khác. Trả nguyên trạng: 199/198/1.

**Chỗ tôi sai:** mục 9 của bản trước viết B3.2 "không khoá được" cho cả cụm.
Đột biến M4 làm đỏ **ba** bài, hai trong đó có sẵn từ trước — nên riêng
`/api/runner/code/finished` thì đã có người canh, và câu chữ của tôi rộng quá
tay. Chẩn đoán gốc (fixture một runner nên gỡ mệnh đề lọc vẫn trả đúng dòng)
thì đúng, và đúng cho bảy chỗ còn lại. Ghi lại đây thay vì sửa lặng.

**Không nên gộp vào `fresh()` cũ.** File riêng là lựa chọn đúng: nền của bài cũ
không đổi, và tám bài mới có fixture hai runner mà bài cũ không cần.

### Một lỗ khác lộ ra khi soát chỗ này — mục 17

Chú thích đầu file mới hứa "mỗi bài khẳng định **cả hai vế**". Bốn bài M2, M4,
M6, M8 chỉ có vế phủ định (404 + trạng thái nguyên vẹn). Tôi đo xem có ai giữ
vế còn lại không, bằng cách làm hỏng hẳn cả đầu API:

| Worker bị hỏng thành | tổng đỏ | bài chết ngoài B3.1 |
|---|---|---|
| `runnerUpdateRun` luôn trả 404 | **1** | **không bài nào** |
| `runnerUpdateControlRequest` luôn trả 404 | **1** | **không bài nào** |
| `runnerFinishedCodeRequests` luôn trả `[]` | 3 | 2 bài |
| `runnerUpdateCodeRequest` luôn trả 404 | 8 | 7 bài |

Hai dòng đầu là lỗ thật: **một Worker từ chối mọi cập nhật trạng thái của
runner đi qua trọn bộ node mà không ai kêu.** Hậu quả nếu xảy ra: runner báo
`completed`, Worker trả 404, lần chạy nằm mãi ở `running`, bot không bao giờ
đổi trạng thái — im lặng, không log, không ai biết. Đây **không phải hồi quy**
của nhánh này: lỗ có sẵn từ `main`, và `984c9ac` chỉ làm nó lộ ra. Cách đóng
rẻ: thêm vế khẳng định vào chính M2 và M8 — runner **một** cập nhật việc của
**chính nó** thì phải thành công và trạng thái phải đổi.

### `6516585` và `bc87b25` — soát lượt cuối, đóng mục 5, 15, 16, 17

Ba câu hỏi lane đặt, trả lời bằng phép đo chứ không bằng đọc diff.

**(a) `race_interceptor_and_project_poll` có đúng là di chuyển thuần không —
CÓ.** Tôi không đọc mắt thường mà so bằng máy: cắt khối cũ inline
(`6ae7c43:flow_web/service.py`) và thân hàm mới, bỏ chú thích, chuẩn hoá
khoảng trắng, rồi `difflib`. Toàn bộ chênh lệch còn lại đúng ba thứ:

| Chênh | Có đổi hành vi không |
|---|---|
| chữ ký + docstring hàm mới | không |
| `Optional[Exception]` → `Optional[BaseException]` | không — chỉ là chú giải kiểu |
| `elif job_id: await self.store.append_log(...)` → `elif on_poll_error is not None: await on_poll_error(...)` | không, xem dưới |

Thứ tự huỷ và `gather` trong `finally` giống nhau **từng dòng** sau khi chuẩn
hoá xuống dòng: vẫn `for task in (interceptor, project): if not task.done():
task.cancel()` rồi `await asyncio.gather(..., return_exceptions=True)`.

Chỗ duy nhất đáng ngờ là `on_poll_error=_ghi_loi_poll if job_id else None`:
bản cũ hỏi `job_id` **mỗi lần** có lỗi, bản mới hỏi **một lần** lúc gọi. Hai
cái ấy chỉ bằng nhau nếu `job_id` không đổi giữa chừng. Đã kiểm: trong cả thân
`_generate_single_reference_image_via_ui` (`:24902-25473`) `job_id` xuất hiện
63 lần và **không lần nào là phép gán** — bốn chỗ trông giống gán đều là tham
số `job_id=job_id`. Nên hai cách hỏi cho cùng một câu trả lời.

**(b) Trần thời gian có che kiểu hỏng nào không — không.** `chay_co_gioi_han`
không dùng `wait_for`; nó hỏi trạng thái task rồi `viec.result()`, nên mọi lỗi
của bài vẫn ném nguyên vẹn — bài `..._raises_the_interceptor_error...` bắt
`TimeoutError` thật và vẫn xanh, đúng cái bẫy 3.11 mà lane đã tự vấp và ghi
lại. Trần chỉ biến **treo** thành **đỏ đọc được**: đột biến D in đúng câu
"cuộc đua không kết thúc trong 2.0s — nhiều khả năng đường thua không được
huỷ", và với D thì chẩn đoán ấy đúng thật.

Bảy đột biến A–G tôi tự dựng lại trên bản sao ở `/tmp`, không chạm file repo.
Nền: `Ran 12 tests … OK`.

| Đột biến | Bài đỏ |
|---|---|
| A `while` → `if` | 2 — `..._poll_that_finds_nothing...`, `..._an_interceptor_timeout...` |
| B bỏ `interceptor_error = task_exc` | 1 — `..._raises_the_interceptor_error...` |
| C bỏ `await on_poll_error(...)` | 2 |
| D bỏ `task.cancel()` | 3 — trong đó 2 bài đỏ **qua trần**, 1 bài đỏ bằng assertion thật |
| E bỏ `raced_images = list(outcome)` | 2 |
| F `got_result = True` → `False` | 4 |
| G bỏ `await asyncio.gather(...)` | 1 — `..._nothing_leaks` |

Bảy trên bảy chết, không đột biến nào để lọt. Bảng trong docstring khai **ít**
hơn thực tế ở C và E (khai 1, đo được 2) — khai thiếu thì không sao, khai thừa
mới là vấn đề.

Một mép nhỏ, không chặn: trần 2.0s là giờ tường, mà 12 bài chạy hết 0.155s —
dư khoảng 13 lần. Máy tải nặng mà vượt trần thì câu báo lỗi sẽ đổ cho "đường
thua không được huỷ" trong khi thủ phạm là chậm. Xác suất thấp, nhưng câu báo
đang khẳng định một chẩn đoán mà nó không phân biệt được.

**(c) Vế khẳng định mới ở bốn bài node có xanh giả không — không.** Đo bằng
đúng phép thử đã lộ ra mục 17: làm hỏng hẳn cả đầu API rồi xem ai kêu. Chạy
riêng `runner_scope_isolation.test.mjs` (nền 8/8):

| Worker bị hỏng thành | trước `bc87b25` | sau |
|---|---|---|
| `runnerUpdateRun` luôn 404 | **không bài nào đỏ** | M2 đỏ |
| `runnerFinishedCodeRequests` luôn `[]` | M4 không đỏ | M4 đỏ |
| `runnerUpdateCodeRequest` luôn 404 | M6 không đỏ | M6 đỏ |
| `runnerUpdateControlRequest` luôn 404 | **không bài nào đỏ** | M8 đỏ |

Và tám đột biến gỡ `runner_key = ?` vẫn chết đúng bài của mình sau khi thêm vế
mới — vế khẳng định không làm hỏng vế phủ định. **12 đột biến, 12 lần chết
đúng chỗ, không lần nào bắn nhầm bài khác.** **Mục 17 đóng.**

**Mục 15 đóng — đo hai chiều.** Dựng một `pytest` giả chạy được rồi chết lúc
gom bài vì thiếu `pytest_asyncio`, mã thoát 4:

```
bản mới:  5. bmad-distillator  0  0  ?  mã thoát 4 nhưng không đọc ra bài đỏ nào
          CÓ BÀI ĐỎ …                                        → thoát 1
ca thiếu pytest THẬT, bản mới:
          5. bmad-distillator  0  0  0  MÔI TRƯỜNG — .venv thiếu extra [dev]
          Không bộ nào đỏ vì code.                           → thoát 0
```

Đúng cả hai chiều: siết được ca sai mà không siết nhầm ca đúng.

**Mục 16 đóng.** Đếm theo bài (`awk '{print $2, $3}' | sort -u`) thay vì theo
dòng. Đo trên log thật và trên ca từng ra số âm:

```
log thật 1 bài đỏ 4 subtest:  tổng=4  đỏ=1  xanh=3   [4 dòng]   ← sự thật: 4 bài, 1 đỏ, 3 xanh
ca từng cho xanh = -4:        tổng=1  đỏ=1  xanh=0   [5 dòng]
log thường 3 bài đỏ khác nhau: tổng=10 đỏ=3 xanh=7   [3 dòng]   ← không gộp nhầm
```

`${PHU[$i]:+ …}` dưới `set -u` không nổ khi phần tử chưa đặt — đã thử riêng.

**Số tôi tự đo tại `bc87b25`**, worktree sạch, cả năm bộ:
`1306 · 85 · 199 · 35 · 0` — **1625 bài, 1624 xanh, 1 đỏ**, và bài đỏ ấy vẫn
đúng một mình B3.1 (`not ok 80 - phía runner`). `OutboundNetworkBlocked` = 0.
Khớp số của lane.

### Đo lại mục 7 và 8 sau `2906917`

15 phép thử, chạy ở worktree sạch tại HEAD. Cả 15 ra đúng chiều:

| Phải CHẶN | Kết quả |
|---|---|
| `getaddrinfo("127.0.0.1.example.com", 443)` — đúng lỗ mục 7 | CHẶN |
| `getaddrinfo("localhost.evil.com", 80)` | CHẶN |
| `sendto` UDP `8.8.8.8:53` — đúng lỗ mục 8 | CHẶN |
| `sendmsg` UDP `1.1.1.1:53` | CHẶN |
| `connect` TCP `api.anthropic.com:443` · `gethostbyname("google.com")` · `connect_ex 8.8.8.8:53` | CHẶN |

| Phải LỌT | Kết quả |
|---|---|
| `localhost` · `127.0.0.1` · `127.0.0.53` · `::1` · UDP loopback | LỌT |

Một chỗ nhỏ, không phải lỗi: `2130706433` và `0x7f.0.0.1` — hai cách viết hợp
lệ khác của `127.0.0.1` — bị **chặn**. Sai chiều an toàn (chặn nhầm một thứ vô
hại), nên để nguyên cũng được; chỉ cần biết trước, kẻo một ngày có bài test
dựng server nội bộ bằng dạng số rồi đỏ mà không hiểu vì sao.

Mở: **6(a), 14**. Đóng: mục 5 ở `6516585`; mục 15, 16, 17 ở `bc87b25`; mục 9 ở `984c9ac`; mục 12 ở `3c9fd10`; mục 13 ở `fb421ca` — mọi mục đóng đều đã đo lại, không mục nào nhận lời.

## Phán quyết `777df54` (B4) — **TEST SAI đã sửa đúng, KHÔNG phải nới lỏng**

Và trước hết: **báo cáo này đã đọc sai B4, tôi ghi lại chỗ sai của mình.** Bản
trước xếp ba bài `bot_command_limit_parity` vào TỒN ĐỌNG với lời "chỉ thiếu
`MAX_BOT_COMMANDS_PER_TURN` trong khối `export {}`". Tôi đọc yêu cầu của bài
test rồi suy ra một dòng sửa, mà **không kiểm dòng ấy có làm đỏ chỗ khác
không**. Nó có. Ai làm theo đúng câu trong báo cáo của tôi sẽ đẩy đi một Worker
không khởi động nổi.

**Đo lại từ đầu, không đọc lập luận của ai.**

*(a) Cài đặt đã xong từ trước, không phải chưa cài.* `git show 306df94` cho
thấy `MAX_BOT_COMMANDS_PER_TURN = 5` ở `worker.js:28`, đi ra ngoài qua
`CONTROL_LIMITS` (`:2772`, trong khối `export` `:2789`), kèm sẵn chú thích ở
`:26` nói rõ *"Xuất ra qua CONTROL_LIMITS vì workerd…"*. `git log 306df94..HEAD
-- src/worker.js` chỉ có một commit là `470b64c` (B3.3). Đúng như lane khai:
**không có byte nào của người sửa test trong `worker.js`.**

*(b) Đường mà bài test cũ đòi là đường bị cấm.* Tôi tự dựng đột biến trên một
bản sao ở `/tmp`: thêm `MAX_BOT_COMMANDS_PER_TURN` vào khối `export {}`.

```
NỀN (không đột biến)              # tests 36  # pass 36  # fail 0
A: thêm named export kiểu số      # tests 36  # pass 35  # fail 1
   not ok 22 - module xuất ra vẫn nạp được vào workerd
   export "MAX_BOT_COMMANDS_PER_TURN" là number; hãy gom vào một object
```

Bài chặn ấy nằm ở `agent_control.test.mjs:259`, sinh ở `002804c`, và tôi đã
kiểm: `002804c` **là tổ tiên của `main`**, file trên `main` và trên HEAD giống
hệt nhau (365 dòng, `git log main..HEAD` cho file ấy rỗng). Nghĩa là làm theo
báo cáo cũ của tôi sẽ **biến một bài đang xanh trên `main` thành đỏ** — đúng
định nghĩa CHẶN của chính tài liệu này. Ba bài B4 bản đầu **đỏ vì chính chúng**:
không bản Worker nào vừa qua được chúng vừa qua được `main`.

*(c) Khẳng định không bị nới.* Bốn đột biến, chạy ở bản sao `/tmp`:

| Đột biến | Kết quả |
|---|---|
| không đột biến | 7/7 **xanh** |
| Worker nới 5→6, runner giữ 5 | **ĐỎ** (3 fail) |
| runner nới `commands[:5]`→`[:7]`, Worker giữ 5 | **ĐỎ** (1 fail) |
| bỏ hằng khỏi `CONTROL_LIMITS` | **ĐỎ** (3 fail) |
| đổi giá trị `5` → chuỗi `"5"` | **ĐỎ** (3 fail) — `typeof` vẫn cắn |
| trả nguyên | 7/7 **xanh** |

Cả hai chiều trôi đều bị bắt, và phép thử kiểu vẫn còn răng. Predicate không
đổi: `typeof === "number"`, so với chính con số runner cắt, và `=== 5`.

*(d) Có mất gì không?* Hợp đồng **có** đổi hình dạng: từ "trần phải là một
named export" thành "trần phải với tới được qua `CONTROL_LIMITS`". Nhưng hình
dạng cũ là hình dạng bị một bài trên `main` cấm, nên không có bản cài đặt hợp
lệ nào rơi vào khoảng vừa mất. Tôi không tìm ra thứ gì bài cũ bắt được mà bài
mới bỏ sót.

**Kết luận: TEST SAI đã sửa đúng. Đừng revert `777df54`.** Cùng loại với
`fba4c47`: một bài đỏ-từ-lúc-sinh-ra, và nếu để nguyên thì nó đẩy lane đi
"sửa" một thứ vốn đã đúng — lần này cái giá là một Worker không boot.

### Bộ 5 chạy bằng `unittest discover` là chạy rỗng — kiểm độc lập

Lane báo chỗ này; tôi kiểm lại và **đúng**, kiểm mà không đụng `.venv` của
repo, không cần mạng. Cách kiểm: dựng một module `pytest` giả ở `/tmp/stub`
chỉ đủ để `import pytest` chạy được, rồi cho vào `PYTHONPATH`.

```
$ PYTHONPATH=/tmp/stub .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
Ran 0 tests in 0.000s
OK
mã thoát=0
```

Nghĩa là **sửa môi trường cho đúng sẽ tạo ra một màu xanh giả**: thiếu pytest
thì lệnh cũ đỏ vì lỗi import, còn có pytest thì nó in `OK` sau khi chạy đúng 0
bài. Bộ 5 có **18** hàm `def test_` nằm trong 4 class `class Test…:` thường
(không phải `unittest.TestCase`, tôi đếm được 0 lớp `TestCase`), nên
`unittest` không nhặt bài nào; pytest đếm ra nhiều hơn 18 vì có
`@pytest.mark.parametrize`.

Đây là loại xanh giả tệ nhất trong bốn loại: nó xuất hiện **đúng lúc** người
ta làm cho môi trường sạch. Lệnh đúng là `python -m pytest tests -q`, và cái
chốt "chạy 0 bài mà thoát 0 cũng là đỏ" là thứ phải có. Cả hai đã vào tài liệu
ở `3c9fd10`.

Ghi thêm một điều đáng khó chịu, vì nó là chuyện của chính vai này:
`.claude/agents/test-reviewer.md` trước `3c9fd10` bảo vai soát chạy bộ 5 bằng
lệnh gom 0 bài. Tôi đã chạy đúng lệnh được đưa và ghi kết quả của nó vào bảng
số, không hỏi lại xem con số ấy có nghĩa gì. **Bảng số của các bản báo cáo
trước vì thế nói về 4 bộ, không phải 5** — và tôi không phát hiện ra, người
khác phát hiện. Cách đóng cho lần sau nằm ngay trong chính mục #12 tôi vừa
viết: đừng bao giờ nhận một dòng "OK" mà không nhìn con số bài chạy kèm nó.

### Soát `fb421ca` — lần đầu nhánh chạm `worker.js`. Chỉ siết, không nới.

Diff là 40 dòng thêm, **0 dòng xoá**, ở 3 file: `worker.js` (+10, chỉ thêm mẫu
vào `PROTECTED_GLOBS`), `orchestrator_runner.py` (+5, bản sao cứng),
`code_scope_covering_glob.test.mjs` (+25). Không đụng một dòng logic phân
quyền nào. Tôi nạp `worker.js` thật ở worktree sạch tại `e889e4b` rồi chạy
`isProtectedPath` và `coveringProtectedGlobs` trên 20 đường dẫn:

| Phải CHẶN | |
|---|---|
| `CLAUDE.md` · `claude.md` · `docs/CLAUDE.md` | CHẶN |
| `.claude/agents/test-reviewer.md` · `.claude/skills/agent-pipeline/SKILL.md` | CHẶN |
| `scripts/chay-test.sh` · `scripts/sub/deep.sh` | CHẶN |
| `.CLAUDE/AGENTS/X.MD` (viết hoa hết) | CHẶN — mẫu chữ thường là đúng |

| Phải còn ghi được (nếu chặn hụt là chết dây chuyền ba vai) | |
|---|---|
| `docs/review-dot-a.md` · `tasks/prd-*.md` · `docs/chay-test-toan-du-an.md` | ghi được |
| `flow_web/service.py` · `flow_web/static/app.js` · `flow_web/scripts/helper.py` | ghi được |
| `automation_center/tests/*.test.mjs` · `tests/test_agent_improvements.py` · `README.md` | ghi được |

Phía runner dùng `fnmatch.fnmatchcase`, mà `*` của `fnmatch` **có** vượt `/`,
nên `".claude/*"` một sao vẫn phủ `.claude/agents/…`; hai bản không lệch nhau.
Bài parity canh chỗ này đang xanh.

Một mép hẹp, đúng chiều siết nên không phải lỗi: phạm vi `**/*.md` nay là glob
phủ (`coveringProtectedGlobs` trả `claude.md`, `**/claude.md`) nên không lưu
được nữa. Phạm vi thật của vai viết PRD là `tasks/*.md` + `docs/*.md`, cả hai
vẫn lưu được — đã đo.

**Kết luận: không có chiều nới nào. Đừng revert.**

### Chỗ hở `.dev.vars` — và **một nửa lập luận của tôi ở bản trước là sai**

Ghi chỗ sai trước, vì nó đúng loại lỗi mà báo cáo này bắt người khác.

Bản trước tôi viết: `.dev.vars` *"cũng không có trong `.gitignore`"*, nên
*"vừa commit được vừa không cần Owner duyệt — có thể commit thẳng bí mật của
Worker vào một nhánh"*. **Sai.** Tôi chỉ đọc `.gitignore` ở gốc rồi kết luận
từ chỗ vắng mặt. Có file thứ hai:

```
$ git check-ignore -v automation_center/.dev.vars
automation_center/.gitignore:2:.dev.vars   automation_center/.dev.vars
$ git check-ignore -v data/state.json
.gitignore:21:data/state.json              data/state.json
```

Cả hai dòng đó có từ trước. Thêm nữa runner chỉ `git("add", "-A")`
(`orchestrator_runner.py:1313`), không `-f`, nên file bị ignore **không bao
giờ** vào được commit. **Câu "commit thẳng bí mật vào một nhánh" là sai, và
tôi rút.** Lỗi này cùng hạng với lỗi tôi mắc ở B4: kết luận từ bằng chứng một
phần mà không kiểm hết đường.

**Chỗ hở thật vẫn còn, chỉ là ở chiều khác.** `.gitignore` chặn chiều *commit*;
nó không nói gì về chiều **đọc và ghi tại chỗ**. `PROTECTED_GLOBS` mới là thứ
quyết định runner có được mở file ấy ra rồi nhét vào prompt hay không. Trước
`5eb5e04`, đo được: `isProtectedPath("automation_center/.dev.vars")` → **LỌT**.
Nên vá vẫn đáng, chỉ vì lý do khác lý do tôi nêu.

**Và tôi bỏ sót một cái tên.** Điều 3 `CLAUDE.md` cấm bốn cái tên; danh sách cũ
phủ hai. Tôi nêu một (`.dev.vars`) và không nêu `data/state.json*` — lane bắt
được chỗ này, không phải tôi.

**Sau `5eb5e04`, đo lại — 23 → 29 mẫu, 0 mẫu bị bỏ.** 20 đường dẫn qua
`worker.js` thật và 8 đường qua bản runner, cả hai đều đọc ra 29 mẫu:

| Phải CHẶN | Worker | runner |
|---|---|---|
| `automation_center/.dev.vars` · `.dev.vars.production` · `.dev.vars` | CHẶN | CHẶN |
| `data/state.json` · `.bak` · `.tmp` · `flow_web/data/state.json` | CHẶN | CHẶN |
| `CLAUDE.md` · `.claude/agents/x.md` · `scripts/chay-test.sh` | CHẶN | CHẶN |

| Phải còn ghi được — canh cho `data/state.json*` khỏi quét rộng | |
|---|---|
| `data/account_book.json` · `data/sku_book.json` · `data/state_helper.py` | ghi được |
| `docs/*.md` · `tasks/*.md` · `flow_web/service.py` · `flow_web/static/app.js` | ghi được |
| `automation_center/tests/*.test.mjs` · `tests/network_guard.py` · `README.md` | ghi được |

`.gitignore` gốc **không bị đụng** (`5eb5e04` chỉ +3 dòng ở
`automation_center/.gitignore`). Cả 4 file trong commit đều chỉ thêm, 0 xoá.

Còn một mép hẹp, nói cho đúng mức lần này: `.gitignore:21` là tên chính xác
`data/state.json`, nên `data/state.json.bak` và `.tmp` **không** bị gitignore
chặn (đo bằng `git check-ignore -q`). Sau `5eb5e04` chúng cần Owner duyệt nên
chiều commit không còn tự do; muốn khoá nốt thì `.gitignore:21` nên là
`data/state.json*`. Một dòng, và nó nằm ở file không ai bị cấm sửa.

### `7a08fc1` — bài chết ấy đã cắn được. Không nới, một từ, đúng chỗ.

Diff đúng một file, `tests/test_luat_cung_repo.py`, +15/−2: thêm `--no-index`
vào `_bi_ignore` cộng một docstring nói vì sao cờ ấy không phải trang trí.
Không assertion nào bị hạ, không đường dẫn nào bị bỏ khỏi danh sách kiểm,
không file cài đặt nào bị chạm. Đây là **TEST SAI đã sửa đúng**, không phải nới lỏng.

Tôi không nhận lời, tôi đo lại từ đầu ở worktree sạch tại `7a08fc1`:

```
nguyên trạng:                       Ran 4 tests  OK
đột biến A (nhét tests/network_guard.py — file ĐANG THEO DÕI — vào .gitignore):
    trước 7a08fc1:  FAILED (failures=1)   bài 3 in "ok"
    tại   7a08fc1:  FAILED (failures=2)   bài 3 FAIL, bài 4 FAIL
đột biến B (trả dấu sao về "data/state.json"):
    FAILED (failures=4) — và -v cho thấy đúng 4 subtest của MỘT bài
    (.bak, .bak-20260101, .tmp, .1), ba bài kia vẫn "ok".  Không bắn quá tay.
```

Đột biến B chỉ đánh thức đúng bài phải thức, nên `--no-index` không biến bài
thành cái chuông kêu bừa.

**Mép còn lại, lane đã ghi và tôi xác nhận là còn:** bài 3 hỏi một danh sách
cố định bốn đường dẫn. File **chưa** được theo dõi mà bị mẫu mới nuốt thì
`git add -A` bỏ qua không tiếng động và không bài nào kêu —
`test_khong_file_nao_dang_theo_doi_bi_chinh_gitignore_nuot` dùng
`git ls-files --cached`, chỉ nhìn file đã vào index. Đóng cho đủ thì phải quét
cả cây làm việc; đó là một lượt việc, không phải một dòng. Để ở **Nên sửa**,
không chặn.

### `e435a80` — vá đúng, nhưng một trong bốn bài mới là bài chết

`.gitignore` gộp hai dòng thành `data/state.json*`: đúng chữ điều 3, và tôi đo
là không quét rộng quá tay. Bài mới `tests/test_luat_cung_repo.py` canh chiều
commit — ý đúng, và ba trong bốn bài cắn thật. **Bài thứ ba thì không thể đỏ.**

`_bi_ignore()` gọi `git check-ignore -q -- <path>`. Mà `git check-ignore`
**mặc định bỏ qua file đang được theo dõi**: file đã nằm trong index thì nó
luôn trả "không bị ignore", bất kể `.gitignore` viết gì. Cả bốn đường dẫn
trong `test_khong_quet_rong_qua_tay` — `data/account_book.json`,
`data/sku_book.json`, `tests/network_guard.py`,
`automation_center/src/worker.js` — **đều đang được theo dõi**. Nên bốn
`assertFalse` ấy luôn đúng, và bài không kiểm được gì.

Đo, không suy luận. Thêm `tests/network_guard.py` vào `.gitignore` ở worktree
sạch — đúng thứ bài này sinh ra để bắt:

```
$ git check-ignore -q -- tests/network_guard.py            → báo KHÔNG ignore
$ git check-ignore -q --no-index -- tests/network_guard.py → báo BỊ IGNORE

đột biến, bản đang có:              FAILED (failures=1)   ← chỉ bài 4 đỏ, bài 3 "ok"
đột biến, thêm --no-index:          FAILED (failures=2)   ← bài 3 đỏ đúng
không đột biến, thêm --no-index:    OK
```

Lưới an toàn **không thủng**, vì `test_khong_file_nao_dang_theo_doi_bi_chinh_gitignore_nuot`
(dùng `git ls-files --cached --ignored --exclude-standard`, có `--exclude-standard`
nên không rỗng giả) vẫn bắt được đúng ca ấy. Nhưng bài 3 đang cho một niềm tin
không có thật, và nó sẽ im cả trong ca nguy hiểm hơn: một file **chưa** được
theo dõi bị mẫu mới nuốt, `git add -A` bỏ qua im lặng, không ai biết.

**Loại: TEST YẾU TỪ LÚC SINH, không phải test bị làm yếu** — nên là việc phải
làm, không phải chỗ chặn. Cách đóng là một từ: thêm `--no-index` vào
`_bi_ignore`. Đã đo: bản nguyên trạng vẫn xanh với `--no-index`, nên không có
tác dụng phụ. Sửa file test thì phải qua đúng cửa như `fba4c47` và `777df54`.

Ngoài chỗ đó, `e435a80` chỉ siết: `.gitignore` +6/−2 (gộp hai dòng thành một
mẫu rộng hơn), không mẫu nào bị bỏ, và `data/` chỉ đang theo dõi
`account_book.json`, `sku_book.json` cùng ba `.gitkeep` — không cái nào bắt
đầu bằng `state.json`.

## Phán quyết `fba4c47` — **TEST SAI đã sửa đúng, KHÔNG phải nới lỏng**

Một commit sửa file test được khai báo trước cho tôi. Vì "test bị nới lỏng" là
mức CHẶN trong chính khuôn báo cáo này, tôi kiểm lại từ đầu chứ không đọc
commit message thay cho code. Năm phép kiểm, năm câu trả lời.

**1. Bài có đỏ bằng mọi giá trước khi sửa không? — Có, và đây là bằng chứng.**
`fba4c47` chỉ chạm đúng một file test (`git diff 470b64c fba4c47 --stat`: 1
file), nên chạy bài **cũ** ở commit cha `470b64c` là chạy nó với **cùng** một
Worker:

```
not ok 1 - trả đúng những id ở trạng thái cuối
  failureType: 'testCodeFailure'
  error: 'Body is unusable: Body has already been read'
  name: 'TypeError'
  stack: _Response.json (…) → orphan_branch_cleanup.test.mjs:106:33
```

Chú ý loại lỗi: `TypeError` / `testCodeFailure`, **không** phải
`AssertionError`. Bài chết ở dòng 106 trước khi tới bất kỳ vị từ nào. Không bản
Worker nào — đúng hay sai — đi qua được. Đây đúng nghĩa TEST SAI: bài ghim vào
một lỗi của chính nó, không đo gì về hệ thống.

**2. Có vị từ nào bị đổi không? — Không, một chữ cũng không.**
`assert.equal(response.status, 200, …)`, `assert.ok(Array.isArray(body.finished),
…)` và `assert.deepEqual` trên danh sách id đã sort: giống hệt từng byte. Diff
đúng ba dòng code (`raw = await response.text()` · `assert.equal(…, raw)` ·
`JSON.parse(raw)`) và bốn dòng chú thích. Đối số thông báo vẫn là thân
response, nên câu lỗi không nghèo đi.

**3. Chặt hơn hay lỏng hơn? — Chặt hơn, và đo được.** Hai vị từ sau (`assert.ok`
và `assert.deepEqual`) trước đây **không bao giờ chạy**. Nay chạy. Đột biến
Worker năm cách rồi chạy lại đúng thân bài ấy — không sửa file nào của repo,
`worker.js` được đọc ra chuỗi, thay chuỗi, ghi sang `/tmp` rồi import:

| Đột biến | Bài sau khi sửa |
|---|---|
| không đột biến (bản như giao) | XANH |
| coi `approved` cũng là trạng thái cuối | **ĐỎ** (`deepEqual`) |
| luôn trả mảng rỗng | **ĐỎ** (`deepEqual`) |
| bỏ lọc trạng thái cuối | **ĐỎ** |
| bỏ lọc `runner_key` | **ĐỎ** |

Bài cũ đỏ trước cả năm cột — kể cả cột "không đột biến" — nên không phân biệt
được cột nào với cột nào. Đó là định nghĩa của một bài không đo gì.

**4. Điểm 4 của bạn — Worker vốn đã đúng? — Đúng, và tôi kiểm độc lập.**
Không dùng bài test của lane. Tôi tự dựng D1 in-memory từ `migrations/`, tự
tính tập kỳ vọng **từ SQLite** (không import `CODE_REQUEST_TERMINAL_STATUSES`
của `worker.js`), thêm một runner thứ hai mà bài test không có, rồi hỏi 23 câu.
Kết quả: 23/23 như mong đợi.

| Câu hỏi | Kết quả |
|---|---|
| hỏi cả 22 id của hai runner → trả đúng 6 id cuối **của mình** | ĐÚNG |
| không rò yêu cầu của runner khác | ĐÚNG |
| không trả trạng thái chưa kết thúc | ĐÚNG |
| không trả id mình không hỏi | ĐÚNG |
| sai bí mật runner → 401 · thiếu header → 401 | ĐÚNG |
| thiếu `runner_key` → 400, **không** trả tất cả | ĐÚNG |
| `ids: []` → `{finished: []}`, không phải "tất cả" | ĐÚNG |
| `ids` là `null` / chuỗi / số / object → không nổ, không trả tất cả | ĐÚNG |
| id thứ 220 bị cắt theo trần 200 | ĐÚNG |
| id/nhánh hình dạng `' OR 1=1 --` → không rò hàng nào | ĐÚNG |
| endpoint chỉ ĐỌC — không hàng nào đổi sau khi hỏi | ĐÚNG |
| đường `branches` (B3.3, `470b64c`): lọc đúng, không rò runner khác, `OR` có ngoặc đúng, cắt trần 200 | ĐÚNG |

Nên bài B3.2 nay xanh **vì Worker đúng**, không vì bài đã bị làm cho dễ. Và
điểm 4 của bạn là điểm đáng giá nhất trong commit ấy: một bài TEST SAI đếm
chung với LỖI CODE thì lane bị điều đi sửa thứ đã đúng.

**5. Phép quét của bạn — đúng kết luận, thiếu số.** Tôi không quét "chỗ nào gọi
`await response.text()` trong đối số thông báo" (đó chỉ là *một* hình dạng của
lỗi), tôi quét bất biến thật: **một thân response bị tiêu hai lần trong cùng một
khối**. Quét cả **19** file `*.test.mjs`, bỏ chú thích trước khi quét, cắt scope
theo `test(`/`function`, và xoá lịch sử biến khi nó được khai báo lại:

```
19 file · 15 chỗ tiêu thân · 0 chỗ tiêu hai lần
```

Chỗ nằm trong đối số thông báo: **9**, không phải 5 — bạn đếm thiếu 4
(`chat_gate.test.mjs:112,241`, `code_request_quota.test.mjs:159`,
`orphan_branch_cleanup.test.mjs:152,167` dùng `.json()` chứ không `.text()`).
Nhưng kết luận của bạn không đổi: không chỗ nào trong 9 chỗ đọc thân lần thứ
hai, nên cả 9 vô hại. Một chỗ trông giống bẫy đã kiểm bằng tay:
`code_scope_covering_glob.test.mjs` đọc `await response.text()` ở dòng 122
**và** ở dòng 135 — hai `test()` khác nhau, mỗi bài một `const response` riêng.
Không phải bẫy. **Bạn không bỏ sót chỗ nào.**

Kết luận: `fba4c47` là **TEST SAI đã sửa đúng**. Không revert. Để bài ấy đỏ
mới là cái sai — nó sẽ là một dòng "tồn đọng" ghim vào một lỗi không tồn tại,
và lane B sẽ mất một lượt đi sửa `runnerFinishedCodeRequests` đang đúng.

## Chưa chắc

Cần một phép đo hoặc một câu trả lời của người, không tự kiểm được từ code.

1. **A8 có gỡ luôn đường đăng nhập của CLI không?** `_looks_like_a_secret`
   khớp `API_?KEY|TOKEN|…` nên `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` bị bỏ.
   Docstring nói `claude`/`codex` đăng nhập bằng hồ sơ trong `HOME`/`APPDATA`.
   Nếu máy trung tâm `100.75.125.80` đang đăng nhập bằng **env var** thì A8
   làm bot câm, và triệu chứng chỉ là một câu lỗi CLI. Cần một lượt
   `_guess_harder` chạy thật trên máy ấy.
2. **`comment_author` xếp `owner` trước `email`.** Nếu có đường đọc thẻ nào
   trả **tên hiển thị** ở `owner` thay vì email, người *có* trong danh sách
   vẫn bị từ chối — và vì C3.3 buộc im lặng, dấu hiệu duy nhất là một dòng
   log. Cần một payload bình luận thật từ ERP để chốt hình dạng.
3. **`timeout_s` 120 → 45 (A9.4).** Lập luận "5 lượt tuần tự" hợp lý, nhưng
   chưa thấy phép đo thời gian trả lời thật của CLI trên máy trung tâm. Nếu
   p95 vượt 45s thì đổi này biến câu trả lời chậm thành câu không có.
4. **B2 không thu hồi phạm vi đã cấp.** `saveCodeScope` nay chặn cả glob bao
   trùm `PROTECTED_GLOBS`, nhưng chú thích nói rõ "phạm vi đang lưu không bị
   thu hồi tự động". Nếu D1 production **đang** có một phạm vi bao trùm thì lỗ
   ấy còn nguyên tới lần lưu lại. Cần một câu `SELECT` do **người** chạy (tôi
   không đọc D1 production). Nếu có, nên có một migration hoặc một lượt duyệt
   tay.

## Tồn đọng

**Còn đúng một bài đỏ, và nó không phải mục chưa cài.** B4 đã đóng ở
`777df54` — và đóng bằng cách sửa bài test, vì cài đặt vốn đã đúng từ
`306df94`; xem phán quyết bên dưới, kèm chỗ báo cáo này từng đọc sai. Bài đỏ
duy nhất còn lại là B3.1 (`orphan_branch_cleanup`), **TEST SAI đang chờ người
chốt hợp đồng**, không phải việc chưa làm.

B1 (`watchdog_budget`), B2 (`code_scope_covering_glob`), B5
(`code_request_quota`) xanh ở `589e89a`; B3.2 xanh ở `fba4c47` (xem phán
quyết ở trên); B3.3 xanh ở `470b64c`.

**B3.1 — phân xử ba câu, sau khi đo lại.** Bài node còn đỏ **là TEST SAI**
(ghim vị trí văn bản, không ghim hành vi). Nhưng chuyện không dừng ở đó: hai
bài đá nhau chỉ là bề mặt, bên dưới là **PRD đá vào một hợp đồng đang xanh
trên `main`**.

*Câu 1 — bài node: TEST SAI.* `orphan_branch_cleanup.test.mjs:208` là regex
quét thân `apply_approved`, đòi lời gọi xoá phải nằm trong `except`/`finally`.
Nó **ghim chỗ**. Ý của nó thì đúng với PRD, nên đường ra là **viết lại thành
bài hành vi**, không phải xoá và không phải hạ regex.

*Câu 2 — không, `127f10e` không lật ngược cái gì cả.* Tôi đo bằng probe ở ba
worktree ghim commit (`306df94`, `fba4c47`, `127f10e`): nạp runner thật, giả
`git`/`report`/`center_request`, gieo `HELD_BRANCHES` đúng như dòng
`finally` của `handle_request` (`:1332`) vẫn gieo, cho merge ném lỗi, rồi chạy
một vòng `drop_finished_branches`.

| commit | runner chạy liên tục | runner vừa khởi động lại |
|---|---|---|
| `306df94` | **nhánh bị xoá ở vòng poll kế tiếp** | không xoá ở poll (nhưng `sweep_stale_branches` xoá ở lần khởi động sau — đã đo, `failed` → xoá) |
| `fba4c47` | **nhánh bị xoá** | như trên |
| `127f10e` | **nhánh bị xoá** | **nhánh bị xoá** |

Nghĩa là hành vi "merge hỏng thì nhánh biến mất vài giây sau" **đã có từ
`306df94`**, tức từ chính B3.2, chứ không phải `127f10e` đẻ ra. `127f10e` chỉ
phủ nốt ca khởi động lại — ca mà lưới B3.3 đã bắt được, chậm hơn một lần khởi
động. Vậy `127f10e` **không** là hồi quy về hành vi.

Cái sai thật nằm ở chỗ khác. PRD (`tasks/prd-agent-improvements.md:539-542`)
liệt kê **"Merge hỏng lúc apply — không `branch -D`"** là chỗ rò **số 1** phải
vá, và B3.2 (`:565-573`) viết thẳng `failed` vào danh sách trạng thái cuối
được `branch -D`. Trong khi đó `test_merge_hong_thi_giu_nhanh_lai_de_con_xem`
có từ `f491d3f` — **đã nằm trên `main`**, không phải bài ai đó viết trong đợt
này để hợp thức hoá chỗ rò. Người viết PRD gọi chỗ rò số 1 mà không thấy trên
`main` đang có một bài xanh đòi đúng chỗ rò ấy.

Nên: **tên bài python bây giờ nói dối.** "giữ nhánh lại để còn xem" hứa một
đảm bảo hệ thống không còn cung cấp — nhánh sống đúng tới hết vòng poll ấy.
Một bài xanh mà tên nó sai còn tệ hơn một bài đỏ. Nhưng nó nói dối **từ
`306df94`**, không phải từ `127f10e`.

*Câu 3 — không CHẶN.* Việc của lượt model **không mất**. Đường
`status === "failed"` của runner (`worker.js:1899-1901`) chỉ `UPDATE` ba cột
`plan_summary, test_output, error` — **không đụng `diff_text`, không đụng
`branch`**. Diff lưu lúc `awaiting_approval` (`:2020`) còn nguyên trên Center
và đọc được ở `/api/code/requests/:id` (`:1515`). Thêm nữa, commit vẫn nằm
trong reflog của `HEAD` vì runner đã checkout và commit trên nhánh đó. Không
phải "mất dữ liệu không hoàn tác được", nên không đạt ngưỡng CHẶN.

Còn đúng **một** ca mất thật, và nó hẹp: diff dài hơn `DIFF_LIMIT = 60000`
(`orchestrator_runner.py:102`, Worker cắt lại ở `DIFF_TEXT_MAX = 60000`,
`worker.js:232`) thì bản trên Center **thiếu đuôi** — cờ `diff_truncated = 1`
nói đúng điều đó. Merge hỏng + diff bị cắt + `branch -D` ⇒ bản đầy đủ chỉ còn
trong reflog, hết hạn theo mặc định git (~30 ngày cho commit không ai với
tới). Đây là **việc phải có người nhận**, không phải chặn phát hành.

*Tôi rút lại khuyến nghị (b) ở tin nhắn trước.* Tôi từng nghiêng về "thêm
`branch -D` vào `except`". Sai: làm thế **biến một bài đang xanh trên `main`
thành đỏ** — đúng điều luật CHẶN của chính báo cáo này cấm. Thứ tự đúng:

1. **Người chốt hợp đồng trước, code sau.** PRD nói xoá; `main` nói giữ. Đọc
   theo PRD thì bên xoá thắng (B3.2 viết rõ chữ `failed`), nhưng đây là quyết
   định sản phẩm, không phải quyết định của người soát.
2. Nếu bên xoá thắng: sửa **tên và assertion** bài python cho khớp hợp đồng
   thật ("merge hỏng thì nhánh còn tới hết vòng poll ấy rồi bị xoá"), và viết
   lại bài node thành bài hành vi. Cả hai đều là sửa file test ⇒ phải khai
   trước và người khác soát, đúng đường `fba4c47` đã đi.
3. Nếu "để còn xem" thắng: bỏ `failed` khỏi danh sách xoá của B3.2 — đó là sửa
   code, và PRD phải sửa theo.

Khai trong mô tả pull request dưới dạng **tồn đọng có lý do**, không phải
"chặn còn mở".

**MÔI TRƯỜNG, có sẵn từ trước, không thuộc đợt A.**
`_bmad/core/bmad-distillator/scripts/tests/test_analyze_sources.py` `import
pytest`, mà `.venv` không có `pytest` và repo dùng `unittest`. 1 error. Dựng
lại bằng `unittest`, hoặc cài `pytest` và nói rõ trong CLAUDE.md. Không phải
lỗi code, không chặn.

**Đã đóng trong lúc soát, ghi để có vết.** `665f45c` làm `test_docs_commands`
đỏ 3 subtest (regex `node\s+--test[^\n`|]*` dừng ở backtick, nên câu *cảnh báo
về* lệnh hỏng bị đọc thành lệnh). `b0872dd` đã sửa; bộ 2 nay 85/85 xanh.

## Ngoài phạm vi — B chưa được soát đủ

Đợt A là phạm vi được giao. Ba commit của lane-orch-opus (`589e89a`,
`306df94`) landing giữa lượt này, và tôi **chỉ** soát chúng theo hướng
quyền/bí mật vì đó là loại chặn:

- `saveCodeScope` chặn glob bao trùm thay vì chỉ glob trùng khít — **siết**,
  không nới. Xem "Chưa chắc" #4 về phạm vi đã cấp.
- `runnerFinishedCodeRequests` đi qua **hai** cửa: `handleRunnerApi` chặn mọi
  route runner bằng `runnerRequestAuthorized` → 401 (đo thật: sai bí mật và
  thiếu header đều 401), rồi câu SQL lọc `WHERE runner_key = ?`. Tham số đều
  bind, không nối chuỗi. Chỉ trả `{id, status, branch}` của chính runner hỏi.
  Không nới quyền. (Bản trước của báo cáo này chỉ nói tới cửa thứ hai — thiếu,
  nay sửa.)
- Trần lệnh bot: Worker nay **từ chối ồn ào** khi vượt trần thay vì `slice(0, 5)`
  im lặng. Siết, và đúng hướng.
- Runner in `token: prompt … completion …` (số, không phải khoá) và
  `RUNNER_KEY` chỉ nằm trong body POST, không vào log.
- Một chỗ đáng hỏi, không tự kiểm được từ code: `branch -D` xoá nhánh của yêu
  cầu ở trạng thái cuối, **kể cả `rejected`** — commit trên nhánh ấy mất khỏi
  cây làm việc (reflog còn ~90 ngày, và diff đã lưu trong D1). Nếu ai đang
  dùng nhánh `agent/*` để xem lại thay đổi bị từ chối thì cần nói ra.

**Phần logic của B (ngân sách watchdog, hạn ngạch, dọn nhánh) cần một lượt
soát riêng.** Đừng đọc mục này thành "B đã được soát".

## Lệnh đã chạy

```bash
# đo ở worktree sạch tại commit cố định, không đo ở cây làm việc đang chạy
git worktree add /tmp/wt-hd 7f86a38 --detach
git worktree add /tmp/wt-e33 e337966 --detach
git worktree add /tmp/wt-b8 b8b7068 --detach
git worktree add /tmp/wt-main main --detach

.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
(cd automation_center && ../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')
node --test --experimental-sqlite automation_center/tests/*.test.mjs
(cd _bmad/core/bmad-init/scripts && ../../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')
(cd _bmad/core/bmad-distillator/scripts && ../../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')
```

Thêm ba phép đo tự viết, không sửa file nào của repo:

- `/tmp/mut_a6.py` — patch `_erp_review_scope → None` lúc chạy để xem bộ test
  A6 có bắt được "đăng tất cả" không (bắt được: `1 != 3`, `2 != 0`).
- `/tmp/probe_guard.py` — 10 đường thử lách chốt mạng (bảng ở trên).
- `/tmp/netguard_all.py` — chạy toàn bộ 1 tại `e337966` dưới một chốt socket
  ngoài, để biết trước chốt thật có làm bài nào đỏ không (không bài nào).
- `/tmp/probe_finished.mjs`, `/tmp/probe_branches.mjs` — 23 câu hỏi độc lập cho
  `/api/runner/code/finished`, kỳ vọng tính từ SQLite chứ không từ `worker.js`.
- `/tmp/mut_finished.mjs`, `/tmp/mut_iso.mjs` — đột biến `worker.js` (đọc ra
  chuỗi, thay, ghi sang `/tmp`, import) để đo bài B3.2 có răng tới đâu.
- `/tmp/sweep_body2.mjs` — quét 19 file test node tìm thân response bị tiêu hai
  lần.

Worktree tạm dọn bằng `git worktree remove`. Lượt soát này không sửa file cài
đặt nào; chỗ duy nhất được ghi là chính file này.

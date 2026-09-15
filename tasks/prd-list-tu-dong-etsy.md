# PRD — Đường list tự động lên Etsy

Mục tiêu người dùng đặt: một thẻ ERP khai `action_1: listing`, người bấm 👍
lên ảnh xong, thẻ **tự** được giao cho bản Listing rồi **tự** sang cột
*Hoàn thành*. Không có bước tay nào ở giữa.

Hồ sơ khảo sát gốc: `ho-so-khao-sat-listing.md` trong scratchpad của phiên
khảo sát (ngoài repo; A1–A13, C T1–T6, D2.1–D2.12, E). PRD này đã đối chiếu
lại từng khẳng định với code; chỗ nào không kiểm được trên máy này thì ghi
**chưa kiểm chứng**.

**Mốc số dòng.** Mọi `file:line` trong PRD tính theo HEAD `3bacaa2` (nhánh
`agent/prd-agent-improvements-tdd`). Bản đầu của PRD tính theo `0804eaf`; từ
đó đến `3bacaa2` có bốn commit cài đợt 1–3 (`538c09e`, `0592d64`, `9faad99`,
`56b2543`) và một commit runbook (`3bacaa2`). `flow_web/service.py` ở HEAD
**bằng** `0804eaf` (không commit nào đụng nó); bản trong worktree đang bị một
agent khác sửa dở nên số dòng lệch — kiểm bằng
`git show 3bacaa2:flow_web/service.py | sed -n '12834,12841p'`. Số dòng
`tests/test_agent_bot.py` tính theo worktree **sau** khi PRD này thêm test
(file ấy chỉ có prd-writer ghi).

## 0. Kết luận đọc trước

Đường list đứng ở **năm** chỗ: ba chỗ ở phía repo này (1–3), hai chỗ ở bản
Listing (4–5). Đợt 1–3 (T1–T7) đã cài và sửa được **hai** trong ba chỗ đầu.
Đợt 4 (T8–T15, PRD này) vá những chỗ hội đồng tìm ra sau khi cài.

| # | Chỗ đứng | Bằng chứng | Trạng thái |
|---|---|---|---|
| 1 | Bot chỉ xét **thẻ gốc** cho nửa listing, trong khi ảnh và 👍 nằm ở **thẻ con** | fan-out ghi ảnh vào con `service.py:4245` `erp_output_task_id=child_id`; con tạo trắng `:3956` | **Đã cài** ở `56b2543`: `listing_pass` duyệt cả cây (`agent_bot.py:3024-3061`), con mượn khối cha qua `inherited_meta_node` (`:1003-1052`), giao từng con ở `_listing_one` (`:3063-3125`). Còn bốn lỗ: T8, T9, T10, T11. |
| 2 | Thẻ con **không có** `action_1: listing`, nên app từ chối đóng nó | cổng đóng `service.py:15085` `if status == COMPLETED and not task_meta(detail).is_listing: return False`; `_erp_pipeline_stage` `:15110` dựng `card_stage` từ meta của chính thẻ con | **Ngoài phạm vi** — chỉ sửa được ở `service.py` (vùng cấm). Q1. Hệ quả phụ (đề nghị Done lặp mỗi lượt) vá ở T12. |
| 3 | Bản chạy rời không nối đường **hỏi lại** bản Listing | `scripts/run_agent_bot.py` | **Đã cài** ở `9faad99`: `:70` import, `:299` `listing_confirm_hook=build_listing_confirm_hook(listing)`. |
| 4 | **Chặng cuối không có thợ**: hàng đợi browser-copy bên bản Listing không ai rút | `service.py:12760` xếp vào bộ nhớ, chỉ `POST /api/extension/etsy-browser-copy/next` rút ra; soi 10/09/2026 lúc 14:18: `queued:0, latest:null`, `/api/etsy/machines` `online_count:0` | **Đã có thợ, ngoài repo này** (10/09/2026). Agent máy Etsy 2.11.1 rút hàng đợi ERP; chạy thử 15:10 và 15:16 hai máy nhận việc và báo lại. Bản ghi: `docs/listing2-agent-2.11.1/`. Chưa có bản nháp thật — xem chỗ đứng 5. |
| 5 | **Cửa vào còn đóng**: `enqueue` của controller :8001 chỉ dựng việc từ thẻ Trello | `prepare_etsy_browser_copy` cần khoá Trello và `trello_card_id`, bỏ qua mọi trường `erp_*`; gọi `prepare` với đúng hình payload của cầu trả `configured=False, missing=trello_credentials` (10/09/2026 15:2x) | **Chưa làm.** Đường đề xuất: cầu gọi `enqueue-direct`, flow-v2 thả ảnh 👍 vào thư mục downloads của controller, thẻ khai listing mẫu. Sửa `listing_bridge.py`, `erp_meta.py` trong repo này. Chi tiết: mục "Cửa vào còn đóng" trong `docs/bat-listing-etsy.md`. |

Tín hiệu thật sau khi cài (đọc kỹ, đây là chỗ bản đầu PRD nói sai): khi thẻ
con đã `confirmed`, bot **đề nghị** Done và app **từ chối**. Dấu vết của lượt
từ chối ấy **không** phải câu ở `service.py:15092` — dòng đó nằm trong
`if job_id:` (`:15089`) mà `_agent_bot_pipeline` gọi
`advance_erp_pipeline(task_id)` không có `job_id` (`:22738-22744`); hơn nữa
`_erp_pipeline_stage` đọc meta riêng của con nên `_leave_review` đã trả
`Move("", "chờ người làm listing")` (`pipeline.py:345`) trước khi tới cổng
`service.py:15085`. Tín hiệu thật là **dòng log của bot**
`Agent bot đẩy N thẻ sang cột kế — <mã con> chờ người làm listing.`
(`agent_bot.py:3332-3333`, in `result.next_column or result.reason`) và trường
`moved[].result.reason == "chờ người làm listing"` trong JSON tóm tắt
(`advance_erp_pipeline` trả `{"moved": False, "reason": …}`, `service.py:15206`,
`:15209`). Thấy dòng đó là **đợt này đã chạy hết phần của nó**.

Chỗ đứng 4 soi ra ngày 10/09/2026: bên kia hàng đợi **không có ai đứng đợi**. Doanh nghiệp chọn gắn thợ vào hàng đợi, không đẩy thẻ ERP sang đường Trello. Cùng ngày, agent máy Etsy 2.11.1 lên 7/8 máy (`etsy-vn32` bị giữ ở 2.10.71) và hai lượt chạy thử đi trọn nửa sau. Việc nằm ngoài repo, bản ghi ở `docs/listing2-agent-2.11.1/`.

Soi tiếp thì ra chỗ đứng 5, và đây giờ là chỗ đắt nhất. Cầu gửi `erp_task_id` vì tưởng `enqueue` bên kia đọc thẳng thẻ ERP. Chỉ instance ERP Trial (:8010, đang tắt) làm vậy; controller :8001 thì không. Nên nửa ERP chọn đúng thẻ, tra đúng máy, bên kia có thợ đứng đợi, mà thẻ vẫn không vào được hàng. Bot sẽ ghi `Bản Listing chưa cấu hình xong: thiếu trello_credentials.` và không ghi sổ — hỏng an toàn, không có bản nháp sai.

## 1. Phạm vi

### Trong phạm vi

File được sửa: `flow_web/agent_bot.py`, `flow_web/erp_meta.py`,
`flow_web/listing_bridge.py`, `flow_web/pipeline.py`,
`flow_web/account_book.py`, `scripts/run_agent_bot.py`,
`tests/test_agent_bot.py`, `tests/test_erp_meta.py`,
`tests/test_run_agent_bot.py`, `tests/test_listing_bridge.py`,
`tests/test_pipeline.py`, `.env.local.example`, `docs/`.

Đã cài (đợt 1–3, giữ nguyên làm nền):

- T1 — nửa listing chạy ở **độ sâu thẻ con**, thừa kế khối cha (`56b2543`).
- T2 — bản chạy rời nối `listing_confirm_hook` (`9faad99`).
- T3 — chỉ tệp **ảnh** mới là "ảnh chờ duyệt" (`56b2543`).
- T4 — `normalize_action` bỏ dấu tiếng Việt và dấu ngoặc (`56b2543`).
- T5 — bot tắt thì `run_forever` nói vì sao; `.env.local.example` thêm biến; runbook `docs/bat-listing-etsy.md` (`0592d64`, `56b2543`, `3bacaa2`).
- T6 — thẻ đã giao đi không rơi khỏi tầm quét (`_listing_stragglers`, `agent_bot.py:1606-1640`).
- T7 — gốc đứng một mình đã giao đi không bị chạy ảnh lại (`agent_bot.py:2644-2649`).

Đợt 4 (PRD này):

- T8 — thẻ con chưa có `sku:` của riêng nó thì **chưa giao**.
- T9 — nhãn tài khoản của cha (`_labels: [acc32]`) xuống con thành dòng `acc:` trong bản sao.
- T10 — chỉ dòng **định tuyến** của cha xuống con; `sku`/`template` của cha không rò.
- T11 — cây **có con** không đóng băng nửa làm ảnh sau khi con đã listed.
- T12 — đề nghị Done bị từ chối thì không lặp lại mỗi lượt.
- T13 — `build_agent_bot` trả `None` phải nói tên `ERP_AGENT_TOKEN` (đường app).
- T14 — T3.3 viết lại đúng luật đã cài; fixture PDF đúng hình dạng người thật; bài gọi tên luật.
- T15 — URL đính kèm **không có đuôi** vẫn là ảnh, khớp docstring `has_image_attachment`.

Câu chốt đích của payload (để không ai truyền nhầm mã cha):
`erp_task_id = erp_source_task_id = **mã thẻ con**` (`listing_bridge.py:265-266`,
`task_id` là nút đang xét trong `_listing_one` `agent_bot.py:3071`), `title` = subject của
con (`listing_bridge.py:242`), ảnh là các bình luận 👍 trên con. Bài chốt:
`tests/test_agent_bot.py::ListingChildCardTests` (:3089) assert hook nhận
`["TASK-P-a"]`, sổ ghi con không ghi cha.

### Ngoài phạm vi đợt này (và vì sao)

| Mục | Vì sao ngoài | Ở đâu |
|---|---|---|
| N1 — Thẻ con mang dòng định tuyến của cha ngay lúc fan-out | Chỉ `service.py` tạo thẻ con (`_erp_create_child_task` `:14892`, gọi ở `:3943`) và chỉ nó có `_erp_update_task_meta` `:13893`. Vùng cấm. | `service.py` — Q1 |
| N2 — Cổng đóng `:15085` và `_erp_pipeline_stage` `:15110` đọc meta **thừa kế** | Cùng file. Cách thay thế cho N1. T12 chỉ làm đề nghị bị từ chối **bớt lặp**, không mở được cổng. | `service.py` — Q1 |
| N3 — `_erp_listing_recorded` `:15129` đọc sổ qua `getattr(self, "_agent_bot")` | Cùng file. Sổ đã ghi đúng mã con (T1). | `service.py` |
| N4 — Cache bridge/sổ tài khoản trong `agent_bot()` `:22627-22683` | Cùng file. | `service.py` |
| N5 — Chạy thật lên Etsy từ máy này | Máy này không có `.env.local`; bản Listing ở `ERP_LISTING_API_URL` nằm ngoài repo. §5. | hvg-pc |
| N6 — Nút *publish* sau bản nháp (`etsy_publish: False`, `listing_bridge.py:289`) | Không đổi. Bản nháp là đích. | — |
| N7 — `IMAGE_SUFFIXES` thêm `.heic`/`.avif`/`.bmp` | App không sinh (`service.py:13224-13226` ép về `.jpg`), nhưng người dán từ điện thoại có thể. Đổi hằng là đổi cả `count_card_images` `:872`. Cần người quyết — Q6. | `agent_bot.py:676` |

### Ràng buộc bắt buộc

1. Không sửa `flow_web/service.py`, `tests/test_flow_web_smoke.py`,
   `flow_web/store.py`, `flow_web/schemas.py`. Đọc để lấy bằng chứng thì được.
2. Hai bài **phải còn xanh**, vì chúng tả hai ranh giới sản phẩm chứ không tả lỗi.
   Lý do xanh ghi theo code **đã cài**, không theo thiết kế cũ:
   - `tests/test_agent_bot.py:1415` `test_a_listing_card_with_no_images_yet_goes_through_the_image_half`.
     Cây: gốc `TASK-L` khai listing, con `TASK-L-a` trắng (`:1418`). Con trắng
     **kế thừa** `action_1` của cha (`inherited_meta_node` `agent_bot.py:1003-1052`, luật
     `erp_meta.inherit` `erp_meta.py:469-487`, chốt `tests/test_erp_meta.py:323-332`) nên
     **chính con** là nút listing; dòng gốc bị lược vì `has_children`
     (`agent_bot.py:3083-3087`). Con chưa có ảnh → `_listing_one` trả
     `{"task": "TASK-L-a", "waiting": "thẻ chưa có ảnh nào để đăng", "needs_images": True}`
     (`agent_bot.py:3090-3094`) → `run_once` không `continue` (`agent_bot.py:3253-3264`) → `autorun_pass`
     dùng **mã gốc** (`agent_bot.py:2955-2956`) → `calls == ["TASK-L"]`. Bài chỉ soi
     `summary["listing"][0]["waiting"]`, không soi `["task"]` (giá trị là
     `TASK-L-a`). Điều kiện xanh: **không đổi chuỗi waiting của con chưa có
     ảnh**, và `autorun_pass` vẫn nhận mã gốc. T8 không đụng vì cổng SKU đứng
     **sau** `listing_readiness` (T8.1). T11 không đụng vì cây này đã không
     `continue`.
   - `tests/test_agent_bot.py:1683` `test_without_a_confirm_hook_the_card_simply_waits_for_a_person`.
     Gốc đứng một mình, không con, không hook hỏi lại. Lượt 2:
     `already_listed` → `_listing_confirm` trả `None` vì hook `None`
     (`agent_bot.py:3002-3003`) → không dòng nào → `summaries[1]["listing"] == []`.
     T11 giữ `continue` cho gốc **không con** (T11.1) nên không autorun. T12
     không đụng: bài không nối `pipeline_hook`. T2 chỉ nối hook ở script.
3. Không nới test. Không đụng `.env.local`, `automation_center/.dev.vars`,
   `automation_center/runner/*.env`, `data/state.json*`. Không `wrangler deploy`.
4. Chữ ký `card_stage(task_node, *, cards_missing_sku, listed, is_listing=None)`
   (`agent_bot.py:1130-1136`) giữ nguyên vì `service.py:15120` gọi ba tham số cũ.
5. `inherited_meta_node` giữ tên và chữ ký `(node, root)` — `docs/bat-listing-etsy.md:255`
   và `pipeline_pass` `agent_bot.py:2866` đang gọi. T9/T10 chỉ đổi **nội dung** khối nối,
   thêm tham số có mặc định nếu cần.

## 2. Xếp hạng ưu tiên

Đợt 1–3 đã cài; giữ dòng để người đọc biết bài chốt nào canh gì.

| # | Cải tiến | Rủi ro nếu không làm | Lợi ích | Công | Test đỏ |
|---|---|---|---|---|---|
| T8 | Con chưa có `sku:` riêng thì chưa giao | **Cao** — con đủ 👍 được giao **cùng lượt** với `etsy_listing_sku=""` (`listing_bridge.py:286`), bản Listing tự đặt mã; không lần từ shop về thẻ được | Mã trên shop = mã trên thẻ | 0,25 ngày | `ListingChildSkuGateTests` |
| T9 | Nhãn `acc32` của cha xuống con | **Cao** — cha chỉ dán nhãn (cách người làm listing khai tài khoản, `listing_bridge.py:178-190`) → con không có tài khoản → máy mặc định (nhầm shop) hoặc `ListingBridgeError` | Giao đúng shop | 0,25 ngày | `ListingChildRoutingInheritanceTests` (bài 1) |
| T10 | Chỉ dòng định tuyến xuống con | **Vừa** — `sku: PARENT` của cha rò xuống con trắng → mã của cha lên shop cho sản phẩm khác | Mã là của riêng từng thẻ | 0,25 ngày | `ListingChildRoutingInheritanceTests` (bài 3, 4) |
| T11 | Cây có con không đóng băng autorun | **Vừa** — mọi con đã listed → `run_once` `continue` → idea mới thả lên **cha** không bao giờ được tách; người bấm tay | Bỏ một bước tay | 0,1 ngày | `ListingTreeAutorunTests` (bài 1) |
| T12 | Đề nghị Done không lặp | **Vừa** — mỗi 120 s một request ERP thừa + một dòng log cho **mỗi** con đã confirmed, mãi tới khi Q1 xong | Log đọc được, ERP không bị gõ thừa | 0,25 ngày | `DoneProposalThrottleTests` (bài 1) |
| T13 | `build_agent_bot` nói tên biến thiếu | **Vừa** — trên hvg-pc `watch_agent_bot` `return` khi `bot is None` (`service.py:22785-22787`); hai dòng T5.1 trong `run_forever` không bao giờ chạy | Log trống ≠ bot tắt | 0,1 ngày | `BuildAgentBotOffLogTests` |
| T15 | URL không đuôi vẫn là ảnh | **Thấp** — ERP Frappe giữ đuôi tệp; nhưng docstring hứa rộng hơn code | Hàm khớp lời hứa | 0,1 ngày | `ReviewPostAttachmentSuffixTests` (bài URL) |
| T14 | T3.3 viết lại; fixture; bài gọi tên luật | — (chỉ tài liệu + test, đã xanh) | Luật đã cài có tên | 0 | — |
| T1–T7 | đã cài | — | — | — | chốt ở §7 |

## 3. Từng mục

### 3.1 T1 — Nửa listing chạy ở độ sâu thẻ con (đã cài `56b2543`)

**Hiện trạng sau khi cài**

- `listing_pass` `agent_bot.py:3024-3061`: `for node in iter_tree_nodes(root)`; mỗi nút
  đi qua `inherited_meta_node(node, root)` `:1003-1052` rồi `is_listing_card`;
  giao ở `_listing_one(card)` `:3063-3125` với `task_id = node["name"]`, sổ
  và cooldown `listing:<task_id>` theo **con**. Gốc có con bị lược
  (`has_children` `:3083-3087`). Tên hàm thật khác đề xuất cũ (`listing_nodes`,
  `_listing_node`) — PRD theo tên đã cài.
- `inherited_meta_node` nối **nguyên** khối `raw` của cha trước khối con
  (`:929-932`), không nối `meta_auto` (nhãn). Đây là chỗ T9/T10 sửa — T9/T10
  đã cài, hàm hiện tại lọc theo khoá thay vì nối nguyên khối, không còn dòng
  nào khớp mô tả cũ để trỏ tới; giữ nguyên số cũ, coi là mô tả hiện trạng
  trước khi T9/T10 sửa.
- `card_stage` có `is_listing: Optional[bool] = None` `:1130-1136`;
  `pipeline_pass` truyền `is_listing=is_listing_card(inherited_meta_node(node, root))` `:2866`.
- Hình dạng thật: `service.py:3871-4000` fan-out từ tệp đính kèm **trên thẻ
  cha**, con tạo trắng `:3956`, ảnh ghi vào con `:4245`;
  `pipeline._leave_doing` `pipeline.py:302-325` (`:307` "mỗi thẻ idea con *là* một sản
  phẩm đi lên listing riêng").

**Hệ quả đã chấp nhận**: mọi con trắng của cha listing đều là nút listing, kể
cả con chưa có ảnh. Cây 10 con vừa fan-out → 10 dòng
`thẻ chưa có ảnh nào để đăng` mỗi lượt trong `summary["listing"]` và một dòng
log gộp `Agent bot: 10 thẻ listing — …` (`agent_bot.py:3304-3308`). **Chấp nhận, không
gộp**: mỗi dòng là một thẻ có thật; gộp là giấu thẻ. Ghi §8.

**Chốt**: `ListingChildCardTests` `tests/test_agent_bot.py:3089` (9 bài, xanh), `ListingCardTests`
`:1351-1713` toàn bộ.

### 3.2 T2 — Bản chạy rời nối `listing_confirm_hook` (đã cài `9faad99`)

- `scripts/run_agent_bot.py:70-71` import cả hai; `:294`
  `listing_hook=build_listing_hook(listing)`, `:299`
  `listing_confirm_hook=build_listing_confirm_hook(listing)`.
- `build_listing_hook` `listing_bridge.py:413-423`, `build_listing_confirm_hook`
  `:426-436`: cùng luật `if bridge is None or not bridge.enabled: return None`
  (`:415-416`, `:428-429`).
- Chốt: `tests/test_run_agent_bot.py::NoiCauHoiLaiListing` `:282` (2 bài).

### 3.3 T3 — Chỉ tệp ảnh mới là "ảnh chờ duyệt" (đã cài `56b2543`)

- `has_image_attachment` `agent_bot.py:679-714`; `is_review_post` `:717-736`;
  `is_foreign_review_post` `:794-810`; `IMAGE_SUFFIXES` `:676`.
- **T3.3 viết lại** (bản đầu ghi "không đổi điều kiện `REVIEW_PREFIX`" — sai
  so với code): *có tệp đính kèm thật thì đuôi tệp quyết định; dấu
  `[FLOW_V2_REVIEW]` chỉ là lối dự phòng khi ERP trả `attachments` rỗng*
  (`:730-736`, `:806-810`). Điều kiện tác giả (`mine`) không đổi.
- Chốt: `tests/test_agent_bot.py::ReviewPostAttachmentSuffixTests` `:3303` — fixture PDF là người thật
  (`mine=0, content=""`, `:3343`); bài gọi tên luật `:3352`. `agent_bot.py:872`
  `count_card_images` không đếm PDF.
- Lỗ còn lại → T15 (URL không đuôi) và Q6 (đuôi lạ).

### 3.4 T4 — `normalize_action` bỏ dấu và dấu ngoặc (đã cài `56b2543`)

- `normalize_action` `erp_meta.py:134`; cùng cách bỏ dấu với
  `agent_bot.compact_status` `agent_bot.py:928` và `pipeline._compact` `pipeline.py:65-74`.
- Chốt: `tests/test_erp_meta.py::ListingActionAccentSpellingTests` `tests/test_erp_meta.py:528`.

### 3.5 T5 — Bot tắt phải nói; env ví dụ đủ; runbook (đã cài, còn một lỗ → T13)

- `run_forever` `agent_bot.py:3362-3410`: `:3374` log `ERP_AGENT_TOKEN`, `:3377` log
  `ERP_AGENT_POLL_SECONDS`, rồi `:3383` "Agent bot bật".
- `.env.local.example:151` `ERP_LISTING_TIMEOUT_SECONDS=`.
- Runbook đã viết là `docs/bat-listing-etsy.md` (không phải tên
  `docs/bat-bot-listing-tren-hvg-pc.md` như bản đầu đề xuất). Nó trỏ sang
  `automation_center/docs/runner-host-runbook.md:34,74-77` (hvg-pc chạy Flow
  v2 **như app**, Scheduled Task `HaviGroup Flow v2`), không chép lại.
- Lỗ: đường app không tới `run_forever` khi thiếu token → T13.

### 3.6 T6 — Thẻ đã giao rời cột nguồn vẫn trong tầm quét (đã cài)

- `_listing_stragglers` `agent_bot.py:1809-1849`, gọi ở `candidate_tasks` `:1746`.
- Chốt: `ListedCardAfterHandoverTests` `tests/test_agent_bot.py:3444` — **bài đơn vị thuần cơ chế**:
  chỉ canh bộ lọc cột của `candidate_tasks`, hình dạng thẻ cố ý tối giản
  (gốc đứng một mình, `mine=1`, `attachment_count: 2`), ghi ngay trong bài `:3451`.

### 3.7 T7 — Gốc đứng một mình đã giao không chạy ảnh lại (đã cài)

- `run_once` `agent_bot.py:3253-3264`: `if not any(item.get("needs_images") …): continue`.
- Chốt: `ListedCardAfterHandoverTests` `tests/test_agent_bot.py:3424` và `ListingTreeAutorunTests`
  `tests/test_agent_bot.py:3723`. Phạm vi thu hẹp lại ở T11: chỉ đúng cho gốc **không con**.

### 3.8 T8 — Thẻ con chưa có `sku:` riêng thì chưa giao

**Bằng chứng**

- Thứ tự một lượt: `pipeline_pass` `agent_bot.py:2813-2940` chạy **trước** `listing_pass`
  (gọi ở `:3244`, `listing_pass` gọi ở `:3251`). `pipeline_pass` đẩy con *Cần làm* → *Đang làm* khi đủ
  phiếu; `advance_erp_pipeline` chỉ điền SKU khi thẻ **đã** ở *Đang làm* và
  "một bước mỗi lượt gọi, cố ý" (`service.py:15146`, `:15157`).
- Cùng lượt, `_listing_one` thấy `listing_readiness` `agent_bot.py:3089` đủ → giao
  (`:3115`) với `etsy_listing_sku = meta.sku` (`listing_bridge.py:286`) rỗng.
- Bộ test cũ `ListingChildCardTests` gán sẵn `meta="sku: KT-0001"` cho con
  nên xanh mà che lỗi.

**Yêu cầu**

- T8.1 `listing_pass` truyền cho `_listing_one` một cờ `child = node is not root`
  (thêm tham số có mặc định `False`). Trong `_listing_one`, **sau**
  `listing_readiness` và **trước** kiểm `listing_hook`: nếu `child` và
  `task_meta(<khối riêng của con>).sku == ""` → trả
  `{"task": task_id, "waiting": "chờ máy điền SKU"}`, **không** có
  `needs_images`. Đọc SKU từ khối **riêng** của con (không phải khối đã nối)
  để không phụ thuộc thứ tự cài T10.
- T8.2 Gốc đứng một mình (`child=False`) giữ nguyên: `ListingCardTests`
  `LISTING_META` `tests/test_agent_bot.py:1361` không có `sku`.

**Không làm**: không gọi `sku_hook` từ `_listing_one`; việc điền mã là của
`advance_erp_pipeline`. Không đổi `listing_readiness`.

**Tiêu chí nghiệm thu**: con *Cần làm*, 2 👍, `meta=""` → `listing_hook` không
được gọi; `summary["listing"]` có dòng `TASK-P-a` với `"SKU"` trong `waiting`
và `needs_images` falsy. Lượt sau con có `sku: KT-0001` → giao, node đưa cho
hook có `task_meta(node).sku == "KT-0001"`. Trễ đúng **một** lượt so với hôm
nay (ghi §8).

### 3.9 T9 — Nhãn tài khoản của cha xuống con

**Bằng chứng**

- Người làm listing khai tài khoản bằng **nhãn** ERP
  (`listing_bridge.py:178-192`); ERP đồng bộ xuống `meta_auto` dòng
  `_labels: [acc32]` (`erp_meta.py:355-359`). `account_from_labels` `:572-587`
  chỉ được gọi trong `resolve_routing` (`:620`) từ `meta.labels`.
- `inherited_meta_node` `agent_bot.py:929-932` chỉ nối `parent.raw` (khối *Thuộc tính*),
  không nối `raw_auto`; `erp_meta.inherit` `erp_meta.py:469` cũng cố ý `auto=dict(child.auto)`.
  → con giao đi không có tài khoản → `resolve_routing` rơi về máy mặc định
  hoặc ném `ListingBridgeError`. (Mô tả hiện trạng trước khi T9 sửa; hàm hiện
  tại — `agent_bot.py:1003-1052` — đã lọc và thêm `acc:` từ nhãn, không còn
  dòng nào khớp nguyên văn để trỏ tới; giữ nguyên `:929-932`.)

**Yêu cầu**

- T9.1 `inherited_meta_node(node, root, known_accounts=())`: khi
  `parent.account_id == ""` và `account_from_labels(parent.labels, known_accounts)`
  trả một mã → thêm dòng `acc: <mã>` vào **khối nối của bản sao** (chỉ trong bộ
  nhớ; không ghi lên ERP). Dòng `acc:` gõ tay trên cha vẫn thắng nhãn
  (`resolve_routing` đã theo thứ tự ấy).
- T9.2 `listing_pass` (`:3046`) và `pipeline_pass` (`:2866`) truyền `known_accounts=self.book.account_ids`
  (`self.book` `agent_bot.py:1585`, `account_ids` `account_book.py:137`). Không có sổ thì
  `()` — quy ước `acc` + số vẫn khớp (`_ACCOUNT_LABEL_RE`, `erp_meta.py:45`).

**Không làm**: không đổi `erp_meta.inherit`; không đổi `ListingBridge.payload`.

**Tiêu chí**: cha `meta="action_1: listing"`, `meta_auto="_labels: [acc32]"`,
con có `sku` + 1 👍 → `task_meta(node_giao).account_id == "acc32"`. Cha có
`acc: acc16` + nhãn `acc32` → `"acc16"` (chốt, đang xanh).

### 3.10 T10 — Chỉ dòng định tuyến của cha xuống con

**Bằng chứng**

- `inherited_meta_node` `agent_bot.py:929-932` nối **nguyên** `parent.raw`. Cha có
  `sku: PARENT` → con trắng đọc ra `sku == "PARENT"` → `etsy_listing_sku`
  của con là mã của cha (`listing_bridge.py:286`). `template`, `product`,
  `flow_profile` của cha cũng rò. (Mô tả hiện trạng trước khi T10 sửa; đã cài,
  xem `agent_bot.py:1003-1052`; giữ nguyên `:929-932` — không còn dòng khớp
  nguyên văn để trỏ tới.)
- `parse_meta_block` khoá trùng: giá trị **sau** thắng, nên con có `sku`
  riêng thì không sao; con trắng thì mượn.

**Yêu cầu**

- T10.1 Khối cha đưa xuống con chỉ gồm khoá khớp `_ACTION_RE` (`erp_meta.py:46`)
  và khoá thuộc `ACCOUNT_KEYS` `:50`, `MACHINE_KEYS` `:53`; dựng bằng
  `render_meta_block` `:399` từ `parent.attributes` đã lọc, rồi nối khối riêng
  của con sau. Dòng `acc:` sinh từ T9.1 thuộc nhóm này.
- T10.2 Nút gốc trong cây không bị sửa (bản sao `{**node, "meta": merged}` giữ nguyên cách làm).

**Không làm**: không thêm khoá nào khác vào danh sách; không đổi luật "con viết thắng".

**Tiêu chí**: cha `action_1: listing / acc: acc32 / machine: etsy-vn32 / sku: PARENT / template: T1`,
con `sku: KT-0001` → node giao có `is_listing`, `account_id == "acc32"`,
`machine_id == "etsy-vn32"`, `sku == "KT-0001"`, `get("template") == ""`.
Gọi thẳng `inherited_meta_node({"name": …, "meta": ""}, root)` với cha có
`sku: PARENT` → `sku == ""`, `is_listing` và `account_id` vẫn xuống.

### 3.11 T11 — Cây có con không đóng băng nửa làm ảnh

**Bằng chứng**

- Idea mới **không** đến dưới dạng thẻ con. Người thả ảnh lên **thẻ cha**;
  `enqueue_erp_idea_jobs` (`service.py:4001`) fan-out từ tệp đính kèm của cha
  (`_erp_intake_idea_images` `:3871-4000`) và **idempotent** — bỏ qua con đã có ảnh
  (`_erp_idea_skip_reason` `:3511-3514`).
  Docstring `autorun_pass` `agent_bot.py:2941-2953` nói đúng cơ chế này.
- `run_once` (nay là `_scan_once`) `agent_bot.py:3244-3264`: mọi con đã listed/confirmed → `outcomes` không có
  `needs_images` → `continue` → `autorun_pass` không chạy → ảnh mới trên cha
  không bao giờ được tách. Bản đầu PRD (§8 cũ) viết "con mới thả chưa có dòng
  sổ nên mở autorun" — sai tiền đề, con chưa tồn tại.
- Lo ngại T7 (chạy lại ảnh lên bộ đã chốt) chỉ đúng với gốc **đứng một
  mình** mang ảnh trên chính nó; với cây, fan-out không đẻ ảnh cho con đã có ảnh.

**Yêu cầu**

- T11.1 `run_once` (nay `_scan_once`): `continue` chỉ khi `not any(needs_images) and not has_children(root)`
  (`has_children` `:779-791`, xem `:3253`). Cây có con rơi xuống `autorun_pass` như thẻ ảnh
  thường; hàng rào là cooldown `autorun_is_cool` `:1437`
  (`DEFAULT_AUTORUN_COOLDOWN_SECONDS = 900`, `:116`).
- T11.2 Docstring `run_once`/`_scan_once` ghi lại cơ chế thả idea qua cha.

**Không làm**: không thêm điều kiện "ảnh mới" (`count_card_images(root) > child_total`)
— thêm là nhân đôi phép lọc mà `autorun_pass` `:2944-2946` đã cố ý không làm.
Không đổi cooldown.

**Tiêu chí**: cây 2 con, cả hai confirmed sau 2 lượt; lượt 3 dòng bảng cha
`attachment_count: 3` → `autorun_hook` nhận `["TASK-P"]`. Gốc đứng một mình đã
giao, hỏi lại trả `pending`, 2 lượt → `autorun_calls == []` (T7 giữ).

### 3.12 T12 — Đề nghị Done bị từ chối thì không lặp mỗi lượt

**Bằng chứng**

- Từ lượt `listing_confirmed(con)` trở đi: `pipeline_pass` dựng
  `card_stage(is_listing=True, listed=True)` `agent_bot.py:2857-2868` → `_leave_review`
  `pipeline.py:329-346` bảo sang *Hoàn thành* → gọi `pipeline_hook` `agent_bot.py:2895`.
  App: `_erp_pipeline_stage` `service.py:15110` đọc meta riêng của con → `_leave_review`
  trả `"chờ người làm listing"` `pipeline.py:345` → `advance_erp_pipeline` trả
  `{"moved": False, "reason": "chờ người làm listing"}` (`service.py:15167`, `:15218`).
- **Đã cài**: `pipeline_pass` nay có cooldown riêng tiền tố `pipeline:`
  (`agent_bot.py:2884-2886`; `is_paused` `:2853`). Mô tả "không có cooldown
  nào" là hiện trạng trước khi T12 sửa — giữ nguyên câu chữ, không còn đúng
  với code hiện tại.

**Yêu cầu**

- T12.1 Trong `pipeline_pass`, khi bot **có nước đi** (`move` khác rỗng) và hook
  trả `outcome` không phải dict có `moved` truthy → `self.state.mark_autorun(f"pipeline:{task_id}")`;
  đầu vòng, nếu `move` khác rỗng và `not autorun_is_cool(f"pipeline:{task_id}", autorun_cooldown_seconds)`
  → bỏ qua nút, thêm dòng `{"task": task_id, "skipped": "vừa đề nghị, đang chờ nguội"}`.
- T12.2 Không ghi cooldown khi chỉ `needs_sku_fill` (`move` rỗng): thẻ *Đang làm*
  chờ điền mã phải được gọi mỗi lượt như hôm nay.
- T12.3 `moved: True` không ghi cooldown.

**Không làm**: không thêm khoá mới vào sổ; dùng lại `autorun_is_cool`/`mark_autorun`
với tiền tố `pipeline:` (cùng cách `listing:` `agent_bot.py:3108`).

**Tiêu chí**: con confirmed, `pipeline_hook` trả `{"moved": False, "reason": …}`,
5 lượt, `autorun_cooldown_seconds=600` → hook được gọi cho `TASK-P-a` đúng
**1** lần. Cùng dữ liệu, hook trả `{"moved": True}` → ≥ 2 lần (chốt, đang xanh).

### 3.13 T13 — `build_agent_bot` nói tên biến thiếu

**Bằng chứng**

- Đường app: `service.watch_agent_bot` `service.py:22783-22787` → `self.agent_bot()`
  `:22627` → `build_agent_bot` `agent_bot.py:3442-3488` → `:3461-3467`
  `if not resolved.enabled: return None` → `watch_agent_bot` `return`.
  `run_forever` không được gọi → hai dòng T5.1 (`:3374`, `:3377`) không hiện
  trên hvg-pc khi thiếu token. Chỉ ca `poll_seconds <= 0` mới tới `:3377`.
- Bản chạy rời tự log `scripts/run_agent_bot.py:279`.
- `RunForeverOffLogTests` `tests/test_agent_bot.py:3475` dựng `AgentBot` tay nên xanh mà không chứng
  minh đường app.

**Yêu cầu**

- T13.1 **Đã cài**: `build_agent_bot`, trước `return None` ở `agent_bot.py:3468`,
  đã có `log.info` dòng `:3467` "Agent bot tắt: chưa đặt ERP_AGENT_TOKEN."
  (dùng lại chữ `ERP_AGENT_TOKEN` như `:3374`). Vẫn trả `None`.
- T13.2 Không sửa `service.watch_agent_bot` (vùng cấm). Giữ hai dòng trong `run_forever`.
- T13.3 `docs/bat-listing-etsy.md:276-277` sửa số dòng `agent_bot.py:2587` →
  `:2762` và ghi thêm dòng log mới của T13.1; `:310` sửa `agent_bot.py:1011` → `:1097`.
  (Đã thực hiện — `docs/bat-listing-etsy.md` hiện ghi số dòng hiện hành, không
  còn `:2587`/`:1011` để so; để nguyên câu, coi là việc đã xong.)

**Tiêu chí**: `build_agent_bot(AgentBotConfig(bot_user=BOT, token=""), state_path=…)`
trả `None` và `assertLogs("flow_web.agent_bot", "INFO")` bắt được dòng có
`ERP_AGENT_TOKEN`.

### 3.14 T14 — T3.3 viết lại; fixture PDF; bài gọi tên luật (đã xong trong PRD này)

- T3.3 viết lại ở §3.3. Fixture `tests/test_agent_bot.py::test_count_decisions_and_readiness_ignore_the_pdf`
  `:3334` đổi thành `comment("note", mine=0, content="", attachments=[{"file_name": "bang-gia.pdf"}])`
  — ghi chú của người thật không mang dấu app. Bài mới
  `test_a_real_file_outranks_the_review_marker` `:3352` gọi tên luật: dấu +
  PDF → không phải ảnh chờ (cả `mine=1` lẫn `mine=0`); dấu + `.png` → là; dấu +
  `attachments: []` → là.
- Không có việc cài đặt. Ảnh app đăng luôn tên `flow-<job>-<n>.{jpg,png,webp,gif}`
  (`service.py:13222-13229`) nên luật này không bỏ sót ảnh của app.

### 3.15 T15 — URL không đuôi vẫn là ảnh

**Bằng chứng**

- Docstring `has_image_attachment` `agent_bot.py:680-693` hứa "không đọc được tên tệp thì
  vẫn tính là ảnh". Code (trước khi T15 sửa) coi `file_url` có giá trị là tên đọc được;
  `https://erp/files/abc` không có đuôi → `False`; dấu `[FLOW_V2_REVIEW]` không
  cứu vì có `attachments`. **Đã cài**: hàm hiện tại (`:695-714`, chốt ở
  `:710` `if "." not in tail: return True`) không còn trả `False` cho URL
  không đuôi — khớp lời hứa docstring.
- Chọn ngả: **sửa hàm cho khớp docstring** (không thu hẹp docstring). Lý do:
  luật gốc của T3 là "bỏ sót một ảnh thật là bỏ sót một phiếu người đã bấm".

**Yêu cầu**

- T15.1 Tên đọc được = phần trước `?` có **đuôi** (`Path(...).suffix` khác rỗng).
  Không đuôi → `True`. Có đuôi → thuộc `IMAGE_SUFFIXES` (không phân biệt hoa thường).

**Không làm**: không đổi `IMAGE_SUFFIXES` (Q6). Không đụng `count_card_images`.

**Tiêu chí**: `has_image_attachment({"attachments":[{"file_url":"https://erp/files/abc"}]})`
là `True`; `is_review_post(comment(…, attachments=[{"file_url":"https://erp/files/abc"}]))`
là `True`; `…/abc.pdf?fid=1` là `False`.

## 4. Kế hoạch test đỏ

Tất cả đã viết, đã chạy (§7 có con số). Bộ dùng chung cho đợt 4:
`_ListingTreeHarness` `tests/test_agent_bot.py:3518-3588` — cha `TASK-P`
(`PARENT_META = "action_1: listing\nacc: acc32"`, `Working`, gắn `BOT`), con
trắng chỉ có ảnh và (khi đã đánh số) `sku:`; `_sweep(root, times, confirm,
pipeline, root_attachments, cooldown)` dựng `FakeClient` mỗi lượt và giữ
`handed / asked / autorun_calls / pipeline_calls`.

### 4.1 `ListingChildCardTests` `tests/test_agent_bot.py:3089` (T1) — 9 bài, xanh

7 bài cũ (hook nhận `["TASK-P-a"]`; định tuyến của cha; dòng con thắng; con
chờ ảnh nói đúng tên; hai biên lai; hỏi lại đúng biên lai; đề nghị Done). Thêm
đợt này, xanh, làm chốt:

| Bài | Assert | Vì sao có |
|---|---|---|
| `…posted_under_a_person_s_identity_still_hand_the_child_over` `tests/test_agent_bot.py:3274` | con có `comment(mine=0, like=1)` × 2 → `handed == ["TASK-P-a"]` | app đăng ảnh review bằng danh tính người (`service.py:21554` `_erp_publish_review_comment`), bot đọc `mine=0` |
| `…waiting_for_votes_keeps_the_image_half_open_on_the_parent` `:3290` | `autorun_calls == ["TASK-P"]` | nửa ảnh chạy ở **cha**; không bài nào canh trước đây |

### 4.2 `ReviewPostAttachmentSuffixTests` `tests/test_agent_bot.py:3303` (T3, T14, T15) — 7 bài, 1 đỏ

- Fixture `:3343` sửa hình dạng người thật (T14). `:3352` gọi tên luật (xanh).
- Đỏ: `test_a_url_without_any_suffix_is_still_trusted_as_an_image` `:3375`
  — `has_image_attachment` trả `False` cho URL không đuôi.

### 4.3 `ListedCardAfterHandoverTests` `tests/test_agent_bot.py:3396` (T7, T6) — 2 bài, xanh

`:3424` gốc đứng một mình chờ Etsy không chạy ảnh lại (T7). `:3444` bộ lọc cột
(T6), chú thích `:3451` nói rõ hình dạng tối giản cố ý.

### 4.4 `ListingChildSkuGateTests` `tests/test_agent_bot.py:3591` (T8) — 2 bài, 2 đỏ

Con *Cần làm*, 2 👍, `meta=""`, `pipeline=True` → `handed == []`, dòng con có
`"SKU"` trong `waiting`, `needs_images` falsy. Bài 2: lượt 1 trắng không giao;
lượt 2 `sku: KT-0001` → giao, `_task_meta(node).sku == "KT-0001"`. Đỏ vì hôm nay
lượt 1 đã giao (`[] != ['TASK-P-a']`).

### 4.5 `ListingChildRoutingInheritanceTests` `tests/test_agent_bot.py:3649` (T9, T10) — 4 bài, 3 đỏ, 1 chốt

| Bài | Đỏ vì |
|---|---|
| `…account_label_reaches_the_child_as_an_acc_line` `:3662` | `'acc32' != ''` — nhãn không xuống con |
| `…acc_line_on_the_parent_still_beats_its_label` `:3679` | chốt, xanh |
| `…only_routing_lines_come_down_from_the_parent` `:3690` | `'' != 'T1'` — `template` của cha rò |
| `…blank_child_does_not_borrow_the_parent_s_sku` `:3708` | `'' != 'PARENT'` |

### 4.6 `ListingTreeAutorunTests` `tests/test_agent_bot.py:3723` (T11, T7) — 2 bài, 1 đỏ, 1 chốt

`:3734` cây 2 con confirmed, lượt 3 cha có 3 tệp → `autorun_calls == ["TASK-P"]`
(đỏ: `[]`). `:3754` gốc đứng một mình → `[]` (chốt T7).

### 4.7 `DoneProposalThrottleTests` `tests/test_agent_bot.py:3774` (T12) — 2 bài, 1 đỏ, 1 chốt

`:3784` hook trả `moved: False`, 5 lượt, cooldown 600 → gọi 1 lần (đỏ: 3 —
lượt 1 đẩy con, lượt 3–5 sau confirmed; lượt 2 là lượt hỏi lại). `:3795`
`moved: True` → ≥ 2 (chốt).

### 4.8 `BuildAgentBotOffLogTests` `tests/test_agent_bot.py:3809` (T13) — 1 bài, đỏ

`build_agent_bot(AgentBotConfig(bot_user=BOT, token=""))` → `None` + `assertLogs`
có `ERP_AGENT_TOKEN`. Đỏ vì "no logs of level INFO".

### 4.9 Bộ cũ đợt 1–3 (chốt)

`RunForeverOffLogTests` `tests/test_agent_bot.py:3475` (2), `NoiCauHoiLaiListing`
`tests/test_run_agent_bot.py:282` (2), `ListingActionAccentSpellingTests`
`tests/test_erp_meta.py:528` (2 hàm, 4 subTest). Tất cả xanh.

### 4.10 Test cho N1/N2 (ngoài phạm vi)

Chưa viết. Viết sau khi Q1 có câu trả lời, trong file thuộc vùng của người cài
`service.py` (không phải `tests/test_flow_web_smoke.py` đang có người sửa).

## 5. Biết nó chạy thật bằng cách nào

### 5.1 Trên máy này (chứng minh được bằng test)

```bash
.venv/bin/python -m unittest tests.test_agent_bot tests.test_run_agent_bot \
  tests.test_erp_meta tests.test_listing_bridge tests.test_pipeline -v
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Chứng minh được: bot giao đúng **thẻ con**, ghi sổ đúng mã, hỏi lại đúng biên
lai, đề nghị đúng nước đi, không chạy ảnh lại cho gốc đứng một mình; sau đợt
4: chờ SKU trước khi giao, nhãn cha thành `acc:`, chỉ dòng định tuyến xuống
con, cây có con vẫn tách idea mới, đề nghị Done không lặp, thiếu token có log.
**Không** chứng minh được: bản Listing có nhận payload không, Etsy có ra bản
nháp không, app có đóng thẻ không (N1/N2). Máy này không có `.env.local`;
không hứa một lượt Etsy thật.

### 5.2 Trên hvg-pc (checklist, làm theo thứ tự)

hvg-pc chạy Flow v2 **như app** (`automation_center/docs/runner-host-runbook.md:34,74-77`),
bot bật qua `service.watch_agent_bot` `service.py:22783`. `listing_confirm_hook` được nối
ở cả app (`:22650`) lẫn script (`scripts/run_agent_bot.py:299`); trên
hvg-pc dùng app, không chạy script song song (hai bot cùng một sổ).

1. Đọc `C:\HaviGroup\flow-v2\.env.local` (không sửa từ máy này; giá trị hiện
   có — **chưa kiểm chứng**). Cần có, không trống:
   `ERP_AGENT_TOKEN`, `ERP_AGENT_BOT_USER`, `ERP_AGENT_PROJECTS`,
   `ERP_AGENT_SCOPE` (`board` hoặc `card`), `ERP_AGENT_SOURCE_STATUS`
   (khớp **đúng** tên cột trên bảng), `ERP_AGENT_POLL_SECONDS` (> 0),
   `ERP_LISTING_API_URL`, `ERP_LISTING_PROJECT`, `ERP_LISTING_STATUS`,
   `ERP_LISTING_MACHINES` **hoặc** `ERP_LISTING_MACHINE`,
   `ERP_LISTING_TIMEOUT_SECONDS` (tuỳ chọn). Mẫu: `.env.local.example:52-151`.
   `load_local_env` (`flow_web/main.py:60-75`) chỉ đặt biến **chưa có** trong
   môi trường: biến đặt ở Scheduled Task thắng file.
2. Khởi động lại Scheduled Task `HaviGroup Flow v2` sau khi đổi `.env.local`.
3. Mở log ở `C:\HaviGroup\logs\`. Phải thấy **"Agent bot bật: quét mỗi …s,
   phạm vi …, cột nguồn: …"** (`agent_bot.py:3383-3384`). Không thấy: trước T13
   thiếu token là **im hoàn toàn** (`build_agent_bot` trả `None`,
   `watch_agent_bot` `return`); sau T13 có dòng nêu `ERP_AGENT_TOKEN`.
   `ERP_AGENT_POLL_SECONDS = 0` thì đã có dòng `:3377`.
4. Gọi bản Listing từ chính hvg-pc:
   `GET <ERP_LISTING_API_URL>/api/etsy/browser-copy/queue?machine_id=<máy>`
   phải trả JSON. Xác thực/lược đồ — **chưa kiểm chứng** (Q4).
5. Tạo thẻ cha khai `action_1: listing` + `acc: <tài khoản có trong sổ>` (hoặc
   dán nhãn tài khoản — sau T9), gắn bot, thả ảnh lên **cha**, để fan-out tạo
   con, bấm 👍 trên con. Chờ con sang *Đang làm* và có `sku:` (sau T8 bot mới giao).
6. Gọi `POST /api/agent-bot/run` (`flow_web/main.py:274`,
   `service.run_agent_bot_once` `service.py:22773`) hoặc chờ một chu kỳ. Trong JSON tìm
   `listing[]` có `"task": "<mã con>", "result": {"queue_task_id": …}`; trong
   log dòng `Giao thẻ listing <mã con> cho máy …`. Lỗi bridge:
   `Không giao được thẻ listing` (`agent_bot.py:3119`).
7. Chu kỳ sau: sổ `data/agent_bot_state.json` (`AgentBotState.load`
   `agent_bot.py:1257`; **chỉ đọc**; không phải `data/state.json`) có
   `listed["<mã con>"].confirmed == true` khi bản Listing báo `completed`;
   `listed["<mã con>"].card_moved_by_listing` (`:1407`) cho biết cột đổi vì bên
   kia. Kiểm chéo bằng `GET …/browser-copy/queue`.
8. Nước cuối: log bot có `Agent bot đẩy 1 thẻ sang cột kế — <mã con> chờ người
   làm listing.` (`agent_bot.py:3333`) và JSON `moved[].result.reason ==
   "chờ người làm listing"`. Thấy là **đợt này đã chạy hết phần của nó**;
   N1/N2 là chỗ còn lại. Sau T12 dòng này chỉ hiện một lần mỗi 15 phút cho
   mỗi con. Không thấy mà thẻ **vẫn** ở *Đang review* → đọc lại bước 6–7.
   **Không** chờ câu ở `service.py:12841` — đường bot không đi qua nó (§0).

### 5.3 Chưa kiểm chứng (liệt kê thẳng)

- Giá trị thật của mọi biến trong `.env.local` trên hvg-pc.
- Lược đồ và xác thực của hai endpoint bản Listing; nghĩa của `erp_done_move`
  (`listing_bridge.py:351` chỉ đọc bool; `docs/bao-cao-kiem-thu-codex.md:105-115`).
- Bản Listing đọc ảnh từ **bình luận** của thẻ con hay từ `taskAttachments`
  (`.env.local.example:118` chỉ nói "ảnh đính kèm"). Ảnh 👍 nằm trong bình luận
  (`service.py:21554`). Nếu bên kia đọc `taskAttachments` thì không thấy ảnh
  đã duyệt — Q7.
- Khi 👎 xoá bình luận (`DeleteTaskComment`), File đã upload lên Task có bị
  xoá theo không. Nếu không và bên kia đọc `taskAttachments` thì lấy cả ảnh bị
  loại — Q8.
- `taskFull` trả bình luận với `attachments` **rỗng** và chỉ giữ một `image`
  (`agent_bot.py:816-818`). Bình luận ảnh của người thật không có dấu app +
  `attachments` rỗng → không được đếm là phiếu. T3/T15 không đụng nhánh này;
  chưa có bài nào dựng đúng hình dạng đó.
- `taskFull` có trả `meta` cho thẻ con không; `parent_task`, `attachment_count`
  trên dòng bảng có đúng tên trường như `FakeClient` không. Nếu khác, bước 6
  hiện "thẻ chưa có ảnh nào để đăng" cho **cả** con.
- ERP cắt `taskFull.subtasks` ở 59 thẻ: con thứ 60 trở đi không bao giờ được giao.

### 5.4 Việc tay còn lại sau khi cài hết PRD

1. Kéo thẻ **con** sang *Hoàn thành* bằng tay — cổng `_erp_pipeline_stage`
   `flow_web/service.py:15110-15127` đọc meta riêng của con (không qua
   `inherited_meta_node`); client bot không có mutation trạng thái; bản Listing tự đóng thẻ
   cũng hỏng cố ý (`docs/giao-viec-codex-kiem-thu.md:61-65`, `card_missing_board_id`). Q1.
2. Thẻ **cha** không bao giờ tự đóng. Q2.
3. Bấm *publish* trên Etsy — `etsy_publish: False`. Q5.
4. Điền mã SKU khi bảng SKU hết mã — T8 chỉ **chờ**, không tự đặt.

(Trước T11: idea mới thả lên cha sau khi mọi con đã listed phải bấm chạy tay
trên dashboard. T11 bỏ bước này.)

## 6. Thứ tự làm đề xuất

| Đợt | Mục | PR | Trạng thái / vì sao |
|---|---|---|---|
| 1 | T3, T4, T7 | `agent_bot.py` + `erp_meta.py` | **Đã cài** (`56b2543`). |
| 2 | T1, T6 | `agent_bot.py` | **Đã cài** (`56b2543`). |
| 3 | T2, T5 | `scripts/run_agent_bot.py` + `.env.local.example` + `docs/` | **Đã cài** (`0592d64`, `9faad99`, `3bacaa2`). Thực tế ba đợt được ba agent làm song song và gộp trong cùng nhánh; thứ tự 1→2→3 không còn ý nghĩa. |
| 4 | T8, T9, T10, T11, T12, T13, T15 (+T14 đã xong) | **một PR**: `flow_web/agent_bot.py` + `docs/bat-listing-etsy.md` (T13.3) | **Đã cài.** Mọi việc đều trong `agent_bot.py`. Thứ tự đã làm: T15 → T10/T9 (`inherited_meta_node` chép danh sách khoá định tuyến + dịch nhãn thành `acc:`) → T8 (`_listing_one(child=…, own_sku=…)`) → T11 (`continue` thêm `and not has_children(root)`) → T12 (khoá nguội `pipeline:<mã>`) → T13 (`build_agent_bot` log trước khi trả `None`). 230/230 bài `tests.test_agent_bot` xanh. |
| — | N1/N2 | PR của người cài `service.py`, sau Q1 | Không nằm trong đợt 4. |

Ai ghi file nào ở đợt 4 (luật CLAUDE.md: hai agent không ghi cùng file):

| File | Người ghi |
|---|---|
| `flow_web/agent_bot.py`, `docs/bat-listing-etsy.md` | code-implementer đợt 4 |
| `tests/test_agent_bot.py` | prd-writer (đã xong; cần thêm bài thì nhờ prd-writer, không tự sửa) |
| `flow_web/service.py`, `tests/test_flow_web_smoke.py` | agent khác — cấm |
| `flow_web/erp_meta.py`, `scripts/run_agent_bot.py`, `.env.local.example` | không ai — đợt 4 không đụng |

## 7. Danh sách test đi kèm

Số **trước** khi cài đợt 4 (HEAD `3bacaa2` + test của PRD này):

- Năm module liên quan: **387 bài / 378 xanh / 9 đỏ**.
- Toàn bộ `tests/` (`discover -s tests`): **1501 bài / 1492 xanh / 9 đỏ** —
  đỏ đúng 9 bài đợt 4 dưới đây, không bài nào khác đỏ (kể cả
  `tests/test_flow_web_smoke.py` với bản `service.py` đang sửa dở trong worktree).
- Hai bài chốt `:1262` và `:1530`: **xanh**.
- 15 hàm test mới đợt 4: 9 đỏ, 6 xanh (chốt chặn). 372 bài trước đợt 4: xanh cả.

Số **sau** khi cài đợt 4: `tests.test_agent_bot` **230/230 xanh**, không nới
một assertion nào. Bốn bộ còn lại giữ nguyên nền: `automation_center` 88,
node 198, `bmad-init` 35, `bmad-distillator` 33 — xanh cả.

| Lớp / file | Mục | Số bài | Đỏ vì gì |
|---|---|---|---|
| `tests/test_agent_bot.py::ListingChildSkuGateTests` `:3591` | T8 | 2 (2 đỏ) | con không `sku` vẫn bị giao cùng lượt: `[] != ['TASK-P-a']` |
| `…::ListingChildRoutingInheritanceTests` `:3649` | T9, T10 | 4 (3 đỏ, 1 chốt) | nhãn không xuống con (`'acc32' != ''`); `sku`/`template` cha rò (`'' != 'PARENT'`, `'' != 'T1'`) |
| `…::ListingTreeAutorunTests` `:3723` | T11, T7 | 2 (1 đỏ, 1 chốt) | cây con listed hết → `autorun_calls == []` thay vì `['TASK-P']` |
| `…::DoneProposalThrottleTests` `:3774` | T12 | 2 (1 đỏ, 1 chốt) | `pipeline_hook` gọi 3 lần thay vì 1 |
| `…::BuildAgentBotOffLogTests` `:3809` | T13 | 1 (1 đỏ) | `build_agent_bot` trả `None` không log |
| `…::ReviewPostAttachmentSuffixTests` `:3303` | T3, T14, T15 | 7 (1 đỏ, 6 chốt) | URL không đuôi bị coi là tên đọc được → `False` |
| `…::ListingChildCardTests` `:3089` | T1 | 9 (0 đỏ) | chốt; 2 bài mới `:3274`, `:3290` |
| `…::ListedCardAfterHandoverTests` `:3396` | T7, T6 | 2 (0 đỏ) | chốt |
| `…::RunForeverOffLogTests` `:3475` | T5 | 2 (0 đỏ) | chốt |
| `tests/test_run_agent_bot.py::NoiCauHoiLaiListing` `:282` | T2 | 2 (0 đỏ) | chốt |
| `tests/test_erp_meta.py::ListingActionAccentSpellingTests` `:528` | T4 | 2 hàm (0 đỏ) | chốt |

Bài xanh **không được phép hỏng** khi cài đợt 4:

- `tests/test_agent_bot.py:1262`, `:1530` (lý do ở §1).
- `ListingCardTests` `:1351-1713` toàn bộ — gốc đứng một mình không có `sku`
  vẫn phải giao (T8 chỉ áp cho con).
- `ListingChildCardTests` `:3089-3301` — 9 bài, gồm `:3290` (`autorun_calls == ["TASK-P"]`
  khi con chờ phiếu: T11 không được làm nó thành `[]`, T8 không được chặn
  con đã có `sku`).
- `ReviewPostAttachmentSuffixTests` trừ bài URL — T15 không được sửa quá tay
  (`abc.pdf?fid=1` vẫn `False`).
- `ListingTreeAutorunTests:3754`, `ListedCardAfterHandoverTests:3424` — T7 cho
  gốc đứng một mình vẫn chặn.
- `DoneProposalThrottleTests:3795` — `moved: True` không được giãn.
- `ListingChildRoutingInheritanceTests:3679` — dòng `acc:` gõ tay thắng nhãn.
- `tests/test_erp_meta.py:322-364` — `inherit` không đổi (T9/T10 sửa ở
  `agent_bot.py`, không sửa `erp_meta.inherit`).
- `tests/test_run_agent_bot.py` 17 bài; `tests/test_agent_chat.py:422-427`
  (`action_1` không sửa được bằng lời); `tests/test_pipeline.py`,
  `tests/test_listing_bridge.py` — đợt 4 không đụng hai file nguồn ấy.

## 8. Rủi ro của chính đợt này

| Rủi ro | Mức | Cách giảm |
|---|---|---|
| Sau đợt 4 thẻ **vẫn không** sang *Hoàn thành* (N1/N2); người đọc tưởng đợt này thất bại | Cao | §0 và §5.2 bước 8 nêu đúng dòng log thật (tổng kết của bot, không phải `service.py:12841`). Runbook `docs/bat-listing-etsy.md` mục *Thẻ con đã lên shop mà vẫn không tự đóng* đã sửa lại đúng chỗ nhìn. Q1 **chặn mục tiêu cuối**. |
| Đề nghị Done lặp mỗi 120 s cho mỗi con đã confirmed cho tới khi Q1 xong | Vừa | T12 giãn xuống một lần mỗi `autorun_cooldown_seconds` (900 s). Vẫn lặp; chỉ Q1 mới hết. |
| T8 làm con giao **trễ một lượt** (2 phút) so với hôm nay | Thấp | Chấp nhận: mã đúng quan trọng hơn 2 phút. Ghi ở §3.8. |
| T8: bảng SKU hết mã → con chờ `SKU` mãi, không lỗi | Vừa | Dòng `waiting: "chờ máy điền SKU"` hiện mỗi lượt trong summary và log gộp `agent_bot.py:3304-3308`. Việc tay §5.4 mục 4. |
| T9 dòng `acc:` chỉ tồn tại trong **bản sao bộ nhớ**; ai ghi bản sao ấy ngược lên ERP là đè *Thuộc tính* của con | Vừa | T9.1/T10.2 nói rõ "bản sao, không ghi"; `ListingBridge.payload` chỉ đọc; bot không gọi `updateTaskMeta` (`agent_bot.py:2127-2129`). |
| T9: hai nhãn cùng chỉ tài khoản → `account_from_labels` trả `""` (cố ý) → con không có tài khoản → máy mặc định | Thấp | Luật có sẵn `erp_meta.py:579-581`; §5.2 bước 5 dặn một nhãn. |
| T10 lọc sót một khoá định tuyến mà `resolve_routing` đọc | Thấp | Danh sách lấy đúng từ `ACCOUNT_KEYS` `:50`, `MACHINE_KEYS` `:53`, `_ACTION_RE` `:46` — không viết tay. |
| T11 mở lại autorun cho cây có con: mỗi 15 phút một lượt `enqueue_erp_idea_jobs` cho **mỗi** cây listing còn mở, kể cả khi không có ảnh mới | Thấp | Fan-out idempotent (`_erp_idea_skip_reason` `service.py:3511-3520`); cooldown 900 s; bằng hành vi hôm nay của thẻ ảnh thường. |
| T12 giãn nhầm cả thẻ *Đang làm* chờ điền SKU | Vừa | T12.2: chỉ ghi cooldown khi bot có `move`; `needs_sku_fill` không có `move`. Bài chốt `tests/test_agent_bot.py:3795`. |
| Cây 10 con vừa fan-out → 10 dòng `thẻ chưa có ảnh nào để đăng` mỗi lượt | Thấp | **Chấp nhận** (§3.1): mỗi dòng là một thẻ thật. Log gộp thành một dòng `agent_bot.py:3304-3308`. |
| Fixture `FakeClient` giả `parent_task`/`attachment_count`/`meta`; ERP thật khác tên trường | Vừa | §5.3; bước 6 §5.2 chỉ cách nhận ra. |
| Agent khác đang sửa `service.py` + `tests/test_flow_web_smoke.py` trong cùng worktree | Thấp | Đợt 4 không chạm hai file ấy; commit của đợt 4 chỉ `add` đúng file của mình. |
| Bị nhờ nới `:1262`/`:1530` hoặc hạ Q1 thành giả định | — | Không. Đến lúc sửa PRD này **chưa** nhận yêu cầu nào như thế; hội đồng chỉ yêu cầu sửa lý do xanh, không yêu cầu nới. |
| Cây > 59 con bị `taskFull` cắt | Thấp | Ngoài phạm vi; §5.3. |

## 9. Câu hỏi cần người quyết

1. **[chặn mục tiêu cuối — không chặn đợt 4]** Thẻ con lấy `action_1: listing`
   từ đâu để app đóng được nó? Ba lối:
   (a) fan-out `service.py:3871` (`_erp_intake_idea_images`) chép `action_*`,
   `ACCOUNT_KEYS`, `MACHINE_KEYS` của cha vào *Thuộc tính* con qua
   `_erp_update_task_meta` `:13893` — ghi lúc tạo; không sửa được con đã có;
   (b) `_erp_pipeline_stage` `service.py:15110` và cổng đọc
   `inherit(task_meta(con), task_meta(cha))` (`erp_meta.py:469`) — không ghi
   chữ lên thẻ, sửa được thẻ cũ, phải đọc thêm cha;
   (c) bot lan meta xuống con trong `inherit_pass` `agent_bot.py:2484` bằng
   mutation `UpdateTaskMeta` mới — trong file được sửa, nhưng trái
   `agent_bot.py:2127-2129`.
   PRD **đề nghị (b)**: đúng với "Không một chữ nào lên thẻ" `service.py:3956`, và
   `inherited_meta_node` bên bot đã làm đúng thế. Người trả lời: chủ
   `service.py` + người đặt luật "không một chữ nào lên thẻ".
2. **[không chặn]** Thẻ cha có được tự đóng khi **mọi** con đã *Hoàn thành*
   không? Hôm nay không có luật nào cho cha. Người trả lời: người vận hành bảng.
3. **[không chặn]** `ERP_AGENT_SOURCE_STATUS` trên hvg-pc đang là gì, cột ấy
   có còn tên `Working` không? Ảnh hưởng T6 và bước 3 §5.2. Người trả lời: ai
   đọc được `.env.local` trên hvg-pc.
4. **[không chặn]** Bản Listing `GET /api/etsy/browser-copy/queue` có cần xác
   thực không, `status` gồm giá trị nào (`queued`/`in_progress`/`completed`/…)?
   `_listing_wait_text` `agent_bot.py:1055` và `confirm` `listing_bridge.py:304-359` dựa vào
   đó. Người trả lời: chủ repo bản Listing.
5. **[không chặn]** Sau bản nháp, ai bấm *publish*? `etsy_publish: False` là
   cố ý. Người trả lời: chủ shop.
6. **[không chặn]** `IMAGE_SUFFIXES` `agent_bot.py:676` có thêm `.heic`/`.avif`/`.bmp`
   không? Ảnh người dán từ điện thoại (`.HEIC`) hôm nay bị loại khỏi phiếu
   ngoại; đổi hằng là đổi cả `count_card_images` `:842`. Người trả lời: người
   vận hành bảng (có ai dán ảnh tay không).
7. **[không chặn — nhưng quyết định bước 6 §5.2 có nghĩa gì]** Bản Listing tải
   ảnh từ **bình luận** thẻ con hay từ `taskAttachments`? Người trả lời: chủ
   repo bản Listing.
8. **[không chặn]** `DeleteTaskComment` có xoá File đính kèm theo không? Nếu
   không, và Q7 là `taskAttachments`, ảnh 👎 vẫn lên shop. Người trả lời: chủ ERP.

## 10. Đối chiếu phán quyết hội đồng

Mỗi vấn đề: **Sửa** (đã đổi trong PRD) hoặc **Giữ** (kèm lý do và `file:line`).
Số dòng ở cột "Bằng chứng" theo HEAD `3bacaa2`.

| # | Phán quyết | Kết luận | Ở đâu trong PRD / bằng chứng |
|---|---|---|---|
| 1 | `build_listing_hook`/`build_listing_confirm_hook` lệch 1 | **Sửa** | §3.2: `listing_bridge.py:413-423`, `:426-436`. |
| 2 | `compact_status`/`_compact` lệch 1 | **Sửa** | §3.4: `agent_bot.py:928` (đã trôi từ `:777` vì T3 thêm dòng), `pipeline.py:65-74`. |
| 3 | `_leave_doing` lệch 1 | **Sửa** | §3.1: `pipeline.py:302-325`, câu trích `:307`. |
| 4, 9 | `runner-host-runbook.md` thiếu thư mục; T5.3 tên file | **Sửa** một nửa, **giữ** một nửa | Đường dẫn sửa ở §3.5, §5.2 thành `automation_center/docs/runner-host-runbook.md:34,74-77`. Tên file T5.3 **không** đổi thành `docs/bat-bot-listing-tren-hvg-pc.md`: file đã được cài và commit là `docs/bat-listing-etsy.md` (`0592d64`, `3bacaa2`); đổi tên trong PRD là tạo hai tên cho một file. |
| 5 | Không ghi mốc commit | **Sửa** | Đầu PRD: mốc `3bacaa2`, lệnh `git show`. |
| 6 | Log thiếu token phải ở `build_agent_bot` | **Sửa** | T13 (§3.13), test `BuildAgentBotOffLogTests` `tests/test_agent_bot.py:3809`. `service.py:22783-22787` xác nhận `watch_agent_bot` `return` khi `None`. Test không truyền `client=` như giám khảo gợi — `build_agent_bot` `agent_bot.py:3442` không có tham số ấy; dùng `state_path`. |
| 7, 14, 18 | Lý do `:1262` xanh sai | **Sửa** | §1 Ràng buộc 2 viết lại theo code đã cài: con `TASK-L-a` là nút listing, gốc bị lược ở `:2507-2511`, `summary["listing"][0]["task"] == "TASK-L-a"`, autorun nhận mã gốc `:2397-2398` *(chưa soát lại số dòng đợt này — để nguyên, chưa chắc)*. T1.6 cũ bỏ; thay bằng điều kiện xanh tường minh. |
| 8, còn thiếu 16 | Đề nghị Done lặp mỗi lượt; `pipeline_pass` có cooldown không | **Sửa** | T12 (§3.12): xác nhận **không có** cooldown (`agent_bot.py:2320-2382` — số dòng trước khi cài T1–T7; `pipeline_pass` giờ ở `:2813-2940`, khoá nguội `cooldown_key`/`autorun_is_cool` tại `:2884-2886`); cooldown `pipeline:<mã>`; §8 ghi rủi ro. |
| 10 | `service.py:12841` không bao giờ ghi qua đường bot | **Sửa** | §0 và §5.2 bước 8: tín hiệu thật là `agent_bot.py:3333` + `moved[].result.reason`; mọi tham chiếu `service.py:12841` chỉ còn để nói "đừng chờ nó". Xác nhận: `service.py:22744` (`_agent_bot_pipeline`) không truyền `job_id`, `service.py:15216` `if job_id:` trong khối `except` của `advance_erp_pipeline`, `pipeline.py:334` trả trước cổng. |
| 11 | Cây đóng băng; idea mới đến qua thẻ cha | **Sửa** | T11 (§3.11): `continue` chỉ khi `not has_children(root)`; §8 dòng rủi ro cũ ("con mới thả chưa có dòng sổ") bỏ. Test `tests/test_agent_bot.py:3723` (`ListingTreeAutorunTests`). |
| 12 | Con giao với `etsy_listing_sku=""` | **Sửa** | T8 (§3.8), test `tests/test_agent_bot.py:3591` (`ListingChildSkuGateTests`). `agent_bot.py:3095-3105` (cổng `if child and not own_sku`) xác nhận SKU điền lượt sau. |
| 13 | Nhãn `acc32` không xuống con | **Sửa** | T9 (§3.9), test `tests/test_agent_bot.py:3662` (`ListingChildRoutingInheritanceTests`). Xác nhận `inherited_meta_node` `agent_bot.py:929-932` chỉ nối `parent.raw` — số dòng cũ trước T9/T10, không còn dòng khớp; bản hiện tại lọc theo `_ACTION_KEY_RE`/`ROUTING_KEYS` ở `agent_bot.py:1003-1052`. |
| 15 | `sku`/`template` cha rò xuống con | **Sửa** | T10 (§3.10), test `tests/test_agent_bot.py:3690`, `:3708`. |
| 16 | §5.2 bước 7 ghi `data/state.json` | **Giữ**, thêm chi tiết | Bản đầu bước 7 đã ghi `data/agent_bot_state.json`; `data/state.json*` chỉ xuất hiện ở Ràng buộc 3 như file **cấm**. Khoá thật là `listed` (`agent_bot.py:1273`), không phải `listing`; `card_moved_by_listing` là khoá con `:1407`; đường sổ `:1258` (không phải `:1041` như giám khảo dẫn). Bước 7 ghi rõ cả ba. |
| 17, còn thiếu 21 | T3.3 sai so với code; fixture PDF mang dấu app | **Sửa** | §3.3 T3.3 viết lại; fixture `tests/test_agent_bot.py:3343` đổi `mine=0, content=""`; bài gọi tên luật `:3352`. Đuôi lạ → Q6. |
| 19, còn thiếu 20 | Không bài nào canh `autorun_calls` ở hình dạng cha+con | **Sửa** một nửa, **giữ** một nửa | Thêm `tests/test_agent_bot.py:3290` (`autorun_calls == ["TASK-P"]` khi con chờ phiếu). **Không** thêm "sau giao con + Etsy `pending` → `autorun_calls == []`": trái với #11 — cây có con phải **còn** autorun để tách idea mới (`agent_bot.py:3253-3264`, `if not any(needs_images) and not has_children(root): continue`). T7 giữ cho gốc đứng một mình bằng `tests/test_agent_bot.py:3424` và `:3754`. |
| 20 | Bài T6 hình dạng tối giản không nói rõ | **Sửa** | Chú thích trong bài `tests/test_agent_bot.py:3451`; §3.6 ghi "bài đơn vị thuần cơ chế". |
| 21, còn thiếu 22 | Thiếu biến thể `mine=0` ở cha+con | **Sửa** | `tests/test_agent_bot.py:3274`. |
| 22 | URL không đuôi | **Sửa**, chọn ngả sửa hàm | T15 (§3.15), test `tests/test_agent_bot.py:3375`. |
| còn thiếu 1, 2, 3, 6, 7, 8, 9, 24, 25 | Ghi nhận đúng | **Giữ** | Không đổi nội dung; tên hàm thật (`inherited_meta_node`, `_listing_one`) thay tên đề xuất cũ ở §3.1. |
| còn thiếu 4, 19 | §7 cũ | **Sửa** | §7 con số mới (387/378/9; toàn `tests/` 1501/1492/9). |
| còn thiếu 5 | Thứ tự đợt bị bỏ qua; số dòng trôi | **Sửa** | Đầu PRD (mốc), §6 ghi ba đợt làm song song. |
| còn thiếu 10 | 10 con = 10 dòng | **Sửa** | §3.1 và §8: chấp nhận, không gộp. |
| còn thiếu 11 | Test đường app cho T5 | **Sửa** | T13. |
| còn thiếu 12 | Ai ghi file nào | **Sửa** | §6 bảng. |
| còn thiếu 13 | Câu chốt đích payload | **Sửa** | §1 "Câu chốt đích của payload". |
| còn thiếu 14, 15 | Listing đọc ảnh từ đâu; xoá File | **Sửa** | §5.3 + Q7, Q8. |
| còn thiếu 17 | Việc tay còn lại | **Sửa** | §5.4. |
| còn thiếu 18 | Confirm hook chỉ khi chạy qua service | **Giữ**, cập nhật | Sau `9faad99` script cũng nối (`scripts/run_agent_bot.py:299`). §5.2 ghi cả hai đường và dặn không chạy song song. |
| còn thiếu 23 | `taskFull` `attachments` rỗng chỉ có `image` | **Sửa** | §5.3 thêm dòng; chưa có bài, ghi thẳng. |

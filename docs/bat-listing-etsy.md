# Bật tự động đăng listing lên Etsy

Runbook này trả lời ba câu: **bật cái gì**, **thẻ phải viết ra sao**, và
**vì sao thẻ đứng im**. Mọi tên biến, câu log và đường API dưới đây chép từ
code kèm `file:dòng`; chỗ nào chưa xác minh được thì ghi thẳng là chưa.
Số dòng ghim theo commit `538c09e`. Lúc viết, `flow_web/agent_bot.py`,
`flow_web/erp_meta.py`, `flow_web/service.py` và `scripts/run_agent_bot.py`
đang bị sửa dở trong working tree, nên đối chiếu bằng
`git show 538c09e:<file> | sed -n '<dòng>p'`, đừng mở file đang mở dở.

Tính năng làm gì, một câu: thẻ ERP viết `action_1: listing` trong khối
*Thuộc tính*, người duyệt bấm 👍 lên ảnh, bot tự giao thẻ sang **bản Listing**
(một app khác, ngoài repo này) để chép ảnh sang máy Etsy và dựng bản nháp, rồi
tự đóng thẻ sang *Hoàn thành* khi bên kia báo xong. Không có lượt tạo ảnh thứ
hai — bản Listing chỉ *đăng* bộ ảnh đã có 👍 trên chính thẻ đó
(`flow_web/listing_bridge.py:1-22`).

## Câu quan trọng nhất

**Giao đi không phải là đăng xong.** Vòng có hai nửa, đi qua hai đường API
khác nhau, và chỉ nửa thứ hai mới mở cổng sang *Hoàn thành*:

| Nửa | Đường API bản Listing | Hàm | Ghi vào sổ bot | Mở cổng *Hoàn thành*? |
|---|---|---|---|---|
| Giao đi | `POST <ERP_LISTING_API_URL>/api/etsy/browser-copy/enqueue` (`listing_bridge.py:48`) | `ListingBridge.dispatch` (`:292-302`) | `listed[<thẻ>] = {queue_task, machine, confirmed: false}` (`agent_bot.py:1371-1376`) | **Không** |
| Xác nhận | `GET <ERP_LISTING_API_URL>/api/etsy/browser-copy/queue?machine_id=<máy>` (`listing_bridge.py:54`, `listing_bridge.py:328-334`) | `ListingBridge.confirm` (`listing_bridge.py:304-359`) | `confirmed: true` — chỉ khi bên kia trả `status == "completed"` (`listing_bridge.py:57`, `listing_bridge.py:347-352`; `agent_bot.py:1398-1407`) | **Có** |

Xếp được hàng và dựng xong bản nháp là hai chuyện khác nhau: giữa hai chuyện
ấy còn một máy ảo phải thức, mở Chrome, chép ảnh và bấm lưu
(`listing_bridge.py:304-319`). Luật cột đọc `listing_done`, mà `listing_done`
chỉ bật khi `listing_confirmed` (`agent_bot.py:1164`, `agent_bot.py:1378-1391`). Nên thẻ
vừa giao sẽ **đứng ở *Đang review*** với câu `chờ listing lên shop`
(`flow_web/pipeline.py:346`) cho tới lượt quét nào bên kia báo `completed`.
Đó là hành vi đúng, không phải kẹt.

`confirm` trả ba loại câu, cố ý tách bạch (`listing_bridge.py:312-319`):

- `done` — `status == "completed"`. Bản nháp có thật trong shop.
- `failed` — status khác `completed` / `queued` / `in_progress`, kèm `error`.
- không cái nào — còn `queued`/`in_progress`, **hoặc không tra ra** (bên kia
  chỉ giữ ít lượt gần nhất trong ảnh chụp hàng đợi, `:341-345`). "Không thấy"
  là *không biết*, không phải *hỏng*.

Không ngả nào xoá dòng sổ, kể cả `failed` (`agent_bot.py:1367-1407`). Sổ còn
dòng thì `already_listed` chặn giao lần hai (`agent_bot.py:3074-3082`) — vì giao lại một
thẻ đã đăng là hai bản nháp cho cùng một sản phẩm. Lượt hỏng thì **người** vào
shop xem, máy không tự giao lại.

## Vòng đi của một thẻ

1. Người viết `action_1: listing` và `acc: <tài khoản>` vào khối *Thuộc tính*
   — **trước khi ảnh xong** (xem "Cách viết thẻ" và `.env.local.example:125-131`).
2. Nửa làm ảnh chạy như thẻ thường, đăng ảnh lên thẻ; người bấm 👍/👎.
3. Mỗi lượt quét, bot dọn phiếu (`janitor_pass`) rồi mới xét listing
   (`agent_bot.py:3237-3251`): thẻ nào `is_listing_card` (`agent_bot.py:975-992`) thì đi
   qua `listing_pass` (`agent_bot.py:3024-3125`).
4. `listing_pass` kiểm `listing_readiness` (`agent_bot.py:1063-1097`). Đủ điều kiện thì gọi
   `enqueue`; bên kia trả `queue_task.id` thì ghi sổ (`agent_bot.py:3114-3125`).
5. Lượt sau, thẻ đã có trong sổ nên `listing_pass` rẽ sang `_listing_confirm`
   (`agent_bot.py:2989-3022`): gọi `queue`, thấy `completed` thì `confirm_listing`.
6. `pipeline_pass` (`agent_bot.py:2857-2869`) đọc `listing_confirmed` → `card_stage`
   → `pipeline.decide` → `_leave_review` trả `Completed` với lý do
   `listing đã lên shop` (`pipeline.py:331-334`). Hook đẩy cột đi qua app
   (`/api/erp/pipeline/advance`, `flow_web/main.py:227`).

Tổng kết mỗi lượt có mảng `listing` (`agent_bot.py:3299`) và một dòng log
`Agent bot: N thẻ listing — <mã> <trạng thái>; …` (`agent_bot.py:3304-3328`). Trạng thái
là một trong: câu `waiting`, câu `skipped`, câu `error`, `listing HỎNG bên máy
Etsy: …`, `bản nháp đã vào shop`, `đã giao`, `chạy khô`.

## Chạy ở đâu

**Trong app** (cách hvg-pc đang chạy): `FlowWebService.agent_bot`
(`flow_web/service.py:22627-22660`) nối **cả hai** hook —
`listing_hook` và `listing_confirm_hook`. Bot quét theo `ERP_AGENT_POLL_SECONDS`
qua `watch_agent_bot` (`flow_web/service.py:22783-22793`); muốn quét ngay một lượt thì
`POST /api/agent-bot/run` (`flow_web/main.py:274-277`), câu trả lời là JSON
tổng kết ở trên.

**Script rời** `scripts/run_agent_bot.py`: ở commit `538c09e` nối
`listing_hook` (`:293`) nhưng **không nối `listing_confirm_hook`** (`:288-307`
không có tham số đó). Hệ quả: thẻ giao đi từ script rời không bao giờ được hỏi
lại, sổ giữ `confirmed: false` mãi, thẻ không sang *Hoàn thành*. Đã vá ở commit
`9faad99` (thêm `build_listing_confirm_hook` vào script) kèm test
`NoiCauHoiLaiListing` trong `tests/test_run_agent_bot.py`; yêu cầu gốc là mục
T2 của `tasks/prd-list-tu-dong-etsy.md`. Kiểm nhanh trước khi dùng
script: `grep -n listing_confirm_hook scripts/run_agent_bot.py` — không ra dòng
nào thì script vẫn thiếu nửa thứ hai; khi ấy dùng bot trong app để đóng thẻ.

`.env.local` được nạp bởi `load_local_env` (`flow_web/main.py:60-75`), đường
file lấy từ `FLOW_ENV_FILE` hoặc mặc định `.env.local` ở gốc repo (`:44-50`).
Nó **chỉ đặt biến chưa có** trong môi trường (`:73`): biến đặt ở Scheduled
Task hay shell thắng file. Đổi file xong phải khởi động lại app.

## Biến môi trường

Toàn bộ những gì `ListingBridgeConfig.from_env` đọc
(`flow_web/listing_bridge.py:92-113`). Khối tương ứng trong
`.env.local.example` là "Thẻ listing Etsy".

| Biến | Bắt buộc | Mặc định | Dùng để làm gì | Đọc ở |
|---|---|---|---|---|
| `ERP_LISTING_API_URL` | **Bắt buộc để bật** | trống = tắt | Địa chỉ gốc bản Listing. Dấu `/` cuối bị cắt. Trống thì `enabled` là False: bot vẫn nhận ra thẻ listing, không đụng vào, không giao đi đâu. | `:107`, `:88-90` |
| `ERP_LISTING_PROJECT` | Tuỳ chọn | `ERP_PROJECT_ID`, rồi `PROJ-0013` | Dự án ERP mà bản Listing đọc thẻ. Viết hoa trước khi dùng. Gửi làm `erp_project_id`. | `:101-105`, `:108`, `:44`, `:263` |
| `ERP_LISTING_STATUS` | Tuỳ chọn | trống | Gửi làm `erp_status_id` trong payload; trống thì đầu kia tự đọc cột hiện tại. | `:109`, `:264` |
| `ERP_LISTING_MACHINES` | Tuỳ chọn (*) | trống | Đội máy Etsy, tách bằng `,` hoặc `;`. Đổi `acc32` thành máy có số đuôi 32 theo quy ước; hai máy cùng số thì không đoán. | `:94-99`; `erp_meta.py:545-569` |
| `ERP_LISTING_MACHINE` | Tuỳ chọn (*) | trống | Máy nhận khi thẻ **không khai** `acc:`/`machine:`. Thẻ đã khai `acc:` mà không tra ra máy thì **không** rơi về đây — bị từ chối, vì gửi sai máy là ảnh lên nhầm shop. | `listing_bridge.py:111`, `listing_bridge.py:197-212`, `listing_bridge.py:224-236` |
| `ERP_LISTING_TIMEOUT_SECONDS` | Tuỳ chọn | `120` | Giây chờ **mỗi** lần gọi bản Listing, dùng chung cho `enqueue` và `queue`. Chỉ nhận số nguyên dương; `0`, số âm, chữ đều rơi về 120. | `listing_bridge.py:45`, `listing_bridge.py:100`, `listing_bridge.py:112`, `listing_bridge.py:300`, `listing_bridge.py:335` |

(*) Thẻ phải tra ra được **một** máy, theo thứ tự: `machine:` trên thẻ → máy
sổ tài khoản ghi cho `acc` đó → quy ước số đuôi với `ERP_LISTING_MACHINES` →
`ERP_LISTING_MACHINE` (chỉ cho thẻ không khai tài khoản)
(`erp_meta.py:591-639`; `listing_bridge.py:209-212`). Không tra ra thì
`payload` ném lỗi, thẻ không đi (`:224-236`).

Sổ tài khoản (`acc` → máy, tên shop) app gộp từ biến môi trường, file trên
đĩa và `FLOW_ACC_SHEET_URL` (`flow_web/service.py:14163-14180`); script rời
xin sổ qua `GET /api/erp/account/book` khi có `--flow-web-url`
(`scripts/run_agent_bot.py:200-225`). Không có sổ thì chỉ còn quy ước số.

Hai biến của bot ảnh hưởng trực tiếp tới listing, không nằm trong `from_env`:

- `ERP_AGENT_AUTORUN_COOLDOWN_SECONDS` — mặc định 900 (`agent_bot.py:116`,
  `agent_bot.py:304-307`). `listing_pass` dùng khoá nguội riêng `listing:<thẻ>`
  (`agent_bot.py:3108-3110`): một thẻ vừa bị bản Listing *từ chối* (không ghi sổ) phải
  chờ chừng ấy giây mới được giao lại.
- `ERP_AGENT_DRY_RUN` — xem "Chạy khô".

Và bot phải bật đã: `ERP_AGENT_TOKEN`, `ERP_AGENT_SOURCE_STATUS`,
`ERP_AGENT_POLL_SECONDS` > 0 — khối "Agent bot" trong `.env.local.example:43-109`.

## Cách viết thẻ ERP

Khối *Thuộc tính* là phần người gõ, ERP trả về trong trường `meta`
(`taskDetail`/`taskFull`) hoặc `meta_custom` (`taskMeta`)
(`erp_meta.py:385-395`). Mỗi dòng `khoá: giá trị`; tên khoá chữ
thường không dấu, số và gạch dưới, bắt đầu bằng chữ cái (`erp_meta.py:37-40`).

```
action_1: listing
acc: acc31
sku: VT_1_001
```

- **`action_1`** — khoá khớp `action`, `action_1`, `action_2`… (`erp_meta.py:46`,
  `erp_meta.py:264-284`). Một dòng chứa được nhiều action tách bằng `,` hoặc `;`.
  Giá trị được chuẩn hoá: chữ thường, khoảng trắng và `-` thành `_`
  (`erp_meta.py:153-156`), nên `Listing Etsy` và `listing-etsy` đều là `listing_etsy`.
  Chữ hợp lệ, đúng `LISTING_ACTIONS` (`erp_meta.py:120-131`):
  `listing`, `listings`, `list`, `etsy`, `etsy_listing`, `listing_etsy`,
  `dang_listing`, `len_listing`.
  Thẻ **không có** dòng `action_*` nào là thẻ ảnh thường — không bị ảnh
  hưởng gì (`agent_bot.py:975-992`).
- **`acc`** — hoặc `account`, `etsy_acc`, `etsy_account`, `shop`, `acc_id`
  (`erp_meta.py:50`). Không gõ dòng này thì bot đọc **nhãn** trên thẻ theo
  dạng `acc` + số, ví dụ nhãn `acc31` (`erp_meta.py:45`, `erp_meta.py:572-578`, `erp_meta.py:579-588`). Hai
  nhãn cùng chỉ tài khoản thì không đoán. Gửi làm `etsy_account_id`
  (`listing_bridge.py:272`).
- **`machine`** — hoặc `machine_id`, `may`, `pc`, `vps` (`erp_meta.py:53`).
  Viết dòng này là ghim đích danh máy, thắng mọi suy đoán (`erp_meta.py:624-631`).
- **`sku`** — hoặc `ma_sku`, `masku`, `sku_code`, `product_key`,
  `productkey` (`erp_meta.py:87`). Gửi làm `etsy_listing_sku` (`listing_bridge.py:286`).
  Trống thì bản Listing tự đặt mã; hai bên sẽ gọi cùng một sản phẩm bằng hai
  mã khác nhau (`:276-285`).

**Viết trước khi ảnh xong.** Bảng dự án không trả khối *Thuộc tính* về; bot
chỉ đọc được nó khi mở từng thẻ. Thẻ xong ảnh trước khi có `action_1` thì đã
bị đóng, và ở phạm vi board thẻ đã đóng không được đọc lại. Lỡ rồi thì gắn
đích danh bot vào thẻ đó — thẻ gắn bot được nhận không qua lọc cột
(`.env.local.example:80-82`, `:125-131`).

Payload gửi đi luôn có `etsy_publish: false` — chỉ dựng bản nháp, không có
bước nào đẩy hàng lên shop thật (`listing_bridge.py:287-289`).

## Điều kiện thẻ được giao đi

`listing_pass` (`agent_bot.py:3024-3125`) kiểm theo đúng thứ tự này; dừng ở
bước đầu tiên không qua và trả về **một dòng** trong tổng kết, không im lặng:

1. Đã có trong sổ `listed` → không giao lại, rẽ sang hỏi kết quả (`agent_bot.py:3074-3082`).
2. Thẻ đang bị "dừng" theo lệnh trên thẻ → `skipped` (`agent_bot.py:3088-3089`).
3. `listing_readiness` (`agent_bot.py:1063-1097`), đếm bằng `count_decisions` (`agent_bot.py:1100-1127`,
   tính **cả** ảnh bot không xoá được):
   - có ít nhất một ảnh trên thẻ;
   - **không còn** ảnh nào chờ 👍/👎 (ảnh 👎 coi như đã chốt — cùng lượt
     `janitor_pass` gỡ nó đi);
   - còn ít nhất **một** ảnh được giữ.
4. Có hook giao đi, tức `ERP_LISTING_API_URL` đã đặt → không thì `skipped`
   (`agent_bot.py:3106-3107`).
5. Khoá nguội `listing:<thẻ>` đã hết → không thì `skipped` (`agent_bot.py:3108-3110`).
6. Không phải chạy khô (`agent_bot.py:3111-3112`).
7. Gọi `enqueue`; chỉ ghi sổ khi bên kia trả `queue_task_id` (`agent_bot.py:3114-3125`).

Trước cả bước 1, thẻ phải lọt vào tầm quét: nằm ở cột `ERP_AGENT_SOURCE_STATUS`
(mặc định file mẫu: `Working`) hoặc được gắn đích danh bot
(`.env.local.example:71-85`). Bot **không** đọc `action_1` từ bảng — nó mở
từng thẻ trong tầm quét (`agent_bot.py:3181-3194`).

Đây là cùng một bản đếm với luật cột (`card_stage`, `agent_bot.py:1130-1168`): bot nói
"đăng được" thì bảng cũng thấy thẻ đã chốt, không có chuyện hai bên lệch.

## Không thấy thẻ nào được giao đi

Grep log theo đúng chữ trong cột đầu. Dòng tổng kết mỗi lượt là
`Agent bot: N thẻ listing — …` (`agent_bot.py:3308`).

### Chưa giao — câu `waiting` / `skipped`

| Chữ trong log | Ở đâu | Nghĩa | Làm gì |
|---|---|---|---|
| `thẻ chưa có ảnh nào để đăng` | `agent_bot.py:1092` | Thẻ chưa có ảnh nào trên nó. Nửa làm ảnh chưa chạy, hoặc chạy rồi mà chưa đăng lên thẻ. | Chờ nửa làm ảnh. Kiểm `ERP_REVIEW_AUTOPUBLISH` (`.env.local.example:39-41`). |
| `còn N ảnh chờ 👍/👎` | `agent_bot.py:1094` (luật cột nói cùng câu ở `pipeline.py:285`) | Người chưa duyệt hết. | Vào thẻ bấm nốt. |
| `không còn ảnh nào được giữ` | `agent_bot.py:1096` | Mọi ảnh đều 👎. Không có gì để đăng. | Chạy lại ảnh; thẻ ở lại cột cũ. |
| `chưa cấu hình ERP_LISTING_API_URL` | `agent_bot.py:3107` | Biến trống, hoặc đặt rồi mà chưa khởi động lại app. | Đặt biến, khởi động lại. |
| `vừa giao xong, đang chờ nguội` | `agent_bot.py:3110` | Lượt trước bản Listing từ chối (không ghi sổ), khoá nguội chưa hết. | Bình thường. Chờ `ERP_AGENT_AUTORUN_COOLDOWN_SECONDS`. |
| `đang tạm dừng theo yêu cầu trên thẻ` | `agent_bot.py:3089` | Có người bảo bot dừng trên thẻ này. | Nói "chạy đi" trên thẻ. |

### Giao hỏng — dòng `Không giao được thẻ listing <mã>: …`

Dòng ở `agent_bot.py:3119`, phần sau dấu hai chấm là lỗi của cầu:

| Phần sau dấu hai chấm | Ở đâu | Nghĩa |
|---|---|---|
| `Không gọi được bản Listing tại <url>` | `listing_bridge.py:132` | Mạng / URL sai / app bên kia chưa chạy. |
| `Bản Listing trả lỗi HTTP <mã>` | `:130` | Bên kia từ chối; 400 chữ đầu thân trả lời đi kèm. |
| `Bản Listing chưa cấu hình xong: thiếu …` | `listing_bridge.py:379` | Bên kia trả `configured: false`. Sửa ở bản Listing, không phải ở đây. |
| `Bản Listing không xếp hàng được thẻ <mã>` | `listing_bridge.py:393-396` | Bên kia không trả `enqueued` hoặc không có `queue_task.id`. |
| `khai tài khoản \`accNN\` nhưng không tra ra máy nào chạy nó` | `:226-229` | Thẻ có `acc:` mà sổ không có dòng, `ERP_LISTING_MACHINES` không có máy mang số ấy. **Không** dùng `ERP_LISTING_MACHINE` cho ca này. |
| `chưa chỉ được máy Etsy nào` | `:233-235` | Thẻ không ghi `machine:`/`acc:`, sổ không có, `ERP_LISTING_MACHINE` trống. |

### Bản Listing từ chối — dòng `Bản Listing bỏ qua thẻ <mã>: …`

Dòng ở `listing_bridge.py:383`, lý do dịch từ `SKIP_REASONS` (`:62-66`):
`thẻ khai action khác, không phải listing` · `thẻ đã ở cột Done` ·
`tên thẻ trùng tên cột`. Từ chối thì **không ghi sổ**, nên sửa thẻ xong là
lượt sau (hết nguội) giao lại được.

### Giao rồi mà thẻ đứng ở *Đang review*

| Chữ trong log | Ở đâu | Nghĩa | Làm gì |
|---|---|---|---|
| `chờ listing lên shop` | `pipeline.py:346` | Thẻ là listing, đã giao, chưa `confirmed`. Đây là trạng thái **bình thường** cho tới khi bên kia báo `completed`. | Xem dòng `waiting` của `_listing_confirm` bên dưới. |
| `chờ người làm listing` | `pipeline.py:345` | Thẻ **không** khai action listing. Máy không đóng thẻ ảnh — *Đang review* là bàn của người viết listing. | Nếu đáng ra là thẻ listing: thiếu `action_1`. Thêm vào rồi gắn đích danh bot (thẻ đã qua tầm quét board). |
| `máy Etsy đang chạy (queued)` / `(in_progress)` | `agent_bot.py:1060` | Bên kia còn chạy. | Chờ. |
| `bản Listing không còn giữ lượt <id> trong ảnh chụp hàng đợi` | `listing_bridge.py:345` | **Không tra ra**, không phải hỏng. Bên kia cắt ảnh chụp còn ít lượt gần nhất. Bot không giao lại. | Kiểm tay bằng `GET …/queue?machine_id=<máy>`; xem shop. |
| `listing HỎNG bên máy Etsy: …` | `agent_bot.py:3317` | Status khác `completed`/`queued`/`in_progress`. Sổ vẫn giữ dòng → **không** tự giao lại. | Người vào shop xem; bản nháp có thể đã dựng một nửa. |
| `Không hỏi được kết quả listing của <mã>: …` | `agent_bot.py:3013` | Gọi `queue` hỏng (mạng, HTTP). | Như phần "Giao hỏng". |

### Thẻ con đã lên shop mà vẫn không tự đóng

Đây là **ranh giới còn lại**, không phải hỏng. Ảnh và 👍 nằm trên **thẻ con**,
còn `action_1: listing` khai trên **thẻ cha**. Bot đã biết đọc kèm: thẻ con
trong cụm listing mượn `action_1` của cha nên nó **được giao** lên Etsy, sổ ghi
theo mã thẻ con, lượt sau **hỏi lại** đúng biên lai ấy
(`agent_bot.py:inherited_meta_node`).

Nhưng luật cột bên app đọc *Thuộc tính* của **chính thẻ con**
(`service.py:15110-15127` dựng `card_stage` từ meta riêng của con), mà fan-out tạo
thẻ con **trắng** (`service.py:14892-14946`). Con không khai `action_1` nên
`_leave_review` trả `Move("", "chờ người làm listing")` (`pipeline.py:345`) —
tức là app **không ghi trạng thái nào cả**, nước cuối dừng trước cả cổng đóng
`service.py:15195`.

Chỗ nhìn thấy điều đó là **tổng kết của bot**, không phải log của app: dòng

> Agent bot đẩy N thẻ sang cột kế — `<mã thẻ con>` chờ người làm listing.

(`agent_bot.py`, cuối `run_once`), và trong JSON của `POST /api/agent-bot/run`
là `moved[].result == {"moved": false, "reason": "chờ người làm listing"}`.

Đừng tìm câu *"Giữ nguyên trạng thái Task …: thẻ này không khai action
listing…"* trong log app: câu ấy nằm trong nhánh `if job_id:`
(`service.py:15089-15094`), mà đường của bot gọi `advance_erp_pipeline(task_id)`
**không kèm `job_id`** (`service.py:22738-22744`), nên nó không bao giờ in ra.
Bản đầu của runbook này chỉ sai đúng chỗ đó.

Từ đợt T12, đề nghị bị từ chối chỉ hỏi lại mỗi `ERP_AGENT_AUTORUN_COOLDOWN`
giây một lần, không phải mỗi lượt quét; giữa hai lần ấy tổng kết ghi
`{"task": "<mã>", "skipped": "vừa đề nghị, đang chờ nguội"}`.

Thấy dòng đó nghĩa là **đã lên shop rồi**, chỉ còn cột chưa đổi. Hai cách:

- Tay: thêm `action_1: listing` vào khối *Thuộc tính* của thẻ con. Lượt quét sau
  bot tự đóng.
- Gốc: cho fan-out chép dòng định tuyến xuống thẻ con, hoặc cho cổng đóng đọc
  meta thừa kế. Cả hai đều nằm trong `service.py` — xem N1/N2 và câu hỏi Q1 của
  `tasks/prd-list-tu-dong-etsy.md`.

### Không có dòng nào về thẻ đó cả

Thẻ không lọt tầm quét. Kiểm theo thứ tự:

1. Có dòng `Agent bot bật: quét mỗi …` (`agent_bot.py:3384`) không? Không có
   thì bot tắt — thiếu `ERP_AGENT_TOKEN` hoặc `ERP_AGENT_POLL_SECONDS` = 0.
   Thiếu token thì trong app chỉ có đúng một dòng `Agent bot tắt: chưa đặt
   ERP_AGENT_TOKEN.` do `build_agent_bot` in ra (`agent_bot.py:3462-3468`);
   `run_forever` không được gọi nên hai dòng của nó không hiện.
2. Thẻ có ở cột `ERP_AGENT_SOURCE_STATUS` không? Bot chỉ nhặt từ cột ấy, trừ
   thẻ gắn đích danh (`.env.local.example:71-85`).
3. Thẻ đã đóng chưa? Cột đóng máy không mở lại (`pipeline.py:62`, `pipeline.py:253-254`).

## Chạy khô

Bật bằng `ERP_AGENT_DRY_RUN=1` (`agent_bot.py:326`) hoặc `--dry-run` của
script rời (`scripts/run_agent_bot.py:232-235`, `:268-269`). Ví dụ kiểm nhanh
một lượt: `python scripts/run_agent_bot.py --once --dry-run`.

Trong `listing_pass`, chạy khô được kiểm **sau** điều kiện ảnh, hook và nguội
(`agent_bot.py:3111-3112`). Nên `{"task": "<mã>", "dry_run": true}` trong
tổng kết nghĩa là "đủ điều kiện, lượt thật sẽ giao". Không gọi `enqueue`,
không ghi sổ, không đặt khoá nguội (`mark_autorun` ở `agent_bot.py:3113`, sau nhánh khô).
Log tổng kết ghi `chạy khô` (`agent_bot.py:3323`).

Hai chỗ chạy khô **không** chặn, cần biết trước:

- `_listing_confirm` (`agent_bot.py:2989-3022`) không kiểm `dry_run`: thẻ đã có trong sổ
  vẫn được hỏi `queue` (chỉ đọc) và vẫn có thể được ghi `confirmed: true`.
- `pipeline_pass` chạy khô thì chỉ ghi `{"to": …, "dry_run": true}` chứ không
  gọi hook (`agent_bot.py:2891-2892`), nên cột **không** đổi.

## Kiểm tay

- Bản Listing có sống không:
  `curl "$ERP_LISTING_API_URL/api/etsy/browser-copy/queue?machine_id=etsy-vn31"`.
  Cầu chỉ đọc `tasks[].id`, `tasks[].status`, `tasks[].error`,
  `tasks[].erp_done_move.moved` (`listing_bridge.py:335-359`). Lược đồ đầy
  đủ và cách xác thực của endpoint — **chưa xác minh**, app đó ngoài repo.
- Quét ngay một lượt trong app: `POST /api/agent-bot/run`
  (`flow_web/main.py:274`), đọc mảng `listing` trong JSON trả về.
- Sổ bot: `data/agent_bot_state.json` (`agent_bot.py:1258`; `data/` theo
  `FLOW_DATA_DIR`, `flow_web/paths.py:19`), khoá `listed` (`agent_bot.py:1232`). **Chỉ
  đọc.** Đây không phải `data/state.json`.
- Grep log: `grep -E 'thẻ listing|Giao thẻ listing|Bản Listing|listing của' <log>`.
  Dòng giao thành công: `Giao thẻ listing <mã> cho máy <máy>, hàng đợi <id>
  bên bản Listing (<n> ảnh).` (`listing_bridge.py:398-404`).

## Trạng thái sản xuất hvg-pc — soi ngày 10/09/2026 lúc 15:25

Soi bằng API, `Get-FileHash` và đọc mã controller ngay trên máy; không in giá
trị bí mật. Bản soi trước (14:18) ghi `ERP_LISTING_API_URL` trỏ cổng 8010,
danh sách máy rỗng, không ai rút hàng đợi. Ba chỗ đó đã sửa. Còn một chỗ
chưa: **cửa vào**.

| Mắt xích | Đang thế nào | Hệ quả |
|---|---|---|
| Bot ERP trên :8000 | **Chạy**, quét mỗi 120s. Khởi động lại 14:24 để nạp env mới | Nửa đầu sống |
| `ERP_LISTING_API_URL` | `http://127.0.0.1:8001`, tức controller Listing2. Sửa lúc 14:24; bản cũ ở `C:\HaviGroup\flow-v2\_backup\20260910-1430\` | Bot gọi vào chỗ có người nghe |
| `ERP_LISTING_MACHINES` | `etsy-vn31`…`etsy-vn36`, `etsy-16` | `acc31` ra `etsy-vn31` theo số đuôi. `acc32` và `acc16` đã bỏ (xem dưới), hai máy ấy còn trong danh sách nhưng không có thẻ nào gọi tới |
| **Cửa vào** `POST :8001/api/etsy/browser-copy/enqueue` | **Chỉ dựng việc từ thẻ Trello.** Gọi `prepare` với đúng hình payload của cầu trả `configured=False, missing=trello_credentials` | **Thẻ ERP thật chưa vào được hàng đợi.** Bot sẽ ghi `Bản Listing chưa cấu hình xong: thiếu trello_credentials.` (`listing_bridge.py:372-374`), không ghi sổ, không có bản nháp sai nào |
| Thợ rút hàng đợi | Agent 2.11.1 trên 7/8 máy: `capa-hinh`, `etsy-16`, `etsy-vn31`, `etsy-vn33`…`etsy-vn36`. `etsy-vn32` bị giữ ở 2.10.71 — **không cần vá**, `acc32` đã bỏ | Việc nào đã nằm trong hàng đợi thì có máy nhận |
| Chạy thử | 15:10 `etsy-vn31` nhận `etsy-smoke-3e08cc8245ef`; 15:16 `etsy-vn35` nhận `etsy-smoke-0ba3dc0c9b36`. Cả hai báo `failed: Việc ERP không có ảnh nào để đăng lên Etsy.` | Đúng như thiết kế: gói smoke không có link ảnh, agent dừng trước khi mở Etsy |
| Sổ bot | `listed` rỗng | Chưa có bản nháp nào từ đường ERP |

Nói gọn: **nửa sau đã nối, cửa vào còn đóng.** Chi tiết hai phần ở hai mục
dưới.

## Thợ rút hàng đợi ERP (agent 2.11.1 trên máy Etsy)

Bản vá nằm ngoài repo, ở `C:\Listing2\scripts\listing2_vps_agent.py` trên
hvg-pc (sha `3aa0206c831c18ae`). Bản ghi để dựng lại, thử lại và quay lui:
`docs/listing2-agent-2.11.1/`.

Mỗi phút, Scheduled Task trên máy Etsy chạy `listing2_vm_runner.ps1`. Runner
so sha với `GET /api/listing2/agent/manifest`, kéo agent mới nếu khác, rồi
chạy một lượt `run_once`:

1. Heartbeat, rồi hỏi `POST /api/listing2/tasks/next` (đường Trello).
2. Có thẻ Trello thật: làm thẻ đó rồi hết lượt. **Thẻ Trello luôn đi trước.**
3. Chỉ nhận việc đồng bộ cột nền (`payload.background_sync`), hoặc không nhận
   gì: sang hàng đợi ERP. Controller giao việc đồng bộ nền gần như mỗi phút.
   Bản 2.11.0 dừng lượt ở đó nên hàng đợi ERP không bao giờ tới lượt; 2.11.1
   sửa đúng chỗ này.
4. `GET /api/etsy/browser-copy/queue` lấy ảnh chụp hàng đợi, rồi
   `POST /api/extension/etsy-browser-copy/next` cho từng tài khoản đang có
   việc. Controller chỉ trao việc khớp tài khoản, khớp máy ghim, mỗi tài khoản
   một việc một lúc.
5. Việc không ghim máy thì bỏ qua, trừ máy bật
   `LISTING2_ERP_ACCEPT_UNPINNED=1`. Ghim sai máy là ảnh lên nhầm shop.
6. Tải ảnh từ `images[].download_url` (hoặc `imageUrls`); link tương đối thì
   ghép với địa chỉ backend. Không có ảnh thì báo `failed`, không mở Etsy.
7. Cần SKU và một nguồn mẫu: `templateListingId`, `templateListingUrl`,
   `templateSourceSku` hoặc từ khoá tìm mẫu. Thiếu thì báo `failed`, không
   tạo Draft.
8. Chạy đúng đường extension Etsy mà thẻ Trello đang dùng: chép listing mẫu,
   thay ảnh, lưu **Draft**. Không có bước publish.
9. `POST /api/extension/etsy-browser-copy/report` báo `completed` hoặc
   `failed` kèm lỗi. Bot ERP đọc lại qua `GET …/queue` (mục "Câu quan trọng
   nhất").

Công tắc, đặt ở biến môi trường **người dùng** trên từng máy ảo:

| Biến | Tác dụng |
|---|---|
| `LISTING2_ERP_QUEUE=0` | Tắt thợ ERP trên máy đó. Đường Trello không đổi. |
| `LISTING2_ERP_ACCEPT_UNPINNED=1` | Cho máy nhận cả việc không ghim máy. Mặc định tắt. |

Quay lui cả đội về 2.10.99, chạy trên hvg-pc:

```powershell
Copy-Item C:\Listing2\deploy-backups\agent-2.10.99-20260910-145602\scripts\listing2_vps_agent.py C:\Listing2\scripts\listing2_vps_agent.py -Force
```

Lượt runner kế tiếp thấy sha khác và kéo bản cũ về. Chưa thử quay lui trên
máy ảo thật.

Kiểm tay: trong `GET :8001/api/etsy/browser-copy/queue`, việc đã có máy nhận
mang `claimed_machine_id` và `worker_id=listing2-agent-<máy>`.

### Giới hạn đã biết

- **Gói tự triển khai sẽ đè bản vá.** `Listing2AutoDeploy` chạy 2 phút một
  lần, áp mọi `C:\Listing2\deploy-inbox\Listing2-*.zip`, và gói có
  `scripts\listing2_vps_agent.py`. Gói mới về là cả đội quay lại bản của
  gói. Phải đưa bản vá vào mã nguồn Listing2 trước gói kế tiếp.
- Extension xoá **mọi** ảnh của listing mẫu, kể cả bảng màu:
  `keepColorChart` không được đọc.
- Mỗi tài khoản một việc một lúc; thẻ Trello thật đi trước.
- Controller coi việc quá 8 phút là hỏng (`draft_may_exist`), agent cho 35
  phút. Báo muộn thì trạng thái bị ghi đè. Runner còn bị cắt ở 20 phút.
- Hàng đợi nằm trong bộ nhớ controller: khởi động lại :8001 là mất.
- `etsy-vn32` giữ ở 2.10.71 nên việc `acc32` sẽ nằm chờ — **không phải việc cần
  làm**: hai tài khoản `acc32` và `acc16` đã bỏ khỏi đội Etsy (chốt 11/09/2026),
  không thẻ nào khai chúng nữa. Thẻ nào lỡ khai thì sửa thẻ, đừng đi nâng máy.
- Không có đường báo tiến độ giữa chừng, chỉ có kết quả cuối.
- Xong việc, controller vẫn thử dời thẻ Trello theo `card_id`. Việc ERP không
  có thẻ Trello nào, nên lệnh dời vô hại.

## Cửa vào còn đóng

Thẻ ERP phải vào được hàng đợi thì thợ mới có việc. Cầu gọi
`POST /api/etsy/browser-copy/enqueue` kèm `erp_task_id`, tưởng đầu kia đọc
thẳng thẻ ERP. Controller :8001 không làm vậy. Route ấy gọi
`prepare_etsy_browser_copy` (`C:\Listing2\flow_web\service.py:12397`), và
hàm này chỉ biết thẻ Trello: cần khoá Trello và `trello_card_id`, bỏ qua mọi
trường `erp_*` — lược đồ `CreateJobRequest` bên đó không có trường `erp_`
nào. Hiện nó dừng ngay ở bước khoá Trello, trước cả bước tìm thẻ, nên chỉ
từ chối. Nếu sau này ai điền khoá Trello và một thẻ mặc định vào cấu hình
controller (`trello_config.card_id`, đang rỗng), thẻ ERP sẽ mang **ảnh của
thẻ Trello ấy**. Khi đó còn tệ hơn bị từ chối.

Chỉ instance `HaviGroup Listing ERP Trial` mới đọc thẳng thẻ ERP. Nó chạy ở
:8010, trong `C:\HaviGroup\listing-erp`, bản flow-v2 ngày 20/08. Instance này
đang tắt, chỉ nghe `127.0.0.1`, và không máy ảo nào hỏi hàng đợi của nó.

Đường mở cửa ít đụng nhất là
`POST :8001/api/etsy/browser-copy/enqueue-direct` (`C:\Listing2\flow_web\service.py:12910`).
Route này nhận thẳng `sku`, ảnh và nguồn mẫu, không cần Trello, và đúng hình
agent 2.11.1 đang đọc. Việc cần làm:

1. flow-v2 tải ảnh 👍 từ ERP (nó có khoá ERP) và thả vào
   `C:\Listing2\data\downloads\erp-<thẻ>\`. Controller phục vụ thư mục này ở
   `/files/downloads/` (`C:\Listing2\flow_web\main.py:302`); máy ảo tải qua
   tailnet như ảnh Trello.
2. Gửi `images[].download_url` là link tương đối `/files/downloads/erp-<thẻ>/…`.
3. Thẻ phải chỉ ra listing mẫu. Route trả `400 … missing a template source`
   cho việc không có nguồn mẫu. Cần một dòng trên thẻ, ví dụ
   `template: <SKU hoặc link listing mẫu>` — **chưa chốt**. Lưu ý T10: dòng
   `template` của cha không xuống con.
4. Giữ `GET …/queue` để hỏi kết quả như cũ.

Việc này sửa `flow_web/listing_bridge.py` và `flow_web/erp_meta.py` trong
repo này, rồi triển khai flow-v2 lên hvg-pc. **Chưa làm.**

## Chưa xác minh

- Lược đồ, xác thực, và nghĩa chính xác của `erp_done_move.moved` ở bản
  Listing (`listing_bridge.py:353` chỉ đọc bool). Khi `moved` là true, sổ ghi
  `card_moved_by_listing` để biết cột đổi vì bên kia hay vì luật cột bên này
  (`agent_bot.py:1406-1407`).
- Giá trị thật của các biến trên hvg-pc: chỉ ghi địa chỉ và danh sách máy,
  không in khoá bí mật. Bảng trạng thái ở trên ghi theo cách soi ấy.
- Một bản nháp Etsy thật đi trọn từ thẻ ERP: chưa có, vì cửa vào còn đóng.
  Hai lượt chạy thử mới chứng minh nửa sau (hàng đợi → máy ảo → báo lại).

## Liên quan

- PRD gốc và checklist chạy thật: `tasks/prd-list-tu-dong-etsy.md`.
- Khối "Thẻ listing Etsy" và "Agent bot" trong `.env.local.example`.
- Luật cột đầy đủ: docstring đầu `flow_web/pipeline.py:1-33`.
- Bản ghi agent máy Etsy 2.11.1 (script vá, diff, bộ thử): `docs/listing2-agent-2.11.1/`.

## Cột *Đang review* → Etsy (`flow_web/review_lister.py`, 10/09/2026)

Luật người vận hành chốt: kéo thẻ sang cột **Đang review**, khai `account`
(đăng vào tài khoản nào) và `copysku` (chép bài mẫu từ SKU nào trên tài khoản
ấy). Ảnh đăng lên là mọi ảnh trên thẻ, theo thứ tự: ảnh bìa, tệp kéo thả
thẳng vào thẻ (cũ trước), ảnh đính trong bình luận. Bỏ ảnh bị 👎, tối đa 9
tấm.

Chạy riêng một tiến trình, không đi qua vòng quét của agent bot, và đi cửa
`enqueue-direct` nên không cần Trello:

1. Quét bảng, lấy thẻ ở *Đang review*. Mỗi lượt soi tối đa 5 thẻ bằng
   `taskFull`, thẻ lâu chưa soi đi trước. Token bot có trần 60 request/phút
   và agent bot dùng chung nó, nên đừng nâng số này. Thẻ đã khai đủ `account`
   và `copysku` thì đọc thêm `taskAttachments` và `taskDetail` bằng **khoá
   app** (`ERP_API_KEY`/`ERP_API_SECRET`). Đọc hỏng thì thẻ ghi lỗi, lượt sau
   đọc lại — không đăng thiếu ảnh.
2. Thiếu `account`/`copysku`/ảnh thì ghi `waiting`, không gửi gì.
3. Đủ thì tải ảnh từ ERP (ảnh `/private/files/` đi qua `download_file` với
   `ERP_API_KEY`/`ERP_API_SECRET`) vào `ERP_LISTING_FILES_DIR\erp-<thẻ>\`.
4. Gọi `POST /api/etsy/browser-copy/enqueue-direct` với
   `templateSourceSku = copysku`, ảnh là đường dẫn tương đối
   `/files/downloads/erp-<thẻ>/…`, máy tra từ tài khoản (acc31 → etsy-vn31).
5. Ghi sổ `data/review_lister.json`: mỗi thẻ chỉ giao **một lần**, vì thẻ đăng
   xong vẫn nằm ở *Đang review*. Trước khi giao còn hỏi hàng đợi của bản
   Listing (lọc theo máy): thẻ đã có lượt đang chờ, đang chạy hay đã xong thì
   nhận lượt ấy vào sổ, không giao lại. Lượt hỏng không tính.
6. Hỏi lại hàng đợi; xong thì bình luận "Đã list xong lên Etsy (bản nháp)."
   lên thẻ.

Trên hvg-pc:

| Việc | Lệnh / chỗ |
|---|---|
| Biến mới | `ERP_LISTING_FILES_DIR=C:\Listing2\data\downloads` trong `.env.local` (bản lưu `.env.local.bak-review-lister-20260910-154333`) |
| Chạy nền | Scheduled Task `HaviGroup Review Lister` (khởi động máy + đăng nhập, **lặp 5 phút một lần**, lỗi thì chạy lại sau 1 phút, chặn chạy hai bản). Nó gọi `scripts\run-review-lister.ps1` → `python -m flow_web.review_lister --loop 300`, log `C:\HaviGroup\logs\review-lister.log` |
| Dựng lại task | `powershell -NoProfile -ExecutionPolicy Bypass -File C:\HaviGroup\flow-v2\scripts\install_review_lister_task.ps1` trong cửa sổ admin. Script dừng mọi lister chạy tay trước khi bật task |
| Đăng ngay một thẻ | `python -m flow_web.review_lister --task TASK-…` trong `C:\HaviGroup\flow-v2`; lệnh này cũng hỏi lại các lượt đã giao và bình luận thẻ nào xong |
| Đăng lại thẻ đã đăng | thêm `--again` (chỉ đi với `--task`, một lượt). Bỏ qua sổ và lượt đã xong; lượt đang chờ/chạy thì vẫn chặn. Sổ giữ mã lượt cũ ở `replaces`. **Bản nháp cũ trên Etsy phải xoá tay.** |
| Tắt | `Stop-ScheduledTask` rồi `Disable-ScheduledTask -TaskName 'HaviGroup Review Lister'`. Chỉ giết tiến trình python thì trong 5 phút task tự bật lại |
| Bị giết | Script nào giết python khớp `flow_web` trong `C:\HaviGroup\flow-v2` (ví dụ `C:\HaviGroup\deploy-hvg-pc.ps1`) là giết cả lister. `RestartCount` của task không cứu: nó chỉ chạy lại khi task không khởi động được. Trigger lặp 5 phút mới cứu. 11/09/2026 lister im 15 phút vì thiếu trigger này |
| Chạy tay `--loop` | Wrapper thấy một vòng quét khác đang chạy thì thoát, không bật bản thứ hai |

Bản nháp thật đầu tiên: TASK-2026-04789 (`account: ETSY - VN31`,
`copysku: ORC5_1439`, `sku: SKUTEST`) → lượt `etsy-copy-fa1a06d575cf` trên
etsy-vn31, 2 ảnh, `draftSaved: true` lúc 16:12 ngày 10/09/2026. Bình luận
"đã list xong" lên thẻ lúc 16:18.

Lượt ấy lộ một lỗi: route `enqueue-direct` bọc kết quả trong
`etsy_browser_copy`, còn code đọc ở tầng ngoài, nên coi là hỏng dù bên kia đã
nhận. Sổ bỏ trống, và vòng sau sẽ đăng thêm một bản nháp. Đã sửa cả hai chỗ:
đọc đúng lớp bọc, và hỏi hàng đợi trước khi giao (bước 5).

Hai bản nháp đầu còn lộ hai chỗ mù về ảnh. Người trong nhóm báo: "nó lấy
mỗi cái ảnh bìa".

- **Tệp treo thẳng trên thẻ.** `taskFull` không trả chúng. TASK-2026-05133 có
  chín tệp (ảnh bìa + tám ảnh Flow), bản nháp chỉ có ảnh bìa. Chúng nằm ở
  `taskAttachments`, trả mới trước.
- **Tệp đính trong bình luận.** Token bot không thấy tệp riêng tư, nên bình
  luận về với `attachments` rỗng. Khoá app thấy đủ: TASK-2026-04789 có năm
  tấm thêm tay (hai bình luận lúc 16:09), bản nháp không có tấm nào.
- **Trường `image` của bình luận là ảnh đại diện người bình luận**, không phải
  ảnh đính kèm. Hai bình luận đính hai bộ tệp khác nhau vẫn trả cùng một
  `image`: tệp công khai `/files/…`, 512×512, chân dung. Đối chiếu thì nó
  trùng đúng `User.user_image` của người viết. Lister cũ đăng tấm ấy làm ảnh
  thứ hai của 04789. Nay bỏ hẳn trường này. `count_card_images` của agent bot
  vẫn đếm trường này là ảnh.

Đăng lại bằng `--again` lúc 17:50 ngày 10/09/2026, cùng máy etsy-vn31:

| Thẻ | Lượt mới | Ảnh | Thay lượt cũ |
|---|---|---|---|
| TASK-2026-05133 | `etsy-copy-a5bc3bb6ffb8` | 9: bìa + 8 ảnh Flow | `etsy-copy-6eb09f502cb1` |
| TASK-2026-04789 | `etsy-copy-f441048208bc` | 6: bìa + 5 tấm thêm tay | `etsy-copy-fa1a06d575cf` |

Cả hai về `draftSaved: true` và đã có bình luận trên thẻ. Máy dọn đúng 9 và
6 tệp tải về. Extension chỉ bấm "Save as draft" khi bộ đếm "Add photos N
remaining" của Etsy đã đủ số tệp; thiếu thì dừng với lỗi "Etsy chỉ hiển thị
x/9 ảnh". Nhưng con số ấy không về tới kết quả: background trả một kết quả
dựng sẵn ngay khi Etsy chuyển trang. Vì vậy người vẫn phải mở bản nháp xem một
lần. Bản nháp mới 9 ảnh hiện "11 remaining", 6 ảnh hiện "14 remaining".

Ảnh chụp "chỉ có ảnh bìa" gửi vào nhóm lúc 17:22 là bản cũ lưu lúc 16:31: nó
có trước lượt đăng lại. Hai bản trùng tiêu đề, mở nhầm là thấy lại bản cũ.
Bản nháp cũ không tự mất.
Etsy không trả mã listing, nên phải xoá tay: hai bản cũ cùng SKU với bản mới
(`SKUTEST` còn 2 ảnh, `SKUTESTTEST` còn 1 ảnh + video).

Soát lại lúc 21:30 cùng ngày, không cần remote. Máy etsy-vn31 tự mở hai bản
nháp mới, chỉ đọc (cách làm ở mục dưới):

| Thẻ | Listing | Bộ đếm Etsy | So với tệp đã giao |
|---|---|---|---|
| TASK-2026-05133 | 4572586100 | "Add photos 11 remaining", không video | 9/9 khớp, đúng thứ tự |
| TASK-2026-04789 | 4572570845 | "Add photos 14 remaining", không video | 6/6 khớp: bìa + 5 tấm thêm tay, không có ảnh đại diện |

Nút "Save draft" ở cả hai đều mờ: không có sửa dở. Cả bốn bản (hai cũ, hai
mới) mang chung tiêu đề của listing mẫu. Bản nào cùng SKU mà không phải hai
mã trên là bản cũ, xoá được.

### Soát bản nháp không cần remote

Dùng việc chỉ đọc của bản Listing: `POST /api/listing2/tasks` trên hvg-pc
(cổng 8001), luôn kèm `verifyOnly: true` và `machineId` của máy Etsy.
`trelloUrl` phải là link thẻ `/c/...`: link bảng kèm `machineId` sẽ đổi bảng
của máy. Việc chỉ đọc không đẩy thẻ sang Done. Xem kết quả ở
`GET /api/listing2/tasks?machine_id=<máy>`.

1. **Tìm bản nháp theo SKU.** `verifyTitle` là SKU, `verifyUrl` là
   `https://www.etsy.com/your/shops/me/tools/listings?state=draft&sort=update_date&search_query=<SKU>`.
   Extension lấy link đầu tiên có chữ ấy. Danh sách xếp theo lần sửa gần
   nhất, nên ra bản mới nhất. Kết quả có `draftUrl`, trong đó có mã listing.
   Việc sẽ báo `failed` "Draft editor chưa hiển thị đủ tiêu đề hoặc ảnh" vì
   tiêu đề không chứa SKU. Bỏ qua lỗi ấy, lấy `draftUrl`.
2. **Mở trình sửa.** `verifyTitle` là `__INSPECT_EDITOR__`, `verifyUrl` là
   `draftUrl` ở bước 1. Kết quả có `optionLabels` chứa "Add photos N
   remaining": số ảnh là 20 − N. `mediaDebug.mediaTiles` là từng ô ảnh, kèm
   link ảnh `i.etsystatic.com`.
3. **So ảnh.** Tệp đã giao còn ở `C:\Listing2\data\downloads\erp-<mã thẻ>`
   trên hvg-pc. Máy Etsy dọn bản của nó, bản trên hvg-pc thì còn.

Bẫy:

- Tìm theo tiêu đề vô dụng: bản nháp giữ tiêu đề của mẫu, nhiều bản trùng
  nhau.
- SKU ngắn khớp cả SKU dài chứa nó. Tìm `SKUTEST` cũng ra bản `SKUTESTTEST`.
- Chỉ ra bản mới nhất. Bản cũ thứ hai trở đi thì cách này không với tới.
- `imagePreviewCount` không phải số ảnh. Nó đếm cả ảnh xem trước (6 ảnh ra
  8, 9 ảnh ra 11), và ra 1 nếu ảnh chưa tải kịp. Đọc bộ đếm "remaining".
- Bước 2 mà thiếu `verifyUrl` thì extension tìm tab trình sửa đang mở. Không
  có tab nào thì việc hỏng với "Không tìm thấy tab Etsy listing editor đang
  mở." Không hại gì.

### Theo dõi từ máy dev: `flow_web/listing_watch.py`

Hai bước trên gói thành một lệnh, chạy ở máy dev, không cần ssh:

```bash
.venv/bin/python -m flow_web.listing_watch               # theo dõi, bản nháp mới lưu thì tự soát
.venv/bin/python -m flow_web.listing_watch --no-check    # chỉ in trạng thái
.venv/bin/python -m flow_web.listing_watch --card TASK-2026-05133   # soát ngay một thẻ
.venv/bin/python -m flow_web.listing_watch --sku SKUTEST --expect 6 # soát theo SKU
```

Lệnh in một dòng mỗi khi một việc đăng đổi trạng thái: thẻ, SKU, máy, số ảnh
đã giao, trạng thái. Việc hỏng thì in kèm lỗi. Việc xong có `draftSaved` thì
lệnh soát luôn:

```
[21:53:40] TASK-2026-05133 soát SKUTESTTEST trên etsy-vn31: listing 4572586100 · 9/9 ảnh · không video · ĐÚNG
           https://www.etsy.com/your/shops/me/listing-editor/edit/4572586100
```

- Lúc mở lệnh, việc đã xong từ trước không bị soát lại. Muốn soát thẻ cũ thì
  dùng `--card`.
- Mỗi lượt soát đặt hai việc chỉ đọc lên máy Etsy. Agent nhận việc của bản
  Listing trước hàng đợi ERP, nên mỗi thẻ chậm thêm 1-3 phút. Hàng dài thì
  chạy `--no-check`.
- `--card` thoát mã 2 khi lệch hoặc không soát được, mã 0 khi đúng.
- Lệnh gọi `http://100.75.125.80` (cổng 80). Trên hvg-pc có portproxy
  `0.0.0.0:80 → 127.0.0.1:8001`. Gọi thẳng cổng 8001 qua Tailscale thì gặp
  `tailscaled`, trả 404. Đổi địa chỉ bằng `--base`.
- Lệnh không đọc được lý do thẻ chưa được nhận (thiếu `account`, thiếu
  `copysku`…). Lý do nằm ở log của lister trên hvg-pc:

```bash
ssh hvg-pc 'powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Content C:\HaviGroup\logs\review-lister.log -Tail 20 -Wait -Encoding UTF8"'
```

Từ 11/09/2026 lister chạy bằng Scheduled Task, khởi động lại máy tự lên. Hai
file `.ps1` phải lưu **UTF-8 có BOM**: PowerShell 5.1 đọc file không BOM theo
bảng mã ANSI, chữ tiếng Việt vỡ và nuốt mất dấu `"` đóng chuỗi — task báo
`LastTaskResult 1`, log ghi `The string is missing the terminator`.

Giới hạn còn đó: hàng đợi của bản Listing nằm trong bộ nhớ: bản Listing
khởi động lại giữa lúc sổ bị trống thì chốt ở bước 5 không thấy gì. Các giới
hạn phía máy Etsy ở mục trên vẫn nguyên.

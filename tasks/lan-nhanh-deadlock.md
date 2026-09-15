# PRD: làn nhanh SKU gặp ERP 500 `QueryDeadlockError`

Mốc: `origin/agent/hvg-pc-dot8` **52a9383**. Số dòng trong tệp này là của
52a9383. Test đỏ: `tests/test_lan_nhanh_deadlock.py`.

hvg-pc chạy dot8 từ 14:31:35 (12/09). c8 chép từ 55d5acb.
- `sku.py` 0f5c945, `agent_bot.py` dc4e9f2, `service.py` be808e9: cùng blob
  ở 52a9383, 55d5acb và đỉnh 8d55fcb. Số dòng khớp bản đang chạy.
- Trước đó là dot7 (083eda9). `sku.py` cùng blob. `agent_bot.py`,
  `service.py` khác blob, nhưng dot7 → dot8 không đổi `graphql`,
  `board_snapshot`, vòng đọc bảng hay `build_sku_fast_lane`.

PRD này không có code cài đặt. Chỗ sửa chỉ trỏ dòng.

## 0. Tóm tắt

- Dòng `ERP HTTP 500: {"exc_type":"QueryDeadlockError"}`. Tất cả đều ở lượt
  đọc bảng của làn nhanh (logger `flow_web.sku`). Giờ hvg-pc.

  | Khoảng | Bản | Số dòng | Dự án | Nguồn |
  |---|---|---|---|---|
  | 12:54–13:56 | dot7 | **12** | 0027 ×4, 0068 ×3, 0013 ×2, 0018, 0024, 0087 | `briefs/ket-qua-c8-deploy-dot7.md` |
  | 14:31:35–14:42:46 (lượt đọc gần nhất của c8) | dot8 | **1**, lúc 14:41:00 | 0027 | `briefs/ket-qua-c8-canh-sau-dot8.md` |

  - Bot và service: 0 dòng deadlock ở cả hai khoảng. Khoảng dot7 có 12 dòng
    HTTP 500, đúng là 12 dòng deadlock ấy.
  - 429 thật: 0.
  - c8 canh tới 17:00. Số mới xem ở tệp của c8.
- Hệ quả: bảng gặp lỗi bị dời **300 s**. Bảng đang nóng thì thẻ vừa kéo
  chờ thêm tới 5 phút mới có mã.
- Quyết (a6, 12/09): **chỉ làm B**, tức "thử lại một lần ở nhịp kế" (mục 3,
  4). A bỏ. Dòng cảnh báo phải có đuôi, để đo tỉ lệ đọc lại thành công.
- Nguyên nhân phía ERP: **chỉ là suy đoán** (mục 1.3). Log chưa chứng minh
  deadlock rơi đúng lúc bot hay service ghi vào cùng dự án.

## 1. Làn và bot đọc bảng khác nhau ở đâu

### 1.1 Bảng so sánh

| | Làn nhanh | Bot (lượt quét chính) |
|---|---|---|
| Hàm gọi | `board=lambda project: bot.client.board_snapshot(project)[0]` (`agent_bot.py:3509`) | `self.client.board_snapshot(project)` (`agent_bot.py:1767`) |
| Query | `taskBoard(project: $project, includeArchived: false)` (`agent_bot.py:476`) | giống hệt, cùng hàm |
| Trường | `taskBoard` là JSON, query không chọn trường con. Hai bên nhận cùng payload | như trái |
| Token, bộ nhịp | cùng `bot.client`: cùng token bot, cùng `SharedRateLimiter` 50/phút (`agent_bot.py:110`, `3411`) | như trái |
| Dự án | `bot.state.projects` (`agent_bot.py:3508`) | danh sách của lượt quét (`agent_bot.py:3168`) |
| Nhịp | nhịp 15 s. Bảng nóng đọc lại sau 15 s, bảng nguội sau 300 s (`sku.py:1669–1671`) | mỗi lượt đọc mọi bảng; ngủ 120 s giữa hai lượt (`agent_bot.py:115`) |
| **Song song** | **có**: `ThreadPoolExecutor(max_workers=min(workers, len(picked)))` rồi `pool.map` (`sku.py:1655–1656`); `workers = 4` (`sku.py:1393`, env `ERP_SKU_FAST_LANE_WORKERS` 1–8 ở `1407`) | **không**: `for project in projects` (`agent_bot.py:1765`) |
| Gặp 500 | log rồi dời bảng 300 s (`sku.py:1663–1664`) | log `Không đọc được bảng`, bỏ bảng ấy trong lượt này (`agent_bot.py:1768–1770`) |

Hai bên chạy cùng lúc. `service.py:22678` gọi
`asyncio.gather(bot.run_forever(), lane.run_forever())`. Mỗi bên đẩy việc
đồng bộ vào `asyncio.to_thread` (`sku.py:1623`, `agent_bot.py:3175`).

Các chỗ khác đọc `taskBoard`:
- service: `_erp_task_board` (`service.py:13623`, query ở `13631`), cùng
  `includeArchived: false`, dùng khoá API của service;
- lister: `scan_once` (`review_lister.py:671`), tiến trình riêng, đọc tuần
  tự, mỗi lượt cách ít nhất 120 s (`review_lister.py:748`). Chú thích ở
  `review_lister.py:685` nói nó dùng chung trần với token bot.

### 1.2 Nhịp đọc song song thực tế

- Bảng nguội chỉ được đọc khi ngân sách còn chừa `_LANE_RESERVE` = 8 chỗ
  (`sku.py:1320`, `1650`). Nhịp đầu sau khởi động đọc tới 20 − 8 = **12
  bảng**, 4 luồng cùng lúc.
- Bảng đọc cùng lô sẽ đến hạn lại cùng lúc (`now + 300 s`). Nên các lô
  nhiều bảng lặp lại suốt buổi, không chỉ lúc khởi động.

### 1.3 Deadlock do đâu: suy đoán, chưa chốt

Chỉ đọc code và log thì **không chốt được**. Mã ERP không nằm trong repo
này.

**Log cho thấy gì** (c8, giờ hvg-pc):
- 13 dòng deadlock (12 trước dot8, 1 sau) rơi vào đúng sáu dự án: 0027,
  0068, 0013, 0018, 0024, 0087.
- Sáu dự án này đều có cụm bot đang giữ, với thẻ ở *Cần làm* hoặc *Đang
  làm*. Nguồn: bảng cụm của c8 lúc 11:54
  (`briefs/ket-qua-c8-thieu-dong-bang-ma.md:25–36`).
- Bảy dự án bot báo "Cột nguồn Working không khớp" (0005, 0007, 0021, 0029,
  0039, 0225, 0229) có 0 dòng.
- Bảng có thẻ gắn bot chưa có mã ở hai cột ấy là bảng **nóng**
  (`board_is_hot`, `sku.py:1479–1485`). Làn đọc bảng nóng 15 s một lần.
  Bot đặt 120 s một lượt, lượt thật còn thưa hơn. Làn đọc **ít nhất 8 lần**
  nhiều hơn.
- Suy luận, chưa kiểm: sáu dự án ấy đang nóng lúc lỗi. Làn không ghi log
  khi đọc được, nên không biết bảng nào nóng vào lúc nào.

**Đính chính bản trước.**
- Bản trước lập luận: bot đọc bảng nguội thường hơn làn mà 0 lỗi, nên
  nghiêng về "làn tự va".
- Lập luận ấy chỉ đúng cho bảng nguội, mà bảng nguội cũng 0 lỗi.
- Ở các bảng có lỗi, làn đọc thường hơn bot chừng 8 lần. Nên "bot 0 lỗi"
  không phân biệt được hai giả thuyết ở cuối mục này.

**Deadlock có trùng lúc bot hay service ghi vào cùng dự án không? Log chưa
chứng minh.** Ba mốc đối chiếu được:

| Mốc | Deadlock | Việc ghi quanh đó, theo log | Cùng dự án? |
|---|---|---|---|
| 13:13:49 | PROJ-0027 | service tách thẻ con cho TASK-2026-07329, 13:08–13:13 | **không**: 07329 thuộc PROJ-0018 |
| 13:25:28 | PROJ-0013, PROJ-0018 | từ 13:21:54 không có dòng ghi nào của service hay bot | không thấy việc ghi nào |
| 14:41:00 | PROJ-0027 | lượt quét 14:40:25: chạy 3 thẻ, **để lượt sau** TASK-2026-05091 (cụm của PROJ-0027) và 6 thẻ khác | chưa biết, xem dưới |

Mốc 14:41:00:
- Dòng `chạy 3 thẻ …` (`agent_bot.py:3275`) ghi **sau** vòng xử lý các cây
  (`3227–3270`). Vậy mọi bước ghi của bot trong vòng ấy đều xong trước
  14:40:25,429: gắn người, chép Thuộc tính, dọn phiếu, trả lời, chuyển cột,
  `autorun_pass`.
- 05091 bị để lượt sau, nên lượt ấy không chạy `autorun_pass` cho nó. Các
  bước đứng trước thì vẫn chạy cho nó. Nhưng dòng tổng c8 trích bỏ lửng các
  con số ấy (`11 thẻ, … chạy 3 … chuyển cột 0 thẻ`).
- Log không cho biết request của làn gửi lúc nào: dòng deadlock chỉ ghi lúc
  `pool.map` xong (14:41:00,673).
- Sau vòng ấy, `_scan_once` chỉ ghi tệp trên máy (`_write_sku_status`,
  `agent_bot.py:3285`) rồi ghi log. Không có lệnh ghi ERP nào nữa.
- Nhưng `autorun_pass` giao việc cho service qua `autorun_hook`
  (`agent_bot.py:2981`). Job của ba thẻ được chạy vẫn chạy tiếp sau
  14:40:25 và có thể ghi ERP.
- Ba thẻ ấy không có tên trong phần c8 trích, nên không biết chúng thuộc
  dự án nào.
- Muốn chứng minh, cần mọi dòng log trong 14:40:00–14:41:01 có tên thẻ hay
  dự án của một lệnh ghi ERP (bot, service, job Flow), để so với PROJ-0027.
- Kể cả có đủ log của 8000, vẫn không thấy người dùng sửa trên ERP, không
  thấy 8001 hay lister.

Vì vậy PRD **không ghi giả thuyết "trùng lúc ghi vào cùng dự án"**. Hai mốc
13:13 và 13:25 còn nghiêng ngược lại.

**Hai giả thuyết còn lại, đều là suy đoán:**
1. Làn tự va với chính nó: 4 request cùng token gửi song song.
2. Lần đọc nào cũng có chung một xác suất nhỏ gặp deadlock. Làn chỉ là đọc
   bảng nóng thường hơn. Khi ấy đọc song song không phải nguyên nhân.

Hai dòng cùng mili-giây 13:25:28,991 **không chứng minh** hai request gửi
cùng lúc. Log ghi sau khi `pool.map` xong cả lô, trong một vòng `for`
(`sku.py:1656–1663`). Nó chỉ cho biết hai lỗi nằm cùng một lô.

Cơ chế phía ERP (**suy đoán**):
- Chuỗi `{"exc_type": …}` giống lỗi của Frappe. Nếu ERP là Frappe, thì
  `QueryDeadlockError` là MariaDB báo deadlock: hai giao dịch giữ khoá và
  chờ nhau.
- Lượt đọc thuần không giữ khoá. Vậy request `taskBoard` phải ghi hay khoá
  gì đó. Ví dụ: dấu dùng token, bộ đếm trần của HVGToken, hoặc chính
  `taskBoard` đọc có khoá.

Muốn chốt thì hỏi đội ERP (mục 6, điều 4). A là phép đo tách được giả
thuyết 1 khỏi giả thuyết 2, nhưng đã bỏ.

## 2. Lỗi 500 đang đi đường nào

1. `AgentBotClient.graphql` (`agent_bot.py:377–457`), `retries=2`:
   - 401: ném ngay (`416–422`);
   - 429: thử lại, ngủ `min(30, 5·lần)` (`423–426`); hết lượt thì ném
     (`427–430`);
   - **mã khác, kể cả 500: ném ngay**
     `AgentBotError(f"ERP HTTP {exc.code}: {detail}")` (`431`). **Không thử
     lại.**
   - `URLError`, `TimeoutError`: thử lại (`432–444`).

   Chuỗi lỗi ra đúng như log: `ERP HTTP 500: {"exc_type":"QueryDeadlockError"}`.
2. `board_snapshot` (`agent_bot.py:466–492`) không bắt lỗi. `_read_one`
   (`sku.py:1634–1638`) bắt mọi `Exception`, trả `(None, exc)`.
3. `_read_boards` (`sku.py:1657–1665`): `_is_rate_limited`
   (`sku.py:1488–1489`) chỉ tìm chữ `"429"`, nên không khớp. Lỗi đi nhánh
   `else`:
   - `log.warning` (`1663`);
   - `_next_read = now + rediscover_s` (`1664`). Mặc định 300 s (`1391`),
     env 60–3600 (`1406`).
   - **Không nghỉ cả làn.** Các bảng khác vẫn đọc bình thường.
4. Trong lúc chờ, bảng ấy giữ `_rows` cũ. Thẻ vừa kéo sang *Đang làm* không
   được thấy tới lần đọc sau, tức tới **300 s**. Lượt quét chính thực tế
   cách nhau 3,5–10 phút, nên thường không cứu kịp.

So với 429: `_rest(now)` (`sku.py:1660`, `1834–1845`) nghỉ cả làn `rest_s` =
60 s (`1389`). Bảng ấy dời 60 s (`1661`).

Ngoài phạm vi PRD này: lượt đánh số đi qua `_erp_graphql` của service
(`service.py:13304`). Hàm đó cũng không thử lại 5xx. c8 chưa thấy lỗi ở đó.

## 3. Phương án, xếp theo rủi ro × lợi ích

| # | Phương án | Code | Request thêm | Giữ trần 20/phút | Rủi ro | Lợi ích |
|---|---|---|---|---|---|---|
| A | `ERP_SKU_FAST_LANE_WORKERS=1`, **bỏ** | không | 0 | giữ | thấp | cao nếu giả thuyết đúng; là phép đo |
| **B** | thử lại một lần ở nhịp kế | nhỏ | +1 mỗi lần deadlock | giữ | thấp | cao, dù nguyên nhân là gì |
| C | hạ song song sau khi vừa gặp deadlock | vừa | 0 | giữ | vừa | vừa |
| D | thử lại ngay trong nhịp, chờ 1–2 s | vừa | +1 mỗi lần | giữ nếu lấy `budget.take` | vừa | thấp |
| E | thử lại 500 trong `graphql` | nhỏ | tới +2 mỗi lần | **không** | cao | vừa |

**A. Đọc tuần tự bằng env. Bỏ** (a6, 12/09).
- Lý do bỏ: A phải sửa `.env.local` trên hvg-pc và restart 8000 giữa giờ
  làm. B vừa sửa vừa đo được (mục 4, luật 6).
- Phân tích dưới đây giữ lại để tra.
- Biến có sẵn, biên 1–8 (`sku.py:1407`). Đã có test biên ở
  `tests/test_sku.py:3570`.
- Request thêm: 0. Trần giữ, vì số lần `budget.take` không đổi.
- Giá phải trả: nhịp đọc nhiều bảng sẽ chậm hơn. Lượt đánh số chạy sau khi
  đọc xong mọi bảng của nhịp (`tick`, `sku.py:1605–1608`). Bảng nóng vẫn
  đọc trước (`1647`). Nhịp sau vẫn chờ `interval_s` sau khi nhịp trước xong
  (`1623–1626`), nên nhịp giãn ra chứ không chồng lên nhau.
- A là phép đo duy nhất tách được "đọc song song" khỏi "tải ERP". Bỏ A thì
  câu hỏi nguyên nhân chờ đội ERP trả lời (mục 6, điều 4).

**B. Thử lại một lần ở nhịp kế.** Luật chi tiết ở mục 4, test đỏ ở mục 5.
- Request thêm: +1 mỗi lần deadlock. Mức sau dot7 là khoảng +12
  request/giờ, chừng 0,2/phút. Tệ nhất, khi lần đọc nào cũng lỗi: mỗi bảng
  2 lần mỗi 300 s thay vì 1.
- Trần giữ: lần thử lại là một lần đọc thường, đi qua
  `budget.take(1, keep=…)` (`sku.py:1649–1652`). Bảng nguội vẫn chừa
  `_LANE_RESERVE`.
- Không đổi 429, không đổi lỗi khác, không đổi `graphql`.
- Một lần deadlock làm thẻ vừa kéo chậm thêm 15 s thay vì 300 s.
- Đo được ngay trong log, nhờ đuôi bắt buộc của dòng cảnh báo (mục 4,
  luật 6).

**C. Hạ song song sau deadlock**, ví dụ đọc tuần tự trong `rest_s` kể từ
lần deadlock gần nhất.
- Thêm trạng thái, và `max_workers` phải đổi theo trạng thái.
- Chỉ có ích nếu giả thuyết đúng. Mà nếu đúng thì A gọn hơn.
- A đã bỏ, nên chưa có gì chứng minh được giả thuyết. Không làm.

**D. Thử lại ngay trong `_read_one`.**
- `RequestBudget` có khoá (`sku.py:1345`), nên gọi `take` từ luồng worker
  được. Nhưng hết chỗ thì không thử lại được.
- Ngủ trong luồng worker kéo dài cả nhịp.
- Thử lại khi các luồng khác cùng lô còn đang đọc thì dễ va tiếp.
- So với B chỉ lợi khoảng 13 s.

**E. Thử lại 500 ngay trong `AgentBotClient.graphql`.**
- Đổi mọi lời gọi của bot, kể cả lệnh ghi.
- Lần thử lại nằm dưới `budget.take` của làn, không bị đếm vào 20/phút.
  Chỉ còn bộ nhịp 50/phút chung chặn.
- Nằm ở vùng `flow_web/agent_*.py`. **Không đề xuất.**

**Quyết: chỉ làm B, giao d6** (a6, 12/09). A bỏ. C, D, E không làm.
- B không giảm số lần lỗi, chỉ làm mỗi lần lỗi đỡ tốn.
- Đuôi log của B cho biết tỉ lệ đọc lại thành công.

## 4. Luật cho d6 (phương án B)

1. Lỗi đọc bảng có chữ `QueryDeadlockError` thì đọc lại bảng ấy ở nhịp
   kế: `_next_read = now + interval_s`. Nhận diện bằng chuỗi, như
   `_is_rate_limited` tìm `"429"`.
2. Chỉ **một** lần liền. Lần đọc lại cũng deadlock thì `now +
   rediscover_s`, như lỗi thường. Lần lỗi kế tiếp sau đó lại được một lần
   thử lại.
3. Đọc được thì xoá dấu: lần deadlock sau lại được thử lại.
4. 429 thắng. 429 trong cùng nhịp vẫn `_rest`; đang nghỉ thì không đọc gì.
   Hết nghỉ thì bảng deadlock đến hạn luôn.
5. Lỗi khác giữ nguyên 300 s: 500 khác, `ERP GraphQL: …`, trả không phải
   JSON.
6. Mỗi lần lỗi vẫn đúng **một** dòng WARNING. Đầu câu giữ nguyên
   `Làn nhanh SKU không đọc được bảng <dự án>: <lỗi>`, vì c8 đếm bằng dòng
   này. **Đuôi bắt buộc** (a6, 12/09). Đuôi đứng sau lỗi, cách một dấu cách:
   - deadlock còn lượt thử lại: ` (đọc lại ở nhịp kế)`;
   - deadlock hết lượt, hoặc lỗi khác: ` (dời <N> giây)`. `N` là số giây
     bị dời, số nguyên; mặc định là `(dời 300 giây)`;
   - 429 vẫn dùng dòng riêng của `_rest` (`sku.py:1844`), không đổi;
   - cùng nhịp với 429 thì lần đọc lại chờ hết nghỉ (luật 4), nhưng đuôi
     vẫn là `(đọc lại ở nhịp kế)`.

   Cách đếm:
   - mỗi dòng `(đọc lại ở nhịp kế)` là một lần thử lại;
   - mỗi dòng deadlock mang `(dời …)` là một lần thử lại vẫn deadlock
     (luật 2);
   - tỉ lệ đọc lại thành công ≈ 1 − (số dòng deadlock `dời`) / (số dòng
     `đọc lại`). Đây chỉ là xấp xỉ: lần thử lại gặp lỗi khác thì ra dòng
     của lỗi khác, cũng mang `dời`.
7. Không đổi `agent_bot.py`, không đổi `graphql`.
8. Chỗ sửa:
   - `flow_web/sku.py` 1657–1671;
   - trạng thái mới khởi tạo trong `__init__` (1585–1596);
   - bảng bị gỡ khỏi `projects` thì dọn dấu luôn, như `1642–1644`.

Bộ test có sẵn không phải đổi. Vá mô phỏng đúng luật trên: bốn bộ canh vẫn
xanh (mục 5).

## 5. Test

Tệp mới `tests/test_lan_nhanh_deadlock.py`.
- Dùng `_LaneWorld` của `tests/test_sku.py`, qua lớp con `_TheGioiLoi`: lỗi
  riêng từng bảng, và lần đọc lỗi vẫn tính một request.
- Không mạng. Bài đường thật dùng `urlopen` giả.

Đợt 2, theo quyết của a6: thêm assertion đuôi (luật 6) vào 5 bài có sẵn,
không thêm bài mới. Assertion mới đứng **sau** assertion cũ:
- bài đỏ từ đợt 1 vẫn đỏ đúng lý do cũ;
- ba bài canh chuyển sang đỏ chỉ vì đuôi hoặc số dòng. Phần canh cũ của
  chúng vẫn qua, vì nó đứng trước.

Trên 52a9383: **9 bài đỏ** (11 failure, vì một bài có 3 subtest), **2
xanh**.

| Bài | 52a9383 | Lý do đỏ |
|---|---|---|
| `test_the_vua_keo_gap_mot_deadlock_van_co_ma_trong_45_giay` | **đỏ** | `315.0 not less than or equal to 45.0` |
| `test_bang_chua_doc_lan_nao_gap_deadlock_duoc_doc_lai_o_nhip_ke` | **đỏ** | `300.0 not less than or equal to 30.0` |
| `test_hai_bang_deadlock_cung_nhip_deu_duoc_doc_lai` | **đỏ** | như 13:25:28: nhịp kế không đọc lại bảng nào |
| `test_doc_duoc_thi_luot_thu_lai_tinh_lai_tu_dau` | **đỏ** | `1060.0 not found in [1000.0, 1015.0]`. Đợt 2 thêm: 2 dòng, cả hai `(đọc lại ở nhịp kế)` |
| `test_deadlock_cung_nhip_voi_429_het_nghi_la_doc_lai` | **đỏ** | `1075.0 not found in [1000.0, 1015.0]` |
| `test_loi_that_tu_graphql_duoc_nhan_la_deadlock` | **đỏ** | `300.0 not less than or equal to 30.0`. Đường thật: HTTP 500 → `graphql` → `board_snapshot` → làn. Đợt 2 thêm: dòng thật mang `(đọc lại ở nhịp kế)` |
| `test_deadlock_mai_chi_doc_toi_da_hai_lan_moi_5_phut` | **đỏ** (đợt 2) | `3 not greater than or equal to 4`: 900 s chỉ có 3 dòng, vì code cũ không thử lại. Đợt 2 thêm: đuôi xen kẽ `đọc lại` / `dời 300 giây`. Assertion trần đứng trước vẫn qua |
| `test_nhieu_bang_deadlock_van_giu_tran_20_request_moi_phut` | canh xanh | 30 bảng cùng deadlock, `worst_minute() <= 20`; hết lỗi thì vẫn đánh số |
| `test_429_van_nghi_ca_lan_mot_phut` | canh xanh | 429 cùng nhịp với deadlock vẫn nghỉ 60 s |
| `test_loi_500_khac_van_doi_5_phut` | **đỏ** (đợt 2), 3 subtest | `' \(dời 300 giây\)$' not found`. Assertion 300 s đứng trước vẫn qua |
| `test_deadlock_van_ghi_mot_dong_canh_bao` | **đỏ** (đợt 2) | `' \(đọc lại ở nhịp kế\)$' not found`. Đầu câu vẫn khớp |

Bài một chờ `30 + interval_s`. Làn hứa thẻ có mã trong 30 s; một lần deadlock
được phép tốn thêm đúng một nhịp.

Kiểm bằng vá mô phỏng. Vá nằm trong scratchpad, không commit; nó thay
`SkuFastLane._read_boards` lúc chạy.

| Bản vá | `test_lan_nhanh_deadlock` |
|---|---|
| đúng luật mục 4 | 11/11 OK; kèm bốn bộ canh: 263 OK |
| thử lại mãi, không trần | đỏ `test_deadlock_mai_…` |
| thử lại mọi lỗi | đỏ `test_loi_500_khac_…`, 3 subtest |
| đọc được mà không xoá dấu | đỏ `test_doc_duoc_thi_…` |
| coi deadlock như 429 (nghỉ cả làn) | 7 bài đỏ |
| đúng hành vi, nhưng dòng không đuôi | 5 bài đỏ (7 failure): `mai`, `canh_bao`, `loi_500_khac` ×3, `doc_duoc`, `loi_that` |
| hết lượt mà vẫn ghi `(đọc lại ở nhịp kế)` | đỏ `test_deadlock_mai_…` |

Không vá, bốn bộ canh (`test_sku`, `test_lan_nhanh_cay_cat`,
`test_429_trong_luot`, `test_sku_nhanh_moi_the`) cho 252 OK. Không chạy
discover.

## 6. Quyết định (a6, 12/09)

1. **A: bỏ.** A phải sửa `.env.local` trên hvg-pc và restart 8000 giữa giờ
   làm. B vừa sửa vừa đo được, nhờ đuôi dòng cảnh báo (luật 6).
2. **Chỉ deadlock**, không mở cho mọi 5xx. Giữ bài
   `test_loi_500_khac_van_doi_5_phut`.
3. **Không đổi mặc định `workers`.** `tests/test_sku.py:3570` giữ nguyên.
4. **Hỏi đội ERP**: a6 đưa vào danh sách báo người dùng. Câu hỏi:
   `taskBoard`, hay bước xác thực HVGToken, có ghi hay khoá gì trong giao
   dịch không (mục 1.3)? Bên này không làm gì thêm.
5. **Dòng tổng mỗi N phút: không làm đợt này.** Để ở mục 7, là việc sau.
6. Tin sau của a6: **đuôi dòng cảnh báo là bắt buộc** (luật 6). Test khoá
   đuôi ở 5 bài có sẵn (mục 5).

Không còn câu hỏi mở.

## 7. Rủi ro

- Nếu nguyên nhân là tải chung của ERP, không phải đọc song song, thì A
  không đổi gì. B vẫn có ích.
- B nhận diện bằng chuỗi. ERP đổi tên `exc_type` thì B im lặng về luật cũ
  (300 s). Không hỏng gì thêm.
- Lượt đánh số của service không thử lại 5xx (mục 2). Nếu deadlock chuyển
  sang đó, cụm ấy thành `failed`. Chưa thấy trong log; ngoài phạm vi PRD.
- A đã bỏ. Nếu nguyên nhân đúng là đọc song song, số dòng deadlock sẽ không
  giảm; B chỉ làm mỗi lần lỗi đỡ tốn. Mỗi lần deadlock tốn thêm một
  request.
- **Việc sau: dòng tổng mỗi N phút** (số lần đọc, số lần lỗi). a6 quyết
  không làm đợt này. Thiếu nó thì chỉ biết tỉ lệ đọc lại thành công, không
  biết tỉ lệ lỗi trên tổng số lần đọc.
- Đuôi log là giao ước với bộ đếm của c8. Đổi chữ là mất số đo. Test khoá
  đúng chữ.

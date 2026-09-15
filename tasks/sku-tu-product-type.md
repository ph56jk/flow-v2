# PRD — Tiền tố SKU lấy thẳng từ danh mục sản phẩm ERP (`product_type`)

Yêu cầu gốc, nguyên văn người dùng: "Có cái product type nè
https://erp.havigroup.llc/hvg/task?task=TASK-2026-05391 và tôi muốn nó dựa
vào product như này để chạy" — "thay vì nhận diện bằng tên nữa để bot dễ
nhận ra hơn" — "erp lưu ấy" — "thì nó sẽ có sẵn như vậy thì nó là SKU ấy".

Dịch ra: bot đang đoán tiền tố SKU từ **tên sản phẩm gõ tay**. ERP đã lưu sẵn
mã trong danh mục sản phẩm riêng của nó. Lấy thẳng mã ERP, đừng đoán theo tên
nữa.

Test đỏ đi kèm: `tests/test_sku_product_type.py` — 30 bài, 1 xanh / 29 đỏ (số
đo thật, xem mục "Danh sách test đi kèm"). Không sửa file test nào đang có.

## 1. Phạm vi

**Trong phạm vi:**

- Thêm nguồn mã mới `"erp-category"` vào `flow_web/sku.py`, đứng **trước**
  `book`/`book-contains`/`book-alias`/`derived`.
- `card_from_node()` đọc thêm `product_type` (taskDetail, cấp 1) và
  `custom_product_type` (taskBoard).
- Một lớp tra danh mục sản phẩm ERP (`ProductCategoryBook` hoặc tên tương
  đương), khớp theo `name_en`/`name_vi`/`code`, chỉ nhận dòng `kind: type` +
  `status: active`.
- Cache danh mục trong tiến trình (kiểu `load_sku_book()`), có TTL, đọc lại
  theo nhịp, không gọi ERP mỗi lượt.
- Nối `plan_erp_skus()` (service.py) với nguồn mới, không đổi hành vi cho
  thẻ đã có mã.

**Ngoài phạm vi (đợt này):**

- Tận dụng `custom_product_type` của dòng `taskBoard` để bớt lượt mở
  `taskFull` từng thẻ — đụng `fill_cost()` (`flow_web/sku.py:1307-1324`) và
  `_LANE_MIN_BUDGET` (`flow_web/sku.py:1329-1331`), hai số đang chạy thật
  trên máy trung tâm. Nêu ở Câu hỏi 3, **không gộp vào đợt này** theo đúng
  yêu cầu của người giao việc.
- Xoá hay thay bảng mã Google Sheet. Bảng vẫn là lớp dự phòng (xem mục 3.5).
- Sửa `ERP_IDEA_REQUIRED_META`/`_erp_idea_missing_meta`
  (`flow_web/service.py:3530-3550`) — khoá `product_type` ở đó là khối
  *Thuộc tính* gõ tay, một tính năng khác hẳn, không đụng ở đây (xem Rủi ro).

**Ràng buộc bắt buộc (từ người giao việc, không tự nới):**

- Không gọi ERP trong test — danh mục nạp qua lớp bơm được dữ liệu giả.
- Có cache, nói rõ nhịp đọc lại và chi phí request thêm mỗi lượt quét.
- Chỉ dòng `kind: type` mới dùng làm mã; dòng `group` (`sku_prefix: null`)
  bỏ qua.
- Chỉ lấy dòng `status: active`.
- Không đổi mã của thẻ đã có mã — luật cũ ở docstring module
  (`flow_web/sku.py:1-59`) giữ nguyên.
- Nguồn phải ghi ra được để soát: thẻ nào lấy mã từ ERP, thẻ nào rơi về
  sheet, thẻ nào vẫn phải đoán.

## 2. Xếp hạng ưu tiên

| # | Cải tiến | Rủi ro nếu không làm | Lợi ích | Công | Test đỏ |
|---|---|---|---|---|---|
| 1 | Nguồn mã `erp-category` trong `ProductBook`-tương-đương + `la_ma_doan` | Bot tiếp tục đoán tiền tố (`derive_prefix`) cho mọi sản phẩm ERP đã có mã sẵn — đúng lỗi `PNO` vs `OL` ghi trong docstring `derive_prefix` (sku.py:221) | Mã đúng ngay cho 97 sản phẩm ERP có `sku_prefix`, không cần ai gõ tay vào sheet | Vừa | `ProductCategoryBookTests` (8 bài), `LaMaDoanErpCategoryTests` (2 bài) |
| 2 | `card_from_node` đọc `product_type`/`custom_product_type` | Có nguồn mã mới nhưng không có gì để tra — cấp 1 chưa từng được đọc | Thẻ mang sẵn dữ liệu ERP dùng được ngay, không cần đổi payload | Nhỏ | `CardFromNodeProductTypeTests` (6 bài) |
| 3 | Nối `categories` vào `plan_skus`/`plan_erp_skus` | Hai việc trên có nhưng không thẻ nào chạm tới — mã vẫn ra từ sheet/đoán như cũ | Toàn bộ đường đi từ thẻ thật tới mã ERP hoạt động | Vừa | `PlanSkusErpCategoryTests` (7 bài), `PlanErpSkusWiringTests` (3 bài) |
| 4 | Cache danh mục ERP có TTL | Không cache thì mỗi lượt quét (mọi board, mọi 120s) tốn thêm 1 request ERP mỗi board — có thể đẩy làn nhanh SKU (`ERP_SKU_FAST_LANE_BUDGET`, mặc định 20/phút, `sku.py:1417`) vượt trần | Danh mục 127 dòng đổi rất chậm (`modified` mới nhất 08/09) — cache dài, tốn cực ít | Vừa | `FlowWebServiceProductCategoryCacheTests` (7 bài) |

Mục 1–3 phụ thuộc lẫn nhau theo chuỗi (mục 3 vô nghĩa nếu thiếu 1, 2); mục 4
độc lập nhưng nên đi kèm 1–3 trong cùng một đợt để không có bản chạy thật nào
gọi ERP không cache.

## 3. Từng mục

### 3.1. Nguồn mã mới `erp-category`

**Hiện trạng.** `ProductBook` (`flow_web/sku.py:283-445`) là nguồn mã duy
nhất ngoài đoán: `entries`/`alternates`/`aliases` (283-304), dựng từ
`from_mapping()` (306-317) hoặc `from_rows()` (319-368, đọc theo tên cột
sheet). Ba tầng so khớp trong `_row_key()` (417-429): đúng dòng (`"book"`) →
tên dài hơn chứa trọn một dòng theo từ (`"book-contains"`, `_contained_key()`
388-411) → bí danh (`"book-alias"`). `lookup()` (431-442) trả `(mã, nguồn)`,
rơi về `derive_prefix()` (213-230) khi không khớp — nguồn `"derived"`.
`normalize_product()` (156-160) bỏ dấu, thường hoá, gộp khoảng trắng; dùng
chung cho mọi so khớp.

`derive_prefix()` tự nói rõ giới hạn của chính nó (sku.py:221): *"Đoán từng
ra `PNO` cho `Punch Needle Ornament` trong khi xưởng gọi món ấy là `OL`."*
Đây đúng là sản phẩm của thẻ đo thật `TASK-2026-05391` — ERP đã có dòng
`HOM-SEA-OL` (`sku_prefix: OL`) cho đúng tên này
(`briefs/danh-muc-erp-do-12-09.txt:41`).

`BOOK_SOURCES = ("book", "book-contains", "book-alias")` (sku.py:130).
`la_ma_doan(source)` (133-140) trả `True` cho mọi nguồn ngoài ba cái này —
tức hôm nay `la_ma_doan("erp-category")` cũng trả `True` (coi là đoán), sai.

**Yêu cầu.**

1. Thêm một lớp tra danh mục sản phẩm ERP (đề xuất tên
   `ProductCategoryBook`), dựng từ danh sách dòng `productCategories` (mỗi
   dòng: `code`, `kind`, `name_vi`, `name_en`, `sku_prefix`, `status`, …).
2. `.lookup(value) -> Tuple[str, str]`, cùng khuôn dạng `(mã, nguồn)` với
   `ProductBook.lookup()`, nguồn cố định `"erp-category"` khi khớp, `("", "")`
   khi không.
3. Chỉ nhận dòng `kind == "type"` **và** `status == "active"` **và**
   `sku_prefix` khác rỗng.
4. Khớp theo `name_en`, `name_vi`, hoặc `code`, qua `normalize_product()`
   sẵn có (không viết lại bộ chuẩn hoá thứ hai).
5. Hai dòng khác nhau trùng cùng một khoá tra (tên hoặc mã) sau chuẩn hoá:
   bỏ cả hai, không đoán đại một mã — theo đúng tiền lệ
   `ProductBook.from_rows()` xử lý bí danh trùng (sku.py:358-367).
6. `la_ma_doan("erp-category")` phải trả `False` — đây là mã ERP tự ghi, không
   phải bot đoán.

**Tiêu chí nghiệm thu đo được.**

- `la_ma_doan("erp-category") is False`.
- `ProductCategoryBook.from_rows([...]).lookup("Punch Needle Ornament") ==
  ("OL", "erp-category")` với dữ liệu mẫu đo thật (4 dòng, xem
  `CATEGORY_ROWS` trong file test).
- Dòng `kind: group` (không `sku_prefix`) tra ra `("", "")`.
- Dòng `status: inactive` tra ra `("", "")`.

### 3.2. `card_from_node()` đọc `product_type`/`custom_product_type`

**Hiện trạng.** `card_from_node()` (`flow_web/sku.py:861-875`) dựng
`SkuCard` từ một node ERP (`taskFull`/`taskDetail`/`taskBoard`), đọc
`name`/`parent_task`(+biến thể)/`subject`/`meta`/`project_name`(+biến
thể)/`project`(+biến thể)/`status`. **Không đọc** `product_type` hay
`custom_product_type`. `SkuCard` (478-503) là dataclass `frozen`, chưa có
field cho việc này.

Đo thật (`briefs/danh-muc-erp-do-12-09.txt` mục 2b-c): `taskDetail` trả
`product_type` ở **cấp 1** (không nằm trong khối `meta`); `taskBoard` trả
`custom_product_type` trên mọi dòng (301 thẻ PROJ-0018, `includeArchived:
false`: 289 có khai, 12 rỗng). Thẻ `TASK-2026-05391` thật:
`product_type = "Punch Needle Ornament"`.

**Cạm bẫy đặt tên — đọc kỹ trước khi cài.** Chuỗi `product_type` chỉ MỘT
tên nhưng ba nghĩa khác nhau trong cùng repo này:

| Chỗ | Là gì | Ai đọc |
|---|---|---|
| `PRODUCT_KEYS` (`flow_web/erp_meta.py:73-83`) | khoá dự phòng cuối cùng trong danh sách tên sản phẩm gõ tay trong khối `meta` | `TaskMeta.product` (`erp_meta.py:321-329`) |
| `ERP_IDEA_REQUIRED_META` (`flow_web/service.py:3530`) | một trong bốn khoá bắt buộc khối *Thuộc tính* gõ tay, gate việc tách thẻ con/tạo ảnh — tính năng "quy trình 11/09", không liên quan gì tới PRD này | `_erp_idea_missing_meta()` (`service.py:3547-3550`, đọc qua `task_meta(detail).get(key)`) |
| Trường cấp 1 của payload `taskDetail`/`taskBoard` | field ERP tự quản, trỏ vào danh mục sản phẩm | **PRD này** |

Cả hai chỗ đầu đọc **text gõ tay trong khối `meta`** (qua
`task_meta()`/`_user_block()`, `erp_meta.py:385-396,447-466`). Chỗ thứ ba đọc
**payload thô**, không qua `TaskMeta`. Thẻ đo thật còn có dòng
`product_type: Punch Needle Ornament` trong khối `meta` của chính nó — trùng
nội dung với trường cấp 1, nhưng khác chỗ lưu. `card_from_node()` **không
được** lẫn hai chỗ này khi thêm field mới.

**Yêu cầu.**

1. Thêm field `product_type: str = ""` vào `SkuCard`.
2. `card_from_node()` đọc `source.get("product_type")`, thiếu thì đọc
   `source.get("custom_product_type")`, `.strip()` giống các trường khác
   (board/project/status, sku.py:872-874). **Không** đọc qua `TaskMeta`/khối
   `meta`.
3. Không đi ngược lên cha (khác `effective_product()`, sku.py:1054-1063):
   chỉ dùng giá trị khai trên chính thẻ. Lý do và hệ quả nêu ở Câu hỏi 4.

**Tiêu chí nghiệm thu đo được.**

- `card_from_node({"product_type": "Punch Needle Ornament"}).product_type ==
  "Punch Needle Ornament"`.
- `card_from_node({"custom_product_type": "Punch Needle Ornament"}).product_type
  == "Punch Needle Ornament"`.
- `card_from_node({"meta": "product_type: X"}).product_type == ""` (không lẫn
  khối meta).

### 3.3. Nối vào `plan_skus()`

**Hiện trạng.** `plan_skus()` (`flow_web/sku.py:977-987`) nhận `book:
Optional[ProductBook] = None`, không có tham số danh mục ERP. Ba chỗ gọi
`catalogue.lookup(...)`:

- dòng 1065-1066: `root_prefix, root_source = catalogue.lookup(root_product)`
  — tính `SkuPlan.prefix`/`SkuPlan.prefix_source` cho cả cụm, dùng
  `effective_product(root_card)` (đi lên cha nếu cần, 1054-1063);
- dòng 1148: `prefix_source=catalogue.lookup(effective_product(card))[1] or
  root_source` — chỉ để **báo cáo** nguồn cho thẻ **đã có mã** (`kept`),
  không đổi mã;
- dòng 1159-1160: `prefix, source = catalogue.lookup(product_name)` — chỗ
  cấp mã **mới** thật sự, theo sau là `la_ma_doan(source)` (1164) bỏ nếu là
  mã đoán.

`card_is_ready()` (925-951): không đọc được cột `status` thì **không chặn**
(rỗng nghĩa là người gọi không đưa cột, không phải thẻ chưa sẵn sàng); chỉ
`Cancelled` luôn chặn.

**Yêu cầu.**

1. Thêm tham số `categories: Optional[ProductCategoryBook] = None` (keyword-
   only, mặc định `None` — không được bắt buộc, để mọi lời gọi cũ trong
   `tests/test_sku.py` không cần sửa).
2. Ở cả ba chỗ gọi `catalogue.lookup(...)` nêu trên: nếu có `categories`, thử
   `categories.lookup(card.product_type)` (hoặc `root_card.product_type` ở
   chỗ gốc) **trước**; chỉ khi không khớp mới rơi xuống `catalogue.lookup(...)`
   như cũ. Thẻ gốc (`TASK-2026-05391` thật) tự khai `product_type` trên
   chính nó — `SkuPlan.prefix`/`prefix_source` của cả cụm phải phản ánh đúng
   nguồn ERP cho trường hợp này, không chỉ áp dụng cho thẻ con.
3. Không đổi hành vi khi `categories=None` hoặc rỗng — tương thích ngược
   tuyệt đối.

**Hiện trạng phía `service.py`.** `plan_erp_skus()`
(`flow_web/service.py:14244-14443`) là nơi gọi `plan_skus()` thật với dữ
liệu ERP: dòng 14422 `book = self.load_sku_book()`; hàm lồng `plan()`
(14429-14439) gọi `plan_skus(cards, book, root_id=root, renumber=renumber,
ledger=on, board_product=board_product, project_id=project,
positions=positions)`. Hàm này chạy **ngay trong** đường của làn nhanh SKU:
`fill_task_skus()` (14538, gọi `plan_erp_skus` ở dòng 14607) là callback
`fill=` của `SkuFastLane` (`build_sku_fast_lane`, wiring tại
`service.py:22789`) — tức mọi request mà `plan_erp_skus` phát sinh đều tính
vào ngân sách 20 request/phút của làn nhanh (xem Rủi ro).

**Yêu cầu.**

1. Thêm `categories = self.load_product_categories(key=key, token=token)`
   ngay sau dòng `book = self.load_sku_book()` (14422), dùng chung
   `key`/`token` của lượt gọi.
2. Thêm `categories=categories` vào lời gọi `plan_skus(...)` bên trong
   `plan()` (14429-14439).

**Tiêu chí nghiệm thu đo được.**

- Thẻ khai `product_type` khớp một dòng `active` trong danh mục ERP, chưa có
  mã, đã sang *Đang làm*: nhận mã đúng tiền tố ERP, `assignment.prefix_source
  == "erp-category"`.
- Thẻ khai `product_type` không khớp danh mục ERP nhưng tên khớp sheet: nhận
  mã sheet như cũ (`prefix_source == "book"`).
- Thẻ không khớp cả hai: nằm trong `plan.skipped`, **không** có trong
  `plan.assignments` (không đoán).
- Thẻ đã có `sku:` hợp lệ: mã giữ nguyên dù `product_type` khớp một tiền tố
  ERP khác.
- `plan_skus(cards, book, ...)` không kèm `categories` vẫn chạy đúng như
  trước khi có PRD này.

### 3.4. Cache danh mục sản phẩm ERP

**Hiện trạng.** `load_sku_book()` (`flow_web/service.py:14047-14088`) là mô
hình cache-theo-TTL đang chạy thật cho bảng sheet: hằng số
`SHEET_TTL_SECONDS = 300.0` (13986), `SHEET_RETRY_SECONDS = 60.0` (13990),
đồng hồ tiêm được `_sheet_clock()` (13992-13999,
`svc._sheet_clock = lambda: now` trong test), hàm dùng chung
`_read_sheet_cached()` (14001-14045): còn hạn thì không đọc lại; hết hạn đọc
lại, lỗi thì giữ bản tốt gần nhất và chờ `SHEET_RETRY_SECONDS` mới thử lại.
`load_account_book()` là bản thứ hai theo đúng lối này — xem
`tests/test_sku_sheet_ttl.py` (`SkuSheetTtlTests`,
`AccountSheetTtlTests`), 296 dòng, mô hình để soi theo, không phải để tái sử
dụng nguyên văn (nguồn khác: HTTP tới Google Sheet, không phải
`_erp_graphql`).

**Khác biệt quan trọng với `load_sku_book()`:** đọc lại sheet là một lượt
HTTP tới Google, **không** đi qua `_erp_graphql`/`RequestBudget` — không tốn
gì trong trần ERP. Đọc lại danh mục sản phẩm thì **có** đi qua `_erp_graphql`
(`flow_web/service.py:13304-13320`, cùng cổng `_erp_task_board()`/
`_erp_task_detail()` đang dùng, 13623-13639/13659-13669) — mỗi lượt đọc lại
là một request thật, tính vào trần 60/phút của ERP và (khi chạy trong làn
nhanh) trần `ERP_SKU_FAST_LANE_BUDGET` (mặc định 20/phút, `sku.py:1417`).

**Yêu cầu.**

1. `load_product_categories(self, key: str, token: str, *, refresh: bool =
   False) -> ProductCategoryBook`, theo đúng khuôn TTL/retry/giữ-bản-tốt của
   `load_sku_book()`.
2. Hai hằng số mới trên `FlowWebService`: `PRODUCT_CATEGORY_TTL_SECONDS =
   1800.0` (30 phút) và `PRODUCT_CATEGORY_RETRY_SECONDS` bằng đúng
   `SHEET_RETRY_SECONDS` (60s). Đề xuất 1800s vì danh mục 127 dòng đổi rất
   chậm — `modified` mới nhất trong bản đo 12/09 là 08/09, tức hơn 4 ngày
   không đổi dòng nào; 300s (bằng sheet) là quá dày cho tần suất đổi này và
   tốn thêm request ERP không cần thiết.
3. Dùng lại `_sheet_clock()` làm đồng hồ tiêm được — không dựng đồng hồ song
   song thứ hai cho một tiến trình.
4. Một lượt đọc lại chỉ tốn **đúng 1** request `_erp_graphql` (danh mục 127
   dòng trả trong một lượt `productCategories`, không phân trang).
5. Cache file trên đĩa (`data/product_categories.json`, theo đúng lối
   `data/sku_book.json`) — đề xuất **không** đưa vào git (khác với
   `data/sku_book.json`, vốn là bản chép tay được commit): danh mục ERP là
   bản sao đọc lại được bất cứ lúc nào, không phải nguồn người vận hành gõ
   tay, đưa vào git chỉ tổ tạo xung đột merge vô nghĩa.

**Tiêu chí nghiệm thu đo được.**

- `FlowWebService.PRODUCT_CATEGORY_TTL_SECONDS == 1800.0`.
- Trong hạn: gọi hai lần không đọc lại ERP (đếm số lời gọi `_erp_graphql`
  giả lập bằng 1).
- Hết hạn: gọi lại đúng một lần nữa (không phải nhiều lần).
- Đọc lỗi (giả lập `_erp_graphql` ném ngoại lệ): giữ nguyên bản tốt gần
  nhất, ghi log cảnh báo (`log.warning` được gọi).
- `refresh=True`: luôn đọc lại, bỏ qua TTL.

### 3.5. Bảng mã sheet — giữ nguyên làm lớp dự phòng

**Dữ kiện đo thật, 12/09, trên hvg-pc** (so bằng đúng đường app đang nạp
sheet, `/edit` → `/export?format=csv`, `flow_web/service.py:1283-1292`):

| Nguồn | Số dòng |
|---|---|
| Sheet "SẢN PHẨM - SKU" | 55 dòng có mã |
| Bản chép `data/sku_book.json` phủ thêm | 9 dòng |
| Danh mục ERP | 97 mã / 193 tên (`name_en` + `name_vi`) |

Sản phẩm có ở cả hai nguồn: **55 — giống mã 55, khác mã 0.** Không bất đồng
nào giữa sheet và ERP tính đến ngày đo. Chín tên chỉ có ở bản chép trên đĩa
đều là biến thể tên tiếng Việt của sản phẩm ERP đã có, **cùng bộ mã** (cờ
treo tường FB, gương ME, gương cầm tay ME, móc treo ô tô TX, mũ vải VM, mũ
vải crown VM, sổ WB, sổ A6/A5/A4 WB, tất len PS). ERP phủ thêm 138 tên mà
sheet không có — gần trọn nhánh POD (hoodie, jersey, ornament acrylic…).

**Yêu cầu.** Đặt `erp-category` lên trước không đổi mã của bất kỳ sản phẩm
nào đang dùng hôm nay. **Giữ nguyên bảng sheet làm lớp dự phòng** — không
đề xuất bỏ, không đề xuất thay. Đây là cơ sở số cho Câu hỏi 1 dưới đây, chứ
không thay câu hỏi đó.

## Thứ tự làm đề xuất

Chia hai đợt, mỗi đợt một pull request:

1. **Đợt 1 — lõi tra cứu, không đụng service.py.** Mục 3.1 + 3.2:
   `ProductCategoryBook`, `la_ma_doan("erp-category")`, `card_from_node` đọc
   `product_type`/`custom_product_type`. Test đỏ: `ProductCategoryBookTests`,
   `LaMaDoanErpCategoryTests`, `CardFromNodeProductTypeTests` (16 bài).
   Không cần chạm `flow_web/service.py`.
2. **Đợt 2 — nối dây thật.** Mục 3.3 + 3.4: tham số `categories` trên
   `plan_skus()`, `load_product_categories()` có cache, nối vào
   `plan_erp_skus()`. Test đỏ: `PlanSkusErpCategoryTests`,
   `FlowWebServiceProductCategoryCacheTests`, `PlanErpSkusWiringTests` (17
   bài). Phụ thuộc đợt 1 đã xanh.

Không tách nhỏ hơn: đợt 1 mà thiếu đợt 2 thì có nguồn mã nhưng không ai gọi
tới — không nên merge riêng mà không có kế hoạch merge đợt 2 ngay sau.

## Danh sách test đi kèm

| Lớp / file | Mục | Số bài | Đỏ vì gì |
|---|---|---|---|
| `ProductCategoryBookTests` (`tests/test_sku_product_type.py`) | 3.1 | 8 | `flow_web.sku.ProductCategoryBook` chưa tồn tại |
| `LaMaDoanErpCategoryTests` | 3.1 | 2 | 1 đỏ (`la_ma_doan("erp-category")` còn trả `True`), 1 xanh (chốt chặn nguồn cũ không đổi) |
| `CardFromNodeProductTypeTests` | 3.2 | 6 | `SkuCard` chưa có field `product_type` |
| `PlanSkusErpCategoryTests` | 3.3 | 7 | `setUp` gọi `ProductCategoryBook` (chưa có) — đỏ dây chuyền từ 3.1; sau khi 3.1+3.2 xanh sẽ lộ đúng phần thiếu của 3.3 (`plan_skus` chưa nhận `categories`) |
| `FlowWebServiceProductCategoryCacheTests` | 3.4 | 7 | `FlowWebService` chưa có `load_product_categories`/`PRODUCT_CATEGORY_TTL_SECONDS` |
| `PlanErpSkusWiringTests` | 3.3 | 3 | regex trên `flow_web/service.py`: chưa có `load_product_categories(`, chưa có `categories=` trong lời gọi `plan_skus` |
| **Tổng** | | **30** (**1 xanh / 29 đỏ**) | đo thật `.venv/bin/python -m unittest tests.test_sku_product_type -v` từ gốc worktree, 2026-09-12 |

**Chốt chặn — không được phép hỏng khi cài đặt:**

- Toàn bộ `tests/test_sku.py` (bộ test SKU hiện có, không sửa) phải giữ
  xanh nguyên — đặc biệt `test_missing_row_is_derived_and_says_so`,
  `test_book_matches_however_the_card_spells_it` (đảm bảo nguồn mã mới
  không đụng vào ba nguồn cũ khi `categories=None`).
- Toàn bộ `tests/test_sku_sheet_ttl.py` (cache sheet hiện có) phải giữ xanh
  — cache mới không được dùng chung state với `_sku_book_path`/
  `_sku_sheet_cache`.
- `LaMaDoanErpCategoryTests.test_cac_nguon_cu_khong_bi_doi` (đã xanh ngay từ
  đầu) không được hỏng ở bất kỳ commit nào.

## Rủi ro của chính đợt này

| Rủi ro | Mức | Cách giảm |
|---|---|---|
| ~~Chưa đo được liệu `taskFull` có trả `product_type` cấp 1 trên node con hay không.~~ **ĐÃ ĐO 12/09, rủi ro này không còn** — xem mục "Số đo `taskFull`" ngay dưới bảng. | — | — |
| `load_product_categories()` thêm một request `_erp_graphql` mỗi lần hết hạn cache — request này **không** nằm trong `fill_cost()` (`sku.py:1307-1324`)/`_LANE_RESERVE`/`_LANE_MIN_BUDGET` (1329-1331). Làn nhanh SKU chạy `plan_erp_skus` trực tiếp trong ngân sách 20 request/phút (`ERP_SKU_FAST_LANE_BUDGET`, `sku.py:1417`; wiring `service.py:22789`→`14607`). TTL 1800s làm việc này cực hiếm (≈1 lần/30 phút/tiến trình), nhưng vẫn là một request không được `RequestBudget.take(...)` biết trước khi trừ ngân sách. | Thấp (hiếm, nhưng không phải 0) | Không sửa `fill_cost`/`_LANE_MIN_BUDGET` trong đợt này (đúng yêu cầu ngoài phạm vi — Câu hỏi 3). Ghi nhận rủi ro, để người vận hành theo dõi log 429 của làn nhanh sau khi triển khai; nếu thấy tăng thì mới cần đụng tới `fill_cost`. |
| `data/product_categories.json` không được thêm vào `.gitignore` — cache runtime lẫn vào git giống một bảng người vận hành gõ tay (khác `data/sku_book.json`, vốn cố ý được commit). | Thấp | Mục 3.4 yêu cầu 5 đã đề xuất không track; người cài đặt cần thêm dòng vào `.gitignore` khi tạo file mới. |
| Cạm bẫy đặt tên `product_type` (ba nghĩa, mục 3.2) — người cài đặt vô tình đọc nhầm sang khối `meta` gõ tay, hoặc vô tình đổi `ERP_IDEA_REQUIRED_META`. | Vừa | `CardFromNodeProductTypeTests.test_khong_lay_nham_tu_khoi_meta_gom_tay` canh riêng; PRD nêu bảng ba-nghĩa tường minh ở 3.2. |

## Số đo `taskFull` — 12/09, trên hvg-pc, chỉ đọc

Người viết PRD nêu đúng một khoảng trống thật: brief chỉ đo `taskDetail` và
`taskBoard`, chưa đo `taskFull` — mà `taskFull` mới là đường `plan_erp_skus`
đi. Đã chạy script chỉ-đọc trên máy trung tâm, hai cụm thật:

| Cụm | Node con | Con có `product_type` **có giá trị** | Giá trị | Tra danh mục ERP |
|---|---|---|---|---|
| `TASK-2026-04628` (Ornament Round) | 59 | **59/59** | `Embroidered Ornament` | → `OR` |
| `TASK-2026-05384` (Punch Needle) | 49 | **49/49** | `Punch Needle Ornament` | → `OL` |

Kết luận: **`taskFull` trả `product_type` ở cấp 1 trên mọi node con**, không
phải chỉ trên `taskDetail`. Suy luận của người viết PRD đúng. Đợt 2 chạm được
đường chính, không chỉ nhánh `taskBoard` dự phòng.

Ba dữ kiện phụ đo được cùng lượt, người cài đặt cần biết:

1. **Node con của `taskFull` có cả `sku` ở cấp 1.** Cụm 04628: 4/59 thẻ đã có
   mã; cụm 05384: 10/49. Tức mã đã cấp đọc được thẳng từ cây, không phải suy
   từ `subject`.
2. **Cây trả về bị cắt ở 60 node** (`node_count: 60`, `max_nodes: 60`,
   `truncated: true` — đúng bản ghi nhớ cũ "ERP cắt `taskFull.subtasks` ở 59
   thẻ"). Nhánh đọc `taskBoard` cho thẻ bị cắt (`service.py:14410-14414`) vẫn
   cần thiết, nên mục 3.2 phải đọc **cả** `product_type` lẫn
   `custom_product_type` — không được bỏ cái nào.
3. Cây gốc nằm dưới khoá **`root`** của payload (`taskFull` trả
   `{depth, max_depth, max_nodes, max_rows, node_count, root, row_count,
   truncated}`), không phải `task`. Node đầy đủ có 39 khoá, trong đó có
   `product_type`, `sku`, `meta`, `meta_auto`, `parent_subject`.

Lệnh đã dùng: `C:\HaviGroup\pc_taskfull_pt2.py <TASK-ID>` trên hvg-pc.

## Câu hỏi cần người quyết

1. **[không chặn]** ERP và bảng mã Google Sheet bất đồng (cùng sản phẩm,
   khác mã) thì theo ai? Đo thật 12/09: **không có bất đồng nào hôm nay**
   (55/55 sản phẩm chung, cùng mã). Đề xuất của người viết PRD: khi bất đồng
   thật sự xuất hiện, ưu tiên ERP (nguồn chính chủ, người vận hành ERP là
   người quyết định danh mục) nhưng **ghi log rõ** để người vận hành sheet
   biết mà sửa, không âm thầm đè. Rủi ro hướng ngược lại (ưu tiên sheet):
   một sản phẩm ERP đã đổi mã (đổi phân loại) mà sheet chưa cập nhật thì mã
   mới mãi không bao giờ được dùng. Người trả lời: người vận hành ERP + chủ
   bảng sheet "SẢN PHẨM - SKU".
2. **[không chặn]** Thẻ khai `product_type` mà danh mục ERP không có dòng
   nào khớp: rơi về sheet (như PRD này đã chọn, mục 3.3), hay dừng và báo?
   Nhắc lại mâu thuẫn đã có sẵn trong code, không phải do PRD này tạo ra:
   người dùng đã nói "đừng đoán tiền tố SKU", nhưng `derive_prefix()` vẫn
   đoán khi cả `book` lẫn `erp-category` đều trượt (dù kết quả đoán đó bị
   `la_ma_doan()` chặn không cho lên thẻ — xem sku.py:1164-1171, thẻ bị đưa
   vào `skipped`/`unlisted` chứ không nhận mã đoán). PRD này giữ nguyên
   hành vi "rơi về sheet trước, hết cả hai mới bỏ" vì đó là hành vi đã chạy
   thật; đổi thứ tự retry là một quyết định sản phẩm riêng, không tự ý đổi ở
   đây. Người trả lời: người giao việc gốc (chủ tài khoản đặt yêu cầu ban
   đầu).
3. **[không chặn — cố ý để ngoài đợt này]** Có nên tận dụng
   `custom_product_type` sẵn có trên dòng `taskBoard` để bớt lượt mở
   `taskFull` từng thẻ bị cắt? Đụng `fill_cost()` (sku.py:1307-1324) và
   `_LANE_MIN_BUDGET` (1329-1331) — hai số đang chạy thật, PRD anh em
   `tasks/the-cat-da-co-ma.md` vừa đo lại kỹ. Không gộp vào đợt này theo
   đúng yêu cầu gốc. Người trả lời: người quyết PRD `the-cat-da-co-ma`
   (cùng vùng số đo, tránh hai PRD sửa chồng lên `fill_cost`).
4. **[không chặn]** 12/301 thẻ PROJ-0018 không khai `product_type`. Xử lý
   sao? PRD này chọn: không đi lên thẻ cha tìm hộ (khác `effective_product()`
   vốn đi lên cho `product:` gõ tay) — thẻ thiếu `product_type` chỉ đơn
   giản rơi thẳng xuống `book`/`derived` như trước khi có PRD này, không có
   gì thay đổi cho 12 thẻ đó. Đây là lựa chọn an toàn nhất (không thêm hành
   vi mới cần đo), nhưng nếu 12 thẻ đó có thẻ cha đã khai `product_type` thì
   thẻ con sẽ *không* thừa hưởng — khác với cách `product:` gõ tay đang hoạt
   động. Người trả lời: người giao việc gốc (có muốn `product_type` cũng đi
   lên cha như `product:` không?).
5. **[ĐÃ TRẢ LỜI 12/09 — không còn chặn]** Đã đo: `taskFull` **có** trả
   `product_type` trên node con, 59/59 và 49/49 ở hai cụm thật, khớp danh mục
   ra `OR` và `OL`. Xem mục "Số đo `taskFull`" ở trên. Đợt 2 merge được.
   Câu hỏi gốc giữ lại bên dưới để người sau biết vì sao phải đo.

   <details><summary>nguyên văn câu hỏi khi chưa đo</summary>

   Chưa ai đo được
   `taskFull` (nguồn cards chính của `plan_erp_skus`) có trả `product_type`
   cấp 1 trên node con hay không — xem Rủi ro đầu bảng. Cần một lượt chỉ-đọc
   trên hvg-pc (giống cách mục 8 của brief đã đo câu hỏi 1) in thử `taskFull`
   của một cụm có ít nhất một thẻ con, xem `product_type`/`custom_product_type`
   có mặt ở node con không. Không đo trước thì đợt 2 có nguy cơ merge xong
   mà không đổi gì trên 289/301 thẻ đọc qua đường chính. Câu hỏi này do
   người viết PRD tự thêm (không nằm trong yêu cầu gốc), nêu ra vì đây là
   khoảng trống dữ kiện thật, không phải ý kiến. Người trả lời: người có
   quyền chạy script chỉ-đọc trên hvg-pc (như đã làm cho mục 8 của brief).

   </details>

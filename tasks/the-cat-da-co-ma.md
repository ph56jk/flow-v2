# Thẻ bị cắt đã có mã: đọc dòng bảng, bỏ `taskFull`

Mốc số dòng: `origin/agent/hvg-pc-dot8` **c8c0761**, nhánh này tách từ đó.
dot8 nay đã lên **f657949** (qua 7405026: hàng rào giữa lượt be59176, ca G,
dừng lượt khi gặp 429). `sku.py` giống hệt; `service.py` dịch +36 dòng ở vùng
plan, +99 ở vùng chữa tên. Bảng chỗ sửa ghi cả hai mốc. Đỉnh dot8 hiện là
**52a9383**: `service.py` (be808e9) và `sku.py` (0f5c945) cùng blob với
f657949, nên cột f657949 đúng cho 52a9383.

Test đỏ: `tests/test_the_cat_da_co_ma.py`. Quyết của a6, ngày 12/09.
Thẻ cháu dưới thẻ bị cắt: `tests/test_the_chau_the_cat.py`, ngoài phần cài
đợt này (mục 6).

## Kết luận đọc trước

- Cụm 04628 có 37 thẻ đã mang mã nằm ngoài phần `taskFull` trả về (ERP cắt
  ở 59 thẻ). Mỗi lượt đánh số đọc `taskFull` 37 lần chỉ để biết lại mã chúng
  đang mang.
- Bỏ 37 lần đọc ấy khi thẻ chắc chắn không cần gì hơn dòng bảng. 04628 về
  **7 / 11 / 15** request cho 1 / 2 / 3 thẻ mới, thay vì **46 / 50 / 54**.
- `fill_cost` mới **chỉ đi cùng** việc này. Một mình nó thì sai.
- Trước khi làm: c8 chạy một lệnh chỉ-đọc trên ERP thật, xem `custom_sku` có
  đúng bằng dòng `sku:` trong `meta` không (mục 7).

## 1. Vấn đề, kèm số đo

Đo trên ERP giả của d6 (`tests/test_sku_nhanh_moi_the.py`), 37 thẻ có mã bị
cắt, n thẻ mới trong cây, k = vị trí PROJ-0018 trong danh sách dự án. w = số
thẻ bị cắt đang kẹt tên (`ten_cu` đã chép, tên chưa đổi). Số khớp giữa
a8e098d và c8c0761.

| w | k | hôm nay, n = 1/2/3 | sau khi sửa, n = 1/2/3 | `TaskFull` sau khi sửa |
|---|---|---|---|---|
| 0 | 1 | 44 / 48 / 52 | 6 / 10 / 14 | 1 |
| 0 | 14, 27 | 46 / 50 / 54 | **7 / 11 / 15** | 1 |
| 5 | 14, 27 | 51 / 55 / 59 | 17 / 21 / 25 | 6 |
| 37 | 14, 27 | 83 / 89 / 93 | 83 / 89 / 93 | 38 |

- Làn nhanh có 20 request mỗi phút (`budget_per_minute`, sku.py 1387).
  46 không bao giờ lọt.
- Trên hai bản chụp bảng thật, 10/10 thẻ có mã mang tên đúng bằng mã: w = 0
  là trạng thái thường.

## 2. Luật

Thẻ bị cắt khỏi `subtasks` mà plan cần đọc (đã tới lượt, hoặc có
`custom_sku`) **chỉ** bỏ `taskFull` khi đủ ba điều. Thiếu một điều thì đọc như
cũ.

1. Dòng bảng có `custom_sku` khác rỗng, và `subject == custom_sku`.
   - Tên khác mã thì cần `ten_cu:` để biết kẹt tên hay người đặt tên khác.
     Dòng bảng không có `meta`, nên không có `ten_cu`.
2. Không thẻ nào nhận nó làm `parent_task`, và không thẻ nào khai
   `fatheridea:` tới nó.
   - `effective_product` (sku.py 1042–1063) đi qua `product:` và
     `fatheridea:` của thẻ cha. Dòng bảng thiếu `product:`, nên thẻ con sẽ
     nhận nhầm đầu mã.
   - **Phải xét hai vòng.** Lời khai `fatheridea:` của một thẻ bị cắt khác
     (thẻ mới ngoài cây, thẻ tên sai) chỉ lộ ra sau `taskFull` của chính nó.
     Đọc các thẻ buộc phải đọc trước, gom `fatheridea:`, rồi lặp tới khi
     không thêm thẻ nào.
3. `meta` dựng bằng `render_meta_block({"sku": custom_sku})` (erp_meta.py 399).
   - Không có bước này thì plan coi thẻ là chưa có mã: mã không vào
     `used_ideas`, sổ không học, thẻ Working bị lên kế hoạch cấp mã mới.

Thêm một điều giữ nguyên: **`renumber=True` đọc đủ như cũ.** Đánh số lại
tính đầu mã theo `product:` của từng thẻ, mà dòng bảng không có.

## 3. `fill_cost` mới, và vì sao chỉ đi cùng

```text
base      = 3 + 5·n + cut_new + 2·wrong        (n = số thẻ mới trong cụm)
fill_cost = base + 2·⌊base / 40⌋
```

- `cut_new`: thẻ mới cần mã nằm ngoài cây. Mỗi thẻ một `taskFull`.
- `wrong`: thẻ có mã trong cụm mà `subject != custom_sku` trên dòng bảng.
  Mỗi thẻ một `taskFull` và một lần chữa tên.
- `+2 mỗi 40`: lượt dài quá 40 request thì bảng nhớ (60 giây) hết hạn, đọc
  lại bảng.
- Đã kiểm: công thức ≥ số thật ở mọi dòng bảng mục 1 và các cụm A–D, F.
- 04628 lúc tên đúng hết: `fill_cost(1) = 8`, vào làn nhanh. `_LANE_RESERVE`
  lên 9.

**Ràng buộc đi cùng:**

- Chỉ đổi `fill_cost`: công thức giả định thẻ bị cắt tên đúng không tốn gì.
  Code cũ vẫn đọc 37 lần, nên làn tính 8 mà tiêu 46, vượt trần 20/phút, ăn
  429. Tính cho đúng code cũ thì 04628 cần ≥ 46 > 20: `_never_fits`, văng
  khỏi làn nhanh.
- Chỉ đổi `service.py`: `fill_cost` cũ hụt khi có thẻ tên sai hay thẻ mới
  ngoài cây (w = 5, n = 1: tiêu 17, ước 7).
- Đổi `fill_cost` làm đỏ `test_sku.py` 3319. a6 gật cho đổi bài ấy (12/09),
  kèm ba điều d6 phải giữ: xem mục 4, "Test có sẵn mã hoá công thức cũ".

## 4. Chỗ cần sửa (chỉ trỏ chỗ)

### `flow_web/service.py`

| c8c0761 | f657949 | Gì |
|---|---|---|
| 14208, 14214 | 14244, 14250 | `plan_erp_skus`, tham số `renumber`: luật chỉ chạy khi `renumber` là False |
| 14271–14284 | 14307–14320 | `_collect_missing_children`: danh sách thẻ bị cắt |
| 14286–14292 | 14322–14328 | chú thích "đã mang mã thì vẫn đọc đủ": sửa theo luật mới |
| 14293–14301 | 14329–14337 | đọc bảng một lần (có sẵn, trúng bảng nhớ) |
| 14302–14308 | 14338–14344 | `rows`: đã có `parent_task`, `subject`, `custom_sku` |
| 14309–14316 | 14345–14352 | **chỗ thêm nhánh**: hiện chỉ dùng dòng bảng cho thẻ chưa tới lượt, chưa có mã |
| 14317–14329 | 14353–14365 | nhánh `taskFull` cũ: thẻ thiếu điều nào thì vẫn đi đây |
| 14356–14374 | 14392–14410 | plan lấy thứ tự theo bảng: dùng lại `board` ở trên, không đổi |
| 14633–14634 | 14732–14733 | chú thích chữa tên "`taskFull` trả cả tên lẫn `ten_cu`": ghi thêm rằng thẻ từ dòng bảng luôn có tên bằng mã nên không vào `repairs` |

Hai vòng của điều 2 phải nằm trước vòng `for p_id, cid in missing_children`.
Vòng hiện nay quyết từng thẻ theo thứ tự, không biết lời khai của thẻ đứng sau.

### `flow_web/sku.py` (giống nhau ở cả hai mốc)

| Dòng | Gì |
|---|---|
| 1307–1315 | `fill_cost`: công thức mục 3 |
| 1320, 1322 | `_LANE_RESERVE` (lên 9), `_LANE_MIN_BUDGET` (lên 11) |
| 1676–1681 | `_candidates`: **đếm `wrong` ở đây**, từ `by_name`. Dòng thuộc cụm (chuỗi `_ancestors`, 1435, chứa `root`) có `custom_sku` và `subject != custom_sku` |
| 1701, 1724 | `_never_fits`: `need = 1 + trees + fill_cost(len(ids), …, wrong)` |
| 1745 | `_fill_cluster`: `cost` trước khi đọc cây, `cut_new = 0` |
| 1757–1761 | sau khi đọc cây: `cut_new` = thẻ trong `ids` không có trong `_tree_names(payload)`, **mỗi khi** `_tree_is_cut(payload)`. Hôm nay `outside` chỉ tính khi `not due`; thẻ ngoài cây khi `due` vẫn tốn `taskFull` trong plan |
| 1773, 1775, 1799 | dùng `cost` đã tính lại: `_never_fits(..., trees=2)`, `keep=cost`, `budget.take(cost)` |

### Test có sẵn mã hoá công thức cũ

Chạy thử `fill_cost` mới trên các bộ hiện có: đỏ đúng một bài.

- `tests/test_sku.py` 3319,
  `SkuFastLaneTests.test_a_pass_over_two_cards_pays_for_the_board_read`:
  `14 != 13`. Bài này ghi luật cũ "từ hai thẻ mới cộng một lần đọc bảng".
  Luật mới đưa lần đọc ấy vào nền cho mọi n.
  - **a6 gật cho đổi (12/09).** Đây là đổi đặc tả, không phải nới test.
    Cụm sạch: cũ `2 + 5n + [n ≥ 2]`, mới `3 + 5n` (cộng 2 mỗi 40). Mới ≥ cũ
    ở mọi n: n = 1 từ 7 lên 8, n = 2 vẫn 13. Làn chỉ ước dư, không ước hụt.
  - d6 sửa bài ấy phải giữ đủ ba điều:
    - (a) Không xoá ý của bài: vẫn khẳng định lần đọc bảng được tính. Viết
      theo luật mới: `fill_cost(2) == fill_cost(1) + 5`.
    - (b) Thêm assert chống hụt: với n = 0..10, `wrong = 0`, `cut_new = 0`,
      `fill_cost` mới ≥ `2 + 5n + (1 nếu n ≥ 2)`.
    - (c) Giữ con số tuyệt đối `fill_cost(2) == 13`.
- `test_sku_nhanh_moi_the` (6 bài) và các chỗ khác gọi `fill_cost` trong
  `test_sku.py` vẫn xanh, không đụng gì.
- `test_lan_nhanh_cay_cat` (19 bài) **không** xanh sẵn: `fill_cost` mới đắt
  hơn, nên bốn bài dựng cụm ở trần 20 rơi vào "không bao giờ vừa". Bốn bài ấy
  dựng lại làn ở **trần 21** (`SkuFastLaneConfig(budget_per_minute=21)`), giữ
  nguyên mọi assert và tên bài. Đây là đổi điều kiện dựng, không phải hạ con
  số: cụm vẫn phải lọt đúng như trước, chỉ là ngân sách phải theo giá mới.

## 5. Test đỏ (`tests/test_the_cat_da_co_ma.py`)

ERP giả của d6, thêm `subject` vào dòng bảng như dòng thật. Trần tính bằng
`tran_moi()` trong test, không chép số đo.

| Bài | Kiểm |
|---|---|
| `test_the_cat_ten_dung_ma_khong_doc_taskfull` | w = 0, n = 1/2/3, k = 14/27: chỉ 1 `TaskFull`, đủ mã, ≤ trần |
| `test_the_moi_ngoai_cay_van_doc_taskfull` | thẻ mới ngoài cây vẫn đọc, ≤ trần có `cut_new` |
| `test_the_ket_ten_van_doc_va_duoc_chua` | w = 5: đúng 5 thẻ kẹt tên bị đọc, cả 5 được chữa, ≤ trần |
| `test_the_cat_la_dich_fatheridea_van_doc_taskfull` | thẻ trong cây khai `fatheridea` tới thẻ bị cắt: thẻ ấy vẫn đọc, thẻ con nhận `BM_` |
| `test_the_moi_ngoai_cay_khai_fatheridea_toi_the_cat` | lời khai nằm trên thẻ mới ngoài cây: vẫn đọc thẻ cha (hai vòng) |
| `test_the_cat_la_cha_van_doc_taskfull` | thẻ bị cắt là `parent_task` của một dòng: vẫn đọc |
| `test_dong_bang_trong_custom_sku_van_doc_taskfull` | dòng bảng trống `custom_sku`: vẫn đọc, giữ mã, không bị ghi |
| `test_khong_cap_trung_ma` | còn sổ và mất sổ: không thẻ nào hai mã, mã cũ không phát lại, sổ lên đúng 37 + n |
| `test_cum_sach_dung_so_request_nhu_hom_nay` | canh: cụm sạch B/F, k = 1/14/27, đúng từng loại request |
| `test_ngoai_luot_van_doc_bang_tuoi` | canh: hàng rào ngoài lượt vẫn đọc bảng tươi |
| `test_danh_so_lai_van_doc_taskfull` | canh: `renumber=True` vẫn đọc mọi thẻ bị cắt |

Tám bài đầu đỏ trên c8c0761, 7405026 và f657949 ở chỗ assert tập `TaskFull`: cả 37
thẻ bị cắt đều bị đọc. Ba bài canh xanh. Bản cài mô phỏng đúng luật trên
(vá lúc chạy, không commit) cho xanh cả 11. Bài canh `renumber` nằm ngoài
danh sách brief; a6 giữ (12/09).

Ngoài bộ này: `tests/test_the_chau_the_cat.py` (mục 6). **Không thuộc phần
d6 cài đợt này**: bài đỏ cả trước lẫn sau đợt, không phải điều kiện xong.

## 6. Rủi ro

- **Độ tươi:** dòng bảng lấy từ bảng nhớ đầu lượt. Người sửa mã một thẻ bị
  cắt đúng lúc ấy thì sổ không học mã mới. Cùng loại rủi ro với thẻ chưa tới
  lượt. Lượt `taskDetail` trước khi ghi vẫn che chính thẻ đang ghi.
- **`renumber`:** quên nhánh này thì đánh số lại lấy đầu mã theo thẻ gốc
  cho thẻ có `product:` riêng. Có bài canh.
- **`fatheridea` trên chính thẻ dựng từ dòng bảng:** không biết được. Không
  sao: thẻ ấy đã có mã, plan không tính lại mã cho nó.
- **`prefix_source`** của thẻ giữ mã (chỉ để báo cáo) có thể theo thẻ gốc.
- **Người đổi tên thẻ** khác mã thì làn đếm vào `wrong`: ước dư, cụm lớn có
  thể rời làn nhanh sang lượt quét chính. An toàn, chỉ chậm.
- **Có từ trước, ngoài phạm vi:** thẻ cháu có `parent_task` là một thẻ bị
  cắt không bao giờ được đánh số. `_collect_missing_children` chỉ đi
  `children` của nút trong cây, và nhánh bị cắt không duyệt cây con. Thử trên
  ERP giả: `written []`, `failed []`, thẻ cháu không nằm trong `skipped`.
  - Test đỏ riêng: `tests/test_the_chau_the_cat.py`,
    `test_the_chau_cua_the_cat_duoc_danh_so` (cha Open, cha Working). a6
    quyết 12/09: có bài, nhưng **ngoài phần d6 cài đợt này**.
  - Đỏ 2/2 trên c8c0761, f657949, 52a9383, đúng vì thẻ cháu không được
    thấy. Cho thẻ cha lộ ra trong cây gốc (chỉ đổi ERP giả) thì bài xanh.
- **`custom_sku` trên ERP thật có thể khác `meta`.** Mục 7.

## 7. Câu hỏi ERP thật cho c8

**`custom_sku` trên dòng `taskBoard` có đúng bằng dòng `sku:` trong `meta`
không?** Điều 3 tin điều này. Làn nhanh (sku.py 1454) và `agent_bot.py` đã
tin nó; ERP giả của d6 dựng nó từ `meta`; chưa ai đối chiếu trên ERP thật.

Lệnh, chạy từ `/Users/admin/orca/workspaces/agenthavi`:

```bash
ssh hvg-pc 'set PYTHONIOENCODING=utf-8&& C:\HaviGroup\flow-v2\.venv\Scripts\python.exe -' < briefs/c8-scripts/the_cat_custom_sku.py
```

- Chỉ đọc. POST `https://erp.havigroup.llc/api/method/hvg_workspace.graphql.endpoint.graphql`,
  12 request cách nhau 2 giây:
  - 1 × `taskBoard(project: "PROJ-0018", includeArchived: false)`: lấy
    `name`, `parent_task`, `custom_sku`, `subject`;
  - 1 × `taskFull(name: "TASK-2026-04628", depth: 3)`: lấy tên trong
    `root.subtasks`;
  - 10 × `taskDetail(name)`: lấy `meta` (đọc `sku:` bằng chính
    `flow_web.erp_meta.task_meta` trên hvg-pc) và `subject`.
- **10 thẻ nào:** 10 tên đầu, xếp theo tên, trong các dòng bảng có
  `parent_task = TASK-2026-04628`, `custom_sku` khác rỗng, và không nằm
  trong `root.subtasks`. Script in tên từng thẻ.
- Khoá lấy như service. Nạp `C:\HaviGroup\flow-v2\.env.local` bằng chính
  `flow_web.review_lister._load_env_file` (biến đã có trong môi trường thì
  thắng), rồi đọc `ERP_API_KEY`, `ERP_API_SECRET`.
  - Env thiếu thì mới đọc `erp_config` trong `data\state.json`, chỉ mở để
    đọc (không dựng `StateStore`, vì hàm dựng có thể ghi lại file).
  - Thiếu cả hai thì dừng, 0 request.
  - Không in khoá, độ dài hay ký tự nào của khoá; không đưa khoá vào lệnh.
  - Lần chạy 13:15 ngày 12/09 dừng ở bước này, 0 request: `state.json` trên
    hvg-pc không có `erp_config`. Bản hiện nay sửa chỗ ấy.
- In thêm, không tốn request: bao nhiêu thẻ bị cắt có mã là cha của dòng
  khác, bao nhiêu bị thẻ trong cây khai `fatheridea` tới.
- **Đọc kết quả:** `khop 10/10` thì điều 3 an toàn. Lệch dù một thẻ thì dừng,
  báo a6 trước khi d6 cài.

Bản chép của script (nguồn là `briefs/c8-scripts/the_cat_custom_sku.py`).
Đã chạy thử với ERP giả, bốn ca khoá:
- khoá từ `.env.local`: 12 request;
- env có sẵn: 12 request;
- chỉ có `state.json`: 12 request;
- thiếu cả hai: dừng, 0 request.

Không ca nào lộ khoá, và ca nào chạy đủ cũng bắt được thẻ lệch.

```python
# Chỉ đọc ERP.  Hỏi: custom_sku trên dòng taskBoard có đúng bằng dòng sku:
# trong meta (taskDetail) không, với 10 thẻ con có mã của 04628 bị cắt khỏi
# taskFull.  Không ghi gì, không in khoá.
# 1 taskBoard + 1 taskFull + 10 taskDetail = 12 request, cách nhau 2 giây.
import json
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

APP = r"C:\HaviGroup\flow-v2"
sys.path.insert(0, APP)
from flow_web.erp_meta import task_meta  # noqa: E402  cùng hàm bot dùng để đọc sku:

ROOT, PROJECT, TAKE = "TASK-2026-04628", "PROJ-0018", 10
URL = "https://erp.havigroup.llc/api/method/hvg_workspace.graphql.endpoint.graphql"

# Khoá lấy như service: env trước.  ``.env.local`` nạp bằng chính hàm của
# bot (biến đã có trong môi trường thì thắng, không in gì).  Env thiếu thì
# mới đọc erp_config trong state.json, chỉ đọc: không dựng StateStore, vì
# hàm dựng có thể ghi lại file.  Không in khoá, độ dài hay ký tự nào của khoá.
import os  # noqa: E402
from pathlib import Path  # noqa: E402

from flow_web.review_lister import _load_env_file  # noqa: E402

_load_env_file(Path(APP) / ".env.local")
KEY = os.environ.get("ERP_API_KEY", "").strip()
SECRET = os.environ.get("ERP_API_SECRET", "").strip()
if not KEY or not SECRET:
    try:
        with open(Path(APP) / "data" / "state.json", encoding="utf-8") as fh:
            cfg = json.load(fh).get("erp_config") or {}
    except (OSError, ValueError):
        cfg = {}
    KEY = str(cfg.get("api_key") or "").strip()
    SECRET = str(cfg.get("api_secret") or cfg.get("token") or "").strip()
if not KEY or not SECRET:
    sys.exit("thiếu ERP_API_KEY/ERP_API_SECRET: dừng.")


def ask(op, query, variables):
    body = json.dumps({"query": query, "variables": variables, "operationName": op}).encode("utf-8")
    req = Request(URL, data=body, method="POST", headers={
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Flow-v2-HaviGroup-ERP/1.0",
        "Authorization": "token %s:%s" % (KEY, SECRET),
    })
    try:
        with urlopen(req, timeout=60) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        sys.exit("%s: HTTP %s, dừng." % (op, exc.code))
    time.sleep(2)
    if out.get("errors"):
        sys.exit("%s lỗi: %s" % (op, json.dumps(out["errors"], ensure_ascii=False)[:300]))
    value = (out.get("data") or {}).get(op[0].lower() + op[1:])
    return json.loads(value) if isinstance(value, str) else (value or {})


board = ask(
    "TaskBoard",
    "query TaskBoard($project: String!) { taskBoard(project: $project, includeArchived: false) }",
    {"project": PROJECT},
)
rows = {}
for column in board.get("columns") or []:
    for row in column.get("tasks") or []:
        rows.setdefault(str(row.get("name") or ""), row)

full = ask(
    "TaskFull",
    "query TaskFull($name: String!, $depth: Int) { taskFull(name: $name, depth: $depth) }",
    {"name": ROOT, "depth": 3},
)
node = full.get("root") if isinstance(full.get("root"), dict) else full
subtasks = node.get("subtasks") or []
shown = {str(item.get("name") or "") for item in subtasks}

coded = sorted(
    name for name, row in rows.items()
    if str(row.get("parent_task") or "") == ROOT and str(row.get("custom_sku") or "").strip()
)
cut = [name for name in coded if name not in shown]
parents = {str(row.get("parent_task") or "") for row in rows.values()}
fathers = {task_meta(item).father_idea for item in subtasks}
print("bang %d dong | con 04628 co ma %d | bi cat %d | cay tra %d the" % (len(rows), len(coded), len(cut), len(shown)))
print("the bi cat co ma ma la cha: %d | bi the trong cay khai fatheridea: %d" % (
    len(set(cut) & parents), len(set(cut) & fathers)))

pick = (cut or coded)[:TAKE]
same = 0
for name in pick:
    detail = ask("TaskDetail", "query TaskDetail($name: String!) { taskDetail(name: $name) }", {"name": name})
    row = rows[name]
    custom = str(row.get("custom_sku") or "").strip()
    meta_sku = task_meta(detail).sku
    same += custom == meta_sku
    print(json.dumps({
        "name": name,
        "bi_cat": name in cut,
        "custom_sku": custom,
        "meta_sku": meta_sku,
        "khop": custom == meta_sku,
        "subject_bang": row.get("subject"),
        "subject_the": detail.get("subject"),
        "ten_bang_bang_ma": str(row.get("subject") or "").strip() == custom,
    }, ensure_ascii=False))
print("khop %d/%d" % (same, len(pick)))
```

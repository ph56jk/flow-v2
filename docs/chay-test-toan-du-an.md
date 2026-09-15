# Chạy test toàn dự án

Repo này có **năm** bộ test, không phải một, và bốn trong năm bộ cần chạy từ
đúng thư mục của nó. Ai chỉ chạy `unittest discover -s tests` rồi báo "test
xanh" là mới nói về 1296 bài trong số 1606.

## Một lệnh, nếu chỉ muốn biết nhánh có sạch không

```bash
scripts/chay-test.sh          # chạy hết, không dừng ở bộ đỏ đầu tiên, in một bảng
scripts/chay-test.sh --sach   # đo ở worktree sạch tại HEAD
scripts/chay-test.sh 3        # chỉ một bộ
```

Script tự tránh cả bốn cái bẫy dưới kia, và thoát 0 khi không bộ nào đỏ vì
code. Bộ 5 đỏ vì máy thiếu `pytest` được tính là MÔI TRƯỜNG và không làm hỏng
mã thoát — nhưng chỉ khi log chứa đúng chuỗi `No module named 'pytest'`; đỏ vì
lý do khác vẫn là đỏ thật.

Phần còn lại của tài liệu này là năm lệnh rời, cho lúc cần chạy tay một bộ,
đọc log đầy đủ, hoặc kiểm chính script.

## Năm lệnh

```bash
cd /Users/admin/orca/agenthavi

# 1. flow_web — bộ lớn nhất, ~170 giây.
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'

# 2. automation_center, phía Python (runner).
(cd automation_center && ../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')

# 3. automation_center, phía Worker (node:test).
node --test --experimental-sqlite automation_center/tests/*.test.mjs

# 4. bmad-init.
(cd _bmad/core/bmad-init/scripts && ../../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')

# 5. bmad-distillator — xem mục "Đã biết" bên dưới trước khi chạy.
(cd _bmad/core/bmad-distillator/scripts && ../../../../.venv/bin/python -m pytest tests -q)
```

## Bốn cái bẫy đã mất thời gian của người khác

- **`node --test --experimental-sqlite automation_center/tests/`** (đường dẫn
  thư mục) hỏng trên máy này ngay cả khi cờ đã đủ: node coi `tests` là một
  module để nạp và chết với `MODULE_NOT_FOUND`, rồi in ra `# fail 1` như thể
  có một bài đỏ. Phải dùng glob `*.test.mjs`. Thiếu `--experimental-sqlite`
  thì lỗi lại khác, và cũng không phải lỗi code.
- **Chạy một bài lẻ phải có tiền tố `tests.`**: `unittest discover` in ra tên
  module *không* kèm tên gói, nên chép nguyên tên từ dòng `FAIL:` sẽ ra
  `ModuleNotFoundError`. Đúng là
  `.venv/bin/python -m unittest tests.test_flow_web_smoke.JobHistoryTrimTests`.
- **`discover -t .` hỏng** vì `tests/` không có `__init__.py`. Cứ để mặc định.
- **`timeout` không tồn tại trên macOS.** Đừng bọc lệnh test bằng nó.

## Đã biết, không phải lỗi của nhánh nào

- Bộ 5 (`bmad-distillator`) **không chạy bằng `unittest`**. Bài của nó viết
  bằng pytest thật (`@pytest.fixture`), nên `unittest discover` không gom được
  bài nào:

  | `.venv` | lệnh cũ `unittest discover` | thực chất |
  |---|---|---|
  | thiếu pytest | `Ran 1 test … FAILED` | 1 "bài đỏ" ấy là lỗi import, không phải bài test |
  | có pytest | `Ran 0 tests … OK` | **xanh mà chạy rỗng** — 33 bài không chạy bài nào |

  Nghĩa là cả 33 bài của bộ 5 chưa từng chạy bằng lệnh cũ, và trên máy dựng
  `.venv` đúng thì lệnh ấy còn **báo OK**. Đo được, không phải suy luận. Lệnh
  đúng là:

  ```bash
  (cd _bmad/core/bmad-distillator/scripts && ../../../../.venv/bin/python -m pytest tests -q)
  ```

  Chạy đúng thì ra **33 bài, xanh cả**. 18 hàm `def test_`, trong đó một hàm
  dùng `parametrize` nên nở thành 16 — nên "18" và "33" đều đúng, chỉ là đếm
  hai thứ khác nhau: hàm và bài.

  Thiếu pytest thì là **MÔI TRƯỜNG**, không phải lỗi code, và sửa bằng một lệnh:

  ```bash
  .venv/bin/python -m pip install -e '.[dev]'
  ```

  `pyproject.toml` ở gốc repo **có** khai pytest — trong
  `[project.optional-dependencies] dev` — và `CLAUDE.md` đã ghi đúng lệnh dựng
  `.venv` ấy từ đầu. Đọc được nên cài gì, chỉ là chưa cài.

  Ghi rõ vì bản trước của tài liệu này nói ngược lại — rằng repo không có
  `pyproject.toml` nào và không chỗ nào khai pytest. Sai cả hai vế. Câu sai ấy
  đẩy người đọc sang hướng viết lại các bài `@pytest.fixture` sang `unittest`,
  một lượt việc dài, để né một lệnh `pip install`. Con số "18 bài" ở bản cũ
  cũng sai: chạy đúng bằng pytest thì ra **33 bài**.

- Bộ 1 có vài bài in cảnh báo ra stderr (thiếu Chromium đầy đủ, sổ SKU hỏng
  trong thư mục tạm). Cảnh báo, không phải bài đỏ — đọc dòng `Ran N tests`
  và `OK`/`FAILED` ở cuối, đừng đọc stderr.

## Số nền, để so

Đo ở **worktree sạch ghim `e6dd796`** — commit mở nhánh
`agent/prd-agent-improvements-tdd` (2026-09-03), chỗ bộ test đỏ được đặt vào:

| Bộ | Số bài | Trạng thái |
|---|---|---|
| 1. `tests/` | 1276 | **48 đỏ** (34 `FAIL` + 14 `ERROR`) |
| 2. `automation_center` Python | 85 | xanh |
| 3. `automation_center` node | 189 | **33 đỏ** — mục B chưa cài xong |
| 4. `bmad-init` | 35 | xanh |
| 5. `bmad-distillator` | 0 (33 khi có pytest) | MÔI TRƯỜNG — `.venv` thiếu `[dev]` |

Cộng: **1586 bài, 82 đỏ**.

Bảng này từng ghi "8 đỏ" và "6 đỏ" — **hai số ấy sai**, chúng là số của một
lần đo giữa chừng ở cây làm việc chứ không phải của commit mở nhánh. Đây là
đúng cái bẫy mà câu "đo ở worktree sạch tại commit" ở trên nói tới: cây làm
việc có thể đang được một file chưa commit đỡ hộ, và số đo ra không thuộc về
commit nào cả.

Bài đỏ vì **mục PRD chưa tới lượt cài** thì ghi vào "Tồn đọng" kèm tên mục,
đừng gọi là lỗi code — và đừng sửa test cho nó xanh.

## Chốt mạng: bộ 1 không gọi được ra ngoài máy

`tests/network_guard.py` chặn mọi kết nối ra ngoài trong bộ 1, và
`tests/test_0_network_guard.py` bật nó. Tên file bắt đầu bằng `0` là cố ý:
`unittest discover` nạp module theo thứ tự chữ cái, nên chốt đứng sẵn trước
khi bài đầu tiên chạy. Có một bài tự kiểm điều đó — đổi tên file ấy thành cái
gì sắp sau `test_a…` là bỏ chốt đi, và bộ test sẽ nói ra.

Vì sao có nó: lượt soát đợt A tìm thấy một fixture giả lập nhầm chỗ, khiến bộ
test bắn một loạt request sai khoá vào ERP **production** mỗi lần chạy. Không
lộ khoá, nhưng ERP nào khoá tài khoản theo số lần sai thì bộ test tự khoá tài
khoản — và chuyện ấy chạy im suốt vì một request 401 không làm bài nào đỏ.

Gặp lỗi này khi chạy test:

```
OutboundNetworkBlocked: Bộ test vừa gọi ra ngoài máy: erp.havigroup.llc:443
```

thì **không phải sửa chốt**. Nghĩa là bài ấy đang chạm dịch vụ thật: hãy giả
lập lớp HTTP của nó. Loopback (`127.0.0.1`, `localhost`) vẫn đi qua bình
thường, nên bài nào dựng server thật để đo vẫn chạy được.

Bài tích hợp có chủ đích thì bọc bằng `tests.network_guard.allow_outbound`,
kèm lý do viết ra được — hàm ấy từ chối lý do rỗng, và lý do nằm trong diff
cho người soát đọc:

```python
from tests.network_guard import allow_outbound

with allow_outbound("đo thời gian trả lời thật của ERP, chạy tay"):
    ...
```

Không có biến môi trường nào tắt chốt. Một cái công tắc trong env là cái sẽ
được bật lên trong CI rồi không ai gỡ.

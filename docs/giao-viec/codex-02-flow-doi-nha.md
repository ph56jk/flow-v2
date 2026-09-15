# Giao việc Codex #02 — Google Flow đã dời nhà, app đang mở sai địa chỉ

## Đây là dữ liệu đo thật, không phải suy đoán

Tôi (Claude) đã mở một bản sao profile trình duyệt Flow
(`~/.flow-py/browser-profile`, sao ra chỗ khác nên không đụng service đang
chạy), đăng nhập vẫn còn nguyên, rồi đo bốn địa chỉ. Kết quả:

| Địa chỉ | Ra cái gì |
|---|---|
| `labs.google/fx/vi/tools/flow` | **trang giới thiệu công khai**, 0 `input[type=file]` |
| `labs.google/fx/vi/tools/flow/project/<id>` | **cũng trang giới thiệu**, không chuyển hướng, không có editor |
| `flow.google.com/` | **dashboard thật, đã đăng nhập**, liệt kê 21 dự án |
| `flow.google.com/project/<id cũ>` | 404 → `flow.google.com/404?reason=project` |

Nói thẳng: **Google Flow đã dời sang `flow.google.com`.** Đường dẫn app đang
dùng (`config.project_url`, dạng `https://labs.google/fx/vi/tools/flow/project/<id>`)
giờ trả về trang quảng cáo. Không có nút Tác nhân, không có ô prompt, không có
ô chọn file — nên bước đính ảnh **chết là hệ quả, không phải nguyên nhân**.

Việc #01 (nới locator) vẫn giữ, nhưng nó không phải cái đang làm hỏng dây
chuyền. Cái này mới là.

## ID dự án cũng đã khác

`project_id` trong state là `a4737705-1551-4900-ad41-e622f15b87db`. ID này
**không nằm** trong 21 dự án của dashboard mới, và mở thẳng thì 404. Dạng URL
mới là `https://flow.google.com/project/<uuid>`.

## Giao diện mới — đo tận nơi

Mở `https://flow.google.com/project/1a8b808d-58cd-4e92-b704-9a636d9b38a9`
(một dự án thật của chủ nhân) rồi quét cả shadow DOM. Panel tác nhân giờ **mở
sẵn ở cột phải**, không còn nút bật/tắt "Tác nhân" riêng. Các nút quanh ô
prompt, kèm toạ độ trên khung 1440×900:

```
(1103, 839) 32x32  button  aria-label="Thêm thành phần vào ô nhập câu lệnh"  icon text: add     ← ĐÂY là nút đính ảnh
(1307, 839) 32x32  button  aria-label="Chỉ dẫn cho tác nhân"                 icon text: article_spark
(1343, 839) 32x32  button  aria-label="Cài đặt"                              icon text: tune
(1379, 839) 32x32  button  aria-label="Bắt đầu tạo"                          icon text: arrow_forward
(1370, 826) iframe title="reCAPTCHA"
```

Ô prompt là một `div` (không phải `textarea`) ở `(1111, 799)` cỡ `288x20`,
không có `placeholder`, chữ hiển thị "Bạn muốn tạo gì?".

**`input[type=file]` trong DOM lúc nghỉ: 0 cái.** Kể cả quét shadow DOM. Nên
nhánh dự phòng `_set_any_file_input()` không bao giờ có gì để bám — ô chọn file
chỉ sinh ra sau khi bấm nút `add`, qua `file_chooser`. Đừng trông vào nó.

Dữ liệu thô: `flow-nut.json`, `flow-host.json`, `flow-duan.json` và ba ảnh chụp
màn hình nằm trong thư mục scratchpad phiên này, tôi dán lại đủ ở trên rồi.

## Việc phải làm

1. **Tìm hết mọi chỗ ghép URL Flow trong repo** — `labs.google/fx`, `/tools/flow`,
   `project_url`, `_project_url()`, và cả trong thư viện `flow` (flow-py) nếu nó
   cũng hardcode. Grep trước, đừng sửa mò.
2. **Cho địa chỉ thành cấu hình được**, mặc định `https://flow.google.com`, và
   giữ đường lùi về `labs.google` để không phá bản đang chạy nếu Google trả lại.
   Có test khoá dạng URL mới.
3. **Chưa đụng vào việc ánh xạ ID dự án cũ sang mới** — đó là việc vận hành, chủ
   nhân phải chọn dự án nào, tôi lo. Cứ để `project_id` là cấu hình.
4. Regex `addish` ở việc #01 **có** khớp `Thêm thành phần vào ô nhập câu lệnh`
   (nhờ chữ "thêm"), nên locator sẽ chạy khi vào đúng trang. Đừng sửa thêm
   phần đó.

## Hai lỗi ở bản vá #01, sửa luôn

1. `candidateDiagnostics` đang lọc `item.nearBox` trước khi cắt 20 phần tử. Khi
   hỏng vì **không có** nút nào gần ô prompt — đúng cái ca mù mà ta đang chữa —
   danh sách chẩn đoán sẽ rỗng tuếch. Nếu không có phần tử `nearBox` nào thì
   phải đổ về top-20 theo điểm, đừng trả mảng rỗng.
2. `const target = scoredTarget || candidates[0]` là **nguy hiểm**. Khi không
   nút nào qua 400, `candidates[0]` là nút điểm cao nhất toàn trang — trên giao
   diện mới có sẵn `Tuỳ chọn khác`, `Gắn cờ cho đầu ra`, và ở dashboard còn có
   `delete`. Bấm mù vào đó là xoá thẻ của chủ nhân. Hãy chặn: nhánh dự phòng chỉ
   nhận nút vừa `nearBox`, vừa (`addish` hoặc `svgOnlyRoleButton`), và phải loại
   thẳng nhãn có `delete|xoá|xoa|remove|thùng rác|thung rac|sign ?out|đăng xuất`.

## Luật cứng

Như việc #01: không nới lỏng test, không sửa `.env.local`/`data/state.json*`,
chú thích tiếng Việt câu ngắn. Chạy đủ năm bộ test, dán số thật.
Ghi kết quả vào `docs/giao-viec/codex-02-ket-qua.md`.

---

## Bổ sung: tôi đã grep sẵn, đừng thay mù

**Đừng đổi tất cả `labs.google` thành `flow.google.com`.** Phần gọi API vẫn
sống: `/api/flow/project-debug` đọc được 803 workflow, và trên host mới có một
dự án do chính app tạo lúc 10:16 sáng nay. Nghĩa là backend vẫn nhận
`Referer/Origin: labs.google`. Chỉ **đường dẫn để mở trang** là chết.

Tách làm hai nhóm:

**Nhóm ĐIỀU HƯỚNG — phải đổi:**

```
flow_web/schemas.py:90     _project_url() → f"https://labs.google/fx/vi/tools/flow/project/{id}"
flow_web/service.py:1682   fallback url khi chưa có page
flow_web/service.py:1690   target_url mở project
flow_web/service.py:8207   target_url = ".../fx/vi/tools/flow"
flow_web/service.py:20540  target_url mở project
flow_web/service.py:21920  is_on_flow = "labs.google" in page.url   ← phải nhận cả hai host
```

**Nhóm API — GIỮ NGUYÊN, đang chạy tốt:**

```
flow_web/service.py:17308  media.getMediaUrlRedirect
flow_web/service.py:17362  ghép tiền tố cho URL media tương đối
flow_web/service.py:19697  media fallback
flow_web/service.py:1599   truy vấn cookie host_key — đã bắt cả '%.google.com' rồi, để yên
```

## Chỗ khó: thư viện `flow-py` cũng hardcode

`pyproject.toml` ghim `flow-py` theo commit
`bd01679304d6fccc4c96fea3b33151c2e9e836f4`. Bên trong nó cũng cứng:

```
flow/_api.py:64      FLOW_BASE     = "https://labs.google/fx"
flow/_browser.py:23  FLOW_BASE_URL = "https://labs.google/fx/tools/flow"
flow/_client.py:96   self._project_url = f"https://labs.google/fx/tools/flow/project/{id}"
flow/_client.py:134  if "labs.google" not in page.url: ...
flow/_flow_ui.py:62  f"https://labs.google/fx/tools/flow/project/{id}/edit/{workflow_id}"
```

`flow/_api.py:461-462` đặt `referer`/`origin` là `labs.google` — **giữ nguyên**,
vì đó là phần đang chạy được.

Không sửa file trong `.venv` (nâng gói là mất). Hãy vá từ phía repo: ghi đè
các hằng điều hướng của `flow-py` ngay lúc khởi tạo client trong `flow_web`,
đặt sau một hàm cấu hình để đổi được mà không phải sửa code. Nếu thấy cách nào
sạch hơn thì đề xuất, đừng tự ý fork thư viện.

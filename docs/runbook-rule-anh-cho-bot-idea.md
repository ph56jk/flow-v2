# Runbook — rule ảnh cho đường bot idea

Từ đợt này, thẻ idea mà bot tự chạy đi **cùng một bộ rule** với tool tay:
`flow_web/shot_rules.py` (bảng `HAVI_Shot_Types_All_Products`, 38 loại hàng).

## Trước và sau

| | Trước | Sau |
|---|---|---|
| Prompt | 4 dòng, không đọc rule | brief đầy đủ: khoá sản phẩm, bộ shot, luật ánh sáng |
| Số ảnh | luôn 12 | theo `target_count` của rule (10 / 12 / 14) |
| Thẻ không nhận ra sản phẩm | vẫn chạy | **bỏ qua**, ghi lý do vào `skipped` |

Chỗ sửa: `enqueue_erp_idea_jobs` trong `flow_web/service.py`. Bot vào đúng cửa
đó (`_agent_bot_autorun`), nên không phải sửa gì thêm ở `agent_bot.py`.

## Sản phẩm được nhận ra bằng ba đường

1. **Tên thẻ** — đọc từ hẹp tới rộng: tên thẻ nguồn, rồi tên thẻ cha. Khớp
   theo `aliases` của từng rule, có cả tiếng Việt (`khăn tay cô dâu`,
   `mũ sinh nhật`, `vương miện`…).
2. **Tên bảng** — khi không tên thẻ nào gọi được tên hàng. Bảng ở đây vốn đã
   đặt theo sản phẩm (*XMAS Ornament Thêu Tròn*), mà ERP trả `project_name`
   ngay trong payload thẻ nên **không tốn request nào**. Payload thẻ không
   mang khoá ấy thì hỏi `taskBoard` đúng một lần cho cả lượt.
3. **Ảnh nguồn** — Gemini soi ảnh rồi xếp vào một rule. Chỉ chạy khi app có
   khoá Gemini.

Thứ tự là từ hẹp tới rộng và cái hẹp hơn thắng: tên thẻ nói riêng thẻ ấy, tên
bảng nói cả bảng. Chỉ những tên **gọi được tên hàng** mới được tính — `Idea`,
`Idea 7`, `OR_18_007` đều bị coi là không nói gì, và nhường lượt cho tên sau.

Không đường nào ra kết quả thì thẻ bị bỏ qua, `skip_code = missing_product_rule`,
lý do ghi rõ là thiếu khoá Gemini hay Gemini không xếp được.

**Tên thẻ và tên bảng đều thắng tên file ảnh.** Bẫy gặp thật ở bảng *XMAS
Ornament Thêu Tròn*: thẻ cha tên trống trơn là `Idea`, còn ảnh nguồn tên
`Embroidered_church_on_hoop_ornament_...` — chữ `hoop` khớp `wedding_hoop`,
nên bot **vẫn chạy** nhưng chạy sai bộ shot, 12 ảnh thay vì 14. Cổng chặn
không cứu được chuyện này: nó chỉ hỏi "có nhận ra sản phẩm không", không hỏi
"nhận có đúng không".

Đường tên bảng đóng đúng cái bẫy ấy mà không phải sửa gì bằng tay: bảng đã tên
`XMAS Ornament Thêu Tròn` rồi, và tên bảng được đọc **trước khi** rơi xuống rổ
chữ có tên file. Chạy thử trên payload thật của PROJ-0018: 10/10 thẻ con ra
`ornament_round`, cả trước lẫn sau lượt đánh số, không sửa tên thẻ nào.

Dán tên sản phẩm vào *mô tả* thẻ cha thì vẫn không ăn thua — mô tả nằm chung
rổ chữ với tên file, mà `wedding_hoop` đứng trước `ornament_round` trong bảng
ưu tiên. Muốn ghi tay thì ghi vào **tiêu đề**.

**Thẻ con đã đánh số vẫn đọc được sản phẩm.** Sau lượt cấp mã, thẻ con không
còn tên `Idea 7` nữa mà tên là `OR_18_007`. Thẻ con *có ảnh idea riêng* thì
chính nó là thẻ nguồn, nên tên nó là chỗ bộ nhận diện đọc trước — mà một dãy
mã thì không nói ra hàng gì. Bộ nhận diện coi tên hình mã SKU là **không nói
gì**, y như tên một chữ cái, rồi mượn tên thẻ cha. Nhờ vậy đánh số xong bảng
vẫn chạy đúng rule. Đây là lý do tên thẻ cha phải đúng *trước* khi đánh số:
sau đó nó là tín hiệu duy nhất còn lại.

Vài alias tiếng Việt được thêm tay vào `ornament_round` cho đúng cách gọi
trên bảng (`xmas ornament`, `ornament thêu tròn`). `flow_web/shot_rules.py`
sinh ra từ file Excel, nên **sinh lại là mất** — chỗ thêm tay có ghi chú
ngay trên đầu, chép lại sau mỗi lần sinh.

Cổng này nằm ở `enqueue_erp_idea_jobs`, nên lượt **vá thiếu ảnh** cũng đi qua
đó: thẻ chưa nhận ra sản phẩm thì không vá, không phải chỉ không chạy mới.

## Bot đứng im, `skipped` toàn `missing_product_rule` thì làm gì

Ba cách, chọn một:

1. **Bật Gemini** — màn Tích hợp trong app, điền API key. Đây là cách đúng:
   ảnh nào cũng soi được, không phụ thuộc người đặt tên thẻ.
2. **Đặt tên bảng hoặc tên thẻ cha theo sản phẩm** — ví dụ bảng *Khăn tay cô
   dâu*, hoặc thẻ cha `Idea khăn tay cô dâu tháng 9`. Tên bảng lợi hơn: đặt
   một lần cho cả bảng, thẻ mới mở sau cũng ăn theo. Phải là **tiêu đề**,
   không phải mô tả: mô tả nằm chung rổ chữ với tên file ảnh nên có thể thua.
3. **Tắt cổng chặn** — `ERP_IDEA_REQUIRE_PRODUCT_RULE=0` trong `.env.local`,
   rồi khởi động lại Flow. Chạy lại như lối cũ: có ảnh, nhưng ảnh ngoài rule.
   Chỉ dùng khi cần chữa cháy.

Kiểm tra nhanh máy có khoá Gemini chưa:

```bash
curl -s http://127.0.0.1:8000/api/state | python -c \
  "import json,sys; print(json.load(sys.stdin)['integrations']['gemini'])"
```

`{'configured': False, ...}` là chưa có.

## Đọc kết quả một lượt chạy

`enqueue_erp_idea_jobs` trả về:

- `queued[].product_rule_key` — rule đã khớp, rỗng nghĩa là chỉ khớp nhóm hàng
  (tạp dề, gối, thú bông…) chứ chưa khớp rule cụ thể;
- `queued[].count` — số ảnh thật của thẻ đó;
- `skipped[].skip_code` — `missing_product_rule` là thẻ bị cổng chặn.

Log của job cũng ghi một dòng `Rule sản phẩm: <key>, <n> ảnh.`

## Cái runbook này **không** đụng tới

Số ảnh người dùng chốt vẫn thắng: nút trên dashboard gửi `count` thì rule
không ghi đè. Rule chỉ điền khi không ai chốt — tức là mọi lượt bot tự chạy,
vì `ERP_IDEA_AUTORUN_COUNT` mặc định là 0.

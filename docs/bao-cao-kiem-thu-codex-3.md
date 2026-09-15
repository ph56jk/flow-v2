# Báo cáo kiểm thử Codex 3 — đường SKU và rule ảnh trước ngày chạy thật

Thời điểm: 2026-09-07. Nhánh `agent/prd-agent-improvements-tdd`.
Codex chạy `--sandbox read-only`, chỉ đọc mã và diff; không gọi ERP, không sửa
file nào. Câu hỏi đặt cho nó đúng một câu: **sáng mai chuyện gì hỏng?**

Codex kết luận **CHƯA ĐI ĐƯỢC** và nêu sáu mục. Dưới đây là phần soát lại từng
mục trên mã thật, mục nào sửa và mục nào không.

## Đã sửa

### 1. ERP gật một lượt ghi mà không ghi, rồi bot xoá tên thẻ (Codex: CRITICAL)

Thật. `_erp_graphql` ném lỗi khi có `errors`, nhưng
`{"data": {"updateTaskMeta": false}}` — HTTP 200, không `errors` — thì
`result if isinstance(result, dict) else {}` nuốt mất. `fill_task_skus` coi
như đã ghi, khai số vào sổ, rồi gọi `updateTaskTitle`. Kết quả: tên `Idea 7`
mất hẳn, mã chưa bao giờ lên thẻ, báo cáo vẫn xanh.

Không sửa bằng cách bắt lỗi theo *hình dạng* kết quả: không ai biết resolver
thật trả `true` hay trả object, mà đoán sai thì sáng mai **mọi** lượt ghi đều
báo hỏng. Sửa bằng cách **đọc lại thẻ**: ghi xong đọc lại, thấy `sku:` đúng mã
mới đi tiếp. Đọc lại thì đúng dù ERP trả gì.

Lượt đọc lại có **ba** kết quả, không phải hai (xem lượt soát thứ hai bên
dưới):

- thấy đúng mã → `written`, rồi mới đổi tên;
- đọc được mà không thấy mã → `failed`, không đổi tên, số **không** khai vào
  sổ — lượt sau cấp lại đúng số ấy chứ không bỏ trống một lỗ;
- đọc *không nổi* (429, mạng rớt) → mã tính là đã ghi, nhưng **không** đụng
  vào tên; lý do vào ô `rename_failed`.

Giá: một request mỗi thẻ *có ghi*. Bảng 85 thẻ tốn thêm 85 request.

### 2. `@bot đánh số lại` đổi tên hàng loạt, không hoàn tác được (Codex: CRITICAL)

Thật, và tự tôi cũng thấy trước khi Codex trả lời. Nhưng cách chữa không phải
là chặn lệnh — mà là làm cho nó **lùi lại được**.

Tên cũ giờ được chép vào dòng `ten_cu:` của chính thẻ, trong **cùng** lượt ghi
`sku:`. Không tốn thêm request nào: dòng `sku:` vẫn đang được ghi ở đúng khối
đó. Chép đúng một lần — lượt `renumber` sau thấy thẻ đang mang tên là mã cũ và
không đè lên — nên `ten_cu` luôn là cái tên người ta đặt lúc đầu, kể cả sau
nhiều lượt đánh số lại.

Hai điều làm hẹp thiệt hại lại, đã kiểm trên mã:

- Thẻ gốc không bao giờ nằm trong `plan.changes` (`plan_skus` loại nó ra), nên
  tên thẻ gốc — chỗ khai `product:` — không bị đụng.
- Lượt đánh số lại mà mã mới **trùng** mã cũ thì không đổi tên. Cả cụm chỉ bị
  đổi tên khi dòng `product:` thật sự đổi, tức là có người vừa sửa nó.

Codex đề nghị thêm bước xác nhận/preview riêng cho `renumber`. Chưa làm: đó là
thay đổi luồng người dùng, cần người quyết. Với `ten_cu` thì hậu quả đã là
lùi được, không còn là mất hẳn.

### 3. Thẻ con đã đánh số lại đọc sai rule (Codex: HIGH)

Thật, và đây là lỗi do chính hai tính năng mới đứng cạnh nhau sinh ra — mỗi
cái tự nó đều đúng.

Đánh số xong, thẻ con tên là `OR_18_007`. Thẻ con *có ảnh idea riêng* thì
chính nó là thẻ nguồn, nên `_erp_idea_rule_card` đọc tên nó. `OR_18_007` dài
hơn hai ký tự nên trượt đường mượn tên thẻ cha, mà tự nó không nói ra hàng gì.
Tên file `..._hoop_ornament_...` lại thắng: `wedding_hoop` đứng thứ 9 trong
bảng ưu tiên, `ornament_round` thứ 26. Ra 12 ảnh sai bộ shot thay vì 14.

Sửa: tên hình một **dãy mã SKU** được coi là *không nói gì*, y như tên một chữ
cái, rồi mượn tên thẻ cha. Bài đỏ dựng đúng ca này chạy ra `wedding_hoop`
trước khi sửa.

### 4. Câu chỉ đường bảo người ta làm cái không ăn thua (Codex: MEDIUM)

Thật. Thẻ bị bỏ qua ghi lý do kèm câu *"ghi tên sản phẩm vào tiêu đề hoặc mô
tả thẻ cha là chạy được"*. Nhưng mô tả rơi chung rổ chữ với tên file ảnh, mà
bảng ưu tiên có thể cho tên file thắng — người vận hành làm đúng lời dặn xong
vẫn chạy sai rule và không hiểu vì sao. Runbook đã ghi đúng chuyện này từ
trước; câu trong mã thì chưa. Bỏ vế "hoặc mô tả".

## Chưa sửa — cần người quyết

### 5. Cổng `missing_product_rule` vẫn cho chạy khi chỉ khớp nhóm hàng (Codex: HIGH)

Codex đúng về sự việc: `_flow_operator_has_product_rule_or_category_signal`
cho qua khi có `is_hoop`, `is_apron`… kể cả lúc `product_rule_key` rỗng. Ảnh
nguồn tên `round_hoop.jpeg`, không Gemini, thẻ cha tên trống trơn → chạy 12
ảnh mặc định, không khoá bộ shot nào.

Nhưng đây **không** phải lỗi mới của đợt này: đó là thiết kế đang có, README và
runbook đều ghi rõ `product_rule_key` rỗng nghĩa là chỉ khớp nhóm hàng. Siết
lại thì an toàn hơn về ảnh, đổi lại sáng mai có thể nhiều thẻ đứng im hơn —
đúng cái người dùng sợ nhất. Nên để người vận hành chọn, không tự đổi.

Hiện tại vẫn nhìn ra được: `queued[].product_rule_key` rỗng, và log job ghi
*"Chưa khớp rule sản phẩm nào, chạy N ảnh theo mặc định."*

### 6. `updateTaskTitle` không có bước xác nhận sau khi ghi (Codex: MEDIUM)

Đúng một nửa. Hàng rào dự án đã kiểm lại ngay trong hàm, và không có đường nào
gọi nó với ID ngoài `change.task_id` — Codex cũng xác nhận thế.

Phần còn lại — đọc lại sau khi đổi tên để chắc ERP ghi đúng trường — chưa làm:
lúc ấy tên đã đổi rồi, đọc lại chỉ để báo cáo cho đúng chứ không cứu được gì,
mà tốn thêm một request mỗi thẻ. Bước đọc lại đặt ở chỗ **cứu được**, tức là
trước khi đụng vào tên.

## Lượt soát thứ hai — Codex đọc lại chính bản vá

Vá xong đưa Codex soát lại một lượt nữa, cùng cách chạy. Nó nêu ba điểm; điểm
thứ ba đúng là lỗ mục 3 ở trên, tôi đã bịt trước khi nó trả lời. Hai điểm còn
lại:

### 7. Lượt đọc lại không có retry, và nó đè thêm lên trần request (Codex: HIGH)

Đúng, và đây là mục nặng nhất của lượt hai. Hai vế:

**Vế đọc chậm.** `_erp_task_detail` không cache, nên đọc lại là một vòng mạng
thật. Nếu ERP đã ghi xong mà bản sao chưa kịp theo, lượt đọc trả về khối cũ —
bot kết luận "hỏng" cho một thẻ *đã* mang mã. Cái sai này khó chữa: lượt chạy
sau không xếp thẻ ấy vào danh sách cần ghi nữa (nó có mã rồi), nên tên cũng
không bao giờ được đổi. Bảng đổi tên dở dang, không ai biết vì sao.

Sửa: chưa thấy mã thì **hỏi lại đúng một lần**, sau `ERP_SKU_VERIFY_DELAY_S`
(1,5 giây). Chỉ hỏi lại ở ca "đọc được mà chưa thấy" — ca "đọc không nổi"
thì không, vì ERP đang chặn mà gõ thêm là gõ vào đúng chỗ đau. Giá phải trả
chỉ phát sinh khi đã có gì đó không ổn.

**Vế trần request.** `_erp_graphql` chỉ thử lại `URLError`/`TimeoutError`;
HTTP 429 ném lỗi ngay, không backoff. Mà mã tự ghi trong repo có nêu trần 60
request/phút. Mỗi thẻ giờ tốn 3 request (đọc trước, ghi, đọc lại) thay vì 2.

Chưa thêm throttle, và đây là chỗ **cần biết trước khi chạy bảng lớn**: rải
nhịp nghỉ cho đủ dưới 60/phút thì bảng 85 thẻ mất hơn bốn phút, tức là câu
`@bot đánh số` đứng im hơn bốn phút. Chưa ai gặp 429 thật, nên chưa đổi. Cái
đã làm được là 429 rơi vào lượt đọc lại **không** còn báo hỏng oan nữa: nó
vào nhánh thứ ba, mã giữ, tên giữ nguyên.

### 8. Thẻ không có tên thì đổi tên mà không chép `ten_cu` (Codex: LOW)

Không sửa. Không có tên thì không có gì để giữ; chính Codex cũng viết "không
mất tên có nội dung". Chép một dòng `ten_cu:` rỗng chỉ làm bẩn khối thuộc
tính.

## Lượt soát thứ ba — Codex đọc bản vá của lượt hai

Codex kết luận **chưa nên chạy**, nêu đúng một mục.

### 9. Hai chuyện hỏng cùng lúc thì đốt mất một số (Codex: CRITICAL)

Sự việc thì đúng. ERP gật lượt ghi mà không ghi, **và** lượt đọc lại không
chạy nổi (429, mạng rớt) — nhánh thứ ba khai số vào sổ dù chưa nhìn thấy gì.
Lượt sau thẻ vẫn trống nên nhận số kế tiếp, số cũ nằm không, sổ chỉ giữ mốc
cao nhất nên không ai lấp lại.

Không sửa, và đây là một lựa chọn chứ không phải bỏ sót. Bỏ nhịp khai sổ ở
nhánh ấy thì đổi một cái hỏng lấy một cái hỏng **nặng hơn**: ca thường gặp
hơn nhiều là lượt ghi *đã vào thẻ* mà chỉ có lượt đọc hỏng. Không khai thì sổ
tụt lại một nấc, và một bảng khác cùng đầu mã cấp đúng số ấy cho thẻ khác —
hai thẻ một mã, đi thẳng ra listing. Một số trống thì không thẻ nào sai.
Chọn cái thủng, không chọn cái trùng.

Sổ tự lành theo bảng cho ca ghi-được-nhưng-không-đọc-được: lượt tính sau đọc
mã trên thẻ rồi khai lại (`sku.py:884`, `service.py:12215`). Cái không tự
lành chỉ là số đã đốt trong ca kép.

Bài test Codex đòi đã viết, đúng ca kép, chạy hai lượt và **khẳng định** lượt
sau nhận `BT_1_002`. Nó ghi lại lựa chọn ấy thành một câu kiểm được, để lần
sau ai đổi thì phải đọc lý do trước.

Tên thẻ — thứ duy nhất không lấy lại được — vẫn nguyên trong cả hai lượt.

## Mục 10 — cái Codex không thấy, người dùng thấy

Sau ba lượt soát, câu hỏi từ người vận hành đóng nốt mục nặng nhất về vận hành:
*"nó lấy dựa trên board mà board tên vậy rồi"*.

Đúng. Bảng đã tên `XMAS Ornament Thêu Tròn`, ERP trả `project_name` **ngay
trong payload của từng thẻ** — và `_erp_idea_rule_card` không hề đọc tới, dù
đường SKU bên cạnh thì có đọc. Cả ba lượt Codex đều không nêu chuyện này: nó
soi cái đang có, không hỏi cái đáng có.

Hậu quả của việc bỏ sót: báo cáo trước đó kết luận "phải sửa tên thẻ cha
TASK-2026-00254 trước sáng mai", tức là bắt người ta gõ tay một điều bảng đã
nói rồi — và gõ lại cho **mỗi** bảng mới.

Sửa: tên thẻ đọc từ hẹp tới rộng — tên thẻ nguồn, tên thẻ cha, rồi **tên
bảng**. Chỉ tên nào gọi được tên hàng mới tính, nên `Idea`, `Idea 7`,
`OR_18_007` vẫn nhường lượt như cũ. Payload thẻ không mang `project_name` thì
hỏi `taskBoard` đúng một lần cho cả lượt — và chỉ hỏi khi còn có ích, tên thẻ
cha đã gọi được tên hàng thì không hỏi. Hỏi hỏng thì trả rỗng chứ không ném:
đây là tín hiệu thêm, không phải điều kiện để chạy.

Chạy thử trên payload thật của PROJ-0018, **không sửa tên thẻ nào**:

| | trước sửa | sau sửa |
|---|---|---|
| trước lượt đánh số | 2/10 đúng rule | **10/10 `ornament_round`** |
| sau lượt đánh số | 2/10 đúng rule | **10/10 `ornament_round`** |

Hai bài đỏ dựng đúng hai đường lấy tên bảng (payload thẻ có sẵn, và phải hỏi
`taskBoard`), đã kiểm ngược: gỡ vá ra thì cả hai đỏ, và bài thứ nhất đỏ đúng
bằng `wedding_hoop` — đúng cái sẽ xảy ra sáng mai.

## Mục 11 — cùng một tên bảng, hai đường đọc ra hai sản phẩm

Tìm ra khi đi nạp bảng SKU thật vào máy đang chạy, không phải do Codex.

Bảng sheet ghi `ornament thêu = OR`. Bảng ERP tên `XMAS Ornament Thêu Tròn`.
`ProductBook.lookup` khớp **đủ tên**, mà không ai đặt tên bảng đúng bằng tên
mặt hàng — bảng còn phải mang mùa, mang hình dáng. Nên nó trượt, rơi xuống
`derive_prefix`, và trả về `XOTT`: một mã chưa bảng nào ghi.

Nặng ở chỗ nó *lặng*. Mã vẫn được cấp, thẻ vẫn được ghi, không có lỗi nào để
đọc. Chỉ đến khi tem in ra mới thấy `XOTT_1_001` thay vì `OR_1_001` — mà tem
in rồi thì không gọi về được.

Và nó làm hai đường nói hai chuyện khác nhau về cùng một bảng: đường nhận ảnh
đã biết đọc `ornament` trong tên bảng (mục 10), đường đánh số thì chưa.

**Sửa:** khớp đủ tên trước; trượt thì tìm dòng dài nhất của bảng **nằm trọn**
trong tên, đếm theo *từ*. `sổ` nằm trong `sofa` là trùng chữ chứ không phải
trùng hàng, nên chỉ khớp trọn từ. Hai dòng cùng khớp thì dòng nhiều từ hơn
thắng: `ornament thêu` thắng `thêu`. Nguồn khai ra là `book-contains`, khác
`book`, để đọc báo cáo còn biết mã tới từ lối nào.

Trên bảng SKU thật (62 dòng) chỉ có năm dòng một từ — `bờm`, `bookmark`,
`gương`, `sổ`, `váy` — nên chỗ khớp nhầm rất hẹp. Thẻ không phải sản phẩm vẫn
đoán như cũ: `Chạy auto Content` ra `CAC`, không dính dòng nào.

Bốn bài đỏ: tên bảng bọc lấy dòng, dòng nói rõ hơn thắng, khớp đủ tên vẫn
thắng, và nửa từ không phải một dòng.

## Về chuyện "test xanh giả"

Codex nói bộ `FillLedgerTests` mock cả đường thật: ghi thuộc tính là lambda
rỗng, nên không bài nào chứng minh được mã đã nằm trên thẻ *trước khi* tên bị
xoá. Đúng. ERP giả trong bộ ấy giờ **có trí nhớ**: khối thuộc tính được giữ
lại giữa các lượt gọi, lượt ghi đọc lại đúng cái nó vừa viết. Có trí nhớ mới
dựng được ca "ERP gật cho xong mà không ghi" — và ca ấy chính là bài đỏ của
mục 1.

Codex không tìm thấy bài nào bị xoá, `skip` hay hạ số để ép xanh trong ba
commit của đợt trước. Đợt này cũng không: sáu bài đỏ, sửa mã cho xanh, cộng một bài ghi lại lựa
chọn của mục 9.

Hai bài của lượt hai được kiểm ngược lại cho chắc: gỡ đúng dòng vá ra thì bài
đỏ, lắp lại thì xanh. Bài xanh mà gỡ vá vẫn xanh là bài không chứng minh gì.

Cả năm bộ chạy lại sau bản vá: 1342 / 88 / 198 / 35 / 33, không bộ nào đỏ.

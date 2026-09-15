# Bảng điều khiển HaviGroup

Một trang web gộp ba việc: **Đăng Etsy**, **Tạo ảnh**, **SKU & Thuộc tính**.
Bảng chỉ đọc và hiện số. Nó không gọi ERP, không bấm hộ bot việc gì.

Tài liệu có hai phần:

- **Phần 1 — cho seller.** Thấy gì → nghĩa là gì → làm gì. Không cần biết code.
- **Phần 2 — cho người vận hành.** Bảng chạy ở đâu, đọc số từ đâu, khởi động
  lại thế nào. Mỗi mục ghi `tệp:dòng`, trích trên commit `52a9383`, soát lại
  cả 202 trích dẫn trên nhánh `agent/bot-erp-len-bang`.

Chỗ nào ghi **chưa kiểm** là chỗ repo không có đủ để khẳng định. Đừng coi đó
là sự thật; hỏi người đang giữ máy.

---

# Phần 1 — cho seller

## 1.1. Vào bảng

- Địa chỉ bảng và mật khẩu: **hỏi người vận hành.** Tài liệu này không ghi.
- Trang đăng nhập chỉ có một ô "Mật khẩu" và nút "Vào bảng". Không có tên
  đăng nhập.
- Gõ sai: trang báo "Sai mật khẩu."
- Gõ sai nhiều lần liền: trang báo "Sai quá nhiều lần. Thử lại sau N phút."
  Chờ đúng số phút ấy rồi thử lại. Trong lúc bị khoá, gõ thêm không làm khoá
  lâu hơn, nhưng cũng không vào được.
- Vào được một lần thì trình duyệt nhớ **30 ngày**.
- Tự nhiên bị đẩy về trang đăng nhập: phiên đã hết, hoặc người vận hành vừa
  đổi mật khẩu. Hỏi lại mật khẩu mới.

## 1.2. Bảng có gì

- Trên đầu: tên bảng, nút **Làm mới**, và một dòng trạng thái kết nối.
- Ba nút chuyển phần: **Đăng Etsy**, **Tạo ảnh**, **SKU & Thuộc tính**.
- Mỗi phần có:
  - một hàng ô số. Bấm vào ô nào thì bảng lọc đúng những thẻ ấy;
  - khối **"Cần xử lý"** — đọc khối này trước tiên;
  - ô tìm kiếm và các nút lọc;
  - các tab bên dưới.

Dòng trạng thái trên đầu:

| Thấy | Nghĩa | Làm gì |
|---|---|---|
| "Trực tiếp · giờ" | Bảng tự nhận số mới, không cần tải lại trang. Tạo ảnh: job đổi thì khoảng 2 giây sau bảng thấy. Đăng Etsy: khoảng 5 giây. Không có gì mới thì 15 giây gửi lại một lần | Không cần làm gì |
| "Cập nhật giờ · hỏi lại 10 giây một lần" | Mất luồng trực tiếp, bảng tự hỏi lại mỗi 10 giây | Không cần làm gì. Số vẫn đúng, chỉ chậm hơn |
| "Mất kết nối tới máy chủ bảng" | Không gọi được máy chủ bảng | Tải lại trang. Vẫn thế thì báo người vận hành |

Nút **Làm mới** chỉ đọc lại số ngay. Nó **không** bắt bot quét, không bắt máy
làm gì. Bấm nhiều không nhanh hơn.

Chuyển sang tab khác của trình duyệt thì bảng tạm ngừng. Quay lại là nó tự nối.

## 1.3. SKU & Thuộc tính

Bot đọc thẻ trên ERP sau mỗi lượt quét, ghi ra một tệp, bảng đọc tệp ấy.
Nên số SKU trên bảng **chỉ mới bằng lượt quét gần nhất** của bot.

### Tab "Thẻ con"

Các cột: **Thẻ**, **Cột**, **SKU / vì sao chưa có**, **Account**, **Copysku**.

- Thẻ đã có mã: cột SKU hiện mã.
  - Có nhãn **"dòng bảng"**: bot đọc mã ấy từ bảng ERP chứ không từ cây thẻ.
    Mã vẫn đúng.
- Thẻ chưa có mã: cột SKU ghi **lý do**. Bảng dưới đây.
- Dòng có vạch đỏ bên trái: thẻ đã ở **Đang làm hoặc cột sau** mà chưa có
  SKU. Đây là thẻ cần để ý nhất.

| Thấy trong cột SKU | Nghĩa | Làm gì |
|---|---|---|
| "chưa sang Đang làm (đang ở …)" | Thẻ chưa tới lúc. Bot chỉ đánh mã khi thẻ sang Đang làm | Kéo thẻ sang Đang làm khi xong ảnh |
| "còn N ảnh chờ duyệt" | Còn ảnh chưa duyệt | Duyệt nốt ảnh |
| "chưa khai sản phẩm, chưa tra được bảng SKU" | Thẻ con và thẻ gốc đều chưa khai sản phẩm (product_type) | Khai sản phẩm ở **thẻ gốc** (hoặc thẻ con) |
| "bảng SKU chưa có dòng cho “…”" | Sản phẩm đã khai nhưng bảng mã SKU chưa có dòng cho nó. Bot không đoán đầu mã | Báo người vận hành thêm dòng vào bảng mã |
| "đã tới lúc, chờ bot đánh mã" | Mọi thứ đủ. Bot sẽ đánh ở nhịp tới | Chờ. Xem mục 1.4 |
| "chưa đọc được (cây bị cắt)" | ERP chỉ trả về một phần cây của cụm lớn. Thẻ này nằm ngoài phần ấy, bot chưa thấy nó | Không phải lỗi của seller. Chờ vài lượt. Kéo dài thì báo người vận hành |

Thẻ đã huỷ thì không ghi lý do nào. Đó là chỗ duy nhất thẻ không mã mà không
có lý do.

Không thấy cụm của mình trên bảng: có thể bot **chưa được thêm vào dự án** ấy
trên ERP. Bot chỉ quét những dự án nó được thêm vào, dự án khác không có mặt
trên bảng. Báo người vận hành.

### Cột Account và Copysku

| Thấy | Nghĩa | Làm gì |
|---|---|---|
| Có giá trị | Thẻ con đã khai | Không cần làm gì |
| Giá trị kèm nhãn **"thẻ cha"** | Thẻ con chưa khai, bot sẽ chép từ thẻ cha ở lượt sau | Không cần làm gì |
| Nhãn vàng **"thiếu"** | Thẻ con và thẻ cha đều chưa khai | Khai account/copysku ở thẻ cha |

### Tab "Cụm"

Một dòng là một cụm (thẻ gốc cùng các thẻ con).

- **"đủ N thẻ con"** (xanh): bot đọc được cả cụm.
- **"bot đọc x/y thẻ"** hoặc **"cây bị cắt"** (đỏ): ERP chỉ trả về một phần.
  Thẻ ngoài phần ấy sẽ hiện "chưa đọc được (cây bị cắt)" hoặc "dòng bảng".
- **"thiếu"** cạnh một thuộc tính: cụm chưa khai thuộc tính ấy. Bốn thuộc
  tính bảng kiểm là product_type, product_group, fulfillment, sales_channel.
  Khai ở thẻ gốc.

### Tab "Sổ bot"

Mọi thứ bot đang nắm bên ERP. Bot ghi kèm vào `sku_status.json` mỗi lượt quét,
nên tab này **không tốn thêm lượt ERP nào**.

Ba ô trên cùng:

| Ô | Đọc thế nào |
|---|---|
| **Phạm vi bot** | Tài khoản bot, số bảng đang theo, bảng nào trong làn nhanh. Bảng ngoài làn nhanh vẫn được quét, chỉ không có lượt điền SKU riêng |
| **Nhịp ERP một phút** | Số lượt bot thật sự gọi ERP trong 60 giây vừa qua, kèm **hai trần tách biệt** |
| **Bot đã làm gì** | Lượt tạo ảnh gần nhất, số thẻ đã cho chạy, đã đăng Etsy, bình luận đã trả lời (giữ 45 ngày), lượt hỏi não (trong một ngày) |

**Hai trần ERP không biết nhau.** "Trần bot + làn nhanh" là hạn của bot và của
việc điền SKU. "Trần service" là hạn của mọi lượt service gọi ERP, gồm cả
**tách thẻ con**. Nâng trần bot **không** làm tách thẻ con nhanh lên. Ô đổi
vàng khi nhịp chạm 70% trần bot, đỏ khi chạm 90% hoặc hết biên dư.

Năm sổ bên dưới:

| Sổ | Nghĩa | Làm gì |
|---|---|---|
| **Thẻ người bảo bot dừng** | Ai đó viết "@bot dừng lại" trong thẻ. Sổ này **không tự hết hạn** — thẻ nằm đây im tới khi có người gỡ. Dừng lâu nhất xếp trên | Xem thẻ, gỡ nếu đã xong việc |
| **Thẻ bot đã nhắc đặt sai cột** | Bot đã nhắc một lần rằng thẻ nằm sai cột. Cũng **không tự hết hạn** | Kéo thẻ về đúng cột |
| **Sổ cấp số SKU** | Số kế tiếp bot sẽ phát cho mỗi tiền tố | ERP không chặn SKU trùng, chống trùng chỉ nằm ở đây. Thấy số lùi là dấu hiệu hỏng sổ |
| **Bảng mã sheet** | Mặt hàng → mã, đọc từ sheet bảng mã | Xem mục dưới |
| **Danh mục sản phẩm ERP** | Danh mục nào có tiền tố SKU khai thẳng bên ERP | Danh mục chưa khai tiền tố thì bot **không đoán hộ** — phải khai bên ERP |

**Một mặt hàng có thể mang nhiều mã.** Bảng thật ghi `khung theu = KT,OR,HK`.
Bot đánh số **lấy mã đầu**; hai mã còn lại hiện ở cột "Mã khác bảng ghi" màu
vàng. Đây là chỗ dễ in sai mã lên thùng hàng nhất — thấy mặt hàng nào bot lấy
mã không như ý thì sửa **thứ tự mã trong sheet**, đừng sửa từng thẻ.

Ô tìm kiếm lọc được cả năm sổ này.

Tab trống mà phần SKU vẫn có số: bản bot trên hvg-pc còn cũ, chưa ghi khoá
`brain`. Lượt quét sau khi cập nhật là có.

### Khối "Cần xử lý" của phần SKU

| Thấy | Nghĩa | Làm gì |
|---|---|---|
| "Bot chưa ghi số SKU: chưa có tệp sku_status.json…" | Bot chưa ghi tệp lần nào | Báo người vận hành |
| "Không đọc được sku_status.json: …" | Bảng không đọc được tệp của bot | Báo người vận hành |
| "Bot chưa ghi mới: lượt cuối cách đây …" | Bot lâu rồi không ghi. Số trên bảng là số của lượt cũ | Báo người vận hành. Đừng tin số đang hiện |
| "N thẻ ở Đang làm chưa có SKU." | Đã tới lúc cấp mã mà chưa có | Xem lý do từng thẻ ở tab Thẻ con |
| "Cụm …: bot chỉ đọc được x/y thẻ…" | ERP cắt cây của cụm này | Không phải lỗi của seller. Xem mục cây bị cắt ở trên |
| "N cụm thiếu thuộc tính: …" | Cụm chưa khai đủ bốn thuộc tính | Khai ở thẻ gốc |
| "N thẻ thiếu account" / "N thẻ thiếu copysku" | Thẻ con và thẻ cha đều chưa khai | Khai ở thẻ cha |
| "Bot đã dùng x/y lượt trần ERP trong một phút…" | Bot chạm 70% trần (vàng) hoặc 90%/hết biên dư (đỏ) | Xem ô "Nhịp ERP" ở tab Sổ bot. Trần này **không** chạm việc tách thẻ con |

## 1.4. Kéo thẻ sang Đang làm thì bao lâu có SKU

Có hai đường đánh mã. Máy chạy thật đang bật cả hai (kiểm ngày 12/09).

**Làn nhanh** (đường chính cho cụm nhỏ):

- Bảng có thẻ gắn bot chưa có mã ở **Cần làm** hoặc **Đang làm** được đọc lại
  khoảng **15 giây** một lần. Bảng khác thì **5 phút** một lần.
- Cụm nhỏ: thường có mã sau vài chục giây tới vài phút.
- Làn nhanh nhường cho lượt quét chính khi cụm quá lớn:
  - cụm từ **4 thẻ con chờ mã** trở lên;
  - cụm có cây bị ERP cắt: từ **3 thẻ con chờ mã** trở lên.
  - Cụm 1–2 thẻ có cây bị cắt vẫn đi làn nhanh.
  - Thẻ **đã có mã** trong cụm bị cắt không còn bị tính là thẻ chờ mã (sửa
    12/09). Trước đó một cụm chỉ có một hai thẻ mới cũng bị đẩy sang lượt quét
    chính.
- ERP đôi khi trả lỗi thoáng qua khi làn đọc bảng. Từ 12/09 làn **đọc lại
  bảng ấy ngay nhịp sau** (15 giây) thay vì bỏ bảng 5 phút. Người dùng không
  thấy gì, chỉ thấy mã tới đúng giờ hơn.

**Lượt quét chính:**

- Mặc định bot nghỉ **2 phút** giữa hai lượt, cộng thời gian quét.
- Mỗi lượt đánh mã cho **mọi cụm** đã tới lúc. Trần "3 thẻ mỗi lượt" chỉ giới
  hạn việc bắt đầu tạo ảnh, không chặn việc đánh SKU.

**Bảng hiện mã chậm hơn ERP.**

- Làn nhanh ghi SKU lên **thẻ ERP trước**.
- Bảng chỉ hiện mã ấy sau **lượt quét chính kế tiếp**.
- Thấy mã trên ERP mà bảng chưa có: chờ lượt quét kế tiếp. Không cần báo.

**ERP đang chặn** (quá nhiều yêu cầu): bot dừng lượt đánh mã, để phần còn lại
cho lượt sau. Mã tới chậm hơn một lượt. Đó không phải lỗi.

Thời gian thật trên máy chạy thật: **chưa đo được** sau lần cập nhật 12/09
chiều — từ 15:00 tới 17:10 không có thẻ mới nào kéo sang Đang làm, nên làn
nhanh không có việc để bấm giờ. Muốn có số thật thì kéo một thẻ sang Đang làm
rồi xem log (mục 2.5). Số đo được trước đợt dot7: một lượt quét cách nhau
3,5–10 phút, mỗi thẻ chừng 50 giây.

**Số SKU có thể nhảy cóc.** Ví dụ có 037 rồi 039, không có 038. Đó **không
phải lỗi**:

- Sổ mã chỉ nhớ số lớn nhất đã phát. Số đã phát không bao giờ cấp lại.
- Đánh số lại một cụm thì mã cũ bỏ hẳn.

Đừng sửa tay cho liền số. Sửa tay dễ làm hai thẻ trùng mã.

## 1.5. Nút "chạy ngay"

- Bảng điều khiển **không có** nút chạy bot. Chỉ có **Làm mới** (đọc lại số).
- App chính có một địa chỉ để người vận hành bắt bot quét một lượt
  (`POST /api/agent-bot/run`). Không nút nào trên giao diện gọi tới địa chỉ ấy.
- Nếu địa chỉ ấy trả **"bot đang quét một lượt khác; lượt này bỏ qua"**:
  - Đó là **bình thường**. Bot đang quét rồi.
  - Không cần gọi lại liên tục. Lượt đang chạy làm xong là số lên bảng.

## 1.6. Đăng Etsy

Luồng: thẻ ERP ở **Đang review** → Review Lister → máy Etsy → bản nháp.
Tab: **Thẻ**, **Việc đăng**, **Máy Etsy**.

Màu dùng chung cả bảng: xanh lá = xong, xanh dương = đang chạy,
vàng = chờ / cần để ý, đỏ = hỏng, xám = tắt / chưa tới.

| Nhãn | Nghĩa | Làm gì |
|---|---|---|
| "chưa soi" | Lister chưa xem tới thẻ này | Chờ lượt sau |
| "chờ khai" | Thẻ thiếu account/copysku | Khai trên thẻ ERP. Đây là bước tay |
| "đã giao, chờ máy" / "chờ máy" | Đã giao cho máy Etsy, máy chưa nhận | Chờ. Quá 10 phút thì bảng tự nhắc |
| "đang đăng" | Máy Etsy đang làm | Chờ |
| "đã lưu nháp" | Xong, có bản nháp trên Etsy | Soát bản nháp (nút "Soát") |
| "chưa sang Hoàn thành" | Nháp đã lưu nhưng lister không chuyển được thẻ | Kéo thẻ sang Hoàn thành bằng tay, hoặc báo người vận hành |
| "xong, không lưu nháp" | Máy báo xong mà không lưu được nháp | Báo người vận hành |
| "hỏng" / "bị chặn" / "lỗi khi soi thẻ" | Có lỗi | Đọc dòng ghi chú, báo người vận hành |
| "đã dừng" | Việc bị dừng | Hỏi người vận hành |

Cột **Soát bản nháp**:

- Bấm **Soát**: máy Etsy mở bản nháp và đếm ảnh. Mất 1–3 phút, kết quả tự hiện.
- "✓ x/y ảnh": đủ ảnh.
- "LỆCH x/y ảnh": thiếu hoặc thừa ảnh. Mở nháp kiểm lại.
- "còn video", "sửa dở": mở nháp xem.

Tab **Máy Etsy**: "rảnh", "đang đăng …", "mất liên lạc" (máy không báo về quá
3 phút — báo người vận hành).

## 1.7. Tạo ảnh

Luồng: thẻ **Idea** trên ERP → flow-v2 → Google Flow → ảnh lên thẻ.
Tab: **Job**, **Flow và sức khoẻ**.

| Nhãn | Nghĩa | Làm gì |
|---|---|---|
| "chờ chạy" | Job đang xếp hàng | Chờ |
| "đang tạo" / "đang chạy" | Đang làm. Dòng phụ ghi bước hiện tại | Chờ |
| "xong" | Xong. Cột Ảnh ghi số ảnh làm ra/số yêu cầu | Tô vàng là thiếu ảnh — xem thẻ |
| "hết quota" | Tài khoản Google Flow hết lượt | Chờ tới giờ "Mở lại" ở tab Flow và sức khoẻ |
| "bị ngắt" | Job bị cắt ngang giữa chừng | Báo người vận hành nếu lặp lại |
| "hỏng" / "lỗi" | Có lỗi | Báo người vận hành |
| "đã huỷ" | Đã huỷ | Không cần làm gì |

Bảng tự nhắc khi một job đang chạy mà **20 phút** không có tín hiệu: có thể
kẹt. Báo người vận hành.

## 1.8. Khi nào báo người vận hành

- Dải đỏ ở bất kỳ phần nào.
- "Mất kết nối tới máy chủ bảng" sau khi đã tải lại trang.
- Máy Etsy "mất liên lạc".
- "Bot chưa ghi mới" ở phần SKU.
- Một thẻ nằm mãi ở "đã tới lúc, chờ bot đánh mã", mà trên ERP cũng chưa có
  mã. Mốc 15 phút là lời khuyên, code không có mốc này.

---

# Phần 2 — cho người vận hành

Mọi `tệp:dòng` trích trên commit `52a9383`, trừ hai script bảng (ghi rõ nhánh
ở mục 2.1 và 2.10). Mục nào ghi "c8 kiểm trên hvg-pc 12/09" là đọc trên máy thật, chỉ
đọc, không chép giá trị.

## 2.1. Bảng chạy ở đâu

- Bảng là **tiến trình riêng**, không nằm trong app 8000:
  `python -m flow_web.board`. Mặc định nghe `127.0.0.1:8765`.
  — `flow_web/board.py:3`, `:535`, `:566`
- Trên hvg-pc: Scheduled Task chạy `scripts/run-board.ps1`, đứng sau
  Cloudflare Tunnel. Tên miền ghi ở docstring. — `flow_web/board.py:5-6`
- **Task "HaviGroup Board"** chạy `scripts/run-board.ps1`, log nối vào
  `C:\HaviGroup\logs\board.log`.
  - Script chạy `python -m flow_web.board --no-open --port 8765` kèm các cờ
    `--listing-base` (:8001), `--flow-base` (:8000), `--flow-state-file`,
    `--password-file`, `--host-name`.
  - Thiếu `.venv` hoặc thiếu tệp mã băm mật khẩu thì thoát mã 78, bảng không
    lên.
  - Task có trigger khi khởi động, khi đăng nhập, và lặp mỗi 5 phút: tiến trình
    chết thì trong 5 phút tự dựng lại.
  - Stop task **không** giết bảng đang chạy. Bật lại bảng: năm bước ở mục 2.6.
- **Tunnel** tên `havi-board`, chạy bằng task "HaviGroup Board Tunnel"
  (`cloudflared tunnel --config … run`). Máy không có service cloudflared:
  tunnel chỉ sống nhờ task.
- Nơi đặt script:
  - `scripts/run-board.ps1` và `scripts/install_board_task.ps1` chỉ có trên
    nhánh `agent/prd-agent-improvements-tdd` (9e10aa0, 9c30075), không có ở
    main, dot7, dot8.
  - Bản trên hvg-pc trùng blob với nhánh ấy.
- Nguồn:
  - `scripts/run-board.ps1:21-28`, `:37-42` (nhánh trên);
  - `scripts/install_board_task.ps1:58-62`, `:74-89` (nhánh trên);
  - c8 kiểm trên hvg-pc 12/09.
- Tham số: `--listing-base/--base`, `--flow-base`, `--flow-state-file`,
  `--port`, `--password-file`, `--host-name`, `--no-open`, `--hash-password`.
  — `flow_web/board.py:530-541`
- Có `--host-name` mà thiếu `--password-file` thì bảng từ chối chạy.
  — `flow_web/board.py:559-561`
- Lệnh cũ `python -m flow_web.listing_board` giờ mở bảng gộp.
  — `flow_web/listing_board.py:454`

Ba tiến trình bảng dựa vào:

| Tiến trình | Cổng | Bảng dùng cho | Nguồn |
|---|---|---|---|
| flow-v2 (`flow_web.main:app`) | 8000 | phần Tạo ảnh; chạy agent bot và làn nhanh | `automation_center/runner/run-flow-v2.ps1:18`, `flow_web/main.py:118`, `flow_web/static/board.html:480` |
| Bản Listing | 8001 | phần Đăng Etsy và tệp `sku_status.json` | `flow_web/static/board.html:384`, `flow_web/sku_board.py:630` |
| Bảng | 8765 | trang web | `flow_web/board.py:535` |

## 2.2. Đăng nhập bảng

- Không có biến môi trường cho mật khẩu. Bảng đọc **tệp mã băm**
  (`pbkdf2_sha256`) qua `--password-file`. Tạo tệp bằng `--hash-password`.
  — `flow_web/board.py:80-83`, `:536`, `:541`
- Phiên sống 30 ngày. Đổi mật khẩu thì mọi phiên cũ mất hiệu lực.
  — `flow_web/board.py:98`, `:101`
- Khoá khi sai 8 lần trên một máy, hoặc 40 lần tổng, trong 15 phút.
  — `flow_web/board.py:103-105`, chữ báo ở `:478`, `:480`

## 2.3. Bảng đọc số từ đâu, nhịp nào

Route, tất cả trong `flow_web/board.py`: `GET /api/etsy` `:409`,
`GET /api/images` `:411`, `GET /api/sku` `:413`, `GET /api/stream` (SSE) `:415`,
`GET /api/me` `:417`, `POST /api/check` `:434`, `/login` `:399`, `/logout` `:430`.

| Phần | Đọc gì | Coi là cũ khi | Nguồn |
|---|---|---|---|
| Đăng Etsy | `copy_tasks()` và `review_lister_status.json` qua bản Listing | quá `2 × chu kỳ + 120` giây, chu kỳ mặc định 300 | `flow_web/listing_board.py:339-360`, `flow_web/listing_watch.py:76-85` |
| Tạo ảnh | `GET /api/state` của flow-v2, giữ đệm 15 giây; hoặc tệp qua `--flow-state-file` | — | `flow_web/image_board.py:39-42`, `:186-188` |
| SKU | `sku_status.json` qua bản Listing. **Không** gọi ERP, không đọc thẳng DATA_DIR | quá `2 × chu kỳ + 120` giây, chu kỳ mặc định 120 | `flow_web/sku_board.py:43-45`, `:630`, `:641` |

Nhịp của máy chủ bảng — `flow_web/board.py:53-58`:

| Hằng | Giá trị | Ý nghĩa |
|---|---|---|
| `TICK` | 1 giây | nhịp dựng lại; phần ảnh dựng mỗi nhịp (`:301`) |
| `ETSY_EVERY` | 5 giây | phần Đăng Etsy |
| `SKU_EVERY` | 5 giây | phần SKU |
| `PUSH_ANYWAY`, `HEARTBEAT` | 15 giây | gửi lại dù không đổi |
| `MAX_STREAMS` | 20 | quá số người xem này thì trang tự hỏi 10 giây một lần (`:441`) |

- Luồng SSE hỏng thì trang hỏi lại mỗi 10 giây. — `flow_web/static/board.html:851`
- Không còn ai xem thì bảng bỏ đệm. — `flow_web/board.py:217`

**Tệp `sku_status.json`:**

- Bot ghi **cuối mỗi lượt quét chính**. — `flow_web/agent_bot.py:3285`,
  `flow_web/sku_board.py:491-515`
- Ghi ra tệp tạm rồi `os.replace`, bảng không bao giờ đọc nửa tệp.
  — `flow_web/sku_board.py:506-511`
- Đường dẫn: `ERP_SKU_STATUS_FILE`; không đặt thì
  `ERP_LISTING_FILES_DIR/sku_status.json`. — `flow_web/sku_board.py:453-460`
- **Làn nhanh không ghi tệp này.** Làn nhanh đánh mã xong thì bảng vẫn hiện
  "chờ bot đánh mã" tới lượt quét chính kế tiếp.
- Bảng trả 404 cho tệp: bảng hiện "Bot chưa ghi số SKU…".
  — `flow_web/sku_board.py:569-572`
- Khoá `brain` trong tệp là **sổ bot** (tab "Sổ bot"). Bot gom ngay lúc ghi
  bằng `sku_board.brain_from_disk`: đọc `sku_ledger.json`,
  `product_categories.json`, `sku_book.json` và sổ nhịp
  `erp-agent-nhip.json` trong `DATA_DIR`, cộng hai trần trong môi trường.
  Gom hỏng thì **bỏ khối `brain`**, không bỏ lượt ghi số SKU.
  — `flow_web/sku_board.py:471-498`, `flow_web/agent_bot.py:2745-2751`
- Bot cũ chưa ghi khoá này thì bảng trả khối rỗng và vẫn mở bình thường.
  — `flow_web/sku_board.py:597-628`

## 2.4. Nhịp và trần của bot, làn nhanh

**Lượt quét chính** — `flow_web/agent_bot.py`:

| Thứ | Mặc định | Biến | Nguồn |
|---|---|---|---|
| Nghỉ giữa hai lượt | 120 giây; 0 là tắt bot | `ERP_AGENT_POLL_SECONDS` | `:115`, `:302`, `:3376-3378` |
| Trần số thẻ Idea được **khởi động tạo ảnh** mỗi lượt. Không chặn việc đánh SKU: `pipeline_pass` chạy cho mọi cụm trước khi xét trần | 3 | `ERP_AGENT_MAX_CARDS_PER_SCAN` | `:136`, `:313`, `:3221`, `:3244`, `:3265-3268` |
| Trần request của token bot | 50/phút, nhận 1–60 | `ERP_AGENT_RATE_PER_MINUTE` | `:110`, `:3415-3437` |
| Sổ nhịp dùng chung giữa tiến trình | `DATA_DIR/erp-agent-nhip.json` | `ERP_AGENT_RATE_FILE` | `:3413-3414`, `flow_web/erp_token_nhip.py:34-47` |

Trần riêng của app (token service, không phải token bot): 40/phút, đệm 10.
Biến `ERP_GRAPHQL_PER_MINUTE`, đọc lại mỗi lần gọi, số âm kẹp về 0.
- Đặt **0** là **tắt hẳn** bộ điều tiết của token service: `acquire` trả ngay.
  **Đừng đặt 0.**
- Bot và làn nhanh có trần riêng, không bị biến này ảnh hưởng.
- Trên hvg-pc biến này không đặt, nên chạy mặc định 40/phút (c8 kiểm 12/09).
— `flow_web/service.py:13244`, `:13252-13259`, `:13270-13271`; chỗ gọi duy
nhất `:13357`

**Khoá lượt quét:** mỗi bot chỉ một lượt quét tại một lúc. Lượt tới sau (vd
gọi `/api/agent-bot/run` giữa lúc bot nền đang quét) trả ngay
`{"enabled": true, "busy": true, "reason": "bot đang quét một lượt khác; lượt này bỏ qua"}`
và không quét. Lượt nền gặp khoá thì bỏ lượt ấy, nhịp không đổi.
— `flow_web/agent_bot.py:1644`, `:3147-3161`; route ở `flow_web/main.py:274`

**Làn nhanh SKU** — `flow_web/sku.py:1389-1422`. Trong code mặc định **tắt**
(`flow_web/sku.py:1396`, `:1412-1413`; dựng làn ở `flow_web/service.py:22789`).
Chạy khô (`ERP_AGENT_DRY_RUN`) thì không dựng làn (`flow_web/agent_bot.py:3502-3504`).

Trên hvg-pc làn nhanh **bật**. Đó là cấu hình của máy thật tại một thời điểm,
không phải mặc định của code. Bằng chứng: log app 8000 lúc 12:54:22 ngày 12/09,
sau đợt dot7 (`083eda9`), có dòng
"Làn nhanh SKU bật: nhịp 15.0s, trần 20 request/phút, 4 worker." (c8 kiểm trên
hvg-pc 12/09). Muốn biết hiện tại, tìm lại dòng ấy trong log (mục 2.5).

| Trường | Biến | Mặc định | Kẹp | Dòng |
|---|---|---|---|---|
| bật | `ERP_SKU_FAST_LANE` | tắt; nhận 1/true/yes/on | — | `:1412-1414` |
| nhịp tick | `ERP_SKU_FAST_LANE_SECONDS` | 15 | 10–120 | `:1415` |
| trần request/phút | `ERP_SKU_FAST_LANE_BUDGET` | 20 | **11**–50 | `:1417` |
| nghỉ khi gặp 429 | `ERP_SKU_FAST_LANE_REST` | 60 | 60–900 | `:1419` |
| đọc lại bảng nguội | `ERP_SKU_FAST_LANE_REDISCOVER` | 300 | 60–3600 | `:1420` |
| số luồng đọc bảng | `ERP_SKU_FAST_LANE_WORKERS` | 4 | 1–8 | `:1421` |

Kẹp dưới của trần là `_LANE_MIN_BUDGET`, tính ra chứ không viết thẳng:
`1 + fill_cost(1) + 2`. Trước 12/09 là 10; sau khi `fill_cost` cộng thêm lượt
đọc bảng thì thành **11** (`flow_web/sku.py:1329-1331`).

- Bảng "nóng" (có thẻ gắn bot chưa mã ở Cần làm/Đang làm) đọc lại mỗi nhịp
  tick; bảng khác mỗi `rediscover_s`. — `flow_web/sku.py:1483-1499`, `:1709-1712`
- Chi phí một cụm: `fill_cost(cards, cut_new, wrong)`.
  — `flow_web/sku.py:1307-1324`
  - Nền **3**: hai lượt đọc cây, một lượt đọc bảng. Mỗi thẻ chờ mã **5**.
  - `cut_new` — thẻ chờ mã nằm **ngoài** cây vì ERP cắt: mỗi thẻ **+1**.
  - `wrong` — thẻ **đã có mã** mà tên khác mã: mỗi thẻ **+2**.
  - Thẻ bị cắt mà tên đã đúng bằng mã thì **không tốn gì** (sửa 12/09,
    `tasks/the-cat-da-co-ma.md`): trước đó nó bị tính như thẻ chờ mã, làm cụm
    một hai thẻ cũng bị đẩy qua trần.
  - Lượt dài quá 40 request thì bảng nhớ hết hạn, phải đọc lại: cộng **2** cho
    mỗi 40.
- Cụm cần `1 + cây + fill_cost(...)` vượt trần thì làn nhường cho lượt quét
  chính, ghi log một lần. — `flow_web/sku.py:1789-1816`
  - Cây không bị cắt (`trees = 1`, `flow_web/sku.py:1743`): cụm từ **4 thẻ**
    trở lên bị nhường, vì `1 + 1 + fill_cost(4) = 25 > 20`, còn
    `1 + 1 + fill_cost(3) = 20` vừa khít.
  - Cây gốc bị cắt, còn thẻ ngoài phần nhận được: làn đọc cây riêng của từng
    thẻ ấy, mỗi nhịp một thẻ, và tính `trees = 2`, `cut_new` = số thẻ ngoài
    cây. Cụm từ **3 thẻ** trở lên bị nhường: `1 + 2 + fill_cost(3, 3) = 24 > 20`.
    Cụm 1–2 thẻ vẫn đi làn nhanh (`1 + 2 + fill_cost(2, 2) = 18`).
    — `flow_web/sku.py:1842-1868`
  - Hai số 4 và 3 là tính ra, code không ghi thẳng.
- ERP trả 500 `QueryDeadlockError` lúc đọc bảng: làn đọc lại bảng ấy ở **nhịp
  kế** (15 giây), đúng **một** lần. Lần đọc lại cũng lỗi thì dời 300 giây như
  lỗi thường. Đọc được thì lần deadlock sau lại có một lượt đọc lại.
  — `flow_web/sku.py:1506-1509`, `:1686-1706`; PRD `tasks/lan-nhanh-deadlock.md`
- ERP chặn giữa lượt đánh số: lượt ghi chữ "HTTP 429" vào `failed`, làn nhanh
  thấy chữ ấy thì nghỉ. — `flow_web/sku.py:1901-1907`, `:1925-1935`
- Làn không xếp hàng khi lượt quét chính đang đánh số: nhịp sau thử lại.
  — `flow_web/sku.py:1293`, `_fill_cluster` (`sku_pass(wait=False)`)
- Làn không gọi `run_once`, nên khoá lượt quét không chặn nó.

**Số nhảy cóc:** sổ chỉ giữ mốc cao nhất, không giữ chỗ trống
(`flow_web/sku.py:650-661`). Đánh số lại thì mã cũ bỏ hẳn
(`flow_web/sku.py:1095-1098`).

## 2.5. Log nào chứng tỏ còn sống

Log của app 8000 (bot, làn nhanh):

| Chữ | Nghĩa | Nguồn |
|---|---|---|
| "Agent bot bật: quét mỗi Ns, phạm vi …, tự chạy …." | Bot đã lên. Một dòng mỗi lần khởi động | `flow_web/agent_bot.py:3384` |
| "Agent bot tắt: chưa đặt ERP_AGENT_TOKEN." | Bot tắt vì thiếu token | `flow_web/agent_bot.py:3467` (và `:3374`) |
| "Agent bot tắt: ERP_AGENT_POLL_SECONDS = 0 …" | Bot tắt vì nhịp 0 | `flow_web/agent_bot.py:3377` |
| "Nhịp token bot chung: …, N/phút" | Trần request đang dùng | `flow_web/agent_bot.py:3438` |
| "Agent bot bỏ lượt này: đang quét một lượt khác." | Có lượt khác đang giữ khoá. Bình thường | `flow_web/agent_bot.py:3156` |
| "Agent bot bỏ lượt này: …" (warning) | Lượt hỏng vì lỗi ERP | `flow_web/agent_bot.py:3406` |
| "Agent bot gặp lỗi ngoài dự tính: …" | Lỗi lạ, có traceback | `flow_web/agent_bot.py:3408` |
| "Agent bot được cấu hình cho … nhưng ERP không cho nó thấy dự án đó …" | Dự án trong `ERP_AGENT_PROJECTS` mà bot chưa được thêm vào Project User | `flow_web/agent_bot.py:1665-1668` |
| "taskFull cắt bớt cây của … — lượt này chưa quét hết." | ERP cắt cây cụm lớn | `flow_web/agent_bot.py:1912-1913` |
| "Làn nhanh SKU bật: nhịp Ns, trần N request/phút, N worker." | Làn nhanh đã lên. Làn tắt thì **không** có dòng nào | `flow_web/sku.py:1640` |
| "Làn nhanh SKU đánh số cụm …" | Làn vừa đánh mã | `flow_web/sku.py:1894` |
| "Làn nhanh SKU để lượt quét chính đánh số cụm …" | Cụm lớn quá trần, nhường | `flow_web/sku.py:1810` |
| "Làn nhanh SKU bị 429, nghỉ tới …" | ERP từ chối, làn nghỉ | `flow_web/sku.py:1935` |
| "Làn nhanh SKU hỏng một nhịp: …" | Lỗi lạ trong một nhịp | `flow_web/sku.py:1649` |
| "Làn nhanh SKU không đọc được bảng …: … **(đọc lại ở nhịp kế)**" | ERP lỗi thoáng qua (`QueryDeadlockError`). Bảng ấy được đọc lại sau 15 giây. Bình thường | `flow_web/sku.py:1692` |
| "Làn nhanh SKU không đọc được bảng …: … **(dời 300 giây)**" | Lần đọc lại cũng hỏng, hoặc lỗi không phải deadlock. Bảng ấy nguội 5 phút | `flow_web/sku.py:1699` |
| "Làn nhanh SKU không đọc được cây thẻ … (cụm …)" | Đọc cây riêng của một thẻ ngoài cây bị cắt, không được | `flow_web/sku.py:1873` |

**Đo bản vá deadlock bằng cách đếm hai đuôi trên.** Không có dòng tổng nào
khác. `(đọc lại ở nhịp kế)` mà **không** có `(dời 300 giây)` theo sau cho cùng
bảng ấy nghĩa là lần đọc lại đã thành công.

- Lượt đo đầu trên hvg-pc sau khi lên dot9 (17:02:57 → 17:10:39): 1 lần
  `(đọc lại ở nhịp kế)` lúc 17:03:04 (PROJ-0005), **0** lần `(dời 300 giây)`,
  0 Traceback, 0 ERROR, 0 dòng 429.
- Mốc trước đó, khi chưa có bản vá: deadlock rải rác chừng **một lần mỗi 10
  phút**, lần nào cũng dời bảng ấy 300 giây.
| "ERP chặn giữa lượt đánh số …: dừng, N thẻ để lượt sau." | Gặp 429 trong lượt đánh số, lượt dừng, N thẻ chưa đụng tới sẽ làm ở lượt sau. Bình thường khi ERP đông | `flow_web/service.py:14632-14636` |
| "chưa đặt ERP_SKU_STATUS_FILE hay ERP_LISTING_FILES_DIR: bảng SKU không có số" | Bot không có chỗ ghi tệp SKU | `flow_web/sku_board.py:503` |

Log của tiến trình bảng: "[board] dựng phần … lỗi: …" — `flow_web/board.py:238`.

Không thấy dòng "Agent bot bật" sau khi khởi động, cũng không thấy "Agent bot
tắt": app chưa lên tới chỗ bật bot. Xem log khởi động của app 8000.

## 2.6. Khởi động lại

**Chỉ khởi động lại app 8000:** `pc-backup-restart.ps1 -Stage restart`.
- Tệp này nằm ở `C:\HaviGroup\` trên hvg-pc, **không nằm trong git** (không
  nhánh nào có).
- `-Stage restart` làm lần lượt:
  1. Thử import `flow_web.service` và `flow_web.agent_bot`. Lỗi thì in
     `IMPORT=fail`, thoát 1, **không** restart.
  2. Dừng task "HaviGroup Flow v2".
  3. Chỉ giết python có dòng lệnh khớp **cả** `flow_web` **và** `--port 8000`.
     Vì vậy không đụng 8001, bảng 8765 hay lister.
  4. Bật lại task, rồi gọi `/api/health` của 8000.
- Tự tìm tiến trình để tắt thì cũng phải lọc `--port 8000`: lọc theo tên
  flow-v2 là giết luôn bản Listing ở 8001.
- Nguồn: c8 kiểm trên hvg-pc 12/09 (đọc script, không chạy).

**Bảng:** sửa code bảng hay đổi mật khẩu thì bật lại theo năm bước dưới đây.

- **Chỉ Stop task là chưa đủ.**
  - `Stop-ScheduledTask "HaviGroup Board"` đưa task về Ready, nhưng chỉ dừng
    `cmd.exe` mà task theo dõi.
  - Tiến trình `powershell … run-board.ps1` và hai tiến trình
    `python -m flow_web.board` vẫn sống, vẫn nghe 8765.
  - `run-board.ps1` không giết bảng cũ. Start ngay, hoặc chờ trigger 5 phút, là
    `run-board.ps1` chạy thêm một lần trong khi bảng cũ vẫn nghe 8765.
  - Nguồn: c8 gặp khi deploy dot8 trên hvg-pc 12/09, và làm đúng năm bước dưới
    đây.
- **Trigger lặp:**
  - Là một TimeTrigger lặp mỗi 5 phút, không hết hạn, kèm `IgnoreNew`. Task
    "HaviGroup Board Tunnel" cũng `IgnoreNew`.
  - Task còn Running thì trigger chỉ ra mã `0x800710E0` (bản đang chạy vẫn còn),
    không dựng bảng mới.
  - Rủi ro chỉ có khi task về Ready mà bảng vẫn sống, tức sau
    `Stop-ScheduledTask`.
  - Nguồn: c8 đọc task và kiểm sau mốc trigger, hvg-pc 12/09.
1. Dừng task: `Stop-ScheduledTask -TaskName "HaviGroup Board"`.
2. Tìm tiến trình bảng, đọc dòng lệnh trước khi tắt:

   ```powershell
   Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'flow_web\.board|run-board\.ps1' } | Select-Object ProcessId, CommandLine
   ```

   - Mẫu lệnh lấy từ `install_board_task.ps1:96`, chuỗi khớp `flow_web\.board`
     ở `:77`. Thêm `run-board\.ps1` để thấy cả powershell bọc ngoài. c8 lọc
     bằng đúng hai chuỗi này.
   - Thường thấy ba dòng: một `powershell … run-board.ps1` và hai
     `python -m flow_web.board`.
   - Hai python là **một** bảng, không phải hai. Một là launcher
     `.venv\Scripts\python.exe`, một là tiến trình con nó đẻ ra, chạy Python311
     gốc. Venv trên Windows chạy như vậy.
   - Tắt từng pid khớp (c8 dùng đúng lệnh này):

     ```powershell
     Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
     ```

   - **Không** tắt `cloudflared`, không đụng task "HaviGroup Board Tunnel".
3. Chờ 3 giây, rồi kiểm 8765 không còn tiến trình nào nghe. Lệnh sau phải ra
   0 dòng; còn dòng thì chờ thêm rồi chạy lại:

   ```powershell
   Get-NetTCPConnection -LocalPort 8765 -State Listen
   ```

4. Bật task: `Start-ScheduledTask -TaskName 'HaviGroup Board'`.
5. Kiểm:
   - lệnh ở bước 3 ra đúng **một** dòng. Pid nghe là cột `OwningProcess`
     (`scripts/apply_rule_update.ps1:122-124` dùng cùng lệnh);
   - `curl.exe -s -o NUL -D - http://127.0.0.1:8765/` ra 303 về `/login`;
   - task ở Running.
- Để yên thì trigger chỉ dựng lại bảng khi tiến trình bảng đã chết.
- **Đừng** chạy lại `install_board_task.ps1` chỉ để bật bảng. Script ấy:
  - cần quyền admin;
  - đăng ký lại (`-Force`) **cả hai** task, "HaviGroup Board" và
    "HaviGroup Board Tunnel";
  - giết cả tiến trình bảng lẫn tunnel, nên bảng rớt khỏi Internet một lúc.
- Nguồn: `scripts/install_board_task.ps1:92-103` (nhánh
  `agent/prd-agent-improvements-tdd`), c8 kiểm trên hvg-pc 12/09.
- Script ấy chỉ dùng khi dựng bảng trên máy mới: mục 2.10.

**Review Lister:** bật lại ngay sau một lượt thì dễ bị ERP trả 429. Chờ 60–120
giây sau mốc `at` của lượt trước rồi mới bật. Đây là **kinh nghiệm vận hành**,
không phải cơ chế trong code: repo không có chỗ nào chờ như vậy.

Phần có trong repo:

- App 8000 chạy bằng `-m uvicorn flow_web.main:app --host 127.0.0.1 --port 8000`.
  — `automation_center/runner/run-flow-v2.ps1:18`
- Review Lister: task "HaviGroup Review Lister", chạy
  `python -m flow_web.review_lister --loop 300`, log ở
  `C:\HaviGroup\logs\review-lister.log`, tự khởi động lại mỗi phút, tối đa
  999 lần. — `scripts/install_review_lister_task.ps1:15-17`, `:53-60`;
  `scripts/run-review-lister.ps1:22`, `:41`
  - Cài task sẽ dừng các bản lister đang chạy tay. — `scripts/install_review_lister_task.ps1:33-37`
  - Thiếu `.venv` hoặc tệp môi trường thì wrapper thoát mã 78. — `scripts/run-review-lister.ps1:24-31`
- Lister gặp 429/503 khi chuyển thẻ sang Hoàn thành: ngừng chuyển trong lượt
  ấy, log "Không chuyển được thẻ … sang Hoàn thành: …". Không có Retry-After.
  — `flow_web/review_lister.py:571-574`

## 2.7. Biến môi trường

**Chỉ tên và ý nghĩa.** Không bao giờ chép giá trị vào tài liệu, chat hay commit.

Bảng (`flow_web/board.py`) không đọc biến môi trường nào.

| Biến | Ý nghĩa | Mặc định | Nơi đọc |
|---|---|---|---|
| `ERP_AGENT_TOKEN` | token của bot; trống là bot tắt | trống | `flow_web/agent_bot.py:298` |
| `ERP_BASE_URL` | địa chỉ ERP | có sẵn trong code | `flow_web/agent_bot.py:294` |
| `ERP_AGENT_BOT_USER` | danh tính bot | tự nhận | `flow_web/agent_bot.py:300` |
| `ERP_AGENT_PROJECTS` | thu hẹp dự án bot quét | mọi dự án bot được thêm vào | `flow_web/agent_bot.py:266` |
| `ERP_PROJECT_ID` | dự án nhà, luôn được giữ trong phạm vi | — | `flow_web/agent_bot.py:276` |
| `ERP_AGENT_SOURCE_STATUS` | cột nguồn bot xét; gõ sai tên cột thì log "Cột nguồn … không khớp" | trống = mọi cột | `flow_web/agent_bot.py:280`, `:960-972`, `:1788-1796` |
| `ERP_AGENT_POLL_SECONDS` | nghỉ giữa hai lượt quét. Trên hvg-pc **có** đặt (c8 kiểm 12/09) | 120 | `flow_web/agent_bot.py:302` |
| `ERP_AGENT_MAX_CARDS_PER_SCAN` | trần số thẻ Idea được khởi động tạo ảnh mỗi lượt; không chặn đánh SKU | 3 | `flow_web/agent_bot.py:313` |
| `ERP_AGENT_AUTORUN` | tự tạo ảnh và tách thẻ con. Tắt là mất cả bước tách thẻ con | bật | `flow_web/agent_bot.py:303` |
| `ERP_AGENT_AUTORUN_COOLDOWN_SECONDS` | nghỉ giữa hai lần tự chạy | 900 | `flow_web/agent_bot.py:305` |
| `ERP_AGENT_SCOPE` | phạm vi quét | board | `flow_web/agent_bot.py:309` |
| `ERP_AGENT_CHAT`, `ERP_AGENT_MAX_CHAT_REPLIES` | trả lời bình luận, trần mỗi lượt | bật, 5 | `flow_web/agent_bot.py:318-320` |
| `ERP_AGENT_COLUMN_ALERT`, `ERP_AGENT_MAX_COLUMN_ALERTS` | nhắc thẻ ở cột lạ | bật, 2 | `flow_web/agent_bot.py:322-324` |
| `ERP_AGENT_DRY_RUN` | chạy khô, không ghi ERP, không dựng làn nhanh | tắt | `flow_web/agent_bot.py:326` |
| `FLOW_AGENT_BOT_ALLOWED_AUTHORS` | chỉ nhận lệnh từ những người này | trống = không khoá | `flow_web/agent_bot.py:316` |
| `ERP_AGENT_RATE_PER_MINUTE` | trần request token bot | 50 | `flow_web/agent_bot.py:3415` |
| `ERP_AGENT_RATE_FILE` | sổ nhịp dùng chung | `DATA_DIR/erp-agent-nhip.json` | `flow_web/agent_bot.py:3413` |
| `ERP_GRAPHQL_PER_MINUTE` | trần request token service. **Đừng đặt 0**: 0 là tắt hẳn bộ điều tiết. Trên hvg-pc không đặt (c8 kiểm 12/09) | 40 | `flow_web/service.py:13252`, `:13270-13271` |
| `ERP_SKU_FAST_LANE` và `…_SECONDS`, `…_BUDGET`, `…_REST`, `…_REDISCOVER`, `…_WORKERS` | làn nhanh SKU | xem 2.4 | `flow_web/sku.py:1398-1407` |
| `ERP_SKU_STATUS_FILE` | chỗ bot ghi `sku_status.json` | — | `flow_web/sku_board.py:456` |
| `ERP_LISTING_FILES_DIR` | thư mục tệp của bản Listing | — | `flow_web/sku_board.py:459`, `flow_web/review_lister.py:618` |
| `ERP_LISTING_API_URL` | địa chỉ API Listing | — | `flow_web/listing_bridge.py:107` |
| `ERP_API_KEY`, `ERP_API_SECRET` | khoá của Review Lister | — | `flow_web/review_lister.py:176-177` |
| `ERP_CARD_URL_BASE` | gốc link thẻ | — | `flow_web/review_lister.py:629` |
| `FLOW_ENV_FILE` | tệp môi trường app đọc | `.env.local` ở gốc repo | `flow_web/main.py:46-48` |
| `FLOW_LOG_LEVEL` | mức log | INFO | `flow_web/main.py:87` |

## 2.8. Giới hạn đã biết

- **Cây bị cắt.** `taskFull` cắt `subtasks` ở khoảng 59–60 thẻ con
  (`flow_web/agent_bot.py:782`, `flow_web/sku_board.py:16`, `:104`).
  - Thẻ ngoài phần ấy mà có dòng `taskBoard` thì bảng đọc mã từ dòng bảng,
    nhãn "dòng bảng" (`flow_web/sku_board.py:295-312`, `:399-404`).
  - Không có dòng bảng thì "chưa đọc được (cây bị cắt)"
    (`flow_web/sku_board.py:269-292`). Không tính vào "Chưa có SKU".
  - Dòng `taskBoard` không có khối Thuộc tính. Thuộc tính của thẻ ngoài cây
    phải hỏi ERP riêng từng thẻ.
- **Hai trần request khác nhau.** 50/phút cho token bot (bot quét và làn
  nhanh, qua sổ nhịp chung), 40/phút cho token service. Làn nhanh còn trần
  riêng 20/phút bên trong. Chạm trần là bot chậm lại, không phải chết.
- **Khoá lượt quét khi bị huỷ.** Lượt quét bị huỷ lúc đang chờ một bước
  chạy trên thread thì khoá nhả ngay, còn bước ấy chạy nốt. Có thể chồng lấn
  tối đa một bước với lượt kế. Lượt nền chỉ bị huỷ khi tắt app.
  — `flow_web/agent_bot.py:3155-3161`
- **Bảng SKU chậm hơn làn nhanh.** Làn nhanh không ghi `sku_status.json`
  (mục 2.3).
- **429 giữa lượt đánh số.**
  - Gặp 429 đầu tiên thì lượt dừng ngay.
  - Các thẻ chưa đụng tới vào `failed` với lỗi "Chưa ghi, ERP đang chặn: …",
    kèm chữ "HTTP 429".
  - Sổ mã vẫn được lưu, nên thẻ đã nhận mã và chỗ giữ số không mất. Lượt sau
    làm tiếp.
  - Vì sao dừng: ERP đang chặn thì mỗi thẻ gõ tiếp tốn thêm request và thời
    gian thử lại, trong khi lượt vẫn giữ khoá đánh số.
  - Nguồn: `flow_web/service.py:14613-14637`.
- **`ERP_GRAPHQL_PER_MINUTE=0` tắt hẳn bộ điều tiết của token service.**
  Khi ấy chỉ còn backoff sau khi đã bị 429. Đừng đặt 0.
  — `flow_web/service.py:13270-13271`
- **Không có nút chạy bot trên bảng.** `/api/agent-bot/run` chỉ có ở app
  8000 (`flow_web/main.py:274-277`), không trang nào trong
  `flow_web/static/` gọi tới.
- **ERP deadlock khi đọc bảng.** ERP trả `HTTP 500 {"exc_type":"QueryDeadlockError"}`
  cho `taskBoard`, rải rác chừng một lần mỗi 10 phút. Đây là lỗi **phía ERP**,
  chưa báo cho đội ERP.
  - Từ 12/09 làn nhanh đọc lại bảng ấy ở nhịp kế, đúng một lần (mục 2.4).
    Đo lần đầu: 1/1 lần đọc lại thành công.
  - Lượt quét chính **không** có bản vá này: bot gặp deadlock thì bỏ lượt ấy,
    lượt sau (120 giây) làm lại.
  - Nếu về sau thấy nhiều dòng `(dời 300 giây)` thì bản vá không đủ, phải báo
    đội ERP chứ đừng nâng số lần thử lại: mỗi lần thử lại là một request ăn
    vào trần 20/phút của làn.

## 2.9. Chưa kiểm

c8 đã kiểm các mục cũ trên hvg-pc ngày 12/09. Kết quả đã chuyển sang mục
2.1, 2.4, 2.6, 2.7. Còn lại:

1. Thời gian thật từ lúc kéo thẻ tới lúc có SKU trên máy thật, khi làn nhanh
   bật: **chưa đo được**. Từ 15:00 tới 17:10 ngày 12/09 không có thẻ mới nào
   sang Đang làm, làn nhanh không có việc để bấm giờ. Cách đo: kéo một thẻ,
   rồi đếm từ dòng log `Làn nhanh SKU đánh số cụm …` ngược lên.
2. Tỉ lệ đọc lại thành công của bản vá deadlock: mới có **1 mẫu** (1/1) trong
   8 phút đầu sau khi lên dot9. Cần đếm lại sau một ngày chạy thật — cách đếm
   ở mục 2.5.

## 2.10. Dựng lại từ đầu

Dùng khi dựng bảng trên một máy mới, hoặc khi mất cả hai task. Bảng đang có
task mà chỉ cần bật lại thì xem mục 2.6.

Nguồn:

- `scripts/install_board_task.ps1` (9c30075) và `scripts/run-board.ps1`
  (9e10aa0).
  - Hai script này **chỉ có trên nhánh `agent/prd-agent-improvements-tdd`**,
    chưa có ở main hay dot8.
  - Đọc bằng `git show origin/agent/prd-agent-improvements-tdd:scripts/<tệp>`.
- Mục "Dựng lại từ đầu" của bản tài liệu cũ trên cùng nhánh:
  `docs/bang-dieu-khien.md:125-150` (9e10aa0). Dưới đây gọi là "tài liệu cũ".
- Code bảng trích trên 52a9383.

**Trước khi bắt đầu:**

- `install_board_task.ps1` cần PowerShell **quyền admin** (`:3`).
- Script ấy dừng và giết cả tiến trình bảng lẫn tunnel, rồi đăng ký lại cả hai
  task (`:92-103`). Bảng rớt khỏi Internet một lúc. **Chỉ dùng khi dựng mới.**
- Tên miền ghi cứng ở hai chỗ:
  - tham số `-HostName` (`install_board_task.ps1:19`);
  - biến `$HostName` (`run-board.ps1:18`).
  - Đổi tên miền thì sửa cả hai. Tài liệu này không ghi tên miền.
- Hai tệp `.ps1` phải lưu **UTF-8 có BOM**, vì máy chạy PowerShell 5.1
  (tài liệu cũ `:150`).
- Bảng lấy số từ app 8000 và bản Listing 8001 trên cùng máy (bảng ba tiến
  trình ở mục 2.1).

**Bước 1. Code và `.venv`.**

- Repo đặt ở `RepoRoot` (mặc định ở `install_board_task.ps1:16`,
  `run-board.ps1:13`). Trên hvg-pc thư mục ấy không phải repo git, phải chép
  tệp vào (tài liệu cũ `:127`).
- Chép cả thư mục `flow_web/` của nhánh đang chạy trên máy (`agent/hvg-pc-dotN`).
  - **Đừng** lấy `flow_web/` của nhánh prd: `board.py` bên ấy là bản cũ, chưa
    có phần SKU.
  - Danh sách chép lẻ ở tài liệu cũ (`:128-130`) nay thiếu tệp:
    - `board.py` cần `sku_board.py` (`flow_web/board.py:46`);
    - `sku_board.py` cần `erp_meta.py`, `pipeline.py`, `sku.py`
      (`flow_web/sku_board.py:34-39`);
    - `listing_board.py` cần `review_lister.py` (`flow_web/listing_board.py:23`).
- Chép `run-board.ps1` và `install_board_task.ps1` từ nhánh prd vào
  `scripts\` của `RepoRoot`. Thiếu `run-board.ps1` thì install dừng
  (`install_board_task.ps1:26-27`).
- `.venv` dùng Python 3.11. hvg-pc chạy 3.11.9
  (`automation_center/docs/runner-host-runbook.md:76`). Dựng theo
  `README.md:166-174`:

  ```powershell
  py -3.11 -m venv .venv
  .\.venv\Scripts\Activate.ps1
  python -m pip install --upgrade pip
  python -m pip install -e .
  ```

- `run-board.ps1` tìm `.venv\Scripts\python.exe` trong `RepoRoot`. Thiếu thì
  thoát mã 78 (`run-board.ps1:14`, `:21-24`).

**Bước 2. Tệp mã băm mật khẩu.**

- Mật khẩu không nằm trong repo, không có biến môi trường. Bảng chỉ đọc tệp mã
  băm (mục 2.2).
- Đường dẫn tệp đặt ở biến `$PasswordFile` (`run-board.ps1:15`). Tài liệu này
  không ghi đường dẫn ấy.
- Tạo tệp trong **cmd**, đứng ở `RepoRoot` (tài liệu cũ `:102-105`):

  ```bat
  .venv\Scripts\python.exe -m flow_web.board --hash-password > <tệp mã băm>
  ```

  - Lệnh hỏi mật khẩu hai lần, không hiện chữ. Mật khẩu ít nhất 6 ký tự.
    — `flow_web/board.py:516-522`, `:544-549`
  - Dùng cmd, đừng dùng `>` của PowerShell 5.1. PowerShell ghi tệp bằng
    UTF-16, còn bảng đọc bằng UTF-8 (`flow_web/board.py:555`). Đọc hỏng thì
    bảng thoát (`:556-558`).
- Khoá quyền đọc tệp, chỉ để chủ máy, SYSTEM và Administrators
  (tài liệu cũ `:131-134`):

  ```bat
  icacls <tệp mã băm> /inheritance:r /grant:r %COMPUTERNAME%\%USERNAME%:F *S-1-5-18:F *S-1-5-32-544:F
  ```

- Thiếu tệp thì `run-board.ps1` thoát mã 78 (`:25-28`). Có `--host-name` mà
  thiếu `--password-file` thì bảng từ chối chạy (`flow_web/board.py:559-561`).
- Sau này đổi mật khẩu:
  - ghi đè tệp, rồi bật lại bảng theo năm bước ở mục 2.6. Bảng chỉ đọc tệp
    lúc khởi động (`flow_web/board.py:552-555`).
  - Chỉ Stop/Start task thì bảng cũ vẫn chạy, vẫn nhận mật khẩu cũ.
  - Không cần chạy lại install, dù tài liệu cũ (`:107-108`) bảo vậy.

**Bước 3. Tunnel.**

- Làm trên một máy có `cloudflared` và vào được tài khoản Cloudflare
  (tài liệu cũ `:135-142`):

  ```bash
  cloudflared tunnel login                              # chọn zone của tên miền
  cloudflared tunnel create havi-board
  cloudflared tunnel route dns havi-board <tên miền>
  ```

- `create` sinh tệp khoá `<id>.json`.
  - Chép tệp ấy vào thư mục `$TunnelDir` trên máy chạy bảng (tham số ở
    `install_board_task.ps1:17`).
  - Tệp khoá không đưa vào repo, không gửi ai.
- Thư mục ấy phải có **đúng một** tệp `*.json`. Chưa có `config.yml` thì
  install dựng từ tệp khoá: id tunnel, tệp khoá, tệp log, tên miền trỏ về
  `127.0.0.1:8765`, còn lại trả 404 (`install_board_task.ps1:31-50`). Đã có
  `config.yml` thì install giữ nguyên.
- Máy chạy bảng cần `cloudflared.exe` ở đường dẫn tham số `-Cloudflared`
  (`:18`). Thiếu thì install dừng (`:28`).
- Tài khoản Cloudflare còn tunnel khác: đừng xoá, đừng sửa (tài liệu cũ
  `:92-94`).

**Bước 4. Đăng ký hai task.** Mở PowerShell quyền admin (`install_board_task.ps1:3-5`):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <RepoRoot>\scripts\install_board_task.ps1
```

- Tạo thư mục log (`:29`).
- Hai task (`:74-90`):
  - "HaviGroup Board": `cmd.exe /c powershell … -File run-board.ps1`, nối log
    vào `board.log` (`:78-79`);
  - "HaviGroup Board Tunnel": `cloudflared tunnel --config <config.yml> run`
    (`:86-87`).
- Trigger khi khởi động, khi đăng nhập, và lặp mỗi 5 phút (`:58-62`).
- `IgnoreNew`, `RestartCount 999`, không giới hạn thời gian chạy (`:64-71`).
- Chạy bằng tài khoản `<tên máy>\<người dùng>`, S4U, quyền cao nhất (`:54`,
  `:72`).
- Với từng task: Stop, giết tiến trình khớp, Register `-Force`, Start
  (`:92-103`). Cuối cùng in trạng thái hai task (`:104-105`).

**Bước 5. Kiểm.**

Bảng không có địa chỉ health riêng. Kiểm bằng các bước sau.

- Hai task ở trạng thái Running: `Get-ScheduledTask -TaskName "HaviGroup Board*"`
  (`install_board_task.ps1:105`).
- Bảng lên trên máy:
  - `curl.exe -s -o NUL -D - http://127.0.0.1:8765/` phải ra 303 về `/login`;
  - `127.0.0.1` luôn được nhận (`flow_web/board.py:297`, `:348-353`);
  - chưa đăng nhập thì bảng chuyển về `/login` (`:403-406`).
- Qua tunnel: cùng lệnh với `https://<tên miền>/`, cũng ra 303 về `/login`
  (tài liệu cũ `:96-98`).
- Đừng dùng `curl -I`. Bảng không có `do_HEAD`, nên HEAD trả 501 (tài liệu cũ
  `:96`).
- Không lên thì đọc log:
  - `board.log` (`install_board_task.ps1:79`):
    - "Thiếu .venv" hoặc "Thiếu <tệp>": `run-board.ps1:21-28`;
    - "Không đọc được tệp mật khẩu": `flow_web/board.py:557`;
    - "Không mở được cổng": `flow_web/board.py:568`.
  - `cloudflared.log`: dòng `logfile` trong `config.yml`
    (`install_board_task.ps1:41`).
- Cuối cùng đăng nhập bằng mật khẩu vừa đặt, xem bảng có đủ như mục 1.2.

# Kéo sang *Đang làm* là có mã, khỏi bấm 👍/👎

## Chuyện đang xảy ra

Người trong team kéo thẻ Idea sang *Đang làm* rồi đợi mã. Mã không tới. Sáng
15/09 Nguyễn Phương hỏi bốn thẻ `Idea 1`–`Idea 4` của cụm `TASK-2026-05740`
(`TASK-2026-06082`…`06085`) — cả bốn nằm ở *Đang làm* từ hôm trước, không thẻ
nào có mã.

Không phải hỏng. Bản đang chạy giữ luật cũ: `_votes_outstanding` trả
`"còn N ảnh chờ 👍/👎"` khi còn tấm nào chưa ai bấm, nên `needs_sku_fill` lắc.
Bốn thẻ ấy còn 11/8/10/12 tấm trắng phiếu. Luật cũ đòi bấm **hết** từng tấm.

Người đặt việc đã chốt lại luật: **kéo sang *Đang làm* là đủ, không cần bấm
like/dislike nữa.**

## Vì sao không đẩy thẳng bản 14/09 quay lại

Hôm 14/09 đã có một bản nới. Nó sửa `_votes_outstanding` — mà hàm ấy nuôi
**ba** cổng cùng lúc:

| Cổng | Việc | Nới có đúng ý không |
|---|---|---|
| `needs_sku_fill` | máy cấp mã | **đúng** — cái đang xin |
| `_leave_doing` | *Đang làm* → *Đang review* | **sai** |
| `_leave_todo`, `_leave_review` | các cổng còn lại | sai |

Đo trên bảng thật 15/09 (vá đúng một hàm rồi gọi lại chính `needs_sku_fill` /
`decide` của bot, `PROJ-0018`, 371 dòng, 72 thẻ ở *Đang làm*):

```
luat dang chay : cap ma ngay 0 the | day sang cot ke 0 the
luat 14/09     : cap ma ngay 4 the | day sang cot ke 0 the
luat 14/09, gia su 4 the DA nhan ma (luot quet ke tiep):
  TASK-2026-06082 -> Pending Review   (con 11 anh chua ai bam)
  TASK-2026-06083 -> Pending Review   (con  8 anh chua ai bam)
  TASK-2026-06084 -> Pending Review   (con 10 anh chua ai bam)
  TASK-2026-06085 -> Pending Review   (con 12 anh chua ai bam)
```

Nghĩa là: thẻ vừa được kéo vào *Đang làm* nhận mã, rồi **biến khỏi cột của
người vừa kéo nó** ở lượt quét kế, sang bàn người viết listing với cả chục
tấm ảnh chưa ai nhìn. Đó là thứ không ai xin.

## Muốn gì

Kéo thẻ Idea sang *Đang làm* → **có mã ngay**, không cần bấm tấm nào.
Thẻ **ở yên** tại *Đang làm*; ai muốn đẩy sang *Đang review* thì tự kéo.

## Luật

1. **Cổng cấp mã tách khỏi cổng chuyển cột.** `needs_sku_fill` dùng điều kiện
   riêng, lỏng hơn; `decide` giữ nguyên điều kiện cũ.
2. Cấp mã khi thẻ ở *Đang làm* và **có ít nhất một tấm ảnh chưa bị 👎**. Ảnh
   trắng phiếu tính là dùng được.
3. **Không ảnh thì không mã.** `images_total == 0` là thẻ chưa có gì để bán —
   giữ nguyên như cũ.
4. **👎 hết thì không mã.** Idea ấy tay trắng thật; thẻ ở lại để chạy lại ảnh.
5. Thẻ sản phẩm (`is_product`) không đổi gì: ảnh của nó không chờ phiếu nào.
6. **Chuyển cột không nới một ly.** *Đang làm* → *Đang review* vẫn đòi mọi ảnh
   đã bấm và còn ít nhất một 👍. *Cần làm* → *Đang làm* và *Đang review* →
   *Hoàn thành* cũng thế.

## Bán kính nổ

Bot chỉ quét **cột nguồn `Working`** (`agent_bot.py`, `card_is_in_source_column`
lọc trước mọi thứ khác). Thẻ ở *Cần làm* không lọt vào tầm nó, nên số thẻ chạy
ngay sau khi đẩy luật này = số thẻ **đang ở *Đang làm* mà chưa có mã**:

Đo bằng cách chạy **đúng hàm của nhánh này** lên bảng thật trên hvg-pc
(`PROJ-0018`, `includeArchived: false`, chỉ đọc, sáng 15/09):

```
tong dong 371 | 79 the o Working | 2 cum
VONG MOT   cap ma 5 the | day sang cot ke 0 the
  TASK-2026-06082 Idea 1   anh 12, chua bam 11, giu 0
  TASK-2026-06083 Idea 2   anh  9, chua bam  8, giu 0
  TASK-2026-06084 Idea 3   anh 10, chua bam 10, giu 0
  TASK-2026-06085 Idea 4   anh 12, chua bam 12, giu 0
  TASK-2026-06262 Idea 39  anh 13, chua bam 13, giu 0
VONG HAI (5 the tren coi nhu da nhan ma) | bi day di 0 the
  moi the: dich='' , ly do="con N anh cho 👍/👎"
```

**5 thẻ** — bốn thẻ Nguyễn Phương hỏi, cộng `Idea 39` được kéo sang sau đó.
**Không thẻ nào bị chuyển cột**, cả ở lượt quét cấp mã lẫn lượt kế tiếp. Vòng
hai chính là chỗ bản 14/09 vỡ; đo riêng ra để chắc nó không vỡ lại.

Sau đó bán kính nằm trong tay người dùng: kéo bao nhiêu thẻ sang *Đang làm*
thì cấp bấy nhiêu mã. Đó là đúng thiết kế.

Một việc kiểm lại tiện thể: hvg-pc **đang chạy bản nghiêm** — thân
`needs_sku_fill` trên máy đó vẫn gọi `_images_settled`. Luật 14/09 không còn
sống ở máy chạy thật.

## Test đỏ

Trong `tests/test_pipeline.py`:

1. `needs_sku_fill` **gật** cho thẻ ở *Đang làm*, 11 ảnh, 11 tấm trắng phiếu,
   chưa có mã.
2. `needs_sku_fill` **gật** cho thẻ 12 ảnh: 1 tấm 👎, 11 tấm trắng phiếu.
3. `needs_sku_fill` **lắc** khi `images_total == 0`.
4. `needs_sku_fill` **lắc** khi mọi tấm đều 👎 (`kept == 0`, `pending == 0`,
   `total > 0`).
5. `decide` cho **chính thẻ ở test 1 nhưng đã có mã** phải trả về đích rỗng và
   lý do `"còn 11 ảnh chờ 👍/👎"` — cổng chuyển cột không được nới theo.
6. `decide` từ *Cần làm* với ảnh trắng phiếu vẫn đứng im.
7. `sku_fill_is_due` (làn nhanh) gật cho cây có thẻ như test 1 — cổng làn
   nhanh gọi thẳng `needs_sku_fill` nên phải đi theo.

### Một test cũ phải viết lại, nói rõ ở đây

`test_a_card_still_waiting_on_people_is_not_the_machines_turn` khẳng định
đúng cái luật vừa bị đổi. Nó không phải hàng rào kỹ thuật — nó là bản chép
của luật kinh doanh cũ. Viết lại thành test 1, giữ nguyên phần nó thật sự
canh (thẻ không được chuyển cột) bằng test 5.

## Không làm trong đợt này

- Không đụng làn nhanh `sku.py`: dòng `"cụm chưa tới lượt, để lượt quét chính"`
  là bình thường, lượt quét chính 120 giây một lần là đủ.
- Không đụng `sku_board.py`.
- Không tự deploy lên hvg-pc. Chờ người gật.

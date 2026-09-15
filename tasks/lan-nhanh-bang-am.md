# Làn nhanh SKU: bảng ấm — thẻ mới có mã trong 10–20 giây

## Vì sao

Đo trên hvg-pc ngày 12/09: làn nhanh đọc lại một bảng theo hai nhịp.

- Bảng **nóng** — còn thẻ gắn bot chưa có mã ở *Cần làm* hay *Đang làm* —
  đọc lại sau `interval_s` (15 giây).
- Bảng còn lại đọc lại sau `rediscover_s` (300 giây).

Nhịp 15 giây chỉ giúp khi làn **đã biết** có thẻ đang chờ. Nó không giúp
*phát hiện* thẻ mới. Bảng sạch — mọi thẻ đã có mã — rơi về 300 giây, nên thẻ
vừa được kéo vào phải chờ trung bình 150 giây, xấu nhất 300 giây, mới bị nhìn
thấy. Đó là toàn bộ độ trễ người dùng than phiền.

Bảng sạch là trạng thái **thường ngày**, không phải ngoại lệ: sáng 12/09,
PROJ-0018 có 35/35 thẻ *Đang làm* đã có mã, PROJ-0087 10/10 — cả hai đều nguội.

## Luật mới

Thêm nhịp thứ ba, nằm giữa hai nhịp cũ: **bảng ấm**.

1. Sau mỗi lần đọc bảng thành công, làn tính một **dấu bảng**: `modified` lớn
   nhất trong các dòng, kèm số dòng. Dấu đổi so với lần đọc trước nghĩa là có
   người vừa động vào bảng ấy.
2. Dấu đổi thì bảng **ấm** trong `warm_for_s` giây (mặc định 900). Bảng ấm đọc
   lại sau `warm_s` giây (mặc định 10) thay vì `rediscover_s`.
3. Bảng nóng vẫn đi trước bảng ấm, bảng ấm đi trước bảng nguội.
4. Nhiều nhất `warm_boards` bảng được hưởng nhịp ấm cùng lúc (mặc định 2). Quá
   số đó thì giữ những bảng có hạn ấm còn lại dài nhất — tức bảng vừa động gần
   đây nhất. Đây là hàng rào chi phí: `warm_boards` bảng × (60 / `warm_s`)
   request mỗi phút.
5. `warm_boards = 0` tắt hẳn tính năng: hành vi quay về đúng như trước.
6. Lượt ngó **thêm vì ấm** chỉ được lấy ngân sách khi còn dư chỗ cho trọn một
   lượt đánh số cụm ba thẻ (`_LANE_WARM_RESERVE = 1 + fill_cost(3)`). Lượt ngó
   định kỳ là bắt buộc, lượt ngó thêm là xa xỉ, nên nó phải nhường. Hệ quả
   quan trọng: **trần hẹp thì nhịp ấm tự tắt** và hành vi quay về như cũ —
   không bao giờ có chuyện ngó nhanh hơn mà lại ghi mã chậm đi. Bảng ấm bị từ
   chối quá `rediscover_s` thì đọc như bảng thường, để không chết đói.
7. Nhịp ngủ của `run_forever` là nhịp **nhỏ nhất** đang dùng (`tick_s`): ngó
   mỗi 10 giây thì vòng lặp phải thức mỗi 10 giây, không thể thưa hơn.

So sánh dấu chứ không so `modified` với đồng hồ máy: ERP trả giờ máy chủ, máy
trung tâm lệch múi giờ, so thẳng là sai cả hai chiều. So hai lần đọc liên tiếp
thì miễn nhiễm múi giờ.

## Biến môi trường

| Tên | Mặc định | Chặn |
|---|---|---|
| `ERP_SKU_FAST_LANE_WARM` | 10 | 5–120 |
| `ERP_SKU_FAST_LANE_WARM_FOR` | 900 | 60–7200 |
| `ERP_SKU_FAST_LANE_WARM_BOARDS` | 2 | 0–6 |

## Chi phí

Xấu nhất 2 bảng × 6 lần/phút = 12 request/phút, trên nền 5,4 request/phút hiện
nay. Trần làn nhanh **mặc định 20/phút vừa khít một lượt đánh số cụm 3 thẻ**
(`1 + 1 + fill_cost(3)` = 20), không còn chỗ cho lượt ngó thêm — nên trên máy
giữ mặc định, luật 6 làm nhịp ấm tự tắt và mọi thứ chạy y như trước. Muốn
hưởng 10–20 giây thì phải nâng `ERP_SKU_FAST_LANE_BUDGET`.

Số nền đo trên hvg-pc, 19:48–21:26 ngày 12/09 (1 giờ 38 phút, tính từ lần khởi
động cuối): **0 lần HTTP 429, 0 ERROR, 0 traceback**, 16 lượt quét chính
(≈ 6 phút một lượt), 12 lần `QueryDeadlockError` đều tự đọc lại được. Token bot
có 60 request/phút và đang còn dư nhiều, nên `ERP_SKU_FAST_LANE_BUDGET=40` là
an toàn: 17 ngó + 20 đánh số = 37 ≤ 40, cộng ~7/phút của lượt quét chính vẫn
dưới 60. Đặt xong phải canh lại số 429 trong log.

## Test đỏ

`tests/test_lan_nhanh_bang_am.py`:

- bảng sạch vừa có thay đổi thì đọc lại sau `warm_s`, không phải `rediscover_s`;
- bảng sạch không đổi gì vẫn đợi `rediscover_s`;
- thẻ kéo vào bảng sạch **đang ấm** có mã trong 20 giây;
- hạn ấm hết thì bảng về lại nhịp 300 giây;
- không bao giờ quá `warm_boards` bảng ấm cùng lúc;
- `warm_boards = 0` giữ nguyên hành vi cũ;
- trần hẹp thì nhịp ấm tự tắt, và bảng ấm bị từ chối quá lâu vẫn được đọc;
- bảng vừa nóng vừa ấm lấy nhịp nhanh hơn trong hai;
- ngân sách: bảng ấm vẫn chừa chỗ cho một lượt đánh số;
- `tick_s` là nhịp nhỏ nhất; đọc env đúng và chặn đúng biên.

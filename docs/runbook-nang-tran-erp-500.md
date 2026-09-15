# Runbook: hôm ERP nâng trần lên 500 request/phút thì đổi gì

Runbook này trả lời đúng một câu hỏi: **đội ERP vừa báo đã nâng trần token bot,
giờ tôi gõ gì để thẻ kéo sang "Đang làm" được đánh số trong ~5 giây?**

Câu trả lời ngắn: **sáu dòng trong `.env.local`, không sửa code.** Code đã mở
sẵn trần cấu hình rồi; hôm nay mặc định vẫn là cấu hình an toàn cho trần 60.

> **Đã làm rồi, 13/09/2026 14:16.** hvg-pc đang chạy đúng sáu dòng dưới đây.
> Giữ lại runbook để lần sau đổi số còn biết đường. Đọc thêm mục "Số luồng" —
> chỗ đó suýt làm hỏng cả đợt.

## Bước 0 — đo xem đã nâng thật chưa

ERP **không phơi header rate-limit** (`X-RateLimit-*`, `Retry-After` đều không
có), nên không hỏi nhẹ nhàng được. Phải đo:

```powershell
C:/HaviGroup/flow-v2/.venv/Scripts/python.exe C:/HaviGroup/pc_do_tran.py
```

Script chỉ đọc, tự dừng ở 429 đầu tiên, cận trên 90 request. Đọc dòng cuối:

- `429 o request thu 36` → **chưa nâng**. Bot sản xuất đang dùng phần còn lại
  của hạn mức, 36 + phần bot ≈ 60. Dừng ở đây.
- `het can tren` với `request 200 : 90` → **đã nâng**. Đi tiếp.

Script nhận cận trên làm tham số: `pc_do_tran.py 560`. Nó bắn tuần tự nên
chỉ đạt ~320 request/phút — đủ để phân biệt 60 với 500, không đủ để tìm mép
thật. Muốn tìm mép thì dùng `C:\HaviGroup\pc_do_tran_song.py <số luồng> <cận
trên>`, nhưng đọc mục "Số luồng" trước: nhiều luồng làm ERP trả 500 chứ không
trả 429, dễ đọc nhầm thành "trần thấp".

Đo 13/09/2026 sau khi nâng: 2 luồng giữ **657 request/phút** sạch 429, 4 luồng
đạt **1297/phút** vẫn sạch 429. Trần mới rộng hơn 500 nhiều.

Cái giá của phép đo: nếu chưa nâng thì mình vừa chạm trần, làn nhanh sẽ
**nghỉ đúng 60 giây** (`ERP_SKU_FAST_LANE_REST`) rồi chạy tiếp. Không có hậu
quả kéo dài, nhưng đừng đo lúc đang gấp.

## Bước 1 — sáu dòng trong `.env.local` trên hvg-pc

Sao lưu trước đã, rồi đặt:

```env
ERP_AGENT_RATE_PER_MINUTE=500
ERP_SKU_FAST_LANE_SECONDS=5
ERP_SKU_FAST_LANE_BUDGET=400
ERP_SKU_FAST_LANE_WARM=5
ERP_SKU_FAST_LANE_WARM_BOARDS=18
ERP_SKU_FAST_LANE_REDISCOVER=5
```

`WARM_BOARDS=18` là **số dự án đang mở**, không phải 29. Làn nhanh đã bỏ 11 dự
án `Completed` từ trước. Số dự án mở có đổi thì sửa lại con số này cho khớp;
đặt thừa cũng không sao, nó tự kẹp theo số bảng thật.

## Số luồng — chỗ dễ sai nhất

**Đừng nâng `ERP_SKU_FAST_LANE_WORKERS`.** Mặc định là **2**, và đó là con số
đo được chứ không phải đoán.

Đo trên ERP thật ngày 13/09/2026, **cùng nhịp đọc 216 request/phút**, chỉ đổi
số luồng:

| số luồng | `QueryDeadlockError` mỗi phút | 429 | mẫu |
|---|---|---|---|
| 4 | 3,8 | 0 | 14:11–14:15 |
| 2 | **2,1** | 0 | 14:17–14:50, 33 phút |

Hạ luồng cắt được **gần một nửa**, không hết hẳn. Chỗ nghẽn của ERP là **số truy
vấn đồng thời**, không phải số request mỗi phút: bắn thử 8 luồng thì ERP trả
HTTP 500 hàng loạt trong 1,4 giây — vẫn không phải 429. Nâng trần token lên 500
**không** chữa được chỗ này.

**Cách đếm cho đúng:** gom theo phút bằng `Group-Object`, đừng lọc bằng khoảng
thời gian rồi đếm một cục. Lần đầu đo tôi lọc `Substring(11,8)` theo khoảng và
ra 0 — sai, log không hề lặng. Số ở bảng trên đếm bằng `Group-Object`.

**Cái giá phải nói rõ:** trước hôm nay làn nhanh đọc 33 request/phút và sổ ghi
8–21 deadlock *mỗi giờ* (≈0,2/phút). Giờ đọc 216/phút thì thành 2,1/phút — tức
gấp khoảng **10 lần**. Mỗi lỗi chỉ tốn một nhịp đọc lại 5 giây, không ảnh hưởng
việc điền SKU, nhưng đó là tải thật đè lên DB dùng chung của ERP. Muốn bỏ hẳn
thì phải đi đường `modified` ở mục dưới, không phải chỉnh số luồng.

2 luồng vẫn thừa sức: 18 bảng × ~190 ms ÷ 2 = **1,7 giây**, trong nhịp 5 giây.
Pool luồng chỉ dùng để đọc bảng, dựng mới mỗi nhịp; việc đánh số chạy sau nó,
nên hạ luồng **không** làm chậm điền SKU.

## Bước 2 — khởi động lại rồi đọc đúng một dòng log

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\HaviGroup\pc-backup-restart.ps1 -Stage restart
```

Ngay lúc làn nhanh bật, nó tự tính chi phí cấu hình rồi in **một dòng**:

```
Làn nhanh SKU tự kiểm: 18 bảng (18 ấm, 0 còn lại), đọc ước 216.0/phút trong trần token 500/phút.
```

Đó là dòng phải đọc. Nếu thấy chữ **`VƯỢT trần token`** thì cấu hình sai — sửa
`.env.local` rồi khởi động lại, đừng để nó chạy. Làn nhanh **không tự kẹp**:
nó kêu rồi vẫn chạy, vì kẹp ngầm thì người vận hành không bao giờ biết mình
đặt sai. Chốt cuối chống bão 429 vẫn là bộ tự hãm token.

## Phép tính, để sau này ai đổi số cũng kiểm được

```
đọc bảng mỗi phút = (số bảng ấm × 60/WARM) + (số bảng còn lại × 60/REDISCOVER)
```

| Kịch bản | nhịp | ấm | đọc bảng | trần | |
|---|---|---|---|---|---|
| hôm nay | 15 s | 2 | 29,3/phút | 50 | lọt |
| sau khi nâng | 5 s | 18 | 216/phút | 500 | lọt |

216 chỉ là phần đọc bảng. Còn đọc cây thẻ và ghi mã nữa, nên `BUDGET=400` là
chỗ đệm — đừng hạ sát 216.

## Nếu đội ERP chọn cách khác

Bên mình có xin hai cách, cách thứ hai **rẻ hơn gần 20 lần**: thêm khoá
`modified` vào `taskProjects`. Có nó thì chỉ cần gọi `taskProjects` mỗi 5 giây
(**12 request/phút**) rồi đọc đúng dự án vừa động — phủ cả 18 bảng ở nhịp 5
giây mà **giảm** tải cho ERP.

Nếu họ làm cách đó thì runbook này không dùng được: phải sửa code (làn nhanh
đang đọc từng bảng một). Hỏi lại trước khi đặt sáu dòng trên.

Sau khi đo ngày 13/09, cách này **đáng xin hơn hẳn**: nó không chỉ rẻ hơn mà
còn là cách duy nhất bỏ được 2,1 deadlock/phút — thứ mà chỉnh số luồng chỉ
giảm được một nửa.

## Liên quan

- Trần token thật, cách đo, và sổ 503/530/deadlock: `docs/chay-test-toan-du-an.md`
  không nói chỗ này — xem thẳng `C:\HaviGroup\pc_ping_erp.py` và
  `C:\HaviGroup\pc_do_tran.py`, cả hai chỉ đọc.
- ERP nền vẫn trả `QueryDeadlockError` đều 8–21 lần/giờ suốt ngày đêm. Nâng
  trần request không chữa được chỗ đó.

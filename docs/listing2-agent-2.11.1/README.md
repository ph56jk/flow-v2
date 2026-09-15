# Agent VM Listing2 2.11.1 — thợ rút hàng đợi ERP

Bản ghi của bản vá đang chạy trên hvg-pc. File thật **không** nằm trong repo
này: nó là `C:\Listing2\scripts\listing2_vps_agent.py` của bản Listing2, và
`C:\Listing2` không phải git repo. Thư mục này giữ đủ để dựng lại, thử lại và
quay lui.

| File | Là gì |
|---|---|
| `va_agent.py` | Script vá. Mỗi mỏ neo phải khớp đúng một lần, không thì dừng. |
| `agent-2.10.99-2.11.1.diff` | Diff thống nhất, cùng kết quả với script vá. |
| `thu_erp_agent.py` | Bộ thử trọn vòng: controller giả, bridge thật, extension Etsy giả. Không chạm máy thật. |

Cách dùng, nguyên nhân và giới hạn: mục "Thợ rút hàng đợi ERP" trong
`docs/bat-listing-etsy.md`.

## Dấu vân tay

| Bản | sha256 (16 ký tự đầu) | Ở đâu trên hvg-pc |
|---|---|---|
| 2.10.99 gốc | `611448d6b8c6d60b` | `C:\Listing2\deploy-backups\agent-2.10.99-20260910-145602\scripts\` |
| 2.11.0 (lỗi việc đồng bộ nền) | `5c801b04b9a545df` | `C:\Listing2\deploy-backups\agent-2.11.0-20260910-150934\scripts\` |
| 2.11.1 bản đầu | `93f8f9ef47973207` | `C:\Listing2\deploy-backups\agent-2.11.1-pre-20260910-151502\scripts\` |
| **2.11.1 đang chạy** | `3aa0206c831c18ae` | `C:\Listing2\scripts\listing2_vps_agent.py` |

Hai bản 2.11.1 chỉ khác một đoạn chú thích.

## Dựng lại từ bản gốc

```bash
python3 va_agent.py listing2_vps_agent-2.10.99.py listing2_vps_agent.py
# hoặc
patch -o listing2_vps_agent.py listing2_vps_agent-2.10.99.py < agent-2.10.99-2.11.1.diff
```

Cả hai đường ra đúng sha `3aa0206c831c18ae` (kiểm ngày 10/09/2026).

## Thử lại

```bash
.venv/bin/python docs/listing2-agent-2.11.1/thu_erp_agent.py <đường dẫn agent>
```

Cần `127.0.0.1:18001` và `127.0.0.1:38421` rảnh. Kết quả 10/09/2026: 17/17
bài xanh. Bộ `tests.test_listing2_direct` của bản Listing2, chạy trên hvg-pc
bằng `C:\Listing2\.venv`: 38/38 với bản gốc, 38/38 với 2.11.1.

Tên file cố ý không bắt đầu bằng `test_`: đây không phải bộ test của repo,
và `unittest discover` không được gom nó.

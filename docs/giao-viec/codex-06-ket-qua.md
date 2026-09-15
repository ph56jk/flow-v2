# Kết quả Codex #06 — ba lỗi ERP/Flow

## Tiến độ

1. Đã đọc trọn `docs/giao-viec/codex-04-thieu-mot-the.md` trước khi khảo sát
   mã của Việc 1. Hướng đã chốt: nếu thẻ cha không có ảnh bìa thì không đoán
   ảnh sản phẩm; mọi ảnh thả phải thành thẻ con.
2. Đã ghi nhận quy ước số test: nếu sandbox chặn mạng hoặc giết tiến trình con,
   chỉ ghi số bài đã chạy được kèm nhãn **số hụt vì sandbox**; không coi đó là
   tổng số thật. Không sửa lỗi môi trường này.
3. Đang tìm helper `_board`, test intake ERP và hai hàm ảnh được brief nêu để
   viết test đỏ cho thẻ không bìa trước khi sửa mã.
4. Đã thêm bốn test intake cho Việc 1 và chạy trên mã cũ: **4 test, 2 fail**.
   - Không bìa + 4 ảnh: kỳ vọng 4 nhưng thực tế chỉ 3.
   - Không bìa + 1 ảnh: kỳ vọng 1 nhưng thực tế 0.
   - Hai ca có bìa (bìa riêng, bìa trùng ảnh thả) xanh trước khi sửa.
   - Có log cấp SKU bị sandbox chặn DNS; đây không phải assertion hỏng và
     không sửa để né môi trường. Đang sửa helper theo hướng không bìa thì
     không đoán ảnh sản phẩm.
5. Đã sửa `_erp_idea_product_image`: chỉ trả ảnh bìa nếu bìa khớp ảnh trên
   thẻ; không bìa trả rỗng để không ảnh nào bị loại. Chạy lại bốn test: **4
   test, OK**. Log SKU vẫn là DNS sandbox, assertion đều xanh. Đang chạy năm
   bộ test của Việc 1.
6. Bộ 1 lượt đầu của Việc 1 đã chạy **1.379 test trong 342,955 giây**; có hai
   error bind loopback do sandbox và hai fail assertion cũ còn giả định ảnh
   đầu là sản phẩm khi không bìa. Hai fail là kỳ vọng phải cập nhật theo đặc tả
   mới, không phải nới test: sẽ chốt đủ cả hai thẻ con và ảnh của chúng, rồi
   chạy lại năm bộ. Số 1.379 là **số hụt vì sandbox** đối với hai lỗi loopback,
   không phải tổng số thật ngoài sandbox.
7. Đã thay hai assertion cũ bằng các assertion đầy đủ theo đặc tả mới: hai
   ảnh không bìa phải tạo/queue hai thẻ con với đúng hai ảnh, còn thẻ cũ không
   ảnh vẫn skip riêng. Chạy sáu ca intake liên quan: **6 test, OK**. Log DNS
   SKU/ERP là sandbox, không phải lỗi assertion. Đang chạy lại đủ năm bộ của
   Việc 1 sau khi chốt test.
8. Bộ 1 của Việc 1 đã chạy lại: **1.379 bài trong 350,962 giây, 2 error**.
   Hai error đều là sandbox chặn `bind(127.0.0.1)`. Đây là **số hụt vì
   sandbox**, không được hiểu là tổng số thật ngoài sandbox; không có fail
   assertion nào. Đang chạy bốn bộ còn lại.
9. automation_center Python bị Node con chết `SIGABRT` sau **82 bài trong
   2,192 giây**. Đây là **số hụt 6 vì sandbox**, không phải kết quả của bộ:
   số thật ngoài sandbox do chủ nhân chạy là **88, OK**. Không sửa mã để né
   lỗi môi trường. Đang chạy Node độc lập.
10. Node độc lập của Việc 1 xanh: **198/198 pass trong 789,57425 ms**. Đang
    chạy bmad-init.
11. bmad-init của Việc 1 xanh: **35/35 pass trong 0,022 giây**. Đang chạy
    bmad-distillator bằng `pytest`.
12. Việc 1 đã chạy đủ năm bộ. bmad-distillator chạy đúng `pytest`: **33/33
    pass trong 0,08 giây**. Đang đọc brief Việc 2 trước khi sửa.
13. Đã đọc trọn `docs/giao-viec/codex-05-product-type.md`. Chỉ sửa đường dựng
    rule ở `service.py`: lời khai `task_meta(...).product` của thẻ con đứng
    trước lời khai thẻ cha, rồi mới đến các tên để suy đoán. Không đụng
    `flow_web/erp_meta.py` hoặc `tests/test_erp_meta.py` của chủ nhân. Đang
    tìm test rule card để viết ca đỏ.
14. Đã thêm ba test cho Việc 2 và chạy trên mã cũ: **3 test, 2 fail**.
    - `product_type` của thẻ cha chưa thắng tên `Idea Phương`.
    - `product_type` của thẻ con chưa thắng lời khai thẻ cha.
    - Không khai vẫn dùng fallback tên cũ và xanh trước khi sửa.
    Đang đặt hai lời khai `task_meta(...).product` lên trước đường suy đoán.
15. Đã đặt lời khai sản phẩm theo thứ tự thẻ nguồn → thẻ cha → tên suy đoán,
    không lọc lời khai qua `_erp_idea_subject_says_product`. Chạy lại: **3
    test, OK**. Quy tắc SKU không đổi: thẻ cha không được cấp SKU; thẻ con chỉ
    nhận mã khi sang *Đang làm*. Đang chạy đủ năm bộ cho Việc 2.
16. automation_center Python của Việc 2 chạy được **82 bài trong 2,118 giây**
    rồi Node con bị `SIGABRT`. Đây là **số hụt 6 vì sandbox**, không phải số
    thật của bộ; chủ nhân đã xác nhận chạy ngoài sandbox là **88, OK**. Không
    sửa mã để che lỗi môi trường. Đang chạy Node độc lập với đúng cờ và glob.
17. Node độc lập của Việc 2 xanh: **198/198 pass trong 1.151,190916 ms**.
    Đang chạy bmad-init, sau đó bmad-distillator bằng `pytest`.
18. bmad-init của Việc 2 xanh: **35/35 trong 0,016 giây**. Đang chạy
    bmad-distillator bằng `pytest` (không dùng `unittest discover`).
19. Việc 2 đã chạy đủ năm bộ; bmad-distillator chạy đúng `pytest`: **33/33
    pass trong 0,40 giây**. Đang đọc brief Việc 3 trước khi khảo sát mã.
20. Đã đọc trọn `docs/giao-viec/codex-03-du-an-chet.md`. Việc 3 sẽ kiểm URL
    cuối cùng ngay sau `goto`: `/404` hoặc `reason=project` phải dừng trước
    mọi thao tác soi/gắn nút, báo tiếng Việt có ID và không tự tạo/chọn dự án.
    Đang xác định các điểm điều hướng và test để viết hai ca đỏ.
21. Đã thêm hai test Việc 3 rồi chạy trên mã cũ: **2 error** vì hàm điều hướng
    hiện trả `None`, chưa thể trả `False` kèm lý do. Ca đỏ mô phỏng `goto`
    thành `https://flow.google.com/404?reason=project`; ca còn lại mô phỏng
    dự án sống. Đang sửa cửa điều hướng chung để trả trạng thái, rồi buộc các
    đường mở project dừng bằng cùng thông báo khi trạng thái là không hợp lệ.
22. Cửa điều hướng giờ trả `(False, chi tiết)` ngay khi URL cuối có `/404` hoặc
    `reason=project`; chi tiết nêu ID và câu Việt “không còn tồn tại”. Các
    đường mở project/client/login/Flow Agent chặn trạng thái này trước khi soi
    nút; không tự tạo hoặc chọn dự án. Hai ca đỏ đã xanh: **2 test, OK**.
    Đang chạy các ca Flow liên quan trước khi chạy năm bộ của Việc 3.
23. Đã chạy thêm **10 test điều hướng/client/Flow Agent liên quan, OK**. Một
    mock cũ được chỉnh để mô phỏng đúng hợp đồng trạng thái mới `(True, "")`;
    assertion không bị nới. Đang chạy đủ năm bộ của Việc 3.
24. Bộ 1 Việc 3 đã chạy **1.384 bài trong 267,467 giây, errors=2**. Cả hai là
    `bind(127.0.0.1)` bị sandbox chặn; đây là **số hụt vì sandbox**, không phải
    tổng số thật ngoài sandbox, và không có fail assertion. Đang chạy
    automation_center Python.
25. automation_center Python Việc 3 chạy được **82 bài trong 1,402 giây** rồi
    Node con `SIGABRT`. Đây là **số hụt 6 vì sandbox**; số thật ngoài sandbox
    chủ nhân đã xác nhận là **88, OK**. Không sửa mã để che lỗi môi trường.
    Đang chạy Node độc lập với đúng cờ/glob.
26. Node độc lập Việc 3 xanh: **198/198 pass trong 436,697334 ms**. Đang chạy
    bmad-init, rồi bmad-distillator đúng bằng `pytest`.
27. bmad-init Việc 3 xanh: **35/35 trong 0,010 giây**. Đang chạy
    bmad-distillator bằng `pytest`, không dùng `unittest discover`.
28. Việc 3 đã chạy đủ năm bộ; bmad-distillator chạy đúng `pytest`: **33/33
    pass trong 0,04 giây**. Đang kiểm tra diff cuối, cú pháp và phạm vi file.
29. Kiểm tra cuối xanh: `py_compile` cho `service.py` và hai file test, cùng
    `git diff --check`, đều không có lỗi. Chỉ thay đổi `flow_web/service.py`,
    file trong `tests/`, và file kết quả này của các việc hiện tại; các thay
    đổi sẵn có của chủ nhân ở `erp_meta` vẫn để nguyên.

## Kết quả test

### Việc 1 — đang chạy bốn bộ còn lại

1. `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
   - **1.379 bài đã chạy được, 350,962 giây, errors=2**.
   - **Số hụt vì sandbox**: hai bind loopback bị chặn, nên không phải tổng số
     thật ngoài sandbox.
2. `(cd automation_center && ../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')`
   - Sandbox chỉ chạy được **82 bài trong 2,192 giây** rồi Node con `SIGABRT`.
   - **Số hụt 6 vì sandbox**; tổng thật ngoài sandbox là **88, OK** theo số
     chủ nhân đã xác nhận. Không dùng 82 làm kết quả bộ.
3. `node --test --experimental-sqlite automation_center/tests/*.test.mjs`
   - **198 test, 198 pass, 0 fail, 789,57425 ms**.
4. `(cd _bmad/core/bmad-init/scripts && ../../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')`
   - **35 test, 0,022 giây, OK**.
5. `(cd _bmad/core/bmad-distillator/scripts && ../../../../.venv/bin/python -m pytest tests -q)`
   - **33 passed trong 0,08 giây**.

### Tổng kết Việc 1

- Không bìa: mọi ảnh thả đều thành thẻ con; không còn lấy ảnh cũ nhất làm ảnh
  sản phẩm và làm mất im lặng một ý tưởng.
- Có bìa: bìa vẫn thắng, dù bìa trùng một ảnh thả.
- Bộ 1 và automation_center Python có số hụt vì sandbox; Node/bmad xanh hoàn
  toàn. Không có mã nào được sửa để che lỗi môi trường.

### Việc 2 — đang chạy năm bộ

1. `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
   - **1.382 bài đã chạy được, 241,507 giây, errors=2**.
   - **Số hụt vì sandbox**: hai bind loopback bị chặn, nên không phải tổng số
     thật ngoài sandbox. Không có fail assertion.
2. Đang chạy: automation_center Python.
   - Sandbox chỉ chạy được **82 bài trong 2,118 giây** rồi Node con `SIGABRT`.
   - **Số hụt 6 vì sandbox**; tổng thật ngoài sandbox là **88, OK** theo số
     chủ nhân đã xác nhận. Không dùng 82 làm kết quả bộ.
3. `node --test --experimental-sqlite automation_center/tests/*.test.mjs`
   - **198 test, 198 pass, 0 fail, 1.151,190916 ms**.
4. `(cd _bmad/core/bmad-init/scripts && ../../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')`
   - **35 test, 0,016 giây, OK**.
5. `(cd _bmad/core/bmad-distillator/scripts && ../../../../.venv/bin/python -m pytest tests -q)`
   - **33 passed trong 0,40 giây**.

### Tổng kết Việc 2

- `product_type` được tin theo thứ tự lời khai của thẻ nguồn, rồi thẻ cha,
  cuối cùng mới suy đoán từ tên như trước.
- Không sửa `flow_web/erp_meta.py` hoặc `tests/test_erp_meta.py` của chủ nhân.
- Bộ 1 và automation_center Python có số hụt vì sandbox; Node/bmad xanh hoàn
  toàn. Không có mã nào được sửa để che lỗi môi trường.

### Việc 3 — đang chạy năm bộ

1. `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
   - **1.384 bài đã chạy được, 267,467 giây, errors=2**.
   - **Số hụt vì sandbox**: hai bind loopback bị chặn, nên không phải tổng số
     thật ngoài sandbox. Không có fail assertion.
2. `(cd automation_center && ../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')`
   - Sandbox chỉ chạy được **82 bài trong 1,402 giây** rồi Node con `SIGABRT`.
   - **Số hụt 6 vì sandbox**; tổng thật ngoài sandbox là **88, OK** theo số
     chủ nhân đã xác nhận. Không dùng 82 làm kết quả bộ.
3. `node --test --experimental-sqlite automation_center/tests/*.test.mjs`
   - **198 test, 198 pass, 0 fail, 436,697334 ms**.
4. `(cd _bmad/core/bmad-init/scripts && ../../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')`
   - **35 test, 0,010 giây, OK**.
5. `(cd _bmad/core/bmad-distillator/scripts && ../../../../.venv/bin/python -m pytest tests -q)`
   - **33 passed trong 0,04 giây**.

### Tổng kết Việc 3

- URL cuối `/404` hoặc `reason=project` được nhận diện ngay ở cửa điều hướng;
  hệ thống dừng với: `Dự án Flow <id> không còn tồn tại (trang trả 404). Hãy
  chọn lại dự án trong phần cấu hình.`
- Không có đường nào tự tạo hoặc tự chọn dự án thay người dùng; API Flow vẫn
  giữ host `labs.google`.
- Bộ 1 và automation_center Python có số hụt vì sandbox; Node/bmad xanh hoàn
  toàn. Không có mã nào được sửa để che lỗi môi trường.

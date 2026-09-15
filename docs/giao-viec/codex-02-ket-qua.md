# Kết quả Codex #02 — Google Flow đổi nhà

## Tiến độ

1. Đã đọc trọn `docs/giao-viec/codex-02-flow-doi-nha.md` trước khi khảo sát
   hoặc sửa mã. Dữ liệu DOM và host trong brief được coi là số liệu thật.
2. Đã ghi nhận: không sửa hai lỗi test do sandbox (`bind 127.0.0.1` và Node
   `SIGABRT`) mà chủ nhân đã xác nhận là lỗi môi trường.
3. Đang grep toàn bộ đường dẫn Flow và điểm khởi tạo `flow-py`, sau đó sẽ viết
   test đỏ cho hai nhánh an toàn locator và host điều hướng trước khi cài đặt.
4. Đã grep xong. Chỉ thay URL điều hướng trong `flow_web/schemas.py` và
   `flow_web/service.py`; giữ nguyên các URL API `labs.google` của media và
   `Referer`/`Origin`. Nhánh CDP của `FlowClient.create` sẽ được đưa qua client
   dựng từ phía repo để không ghé host cũ trước khi ghi đè URL project.
5. Đã viết/chỉnh tám test trước khi sửa và chạy riêng: **8 test, 6 lỗi, 2
   error**. Các lỗi xác nhận đúng điểm cần đổi: host điều hướng cũ, chưa có
   cấu hình/chấp nhận hai host, locator fallback toàn trang, và CDP còn gọi
   factory `flow-py`.
6. Đã cài đặt xong và chạy lại tám test: **8 test, 0 lỗi**; biên dịch Python
   và `git diff --check` cùng xanh.
   - `FLOW_NAVIGATION_BASE_URL` là cấu hình duy nhất, mặc định
     `https://flow.google.com`; đặt biến này về route `labs.google` để lùi.
   - Chỉ URL điều hướng đổi host. URL API media, `Referer` và `Origin`
     `labs.google` không đổi.
   - Ghi đè hằng/chuyển hướng `flow-py` từ phía repo; không sửa `.venv`.
   - Nhánh CDP dựng client qua code repo, tránh `FlowClient.create` mở host cũ.
   - Locator chỉ fallback trong vùng prompt với nút thêm/SVG, loại nhãn nguy
     hiểm; chẩn đoán đổ về top-20 toàn trang nếu không có gì gần prompt.
7. Đã chạy xong bộ 1 sau khi cô lập file registry `flow-py` trong test ERP để
   test không ghi vào profile thật: **1.370 test trong 337,729 giây; 2 lỗi**.
   Cả hai đều là `PermissionError: [Errno 1] Operation not permitted` khi test
   bind `127.0.0.1`, đúng lỗi sandbox đã được chủ nhân xác nhận, không phải hồi
   quy mã. Đang chạy bộ automation_center Python.
8. Bộ automation_center Python xong: **82 test trong 1,653 giây; 1 error**.
   `test_scope_parity` gọi Node con và Node chết `SIGABRT`; giữ nguyên theo
   chỉ đạo. Đang chạy bộ Node độc lập với cờ và glob bắt buộc.
9. Bộ Node độc lập xong: **198/198 pass trong 774,5315 ms**. Đang chạy
   bmad-init.
10. bmad-init xong: **35/35 pass trong 0,011 giây**. Đang chạy
    bmad-distillator bằng `pytest`.
11. Đã chạy đủ năm bộ. bmad-distillator chạy đúng `pytest`: **33/33 pass
    trong 0,07 giây**. Đang kiểm tra diff, biên dịch và xác nhận các endpoint
    API `labs.google` không bị đổi.
12. Rà flow-py phát hiện thêm URL project lưu trong instance API có thể khiến
    luồng lấy Bearer quay về host cũ. Đã viết test đỏ rồi xanh cho hai điểm:
    URL project của API instance được lấy từ cấu hình repo, và lookup Bearer
    không rời `flow.google.com` khi đang ở đúng editor. Vì thay đổi này đến
    sau lượt năm bộ đầu, đang chạy lại đủ năm bộ để số cuối cùng phản ánh bản
    chốt. API media cùng `Referer`/`Origin` `labs.google` vẫn giữ nguyên.
13. Bộ 1 của lượt chốt xong: **1.372 test trong 273,640 giây; 2 error**.
    Đó vẫn là hai `PermissionError` bind `127.0.0.1` do sandbox; không có lỗi
    hồi quy. Đang chạy automation_center Python của lượt chốt.
14. automation_center Python của lượt chốt xong: **82 test trong 1,860 giây;
    1 error**. Node con trong `test_scope_parity` nhận `SIGABRT`, đúng lỗi môi
    trường đã biết. Đang chạy Node độc lập với đúng cờ/glob.
15. Node độc lập của lượt chốt xanh: **198/198 pass trong 609,223208 ms**.
    Đang chạy bmad-init.
16. bmad-init của lượt chốt xanh: **35/35 pass trong 0,015 giây**. Đang chạy
    bmad-distillator bằng `pytest`.
17. Đủ năm bộ của lượt chốt đã xong. bmad-distillator chạy bằng đúng `pytest`:
    **33/33 pass trong 0,05 giây**.
18. `git diff --check` và biên dịch bốn file Python đã sửa đều xanh. Xác nhận
    lại các URL `media.getMediaUrlRedirect` vẫn là `https://labs.google`; không
    có sửa đổi nào trong `.venv`.

## Kết quả test

1. `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
   - **1.372 test, 273,640 giây, FAILED (errors=2)**.
   - Hai error `bind("127.0.0.1", 0)` bị sandbox chặn; không sửa mã theo
     chỉ đạo của chủ nhân.
2. `(cd automation_center && ../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')`
   - **82 test, 1,860 giây, FAILED (errors=1)**.
   - `test_scope_parity` gọi Node con, nhận `SIGABRT`; không sửa mã theo chỉ
     đạo của chủ nhân.
3. `node --test --experimental-sqlite automation_center/tests/*.test.mjs`
   - **198 test, 198 pass, 0 fail, 609,223208 ms**.
4. `(cd _bmad/core/bmad-init/scripts && ../../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')`
   - **35 test, 0,015 giây, OK**.
5. `(cd _bmad/core/bmad-distillator/scripts && ../../../../.venv/bin/python -m pytest tests -q)`
   - **33 passed trong 0,05 giây**.

## Tổng kết

- Đã chạy đủ năm bộ theo đúng lệnh trong `CLAUDE.md` trên bản chốt.
- Hai error ở bộ 1 là sandbox chặn bind loopback; một error ở automation Python
  là Node con `SIGABRT`. Đây là lỗi môi trường đã được chủ nhân xác nhận; không
  có thay đổi mã để che hoặc né chúng.
- Ba bộ còn lại xanh hoàn toàn: Node **198/198**, bmad-init **35/35**,
  bmad-distillator/pytest **33/33**.

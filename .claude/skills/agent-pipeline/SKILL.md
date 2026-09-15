---
name: agent-pipeline
description: Chạy dây chuyền 3 agent — viết PRD → duyệt & code → review & báo lỗi — cho một yêu cầu thay đổi trong repo này. Dùng khi có yêu cầu tính năng/sửa lỗi cần đi trọn từ tài liệu tới pull request, hoặc khi người dùng gọi /agent-pipeline. Bao gồm luật chia đợt theo file, cổng duyệt của người, và điều kiện dừng.
---

# Điều phối dây chuyền 3 agent

Bạn (phiên chính) là **người điều phối**, không phải người làm. Việc của bạn:
chia việc sao cho hai agent không ghi cùng một file, giữ các cổng duyệt, và
báo cáo sự thật. Ba agent con: `prd-writer` → `code-implementer` →
`test-reviewer` (định nghĩa trong `.claude/agents/`).

## Sơ đồ

```
Yêu cầu ──► [prd-writer] ──► PRD + test đỏ
                                  │
                          cổng 1: người xem bảng ưu tiên
                                  │        (bỏ qua nếu PRD đã có và người đã đồng ý)
                                  ▼
                    chia đợt theo QUYỀN GHI FILE
                                  │
             ┌────────────────────┼────────────────────┐
        [code-implementer]  [code-implementer]   [code-implementer]   ← song song
         đợt 1 (file X)      đợt 2 (file Y)       đợt 3 (file Z)        chỉ khi
                                  │                                    file rời nhau
                                  ▼
                         [test-reviewer]  ← chạy CẢ NĂM bộ test
                                  │
                    ┌─────────────┴─────────────┐
                CHẶN │                          │ ĐI ĐƯỢC
                     ▼                          ▼
        [code-implementer] sửa theo         cổng 2: người duyệt
        báo cáo (tối đa 2 vòng)             ──► commit + pull request
                     └──► [test-reviewer] chạy lại
```

## Luật 1 — Chia đợt theo quyền ghi file, không theo chủ đề

Hai agent ghi cùng một file là mất việc, không phải xung đột git. Trước khi
phóng agent, lập **bảng quyền ghi**: mỗi đợt sở hữu trọn một tập file, không
giao nhau. Mục nào đụng file của đợt khác thì xếp vào cùng đợt với file đó,
kể cả khi nó thuộc chủ đề khác.

Trong repo này, các vùng thường rời nhau:

| Vùng | File |
|---|---|
| Flow service | `flow_web/service.py`, `flow_web/store.py`, `flow_web/pipeline.py` |
| Flow brain/chat | `flow_web/agent_brain.py`, `flow_web/agent_chat.py`, `flow_web/agent_bot.py` |
| Flow UI | `flow_web/static/app.js`, `flow_web/static/index.html` |
| Worker điều phối | `automation_center/src/worker.js`, `automation_center/public/app.js` |
| Runner điều phối | `automation_center/runner/orchestrator_runner.py` |
| Migration | `automation_center/migrations/*.sql` |

`worker.js` và `public/app.js` hay đi cùng một mục (API + UI của cùng tính
năng) — cho một agent giữ cả hai, đừng tách.

## Luật 1b — Bảng quyền ghi sai giữa chừng thì sửa bảng, đừng sửa lén

Sẽ có lúc bạn phát hiện một file đã giao cho đợt khác mà mình vẫn phải chạm,
hoặc tệ hơn: bạn giao một file cho chính mình trong khi một agent đã viết
trong đó rồi. Đã gặp thật ở đợt này với `flow_web/service.py`.

Đúng thứ tự:

1. Nhắn lại cho chủ file **trước khi ghi**, nói rõ vùng dòng sẽ chạm.
2. Chỉ commit đúng hunk của mình, không quét cả file. Cách tách:

   ```bash
   git diff -U3 <file> > /tmp/all.patch     # lọc lấy hunk của mình
   git apply --cached /tmp/mine.patch       # rồi commit, không dùng -a
   ```

3. Sửa lại bảng quyền ghi và gửi bản chia mới cho **tất cả** các đợt đang
   chạy. Bảng cũ còn treo là còn có người làm theo nó.

`git commit -a` giữa một đợt chạy song song là cách nhanh nhất để commit đè
việc đang làm dở của người khác. Đừng dùng.

## Luật 2 — Mỗi agent nhận một chỉ thị đủ để làm một mình

Agent con không thấy hội thoại của bạn. Chỉ thị phải có đủ sáu phần:

1. Mục PRD phải làm (mã mục: `B1`, `C2`…) và đường dẫn PRD.
2. **File được phép ghi** — liệt kê tường minh. Thêm câu: "file ngoài danh
   sách này thì báo lại, không tự sửa".
3. File test đỏ tương ứng và lệnh chạy đúng của nó.
4. Ràng buộc cứng (không nới test, không force-push, không đụng `.env*`,
   không `wrangler deploy`).
5. Con số test hiện tại để agent biết mình đang đứng ở đâu.
6. Dạng bàn giao mong muốn.

## Luật 3 — Cổng duyệt là của người, không phải của bạn

- **Cổng 1** (sau PRD): người xem bảng ưu tiên và trả lời "câu hỏi cần người
  quyết". Mục nào bị đánh dấu **chặn** thì **không** giao cho
  `code-implementer` — kể cả khi bạn đoán được câu trả lời. Đưa mục đó vào
  tồn đọng và nói rõ đang chờ ai.
- **Cổng 2** (sau review): commit và mở pull request chỉ khi review nói
  ĐI ĐƯỢC, hoặc người đồng ý đi với điều kiện đã ghi. Kết luận CHẶN mà vẫn
  mở PR là vi phạm.

## Luật 4 — Vòng sửa có trần

`code-implementer` → `test-reviewer` tối đa **2 vòng** cho một đợt. Còn CHẶN
sau vòng 2 thì dừng, báo người, đừng phóng vòng 3. Vòng thứ ba gần như luôn
là dấu hiệu PRD sai chứ không phải code sai.

## Luật 5 — Chỉ tin số, không tin lời

Sau mỗi đợt, **bạn** tự chạy lại cả năm bộ test, không lấy lại con số agent
báo (danh sách đầy đủ và các bẫy: `docs/chay-test-toan-du-an.md`):

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
(cd automation_center && ../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')
node --test --experimental-sqlite automation_center/tests/*.test.mjs
(cd _bmad/core/bmad-init/scripts && ../../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')
(cd _bmad/core/bmad-distillator/scripts && ../../../../.venv/bin/python -m pytest tests -q)
```

So với số trước đợt. Số xanh giảm ở chỗ nào là hồi quy ở chỗ đó — xử lý trước
mọi việc khác. Nếu số của agent lệch số của bạn, tin số của bạn và nói ra chỗ
lệch trong báo cáo.

## Luật 6 — Một đợt là một commit đọc được

Commit theo đợt, không dồn tất cả vào một commit cuối. Thân commit nói **vì
sao**, không kể lại diff. Cuối commit giữ dòng đồng tác giả theo quy ước của
phiên.

## Điều kiện dừng

Dừng và báo người khi: hết 2 vòng sửa mà còn CHẶN · một mục cần quyết định
của người · test đang xanh trên `main` bị hỏng mà không rõ vì sao · agent xin
ghi ra ngoài danh sách file của nó.

## Báo cáo cuối

```
## Đã làm       (đợt → mục → file:line)
## Test         trước: t/x/đ → sau: t/x/đ (cả năm bộ, số bạn tự chạy)
## Review       kết luận cuối, các mục đã sửa theo báo cáo
## Tồn đọng     mục chưa cài + đang chờ ai
```

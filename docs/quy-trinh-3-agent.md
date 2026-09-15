# Quy trình 3 agent — từ yêu cầu tới pull request

Tài liệu này nói **cách làm việc**, không nói cách cài đặt. Ai cũng đọc được:
người gửi yêu cầu, người duyệt, người vận hành máy trung tâm.

## 1. Vì sao ba agent, không phải một

Một agent làm cả ba việc — viết yêu cầu, sửa code, tự nghiệm thu — thì phần
nghiệm thu vô giá trị: nó chấm bài của chính nó. Ba vai tách ra, mỗi vai có
**quyền ghi file khác nhau**, nên vai sau bắt được lỗi của vai trước.

| Vai | Agent | Được ghi | Không được |
|---|---|---|---|
| Viết yêu cầu | `prd-writer` | `tasks/*.md`, `docs/*.md`, file test | code cài đặt |
| Duyệt và làm | `code-implementer` | code, theo danh sách file được giao | sửa test cho xanh |
| Soát và báo | `test-reviewer` | `docs/review-*.md` | code cài đặt |

### Bảng trên được giữ bằng gì — nói thẳng, vì chỗ này dễ tưởng bở

Danh sách công cụ trong `.claude/agents/*.md` có giữ một phần: `code-implementer`
là vai duy nhất có `NotebookEdit`, `test-reviewer` không có `Edit`. Nhưng **cả
ba vai đều có `Bash`**, và `Bash` ghi được mọi file. Repo cũng không có
`.claude/settings.json` lẫn hook nào chặn đường ghi.

Nên phải nói cho đúng: **cột "Không được" ở bảng trên là luật viết trong lời
nhắc, không phải hàng rào kỹ thuật.** Một vai bị thuyết phục vẫn ghi được ra
ngoài phần của nó. Ai đọc tài liệu này rồi tưởng có hàng rào thật sẽ bỏ qua
đúng cái cần canh.

Ba thứ thật sự đỡ, và cả ba đều là *phát hiện sau*, không phải *chặn trước*:

1. **Vai soát chạy lại test từ worktree sạch tại commit**, không tin commit
   message và không đo ở cây làm việc. Một lượt nới test cho xanh sẽ hiện ra ở
   đây — lượt soát trên chính nhánh này đã bắt được thật.
2. **Hai cổng của người** ở §2. Cổng cũng là chữ — một agent *có thể* đi
   qua mà không hỏi. Chỗ đỡ là bỏ qua cổng thì thấy được: không có câu trả
   lời của người trong lịch sử, không có `docs/review-*.md` cho đợt ấy. Rẻ
   để kiểm, nên đáng kiểm mỗi lần.
3. **Git.** Mỗi đợt một commit đọc được, không rewrite, không force-push —
   nên "ai ghi cái gì" luôn tra lại được.

Muốn thành hàng rào thật thì phải thêm `permissions.deny` hoặc một `PreToolUse`
hook chặn theo đường dẫn. Đó là việc chưa làm, cố ý ghi ra đây để lần sau có
người làm chứ không phải để lờ đi. Nguyên tắc tách vai thì vẫn đúng như Agent
điều phối trong `automation_center`
(`automation_center/docs/prd-agent-dieu-phoi.md` §1); chỗ khác nhau là bên ấy
chốt bằng code chạy được, còn bên này mới chốt bằng chữ.

## 2. Luồng đầy đủ

```
Yêu cầu bằng tiếng Việt
        │
        ▼
[prd-writer] ──► tasks/prd-<tên>.md + test đỏ
        │
   ╔════╧═════════════════════════════════════════╗
   ║ CỔNG 1 — người xem bảng ưu tiên và trả lời    ║
   ║ "câu hỏi cần người quyết"                     ║
   ╚════╤═════════════════════════════════════════╝
        │  mục bị đánh dấu "chặn" → không giao, đưa vào tồn đọng
        ▼
Điều phối chia đợt theo QUYỀN GHI FILE (không theo chủ đề)
        │
        ├──► [code-implementer] đợt 1 ─┐
        ├──► [code-implementer] đợt 2 ─┤ song song, file rời nhau
        └──► [code-implementer] đợt 3 ─┘
                     │
                     ▼
           [test-reviewer] chạy CẢ NĂM bộ test + soát diff
                     │
        ┌────────────┴────────────┐
      CHẶN                     ĐI ĐƯỢC
        │                         │
   sửa theo báo cáo          ╔════╧═══════════════════════╗
   (tối đa 2 vòng)           ║ CỔNG 2 — người duyệt diff  ║
        │                    ╚════╤═══════════════════════╝
        └──► review lại              │
                                     ▼
                          commit theo đợt + pull request
```

Chi tiết luật điều phối (chia đợt, trần vòng sửa, điều kiện dừng) nằm ở
`.claude/skills/agent-pipeline/SKILL.md`. Gọi bằng `/agent-pipeline`.

## 3. Bốn luật giữ cho nó không hỏng

**Luật quyền ghi file.** Hai agent ghi cùng một file là mất việc, không phải
xung đột git — agent sau đọc file lúc agent trước chưa ghi xong. Vì thế mỗi
đợt sở hữu trọn một tập file. Mục nào đụng file của đợt khác thì xếp vào cùng
đợt với file đó, **kể cả khi nó thuộc chủ đề khác**.

**Luật không nới test.** Test đỏ thì sửa code. Agent nào tin test sai thì
"trả lại" mục đó kèm lý do — nó không có quyền tự sửa test rồi báo là xong.
`test-reviewer` soát riêng `git diff main...HEAD -- tests automation_center/tests`
để bắt đúng chuyện này; test bị làm yếu đi là phát hiện **mức chặn**.

**Luật chỉ tin số.** Người điều phối tự chạy lại cả năm bộ test sau mỗi đợt,
không lấy lại con số agent báo. Số agent lệch số mình thì tin số mình và ghi
chỗ lệch vào báo cáo.

**Luật cổng là của người.** Agent không tự trả lời "câu hỏi cần người quyết".
Mục chờ quyết định thì nằm trong tồn đọng, nói rõ đang chờ ai — ví dụ danh
sách tác giả được ra lệnh cho bot ERP là quyết định của chủ bảng, không phải
của agent.

## 4. Năm bộ test — chạy cả năm, đừng chỉ chạy một

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
(cd automation_center && ../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')
node --test --experimental-sqlite automation_center/tests/*.test.mjs
(cd _bmad/core/bmad-init/scripts && ../../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')
(cd _bmad/core/bmad-distillator/scripts && ../../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')
```

Bẫy, số nền và lý do bộ `bmad-distillator` đỏ vì môi trường chứ không phải vì
code: `docs/chay-test-toan-du-an.md`.

Đọc bài đỏ thì phân loại trước khi kết luận: `LỖI CODE` · `CHƯA CÀI` (test TDD
của mục chưa tới lượt) · `TEST SAI` · `MÔI TRƯỜNG`. Bài đỏ vì thiếu thư viện
không phải lỗi code; bài đỏ vì thiếu cờ `--experimental-sqlite` không phải
thiếu module.

## 5. Quy trình này khớp vào Agent điều phối thế nào

Agent điều phối trong `automation_center` đã có sẵn một dây chuyền cùng hình
dạng, chạy trên máy trung tâm cho **nhân viên không dùng dòng lệnh**:

| Bước quy trình 3 agent | Trạng thái trong Agent điều phối |
|---|---|
| Yêu cầu bằng tiếng Việt | `queued` (Worker đóng băng phạm vi vào `scope_json`) |
| `code-implementer` làm | `planning` (runner claim, sửa file, chạy test, commit lên `agent/<id>`) |
| `test-reviewer` + CỔNG 2 | `awaiting_approval` (người có `code_approve` duyệt) |
| commit + pull request | `approved` → `applied` (merge vào nhánh base trên máy trung tâm) |
| mục bị trả lại | `failed` / `rejected` — không ai duyệt được |

Hai điều **không** giống nhau, và đây là chỗ hay bị hiểu sai:

1. Agent điều phối `applied` nghĩa là **đã merge vào bản sao repo trên máy
   trung tâm**, không phải đã deploy. Đưa code vào service đang chạy vẫn là
   bước tay (`automation_center/docs/prd-agent-dieu-phoi.md` §2 non-goal 1).
2. Agent điều phối **không tự viết PRD**. Yêu cầu của nhân viên thay chỗ PRD
   cho những thay đổi nhỏ. Thay đổi lớn thì vẫn nên đi qua `prd-writer` trước,
   rồi mới giao cho Agent điều phối từng mục nhỏ.

Hàng rào của Agent điều phối là **ba lớp độc lập** (vai trò, phạm vi glob +
trần file/dòng, danh sách bảo vệ toàn cục) và nó nằm trong code Worker/runner,
không nằm trong lời nhắc gửi cho model. Quy trình 3 agent ở trên là lớp thứ
tư, dành cho người có dòng lệnh — nó không thay thế ba lớp kia.

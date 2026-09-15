# Hướng dẫn cho Claude Code trong repo này

Repo có hai hệ thống, hai môi trường chạy, một bộ luật chung.

| Vùng | Là gì | Chạy ở đâu |
|---|---|---|
| `flow_web/` | UI + service tự động hoá Google Flow (FastAPI, Python) | máy local / worker Windows |
| `automation_center/` | Automation Center: Worker Cloudflare (`src/worker.js`) + runner trên máy trung tâm (`runner/*.py`) | Cloudflare + PC `100.75.125.80` |
| `tasks/`, `docs/`, `automation_center/docs/` | PRD và runbook — đọc trước khi sửa | — |

`flow_web/service.py` dài hơn 20.000 dòng: **grep tới đúng chỗ**, đừng đọc cả file.

## Lệnh test — có **năm** bộ, đừng chỉ chạy một

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
(cd automation_center && ../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')
node --test --experimental-sqlite automation_center/tests/*.test.mjs
(cd _bmad/core/bmad-init/scripts && ../../../../.venv/bin/python -m unittest discover -s tests -p 'test_*.py')
(cd _bmad/core/bmad-distillator/scripts && ../../../../.venv/bin/python -m pytest tests -q)
```

Bẫy và số nền: `docs/chay-test-toan-du-an.md`. Lệnh node ở trên phải giữ
nguyên cả cờ lẫn glob: `node --test --experimental-sqlite` trỏ vào **đường
dẫn thư mục** vẫn hỏng trên máy này — phải là glob `*.test.mjs`.

- Bốn bộ đầu dùng `unittest`. Bộ `bmad-distillator` dùng **pytest** thật
  (`@pytest.fixture`): `unittest discover` gom được **0 bài** rồi in `OK` —
  xanh mà chạy rỗng. Chạy đúng bằng `pytest` thì ra 33 bài.
- Thiếu `--experimental-sqlite` là **thiếu cờ**, không phải thiếu module.
- `.venv` dựng bằng: `python3.11 -m venv .venv` rồi
  `.venv/bin/python -m pip install -e '.[dev]'` (kéo cả `flow-py` từ GitHub).
  Thiếu `flow`/`cv2` thì bài đỏ là **lỗi môi trường**, không phải lỗi code.

## Luật cứng

1. **Không nới lỏng test để cho xanh.** Assertion đỏ thì sửa code, hoặc dừng
   lại hỏi. Xoá/`skip`/hạ con số trong test là hỏng cả lượt.
2. Không rewrite history, không force-push. Nhánh mới tách từ `main`, kết thúc
   bằng pull request.
3. Không sửa, không commit: `.env.local`, `automation_center/.dev.vars`,
   `automation_center/runner/*.env`, `data/state.json*`.
4. Không `wrangler deploy`, không ghi lên D1 production.
5. File phân quyền của Agent điều phối (`automation_center/src/worker.js`,
   `migrations/`, `runner/`, `scripts/`) nằm trong `PROTECTED_GLOBS` — sửa
   được bằng tay, nhưng agent điều phối thì không. Đừng làm thay đổi nào khiến
   nó tự nới được quyền của chính nó.
6. Tài liệu và chú thích: tiếng Việt, câu ngắn, theo giọng file xung quanh.
7. **Xong một đợt là đẩy lên GitHub ngay, không đợi ai hỏi.** Agent làm xong
   phần việc được giao thì commit rồi `git push -u origin <nhánh>` — kể cả khi
   chưa mở PR, kể cả khi đang làm trong worktree riêng (`git worktree list` để
   biết mình đứng ở đâu; push nhánh của chính worktree đó). Push xong thì báo
   lại tên nhánh và link so sánh. Nhánh nằm im trên máy dev là việc không ai
   nhìn thấy — người đặt việc phải nắm được ngay khi nó xong, không phải chờ
   tới lúc mở PR. Vẫn giữ điều 2: không rewrite history, không force-push.
8. Chỉ đẩy lên `origin` (`ph56jk/agenthavi`). Remote `pub`
   (`ph56jk/flow-v2`) là chỗ máy tạo ảnh `DESKTOP-DPTR5BH` kéo code về chạy
   thật — đẩy lên đó là đổi code đang chạy sản xuất, phải có người nói rõ mới
   được làm.

## Dây chuyền 3 agent

Ba agent trong `.claude/agents/`, cách điều phối trong
`.claude/skills/agent-pipeline/SKILL.md` (gọi `/agent-pipeline`):

| Agent | Việc | Được ghi |
|---|---|---|
| `prd-writer` | viết PRD + test đỏ | `tasks/*.md`, `docs/*.md`, file test |
| `code-implementer` | duyệt PRD rồi cài đặt TDD | code, theo danh sách file được giao |
| `test-reviewer` | review diff + chạy cả năm bộ test + báo lỗi | `docs/review-*.md` |

Luật chia việc: **hai agent không bao giờ ghi cùng một file**. Các vùng rời
nhau: `flow_web/service.py`+`store.py`+`schemas.py` · `flow_web/agent_*.py` ·
`flow_web/static/app.js` · `automation_center/src/worker.js`+`public/app.js` ·
`automation_center/runner/orchestrator_runner.py`.

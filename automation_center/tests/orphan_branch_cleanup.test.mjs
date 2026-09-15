// B3 — nhánh agent/<id> mồ côi phải được dọn.
//
//   /Users/admin/.local/node/bin/node --test --experimental-sqlite automation_center/tests/orphan_branch_cleanup.test.mjs
//
// PRD: tasks/prd-agent-improvements.md §B3.  **Mọi bài ở đây đang ĐỎ và phải đỏ**
// trừ hai bài canh chừng ở cuối.
//
// cleanup_branch được gọi ở sáu lối ra của handle_request, nhưng có bốn đường
// không đi qua chỗ nào trong sáu chỗ đó:
//
//   1. merge hỏng lúc apply (orchestrator_runner.py:1256-1260) — chỉ
//      merge --abort rồi checkout, không branch -D;
//   2. huỷ/từ chối muộn sau khi đã báo awaiting_approval: vòng lặp chính chỉ
//      hỏi /code/approved và /code/claim, không bao giờ biết về cancelled;
//   3. huỷ trong lúc planning: Worker trả {ok:true, idempotent:true} KHÔNG kèm
//      cờ blocked, nên nhánh lệnh dọn ở :1237 không kích hoạt;
//   4. yêu cầu bị watchdog đóng — chuyện xảy ra hoàn toàn phía Worker.
//
// Hậu quả đã được ghi ngay trong code (:1261-1265): một yêu cầu sau trùng 12
// ký tự đầu của id sẽ checkout -B ĐÈ LÊN nhánh cũ, im lặng.
import test, { describe } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import worker from "../src/worker.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const MIGRATIONS = join(HERE, "..", "migrations");
const RUNNER_SOURCE = readFileSync(new URL("../runner/orchestrator_runner.py", import.meta.url), "utf8");
const SECRET = "runner-secret-cho-test";
const OWNER = "chu@havigroup.llc";

function d1(db) {
  return {
    prepare(sql) {
      const statement = db.prepare(sql);
      let values = [];
      const api = {
        bind(...bound) { values = bound; return api; },
        async first() { return statement.get(...values) ?? null; },
        async all() { return { results: statement.all(...values) }; },
        async run() {
          const result = statement.run(...values);
          return { meta: { changes: Number(result.changes), last_row_id: Number(result.lastInsertRowid) } };
        },
      };
      return api;
    },
  };
}

// Một hàng cho mỗi trạng thái đáng quan tâm, tên id nói luôn trạng thái để
// câu lỗi đọc được mà không phải tra ngược.
const STATUSES = [
  "queued", "planning", "awaiting_approval", "approved", "applying",
  "applied", "answered", "failed", "rejected", "cancelled", "bot_done",
];
const TERMINAL = ["applied", "answered", "failed", "rejected", "cancelled", "bot_done"];

function fresh() {
  const db = new DatabaseSync(":memory:");
  for (const file of readdirSync(MIGRATIONS).filter((name) => name.endsWith(".sql")).sort()) {
    db.exec(readFileSync(join(MIGRATIONS, file), "utf8"));
  }
  db.exec(`
    INSERT INTO users (email, display_name, global_role) VALUES ('${OWNER}', 'Chu', 'owner');
    INSERT INTO dashboards (id, slug, name, status, created_by)
      VALUES ('dash', 'dash', 'Dashboard thử', 'active', '${OWNER}');
    INSERT INTO runners (runner_key, label, status, last_seen_at)
      VALUES ('orchestrator-runner', 'Trung tâm', 'online', '${new Date().toISOString()}');
    INSERT INTO agent_threads (id, dashboard_id, title, created_by)
      VALUES ('thread', 'dash', 'Luồng thử', '${OWNER}');
  `);
  for (const status of STATUSES) {
    db.exec(`INSERT INTO code_change_requests
      (id, dashboard_id, thread_id, runner_key, requested_by, requested_role, instruction, status)
      VALUES ('req-${status}', 'dash', 'thread', 'orchestrator-runner', '${OWNER}', 'owner', 'Sửa giúp nhãn nút', '${status}')`);
  }
  return { db, env: { DB: d1(db), RUNNER_SHARED_SECRET: SECRET } };
}

const askFinished = (ids) => worker.fetch(
  new Request("https://x/api/runner/code/finished", {
    method: "POST",
    headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
    body: JSON.stringify({ runner_key: "orchestrator-runner", ids }),
  }),
  null,
);

describe("runner hỏi được yêu cầu nào đã kết thúc", () => {
  test("trả đúng những id ở trạng thái cuối", async () => {
    const { db, env } = fresh();
    const response = await worker.fetch(
      new Request("https://x/api/runner/code/finished", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: "orchestrator-runner", ids: STATUSES.map((s) => `req-${s}`) }),
      }),
      env,
    );
    // Đọc thân MỘT lần. Đối số thông báo của assert.equal được tính trước,
    // không phải khi assert hỏng, nên `await response.text()` ở đó luôn nuốt
    // thân — và `response.json()` ngay dưới nổ "Body has already been read"
    // dù Worker trả đúng. Bài này vì thế đỏ bằng mọi giá, không đo được gì.
    // Vị từ giữ nguyên từng chữ; chỗ sửa chỉ là đọc một lần rồi dùng lại.
    const raw = await response.text();
    assert.equal(response.status, 200, raw);
    const body = JSON.parse(raw);
    assert.ok(Array.isArray(body.finished), "B3.2: phải trả mảng finished");
    assert.deepEqual(
      body.finished.map((row) => row.id).sort(),
      TERMINAL.map((status) => `req-${status}`).sort(),
    );
    db.close();
  });

  // Đây là ca số 2 và số 4 trong danh sách trên: hai đường mà runner hôm nay
  // không có cách nào biết được.
  test("yêu cầu bị huỷ và yêu cầu bị watchdog đóng đều lọt vào danh sách", async () => {
    const { db, env } = fresh();
    const response = await worker.fetch(
      new Request("https://x/api/runner/code/finished", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: "orchestrator-runner", ids: ["req-cancelled", "req-rejected", "req-failed"] }),
      }),
      env,
    );
    const body = await response.json();
    const byId = new Map(body.finished.map((row) => [row.id, row.status]));
    assert.equal(byId.get("req-cancelled"), "cancelled");
    assert.equal(byId.get("req-rejected"), "rejected");
    assert.equal(byId.get("req-failed"), "failed");
    db.close();
  });

  // Không được đánh đổi: dọn nhầm một nhánh đang chạy thì mất cả lượt việc.
  test("yêu cầu còn sống KHÔNG bị báo là đã kết thúc", async () => {
    const { db, env } = fresh();
    const response = await worker.fetch(
      new Request("https://x/api/runner/code/finished", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: "orchestrator-runner", ids: ["req-planning", "req-awaiting_approval", "req-approved", "req-applying"] }),
      }),
      env,
    );
    assert.deepEqual((await response.json()).finished, []);
    db.close();
  });

  test("id của runner khác không trả lời, kể cả khi đã kết thúc", async () => {
    const { db, env } = fresh();
    db.exec(`UPDATE code_change_requests SET runner_key = 'runner-khac' WHERE id = 'req-cancelled'`);
    const response = await worker.fetch(
      new Request("https://x/api/runner/code/finished", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: "orchestrator-runner", ids: ["req-cancelled"] }),
      }),
      env,
    );
    assert.deepEqual((await response.json()).finished, []);
    db.close();
  });

  test("không có secret thì không hỏi được", async () => {
    const { db, env } = fresh();
    const response = await worker.fetch(
      new Request("https://x/api/runner/code/finished", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ runner_key: "orchestrator-runner", ids: ["req-cancelled"] }),
      }),
      env,
    );
    assert.equal(response.status, 401);
    db.close();
  });
});

// Ba yêu cầu còn lại nằm phía Python.  Kiểm bằng cách đọc nguồn — cùng lối
// agent_busy_parity.test.mjs đọc public/app.js: thứ cần ghim là "chỗ này có
// tồn tại không", không phải giá trị lúc chạy.
describe("phía runner", () => {
  const slice = (from, to) => {
    const start = RUNNER_SOURCE.indexOf(from);
    const end = RUNNER_SOURCE.indexOf(to, start);
    assert.ok(start !== -1 && end > start, `không tìm thấy ${from}`);
    return RUNNER_SOURCE.slice(start, end);
  };

  // B3.1 — một finally là thứ duy nhất bắt được cả ca runner ném giữa chừng.
  test("handle_request dọn nhánh trong finally", () => {
    const body = slice("def handle_request(", "def apply_approved(");
    assert.ok(/\n    finally:/.test(body), "B3.1: vòng đời yêu cầu chưa có finally");
    assert.ok(
      /finally:[\s\S]{0,400}cleanup_branch\(/.test(body),
      "finally phải gọi cleanup_branch, trừ đúng ca đã merge thành công",
    );
  });

  // Ca số 1 — merge hỏng — KHÔNG có bài đọc nguồn ở đây, và đó là cố ý.
  //
  // Bản đầu của file này ghim chữ ``branch -D`` vào thân ``apply_approved``.
  // Bản cài đặt chọn đường khác và đường ấy tốt hơn: merge hỏng thì vào sổ
  // ``HELD_BRANCHES``, đợi Center xác nhận trạng thái cuối rồi ``drop_finished
  // _branches`` mới xoá — nên nhánh không bao giờ bị xoá trước lúc Center kịp
  // ghi nhận, và ``sweep_stale_branches`` vớt được cả ca runner bị kill.  Bài
  // đọc nguồn ấy đỏ vì soi nhầm hàm, chứ rò số 1 của PRD B3 đã đóng thật.
  //
  // Chỗ ghim bây giờ là hành vi, ở hai đầu:
  //   · phía Worker — "trả đúng những id ở trạng thái cuối" ngay trên đây đã
  //     khẳng định ``failed`` nằm trong câu trả lời của /api/runner/code/finished;
  //   · phía runner — bốn bài trong ``MergeXongThiDonNhanh``
  //     (automation_center/tests/test_orchestrator_bot.py) chạy thật
  //     ``apply_approved`` rồi ``drop_finished_branches``, khoá cả chiều xoá
  //     lẫn chiều không được xoá khi Center chưa chốt.

  // B3.3 — lưới cuối, bắt cả ca runner bị kill giữa chừng.
  test("khởi động quét và dọn nhánh agent/* không còn ứng với yêu cầu nào", () => {
    assert.ok(
      /"branch",\s*"--list",\s*"agent\/\*"/.test(RUNNER_SOURCE),
      "B3.3: không có bước quét git branch --list 'agent/*' lúc khởi động",
    );
  });

  // B3.4 — đè im lặng là cách mất việc mà không ai thấy.
  test("checkout -B cảnh báo trước khi đè lên một nhánh đã có", () => {
    const body = slice("def handle_request(", "def apply_approved(");
    const before = body.slice(0, body.indexOf('git("checkout", "-B"'));
    assert.ok(
      /rev-parse|"branch",\s*"--list"/.test(before),
      "B3.4: chưa hề nhìn xem nhánh đã tồn tại chưa trước khi checkout -B",
    );
  });

  // B3.5 — hàng rào chống sửa quá tay.  XANH hôm nay, phải ở lại xanh: đổi
  // cách đặt tên là làm hỏng mọi nhánh đang có trên máy trung tâm.
  test("cách đặt tên nhánh không đổi", () => {
    assert.ok(RUNNER_SOURCE.includes('branch = f"agent/{request_id[:12]}"'));
  });

  test("cleanup_branch vẫn đưa repo về nhánh nền trước khi xoá", () => {
    const body = slice("def cleanup_branch(", "def handle_request(");
    assert.ok(body.includes('git("checkout", BASE_BRANCH'), "xoá nhánh đang đứng trên nó thì git từ chối");
    assert.ok(body.includes('git("branch", "-D", branch'));
  });
});

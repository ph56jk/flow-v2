// Runner chỉ được nhận và sửa việc của CHÍNH nó.
//
// Vai soát đo được (mục 9 của docs/review-dot-a.md) rằng chốt này gần như
// không có bài nào canh.  Đo lại bằng đột biến — bỏ `runner_key = ?` khỏi
// từng câu SQL, mỗi lần một câu, bỏ cả tham số bind để lỗi là hành vi chứ
// không phải lệch số tham số — thì bảy trên tám câu bị gỡ mà cả bộ node vẫn
// xanh 190/1:
//
//     M1 bot_runs claim      (worker.js:760)   xanh — KHÔNG bắt được
//     M2 bot_run update      (worker.js:779)   xanh — KHÔNG bắt được
//     M3 code claim          (worker.js:1790)  xanh — KHÔNG bắt được
//     M4 code finished       (worker.js:1868)  ĐỎ   — có bài canh
//     M5 code approved       (worker.js:1884)  xanh — KHÔNG bắt được
//     M6 code update         (worker.js:1900)  xanh — KHÔNG bắt được
//     M7 control claim       (worker.js:2528)  xanh — KHÔNG bắt được
//     M8 control update      (worker.js:2589)  xanh — KHÔNG bắt được
//
// Worker hôm nay ĐÚNG cả tám chỗ — đây là lỗ ở bộ test, không phải lỗ ở code.
// Nhưng một bản Worker phát việc của runner này cho runner kia sẽ đi qua cả
// bộ mà không ai kêu, và đó là chuyện phân quyền.
//
// Vì sao các bài cũ không bắt được: fixture của chúng chỉ có MỘT runner.  Gỡ
// mệnh đề lọc đi thì câu SQL vẫn trả đúng dòng ấy, vì trong bảng không có
// dòng nào khác để trả nhầm.  Nên fixture ở đây có hai runner, và việc của
// `runner-hai` luôn được xếp TRƯỚC — `ORDER BY created_at ASC LIMIT 1` không
// lọc theo runner sẽ vớ đúng nó.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import worker from "../src/worker.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const MIGRATIONS = join(HERE, "..", "migrations");
const SECRET = "runner-secret-cho-test";
const OWNER = "chu@havigroup.llc";
const MOT = "runner-mot";
const HAI = "runner-hai";
// Việc của HAI xếp trước việc của MOT.  Đây là chỗ bài cắn: một câu SQL quên
// lọc runner sẽ trả dòng cũ nhất, tức dòng của HAI.
const SOM = "2026-01-01T00:00:00.000Z";
const MUON = "2026-01-02T00:00:00.000Z";

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

function fresh() {
  const db = new DatabaseSync(":memory:");
  for (const file of readdirSync(MIGRATIONS).filter((name) => name.endsWith(".sql")).sort()) {
    db.exec(readFileSync(join(MIGRATIONS, file), "utf8"));
  }
  const at = new Date().toISOString();
  db.exec(`
    INSERT INTO users (email, display_name, global_role) VALUES ('${OWNER}', 'Chủ', 'owner');
    INSERT INTO dashboards (id, slug, name, status, created_by)
      VALUES ('dash', 'dash', 'Dashboard thử', 'active', '${OWNER}');
    INSERT INTO runners (runner_key, label, status, last_seen_at) VALUES
      ('${MOT}', 'Runner một', 'online', '${at}'),
      ('${HAI}', 'Runner hai', 'online', '${at}');
    INSERT INTO bots (id, dashboard_id, name, purpose, runner_key, status, created_by) VALUES
      ('bot-mot', 'dash', 'Bot một', 'Việc của một', '${MOT}', 'paused', '${OWNER}'),
      ('bot-hai', 'dash', 'Bot hai', 'Việc của hai', '${HAI}', 'paused', '${OWNER}');
    INSERT INTO agent_threads (id, dashboard_id, title, created_by)
      VALUES ('thread', 'dash', 'Luồng thử', '${OWNER}');

    INSERT INTO bot_runs (id, dashboard_id, bot_id, runner_key, requested_by, title, status, created_at, updated_at) VALUES
      ('run-hai', 'dash', 'bot-hai', '${HAI}', '${OWNER}', 'Việc của hai', 'queued', '${SOM}', '${SOM}'),
      ('run-mot', 'dash', 'bot-mot', '${MOT}', '${OWNER}', 'Việc của một', 'queued', '${MUON}', '${MUON}');

    INSERT INTO code_change_requests
      (id, dashboard_id, thread_id, runner_key, requested_by, requested_role, instruction, status, created_at, decided_at) VALUES
      ('code-hai', 'dash', 'thread', '${HAI}', '${OWNER}', 'owner', 'Sửa cho hai', 'queued', '${SOM}', NULL),
      ('code-mot', 'dash', 'thread', '${MOT}', '${OWNER}', 'owner', 'Sửa cho một', 'queued', '${MUON}', NULL),
      ('duyet-hai', 'dash', 'thread', '${HAI}', '${OWNER}', 'owner', 'Đã duyệt cho hai', 'approved', '${SOM}', '${SOM}'),
      ('duyet-mot', 'dash', 'thread', '${MOT}', '${OWNER}', 'owner', 'Đã duyệt cho một', 'approved', '${MUON}', '${MUON}'),
      ('xong-hai', 'dash', 'thread', '${HAI}', '${OWNER}', 'owner', 'Đã xong của hai', 'applied', '${SOM}', '${SOM}'),
      ('xong-mot', 'dash', 'thread', '${MOT}', '${OWNER}', 'owner', 'Đã xong của một', 'applied', '${MUON}', '${MUON}');

    INSERT INTO agent_control_requests
      (id, dashboard_id, thread_id, runner_key, requested_by, requested_role, instruction, status, created_at) VALUES
      ('ctl-hai', 'dash', 'thread', '${HAI}', '${OWNER}', 'owner', 'Điều khiển cho hai', 'queued', '${SOM}'),
      ('ctl-mot', 'dash', 'thread', '${MOT}', '${OWNER}', 'owner', 'Điều khiển cho một', 'queued', '${MUON}');
  `);
  return { db, env: { DB: d1(db), RUNNER_SHARED_SECRET: SECRET } };
}

const trangThai = (db, bang, id) =>
  db.prepare(`SELECT status FROM ${bang} WHERE id = ?`).get(id).status;

test.describe("runner chỉ chạm được việc của chính nó", () => {
  // Mỗi bài dưới đây khoá một câu SQL đã đo được là không có bài nào canh.
  // Cả hai vế đều phải khẳng định: nhận ĐÚNG việc của mình, và KHÔNG chạm
  // vào việc của runner kia.  Thiếu vế đầu thì bài xanh rỗng — một Worker trả
  // null cho tất cả cũng qua được.

  test("M1 · /api/runner/claim không phát bot_run của runner khác", async () => {
    const { db, env } = fresh();
    const response = await worker.fetch(
      new Request("https://x/api/runner/claim", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: MOT }),
      }),
      env,
    );
    const { run } = await response.json();
    assert.equal(run?.id, "run-mot", "runner một phải nhận đúng việc của nó");
    assert.equal(trangThai(db, "bot_runs", "run-hai"), "queued", "việc của hai không được ai nhận thay");
    db.close();
  });

  test("M2 · /api/runner/runs/{id} không cho runner khác cập nhật", async () => {
    const { db, env } = fresh();
    const response = await worker.fetch(
      new Request("https://x/api/runner/runs/run-hai", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: MOT, status: "completed" }),
      }),
      env,
    );
    assert.equal(response.status, 404);
    assert.equal(trangThai(db, "bot_runs", "run-hai"), "queued", "trạng thái của hai phải nguyên vẹn");

    // Vế khẳng định. Thiếu nó thì một Worker trả 404 cho MỌI cập nhật trạng
    // thái của runner đi qua trọn bộ mà không ai kêu — đã đo, 0 bài chết.
    const cuaMinh = await worker.fetch(
      new Request("https://x/api/runner/runs/run-mot", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: MOT, status: "completed" }),
      }),
      env,
    );
    const raw = await cuaMinh.text();
    assert.equal(cuaMinh.status, 200, raw);
    assert.equal(trangThai(db, "bot_runs", "run-mot"), "completed", "runner một phải cập nhật được việc của chính nó");
    db.close();
  });

  test("M3 · /api/runner/code/claim không phát yêu cầu của runner khác", async () => {
    const { db, env } = fresh();
    const response = await worker.fetch(
      new Request("https://x/api/runner/code/claim", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: MOT }),
      }),
      env,
    );
    const body = await response.json();
    assert.equal(body.request?.id, "code-mot", "runner một phải nhận đúng yêu cầu của nó");
    assert.equal(trangThai(db, "code_change_requests", "code-hai"), "queued", "yêu cầu của hai không được ai nhận thay");
    db.close();
  });

  test("M4 · /api/runner/code/finished không trả id của runner khác", async () => {
    const { db, env } = fresh();
    const response = await worker.fetch(
      new Request("https://x/api/runner/code/finished", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: MOT, ids: ["xong-hai", "xong-mot"] }),
      }),
      env,
    );
    // Hỏi cả hai id trong một lượt: phải nhận đúng id của mình và KHÔNG nhận
    // id của hai. Một vế thôi thì bài rỗng theo đúng chiều còn lại.
    assert.deepEqual(
      (await response.json()).finished.map((row) => row.id),
      ["xong-mot"],
    );
    db.close();
  });

  test("M5 · /api/runner/code/approved chỉ liệt kê yêu cầu của người hỏi", async () => {
    const { db, env } = fresh();
    const response = await worker.fetch(
      new Request(`https://x/api/runner/code/approved?runner_key=${MOT}`, {
        method: "GET",
        headers: { "x-automation-runner-secret": SECRET },
      }),
      env,
    );
    const ids = (await response.json()).requests.map((row) => row.id);
    // Vế khẳng định phải có, nếu không một Worker trả danh sách rỗng cũng qua.
    assert.deepEqual(ids, ["duyet-mot"]);
    db.close();
  });

  test("M6 · /api/runner/code/{id} không cho runner khác cập nhật", async () => {
    const { db, env } = fresh();
    const response = await worker.fetch(
      new Request("https://x/api/runner/code/code-hai", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: MOT, status: "failed", error: "không được ghi" }),
      }),
      env,
    );
    assert.equal(response.status, 404);
    assert.equal(trangThai(db, "code_change_requests", "code-hai"), "queued", "yêu cầu của hai phải nguyên vẹn");

    const cuaMinh = await worker.fetch(
      new Request("https://x/api/runner/code/code-mot", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: MOT, status: "failed", error: "một tự báo hỏng" }),
      }),
      env,
    );
    const raw = await cuaMinh.text();
    assert.equal(cuaMinh.status, 200, raw);
    assert.equal(trangThai(db, "code_change_requests", "code-mot"), "failed", "runner một phải cập nhật được yêu cầu của chính nó");
    db.close();
  });

  test("M7 · /api/runner/control/claim không phát yêu cầu của runner khác", async () => {
    const { db, env } = fresh();
    const response = await worker.fetch(
      new Request("https://x/api/runner/control/claim", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: MOT }),
      }),
      env,
    );
    const body = await response.json();
    assert.equal(body.request?.id, "ctl-mot", "runner một phải nhận đúng yêu cầu của nó");
    assert.equal(trangThai(db, "agent_control_requests", "ctl-hai"), "queued", "yêu cầu của hai không được ai nhận thay");
    db.close();
  });

  test("M8 · /api/runner/control/{id} không cho runner khác cập nhật", async () => {
    const { db, env } = fresh();
    const response = await worker.fetch(
      new Request("https://x/api/runner/control/ctl-hai", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: MOT, status: "failed", error: "không được ghi" }),
      }),
      env,
    );
    assert.equal(response.status, 404);
    assert.equal(trangThai(db, "agent_control_requests", "ctl-hai"), "queued", "yêu cầu của hai phải nguyên vẹn");

    const cuaMinh = await worker.fetch(
      new Request("https://x/api/runner/control/ctl-mot", {
        method: "POST",
        headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
        body: JSON.stringify({ runner_key: MOT, status: "failed", error: "một tự báo hỏng" }),
      }),
      env,
    );
    const raw = await cuaMinh.text();
    assert.equal(cuaMinh.status, 200, raw);
    assert.equal(trangThai(db, "agent_control_requests", "ctl-mot"), "failed", "runner một phải cập nhật được yêu cầu của chính nó");
    db.close();
  });
});

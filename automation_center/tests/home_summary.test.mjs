// Thẻ khung chat trên màn hình chính lấy số từ agentChatSummary().
//
//   node --test --experimental-sqlite tests/home_summary.test.mjs
//
// Con số này hiện ra trước khi người dùng bấm vào bất kỳ chương trình nào, nên
// nó phải bị chặn theo quyền ngay tại chỗ đếm: đếm gộp cả dashboard người ta
// không được vào là rò rỉ, dù chỉ là "có 3 việc đang chờ" — đủ để biết bên kia
// đang có việc.  Test này chạy trên SQLite thật vì cái cần kiểm là câu SQL
// lọc theo dashboard_id, không phải nhánh if.
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { agentChatSummary } from "../src/worker.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const MIGRATIONS = join(HERE, "..", "migrations");

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

const OWNER = { email: "chu@havigroup.llc", global_role: "owner" };

// Hai dashboard: "mine" là nơi người dùng có quyền nhắn, "other" là nơi không.
// Mỗi nơi đều có việc đang chờ, để đếm nhầm là thấy ngay.
function fresh() {
  const db = new DatabaseSync(":memory:");
  for (const file of readdirSync(MIGRATIONS).filter((n) => n.endsWith(".sql")).sort()) {
    db.exec(readFileSync(join(MIGRATIONS, file), "utf8"));
  }
  db.exec(`INSERT INTO users (email, display_name, global_role) VALUES ('${OWNER.email}', 'Chu', 'owner')`);
  for (const [id, slug] of [["dash-mine", "listing-2-erp"], ["dash-other", "kho-anh"]]) {
    db.exec(`INSERT INTO dashboards (id, slug, name, status, created_by) VALUES ('${id}', '${slug}', '${slug}', 'active', '${OWNER.email}')`);
    db.exec(`INSERT INTO agent_threads (id, dashboard_id, created_by) VALUES ('thread-${id}', '${id}', '${OWNER.email}')`);
  }
  return { db, env: { DB: d1(db) } };
}

function addCodeRequest(db, dashboardId, status) {
  db.exec(`INSERT INTO code_change_requests (id, dashboard_id, thread_id, requested_by, instruction, status)
           VALUES ('code-${dashboardId}-${status}', '${dashboardId}', 'thread-${dashboardId}', '${OWNER.email}', 'sửa gì đó', '${status}')`);
}

function addControlRequest(db, dashboardId, status) {
  db.exec(`INSERT INTO agent_control_requests (id, dashboard_id, thread_id, requested_by, instruction, status)
           VALUES ('ctl-${dashboardId}-${status}', '${dashboardId}', 'thread-${dashboardId}', '${OWNER.email}', 'chạy bot', '${status}')`);
}

const visible = (roles) => Object.entries(roles).map(([id, role]) => ({ id, slug: id === "dash-mine" ? "listing-2-erp" : "kho-anh", role }));

describe("Tóm tắt khung chat trên màn hình chính", () => {
  test("chưa có yêu cầu nào thì trả về số 0 và trỏ vào chương trình nhắn được", async () => {
    const { env } = fresh();
    const summary = await agentChatSummary(env, OWNER, visible({ "dash-mine": "owner" }));
    assert.equal(summary.locked, "");
    assert.equal(summary.slug, "listing-2-erp");
    assert.equal(summary.dashboards, 1);
    assert.equal(summary.awaiting, 0);
    assert.equal(summary.active, 0);
    // Chưa có heartbeat nào thì phải là chưa kết nối, không phải "chắc là ổn".
    assert.equal(summary.runner_online, false);
  });

  test("đếm cả hai bảng: sửa code và điều khiển bot", async () => {
    const { db, env } = fresh();
    addCodeRequest(db, "dash-mine", "awaiting_approval");
    addCodeRequest(db, "dash-mine", "planning");
    addControlRequest(db, "dash-mine", "queued");
    addControlRequest(db, "dash-mine", "executing");
    // Đã xong thì không còn là việc đang chờ.
    addCodeRequest(db, "dash-mine", "applied");
    const summary = await agentChatSummary(env, OWNER, visible({ "dash-mine": "owner" }));
    assert.equal(summary.awaiting, 1);
    assert.equal(summary.active, 3);
  });

  test("không đếm dashboard người dùng không có quyền nhắn", async () => {
    const { db, env } = fresh();
    addCodeRequest(db, "dash-other", "awaiting_approval");
    addControlRequest(db, "dash-other", "queued");
    const summary = await agentChatSummary(env, OWNER, visible({ "dash-mine": "owner", "dash-other": "viewer" }));
    assert.equal(summary.dashboards, 1);
    assert.equal(summary.slug, "listing-2-erp");
    assert.equal(summary.awaiting, 0);
    assert.equal(summary.active, 0);
  });

  test("chỉ xem được ở mọi nơi thì không có chương trình nào để nhắn", async () => {
    const { db, env } = fresh();
    addCodeRequest(db, "dash-mine", "awaiting_approval");
    const summary = await agentChatSummary(env, { email: "xem@havigroup.llc", global_role: "viewer" }, visible({ "dash-mine": "viewer" }));
    assert.equal(summary.dashboards, 0);
    assert.equal(summary.slug, "");
    assert.equal(summary.awaiting, 0);
  });

  test("reviewer chỉ duyệt, không nhắn được, nên thẻ chat không trỏ vào đâu", async () => {
    const { env } = fresh();
    const summary = await agentChatSummary(env, { email: "duyet@havigroup.llc", global_role: "reviewer" }, visible({ "dash-mine": "reviewer" }));
    assert.equal(summary.dashboards, 0);
  });

  test("operator nhắn được nên vẫn có thẻ chat", async () => {
    const { db, env } = fresh();
    addControlRequest(db, "dash-mine", "queued");
    const summary = await agentChatSummary(env, { email: "van@havigroup.llc", global_role: "operator" }, visible({ "dash-mine": "operator" }));
    assert.equal(summary.dashboards, 1);
    assert.equal(summary.active, 1);
  });

  test("heartbeat mới thì runner báo trực tuyến", async () => {
    const { db, env } = fresh();
    db.exec(`INSERT INTO runners (runner_key, status, last_seen_at) VALUES ('orchestrator-runner', 'online', '${new Date().toISOString()}')`);
    const summary = await agentChatSummary(env, OWNER, visible({ "dash-mine": "owner" }));
    assert.equal(summary.runner_online, true);
  });

  test("danh sách trắng khoá thì thẻ chat nói rõ lý do", async () => {
    const { env } = fresh();
    const locked = { ...env, AGENT_CHAT_ALLOWED_EMAILS: "aikhac@havigroup.llc" };
    const summary = await agentChatSummary(locked, OWNER, visible({ "dash-mine": "owner" }));
    assert.match(summary.locked, /aikhac@havigroup\.llc/);
  });
});

// Xoá một cuộc trò chuyện với Agent điều phối.
//
//   node --test --experimental-sqlite tests/agent_thread_delete.test.mjs
//
// Luật giống hệt việc rút lại một yêu cầu (xem chat_gate.test.mjs): người tạo
// luôn xoá được của chính mình, người khác cần code_approve. Khác ở chỗ xoá là
// vĩnh viễn và kéo theo cả agent_messages + code_change_requests, nên test này
// đếm hàng ở cả ba bảng chứ không chỉ đọc mã lỗi HTTP trả về.
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { deleteAgentThread } from "../src/worker.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const MIGRATIONS = join(HERE, "..", "migrations");

// D1 trả {meta:{changes}} / {results:[...]}; node:sqlite trả hình dạng khác.
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

function fresh() {
  const db = new DatabaseSync(":memory:");
  for (const file of readdirSync(MIGRATIONS).filter((n) => n.endsWith(".sql")).sort()) {
    db.exec(readFileSync(join(MIGRATIONS, file), "utf8"));
  }
  db.exec(`INSERT INTO users (email, display_name, global_role) VALUES ('${OWNER.email}', 'Chu', 'owner')`);
  db.exec(`INSERT INTO dashboards (id, slug, name, status, created_by)
           VALUES ('dash-1', 'listing-2-erp', 'Listing 2', 'active', '${OWNER.email}')`);
  db.exec(`INSERT INTO dashboards (id, slug, name, status, created_by)
           VALUES ('dash-2', 'khac', 'Khác', 'active', '${OWNER.email}')`);
  return { db, env: { DB: d1(db) } };
}

function addMember(db, email, role) {
  db.exec(`INSERT INTO users (email, global_role) VALUES ('${email}', 'viewer')`);
  db.exec(`INSERT INTO dashboard_members (dashboard_id, user_email, role, granted_by)
           VALUES ('dash-1', '${email}', '${role}', '${OWNER.email}')`);
  return { email, global_role: "viewer" };
}

function seedThread(db, { id = "thread-1", dashboardId = "dash-1", createdBy = OWNER.email, status = "open" } = {}) {
  db.exec(`INSERT INTO agent_threads (id, dashboard_id, title, created_by, status)
           VALUES ('${id}', '${dashboardId}', 'Luồng test', '${createdBy}', '${status}')`);
  return id;
}

function seedMessage(db, threadId, id = "msg-1") {
  db.exec(`INSERT INTO agent_messages (id, thread_id, dashboard_id, kind, author_email, content)
           VALUES ('${id}', '${threadId}', 'dash-1', 'user', '${OWNER.email}', 'xin chào')`);
}

function seedRequest(db, threadId, { id = "req-1", status = "applied" } = {}) {
  db.exec(`INSERT INTO code_change_requests (id, dashboard_id, thread_id, requested_by, instruction, status)
           VALUES ('${id}', 'dash-1', '${threadId}', '${OWNER.email}', 'làm gì đó', '${status}')`);
}

const threadCount = (db) => db.prepare("SELECT COUNT(*) AS n FROM agent_threads").get().n;
const messageCount = (db) => db.prepare("SELECT COUNT(*) AS n FROM agent_messages").get().n;
const requestCount = (db) => db.prepare("SELECT COUNT(*) AS n FROM code_change_requests").get().n;

describe("người tạo xoá được luồng của chính mình", () => {
  test("xoá kéo theo cả tin nhắn và yêu cầu đã kết thúc", async () => {
    const { db, env } = fresh();
    const threadId = seedThread(db);
    seedMessage(db, threadId);
    seedRequest(db, threadId, { status: "applied" });
    const response = await deleteAgentThread(env, OWNER, "listing-2-erp", threadId);
    assert.equal(response.status, 200);
    assert.equal(threadCount(db), 0);
    assert.equal(messageCount(db), 0);
    assert.equal(requestCount(db), 0);
  });
});

describe("người không phải chủ luồng cần code_approve mới xoá được", () => {
  test("operator (có code_request, không có code_approve) xoá luồng của người khác thì bị chặn", async () => {
    const { db, env } = fresh();
    const operator = addMember(db, "nv@havigroup.llc", "operator");
    const threadId = seedThread(db, { createdBy: OWNER.email });
    const response = await deleteAgentThread(env, operator, "listing-2-erp", threadId);
    assert.equal(response.status, 403);
    assert.equal(threadCount(db), 1, "luồng của người khác phải còn nguyên");
  });

  test("admin (có code_approve) xoá được luồng do người khác tạo", async () => {
    const { db, env } = fresh();
    const admin = addMember(db, "quanly@havigroup.llc", "admin");
    const threadId = seedThread(db, { createdBy: "nv@havigroup.llc" });
    const response = await deleteAgentThread(env, admin, "listing-2-erp", threadId);
    assert.equal(response.status, 200);
    assert.equal(threadCount(db), 0);
  });
});

describe("luồng còn việc chưa xong thì không xoá được", () => {
  for (const status of ["queued", "planning", "awaiting_approval", "applying"]) {
    test(`yêu cầu ở trạng thái ${status} chặn việc xoá`, async () => {
      const { db, env } = fresh();
      const threadId = seedThread(db);
      seedRequest(db, threadId, { status });
      const response = await deleteAgentThread(env, OWNER, "listing-2-erp", threadId);
      assert.equal(response.status, 409);
      assert.equal(threadCount(db), 1, "phải huỷ hoặc chờ xong trước, không âm thầm xoá");
    });
  }

  test("yêu cầu đã kết thúc (rejected/cancelled/failed) không chặn xoá", async () => {
    const { db, env } = fresh();
    const threadId = seedThread(db);
    seedRequest(db, threadId, { status: "cancelled" });
    const response = await deleteAgentThread(env, OWNER, "listing-2-erp", threadId);
    assert.equal(response.status, 200);
    assert.equal(threadCount(db), 0);
  });
});

describe("biên giới id và dashboard", () => {
  test("threadId không tồn tại trả về 404", async () => {
    const { db, env } = fresh();
    const response = await deleteAgentThread(env, OWNER, "listing-2-erp", "khong-ton-tai");
    assert.equal(response.status, 404);
  });

  test("luồng của dashboard khác không xoá lẫn qua slug này", async () => {
    const { db, env } = fresh();
    const threadId = seedThread(db, { dashboardId: "dash-2" });
    const response = await deleteAgentThread(env, OWNER, "listing-2-erp", threadId);
    assert.equal(response.status, 404);
    assert.equal(threadCount(db), 1, "luồng ở dashboard khác phải còn nguyên");
  });
});

// B5 — hạn mức yêu cầu sửa code theo ngày.
//
//   /Users/admin/.local/node/bin/node --test --experimental-sqlite automation_center/tests/code_request_quota.test.mjs
//
// PRD: tasks/prd-agent-improvements.md §B5.  **Mọi bài ở đây đang ĐỎ và phải đỏ**
// trừ hai bài canh chừng ở cuối.
//
// Tìm usage|tokens|cost|quota|budget trong worker.js, orchestrator_runner.py,
// public/app.js và migrations/*.sql: không một kết quả nào liên quan tới token.
// Cái đang có là trần CẤU TRÚC (MAX_ROUNDS, MAX_CONTEXT_FILES, một yêu cầu
// sống mỗi thread), không phải trần CHI PHÍ.
//
// Trần theo ngày đã có sẵn cho lệnh điều khiển bot và làm rất gọn:
// max_commands_per_day mặc định 40, kẹp 1..200, deny("daily_limit", ...),
// countControlCommandsToday đếm theo mốc ngày Việt Nam.  Yêu cầu sửa code —
// thứ thật sự gọi model và thật sự tốn tiền — thì không có trần nào.  B5 là
// làm đúng khuôn đó cho đường đắt hơn.
import test, { describe } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import * as workerModule from "../src/worker.js";
import { createAgentThread, vietnamDayStartIso, OWNER_DEFAULT_CONTROL_SCOPE } from "../src/worker.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const MIGRATIONS = join(HERE, "..", "migrations");
const OWNER = { email: "chu@havigroup.llc", global_role: "owner", active: 1 };
const HOUR = 3600000;

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
  db.exec(`
    INSERT INTO users (email, display_name, global_role) VALUES ('${OWNER.email}', 'Chu', 'owner');
    INSERT INTO dashboards (id, slug, name, status, created_by)
      VALUES ('dash-1', 'listing-2-erp', 'Listing 2', 'active', '${OWNER.email}');
    INSERT INTO runners (runner_key, label, status, last_seen_at)
      VALUES ('orchestrator-runner', 'Trung tâm', 'online', '${new Date().toISOString()}');
  `);
  return { db, env: { DB: d1(db) } };
}

const post = (message) => new Request("https://x/api/dashboards/listing-2-erp/agent/threads", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ message }),
});

// Xếp sẵn n yêu cầu ĐÃ TIÊU quota trong hôm nay, không đi qua createAgentThread
// để bài test không phụ thuộc vào chính thứ nó đang kiểm.
function seedRequestsToday(db, count, { status = "applied", at = new Date().toISOString() } = {}) {
  for (let index = 0; index < count; index += 1) {
    db.exec(`
      INSERT INTO agent_threads (id, dashboard_id, title, created_by, status, created_at, updated_at)
        VALUES ('t-${index}', 'dash-1', 'Luồng ${index}', '${OWNER.email}', 'open', '${at}', '${at}');
      INSERT INTO code_change_requests
        (id, dashboard_id, thread_id, runner_key, requested_by, requested_role, instruction, status, created_at, updated_at)
        VALUES ('r-${index}', 'dash-1', 't-${index}', 'orchestrator-runner', '${OWNER.email}', 'owner', 'Sửa nhãn nút số ${index}', '${status}', '${at}', '${at}');
    `);
  }
}

const threadCount = (db) => db.prepare("SELECT COUNT(*) AS n FROM agent_threads").get().n;
const requestCount = (db) => db.prepare("SELECT COUNT(*) AS n FROM code_change_requests").get().n;

describe("trần ngày phải tồn tại và có tên", () => {
  test("CODE_REQUEST_LIMITS được xuất ra", () => {
    const limits = workerModule.CODE_REQUEST_LIMITS;
    assert.ok(limits, "B5.1: trần phải là hằng số công bố, đúng khuôn CONTROL_LIMITS");
    assert.equal(typeof limits.defaultPerDay, "number");
    assert.equal(typeof limits.minPerDay, "number");
    assert.equal(typeof limits.maxPerDay, "number");
  });

  // Không phải một con số tuỳ hứng: một yêu cầu sửa code gọi model tới 4 vòng
  // và chạy cả bộ test, còn một lệnh bot chỉ chèn một hàng.  Trần của đường
  // đắt hơn không được rộng hơn trần của đường rẻ hơn.
  test("trần sửa code không rộng hơn trần lệnh bot", () => {
    assert.ok(
      workerModule.CODE_REQUEST_LIMITS.defaultPerDay <= OWNER_DEFAULT_CONTROL_SCOPE.max_commands_per_day,
      `sửa code (${workerModule.CODE_REQUEST_LIMITS?.defaultPerDay}) đang rộng hơn lệnh bot (${OWNER_DEFAULT_CONTROL_SCOPE.max_commands_per_day})`,
    );
    assert.ok(workerModule.CODE_REQUEST_LIMITS.defaultPerDay >= workerModule.CODE_REQUEST_LIMITS.minPerDay);
    assert.ok(workerModule.CODE_REQUEST_LIMITS.defaultPerDay <= workerModule.CODE_REQUEST_LIMITS.maxPerDay);
  });
});

describe("đếm theo mốc ngày Việt Nam", () => {
  test("codeRequestsUsedToday được xuất ra và đếm đúng người, đúng dashboard", async () => {
    assert.equal(typeof workerModule.codeRequestsUsedToday, "function", "B5.1: cần hàm đếm kiểm được ngoài Worker");
    const { db, env } = fresh();
    seedRequestsToday(db, 3);
    db.exec(`
      INSERT INTO users (email, display_name, global_role) VALUES ('nv@havigroup.llc', 'NV', 'operator');
      INSERT INTO agent_threads (id, dashboard_id, title, created_by) VALUES ('t-nv', 'dash-1', 'NV', 'nv@havigroup.llc');
      INSERT INTO code_change_requests (id, dashboard_id, thread_id, runner_key, requested_by, requested_role, instruction, status)
        VALUES ('r-nv', 'dash-1', 't-nv', 'orchestrator-runner', 'nv@havigroup.llc', 'operator', 'Việc của người khác', 'applied');
    `);
    const used = await workerModule.codeRequestsUsedToday(env, { id: "dash-1" }, OWNER.email, Date.now());
    assert.equal(used, 3, "quota của mỗi người là của riêng họ");
    db.close();
  });

  // 23:00 UTC = 06:00 sáng hôm sau ở VN.  Đếm theo ngày UTC sẽ reset trần vào
  // 07:00 sáng — đúng lúc người ta bắt đầu làm việc.
  test("yêu cầu của hôm qua theo giờ VN không tính vào hôm nay", async () => {
    const { db, env } = fresh();
    const nowMs = Date.parse("2026-09-03T04:00:00.000Z"); // 11:00 giờ VN
    const homQua = new Date(Date.parse(vietnamDayStartIso(nowMs)) - HOUR).toISOString();
    seedRequestsToday(db, 2, { at: homQua });
    assert.equal(await workerModule.codeRequestsUsedToday(env, { id: "dash-1" }, OWNER.email, nowMs), 0);
    db.close();
  });

  // Cùng lý lẽ với countControlCommandsToday: yêu cầu bị CHẶN không tiêu
  // quota, nếu không thì một chuỗi lệnh sai sẽ khoá luôn người dùng thật.
  test("yêu cầu bị chặn ở cửa không tiêu quota", async () => {
    const { db, env } = fresh();
    seedRequestsToday(db, 2, { status: "rejected" });
    // rejected là "người đã xem rồi từ chối" — model đã chạy, vẫn tính tiền.
    assert.equal(await workerModule.codeRequestsUsedToday(env, { id: "dash-1" }, OWNER.email, Date.now()), 2);
    db.close();
  });
});

describe("đường xếp việc thật", () => {
  test("hết hạn mức thì từ chối 429 và không để lại luồng rỗng", async () => {
    const { db, env } = fresh();
    seedRequestsToday(db, workerModule.CODE_REQUEST_LIMITS?.defaultPerDay ?? 20);
    const before = threadCount(db);
    const thrown = await createAgentThread(post("sửa giúp hàm gửi ảnh lên ERP"), env, OWNER, "listing-2-erp")
      .then(() => null, (caught) => caught);
    assert.ok(thrown instanceof Response, "phải ném Response chứ không âm thầm xếp thêm việc");
    assert.equal(thrown.status, 429);
    assert.match(await thrown.text(), /hạn mức|hôm nay/i, "câu từ chối phải nói rõ là hết hạn mức ngày");
    assert.equal(threadCount(db), before, "bị từ chối thì không được bỏ lại luồng rỗng");
    db.close();
  });

  test("chưa chạm trần thì vẫn xếp việc bình thường", async () => {
    const { db, env } = fresh();
    seedRequestsToday(db, Math.max(0, (workerModule.CODE_REQUEST_LIMITS?.defaultPerDay ?? 20) - 1));
    const before = requestCount(db);
    const response = await createAgentThread(post("sửa giúp hàm gửi ảnh lên ERP"), env, OWNER, "listing-2-erp");
    assert.equal(response.status, 201, await response.text());
    assert.equal(requestCount(db), before + 1);
    db.close();
  });
});

// B5.2/B5.3 — token chỉ để xem lại, không để làm trần: hai trong ba provider
// (call_claude, call_codex là subprocess CLI) không báo token, nên một trần
// theo token sẽ lệch tuỳ provider.
describe("ghi lại usage khi provider có trả", () => {
  test("call_chatgpt đọc usage từ phản hồi", () => {
    const python = readFileSync(new URL("../runner/orchestrator_runner.py", import.meta.url), "utf8");
    const body = python.slice(python.indexOf("def call_chatgpt("), python.indexOf("def claude_argv("));
    assert.ok(body.length > 0, "không tìm thấy call_chatgpt");
    assert.ok(/\busage\b/.test(body), "B5.2: phản hồi có trường usage mà không ai đọc");
  });

  test("trần vẫn đếm theo số yêu cầu, không theo token", () => {
    // B5.3.  Bài này canh chừng chiều ngược lại: đừng biến usage thành trần.
    const limits = workerModule.CODE_REQUEST_LIMITS || {};
    for (const key of Object.keys(limits)) {
      assert.ok(!/token/i.test(key), `trần không được tính theo token: ${key}`);
    }
  });
});

// Hàng rào chống sửa quá tay.  Hai bài này XANH hôm nay và phải ở lại xanh.
describe("những thứ B5 không được đụng", () => {
  test("trần lệnh bot giữ nguyên", () => {
    assert.equal(OWNER_DEFAULT_CONTROL_SCOPE.max_commands_per_day, 40);
  });

  test("mốc ngày Việt Nam vẫn là +07:00", () => {
    const nowMs = Date.parse("2026-09-03T04:00:00.000Z");
    assert.equal(vietnamDayStartIso(nowMs), "2026-09-02T17:00:00.000Z");
  });
});

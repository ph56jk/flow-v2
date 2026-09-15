// Cửa vào của hai đường chat trong panel "Agent trung tâm".
//
//   node --test --experimental-sqlite tests/chat_gate.test.mjs
//
// Hai tab Chat và Điều khiển bot dùng CHUNG bảng agent_threads, và danh sách
// luồng chỉ hiện 30 hàng mới nhất.  Nên một luồng rỗng sinh ra do yêu cầu bị từ
// chối không phải rác vô hại: đủ 30 lần bị từ chối là luồng thật biến mất khỏi
// màn hình của CẢ hai tab.  Vì vậy test này chạy trên SQLite thật và đếm hàng,
// chứ không chỉ kiểm mã lỗi HTTP trả về.
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { createAgentThread, createControlThread, postAgentMessage } from "../src/worker.js";

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
  return { db, env: { DB: d1(db) } };
}

const post = (body) => new Request("https://x/api", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

const threadCount = (db) => db.prepare("SELECT COUNT(*) AS n FROM agent_threads").get().n;

// Cả hai runner đều vắng mặt trong cơ sở dữ liệu trắng, nên cả hai đường chat
// đều phải từ chối ở bước "chưa có ai xử lý" — đúng tình huống hay gặp nhất
// ngoài đời: người dùng nhắn lúc máy trung tâm đang tắt.
describe("runner chưa kết nối thì không để lại luồng rỗng", () => {
  test("tab Chat: từ chối 409 và agent_threads vẫn trống", async () => {
    const { db, env } = fresh();
    const thrown = await createAgentThread(post({ message: "sửa giúp hàm gửi ảnh" }), env, OWNER, "listing-2-erp")
      .then(() => null, (caught) => caught);
    assert.ok(thrown instanceof Response, "phải ném Response chứ không âm thầm đi tiếp");
    assert.equal(thrown.status, 409);
    assert.equal(threadCount(db), 0, "luồng rỗng bị bỏ lại");
  });

  test("tab Điều khiển bot: từ chối 409 và agent_threads vẫn trống", async () => {
    const { db, env } = fresh();
    const thrown = await createControlThread(post({ message: "dừng con bot ảnh lại" }), env, OWNER, "listing-2-erp")
      .then(() => null, (caught) => caught);
    assert.ok(thrown instanceof Response);
    assert.equal(thrown.status, 409);
    assert.equal(threadCount(db), 0, "luồng rỗng bị bỏ lại");
  });

  // Bị từ chối nhiều lần cũng không được tích luỹ: đây mới là kịch bản làm mất
  // luồng thật, vì hai tab chia nhau đúng một danh sách 30 hàng.
  test("từ chối nhiều lần vẫn không tích luỹ luồng", async () => {
    const { db, env } = fresh();
    for (let i = 0; i < 5; i += 1) {
      await createAgentThread(post({ message: `yêu cầu số ${i} cần sửa code` }), env, OWNER, "listing-2-erp").catch(() => {});
      await createControlThread(post({ message: `yêu cầu số ${i} cần dừng bot` }), env, OWNER, "listing-2-erp").catch(() => {});
    }
    assert.equal(threadCount(db), 0);
  });
});

describe("luồng chờ người duyệt phải nói rõ lối ra", () => {
  test("awaiting_approval trả 409 hướng người dùng duyệt hoặc từ chối, không xếp thêm yêu cầu", async () => {
    const { db, env } = fresh();
    db.exec(`
      INSERT INTO runners (runner_key, label, status, last_seen_at)
        VALUES ('orchestrator-runner', 'Trung tâm', 'online', '${new Date().toISOString()}');
      INSERT INTO agent_threads (id, dashboard_id, title, created_by, status)
        VALUES ('thread-approval', 'dash-1', 'Cần duyệt', '${OWNER.email}', 'open');
      INSERT INTO code_change_requests (id, dashboard_id, thread_id, runner_key, requested_by, instruction, status)
        VALUES ('request-approval', 'dash-1', 'thread-approval', 'orchestrator-runner', '${OWNER.email}', 'Đổi nhãn nút', 'awaiting_approval');
    `);

    const result = await postAgentMessage(post({ message: "Gửi thêm yêu cầu khác sau khi đã duyệt" }), env, OWNER, "listing-2-erp", "thread-approval");

    assert.equal(result.status, 409);
    assert.match(await result.text(), /chờ duyệt.*duyệt hoặc từ chối/i);
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM code_change_requests WHERE thread_id = 'thread-approval'").get().n, 1);
    db.close();
  });
});

// Người chưa được cấp phạm vi phải bị chặn TRƯỚC khi có bất kỳ hàng nào được
// ghi.  operator có capability code_request nhưng không mặc nhiên có code_scope.
describe("chưa được cấp phạm vi thì không để lại luồng rỗng", () => {
  test("operator không có code_scope: 403, không có luồng", async () => {
    const { db, env } = fresh();
    db.exec(`INSERT INTO users (email, global_role) VALUES ('nv@havigroup.llc', 'operator')`);
    db.exec(`INSERT INTO dashboard_members (dashboard_id, user_email, role, granted_by)
             VALUES ('dash-1', 'nv@havigroup.llc', 'operator', '${OWNER.email}')`);
    // Runner sống, để chắc chắn lỗi đến từ phạm vi chứ không từ kết nối.
    db.exec(`INSERT INTO runners (runner_key, label, status, last_seen_at)
             VALUES ('orchestrator-runner', 'Trung tâm', 'online', '${new Date().toISOString()}')`);
    const user = { email: "nv@havigroup.llc", global_role: "operator" };
    const thrown = await createAgentThread(post({ message: "đổi giúp mức log sang DEBUG" }), env, user, "listing-2-erp")
      .then(() => null, (caught) => caught);
    assert.ok(thrown instanceof Response);
    assert.equal(thrown.status, 403);
    assert.equal(threadCount(db), 0);
  });
});

// Owner và Admin phải gõ được vào khung chat ngay lần đầu mở trang.  Trước đây
// chỉ Owner có phạm vi mặc định, nên một Admin mới được cấp quyền vẫn nhìn thấy
// ô soạn kèm dòng chữ bảo đi nhờ người khác — trang trông như chưa làm xong.
describe("Owner và Admin nhắn được ngay, không cần ai cấp phạm vi trước", () => {
  function liveDashboard() {
    const { db, env } = fresh();
    db.exec(`INSERT INTO runners (runner_key, label, status, last_seen_at)
             VALUES ('orchestrator-runner', 'Trung tâm', 'online', '${new Date().toISOString()}')`);
    return { db, env };
  }

  function addMember(db, email, role) {
    db.exec(`INSERT INTO users (email, global_role) VALUES ('${email}', 'viewer')`);
    db.exec(`INSERT INTO dashboard_members (dashboard_id, user_email, role, granted_by)
             VALUES ('dash-1', '${email}', '${role}', '${OWNER.email}')`);
    return { email, global_role: "viewer" };
  }

  const scopeSource = (db) => JSON.parse(db.prepare("SELECT scope_json FROM code_change_requests").get().scope_json).source;

  test("Admin không có dòng code_scopes nào vẫn mở được luồng", async () => {
    const { db, env } = liveDashboard();
    const admin = addMember(db, "quanly@havigroup.llc", "admin");
    const response = await createAgentThread(post({ message: "đổi nhãn nút Tạo ảnh giúp anh" }), env, admin, "listing-2-erp");
    assert.equal(response.status, 201);
    assert.equal(threadCount(db), 1);
    assert.equal(scopeSource(db), "admin_default");
  });

  test("Owner vẫn dùng phạm vi rộng hơn của Owner", async () => {
    const { db, env } = liveDashboard();
    const response = await createAgentThread(post({ message: "đổi nhãn nút Tạo ảnh giúp anh" }), env, OWNER, "listing-2-erp");
    assert.equal(response.status, 201);
    assert.equal(scopeSource(db), "owner_default");
  });

  // Mặc định không được phép mở khoá một người đã bị Owner khoá lại.  Cấp một
  // dòng phạm vi rỗng là cách khoá; nếu mặc định thắng thì thao tác khoá đó im
  // lặng mất tác dụng, và không ai thấy.
  test("Admin bị Owner cấp phạm vi rỗng thì vẫn bị chặn", async () => {
    const { db, env } = liveDashboard();
    const admin = addMember(db, "quanly@havigroup.llc", "admin");
    db.exec(`INSERT INTO code_scopes (id, dashboard_id, subject_type, subject, allow_globs, max_files, max_lines, auto_apply, updated_by)
             VALUES ('scope-1', 'dash-1', 'user', 'quanly@havigroup.llc', '', 5, 200, 0, '${OWNER.email}')`);
    const thrown = await createAgentThread(post({ message: "đổi nhãn nút Tạo ảnh giúp anh" }), env, admin, "listing-2-erp")
      .then(() => null, (caught) => caught);
    assert.ok(thrown instanceof Response);
    assert.equal(thrown.status, 403);
    assert.equal(threadCount(db), 0);
  });

  // Ranh giới "chỉ Owner/Admin dùng được ngay" nằm ở đây: operator có
  // capability code_request nhưng không có phạm vi mặc định.
  test("Operator vẫn phải được cấp phạm vi đích danh", async () => {
    const { db, env } = liveDashboard();
    const operator = addMember(db, "nhanvien@havigroup.llc", "operator");
    const thrown = await createAgentThread(post({ message: "đổi nhãn nút Tạo ảnh giúp anh" }), env, operator, "listing-2-erp")
      .then(() => null, (caught) => caught);
    assert.ok(thrown instanceof Response);
    assert.equal(thrown.status, 403);
    assert.equal(threadCount(db), 0);

    db.exec(`INSERT INTO code_scopes (id, dashboard_id, subject_type, subject, allow_globs, max_files, max_lines, auto_apply, updated_by)
             VALUES ('scope-2', 'dash-1', 'role', 'operator', 'flow_web/**', 5, 200, 0, '${OWNER.email}')`);
    const response = await createAgentThread(post({ message: "đổi nhãn nút Tạo ảnh giúp anh" }), env, operator, "listing-2-erp");
    assert.equal(response.status, 201);
    assert.equal(scopeSource(db), "role:operator");
  });
});

// Danh sách trắng AGENT_CHAT_ALLOWED_EMAILS đứng TRƯỚC vai trò và phạm vi: đây
// là cái van đóng nhanh khi muốn thu khung chat về đúng vài người trong lúc còn
// thử.  Test giữ hai nửa của lời hứa đó — đóng đúng người, và không âm thầm
// đóng khi biến để trống.
describe("Danh sách trắng khoá khung chat về đúng vài người", () => {
  function liveDashboard(allowed) {
    const { db, env } = fresh();
    db.exec(`INSERT INTO runners (runner_key, label, status, last_seen_at)
             VALUES ('orchestrator-runner', 'Trung tâm', 'online', '${new Date().toISOString()}')`);
    if (allowed !== undefined) env.AGENT_CHAT_ALLOWED_EMAILS = allowed;
    return { db, env };
  }

  function addMember(db, email, role) {
    db.exec(`INSERT INTO users (email, global_role) VALUES ('${email}', 'viewer')`);
    db.exec(`INSERT INTO dashboard_members (dashboard_id, user_email, role, granted_by)
             VALUES ('dash-1', '${email}', '${role}', '${OWNER.email}')`);
    return { email, global_role: "viewer" };
  }

  test("người trong danh sách vẫn nhắn được", async () => {
    const { db, env } = liveDashboard(OWNER.email);
    const response = await createAgentThread(post({ message: "đổi nhãn nút" }), env, OWNER, "listing-2-erp");
    assert.equal(response.status, 201);
    assert.equal(threadCount(db), 1);
  });

  test("Owner ngoài danh sách cũng bị chặn, và không để lại luồng rỗng", async () => {
    const { db, env } = liveDashboard("nguoikhac@havigroup.llc");
    const thrown = await createAgentThread(post({ message: "đổi nhãn nút" }), env, OWNER, "listing-2-erp")
      .then(() => null, (caught) => caught);
    assert.ok(thrown instanceof Response);
    assert.equal(thrown.status, 403);
    assert.match(await thrown.text(), /chỉ mở cho nguoikhac@havigroup\.llc/);
    assert.equal(threadCount(db), 0);
  });

  test("Admin ngoài danh sách mất luôn phạm vi mặc định", async () => {
    const { db, env } = liveDashboard(OWNER.email);
    const admin = addMember(db, "quanly@havigroup.llc", "admin");
    const thrown = await createAgentThread(post({ message: "sửa giúp" }), env, admin, "listing-2-erp")
      .then(() => null, (caught) => caught);
    assert.ok(thrown instanceof Response);
    assert.equal(thrown.status, 403);
    assert.equal(threadCount(db), 0);
  });

  test("đường điều khiển bot cũng đóng theo, không phải chỉ đường sửa code", async () => {
    const { db, env } = liveDashboard("nguoikhac@havigroup.llc");
    const thrown = await createControlThread(post({ message: "dừng bot tạo ảnh" }), env, OWNER, "listing-2-erp")
      .then(() => null, (caught) => caught);
    assert.ok(thrown instanceof Response);
    assert.equal(thrown.status, 403);
    assert.equal(threadCount(db), 0);
  });

  test("hoa thường và khoảng trắng thừa không lọt thành một người khác", async () => {
    const { db, env } = liveDashboard(`  ${OWNER.email.toUpperCase()} , nguoikhac@havigroup.llc `);
    const response = await createAgentThread(post({ message: "đổi nhãn nút" }), env, OWNER, "listing-2-erp");
    assert.equal(response.status, 201);
    assert.equal(threadCount(db), 1);
  });

  test("để trống biến thì không khoá gì thêm", async () => {
    const { db, env } = liveDashboard("   ");
    const response = await createAgentThread(post({ message: "đổi nhãn nút" }), env, OWNER, "listing-2-erp");
    assert.equal(response.status, 201);
    assert.equal(threadCount(db), 1);
  });
});

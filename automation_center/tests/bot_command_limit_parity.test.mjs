// B4 — trần số lệnh bot phải là một hằng số dùng chung, không phải hai số 5.
//
//   /Users/admin/.local/node/bin/node --test --experimental-sqlite automation_center/tests/bot_command_limit_parity.test.mjs
//
// PRD: tasks/prd-agent-improvements.md §B4.  **Các bài đầu đang ĐỎ và phải đỏ**;
// hai bài cuối là hàng rào chống sửa quá tay và đang xanh.
//
// Số 5 được chép ở hai nơi, không nơi nào đặt tên:
//
//   orchestrator_runner.py:1188  report(..., bot_commands=commands[:5])
//   worker.js:1774               body.bot_commands.slice(0, 5)
//
// Hai bên cắt độc lập.  Nới một bên mà quên bên kia thì lệnh bị CẮT LẶNG —
// không lỗi, không log, người dùng chỉ thấy bot làm thiếu việc.  Đây đúng loại
// trôi mà agent_busy_parity.test.mjs được viết ra để bắt.
//
// Vì sao qua CONTROL_LIMITS chứ không phải một named export riêng
// ----------------------------------------------------------------
// Bản đầu của ba bài dưới đòi ``workerModule.MAX_BOT_COMMANDS_PER_TURN`` —
// tức một named export kiểu số ở entrypoint.  Làm đúng như thế thì Worker
// CHẾT lúc khởi động: workerd coi mọi named export của entrypoint là một
// service entrypoint và chỉ nhận function hoặc object ("Incorrect type for
// map entry").  Đã đo: thêm cái tên ấy vào khối ``export {}`` làm đỏ bài
// ``module xuất ra vẫn nạp được vào workerd`` (agent_control.test.mjs:259) —
// bài ấy có từ ``002804c``, tức là trước nhánh này, và nó có lý.
//
// Nên phần cài đặt ở ``306df94`` là ĐÚNG: hằng số có tên ở worker.js:28 và đi
// ra ngoài qua ``CONTROL_LIMITS``, kèm chú thích ngay cạnh nói rõ vì sao.
// Cái sai là ĐƯỜNG ĐỌC trong ba bài này, không phải code.  Ba khẳng định giữ
// nguyên: vẫn là số, vẫn khớp con số runner cắt, vẫn phải bằng 5.
import test, { describe } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// SỬA ĐƯỜNG ĐỌC, KHÔNG NỚI KHẲNG ĐỊNH — xem chú thích "Vì sao qua
// CONTROL_LIMITS" ở đầu file.  Ba khẳng định dưới giữ nguyên độ chặt.
import worker, { BOT_ACTIONS, CONTROL_LIMITS } from "../src/worker.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const MIGRATIONS = join(HERE, "..", "migrations");
const RUNNER_SOURCE = readFileSync(new URL("../runner/orchestrator_runner.py", import.meta.url), "utf8");
const SECRET = "runner-secret-cho-test";

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
    INSERT INTO users (email, display_name, global_role) VALUES ('chu@havigroup.llc', 'Chủ', 'owner');
    INSERT INTO dashboards (id, slug, name, status, created_by)
      VALUES ('dash', 'dash', 'Dashboard thử', 'active', 'chu@havigroup.llc');
    INSERT INTO runners (runner_key, label, status, last_seen_at)
      VALUES ('content-image-agent-runner', 'Runner tạo ảnh', 'online', '${at}');
    INSERT INTO agent_threads (id, dashboard_id, title, created_by)
      VALUES ('thread', 'dash', 'Dừng bot', 'chu@havigroup.llc');
    INSERT INTO code_change_requests
      (id, dashboard_id, thread_id, runner_key, requested_by, requested_role, instruction, status)
      VALUES ('request', 'dash', 'thread', 'orchestrator-runner', 'chu@havigroup.llc', 'owner', 'Dừng hết bot lại', 'planning');
  `);
  for (let index = 0; index < 8; index += 1) {
    db.exec(`INSERT INTO bots (id, dashboard_id, name, purpose, runner_key, status, created_by)
             VALUES ('bot-${index}', 'dash', 'Bot ${index}', 'Tạo ảnh', 'content-image-agent-runner', 'running', 'chu@havigroup.llc')`);
  }
  return { db, env: { DB: d1(db), RUNNER_SHARED_SECRET: SECRET } };
}

const botAction = (env, commands) => worker.fetch(
  new Request("https://x/api/runner/code/request", {
    method: "POST",
    headers: { "content-type": "application/json", "x-automation-runner-secret": SECRET },
    body: JSON.stringify({
      runner_key: "orchestrator-runner",
      status: "bot_action",
      plan_summary: "Agent xin dừng một loạt bot",
      bot_commands: commands,
    }),
  }),
  env,
);

const pauseCommands = (count) => Array.from({ length: count }, (_unused, index) => ({ bot_id: `bot-${index}`, command: "pause" }));

describe("trần lệnh bot có tên và khớp hai phía", () => {
  test("Worker xuất MAX_BOT_COMMANDS_PER_TURN", () => {
    assert.equal(
      typeof CONTROL_LIMITS.MAX_BOT_COMMANDS_PER_TURN,
      "number",
      "B4.1: trần phải có tên và với tới được từ ngoài, qua CONTROL_LIMITS",
    );
  });

  test("runner cắt theo đúng con số đó", () => {
    const found = RUNNER_SOURCE.match(/bot_commands=commands\[:(\d+)\]/);
    assert.ok(found, "không đọc được chỗ runner cắt danh sách lệnh");
    assert.equal(
      Number(found[1]),
      CONTROL_LIMITS.MAX_BOT_COMMANDS_PER_TURN,
      "hai bên cắt bằng hai con số chép tay; nới một bên là cắt lặng ở bên kia",
    );
  });

  // B4.3 — không đổi giá trị, chỉ đặt tên cho nó.
  test("giá trị vẫn là 5", () => {
    assert.equal(CONTROL_LIMITS.MAX_BOT_COMMANDS_PER_TURN, 5);
  });
});

describe("vượt trần thì báo lỗi, không cắt lặng", () => {
  // Ca chạm thật: runner cũ nói chuyện với Worker mới.  Runner mới đã cắt từ
  // :1188 nên đường bình thường không tới đây — đúng lúc cần một lỗi ồn ào.
  test("6 lệnh bị từ chối kèm câu lỗi nói rõ trần", async () => {
    const { db, env } = fresh();
    const response = await botAction(env, pauseCommands(6));
    assert.equal(response.status, 200, "đường runner luôn trả 200 và nói kết quả trong body");
    const body = await response.json();
    assert.equal(body.blocked, true, "B4.2: phải chặn, không slice");
    assert.match(String(body.error || ""), /5/, "câu lỗi phải nói trần là bao nhiêu");
    assert.equal(
      db.prepare("SELECT COUNT(*) AS n FROM bot_runs").get().n,
      0,
      "bị chặn thì không được chạy nửa đầu danh sách",
    );
    const row = db.prepare("SELECT status FROM code_change_requests WHERE id = 'request'").get();
    assert.equal(row.status, "failed", "yêu cầu phải kết thúc rõ ràng chứ không treo ở planning");
    db.close();
  });

  test("đúng 5 lệnh vẫn chạy bình thường", async () => {
    const { db, env } = fresh();
    const response = await botAction(env, pauseCommands(5));
    const body = await response.json();
    assert.equal(body.blocked, undefined, "đúng trần thì không được coi là vượt trần");
    assert.equal(body.results.length, 5);
    assert.equal(
      db.prepare("SELECT status FROM code_change_requests WHERE id = 'request'").get().status,
      "bot_done",
    );
    db.close();
  });

  // Không được đánh đổi: danh sách rỗng vẫn phải đi qua đường cũ, không biến
  // thành "vượt trần".
  test("không có lệnh nào thì vẫn là bot_done với lời giải thích cũ", async () => {
    const { db, env } = fresh();
    const response = await botAction(env, []);
    const body = await response.json();
    assert.equal(body.blocked, undefined);
    assert.deepEqual(body.results, []);
    const message = db.prepare("SELECT content FROM agent_messages WHERE request_id = 'request' ORDER BY created_at DESC LIMIT 1").get();
    assert.match(String(message?.content || ""), /không đưa ra lệnh bot nào/i);
    db.close();
  });
});

// B4.3 — hàng rào chống sửa quá tay, XANH hôm nay và phải ở lại xanh.
test("danh sách động từ bot không đổi", () => {
  assert.deepEqual(BOT_ACTIONS, ["run", "pause"]);
});

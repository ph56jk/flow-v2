// Động từ bot do Agent điều phối chọn phải có nghĩa thật ở Worker.
//
// ``resume`` từng lọt qua whitelist rồi rơi vào nhánh ``run``: khi thiếu
// prompt thì trả một lỗi tạo ảnh vô nghĩa, còn có prompt thì tạo ảnh thật. Ba
// test này khoá cả lõi lẫn đường runner ghi kết quả về code_change_requests.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import worker, { BOT_ACTIONS, runBotCommand } from "../src/worker.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const MIGRATIONS = join(HERE, "..", "migrations");
const SECRET = "runner-secret-cho-test";
const INVALID_ACTION = `Action bot không hợp lệ: chỉ nhận ${BOT_ACTIONS.join(", ")}.`;

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
    INSERT INTO bots (id, dashboard_id, name, purpose, runner_key, status, created_by)
      VALUES ('bot', 'dash', 'Bot tạo ảnh', 'Tạo ảnh Content', 'content-image-agent-runner', 'paused', 'chu@havigroup.llc');
    INSERT INTO runners (runner_key, label, status, last_seen_at)
      VALUES ('content-image-agent-runner', 'Runner tạo ảnh', 'online', '${at}');
    INSERT INTO agent_threads (id, dashboard_id, title, created_by)
      VALUES ('thread', 'dash', 'Mở bot', 'chu@havigroup.llc');
    INSERT INTO code_change_requests
      (id, dashboard_id, thread_id, runner_key, requested_by, requested_role, instruction, status)
      VALUES ('request', 'dash', 'thread', 'orchestrator-runner', 'chu@havigroup.llc', 'owner', 'Mở bot tạo ảnh', 'planning');
  `);
  return {
    db,
    env: { DB: d1(db), RUNNER_SHARED_SECRET: SECRET },
    dashboard: { id: "dash" },
  };
}

function botRunCount(db) {
  return db.prepare("SELECT COUNT(*) AS count FROM bot_runs").get().count;
}

test("BOT_ACTIONS chỉ có hai nhánh thật của runBotCommand", () => {
  assert.deepEqual(BOT_ACTIONS, ["run", "pause"]);
});

test("resume bị từ chối trước nhánh run và không tạo bot_run", async () => {
  const { db, env, dashboard } = fresh();
  const result = await runBotCommand(env, dashboard, "agent:chu@havigroup.llc", "bot", "resume", {
    prompt: "Một prompt hợp lệ không được phép biến resume thành run",
  });

  assert.equal(result.ok, false);
  assert.equal(result.message, INVALID_ACTION);
  assert.match(result.message, /run/);
  assert.match(result.message, /pause/);
  assert.equal(botRunCount(db), 0, "resume không được đi vào nhánh run để chèn hàng");
  db.close();
});

test("bot_action ghi kết quả động từ lạ thay vì chạy bot", async () => {
  const { db, env } = fresh();
  const request = new Request("https://x/api/runner/code/request", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-automation-runner-secret": SECRET,
    },
    body: JSON.stringify({
      runner_key: "orchestrator-runner",
      status: "bot_action",
      plan_summary: "Agent thử tiếp tục bot tạo ảnh",
      bot_commands: [{ bot_id: "bot", command: "resume", prompt: "Không được chạy prompt này" }],
    }),
  });

  const response = await worker.fetch(request, env);
  assert.equal(response.status, 200, await response.text());
  const row = db.prepare("SELECT status, bot_commands_json FROM code_change_requests WHERE id = 'request'").get();
  const [outcome] = JSON.parse(row.bot_commands_json);
  assert.equal(row.status, "bot_done");
  assert.deepEqual(outcome, {
    bot_id: "bot",
    command: "resume",
    ok: false,
    message: INVALID_ACTION,
  });
  assert.equal(botRunCount(db), 0, "đường bot_action không được rơi qua run");
  db.close();
});

test("run thiếu prompt vẫn giữ thông báo tạo ảnh cũ", async () => {
  const { db, env, dashboard } = fresh();
  const result = await runBotCommand(env, dashboard, "chu@havigroup.llc", "bot", "run", {});

  assert.equal(result.ok, false);
  assert.equal(result.message, "Hãy nhập yêu cầu tạo ảnh rõ ràng (ít nhất 5 ký tự).");
  assert.equal(botRunCount(db), 0);
  db.close();
});

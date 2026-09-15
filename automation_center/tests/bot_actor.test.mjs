// Hồi quy cho actor `agent:<email>`: bot_runs.requested_by có FK tới users(email)
// nên phải ghi email thật, nhưng audit vẫn được phép mang tiền tố agent:.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { runBotCommand } from "../src/worker.js";

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

function fixture(email) {
  const db = new DatabaseSync(":memory:");
  for (const file of readdirSync(MIGRATIONS).filter((name) => name.endsWith(".sql")).sort()) {
    db.exec(readFileSync(join(MIGRATIONS, file), "utf8"));
  }
  db.exec(`
    INSERT INTO users (email, display_name, global_role) VALUES ('${email}', 'Người gửi', 'owner');
    INSERT INTO dashboards (id, slug, name, status, created_by) VALUES ('dash', 'dash', 'Dash', 'active', '${email}');
    INSERT INTO bots (id, dashboard_id, name, purpose, runner_key, status, created_by)
      VALUES ('bot', 'dash', 'Bot', 'Tạo ảnh', 'content-image-runner', 'paused', '${email}');
    INSERT INTO runners (runner_key, label, status, last_seen_at)
      VALUES ('content-image-runner', 'Ảnh', 'online', '${new Date().toISOString()}');
  `);
  return { db, env: { DB: d1(db) }, dashboard: { id: "dash" } };
}

async function queuedBy(actor, userEmail) {
  const { db, env, dashboard } = fixture(userEmail);
  const result = await runBotCommand(env, dashboard, actor, "bot", "run", { prompt: "Tạo một ảnh sản phẩm" });
  assert.equal(result.ok, true);
  const value = db.prepare("SELECT requested_by FROM bot_runs").get().requested_by;
  db.close();
  return value;
}

test("chỉ tiền tố agent: ở đầu email mới bị bỏ trước khi ghi bot run", async () => {
  assert.equal(await queuedBy("agent:a@b.c", "a@b.c"), "a@b.c");
  assert.equal(await queuedBy("a@b.c", "a@b.c"), "a@b.c");
  assert.equal(await queuedBy("nguoi-agent:a@b.c", "nguoi-agent:a@b.c"), "nguoi-agent:a@b.c");
});

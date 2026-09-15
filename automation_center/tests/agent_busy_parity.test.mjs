// Danh sách trạng thái khoá luồng phải đến từ Worker, không được có bản sao
// lặng lẽ trong app.js.  Đây là parity JS↔JS tương tự ý nghĩa parity Worker↔runner.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { AGENT_BUSY_STATUSES } from "../src/worker.js";

const SOURCE = readFileSync(new URL("../public/app.js", import.meta.url), "utf8");

function slice(from, to) {
  const start = SOURCE.indexOf(from);
  assert.notEqual(start, -1, `không tìm thấy ${from}`);
  const end = SOURCE.indexOf(to, start);
  assert.notEqual(end, -1, `không tìm thấy ${to} sau ${from}`);
  return SOURCE.slice(start, end);
}

test("app nhận nguyên danh sách busy do Worker trả, kể cả awaiting_approval", () => {
  assert.ok(Array.isArray(AGENT_BUSY_STATUSES));
  assert.ok(AGENT_BUSY_STATUSES.includes("awaiting_approval"));
  assert.doesNotMatch(SOURCE, /const AGENT_BUSY\s*=/, "app không được tự chép danh sách");

  const state = { agent: { busy_statuses: [...AGENT_BUSY_STATUSES] } };
  const { agentBusyStatuses } = new Function(
    "state",
    `${slice("function agentBusyStatuses(", "function parseList(")}
     return { agentBusyStatuses };`,
  )(state);
  assert.deepEqual(agentBusyStatuses(), AGENT_BUSY_STATUSES);
  assert.equal(agentBusyStatuses().includes("awaiting_approval"), true);
  state.agent = {};
  assert.deepEqual(agentBusyStatuses(), AGENT_BUSY_STATUSES, "phản hồi Worker cũ/thiếu trường vẫn phải tự làm mới an toàn");
  assert.equal((SOURCE.match(/agentBusyStatuses\(\)\.includes/g) || []).length, 3, "cả ba điểm khoá/tự làm mới dùng cùng nguồn");
});

// Hợp đồng của client HTTP cho Automation Center.
//
// app.js chạy thẳng trong trình duyệt nên không import được như module.  Cắt
// riêng hai hàm cần kiểm và chạy trong ngữ cảnh nhỏ, đúng lối chat_ui.test.mjs.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SOURCE = readFileSync(new URL("../public/app.js", import.meta.url), "utf8");

function slice(from, to) {
  const start = SOURCE.indexOf(from);
  assert.notEqual(start, -1, `không tìm thấy ${from}`);
  const end = SOURCE.indexOf(to, start);
  assert.notEqual(end, -1, `không tìm thấy ${to} sau ${from}`);
  return SOURCE.slice(start, end);
}

function client(fetchImpl, state = {}) {
  const toasts = [];
  const refreshes = [];
  const { api } = new Function(
    "fetch", "location",
    `${slice("async function api(", "function showToast(")}
     return { api };`,
  )(fetchImpl, { href: "https://automation.havigroup.llc/", origin: "https://automation.havigroup.llc" });
  const { sendAgentMessage } = new Function(
    "state", "api", "render", "showToast", "refreshAgent",
    `${slice("async function sendAgentMessage(", "async function deleteThread(")}
     return { sendAgentMessage };`,
  )(state, api, () => {}, (message, isError) => toasts.push({ message, isError }), async (value) => refreshes.push(value));
  return { api, sendAgentMessage, toasts, refreshes };
}

function response({ status = 200, contentType = "application/json", body = {}, redirected = false, url = "https://automation.havigroup.llc/api" } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    redirected,
    url,
    headers: new Headers(contentType ? { "content-type": contentType } : {}),
    async json() {
      if (body instanceof Error) throw body;
      return body;
    },
  };
}

test("2xx JSON hợp lệ được trả nguyên payload", async () => {
  const { api } = client(async () => response({ body: { thread_id: "t-1" } }));
  assert.deepEqual(await api("/api/test"), { thread_id: "t-1" });
});

test("HTML 2xx của trang đăng nhập phải báo phiên hết hạn", async () => {
  const { api } = client(async () => response({ contentType: "text/html", body: new Error("HTML không phải JSON") }));
  await assert.rejects(api("/api/test"), /Phiên đăng nhập đã hết hạn/);
});

test("redirect sang origin khác phải báo phiên hết hạn", async () => {
  const { api } = client(async () => response({ redirected: true, url: "https://access.cloudflare.com/cdn-cgi/access/login", body: {} }));
  await assert.rejects(api("/api/test"), /Phiên đăng nhập đã hết hạn/);
});

test("204 không thân là thành công hợp lệ", async () => {
  const { api } = client(async () => response({ status: 204, contentType: "", body: new Error("không có thân") }));
  assert.deepEqual(await api("/api/test"), {});
});

test("4xx JSON vẫn giữ nguyên thông điệp của server", async () => {
  const { api } = client(async () => response({ status: 409, body: { error: "Luồng đang bận." } }));
  await assert.rejects(api("/api/test"), /^Error: Luồng đang bận\.$/);
});

test("tạo thread không trả thread_id thì bản nháp vẫn còn", async () => {
  const state = {
    agentSending: false,
    draft: "Hãy sửa nhãn nút để dễ đọc hơn",
    selected: "listing-2-erp",
    thread: null,
  };
  const { sendAgentMessage, toasts, refreshes } = client(async () => response({ body: {} }), state);

  await sendAgentMessage();

  assert.equal(state.draft, "Hãy sửa nhãn nút để dễ đọc hơn");
  assert.equal(refreshes.length, 0);
  assert.ok(toasts.some((toast) => toast.isError), "phải báo lỗi thay vì xoá im lặng");
});

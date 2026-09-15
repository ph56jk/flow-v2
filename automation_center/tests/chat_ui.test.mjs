import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// app.js là script chạy trong trình duyệt: dòng đầu tiên đã gọi document.
// Thay vì dựng cả một DOM giả, chỉ cắt ra đúng những hàm quyết định thuần tuý
// rồi chạy chúng.  Cắt theo tên hàm nên đổi tên hàm sẽ làm test đỏ — đó là chủ
// ý: những quy tắc này là hợp đồng của khung chat chứ không phải chi tiết vặt.
const SOURCE = readFileSync(new URL("../public/app.js", import.meta.url), "utf8");
const CSS = readFileSync(new URL("../public/styles.css", import.meta.url), "utf8");

function slice(from, to) {
  const start = SOURCE.indexOf(from);
  assert.notEqual(start, -1, `không tìm thấy "${from}" trong app.js`);
  const end = SOURCE.indexOf(to, start);
  assert.notEqual(end, -1, `không tìm thấy "${to}" sau "${from}"`);
  return SOURCE.slice(start, end);
}

const { dayLabel, requestNeedsCard } = new Function(`
  ${slice("function parseList(", "function diffHtml(")}
  ${slice("const DAY_MS =", "function chatRow(")}
  return { dayLabel, requestNeedsCard };
`)();

const iso = (offsetDays, hour = 10) => {
  const at = new Date();
  at.setHours(hour, 0, 0, 0);
  at.setDate(at.getDate() - offsetDays);
  return at.toISOString();
};

test("mốc ngày đọc như trong một đoạn chat thật", () => {
  assert.equal(dayLabel(iso(0)), "Hôm nay");
  assert.equal(dayLabel(iso(1)), "Hôm qua");
  assert.notEqual(dayLabel(iso(9)), "Hôm nay");
  assert.notEqual(dayLabel(iso(9)), "Hôm qua");
  // Ngày hỏng không được ném lỗi giữa lúc dựng luồng tin nhắn.
  assert.equal(dayLabel("khong-phai-ngay"), "");
  assert.equal(dayLabel(null), "");
});

test("mốc ngày không lệch vì giờ trong ngày", () => {
  // 00:05 hôm nay vẫn là "Hôm nay", 23:55 hôm qua vẫn là "Hôm qua" — so sánh
  // phải theo mốc nửa đêm chứ không theo khoảng cách 24 giờ.
  assert.equal(dayLabel(iso(0, 0)), "Hôm nay");
  assert.equal(dayLabel(iso(0, 23)), "Hôm nay");
  assert.equal(dayLabel(iso(1, 23)), "Hôm qua");
});

test("yêu cầu còn phải quyết thì luôn có thẻ", () => {
  for (const status of ["awaiting_approval", "applying", "applied", "rejected", "cancelled", "failed"]) {
    assert.equal(requestNeedsCard({ status }), true, `${status} phải hiện thẻ`);
  }
});

test("câu trả lời suông không đẻ thêm một thẻ rỗng", () => {
  // Agent trả lời một câu hỏi thì câu trả lời đã là tin nhắn ngay phía trên;
  // thêm một thẻ "Đã trả lời" trắng trơn chỉ làm đoạn chat dài gấp đôi.
  assert.equal(requestNeedsCard({ status: "answered" }), false);
  assert.equal(requestNeedsCard({ status: "queued" }), false);
  assert.equal(requestNeedsCard({ status: "planning" }), false);
});

test("có thứ để xem thì hiện thẻ dù trạng thái là gì", () => {
  assert.equal(requestNeedsCard({ status: "answered", diff_length: 400 }), true);
  assert.equal(requestNeedsCard({ status: "answered", files_changed: 2 }), true);
  assert.equal(requestNeedsCard({ status: "answered", error: "hết giờ" }), true);
  assert.equal(requestNeedsCard({ status: "answered", bot_commands_json: '["dừng bot"]' }), true);
  // JSON hỏng chỉ là "không có lệnh bot", không phải một ngoại lệ giữa luồng.
  assert.equal(requestNeedsCard({ status: "answered", bot_commands_json: "{" }), false);
  assert.equal(requestNeedsCard({ status: "answered", bot_commands_json: "[]" }), false);
});

test("Enter gửi tin nhưng không cắt ngang bộ gõ tiếng Việt", () => {
  // Bộ gõ dấu dựng một chữ bằng nhiều phím; nếu Enter gửi ngay giữa lúc đó thì
  // chữ đang dựng dở bay mất.  isComposing là cái chặn đó.
  const handler = slice('app.addEventListener("keydown"', "app.addEventListener(\"scroll\"");
  assert.match(handler, /event\.isComposing/);
  assert.match(handler, /event\.shiftKey/);
  assert.match(handler, /preventDefault/);
});

test("gõ phím không dựng lại cả màn hình", () => {
  // render() thay toàn bộ innerHTML; gọi nó ở mỗi phím gõ cũng giết bộ gõ dấu
  // giống hệt như trên.  Handler input phải sửa tại chỗ.
  const handler = slice('app.addEventListener("input"', 'app.addEventListener("keydown"');
  assert.doesNotMatch(handler, /\brender\(\)/);
  assert.match(handler, /growComposer/);
});

test("khung chat chiếm trọn màn hình điện thoại", () => {
  // Hai thanh cuộn lồng nhau là cách chắc chắn nhất để mất ô soạn khi đang gõ.
  assert.match(CSS, /\.app-shell\.chat-mode\s*\{[^}]*height:\s*100dvh/);
  assert.match(CSS, /\.app-shell\.chat-mode\s*\{[^}]*overflow:\s*hidden/);
  // Trên điện thoại thanh điều hướng ngang bị giấu: nút quay lại ở thanh tiêu
  // đề đã làm đúng việc đó rồi.
  assert.match(CSS, /\.app-shell\.chat-mode \.sidebar\s*\{\s*display:\s*none/);
});

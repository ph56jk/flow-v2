// B1 — ngưỡng watchdog phải bám theo ngân sách model, không phải một số viết tay.
//
//   /Users/admin/.local/node/bin/node --test --experimental-sqlite automation_center/tests/watchdog_budget.test.mjs
//
// PRD: tasks/prd-agent-improvements.md §B1.  **Mọi bài ở đây đang ĐỎ và phải
// đỏ** — chúng tả hành vi *sau* khi B1 được cài.
//
// Chuyện đã xảy ra: chú thích ở worker.js:877-879 tính ngưỡng từ "4 vòng model
// × 300 giây + test 900 giây = 35 phút" rồi chọn 45 phút.  Commit 976fc70 nới
// một lượt model lên 1800 giây và **chỉ** sửa phía Python.  worker.js không
// đổi một dòng.  Ngân sách thật bây giờ là 4×1800+900 = 8100 giây = 135 phút,
// đứng trước một watchdog 45 phút.  Ngay cả MỘT vòng model rồi chạy test đã là
// đúng 45 phút, dư bằng không.
//
// Watchdog không đọc được env của runner, nên cách duy nhất để hai bên không
// trôi nữa là công bố ngân sách ở một chỗ trong worker.js rồi ghim nó vào file
// Python bằng test parity — đúng lối agent_busy_parity.test.mjs đã đặt ra.
import test, { describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Nhập cả namespace: hằng số B1 chưa tồn tại, và một named import thiếu sẽ
// giết cả file bằng SyntaxError lúc link — che mất mọi bài khác trong file.
import * as worker from "../src/worker.js";
import { healthThresholds } from "../src/worker.js";

const RUNNER_SOURCE = readFileSync(new URL("../runner/orchestrator_runner.py", import.meta.url), "utf8");
const WORKER_SOURCE = readFileSync(new URL("../src/worker.js", import.meta.url), "utf8");
const MINUTE = 60 * 1000;

// Đọc con số runner đang thật sự dùng, không chép lại.  Chép lại thì test này
// trở thành bản sao thứ ba của cùng một con số — đúng cái bệnh nó đi chữa.
function pythonNumber(name, pattern) {
  const found = RUNNER_SOURCE.match(pattern);
  assert.ok(found, `không đọc được ${name} trong orchestrator_runner.py`);
  return Number(found[1]);
}

const RUNNER_BUDGET = {
  maxRounds: pythonNumber("MAX_ROUNDS", /^MAX_ROUNDS\s*=\s*(\d+)/m),
  modelTimeoutS: pythonNumber("OPENAI_TIMEOUT", /^OPENAI_TIMEOUT\s*=\s*max\(\s*\d+\s*,\s*int\(os\.environ\.get\("OPENAI_TIMEOUT_SECONDS",\s*"(\d+)"\)\)\)/m),
  testTimeoutS: pythonNumber("TEST_TIMEOUT", /^TEST_TIMEOUT\s*=\s*max\(\s*\d+\s*,\s*int\(os\.environ\.get\("AGENT_TEST_TIMEOUT_SECONDS",\s*"(\d+)"\)\)\)/m),
};

const worstCaseSilenceMs = (budget) => (budget.maxRounds * budget.modelTimeoutS + budget.testTimeoutS) * 1000;

describe("ngân sách model phải được công bố ở đúng một chỗ", () => {
  test("worker.js xuất RUNNER_MODEL_BUDGET", () => {
    const budget = worker.RUNNER_MODEL_BUDGET;
    assert.ok(budget, "B1.2: Worker không đọc được env runner, nên ngân sách phải là hằng số công bố");
    for (const field of ["maxRounds", "modelTimeoutS", "testTimeoutS"]) {
      assert.equal(typeof budget[field], "number", `thiếu trường ${field}`);
      assert.ok(budget[field] > 0, `${field} phải dương`);
    }
  });

  // Đây là bài parity thật sự: nó đỏ vào đúng ngày ai đó sửa một bên.
  test("ba con số khớp với orchestrator_runner.py", () => {
    assert.deepEqual(worker.RUNNER_MODEL_BUDGET, RUNNER_BUDGET);
  });
});

describe("ngưỡng đóng yêu cầu mồ côi phải bao được ngân sách đó", () => {
  test("45 phút không bao nổi 135 phút im lặng hợp lệ", () => {
    const { codeRequestOrphanMs } = healthThresholds();
    assert.ok(
      codeRequestOrphanMs >= worstCaseSilenceMs(RUNNER_BUDGET),
      `watchdog đóng ở ${Math.round(codeRequestOrphanMs / MINUTE)} phút trong khi runner được phép im ${Math.round(worstCaseSilenceMs(RUNNER_BUDGET) / MINUTE)} phút`,
    );
  });

  // Bằng đúng ngân sách vẫn là hỏng: git, mạng và một lần thử lại đều nằm
  // ngoài ba con số kia.  PRD đề nghị hệ số dư 1.3.
  test("còn chừa dư ít nhất 30% cho git và mạng", () => {
    const { codeRequestOrphanMs } = healthThresholds();
    assert.ok(codeRequestOrphanMs >= worstCaseSilenceMs(RUNNER_BUDGET) * 1.3);
  });

  test("ngưỡng suy ra từ ngân sách chứ không viết tay 45 phút", () => {
    const { codeRequestOrphanMs } = healthThresholds();
    assert.notEqual(codeRequestOrphanMs, 45 * MINUTE, "B1.1: con số 45 phút là con số của ngân sách cũ");
  });

  // B1.4.  Chú thích sai nguy hiểm hơn không có chú thích: nó nói với người
  // đọc sau rằng phép tính đã được làm rồi.
  test("chú thích không còn nhắc con số cũ", () => {
    const around = WORKER_SOURCE.slice(
      Math.max(0, WORKER_SOURCE.indexOf("CODE_REQUEST_ORPHAN_MS") - 500),
      WORKER_SOURCE.indexOf("CODE_REQUEST_ORPHAN_MS") + 200,
    );
    assert.ok(!around.includes("300 giây"), "chú thích còn ghi 300 giây, ngân sách đã là 1800");
    assert.ok(!around.includes("35 phút"), "chú thích còn ghi 35 phút, ngân sách đã là 135");
  });
});

// B1.3 — cách rẻ nhất và cũng tốt nhất: runner tự lên tiếng giữa các vòng.
// worker.js đã bump updated_at cho đường "planning", nên chỉ thiếu đúng lời
// gọi.  Làm được việc này thì ngưỡng chỉ cần bao MỘT vòng.
test("runner báo planning sau mỗi vòng model", () => {
  const from = RUNNER_SOURCE.indexOf("def plan_change(");
  const to = RUNNER_SOURCE.indexOf("def process_output_text(");
  assert.ok(from !== -1 && to > from, "không tìm thấy plan_change trong orchestrator_runner.py");
  // So bằng boolean chứ không assert.match: thân hàm dài, và một bài đỏ in cả
  // thân hàm ra log thì lần sau không ai đọc log nữa.
  assert.ok(
    /report\([^)]*"planning"/.test(RUNNER_SOURCE.slice(from, to)),
    "vòng lặp for _ in range(MAX_ROUNDS) không hề báo về, nên watchdog thấy một khoảng im lặng liền mạch",
  );
});

// B1.5 — hai ngưỡng còn lại đo việc khác và đang đúng.  Bài này XANH hôm nay
// và phải ở lại xanh: nó là hàng rào chống sửa quá tay.
test("không đụng vào ngưỡng runner offline và run mồ côi", () => {
  const { runnerStaleMs, runOrphanMs } = healthThresholds();
  assert.equal(runnerStaleMs, 5 * MINUTE);
  assert.equal(runOrphanMs, 60 * MINUTE);
});

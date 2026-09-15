// B2 — saveCodeScope phải chặn cả glob BAO TRÙM file được bảo vệ.
//
//   /Users/admin/.local/node/bin/node --test --experimental-sqlite automation_center/tests/code_scope_covering_glob.test.mjs
//
// PRD: tasks/prd-agent-improvements.md §B2.  **Mọi bài ở đây đang ĐỎ và phải đỏ.**
//
// worker.js:1644 so khớp bằng `===`, tức là so khớp CHỮ.  Cấp thẳng
// "automation_center/src/worker.js" thì bị chặn; cấp "automation_center/**",
// "automation_center/src/*" hay "**" thì qua, dù cả ba đều bao trùm đúng file
// ấy.
//
// Nói cho cân bằng: lớp này thủng nhưng không phải lớp duy nhất.
// auditChangedFiles vẫn gắn cờ touches_protected, worker.js:1593 vẫn cấm người
// không phải Owner duyệt thay đổi chạm file bảo vệ, và runner tự loại file bảo
// vệ khỏi danh sách sửa được.  Đây là làm dày hàng rào, không phải bịt một lỗ
// đang chảy — nhưng nó là lớp mà người vận hành NHÌN THẤY và tin khi cấp
// quyền, nên một lời "đã cấp" sai chỗ này đắt hơn vẻ ngoài của nó.
import test, { describe } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// Namespace: coveringProtectedGlobs và saveCodeScope chưa được xuất, và một
// named import thiếu sẽ giết cả file lúc link.
import * as worker from "../src/worker.js";
import { PROTECTED_GLOBS, OWNER_DEFAULT_SCOPE, matchesAnyGlob, isProtectedPath } from "../src/worker.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const MIGRATIONS = join(HERE, "..", "migrations");
const OWNER = { email: "chu@havigroup.llc", global_role: "owner", active: 1 };

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
  `);
  return { db, env: { DB: d1(db) } };
}

const post = (body) => new Request("https://x/api/dashboards/listing-2-erp/agent/scopes", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

const scopeRows = (db) => db.prepare("SELECT subject, allow_globs FROM code_scopes").all();

describe("nhận diện glob bao trùm", () => {
  test("coveringProtectedGlobs được xuất ra", () => {
    assert.equal(
      typeof worker.coveringProtectedGlobs,
      "function",
      "B2.1: phép so khớp bao trùm phải là một hàm kiểm được ngoài môi trường Worker",
    );
  });

  test("glob rộng bao trùm file bảo vệ đều bị gọi tên", () => {
    for (const glob of ["**", "automation_center/**", "automation_center/src/*", "**/*.js", "automation_center/runner/*"]) {
      const covered = worker.coveringProtectedGlobs([glob]);
      assert.ok(covered.length, `"${glob}" bao trùm file được bảo vệ mà vẫn lọt`);
    }
  });

  // Không được đánh đổi: siết quá tay thì không ai cấp được phạm vi nào nữa,
  // và người vận hành sẽ đi đường vòng — kết cục tệ hơn hiện tại.
  test("glob thật sự nằm ngoài vùng bảo vệ vẫn cấp được", () => {
    for (const glob of ["flow_web/**", "flow_web/static/app.js", "tests/**", "tasks/*.md"]) {
      assert.deepEqual(worker.coveringProtectedGlobs([glob]), [], `"${glob}" không chạm file bảo vệ nào`);
    }
  });

  test("so khớp chữ như hôm nay vẫn phải bị chặn", () => {
    assert.ok(worker.coveringProtectedGlobs(["automation_center/src/worker.js"]).length);
    assert.ok(worker.coveringProtectedGlobs(["automation_center/migrations/**"]).length);
  });

  // B2.2 — người bị từ chối cần biết THU HẸP THẾ NÀO, nên câu trả lời phải nối
  // được glob xin cấp với file bảo vệ mà nó chạm.
  test("kết quả nói glob nào chạm file bảo vệ nào", () => {
    const [first] = worker.coveringProtectedGlobs(["automation_center/**"]);
    assert.equal(first.glob, "automation_center/**");
    assert.ok(Array.isArray(first.protects) && first.protects.length, "phải kể tên mẫu bảo vệ bị chạm");
    assert.ok(first.protects.some((item) => item.startsWith("automation_center/")));
  });
});

describe("đường lưu phạm vi thật", () => {
  test("Owner cấp automation_center/** bị từ chối và không ghi hàng nào", async () => {
    assert.equal(typeof worker.saveCodeScope, "function", "saveCodeScope phải xuất ra để kiểm được đường thật");
    const { db, env } = fresh();
    const response = await worker.saveCodeScope(
      post({ subject_type: "role", subject: "operator", allow_globs: "automation_center/**" }),
      env, OWNER, "listing-2-erp",
    );
    assert.equal(response.status, 400);
    const text = await response.text();
    assert.match(text, /automation_center\/\*\*/, "câu lỗi phải nhắc lại glob bị từ chối");
    assert.match(text, /worker\.js|migrations|runner/, "và nói nó chạm vào cái gì");
    assert.deepEqual(scopeRows(db), [], "bị từ chối thì không được để lại hàng nào");
    db.close();
  });

  test("cấp phạm vi flow_web/** vẫn lưu bình thường", async () => {
    const { db, env } = fresh();
    const response = await worker.saveCodeScope(
      post({ subject_type: "role", subject: "operator", allow_globs: "flow_web/**", max_files: 3, max_lines: 200 }),
      env, OWNER, "listing-2-erp",
    );
    assert.equal(response.status, 200, await response.text());
    assert.deepEqual(scopeRows(db).map((row) => row.allow_globs), ["flow_web/**"]);
    db.close();
  });
});

// B2.3/B2.4 — hai hàng rào chống sửa quá tay.  Hai bài này XANH hôm nay và
// phải ở lại xanh.
describe("những thứ B2 không được đụng", () => {
  // So parity theo HÀNH VI, không theo chữ: Worker viết "**/.env" còn runner
  // viết "*/.env" vì fnmatch của Python cho "*" nuốt cả dấu "/".  Hai danh
  // sách phải cho cùng câu trả lời trên cùng một đường dẫn — đó mới là thứ
  // đáng ghim.  Bài này XANH hôm nay.
  test("PROTECTED_GLOBS giữ nguyên và vẫn khớp bản sao phía runner", () => {
    const python = readFileSync(new URL("../runner/orchestrator_runner.py", import.meta.url), "utf8");
    const tuple = python.slice(python.indexOf("PROTECTED_GLOBS = ("), python.indexOf(")", python.indexOf("PROTECTED_GLOBS = (")));
    const runnerGlobs = [...tuple.matchAll(/"([^"]+)"/g)].map((match) => match[1]);
    assert.equal(runnerGlobs.length, PROTECTED_GLOBS.length, "hai danh sách đã lệch số mẫu");

    // fnmatch của Python: "*" khớp cả "/", "?" khớp đúng một ký tự.
    const fnmatch = (path, pattern) => new RegExp(
      `^${pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".")}$`,
    ).test(path);

    for (const path of [
      "automation_center/src/worker.js", "automation_center/migrations/0001_init.sql",
      "automation_center/runner/orchestrator_runner.py", "automation_center/scripts/deploy.ps1",
      ".env.local", "flow_web/.env", "secrets/keys.pem", ".github/workflows/ci.yml",
      "wrangler.jsonc", "flow_web/service.py", "tests/test_erp_review.py", "tasks/prd-agent-improvements.md",
    ]) {
      const lower = path.toLowerCase();
      assert.equal(
        isProtectedPath(path),
        runnerGlobs.some((glob) => fnmatch(lower, glob)),
        `Worker và runner trả lời khác nhau cho ${path}`,
      );
    }
  });

  // Luật của chính hệ này nằm trong repo: CLAUDE.md là luật cứng, .claude/**
  // là định nghĩa ba vai agent, scripts/** là lệnh chạy test — thứ trả lời
  // câu "nhánh này có sạch không".  Agent sửa được ba chỗ ấy thì nó tự viết
  // lại luật của mình, tự đổi mô tả vai, hoặc sửa cái thước đo rồi báo xanh.
  // Cùng hạng với worker.js, nên cùng cách chặn.
  test("agent không sửa được luật, định nghĩa vai, hay cái thước đo của chính nó", () => {
    for (const path of [
      "CLAUDE.md", "flow_web/CLAUDE.md",
      ".claude/agents/code-implementer.md", ".claude/agents/test-reviewer.md",
      ".claude/skills/agent-pipeline/SKILL.md", ".claude/settings.json",
      "scripts/chay-test.sh",
    ]) {
      assert.equal(isProtectedPath(path), true, `${path} phải nằm trong vùng bảo vệ`);
    }

    // Và vẫn phải chừa đúng chỗ ba vai được ghi, nếu không thì dây chuyền chết.
    for (const path of [
      "tasks/prd-agent-improvements.md", "docs/chay-test-toan-du-an.md",
      "docs/review-dot-a.md", "flow_web/service.py",
      "automation_center/tests/permissions.test.mjs",
    ]) {
      assert.equal(isProtectedPath(path), false, `${path} phải ghi được`);
    }
  });

  // Điều 3 của CLAUDE.md cấm sửa bốn cái tên.  Hai trong số đó — `.dev.vars`
  // và `data/state.json*` — trước nay chỉ được cấm bằng chữ: `isProtectedPath`
  // cho cả hai đi lọt.  Luật bằng chữ chỉ ràng được người đọc nó, còn một yêu
  // cầu code phạm vi rộng thì chỉ gặp hàm này.
  test("bốn cái tên CLAUDE.md điều 3 cấm sửa đều có hàng rào máy", () => {
    for (const path of [
      ".env.local",
      "automation_center/.dev.vars",
      "automation_center/.dev.vars.local",
      "automation_center/runner/orchestrator.env",
      "data/state.json",
      "data/state.json.bak-20260101",
    ]) {
      assert.equal(isProtectedPath(path), true, `${path} — CLAUDE.md điều 3 cấm sửa`);
    }

    // Và không được quét rộng quá tay: hai sổ này ở cùng thư mục data/ nhưng
    // là dữ liệu làm việc, phải còn ghi được.
    for (const path of ["data/account_book.json", "data/sku_book.json"]) {
      assert.equal(isProtectedPath(path), false, `${path} phải ghi được`);
    }
  });

  test("phạm vi mặc định của Owner vẫn là ** và vẫn không tự áp", () => {
    // ** ở đây là mặc định NGẦM của Owner, không phải quyền cấp qua
    // saveCodeScope, và các lớp sau vẫn chặn.  Đổi nó là đổi hành vi mặc định
    // của cả hệ — ngoài phạm vi đợt này.
    assert.deepEqual(OWNER_DEFAULT_SCOPE.allow_globs, ["**"]);
    assert.equal(OWNER_DEFAULT_SCOPE.auto_apply, 0);
    assert.ok(matchesAnyGlob("automation_center/src/worker.js", OWNER_DEFAULT_SCOPE.allow_globs));
  });
});

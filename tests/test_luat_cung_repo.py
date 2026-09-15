"""Điều 3 của CLAUDE.md cấm sửa và cấm commit bốn cái tên.

Cấm bằng chữ thì chỉ ràng được người đọc CLAUDE.md.  Hai hàng rào máy đứng sau
câu chữ ấy, và chúng khoá hai chiều khác nhau — thiếu chiều nào cũng là hở:

* ``PROTECTED_GLOBS`` (worker.js + orchestrator_runner.py) khoá chiều **đọc và
  ghi tại chỗ**: nó chặn runner mở file bí mật ra rồi nhét vào một prompt.
  Bài canh nó nằm ở ``automation_center/tests/code_scope_covering_glob.test.mjs``.
* ``.gitignore`` khoá chiều **commit**.  Đó là chiều bài này canh.

Viết bài này vì một lượt soát đã kết luận sai từ chỗ vắng mặt: đọc mỗi
``.gitignore`` ở gốc, không thấy ``.dev.vars``, rồi báo là commit được — trong
khi ``automation_center/.gitignore`` đã chặn nó từ trước.  Đọc bằng mắt qua
nhiều file ``.gitignore`` lồng nhau là việc dễ sai; ``git check-ignore`` trả
lời đúng câu hỏi ấy, nên hỏi thẳng nó.
"""

import subprocess
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parent.parent


def _bi_ignore(duong_dan: str) -> bool:
    """git có bỏ qua đường dẫn này không.  Trả lời đúng cả khi có .gitignore lồng.

    ``--no-index`` KHÔNG phải cờ trang trí.  Thiếu nó, ``git check-ignore`` bỏ
    qua mọi file đang được theo dõi và trả lời "không bị ignore" **dù mẫu có
    khớp** — vì với file đã vào index thì câu trả lời ấy đúng về mặt thực dụng.
    Nhưng bài dưới hỏi câu khác: "mẫu mới có quét trúng file không được quét
    không".  Hỏi bằng lệnh mặc định thì mọi ``assertFalse`` trên file đang được
    theo dõi đều đúng vô điều kiện — bài xanh mà không cắn được gì.  Đo:

        $ echo tests/network_guard.py >> .gitignore
        $ git check-ignore -q tests/network_guard.py            ; echo $?   # 1 — im
        $ git check-ignore -q --no-index tests/network_guard.py ; echo $?   # 0 — đúng
    """
    ket_qua = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", "--", duong_dan],
        cwd=GOC,
        capture_output=True,
    )
    # 0 = bị ignore, 1 = không, còn lại là lỗi thật.
    if ket_qua.returncode not in (0, 1):
        raise AssertionError(
            f"git check-ignore hỏng cho {duong_dan!r}: {ket_qua.stderr.decode(errors='replace')}"
        )
    return ket_qua.returncode == 0


class DieuBaCamCommitTests(unittest.TestCase):
    def test_bon_cai_ten_dieu_3_deu_bi_gitignore_chan(self):
        for duong_dan in (
            ".env.local",
            "automation_center/.dev.vars",
            "automation_center/.dev.vars.production",
            "automation_center/runner/orchestrator.env",
            "data/state.json",
        ):
            with self.subTest(duong_dan=duong_dan):
                self.assertTrue(_bi_ignore(duong_dan))

    def test_dau_sao_cua_data_state_json_sao_phu_ca_cac_duoi_kem(self):
        # CLAUDE.md viết "data/state.json*" — có dấu sao.  Bản sao lưu và bản
        # tạm cũng là trạng thái của máy đang chạy, cũng không được commit.
        for duong_dan in (
            "data/state.json.bak",
            "data/state.json.bak-20260101",
            "data/state.json.tmp",
            "data/state.json.1",
        ):
            with self.subTest(duong_dan=duong_dan):
                self.assertTrue(_bi_ignore(duong_dan))

    def test_khong_quet_rong_qua_tay(self):
        # Siết .gitignore mà nuốt nhầm file đang được theo dõi thì lần commit
        # sau âm thầm bỏ sót thay đổi.  Hai sổ này là dữ liệu làm việc thật.
        # Bài này chỉ cắn được nhờ `--no-index` trong _bi_ignore — xem ở đó.
        for duong_dan in (
            "data/account_book.json",
            "data/sku_book.json",
            "tests/network_guard.py",
            "automation_center/src/worker.js",
        ):
            with self.subTest(duong_dan=duong_dan):
                self.assertFalse(_bi_ignore(duong_dan))

    def test_khong_file_nao_dang_theo_doi_bi_chinh_gitignore_nuot(self):
        # Câu hỏi tổng: git đang theo dõi file nào mà .gitignore cũng chặn?
        # Đáp án phải là không có cái nào.
        ra = subprocess.run(
            ["git", "ls-files", "--cached", "--ignored", "--exclude-standard"],
            cwd=GOC,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(ra.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()

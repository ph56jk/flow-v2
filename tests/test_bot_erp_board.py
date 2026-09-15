"""Phần "Bot & ERP" của bảng: mọi thứ bot đang nắm bên ERP phải lên bảng.

Bot giữ tám sổ trên đĩa mà bảng trước đây chỉ dùng hai. Sổ quan trọng nhất là
``paused`` (thẻ người bảo "@bot dừng lại") — nó **không tự hết hạn**, nên một
thẻ nằm im trong đó có thể im hàng tháng mà không ai thấy.

Hàm ``bot_brain`` là hàm thuần: nhận sổ, trả dict. Không đọc đĩa, không gọi
ERP — có vậy mới test được mà không dựng cả bot.
"""

import json
import shutil
import tempfile
import unittest
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from flow_web.sku_board import bot_brain, brain_from_disk, build_sku, snapshot


NOW = datetime(2026, 9, 14, 3, 0, 0, tzinfo=timezone.utc)


class SoBot:
    """Đủ thuộc tính của ``AgentBotState`` cho phần bảng. Không kéo cả bot vào."""

    def __init__(self, **kw):
        self.bot_user = kw.get("bot_user", "bot@havigroup")
        self.projects = kw.get("projects", [])
        self.fast_lane_projects = kw.get("fast_lane_projects", [])
        self.paused = kw.get("paused", {})
        self.warned_columns = kw.get("warned_columns", {})
        self.handled = kw.get("handled", {})
        self.listed = kw.get("listed", {})
        self.runs = kw.get("runs", {})
        self.brain_calls = kw.get("brain_calls", [])


class PhamViTest(unittest.TestCase):
    """Bot đứng ở những bảng nào, làn nhanh đọc bảng nào."""

    def test_liet_ke_du_an_va_lan_nhanh(self):
        brain = bot_brain(
            SoBot(projects=["PROJ-0087", "PROJ-0013", "PROJ-0018"],
                  fast_lane_projects=["PROJ-0087", "PROJ-0013"]),
            now=NOW,
        )
        self.assertEqual(brain["projects"], ["PROJ-0087", "PROJ-0013", "PROJ-0018"])
        self.assertEqual(brain["fast_lane"], ["PROJ-0087", "PROJ-0013"])

    def test_du_an_lan_nhanh_khong_doc_thi_noi_ra(self):
        """18/29 bảng nằm trong làn nhanh. 11 bảng còn lại phải hiện tên."""
        brain = bot_brain(
            SoBot(projects=["PROJ-0087", "PROJ-0013", "PROJ-0018"],
                  fast_lane_projects=["PROJ-0087"]),
            now=NOW,
        )
        self.assertEqual(brain["outside_fast_lane"], ["PROJ-0013", "PROJ-0018"])

    def test_dem_du_moi_so(self):
        brain = bot_brain(
            SoBot(projects=["A", "B"], fast_lane_projects=["A"],
                  paused={"TASK-1": "2026-09-13T10:00:00Z"},
                  warned_columns={"TASK-2": "Cột lạ"},
                  handled={"TASK-3": {}}, listed={"TASK-4": {}},
                  runs={"TASK-5": "2026-09-13T11:00:00Z"},
                  brain_calls=["2026-09-13T11:00:00Z", "2026-09-13T12:00:00Z"]),
            now=NOW,
        )
        self.assertEqual(brain["counts"], {
            "projects": 2, "fast_lane": 1, "outside_fast_lane": 1,
            "paused": 1, "warned_columns": 1,
            "handled": 1, "listed": 1, "runs": 1, "brain_calls": 2,
        })


class LenhDungTest(unittest.TestCase):
    """``paused`` không tự hết hạn: phải hiện tên thẻ và đã dừng bao lâu."""

    def test_the_bi_dung_hien_ten_va_tuoi(self):
        brain = bot_brain(
            SoBot(paused={"TASK-2026-00202": "2026-09-13T03:00:00Z"}),
            now=NOW,
        )
        self.assertEqual(len(brain["paused"]), 1)
        dong = brain["paused"][0]
        self.assertEqual(dong["task"], "TASK-2026-00202")
        self.assertEqual(dong["at"], "2026-09-13T03:00:00+00:00")
        self.assertEqual(dong["age_s"], 86400.0)
        self.assertTrue(dong["link"].endswith("TASK-2026-00202"))

    def test_cot_dat_sai_hien_ten_cot(self):
        brain = bot_brain(
            SoBot(warned_columns={"TASK-2026-05384": "Đang chờ duyệt"}),
            now=NOW,
        )
        self.assertEqual(brain["warned_columns"],
                         [{"task": "TASK-2026-05384", "column": "Đang chờ duyệt",
                           "link": brain["warned_columns"][0]["link"]}])

    def test_lenh_dung_sap_theo_thu_tu_dung_lau_nhat_truoc(self):
        brain = bot_brain(
            SoBot(paused={"TASK-B": "2026-09-13T20:00:00Z",
                          "TASK-A": "2026-09-10T20:00:00Z"}),
            now=NOW,
        )
        self.assertEqual([d["task"] for d in brain["paused"]], ["TASK-A", "TASK-B"])


class LuotChayTest(unittest.TestCase):
    def test_lay_luot_autorun_gan_nhat(self):
        brain = bot_brain(
            SoBot(runs={"TASK-A": "2026-09-13T20:00:00Z",
                        "TASK-B": "2026-09-14T02:30:00Z"}),
            now=NOW,
        )
        self.assertEqual(brain["last_run"]["task"], "TASK-B")
        self.assertEqual(brain["last_run"]["age_s"], 1800.0)
        # Link do Python ghi kèm: bảng không tự nối tên miền ERP.
        self.assertTrue(brain["last_run"]["link"].endswith("TASK-B"))

    def test_chua_chay_lan_nao_thi_rong_chu_khong_no(self):
        brain = bot_brain(SoBot(), now=NOW)
        self.assertEqual(brain["last_run"], {"task": "", "link": "", "at": "", "age_s": None})


class NhipErpTest(unittest.TestCase):
    """Sổ nhịp là danh sách mốc epoch. Chỉ đếm mốc còn trong cửa sổ."""

    def test_dem_luot_trong_cua_so(self):
        moc = NOW.timestamp()
        brain = bot_brain(
            SoBot(), now=NOW,
            rate_calls=[moc - 10, moc - 30, moc - 59, moc - 61, moc - 600],
        )
        self.assertEqual(brain["rate"]["calls"], 3)
        self.assertEqual(brain["rate"]["per_minute"], 3.0)

    def test_hien_ca_hai_tran(self):
        """Hai limiter tách biệt: bảng phải nói cả hai, không gộp một số."""
        brain = bot_brain(SoBot(), now=NOW, limits={"agent": 500, "graphql": 400})
        self.assertEqual(brain["rate"]["limits"], {"agent": 500.0, "graphql": 400.0})

    def test_gan_tran_thi_bao_dong(self):
        moc = NOW.timestamp()
        brain = bot_brain(SoBot(), now=NOW, rate_calls=[moc - 1] * 95,
                          limits={"agent": 100, "graphql": 400})
        self.assertEqual(brain["rate"]["tone"], "bad")
        self.assertEqual(brain["rate"]["headroom"], 5.0)

    def test_con_nhieu_bien_du_thi_yen(self):
        moc = NOW.timestamp()
        brain = bot_brain(SoBot(), now=NOW, rate_calls=[moc - 1] * 10,
                          limits={"agent": 500, "graphql": 400})
        self.assertEqual(brain["rate"]["tone"], "ok")

    def test_so_nhip_hong_thi_khong_no(self):
        brain = bot_brain(SoBot(), now=NOW, rate_calls=["không phải số", None, {}])
        self.assertEqual(brain["rate"]["calls"], 0)


class SoCapSoTest(unittest.TestCase):
    """``sku_ledger.json``: số kế tiếp mỗi dự án. Người vận hành hay hỏi số này."""

    def test_so_ke_tiep_tung_du_an(self):
        brain = bot_brain(
            SoBot(), now=NOW,
            ledger={"project_seq": {"OL_1": 60, "OR_1": 12}},
        )
        self.assertEqual(brain["ledger"], [
            {"prefix": "OL_1", "next": 61},
            {"prefix": "OR_1", "next": 13},
        ])

    def test_so_cap_so_hong_thi_rong(self):
        brain = bot_brain(SoBot(), now=NOW, ledger={"project_seq": "hỏng"})
        self.assertEqual(brain["ledger"], [])


class BangMaTest(unittest.TestCase):
    def test_chi_liet_ke_danh_muc_co_tien_to(self):
        """Danh mục không có ``sku_prefix`` thì bot không đoán được — đừng hiện."""
        brain = bot_brain(
            SoBot(), now=NOW,
            categories={"entries": {
                "Embroidered Ornament": {"sku_prefix": "OR"},
                "Ornament len chọc": {"sku_prefix": "OL"},
                "Chưa đặt": {"sku_prefix": ""},
            }},
        )
        self.assertEqual(brain["categories"], [
            {"name": "Embroidered Ornament", "prefix": "OR"},
            {"name": "Ornament len chọc", "prefix": "OL"},
        ])
        self.assertEqual(brain["counts_extra"]["categories_no_prefix"], 1)


class BangMaSheetTest(unittest.TestCase):
    """Bảng mã đọc từ sheet: một mặt hàng có thể mang nhiều mã.

    Bảng thật ghi ``khung theu = KT,OR,HK``. Bot đánh số lấy **mã đầu**; hai mã
    còn lại là chỗ dễ in sai lên thùng hàng, nên bảng phải nói ra.
    """

    def test_lay_ma_dau_va_giu_ma_con_lai(self):
        brain = bot_brain(SoBot(), now=NOW, book_rows={"entries": {
            "khung theu": "KT,OR,HK",
            "bom": "BT",
        }})
        self.assertEqual(brain["book"], [
            {"name": "bom", "prefix": "BT", "alternates": []},
            {"name": "khung theu", "prefix": "KT", "alternates": ["OR", "HK"]},
        ])

    def test_dem_rieng_dong_nhieu_ma(self):
        brain = bot_brain(SoBot(), now=NOW, book_rows={"entries": {
            "khung theu": "KT,OR,HK", "gau len": "LM,BD", "bom": "BT",
        }})
        self.assertEqual(brain["counts_extra"]["book_rows"], 3)
        self.assertEqual(brain["counts_extra"]["book_multi"], 2)

    def test_khong_co_bang_thi_rong_chu_khong_no(self):
        for xau in (None, "hỏng", [], {"entries": {"trống": ""}}):
            with self.subTest(xau=xau):
                brain = bot_brain(SoBot(), now=NOW, book_rows=xau)
                self.assertEqual(brain["book"], [])
                self.assertEqual(brain["counts_extra"]["book_multi"], 0)


class GanVaoTepTest(unittest.TestCase):
    """``snapshot`` nhét brain vào tệp, ``build_sku`` đọc lại."""

    def test_snapshot_giu_brain(self):
        data = snapshot([], NOW, brain={"bot_user": "bot@havigroup"})
        self.assertEqual(data["brain"]["bot_user"], "bot@havigroup")

    def test_build_sku_tra_brain_ra_bang(self):
        class Api:
            base = "http://x"

            def lister_status(self, name):
                return {"at": NOW.isoformat(), "every": 120,
                        "clusters": [], "cards": [],
                        "brain": {"bot_user": "bot@havigroup",
                                  "projects": ["PROJ-0087"]}}

        board = build_sku(Api(), now=NOW)
        self.assertEqual(board["brain"]["bot_user"], "bot@havigroup")
        self.assertEqual(board["brain"]["projects"], ["PROJ-0087"])

    def test_bot_cu_chua_ghi_brain_thi_bang_van_mo_duoc(self):
        """Deploy bảng trước bot: thiếu khoá ``brain`` không được làm vỡ bảng."""
        class Api:
            base = "http://x"

            def lister_status(self, name):
                return {"at": NOW.isoformat(), "clusters": [], "cards": []}

        board = build_sku(Api(), now=NOW)
        self.assertEqual(board["brain"]["projects"], [])
        self.assertEqual(board["brain"]["counts"]["projects"], 0)


class CanhBaoNhipTest(unittest.TestCase):
    """Chạm trần ERP phải lên khối "Cần xử lý", không nằm im trong một tab.

    Số nằm im thì không ai mở ra xem đúng lúc nó hỏng.
    """

    @staticmethod
    def _bang(rate):
        class Api:
            base = "http://x"

            def lister_status(self, name):
                return {"at": NOW.isoformat(), "every": 120, "clusters": [], "cards": [],
                        "brain": {"rate": rate}}

        return build_sku(Api(), now=NOW)

    def test_het_bien_du_thi_bao_do(self):
        board = self._bang({"calls": 500, "tone": "bad", "headroom": 0,
                            "limits": {"agent": 500, "graphql": 400}})
        loi = [a for a in board["alerts"] if "trần ERP" in a["text"]]
        self.assertEqual(len(loi), 1)
        self.assertEqual(loi[0]["tone"], "bad")
        self.assertIn("500", loi[0]["text"])

    def test_gan_tran_thi_bao_vang(self):
        board = self._bang({"calls": 380, "tone": "warn", "headroom": 120,
                            "limits": {"agent": 500, "graphql": 400}})
        loi = [a for a in board["alerts"] if "trần ERP" in a["text"]]
        self.assertEqual([a["tone"] for a in loi], ["warn"])

    def test_nhip_binh_thuong_thi_im(self):
        board = self._bang({"calls": 12, "tone": "ok", "headroom": 488,
                            "limits": {"agent": 500, "graphql": 400}})
        self.assertEqual([a for a in board["alerts"] if "trần ERP" in a["text"]], [])

    def test_bot_cu_khong_co_nhip_thi_im(self):
        class Api:
            base = "http://x"

            def lister_status(self, name):
                return {"at": NOW.isoformat(), "clusters": [], "cards": []}

        board = build_sku(Api(), now=NOW)
        self.assertEqual([a for a in board["alerts"] if "trần ERP" in a["text"]], [])


class DocSoTuDiaTest(unittest.TestCase):
    """``brain_from_disk`` gom ba sổ trên đĩa + hai trần trong môi trường."""

    def setUp(self):
        self.thu_muc = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.thu_muc, True)

    def ghi(self, ten, data):
        (self.thu_muc / ten).write_text(json.dumps(data), encoding="utf-8")

    def test_gom_du_ba_so(self):
        self.ghi("sku_ledger.json", {"project_seq": {"OL_1": 60}})
        self.ghi("product_categories.json", {"entries": {"Ornament len chọc": {"sku_prefix": "OL"}}})
        self.ghi("erp-agent-nhip.json", [NOW.timestamp() - 5, NOW.timestamp() - 10])
        brain = brain_from_disk(
            SoBot(projects=["PROJ-0087"]),
            data_dir=self.thu_muc, now=NOW,
            env={"ERP_AGENT_RATE_PER_MINUTE": "500", "ERP_GRAPHQL_PER_MINUTE": "400"},
        )
        self.assertEqual(brain["ledger"], [{"prefix": "OL_1", "next": 61}])
        self.assertEqual(brain["categories"], [{"name": "Ornament len chọc", "prefix": "OL"}])
        self.assertEqual(brain["rate"]["calls"], 2)
        self.assertEqual(brain["rate"]["limits"], {"agent": 500.0, "graphql": 400.0})

    def test_thieu_tep_thi_rong_chu_khong_no(self):
        brain = brain_from_disk(SoBot(), data_dir=self.thu_muc, now=NOW, env={})
        self.assertEqual(brain["ledger"], [])
        self.assertEqual(brain["categories"], [])
        self.assertEqual(brain["rate"]["calls"], 0)

    def test_tep_hong_thi_rong_chu_khong_no(self):
        (self.thu_muc / "sku_ledger.json").write_text("{ hỏng", encoding="utf-8")
        brain = brain_from_disk(SoBot(), data_dir=self.thu_muc, now=NOW, env={})
        self.assertEqual(brain["ledger"], [])

    def test_tran_graphql_chua_dat_thi_bao_none_chu_khong_doan(self):
        """Chưa đặt biến thì code chạy 40/phút mặc định — nhưng bảng không đoán."""
        brain = brain_from_disk(SoBot(), data_dir=self.thu_muc, now=NOW,
                                env={"ERP_AGENT_RATE_PER_MINUTE": "500"})
        self.assertEqual(brain["rate"]["limits"]["agent"], 500.0)
        self.assertIsNone(brain["rate"]["limits"]["graphql"])

    def test_doc_duoc_so_nhip_dat_cho_khac(self):
        khac = self.thu_muc / "nhip-rieng.json"
        khac.write_text(json.dumps([NOW.timestamp() - 1]), encoding="utf-8")
        brain = brain_from_disk(SoBot(), data_dir=self.thu_muc, now=NOW,
                                env={"ERP_AGENT_RATE_FILE": str(khac)})
        self.assertEqual(brain["rate"]["calls"], 1)


class GhiRaTepTest(unittest.TestCase):
    """``write_status`` phải mang brain sang tệp bảng đọc."""

    def test_brain_di_duoc_ra_tep(self):
        from flow_web.sku_board import write_status

        thu_muc = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, thu_muc, True)
        dich = thu_muc / "sku_status.json"
        self.assertTrue(write_status([], dich, now=NOW,
                                     brain={"bot_user": "bot@havigroup",
                                            "projects": ["PROJ-0087"]}))
        data = json.loads(dich.read_text(encoding="utf-8"))
        self.assertEqual(data["brain"]["projects"], ["PROJ-0087"])

    def test_khong_truyen_brain_thi_khoa_van_co_nhung_rong(self):
        from flow_web.sku_board import write_status

        thu_muc = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, thu_muc, True)
        dich = thu_muc / "sku_status.json"
        self.assertTrue(write_status([], dich, now=NOW))
        data = json.loads(dich.read_text(encoding="utf-8"))
        self.assertEqual(data["brain"], {})


class GiaoDienTest(unittest.TestCase):
    """Tab "Sổ bot" trong ``board.html``.

    Không có bộ chạy JS trong repo, nên soát bằng chữ: tab phải được khai, hàm
    vẽ phải có, và **cả hai trần** phải hiện riêng. Gộp hai trần thành một số
    là nói dối người đọc — nâng trần bot không chạm lượt tách thẻ con.
    """

    html = (Path(__file__).resolve().parents[1] / "flow_web" / "static" / "board.html").read_text(encoding="utf-8")

    def test_01_tab_duoc_khai(self):
        self.assertIn("function skuBrain", self.html)
        self.assertIn("['brain', 'Sổ bot'", self.html)

    def test_02_hien_ca_hai_tran_rieng(self):
        self.assertIn("lim.agent", self.html)
        self.assertIn("lim.graphql", self.html)

    def test_03_du_bon_so(self):
        for khoa in ("b.paused", "b.warned_columns", "b.ledger", "b.categories", "b.book"):
            with self.subTest(khoa=khoa):
                self.assertIn(khoa, self.html)

    def test_04_link_lay_tu_so_khong_tu_noi(self):
        # Link sang ERP do Python ghi kèm từng dòng. Bảng nối chuỗi lấy là
        # thêm một chỗ phải sửa khi ERP đổi tên miền.
        self.assertNotIn("erp.havigroup", self.html)

    def test_05_noi_ro_so_dung_khong_tu_het_han(self):
        self.assertIn("không tự hết hạn", self.html)


class SoDangBiSuaTest(unittest.TestCase):
    """Gom sổ chạy trong thread; làn nhanh có thể đang sửa chính sổ ấy.

    ``dict`` đang bị sửa thì ``dict(...)`` ném ``RuntimeError``. Ném ra ngoài
    thì bảng mất cả khối sổ bot — mà lỗi ấy chỉ là chạm nhau một nhịp.
    """

    class SoHay(Mapping):
        """Sổ ném ``RuntimeError`` ``lan`` lần đầu, rồi trả về bình thường."""

        def __init__(self, data, lan):
            self.data = data
            self.con = lan

        def __iter__(self):
            return iter(self.data)

        def __len__(self):
            return len(self.data)

        def __getitem__(self, key):
            return self.data[key]

        def keys(self):
            return self.data.keys()

        def items(self):
            if self.con > 0:
                self.con -= 1
                raise RuntimeError("dictionary changed size during iteration")
            return self.data.items()

    def test_cham_nhau_mot_nhip_thi_thu_lai(self):
        so = self.SoHay({"TASK-A": "2026-09-14T02:00:00Z"}, lan=1)
        brain = bot_brain(SoBot(paused=so), now=NOW)
        self.assertEqual([row["task"] for row in brain["paused"]], ["TASK-A"])

    def test_cham_nhau_mai_thi_bo_so_ay_thoi(self):
        so = self.SoHay({"TASK-A": "2026-09-14T02:00:00Z"}, lan=99)
        brain = bot_brain(SoBot(paused=so, projects=["PROJ-0018"]), now=NOW)
        self.assertEqual(brain["paused"], [])
        # Sổ khác vẫn còn: hỏng một sổ không được kéo cả khối đi.
        self.assertEqual(brain["projects"], ["PROJ-0018"])

    def test_danh_sach_bi_sua_cung_khong_no(self):
        class DanhSachHay(list):
            def __iter__(self):
                raise RuntimeError("list changed during iteration")

        brain = bot_brain(SoBot(projects=DanhSachHay(["PROJ-0018"])), now=NOW)
        self.assertEqual(brain["projects"], [])


class KhongNoTest(unittest.TestCase):
    def test_so_rong_hoan_toan(self):
        brain = bot_brain(SoBot(), now=NOW)
        self.assertEqual(brain["projects"], [])
        self.assertEqual(brain["paused"], [])
        self.assertEqual(brain["rate"]["calls"], 0)

    def test_gio_hong_trong_so_dung(self):
        brain = bot_brain(SoBot(paused={"TASK-X": "không phải giờ"}), now=NOW)
        self.assertEqual(brain["paused"][0]["at"], "")
        self.assertIsNone(brain["paused"][0]["age_s"])


if __name__ == "__main__":
    unittest.main()

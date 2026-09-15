"""Làn nhanh SKU: bảng ấm — thẻ mới có mã trong 10–20 giây.

PRD ``tasks/lan-nhanh-bang-am.md``.

Nhịp 15 giây của bảng *nóng* chỉ giúp khi làn **đã biết** có thẻ đang chờ.  Nó
không giúp *phát hiện* thẻ mới: bảng sạch — mọi thẻ đã có mã — rơi về
``rediscover_s`` (300 giây), nên thẻ vừa kéo vào chờ trung bình 150 giây.  Sáng
12/09 trên hvg-pc, PROJ-0018 có 35/35 thẻ *Đang làm* đã có mã và PROJ-0087
10/10: bảng sạch là trạng thái thường ngày, không phải ngoại lệ.

Nhịp thứ ba nằm giữa: bảng vừa có ai động vào thì **ấm**, đọc lại mỗi
``warm_s`` giây.  Biết "vừa động vào" bằng cách so dấu bảng hai lần đọc liên
tiếp, chứ không so ``modified`` với đồng hồ máy — ERP trả giờ máy chủ, máy
trung tâm lệch múi giờ, so thẳng là sai cả hai chiều.

Không mạng: bảng, đồng hồ và lượt đánh số giả lấy từ ``_LaneWorld``.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from flow_web.sku import SkuFastLaneConfig, board_stamp, fill_cost
from tests.test_sku import _cluster, _LaneWorld, board_row

DU_AN = "PROJ-0018"
CU = SkuFastLaneConfig()
#: Trần mặc định 20 vừa khít **một** lượt đánh số cụm ba thẻ, không còn chỗ
#: cho lượt ngó thêm — nên nhịp ấm chỉ chạy thật khi trần được nâng.  Đây là
#: con số đặt trên hvg-pc qua ``ERP_SKU_FAST_LANE_BUDGET``.
TRAN_AM = 40
AM = SkuFastLaneConfig(enabled=True, budget_per_minute=TRAN_AM)


def _sach(root="R", con="C1", sku="OL_1_049"):
    """Cụm đã đánh số xong: bảng nguội, đúng cảnh thường ngày của PROJ-0018."""
    rows = _cluster(root, (con, "Working"))
    rows[1]["custom_sku"] = sku
    rows[1]["subject"] = sku
    return rows


def _cham(rows, khi="2026-09-12 08:00:00"):
    """Có người động vào bảng: ERP đẩy ``modified`` của dòng ấy lên."""
    rows[-1]["modified"] = khi
    return rows


class DauBangTests(unittest.TestCase):
    """``board_stamp`` đổi đúng khi bảng đổi, không đổi khi bảng yên."""

    def test_bang_yen_thi_dau_khong_doi(self):
        rows = _sach()

        self.assertEqual(board_stamp(rows), board_stamp([dict(r) for r in rows]))

    def test_mot_dong_duoc_sua_thi_dau_doi(self):
        rows = _sach()
        truoc = board_stamp(rows)

        self.assertNotEqual(truoc, board_stamp(_cham(rows)))

    def test_them_the_thi_dau_doi(self):
        rows = _sach()
        truoc = board_stamp(rows)
        rows.append(board_row("C2", parent="R", status="Open"))

        self.assertNotEqual(truoc, board_stamp(rows))

    def test_xoa_the_thi_dau_doi(self):
        """``modified`` lớn nhất không đổi khi thẻ bị xoá: phải đếm cả số dòng."""
        rows = _sach()
        rows.append(board_row("C2", parent="R", status="Open", modified="2026-09-01 00:00:00"))
        truoc = board_stamp(rows)

        self.assertNotEqual(truoc, board_stamp(rows[:-1]))

    def test_bang_rong_khong_no(self):
        self.assertIsInstance(board_stamp([]), str)


class NhipBangAmTests(unittest.TestCase):
    """Bảng vừa có người động vào thì đọc lại mỗi ``warm_s``, không phải 300 giây."""

    def _the_gioi(self, config=AM):
        rows = _sach()
        world = _LaneWorld({DU_AN: rows})
        return world, rows, world.lane(config)

    def test_bang_sach_vua_doi_thi_nhip_xuong_warm_s(self):
        world, rows, lane = self._the_gioi()
        lane.tick()
        self.assertEqual(1, len(world.reads()))

        # Bảng sạch, chưa biết gì: vẫn đợi hết 300 giây mới nhìn lại.
        world.beat(lane, CU.rediscover_s - AM.tick_s)
        self.assertEqual(1, len(world.reads()))

        # Trong lúc ấy có người động vào bảng.  Lần đọc kế thấy dấu đổi.
        _cham(rows)
        world.beat(lane, AM.tick_s)
        self.assertEqual(2, len(world.reads()))

        # Từ đây bảng ấm: mỗi nhịp warm_s một lần đọc, không chờ 300 giây.
        world.beat(lane, AM.warm_s)
        self.assertEqual(3, len(world.reads()))

    def test_bang_yen_van_doi_du_300_giay(self):
        world, _rows, lane = self._the_gioi()
        lane.tick()
        world.beat(lane, CU.rediscover_s)
        self.assertEqual(2, len(world.reads()))

        # Không ai động vào: dấu không đổi, bảng vẫn nguội.
        world.beat(lane, AM.warm_s)
        self.assertEqual(2, len(world.reads()))

    def test_bang_vua_nong_vua_am_lay_nhip_nhanh_hon(self):
        """Thẻ đang chờ mã không được ngó thưa hơn bảng chỉ vừa động đậy."""
        config = SkuFastLaneConfig(enabled=True, interval_s=15.0, warm_s=10.0)
        rows = _sach()
        world = _LaneWorld({DU_AN: rows})
        lane = world.lane(config)
        lane.tick()
        # Bảng vừa đổi *và* có thẻ chờ mã: nóng lẫn ấm.
        rows.append(board_row("C2", parent="R", status="Open", modified="2026-09-12 09:00:00"))
        world.beat(lane, CU.rediscover_s)
        dem = len(world.reads())

        world.beat(lane, config.warm_s)

        self.assertEqual(dem + 1, len(world.reads()))

    def test_het_han_am_thi_ve_lai_nhip_300_giay(self):
        world, rows, lane = self._the_gioi()
        lane.tick()
        _cham(rows)
        world.beat(lane, CU.rediscover_s)
        self.assertEqual(2, len(world.reads()))

        # Ấm rồi, nhưng từ đây không ai động vào nữa.  Sau warm_for_s thì thôi.
        het = world.now + AM.warm_for_s
        while world.now < het:
            world.beat(lane, AM.warm_s)
        truoc = len(world.reads())
        world.beat(lane, AM.warm_s)

        self.assertEqual(truoc, len(world.reads()))


class TreDanhSoTests(unittest.TestCase):
    """Con số người dùng chốt: thẻ kéo vào bảng đang ấm có mã trong 20 giây."""

    def _bang_dang_am(self):
        rows = _sach()
        world = _LaneWorld({DU_AN: rows})
        lane = world.lane(AM)
        lane.tick()
        _cham(rows)
        world.beat(lane, CU.rediscover_s)
        return world, rows, lane

    def test_the_keo_vao_bang_dang_am_co_ma_trong_20_giay(self):
        world, rows, lane = self._bang_dang_am()
        rows.append(board_row("C2", parent="R", status="Working", modified="2026-09-12 09:00:00"))
        keo = world.now

        while not world.filled and world.now - keo < 300:
            world.beat(lane, AM.tick_s)

        self.assertEqual(["R"], world.filled)
        self.assertLessEqual(world.now - keo, 20)

    def test_cung_canh_ay_truoc_thay_doi_nay_phai_cho_gan_300_giay(self):
        """Mốc canh: chứng minh 20 giây là cái mới, không phải cái đã có sẵn."""
        rows = _sach()
        world = _LaneWorld({DU_AN: rows})
        lane = world.lane(SkuFastLaneConfig(enabled=True, warm_boards=0))
        lane.tick()
        rows.append(board_row("C2", parent="R", status="Working", modified="2026-09-12 09:00:00"))
        keo = world.now

        while not world.filled and world.now - keo < 600:
            world.beat(lane, CU.interval_s)

        self.assertEqual(["R"], world.filled)
        self.assertGreater(world.now - keo, 120)


class HangRaoChiPhiTests(unittest.TestCase):
    """Nhịp nhanh không được ăn hạn mức của lượt đánh số."""

    def test_khong_bao_gio_qua_warm_boards_bang_am_cung_luc(self):
        config = SkuFastLaneConfig(enabled=True, warm_boards=2, budget_per_minute=TRAN_AM)
        boards = {"PROJ-000%d" % i: _sach("R%d" % i, "C%d" % i) for i in range(5)}
        world = _LaneWorld(boards)
        lane = world.lane(config)
        lane.tick()
        for i, rows in enumerate(boards.values()):
            _cham(rows, "2026-09-12 08:0%d:00" % i)
        world.beat(lane, CU.rediscover_s)

        dem_truoc = {du_an: world.reads().count("board:" + du_an) for du_an in boards}
        world.beat(lane, config.warm_s)
        nhanh = [
            du_an
            for du_an in boards
            if world.reads().count("board:" + du_an) > dem_truoc[du_an]
        ]

        # Có bảng được hưởng nhịp ấm thật, nhưng không quá số đã chốt — thiếu
        # vế đầu thì bài này xanh cả khi tính năng không chạy lần nào.
        self.assertTrue(nhanh)
        self.assertLessEqual(len(nhanh), config.warm_boards)

    def test_tran_hep_thi_nhip_am_tu_tat(self):
        """Trần mặc định không còn chỗ cho lượt ngó thêm: ấm phải tự nhường.

        Ngó nhanh hơn mà ghi mã chậm đi là lỗ vốn.  Trần 20 vừa khít một lượt
        đánh số cụm ba thẻ (``1 + 1 + fill_cost(3)``), nên trên máy chưa nâng
        ``ERP_SKU_FAST_LANE_BUDGET`` thì hành vi phải y như cũ.
        """
        self.assertEqual(1 + 1 + fill_cost(3), CU.budget_per_minute)
        rows = _sach()
        world = _LaneWorld({DU_AN: rows})
        lane = world.lane(SkuFastLaneConfig(enabled=True))
        lane.tick()
        _cham(rows)
        world.beat(lane, CU.rediscover_s)
        dem = len(world.reads())

        world.beat(lane, CU.warm_s)

        self.assertEqual(dem, len(world.reads()))

    def test_bang_am_bi_tu_choi_qua_lau_van_duoc_doc_nhu_bang_thuong(self):
        """Nhường chỗ là được, chết đói thì không: quá 300 giây phải đọc."""
        rows = _sach()
        world = _LaneWorld({DU_AN: rows})
        lane = world.lane(SkuFastLaneConfig(enabled=True))
        lane.tick()
        _cham(rows)
        world.beat(lane, CU.rediscover_s)
        dem = len(world.reads())

        het = world.now + CU.rediscover_s + CU.warm_s
        while world.now < het:
            world.beat(lane, CU.warm_s)

        self.assertGreater(len(world.reads()), dem)

    def test_bang_am_van_chua_cho_cho_mot_luot_danh_so(self):
        """Trần một phút vẫn đủ cho cụm 3 thẻ sau khi thêm nhịp ấm."""
        config = SkuFastLaneConfig(enabled=True, budget_per_minute=TRAN_AM)
        rows = _sach()
        rows.append(board_row("C2", parent="R", status="Working", modified="2026-09-12 09:00:00"))
        world = _LaneWorld({DU_AN: rows})
        lane = world.lane(config)
        lane.tick()
        _cham(rows)
        keo = world.now

        while not world.filled and world.now - keo < 300:
            world.beat(lane, config.tick_s)

        self.assertEqual(["R"], world.filled)
        self.assertLessEqual(world.worst_minute(), config.budget_per_minute)

    def test_warm_boards_0_giu_nguyen_hanh_vi_cu(self):
        rows = _sach()
        world = _LaneWorld({DU_AN: rows})
        lane = world.lane(
            SkuFastLaneConfig(enabled=True, warm_boards=0, budget_per_minute=TRAN_AM)
        )
        lane.tick()
        _cham(rows)
        world.beat(lane, CU.rediscover_s)
        self.assertEqual(2, len(world.reads()))

        world.beat(lane, AM.warm_s)

        self.assertEqual(2, len(world.reads()))

    def test_tu_kiem_canh_bao_khi_nhip_doc_vuot_tran_token(self):
        """Khởi động làn nhanh phải nói to trước khi cấu hình sai kịp gửi bão."""
        boards = {"PROJ-%02d" % i: _sach("R%d" % i, "C%d" % i) for i in range(18)}
        world = _LaneWorld(boards)
        config = SkuFastLaneConfig(
            enabled=True,
            interval_s=5.0,
            budget_per_minute=400,
            rediscover_s=5.0,
            warm_s=5.0,
            warm_boards=18,
        )
        lane = world.lane(config, token_limit=50)

        with self.assertLogs("flow_web.sku", level="WARNING") as logs:
            with patch.object(lane, "tick", side_effect=asyncio.CancelledError):
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(lane.run_forever())

        message = "\n".join(record.getMessage() for record in logs.records)
        self.assertIn("18 bảng", message)
        self.assertIn("216.0/phút", message)
        self.assertIn("VƯỢT trần token 50/phút", message)

class CauHinhTests(unittest.TestCase):
    """Nhịp ngủ và biến môi trường."""

    def test_tick_s_la_nhip_nho_nhat_dang_dung(self):
        """Ngó mỗi 10 giây thì vòng lặp phải thức mỗi 10 giây."""
        config = SkuFastLaneConfig(enabled=True, interval_s=15.0, warm_s=10.0)

        self.assertEqual(10.0, config.tick_s)

    def test_tat_bang_am_thi_tick_s_ve_lai_interval_s(self):
        config = SkuFastLaneConfig(enabled=True, interval_s=15.0, warm_s=10.0, warm_boards=0)

        self.assertEqual(15.0, config.tick_s)

    def test_doc_env(self):
        config = SkuFastLaneConfig.from_env(
            {
                "ERP_SKU_FAST_LANE": "1",
                "ERP_SKU_FAST_LANE_WARM": "12",
                "ERP_SKU_FAST_LANE_WARM_FOR": "600",
                "ERP_SKU_FAST_LANE_WARM_BOARDS": "3",
                "ERP_SKU_FAST_LANE_LOCK_WAIT": "3",
            }
        )

        self.assertEqual((12.0, 600.0, 3), (config.warm_s, config.warm_for_s, config.warm_boards))
        self.assertEqual(3.0, config.lock_wait_s)

    def test_cau_hinh_500_phut_va_nhip_5_giay_duoc_nhan(self):
        config = SkuFastLaneConfig.from_env(
            {
                "ERP_SKU_FAST_LANE": "1",
                "ERP_SKU_FAST_LANE_SECONDS": "5",
                "ERP_SKU_FAST_LANE_BUDGET": "400",
                "ERP_SKU_FAST_LANE_REDISCOVER": "5",
                "ERP_SKU_FAST_LANE_WARM_BOARDS": "18",
                "ERP_SKU_FAST_LANE_WARM": "5",
            }
        )

        self.assertEqual((5.0, 400, 5.0, 18, 5.0), (
            config.interval_s,
            config.budget_per_minute,
            config.rediscover_s,
            config.warm_boards,
            config.warm_s,
        ))

    def test_env_hong_hoac_qua_bien_thi_ve_trong_khoang(self):
        config = SkuFastLaneConfig.from_env(
            {
                "ERP_SKU_FAST_LANE_WARM": "1",
                "ERP_SKU_FAST_LANE_WARM_FOR": "99999",
                "ERP_SKU_FAST_LANE_WARM_BOARDS": "x",
                "ERP_SKU_FAST_LANE_LOCK_WAIT": "99",
            }
        )

        self.assertEqual((5.0, 7200.0, 2), (config.warm_s, config.warm_for_s, config.warm_boards))
        self.assertEqual(5.0, config.lock_wait_s)

    def test_mac_dinh(self):
        self.assertEqual((15.0, 20, 300.0, 10.0, 900.0, 2), (
            CU.interval_s,
            CU.budget_per_minute,
            CU.rediscover_s,
            CU.warm_s,
            CU.warm_for_s,
            CU.warm_boards,
        ))

    def test_doc_bang_toi_da_hai_luong(self):
        """Chốt số luồng ở 2.  Đây là con số đo được, đừng nâng cho nhanh.

        Đo trên ERP thật 13/09/2026, cùng nhịp đọc 216 request/phút: 4 luồng ra
        3,8 lỗi ``QueryDeadlockError`` mỗi phút, 2 luồng ra 2,1 (mẫu 33 phút) —
        hạ luồng cắt gần một nửa, không hết hẳn.  Nghẽn nằm ở số truy vấn đồng
        thời, không phải số request mỗi phút, nên nâng trần token lên 500 không
        cứu được chỗ này.
        """
        self.assertEqual(2, CU.workers)
        self.assertEqual(
            2, SkuFastLaneConfig.from_env({"ERP_SKU_FAST_LANE": "1"}).workers
        )

    def test_chi_phi_xau_nhat_moi_phut_van_duoi_tran_token_bot(self):
        """2 bảng × 6 lần/phút = 12, cộng một lượt đánh số cụm 3 thẻ."""
        ngo = CU.warm_boards * (60.0 / CU.warm_s)
        danh_so = 1 + 1 + fill_cost(3)

        self.assertLessEqual(ngo + danh_so, 60)


if __name__ == "__main__":
    unittest.main()

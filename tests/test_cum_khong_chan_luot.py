"""Làn nhanh SKU: một cụm không có việc thì không được ăn cả nhịp.

``_fill_one`` duyệt từng cụm rồi **dừng ở cụm đầu tiên trả về kết quả**.  Cụm
"chưa tới lượt" cũng tính là kết quả, nên nó dừng — mà "chưa tới lượt" là
trạng thái *nghỉ lâu dài*: thẻ Idea còn ảnh chờ phiếu nằm đó hàng ngày.  Cụm
ấy đứng trước trong thứ tự duyệt thì mọi cụm sau nó không bao giờ tới lượt.

Đo trên hvg-pc tối 13/09/2026: đúng hai cụm ứng viên trên 18 bảng —
``TASK-2026-00202`` (PROJ-0013, thẻ Idea chờ phiếu) và ``TASK-2026-05384``
(PROJ-0087).  Bản mô phỏng chạy 6 nhịp liền, **6/6 nhịp** trả
``{'not_due': 'TASK-2026-00202'}`` rồi dừng; thẻ ``TASK-2026-05406`` người
dùng kéo sang *Đang làm* lúc 19:58 tới 20:10 vẫn chưa được chữa tên.  Không
một dòng log: hàng rào ``_stuck`` lùi ``rediscover_s`` = 5 giây, ngắn hơn
nhịp thật (~8 giây), nên nó hết hạn trước mỗi nhịp và ``_note_skip`` không
bao giờ chạy.  Đây chính là "kéo thẻ tiếp theo lại rất lâu, có khi không
chạy".

Luật: chỉ ba thứ được kết thúc một nhịp — **đánh số xong** (đã làm việc
thật), **khoá đang bận** (cả làn tắc, không riêng cụm này) và **hết ngân
sách** (nhịp sau cũng thế).  Còn lại là "cụm này không có việc": ghi một dòng
rồi xét cụm kế.

Không mạng: bảng, đồng hồ và lượt đánh số giả lấy từ ``_LaneWorld``.
"""

from __future__ import annotations

import unittest

from flow_web.sku import SkuFastLaneConfig, fill_cost
from tests.test_sku import _cluster, _LaneWorld

#: Bảng đứng trước trong thứ tự duyệt, giữ cụm mãi không tới lượt.
CHAN = "PROJ-0013"
#: Bảng đứng sau, giữ thẻ người dùng vừa kéo sang *Đang làm*.
SAU = "PROJ-0087"
GOC_CHAN, GOC_SAU = "TASK-2026-00202", "TASK-2026-05384"
CON_CHAN, CON_SAU = "TASK-2026-00615", "TASK-2026-05406"
#: Trần rộng để không ca nào dưới đây dừng vì thiếu chỗ — trừ ca cố ý thử nó.
RONG = SkuFastLaneConfig(enabled=True, budget_per_minute=200)
#: Vừa đủ hai lượt đọc bảng và một lượt đọc cây, rồi hết: cụm thứ hai xin chỗ
#: cho cây của nó là bị từ chối.  Đúng chỗ ngân sách phải chặn thay cho vòng
#: lặp, nên đừng thay bằng con số viết cứng.
TRAN_VUA_DU_MOT_CAY = 2 + 1 + fill_cost(1)


def _hai_bang():
    """Cụm chờ phiếu đứng trước, cụm có thẻ vừa kéo đứng sau."""
    return _LaneWorld(
        {
            CHAN: _cluster(GOC_CHAN, (CON_CHAN, "Working")),
            SAU: _cluster(GOC_SAU, (CON_SAU, "Working")),
        }
    )


def _cay(world):
    """``taskFull`` giả, ghi lại từng lượt đọc cây."""

    def doc(root):
        world.spent.append((world.now, 1, "tree:" + root))
        return {"root": {"name": root}}

    return doc


def _chan_mai_khong_toi_luot(payload, ids):
    """Cụm chờ phiếu không bao giờ tới lượt; cụm khác thì tới ngay."""
    return str((payload.get("root") or {}).get("name") or "") != GOC_CHAN


class CumNghiKhongChanCumSauTests(unittest.TestCase):
    """Cụm chưa tới lượt nhường nhịp, không giữ nó."""

    def test_cum_chua_toi_luot_khong_chan_cum_sau(self):
        world = _hai_bang()
        lane = world.lane(RONG, tree=_cay(world), is_due=_chan_mai_khong_toi_luot)

        lane.tick()

        self.assertEqual([GOC_SAU], world.filled)

    def test_cum_chan_van_nam_do_ca_ngay_thi_the_keo_sau_van_duoc_danh_so(self):
        """Ca thật trên hvg-pc: cụm chờ phiếu nằm đó, seller kéo thẻ mới."""
        world = _LaneWorld(
            {
                CHAN: _cluster(GOC_CHAN, (CON_CHAN, "Working")),
                SAU: _cluster(GOC_SAU, (CON_SAU, "Open")),
            }
        )
        lane = world.lane(RONG, tree=_cay(world), is_due=_chan_mai_khong_toi_luot)
        for _ in range(6):
            world.beat(lane, 5.0)
        self.assertEqual([], world.filled)

        world.boards[SAU][1].update(status="Working", modified="2026-09-13 19:58:05")
        world.beat(lane, 5.0)

        self.assertEqual([GOC_SAU], world.filled)

    def test_cum_chua_toi_luot_ghi_dung_mot_dong_moi_phut(self):
        """Bỏ qua mà im lặng thì đọc y hệt 'không có gì để làm'."""
        world = _hai_bang()
        lane = world.lane(RONG, tree=_cay(world), is_due=_chan_mai_khong_toi_luot)

        with self.assertLogs("flow_web.sku", level="INFO") as ghi:
            lane.tick()
        keu = [d for d in ghi.output if GOC_CHAN in d and "chưa đánh số cụm" in d]
        self.assertEqual(1, len(keu), ghi.output)

        with self.assertNoLogs("flow_web.sku", level="INFO"):
            world.beat(lane, 5.0)

    def test_doc_cay_hong_o_cum_dau_khong_chan_cum_sau(self):
        """Deadlock ERP trên một cụm là việc của cụm ấy, không phải của cả làn."""
        world = _hai_bang()

        def hong(root):
            if root == GOC_CHAN:
                raise RuntimeError('ERP HTTP 500: {"exc_type":"QueryDeadlockError"}')
            return _cay(world)(root)

        lane = world.lane(RONG, tree=hong, is_due=lambda payload, ids: True)

        lane.tick()

        self.assertEqual([GOC_SAU], world.filled)


class MotNhipVanChiMotLuotDanhSoTests(unittest.TestCase):
    """Nhường nhịp cho cụm sau, nhưng đừng biến một nhịp thành cơn bão request."""

    def test_danh_so_xong_thi_nhuong_nhip_ke_cho_cum_con_lai(self):
        world = _hai_bang()
        lane = world.lane(RONG, tree=_cay(world), is_due=lambda payload, ids: True)

        lane.tick()
        self.assertEqual([GOC_CHAN], world.filled)

        world.beat(lane, 5.0)
        self.assertEqual([GOC_CHAN, GOC_SAU], world.filled)

    def test_het_ngan_sach_thi_dung_han_chu_khong_duyet_tiep(self):
        """Thiếu chỗ là thiếu chung cho mọi cụm — xét tiếp chỉ tốn vòng lặp."""
        world = _hai_bang()
        lane = world.lane(
            SkuFastLaneConfig(enabled=True, budget_per_minute=TRAN_VUA_DU_MOT_CAY),
            tree=_cay(world),
            is_due=_chan_mai_khong_toi_luot,
        )

        lane.tick()

        self.assertEqual([], world.filled)
        self.assertNotIn("tree:" + GOC_SAU, [what for _, _, what in world.spent])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

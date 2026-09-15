"""429 trong lượt đánh số: gặp 429 đầu tiên là dừng, không trả giá theo từng thẻ.

``_erp_graphql`` tự thử lại 429 ba lần, nghỉ 10/30/60 s, rồi mới ném.  Mỗi
request bị chặn tốn 4 lần gửi và 100 s.  Cách cũ để vòng lặp thẻ đi tiếp, nên
mỗi thẻ còn lại tốn thêm chừng ấy trong khi lượt vẫn giữ khoá ``sku_pass``.

Giờ gặp 429 đầu tiên thì dừng:

- thẻ còn lại vào ``failed``, lỗi mang chữ "HTTP 429" để làn nhanh biết mà nghỉ;
- sổ vẫn lưu, chỗ giữ của thẻ đọc kiểm bị 429 vẫn còn;
- khoá ``sku_pass`` được nhả.

429 lúc hỏi thẻ nằm ở dự án nào cũng nổi lên cả trong lượt, nên lượt dừng ở
hàng rào thẻ gốc, trước mọi lệnh ghi.

ERP giả và đồng hồ giả lấy từ ``test_sku_nhanh_moi_the``.
"""

from __future__ import annotations

import io
import json
import threading
import unittest
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.error import HTTPError

from flow_web.erp_meta import task_meta
from flow_web.service import FlowWebService
from flow_web.sku import sku_pass
from tests.test_sku import _cluster, _LaneWorld
from tests.test_sku_nhanh_moi_the import (
    CARDS,
    K_OL,
    K_OR,
    LATENCY_S,
    ROOT,
    DongHoGia,
    ErpGia,
    child_id,
    erp_gia,
)

K_HVG = 30  # hvg-pc có 30 dự án được phép
THU_LAI_429 = 3  # ``max_429_retries`` trong ``_erp_graphql``


class _Chan:
    """Bọc ERP giả: từ lúc bắt đầu chặn, mọi request thuộc ``ops`` bị 429.

    ``sau``: chặn từ ngay sau lần gửi thành công đầu tiên của loại ấy.  Bỏ
    trống thì chặn từ đầu.  ``ops`` bỏ trống thì chặn mọi loại.
    """

    def __init__(
        self, erp: ErpGia, ops: Optional[Set[str]] = None, sau: Optional[str] = None
    ) -> None:
        self._real = erp.urlopen
        self._clock = erp.clock
        self.ops = ops
        self.sau = sau
        self.dang_chan = sau is None
        self.gui: List[Tuple[str, bool]] = []  # mọi lần gửi, kể cả lần bị 429
        erp.urlopen = self.urlopen

    def urlopen(self, request: Any, timeout: Any = None):
        op = json.loads(request.data.decode("utf-8"))["operationName"]
        chan = self.dang_chan and (self.ops is None or op in self.ops)
        self.gui.append((op, chan))
        if chan:
            self._clock.now += LATENCY_S
            raise HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO(b""))
        out = self._real(request, timeout)
        if op == self.sau:
            self.dang_chan = True
        return out

    def gui_sau_429_dau(self) -> int:
        dau = next(index for index, (_, chan) in enumerate(self.gui) if chan)
        return len(self.gui) - dau - 1

    def dem(self, op: str) -> int:
        return sum(1 for item, _ in self.gui if item == op)


def het_han_bang_nho_sau_lan_ghi_dau(erp: ErpGia, clock: DongHoGia, chan: _Chan) -> None:
    """Móc cho ``chay``: 429 rơi đúng vào hàng rào trước khi đổi tên.

    Lượt ghi mã đầu tiên xong thì đồng hồ nhảy qua TTL bảng nhớ, như một
    lượt dài ở nhịp 40/phút.  Lượt đọc kiểm ngay sau vẫn qua.  Từ request
    kế tiếp — hàng rào đọc lại vì bảng nhớ đã hết hạn — ERP chặn tất cả.
    """
    chan.dang_chan = False
    real = erp.urlopen
    state = {"ghi": False}

    def urlopen(request: Any, timeout: Any = None):
        op = json.loads(request.data.decode("utf-8"))["operationName"]
        out = real(request, timeout)
        if op == "UpdateTaskMeta" and not state["ghi"]:
            state["ghi"] = True
            clock.now += FlowWebService.ERP_SKU_BOARD_MEMO_TTL_S + 1
        elif op == "TaskDetail" and state["ghi"]:
            chan.dang_chan = True
        return out

    erp.urlopen = urlopen


def chay(
    n: int,
    k: int,
    ops: Optional[Set[str]] = None,
    sau: Optional[str] = None,
    moc: Optional[Callable[[ErpGia, DongHoGia, _Chan], None]] = None,
) -> Dict[str, Any]:
    """Một lượt ``fill_task_skus`` trên cụm ``n`` thẻ Working, ERP chặn theo ``_Chan``.

    ``moc`` cài thêm móc lên ERP giả sau ``_Chan``, trước khi chạy lượt.
    """
    clock = DongHoGia()
    step = CARDS // n
    the = [child_id(index * step) for index in range(n)]
    erp = ErpGia(clock, [index * step for index in range(n)])
    chan = _Chan(erp, ops, sau)
    if moc is not None:
        moc(erp, clock, chan)
    out: Dict[str, Any] = {
        "the": the,
        "erp": erp,
        "chan": chan,
        "clock": clock,
        "loi": None,
        "result": {},
    }
    with erp_gia(clock, erp, k) as svc:
        try:
            out["result"] = FlowWebService.fill_task_skus(svc, ROOT)
        except Exception as exc:  # noqa: BLE001
            out["loi"] = exc
        path = svc._sku_ledger_path()
        out["so"] = json.loads(path.read_text()) if path.exists() else None
    return out


def khoa_nha() -> bool:
    """Luồng khác lấy được ``sku_pass`` ngay không."""
    got: List[bool] = []

    def thu() -> None:
        with sku_pass(wait=False) as ok:
            got.append(ok)

    worker = threading.Thread(target=thu)
    worker.start()
    worker.join(5)
    return got == [True]


def ma_len_the_ma_so_chua_ghi(run: Dict[str, Any]) -> List[str]:
    """Thẻ mang mã mà mốc số trong sổ trên đĩa chưa tới mã ấy."""
    seq = (run["so"] or {}).get("idea_seq", {})
    out = []
    for task in run["the"]:
        sku = task_meta(run["erp"].nodes[task]).sku
        if sku and int(sku.rsplit("_", 1)[1]) > int(seq.get(sku.split("_", 1)[0], 0)):
            out.append(task)
    return out


class VongTheGap429Tests(unittest.TestCase):
    def _dung_ngay(self, run: Dict[str, Any]) -> None:
        # Sau lần 429 đầu chỉ còn các lần thử lại của chính request ấy.
        self.assertLessEqual(run["chan"].gui_sau_429_dau(), THU_LAI_429, run["chan"].gui)
        self.assertTrue(khoa_nha(), "lượt dừng rồi mà vẫn giữ sku_pass")
        self.assertEqual([], ma_len_the_ma_so_chua_ghi(run))

    def _con_lai_vao_failed(self, run: Dict[str, Any], xong: List[str]) -> None:
        failed = run["result"]["failed"]
        self.assertEqual(
            sorted(set(run["the"]) - set(xong)), sorted(item["task_id"] for item in failed)
        )
        for item in failed:
            self.assertIn("HTTP 429", item["error"], item)

    def test_doc_kiem_bi_429_thi_dung_va_giu_cho(self):
        # ERP chặn mọi request ngay sau lượt ghi mã đầu tiên: lượt đọc kiểm
        # của thẻ ấy bị 429.
        for k in (1, K_OR):
            with self.subTest(k=k):
                run = chay(5, k, sau="UpdateTaskMeta")
                self.assertIsNone(run["loi"])
                result = run["result"]
                self.assertEqual(1, len(result["written"]), result)
                dau = result["written"][0]
                self.assertEqual([dau["task_id"]], [i["task_id"] for i in result["rename_failed"]])
                self._con_lai_vao_failed(run, [dau["task_id"]])
                self.assertEqual({dau["task_id"]: dau["sku"]}, run["so"]["pending"])
                self._dung_ngay(run)

    def test_doc_the_ke_tiep_bi_429_thi_dung(self):
        # Thẻ đầu xong trọn, ERP chặn từ lượt đọc thẻ thứ hai.
        for k in (1, K_OR):
            with self.subTest(k=k):
                run = chay(5, k, sau="UpdateTaskTitle")
                self.assertIsNone(run["loi"])
                result = run["result"]
                self.assertEqual(1, len(result["written"]), result)
                self.assertEqual(1, len(result["renamed"]))
                self._con_lai_vao_failed(run, [result["written"][0]["task_id"]])
                self.assertNotIn("pending", run["so"])
                self.assertEqual(1, run["chan"].dem("UpdateTaskMeta"))
                self._dung_ngay(run)

    def test_doi_ten_bi_429_thi_dung(self):
        run = chay(5, K_OR, ops={"UpdateTaskTitle"})
        self.assertIsNone(run["loi"])
        result = run["result"]
        self.assertEqual(1, len(result["written"]), result)
        dau = result["written"][0]["task_id"]
        self.assertEqual([dau], [item["task_id"] for item in result["rename_failed"]])
        self.assertIn("HTTP 429", result["rename_failed"][0]["error"])
        self._con_lai_vao_failed(run, [dau])
        self.assertEqual(1, run["chan"].dem("UpdateTaskMeta"))
        self._dung_ngay(run)

    def test_hang_rao_truoc_doi_ten_bi_429_thi_dung(self):
        # Lượt dài quá TTL bảng nhớ: ngay sau lượt ghi mã đầu tiên, bảng nhớ
        # hết hạn, nên hàng rào trước khi đổi tên phải hỏi ERP.  ERP chặn từ
        # đúng lần hỏi ấy.  Mã đã lên thẻ và đọc kiểm thấy rồi: mã giữ, tên
        # giữ, thẻ vào ``rename_failed``.  Không đọc thẻ kế tiếp nữa.
        for k in (1, K_OR, K_HVG):
            with self.subTest(k=k):
                run = chay(5, k, moc=het_han_bang_nho_sau_lan_ghi_dau)
                self.assertIsNone(run["loi"])
                result = run["result"]
                self.assertEqual(1, len(result["written"]), result)
                dau = result["written"][0]
                self.assertEqual([dau["task_id"]], [i["task_id"] for i in result["rename_failed"]])
                self.assertIn("HTTP 429", result["rename_failed"][0]["error"])
                self.assertEqual([], result["renamed"])
                self.assertEqual(dau["sku"], task_meta(run["erp"].nodes[dau["task_id"]]).sku)
                self.assertEqual(0, run["chan"].dem("UpdateTaskTitle"))
                self._con_lai_vao_failed(run, [dau["task_id"]])
                self.assertNotIn("pending", run["so"])
                self._dung_ngay(run)

    def test_chi_phi_sau_429_khong_theo_so_the(self):
        # Hai thẻ hay năm thẻ thì phần sau lần 429 đầu cũng như nhau.
        for k in (1, K_OR):
            with self.subTest(k=k):
                hai, nam = chay(2, k, sau="UpdateTaskMeta"), chay(5, k, sau="UpdateTaskMeta")
                self.assertEqual(hai["chan"].gui_sau_429_dau(), nam["chan"].gui_sau_429_dau())

    def test_dung_vi_429_thi_bo_luot_chua_ten(self):
        # Lượt chữa tên cũng là giá theo từng thẻ.  Lượt đã dừng vì 429 thì
        # không chữa nữa: thẻ chờ chữa vào ``rename_failed``, lượt sau chữa.
        clock = DongHoGia()
        erp = ErpGia(clock, [0])
        chan = _Chan(erp, {"TaskDetail"})
        chan.dang_chan = False
        with erp_gia(clock, erp, 1) as svc:
            dau = FlowWebService.fill_task_skus(svc, ROOT)["written"][0]
            # Tên kẹt: mã và ``ten_cu`` đã lên thẻ, bước đổi tên chưa chạy.
            erp.nodes[dau["task_id"]]["subject"] = task_meta(erp.nodes[dau["task_id"]]).get("ten_cu")
            erp.nodes[child_id(90)]["status"] = "Working"
            chan.gui.clear()
            chan.dang_chan = True
            result = FlowWebService.fill_task_skus(svc, ROOT)
        self.assertEqual(0, chan.dem("UpdateTaskTitle"), chan.gui)
        self.assertEqual([child_id(90)], [item["task_id"] for item in result["failed"]])
        self.assertEqual([dau["task_id"]], [item["task_id"] for item in result["rename_failed"]])
        self.assertIn("HTTP 429", result["rename_failed"][0]["error"])
        self.assertLessEqual(chan.gui_sau_429_dau(), THU_LAI_429)

    def test_lan_nhanh_nghi_khi_luot_dung_vi_429(self):
        # Làn nhanh giữ nguyên: nó nghỉ khi thấy "429" trong ``failed``.
        run = chay(5, K_OR, sau="UpdateTaskMeta")
        result = run["result"]
        world = _LaneWorld(
            {"PROJ-0087": _cluster("R", ("C1", "Working"))}, fill_result=lambda root: result
        )
        lane = world.lane()
        lane.tick()
        self.assertEqual(["R"], world.filled)
        self.assertTrue(world.beat(lane).get("resting"))


class HoiTheTrongLuotGap429Tests(unittest.TestCase):
    def test_hoi_the_429_thi_dung_o_hang_rao_goc(self):
        # Chỉ ``taskDetail`` bị chặn.  Danh sách dài hơn hai dự án thì hàng rào
        # thẻ gốc hỏi thẻ trước: 429 nổi lên, chưa đọc bảng, chưa ghi gì.
        for k in (K_OR, K_OL, K_HVG):
            with self.subTest(k=k):
                run = chay(5, k, ops={"TaskDetail"})
                self.assertIsInstance(run["loi"], RuntimeError)
                self.assertIn("429", str(run["loi"]))
                self.assertEqual(
                    [("TaskDetail", True)] * (1 + THU_LAI_429), run["chan"].gui
                )
                self.assertIsNone(run["so"])
                self.assertTrue(khoa_nha())

    def test_k_nho_thi_dung_o_the_dau(self):
        # Hai dự án trở xuống thì hàng rào không hỏi thẻ.  429 đầu tiên rơi vào
        # lượt đọc thẻ đầu trong vòng lặp: dừng luôn, chưa ghi gì.
        for k in (1, 2):
            with self.subTest(k=k):
                run = chay(5, k, ops={"TaskDetail"})
                self.assertIsNone(run["loi"])
                self.assertEqual([], run["result"]["written"])
                self.assertEqual(0, run["chan"].dem("UpdateTaskMeta"))
                VongTheGap429Tests._con_lai_vao_failed(self, run, [])
                self.assertLessEqual(run["chan"].gui_sau_429_dau(), THU_LAI_429)
                self.assertTrue(khoa_nha())


if __name__ == "__main__":
    unittest.main()

"""Thẻ bị cắt khỏi cây mà đã có mã thì đọc dòng bảng, không đọc ``taskFull``.

ERP cắt ``taskFull.subtasks`` ở 59 thẻ.  Cụm 04628 có 37 thẻ đã mang mã nằm
ngoài phần ấy, nên mỗi lượt ``fill_task_skus`` đọc ``taskFull`` thêm 37 lần
chỉ để biết lại mã chúng đang mang: 46/50/54 request cho 1/2/3 thẻ mới, trong
khi làn nhanh có 20 request mỗi phút.

a6 quyết (PRD ``tasks/the-cat-da-co-ma.md``): bỏ ``taskFull`` cho thẻ bị cắt
**chỉ** khi đủ ba điều, thiếu một điều thì đọc như cũ.

1. Dòng bảng có ``custom_sku`` khác rỗng và ``subject == custom_sku``.
2. Không thẻ nào trong cụm nhận nó làm ``parent_task`` hay khai
   ``fatheridea`` tới nó.
3. ``meta`` dựng từ ``custom_sku`` bằng ``render_meta_block({"sku": ...})``.

Trần request mới (:func:`tran_moi`) chỉ đi cùng việc ấy.

ERP giả là của ``test_sku_nhanh_moi_the``.  Dòng bảng thật có ``subject``,
dòng giả thì không, nên :class:`ErpDongThat` thêm vào.
"""

from __future__ import annotations

import contextlib
import json
import unittest
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Sequence, Tuple

from flow_web.erp_meta import task_meta
from flow_web.service import FlowWebService
from flow_web.sku import ProductBook
from tests.test_sku_nhanh_moi_the import (
    K_OL,
    K_OR,
    PROJECT,
    ROOT,
    SHOWN,
    DongHoGia,
    ErpGia,
    allowed_projects,
    child_id,
    erp_gia,
)

#: 37 thẻ đã mang mã, nằm ngoài phần cây ERP trả về (như 04628 ngày 12/09).
DA_CO_MA = [child_id(SHOWN + index) for index in range(37)]


def moi_trong_cay(n: int) -> List[str]:
    """``n`` thẻ chờ mã nằm trong phần cây ERP trả về."""
    return [child_id(1 + index) for index in range(n)]


def moi_ngoai_cay(n: int) -> List[str]:
    """``n`` thẻ chờ mã nằm ngoài cây, sau 37 thẻ đã có mã."""
    return [child_id(SHOWN + len(DA_CO_MA) + index) for index in range(n)]


def tran_moi(n: int, cut_new: int = 0, wrong: int = 0) -> int:
    """``fill_cost`` mới a6 nhận: ``3 + 5n + cut_new + 2·wrong``, cộng 2 cho mỗi 40 request.

    ``cut_new``: thẻ mới cần mã nằm ngoài cây, mỗi thẻ một ``taskFull``.
    ``wrong``: thẻ có mã mà tên khác mã, mỗi thẻ một ``taskFull`` và một lần
    chữa tên.  Cộng 2 mỗi 40 request: lượt dài quá chừng ấy thì bảng nhớ hết
    hạn, phải đọc lại bảng.
    """
    base = 3 + 5 * n + cut_new + 2 * wrong
    return base + 2 * (base // 40)


class ErpDongThat(ErpGia):
    """ERP giả mà dòng bảng mang ``subject`` như dòng thật; ghi lại thẻ nào bị đọc cây, bị ghi mã."""

    def __init__(self, clock: DongHoGia, working: Iterable[int] = (), away: Iterable[int] = ()) -> None:
        super().__init__(clock, list(working), away)
        self.full_reads: List[str] = []
        self.meta_writes: List[str] = []
        #: Thẻ mà dòng bảng để trống ``custom_sku`` dù ``meta`` đã có mã.
        self.blank_sku: set = set()

    def reset(self) -> None:
        self.calls.clear()
        self.full_reads.clear()
        self.meta_writes.clear()

    def full(self, name: str) -> Dict[str, Any]:
        self.full_reads.append(name)
        return super().full(name)

    def board(self, project: str) -> Dict[str, Any]:
        payload = super().board(project)
        if project != PROJECT:
            return payload
        for column in payload["columns"]:
            for row in column["tasks"]:
                row["subject"] = self.nodes[row["name"]]["subject"]
                if row["name"] in self.blank_sku:
                    row["custom_sku"] = ""
        return payload

    def urlopen(self, request: Any, timeout: Any = None) -> Any:
        body = json.loads(request.data.decode("utf-8"))
        if body["operationName"] == "UpdateTaskMeta":
            self.meta_writes.append(body["variables"]["task"])
        return super().urlopen(request, timeout)


def sku_cua(erp: ErpGia, name: str) -> str:
    return task_meta(erp.nodes[name]).sku


@contextlib.contextmanager
def cum_e(
    k: int,
    *,
    san_pham: Mapping[str, str] | None = None,
    book: ProductBook | None = None,
) -> Iterator[Tuple[FlowWebService, ErpDongThat]]:
    """Cụm E sau lượt một: 37 thẻ ngoài cây đã mang mã, tên đã đổi đúng bằng mã.

    ``san_pham``: thẻ nào khai ``product:`` riêng trước lượt một.
    """
    clock = DongHoGia()
    erp = ErpDongThat(clock)
    with erp_gia(clock, erp, k) as svc:
        if book is not None:
            svc.load_sku_book = lambda *a, **kw: book
        for name, product in (san_pham or {}).items():
            erp.nodes[name]["meta"] = f"product: {product}"
        for name in DA_CO_MA:
            erp.nodes[name]["status"] = "Working"
        result = FlowWebService.fill_task_skus(svc, ROOT)
        written = sorted(item["task_id"] for item in result["written"])
        if written != sorted(DA_CO_MA) or result["failed"]:
            raise AssertionError(f"lượt một hỏng: {result['failed']}")
        for name in DA_CO_MA:
            meta = task_meta(erp.nodes[name])
            if erp.nodes[name]["subject"] != meta.sku or not meta.get("ten_cu"):
                raise AssertionError(f"lượt một chưa đổi tên {name}")
        erp.reset()
        yield svc, erp


def luot_hai(svc: FlowWebService, erp: ErpDongThat, new: Sequence[str]) -> Dict[str, Any]:
    """Lượt hai: ``new`` sang Working rồi đánh số, đếm request từ đầu lượt."""
    for name in new:
        erp.nodes[name]["status"] = "Working"
    erp.reset()
    return FlowWebService.fill_task_skus(svc, ROOT)


class TheCatDaCoMaTests(unittest.TestCase):
    # ── 1. Cụm E, mọi thẻ bị cắt tên đúng bằng mã ─────────────────────────

    def test_the_cat_ten_dung_ma_khong_doc_taskfull(self):
        """Cụm E, w = 0: chỉ đọc cây gốc, thẻ mới đủ mã, lượt nằm dưới trần mới."""
        for k in (K_OR, K_OL):
            for n in (1, 2, 3):
                with self.subTest(k=k, n=n):
                    with cum_e(k) as (svc, erp):
                        result = luot_hai(svc, erp, moi_trong_cay(n))
                    self.assertEqual([], result["failed"])
                    self.assertEqual(
                        sorted(moi_trong_cay(n)), sorted(item["task_id"] for item in result["written"])
                    )
                    self.assertTrue(all(sku_cua(erp, name) for name in moi_trong_cay(n)))
                    self.assertEqual([ROOT], erp.full_reads, "thẻ bị cắt tên đúng bằng mã không cần taskFull")
                    self.assertLessEqual(sum(erp.calls.values()), tran_moi(n), dict(erp.calls))

    def test_the_moi_ngoai_cay_van_doc_taskfull(self):
        """Thẻ mới nằm ngoài cây chưa có mã thì vẫn đọc ``taskFull``, lượt dưới trần mới có ``cut_new``."""
        for k in (K_OR, K_OL):
            for n in (1, 2, 3):
                with self.subTest(k=k, n=n):
                    with cum_e(k) as (svc, erp):
                        result = luot_hai(svc, erp, moi_ngoai_cay(n))
                    self.assertEqual([], result["failed"])
                    self.assertTrue(all(sku_cua(erp, name) for name in moi_ngoai_cay(n)))
                    self.assertEqual(sorted([ROOT, *moi_ngoai_cay(n)]), sorted(erp.full_reads))
                    self.assertLessEqual(
                        sum(erp.calls.values()), tran_moi(n, cut_new=n), dict(erp.calls)
                    )

    # ── 2. Cụm E, năm thẻ kẹt tên ─────────────────────────────────────────

    def test_the_ket_ten_van_doc_va_duoc_chua(self):
        """Cụm E, w = 5: đúng năm thẻ kẹt tên bị đọc ``taskFull``, cả năm được chữa tên, lượt dưới trần mới."""
        ket = DA_CO_MA[::8]
        self.assertEqual(5, len(ket))
        for k in (K_OR, K_OL):
            for n in (1, 2, 3):
                with self.subTest(k=k, n=n):
                    with cum_e(k) as (svc, erp):
                        for name in ket:
                            # Kẹt tên: mã đã lên, ``ten_cu`` đã chép, bước đổi tên chưa chạy.
                            erp.nodes[name]["subject"] = task_meta(erp.nodes[name]).get("ten_cu")
                            self.assertNotEqual(sku_cua(erp, name), erp.nodes[name]["subject"])
                        result = luot_hai(svc, erp, moi_trong_cay(n))
                    self.assertEqual([], result["failed"])
                    self.assertEqual([], result["rename_failed"])
                    self.assertEqual(sorted([ROOT, *ket]), sorted(erp.full_reads))
                    self.assertLessEqual(set(ket), {item["task_id"] for item in result["renamed"]})
                    for name in ket:
                        self.assertEqual(sku_cua(erp, name), erp.nodes[name]["subject"])
                    self.assertLessEqual(
                        sum(erp.calls.values()), tran_moi(n, wrong=len(ket)), dict(erp.calls)
                    )

    # ── 3. Thẻ bị cắt là cha hoặc là đích ``fatheridea`` ───────────────────

    def test_the_cat_la_dich_fatheridea_van_doc_taskfull(self):
        """Thẻ bị cắt mà thẻ trong cây khai ``fatheridea`` tới nó vẫn đọc ``taskFull``, thẻ con lấy đầu mã theo ``product:`` của nó."""
        cha = DA_CO_MA[3]
        con = moi_trong_cay(1)[0]
        book = ProductBook.from_mapping({"khăn tay": "KT", "bờm": "BM"})
        with cum_e(K_OR, san_pham={cha: "bờm"}, book=book) as (svc, erp):
            self.assertTrue(sku_cua(erp, cha).startswith("BM_"), sku_cua(erp, cha))
            erp.nodes[con]["meta"] = f"fatheridea: {cha}"
            result = luot_hai(svc, erp, [con])
        self.assertEqual([], result["failed"])
        self.assertTrue(sku_cua(erp, con).startswith("BM_"), sku_cua(erp, con))
        self.assertEqual(sorted([ROOT, cha]), sorted(erp.full_reads))

    def test_the_moi_ngoai_cay_khai_fatheridea_toi_the_cat(self):
        """Thẻ mới ngoài cây khai ``fatheridea`` tới thẻ bị cắt: lời khai chỉ lộ ra sau ``taskFull`` của thẻ mới, nên thẻ cha vẫn phải đọc ``taskFull``."""
        cha = DA_CO_MA[3]
        con = moi_ngoai_cay(1)[0]
        book = ProductBook.from_mapping({"khăn tay": "KT", "bờm": "BM"})
        with cum_e(K_OR, san_pham={cha: "bờm"}, book=book) as (svc, erp):
            erp.nodes[con]["meta"] = f"fatheridea: {cha}"
            result = luot_hai(svc, erp, [con])
        self.assertEqual([], result["failed"])
        self.assertTrue(sku_cua(erp, con).startswith("BM_"), sku_cua(erp, con))
        self.assertEqual(sorted([ROOT, cha, con]), sorted(erp.full_reads))

    def test_the_cat_la_cha_van_doc_taskfull(self):
        """Thẻ bị cắt mà một dòng bảng nhận nó làm ``parent_task`` vẫn đọc ``taskFull``."""
        cha = DA_CO_MA[3]
        chau = "TASK-2026-19999"
        book = ProductBook.from_mapping({"khăn tay": "KT", "bờm": "BM"})
        with cum_e(K_OR, san_pham={cha: "bờm"}, book=book) as (svc, erp):
            erp.nodes[chau] = {
                "name": chau, "parent_task": cha, "subject": "Idea con", "status": "Open",
                "project": PROJECT, "project_name": "khăn tay", "meta": "",
            }
            result = luot_hai(svc, erp, moi_trong_cay(1))
        self.assertEqual([], result["failed"])
        self.assertEqual(sorted([ROOT, cha]), sorted(erp.full_reads))
        self.assertTrue(sku_cua(erp, cha).startswith("BM_"), sku_cua(erp, cha))

    # ── 4. Dòng bảng không có ``custom_sku`` ───────────────────────────────

    def test_dong_bang_trong_custom_sku_van_doc_taskfull(self):
        """Dòng bảng để trống ``custom_sku`` thì thẻ bị cắt vẫn đọc ``taskFull``, giữ mã, không bị ghi."""
        trong = DA_CO_MA[1::9]
        with cum_e(K_OR) as (svc, erp):
            cu = {name: sku_cua(erp, name) for name in trong}
            erp.blank_sku = set(trong)
            result = luot_hai(svc, erp, moi_trong_cay(2))
        self.assertEqual([], result["failed"])
        self.assertEqual(sorted([ROOT, *trong]), sorted(erp.full_reads))
        self.assertEqual(sorted(moi_trong_cay(2)), sorted(erp.meta_writes))
        self.assertEqual(cu, {name: sku_cua(erp, name) for name in trong})

    # ── 5. Chống trùng ─────────────────────────────────────────────────────

    def test_khong_cap_trung_ma(self):
        """Không thẻ nào nhận hai mã, sổ không phát số cho thẻ đã có mã, mã thẻ bị cắt không phát lại, kể cả khi mất sổ."""
        new = moi_trong_cay(3)
        for mat_so in (False, True):
            with self.subTest(mat_so=mat_so):
                with cum_e(K_OR) as (svc, erp):
                    cu = {name: sku_cua(erp, name) for name in DA_CO_MA}
                    if mat_so:
                        # Máy vừa dựng lại, hay file sổ bị xoá: mốc chỉ còn học
                        # được từ mã nằm trên thẻ.
                        svc._sku_ledger_path().unlink()
                    result = luot_hai(svc, erp, new)
                    so = svc.load_sku_ledger().as_dict()
                self.assertEqual([], result["failed"])
                self.assertEqual(sorted(new), sorted(erp.meta_writes), "chỉ thẻ mới bị ghi mã, mỗi thẻ một lần")
                self.assertEqual(cu, {name: sku_cua(erp, name) for name in DA_CO_MA})
                moi_cap = {sku_cua(erp, name) for name in new}
                self.assertEqual(len(new), len(moi_cap))
                self.assertFalse(moi_cap & set(cu.values()), "mã của thẻ bị cắt bị phát lại")
                codes = [task_meta(node).sku for node in erp.nodes.values() if task_meta(node).sku]
                self.assertEqual(len(codes), len(set(codes)))
                for node in erp.nodes.values():
                    lines = [line for line in str(node["meta"]).splitlines() if line.strip().startswith("sku:")]
                    self.assertLessEqual(len(lines), 1, node["name"])
                self.assertEqual(len(DA_CO_MA) + len(new), so["idea_seq"]["KT"])
                self.assertNotIn("pending", so)
                self.assertEqual([ROOT], erp.full_reads)

    # ── 6. Canh: xanh cả trước lẫn sau ─────────────────────────────────────

    def test_cum_sach_dung_so_request_nhu_hom_nay(self):
        """Cụm sạch B/F (không thẻ bị cắt nào có mã): số request từng loại đúng như hôm nay."""
        for ten, du_an in (("B", 0), ("F", 30)):
            for k in (1, K_OR, K_OL):
                for n in (1, 2, 3):
                    with self.subTest(cum=ten, k=k, n=n):
                        clock = DongHoGia()
                        erp = ErpDongThat(clock, range(1, n + 1))
                        with erp_gia(clock, erp, k) as svc:
                            if du_an:
                                projects = allowed_projects(k) + [
                                    f"PROJ-8{j:03d}" for j in range(du_an - k)
                                ]
                                svc._erp_allowed_project_ids = lambda projects=projects: list(projects)
                            allowed = svc._erp_allowed_project_ids()
                            result = FlowWebService.fill_task_skus(svc, ROOT)
                        self.assertEqual(n, len(result["written"]), result["failed"])
                        # Danh sách dài hơn hai dự án thì hàng rào hỏi thẻ gốc
                        # nằm ở đâu trước: một ``taskDetail``.  Rồi một bảng, một
                        # cây.  Mỗi thẻ: đọc trước khi ghi, ghi mã, đọc kiểm, đổi
                        # tên.  Thẻ bị cắt đều ở Open, chưa có mã: lấy từ dòng bảng.
                        #
                        # ``ProductCategories: 1`` là danh mục sản phẩm ERP
                        # (``tasks/sku-tu-product-type.md``), nơi lấy tiền tố SKU
                        # thay cho việc đoán theo tên.  Đây là **trường hợp xấu
                        # nhất**: mỗi subTest dựng một ``FlowWebService`` mới nên
                        # cache luôn lạnh.  Chạy thật thì tiến trình sống lâu,
                        # TTL 30 phút, nên một request này chia cho mọi lượt quét
                        # trong nửa tiếng.  Số 1 giữ ở đây để bài canh vẫn báo
                        # động nếu ai thêm request **thứ hai**: trần làn nhanh
                        # 3 thẻ đang là 18 + 1 = 19 trên 20, chỉ còn dư đúng 1.
                        hoi_the = 1 if len(allowed) > 2 else 0
                        self.assertEqual(
                            {
                                "TaskDetail": hoi_the + 2 * n,
                                "TaskBoard": 1,
                                "TaskFull": 1,
                                "ProductCategories": 1,
                                "UpdateTaskMeta": n,
                                "UpdateTaskTitle": n,
                            },
                            dict(erp.calls),
                        )

    def test_ngoai_luot_van_doc_bang_tuoi(self):
        """Sau một lượt đánh số, hàng rào ngoài lượt vẫn đọc bảng tươi mỗi lần hỏi."""
        with cum_e(K_OR) as (svc, erp):
            luot_hai(svc, erp, moi_trong_cay(1))
            erp.reset()
            svc._erp_assert_task_in_project("k", "t", DA_CO_MA[0])
            svc._erp_assert_task_in_project("k", "t", DA_CO_MA[1])
        self.assertEqual(2, erp.calls["TaskBoard"])

    def test_danh_so_lai_van_doc_taskfull(self):
        """``renumber=True`` tính lại mã cả cụm theo ``product:`` nên mọi thẻ bị cắt đã có mã vẫn đọc ``taskFull``."""
        with cum_e(K_OR) as (svc, erp):
            FlowWebService.fill_task_skus(svc, ROOT, dry_run=True, renumber=True)
        self.assertLessEqual(set(DA_CO_MA), set(erp.full_reads))


if __name__ == "__main__":
    unittest.main()

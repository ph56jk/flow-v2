"""Đánh số mất bao lâu mỗi thẻ: đếm request và giờ mô phỏng.

Cụm 04628 ngày 12/09: 37 mã vào trong một lượt ``fill_task_skus``, khoảng
50 giây mỗi thẻ, trong khi một request ERP chỉ mất 0,2–0,7 giây.  Cụm OL
ngày 11/09 thì khoảng 10 giây mỗi thẻ.

Ở đây ERP giả đứng sau ``urlopen``, nên ``_erp_graphql`` thật chạy cùng bộ
nhịp thật (40/phút, xô 10).  Đồng hồ giả: không ngủ thật giây nào.

Cụm giả giống 04628: 184 thẻ con, ``taskFull`` chỉ trả đủ 59 thẻ, còn lại
chỉ có tên.  ``k`` là chỗ đứng của dự án cụm trong danh sách dự án được
phép.  Hàng rào dự án đọc bảng từng dự án theo thứ tự tới khi thấy thẻ, nên
``k`` càng lớn thì mỗi lần kiểm càng nhiều bảng.
"""

from __future__ import annotations

import collections
import contextlib
import json
import os
import sys
import tempfile
import time as _time
import unittest
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List
from unittest.mock import patch

from flow_web import service as service_mod
from flow_web.erp_meta import task_meta
from flow_web.service import FlowWebService
from flow_web.sku import ProductBook

ROOT = "TASK-2026-04628"
PROJECT = "PROJ-0018"
CARDS = 184
SHOWN = 59  # taskFull cắt subtasks: bot thấy 59 thẻ con
LATENCY_S = 0.5  # một request ERP, giữa 0,19 và 0,66 giây c8 đo
OTHER_ROWS = 40  # thẻ trên bảng của mỗi dự án khác
# Chỗ đứng thật trên hvg-pc ngày 12/09 (c8 đọc): dự án mặc định PROJ-0013
# đứng đầu, sau đó 29 dự án trong sổ bot.  PROJ-0018 (OR) thứ 13 trong sổ nên
# thứ 14 trong danh sách; PROJ-0087 (OL) thứ 26 nên thứ 27.
K_OR = 14
K_OL = 27


def child_id(index: int) -> str:
    return f"TASK-2026-{10000 + index}"


class DongHoGia:
    """Thay module ``time`` trong service: ngủ chỉ là cộng giờ."""

    def __init__(self) -> None:
        self.now = 1_000_000.0
        # Ai ngủ, ngủ bao lâu: ``acquire`` là bộ nhịp, ``_erp_graphql`` là
        # chờ 429 hay mạng hỏng, ``_fill_task_skus_once`` là nhịp đọc kiểm.
        self.slept: Dict[str, float] = collections.defaultdict(float)

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.now

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        seconds = max(0.0, float(seconds))
        self.slept[sys._getframe(1).f_code.co_name] += seconds
        self.now += seconds

    def __getattr__(self, name: str) -> Any:
        return getattr(_time, name)


class _Tra:
    status = 200

    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def getcode(self) -> int:
        return 200

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Tra":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class ErpGia:
    """ERP giả sau ``urlopen``: đếm request theo loại, mỗi request tốn ``LATENCY_S``."""

    def __init__(self, clock: DongHoGia, working: List[int], away: Iterable[int] = ()) -> None:
        self.clock = clock
        self.calls: collections.Counter = collections.Counter()
        work = set(working)
        # Thẻ đã bị kéo sang một dự án không được phép: không nằm trên bảng
        # nào bot được đọc, và taskDetail khai dự án lạ.
        self.away = {child_id(index) for index in away}
        self.nodes: Dict[str, Dict[str, Any]] = {
            ROOT: {
                "name": ROOT, "parent_task": "", "subject": "Khăn tay", "status": "Open",
                "project": PROJECT, "project_name": "khăn tay", "meta": "product: khăn tay",
            }
        }
        for index in range(CARDS):
            name = child_id(index)
            self.nodes[name] = {
                "name": name, "parent_task": ROOT, "subject": f"Idea {index + 1}",
                "status": "Working" if index in work else "Open",
                "project": PROJECT, "project_name": "khăn tay", "meta": "",
            }
        for name in self.away:
            self.nodes[name]["project"] = "PROJ-7777"

    def full(self, name: str) -> Dict[str, Any]:
        if name != ROOT:
            return {"root": {**self.nodes[name], "subtasks": []}}
        kids = [child_id(index) for index in range(CARDS)]
        return {
            "root": {
                **self.nodes[ROOT],
                "children": [{"name": kid} for kid in kids],
                "subtasks": [{**self.nodes[kid], "subtasks": []} for kid in kids[:SHOWN]],
            }
        }

    def board(self, project: str) -> Dict[str, Any]:
        if project != PROJECT:
            rows = [{"name": f"{project}-T{j}", "project": project} for j in range(OTHER_ROWS)]
            return {"columns": [{"status": "Open", "tasks": rows}]}
        columns: Dict[str, List[Dict[str, Any]]] = {"Open": [], "Working": []}
        for node in self.nodes.values():
            if node["name"] in self.away:
                continue
            columns[node["status"]].append(
                {
                    "name": node["name"], "parent_task": node["parent_task"], "project": PROJECT,
                    "status": node["status"], "custom_sku": task_meta(node).sku,
                }
            )
        return {"columns": [{"status": status, "tasks": rows} for status, rows in columns.items()]}

    def urlopen(self, request: Any, timeout: Any = None) -> _Tra:
        body = json.loads(request.data.decode("utf-8"))
        op, args = body["operationName"], body["variables"]
        self.clock.now += LATENCY_S
        self.calls[op] += 1
        if op == "TaskFull":
            data: Dict[str, Any] = {"taskFull": self.full(args["name"])}
        elif op == "TaskBoard":
            data = {"taskBoard": self.board(args["project"])}
        elif op == "TaskDetail":
            data = {"taskDetail": dict(self.nodes[args["name"]])}
        elif op == "UpdateTaskMeta":
            self.nodes[args["task"]]["meta"] = args["meta"]
            data = {"updateTaskMeta": {}}
        elif op == "UpdateTaskTitle":
            self.nodes[args["task"]]["subject"] = args["subject"]
            data = {"updateTaskTitle": {}}
        else:
            raise AssertionError(f"ERP giả không biết {op}")
        return _Tra(json.dumps({"data": data}, ensure_ascii=False))


def allowed_projects(k: int) -> List[str]:
    """Danh sách dự án được phép, dự án của cụm đứng thứ ``k``."""
    return [f"PROJ-9{j:03d}" for j in range(k - 1)] + [PROJECT]


@contextlib.contextmanager
def erp_gia(clock: DongHoGia, erp: ErpGia, k: int) -> Iterator[FlowWebService]:
    """Service thật trên ERP giả: ``_erp_graphql``, bộ nhịp, hàng rào đều thật."""
    projects = allowed_projects(k)
    with tempfile.TemporaryDirectory() as tmp:
        svc = FlowWebService.__new__(FlowWebService)
        svc._sku_ledger_path = lambda: Path(tmp) / "sku_ledger.json"
        svc.load_sku_book = lambda *a, **kw: ProductBook.from_mapping({"khăn tay": "KT"})
        svc._erp_credentials = lambda: ("k", "t")
        svc._erp_base_url = lambda: "https://erp.gia"
        svc._erp_allowed_project_ids = lambda: list(projects)
        svc._erp_comment = lambda *a, **kw: {}
        # Xô mới cho mỗi lượt: bộ nhịp của lớp dùng chung giữa mọi instance.
        svc._erp_rate_limiter = FlowWebService._GraphQLRateLimiter()
        with patch.object(service_mod, "time", clock), patch.object(
            service_mod, "urlopen", erp.urlopen
        ), patch.object(service_mod, "log"), patch.dict(os.environ, {"ERP_SKU_RENAME_TASK": "1"}):
            os.environ.pop("ERP_GRAPHQL_PER_MINUTE", None)
            yield svc


def do_luot(n: int, k: int, away: Iterable[int] = ()) -> Dict[str, Any]:
    """Một lượt ``fill_task_skus`` trên cụm giả có ``n`` thẻ Working chưa mã."""
    clock = DongHoGia()
    step = CARDS // n
    erp = ErpGia(clock, [index * step for index in range(n)], away)
    with erp_gia(clock, erp, k) as svc:
        start = clock.now
        result = FlowWebService.fill_task_skus(svc, ROOT)
    return {
        "calls": dict(erp.calls),
        "requests": sum(erp.calls.values()),
        "seconds": clock.now - start,
        "slept": dict(clock.slept),
        "written": len(result["written"]),
        "renamed": len(result["renamed"]),
        "failed": result["failed"],
        "result": result,
        "nodes": erp.nodes,
    }


class SkuNhanhMoiTheTests(unittest.TestCase):
    def _luot(self, n: int, k: int) -> Dict[str, Any]:
        stats = do_luot(n, k)
        self.assertEqual(n, stats["written"], stats["failed"])
        self.assertEqual(n, stats["renamed"])
        return stats

    def test_them_the_khong_doc_them_bang(self):
        # Bảng dự án không đổi giữa hai thẻ của cùng một lượt.  Đọc lại nó cho
        # từng thẻ, hai lần mỗi thẻ (ghi mã, đổi tên), là phần lớn của 50 giây.
        for k in (1, K_OR, K_OL):
            with self.subTest(k=k):
                mot, nam = self._luot(1, k), self._luot(5, k)
                self.assertEqual(
                    mot["calls"].get("TaskBoard", 0),
                    nam["calls"].get("TaskBoard", 0),
                    "mỗi bảng chỉ đọc một lần mỗi lượt",
                )

    def test_tran_request_moi_the(self):
        # Mỗi thẻ: đọc trước khi ghi, ghi mã, đọc kiểm, đổi tên là 4.  Thẻ bị
        # cắt khỏi cây tốn thêm một ``taskFull`` lúc lập kế hoạch.
        for k in (1, K_OR, K_OL):
            with self.subTest(k=k):
                mot, nam = self._luot(1, k), self._luot(5, k)
                them = (nam["requests"] - mot["requests"]) / 4
                self.assertLessEqual(them, 5, (mot["calls"], nam["calls"]))

    def test_van_doc_kiem_moi_the(self):
        # Không bỏ bước đọc kiểm: nó chống ghi hụt (vụ OL_1_019).
        stats = self._luot(5, K_OR)
        self.assertGreaterEqual(stats["calls"].get("TaskDetail", 0), 2 * 5)

    def test_nam_the_duoi_60_giay(self):
        for k in (K_OR, K_OL):
            with self.subTest(k=k):
                stats = self._luot(5, k)
                self.assertLess(stats["seconds"], 60.0, stats)

    def test_the_ngoai_du_an_van_bi_choi(self):
        # Bảng nhớ không được làm lỏng hàng rào: thẻ đã sang dự án không được
        # phép thì không nhận mã, không bị đổi tên, dù bảng cụm đã nằm sẵn trong
        # bộ nhớ.  Các thẻ khác trong lượt vẫn chạy.
        away = child_id(0)
        for k in (1, K_OR):
            with self.subTest(k=k):
                stats = do_luot(5, k, away=[0])
                self.assertEqual([away], [item["task_id"] for item in stats["failed"]])
                self.assertIn("không thuộc Project", stats["failed"][0]["error"])
                self.assertEqual("", stats["nodes"][away]["meta"])
                self.assertEqual("Idea 1", stats["nodes"][away]["subject"])
                self.assertEqual(4, stats["written"])
                self.assertEqual(4, stats["renamed"])

    def test_ngoai_luot_danh_so_van_doc_bang_tuoi(self):
        # Bộ nhớ bảng chỉ sống trong ``fill_task_skus``.  Mọi chỗ khác hỏi
        # hàng rào vẫn đọc bảng mới mỗi lần, như trước.  Ngoài lượt, hàng rào
        # hỏi thẻ trước rồi đọc tươi đúng bảng ấy (test_hang_rao_hoi_the_truoc),
        # nên mỗi lần hỏi là một lượt đọc bảng.
        clock = DongHoGia()
        erp = ErpGia(clock, [])
        with erp_gia(clock, erp, K_OR) as svc:
            svc._erp_assert_task_in_project("k", "t", child_id(3))
            svc._erp_assert_task_in_project("k", "t", child_id(4))
        self.assertEqual(2, erp.calls["TaskBoard"])


if __name__ == "__main__":
    unittest.main()

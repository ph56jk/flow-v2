"""Nhận ảnh idea không để lại thẻ con rỗng, không đẻ thẻ trùng — 12/09.

Đường nhận ảnh (``_erp_intake_idea_images``) chạy: tải ảnh nguồn →
``CreateTask`` → upload → hàng rào thẻ con → ``AddTaskComment``.  Hỏng sau
``CreateTask`` thì thẻ con đã nằm trên ERP mà không có ảnh; nhánh ``except``
chỉ ghi log rồi đi tiếp.  Lượt sau chỉ nhận ra thẻ đã "giữ" ảnh bằng chính tấm
ảnh, nên thẻ rỗng không giữ gì, và ảnh còn trên thẻ cha thì bot tạo thẻ thứ
hai.  00202 có ba thẻ rỗng: 02118 (hvg-pc), 02121 và 02126 (Mac, đã tắt).

PRD: ``tasks/nhan-anh-the-con-rong.md``.  Hai đợt:

- Đợt 1
  - #1  Đường nhận ảnh không đọc bảng để rào thẻ con **vừa tạo**.  Mọi đường
        khác vẫn rào như cũ.
  - #2  Log nói được thẻ con nào đã tạo; chuyển cột hỏng mà không có job thì
        vẫn có đúng một dòng, ở cả ``_erp_advance_task_status`` lẫn except
        ngoài của ``advance_erp_pipeline``.
- Đợt 2
  - #4  ``CreateTask`` ghi dấu ảnh vào mô tả (dạng chú thích HTML).  Lượt sau
        gắn ảnh X vào đúng thẻ mang dấu X mà chưa có tệp.  Thẻ không dấu thì
        không đụng, kể cả thẻ rỗng cũ như 02118.

ERP giả ở tầng thấp (``_erp_graphql``, ``_erp_upload_file``,
``_erp_task_project_id``), để ``_erp_create_child_task``,
``_erp_attach_file_bytes``, ``_erp_request_json`` và hàng rào chạy code thật.
"""

from __future__ import annotations

import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from flow_web.schemas import ERPConfig, ERPIdeaBatchRequest
from flow_web.service import FlowBrowserProfile, FlowWebService
from flow_web.store import StateStore

PARENT = "TASK-2026-00202"
CHILD_A = "TASK-2026-00615"
CHILD_B = "TASK-2026-00616"
#: Thẻ con rỗng có sẵn, không dấu: như 02118, thẻ đang chờ người dùng quyết.
CHILD_RONG = "TASK-2026-02118"
#: Thẻ con bot tạo theo đợt 2 mà chưa gắn được ảnh: chỉ có dấu trong mô tả.
CHILD_DAU = "TASK-2026-00618"
PROJECT = "PROJ-0013"

DU_BON_KHOA = "\n".join(
    [
        "product_type: Khăn tay cô dâu thêu tay",
        "product_group: Thêu tay",
        "fulfillment: HaviGroup",
        "sales_channel: Etsy",
    ]
)
CO_CONTENT = DU_BON_KHOA + "\ncontent: Có"

ANH_1 = "/private/files/17ee9ea.png"
ANH_2 = "/private/files/29d66c0.png"

#: Dấu nhận ảnh: dùng lại dạng ``ERP_IDEA_INTAKE_MARKER`` đã đọc, bọc trong chú
#: thích HTML để không thành chữ trên thẻ.
DAU_1 = f"<!-- [FLOW_V2_IDEA src={ANH_1}] -->"
DAU_2 = f"<!-- [FLOW_V2_IDEA src={ANH_2}] -->"
#: Cùng dấu ấy nếu ERP trả mô tả đã escape (chưa biết ERP có làm vậy không).
DAU_1_ESCAPE = f"&lt;!-- [FLOW_V2_IDEA src={ANH_1}] --&gt;"

DEADLOCK = 'ERP HTTP 500: {"exc_type":"QueryDeadlockError"}'

#: Lỗi thật ở từng chỗ hỏng, lấy từ log hvg-pc và brief 49.
LOI = {
    # Trước ``CreateTask``: 4 dòng của TASK-2026-04628 ngày 12/09.
    "tai_anh": lambda: RuntimeError("Không tải được ảnh nguồn ERP (HTTP 403)."),
    # Sau ``CreateTask``: ca TASK-2026-00202 lúc 27/08 21:35:47.
    "upload": lambda: TimeoutError("The write operation timed out"),
    "add_task_comment": lambda: RuntimeError(DEADLOCK),
}


def the_mang_dau(dau: str, **extra) -> dict:
    """Thẻ con "Idea 3" chỉ mang dấu trong mô tả, chưa có tệp nào."""
    return {"subject": "Idea 3", "description": dau, "meta": DU_BON_KHOA, **extra}


class _NhanAnhTestCase(unittest.TestCase):
    """Kho tạm + service có key giả; ERP giả ở tầng graphql, upload và bảng."""

    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.patches = [
            patch("flow_web.store.STATE_FILE", root / "state.json"),
            patch("flow_web.store.ensure_app_dirs", lambda: root.mkdir(parents=True, exist_ok=True)),
            patch("flow_web.service.ensure_app_dirs", lambda: root.mkdir(parents=True, exist_ok=True)),
        ]
        for item in self.patches:
            item.start()
        self.store = StateStore()
        self.service = FlowWebService(self.store)
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(api_key="test-key", api_secret="test-secret", project_id=PROJECT, task_id=PARENT)
            )
        )
        self.profile = FlowBrowserProfile(index=0, label="Flow profile 1", path=root / "profile")
        self.details: dict = {}
        #: Thẻ mà bảng dự án đang liệt kê.
        self.bang: set = set()
        #: True: thẻ vừa tạo chưa lên bảng cho tới khi test gọi ``_bang_bat_kip``.
        self.bang_tre = False
        self.cho_len_bang: set = set()
        self.hong: dict = {}
        self.tao: list = []
        self.gan: list = []
        self.upload: list = []
        self.doc_bang: list = []
        self.la: list = []

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()
        self.loop.close()
        asyncio.set_event_loop(None)

    # ── Dựng thẻ ────────────────────────────────────────────────────────

    def _dung(
        self,
        *,
        parent_meta: str = DU_BON_KHOA,
        dropped: tuple = (),
        children: tuple = (CHILD_A, CHILD_B),
        rong: tuple = (),
        khac: dict | None = None,
    ) -> None:
        """Thẻ cha có ảnh sản phẩm làm bìa, ảnh idea thả trong bình luận.

        ``children`` là thẻ con người đã viết mô tả.  ``rong`` là thẻ con rỗng
        không dấu, như 02118: tiêu đề ``Idea N``, mô tả trống, không ảnh, chỉ
        có khối Thuộc tính bot chép xuống sau đó.  ``khac`` là thẻ con tuỳ ý.
        """
        khac = dict(khac or {})
        order = list(children) + list(rong) + list(khac)
        self.details = {
            PARENT: {
                "name": PARENT,
                "subject": "Idea",
                "status": "Working",
                "description": "<p>Tạo idea cho khăn tay cô dâu thêu tay</p>",
                "cover_image": "/private/files/khan-tay.jpg",
                "meta": parent_meta,
                "children": [],
                "comments": [
                    {
                        "name": f"drop-{index}",
                        "content": "",
                        "attachments": [{"file_url": url, "file_name": Path(url).name}],
                    }
                    for index, url in enumerate(dropped)
                ],
            }
        }
        for index, child in enumerate(order):
            if child in khac:
                detail = {"name": child, "status": "Open", "cover_image": "", "comments": [], **khac[child]}
            elif child in rong:
                detail = {
                    "name": child,
                    "subject": f"Idea {index + 1}",
                    "status": "Open",
                    "description": "",
                    "cover_image": "",
                    "comments": [],
                    # Bot chép Thuộc tính vào ``meta`` (updateTaskMeta), không vào mô tả.
                    "meta": DU_BON_KHOA,
                }
            else:
                detail = {
                    "name": child,
                    "subject": f"Idea {index + 1}",
                    "status": "Open",
                    "description": "<p>Khăn tay đặt cạnh cây thông</p>",
                    "cover_image": "",
                    "comments": [],
                }
            detail.setdefault("parent_task", PARENT)
            # ``taskDetail`` trả ``project``; có nó thì hàng rào ghi chỉ kiểm
            # chuỗi dự án chứ không quét bảng (đó là việc ``doc_bang`` đo).
            detail.setdefault("project", PROJECT)
            self.details[child] = detail
            self.details[PARENT]["children"].append({"name": child, "subject": detail.get("subject", "")})
        self.bang = {PARENT, *order}

    def _hong_o(self, where: str, lan: int = 1) -> None:
        """Cho chỗ ``where`` hỏng ``lan`` lần đầu.

        ``hang_rao_con``: bảng chưa kịp liệt kê thẻ vừa tạo, và lần đọc tươi
        bảng nóng ấy gặp deadlock — đúng chỗ brief 49 chỉ ra.
        """
        if where == "hang_rao_con":
            self.bang_tre = True
            return
        self.hong[where] = lan

    def _co_hong(self, where: str) -> None:
        if self.hong.get(where, 0) > 0:
            self.hong[where] -= 1
            raise LOI[where]()

    def _bang_bat_kip(self) -> None:
        """Vài phút sau: bảng dự án đã liệt kê mọi thẻ vừa tạo."""
        self.bang |= self.cho_len_bang
        self.cho_len_bang = set()

    def _mang_anh(self, task_id: str, anh: str) -> bool:
        """Thẻ có mang tấm ảnh này không: làm bìa, hay đính kèm trong bình luận."""
        detail = self.details.get(task_id) or {}
        if detail.get("cover_image") == anh:
            return True
        return any(
            str(att.get("file_url") or "") == anh
            for comment in detail.get("comments") or []
            for att in comment.get("attachments") or []
        )

    def _the_mang(self, anh: str) -> list:
        return [
            child["name"]
            for child in self.details[PARENT]["children"]
            if self._mang_anh(child["name"], anh)
        ]

    def _gan_vao(self, task_id: str) -> list:
        return [url for task, url in self.gan if task == task_id]

    # ── ERP giả ─────────────────────────────────────────────────────────

    def _read(self, _key, _token, task_id):
        # ERP thật trả một bản mới mỗi lần đọc: đừng để test nhìn thấy thay
        # đổi qua một tham chiếu mà code thật không có.
        return copy.deepcopy(self.details[self.service._normalize_erp_task_id(task_id)])

    def _task_project_id(self, _key, _token, task_id):
        target = self.service._normalize_erp_task_id(task_id)
        self.doc_bang.append(target)
        if target in self.bang:
            return PROJECT
        if target in self.cho_len_bang:
            raise RuntimeError(DEADLOCK)
        raise RuntimeError(f"ERP Task {target} không thuộc Project {PROJECT}.")

    def _graphql(self, _query, variables=None, operation="", **_kwargs):
        variables = dict(variables or {})
        if operation == "CreateTask":
            child_id = f"TASK-2026-{9001 + len(self.tao):05d}"
            parent = variables["parentTask"]
            description = variables.get("description") or ""
            self.tao.append(
                {
                    "id": child_id,
                    "subject": variables["subject"],
                    "project": variables["project"],
                    "parent": parent,
                    "description": description,
                }
            )
            self.details[parent]["children"].append({"name": child_id, "subject": variables["subject"]})
            self.details[child_id] = {
                "name": child_id,
                "subject": variables["subject"],
                "status": variables.get("status") or "Open",
                "description": description,
                "cover_image": "",
                "comments": [],
                "parent_task": parent,
                "project": variables["project"],
            }
            (self.cho_len_bang if self.bang_tre else self.bang).add(child_id)
            return {"createTask": child_id}
        if operation == "AddTaskComment":
            self._co_hong("add_task_comment")
            task = self.service._normalize_erp_task_id(variables["name"])
            files = list(variables.get("attachments") or [])
            self.details[task]["comments"].append(
                {
                    "name": f"cmt-{len(self.gan)}",
                    "content": variables.get("content") or "",
                    "meta": variables.get("meta") or "",
                    "attachments": [{"file_url": url, "file_name": Path(url).name} for url in files],
                }
            )
            self.gan.extend((task, url) for url in files)
            return {"addTaskComment": {"name": f"cmt-{len(self.gan)}", "linked": len(files)}}
        if operation == "UpdateTaskMeta":
            task = self.service._normalize_erp_task_id(variables["task"])
            self.details[task]["meta"] = variables.get("meta") or ""
            return {"updateTaskMeta": {"name": task}}
        self.la.append(operation)
        raise RuntimeError(f"Test không giả lượt ERP {operation}.")

    def _upload(self, _key, _token, task_id, _data, _mime, name):
        self._co_hong("upload")
        self.upload.append((task_id, name))
        return f"/private/files/{name}"

    def _download(self, _key, _token, _task, att):
        self._co_hong("tai_anh")
        return f"bytes:{att.get('name')}".encode(), "image/png"

    def _cover(self, _key, _token, task_id, _data, _mime, name):
        self.details[task_id]["cover_image"] = f"/private/files/{name}"

    def _wire(self):
        return patch.multiple(
            self.service,
            _erp_allowed_project_ids=lambda: [PROJECT],
            _erp_task_project_id=self._task_project_id,
            _erp_task_detail=self._read,
            _erp_task_attachment_files=lambda *_a, **_k: [],
            _erp_board_name=lambda *_a, **_k: "",
            _erp_graphql=self._graphql,
            _erp_upload_file=self._upload,
            _erp_download_attachment_bytes=self._download,
            _erp_set_task_cover=self._cover,
            _erp_add_task_agent=lambda *_a, **_k: None,
            _erp_comment=lambda *_a, **_k: {"comment": "note"},
            # Cấp SKU và vá thẻ con là việc của bộ khác.
            sync_erp_skus=AsyncMock(return_value={"written": []}),
            repair_erp_idea_children=AsyncMock(return_value={"republished": [], "topped_up": [], "skipped": []}),
        )

    def _luot(self) -> dict:
        """Một lượt nút "Chạy" trên thẻ cha: nhận ảnh rồi fan-out."""
        with self._wire(), patch.object(
            self.service, "_flow_profile_specs", return_value=[self.profile]
        ), patch.object(self.service, "_run_flow_job", new_callable=AsyncMock):
            response = self.loop.run_until_complete(
                self.service.enqueue_erp_idea_jobs(ERPIdeaBatchRequest(task_id=PARENT))
            )
            for _ in range(3):
                self.loop.run_until_complete(asyncio.sleep(0))
        self.assertEqual([], self.la, "đường nhận ảnh gọi một lượt ERP mà test không giả")
        return response

    def _khoi_dong_lai(self) -> None:
        """App khởi động lại: mọi thứ trong bộ nhớ của service mất, thẻ ERP còn nguyên."""
        self.service = FlowWebService(self.store)


# ════════════════════════════════════════════════════════════════════════
# Đợt 2 — #4
# ════════════════════════════════════════════════════════════════════════


class HongSauCreateTaskTests(_NhanAnhTestCase):
    """#4 (đợt 2): hỏng sau ``CreateTask`` thì lượt sau không đẻ thẻ con thứ hai."""

    def _hai_luot(self, cho: str, *, khoi_dong_lai: bool = False) -> str:
        self._dung(dropped=(ANH_1,))
        self._hong_o(cho)

        self._luot()

        self.assertEqual(1, len(self.tao), f"lượt 1 phải tạo đúng một thẻ con rồi mới hỏng ở {cho}")
        child = self.tao[0]["id"]
        if cho != "hang_rao_con":
            self.assertFalse(self._mang_anh(child, ANH_1), f"kịch bản sai: hỏng ở {cho} mà thẻ vẫn có ảnh")
        self._bang_bat_kip()
        if khoi_dong_lai:
            self._khoi_dong_lai()

        self._luot()

        self.assertEqual(
            1,
            len(self.tao),
            f"hỏng ở {cho} sau CreateTask: lượt sau lại tạo thẻ con thứ hai cho cùng ảnh, "
            "thay vì gắn ảnh vào thẻ mang dấu đã có",
        )
        self.assertEqual(
            [child],
            self._the_mang(ANH_1),
            f"hỏng ở {cho}: ảnh phải nằm trên đúng thẻ con đã tạo ở lượt 1, không mất, không sang thẻ khác",
        )
        return child

    def test_hong_o_upload(self) -> None:
        # Ca thật: "The write operation timed out" (02118 của hvg-pc, 02121 và
        # 02126 của Mac).
        self._hai_luot("upload")

    def test_hong_o_hang_rao_the_con(self) -> None:
        self._hai_luot("hang_rao_con")

    def test_hong_o_add_task_comment(self) -> None:
        self._hai_luot("add_task_comment")

    def test_hong_o_upload_roi_khoi_dong_lai(self) -> None:
        # Dấu nằm trên thẻ, không nằm trong bộ nhớ: khởi động lại vẫn nhận ra.
        self._hai_luot("upload", khoi_dong_lai=True)

    def test_hong_truoc_create_task_thi_luot_sau_van_tao_nhu_cu(self) -> None:
        # Bài canh: 4 dòng HTTP 403 của 04628.  Chưa có thẻ nào thì lượt sau
        # phải tạo thẻ như hôm nay.
        self._dung(dropped=(ANH_1,))
        self._hong_o("tai_anh")

        self._luot()

        self.assertEqual([], self.tao, "hỏng lúc tải ảnh nguồn thì chưa được tạo thẻ con nào")

        self._luot()

        self.assertEqual(1, len(self.tao), "tải được ảnh ở lượt sau thì phải tạo đúng một thẻ con như cũ")
        self.assertEqual([self.tao[0]["id"]], self._the_mang(ANH_1))


class DungLaiTheRongTests(_NhanAnhTestCase):
    """#4 (đợt 2): chỉ gắn ảnh vào thẻ mang dấu của đúng ảnh ấy.

    Thẻ không dấu thì không đụng.  a6 đổi đặc tả ngày 12/09
    (``briefs/quyet-dinh-a6-nhan-anh-the-con-rong.md``): 02118, 02121, 02126
    đang chờ người dùng quyết, và ``taskDetail`` không có ``owner`` để tách
    thẻ bot tạo khỏi thẻ người tạo.
    """

    def test_the_rong_khong_dau_khong_duoc_dung_lai(self) -> None:
        # Như 02118: rỗng, không dấu.  Lượt ấy tạo thẻ mới như hôm nay.
        self._dung(dropped=(ANH_1,), rong=(CHILD_RONG,))

        self._luot()

        self.assertEqual(1, len(self.tao), "thẻ rỗng không dấu không phải của ảnh này: phải tạo thẻ mới như cũ")
        self.assertEqual([self.tao[0]["id"]], self._the_mang(ANH_1))
        self.assertEqual([], self._gan_vao(CHILD_RONG), "không được ghi gì lên thẻ rỗng không dấu")
        self.assertEqual("", self.details[CHILD_RONG]["cover_image"], "không được đặt bìa cho thẻ rỗng không dấu")

    def test_hai_anh_hai_the_rong_moi_the_mot_anh(self) -> None:
        self._dung(dropped=(ANH_1, ANH_2))
        self._hong_o("upload", lan=2)

        self._luot()

        self.assertEqual(2, len(self.tao), "lượt 1 phải tạo hai thẻ rồi hỏng cả hai lần upload")
        self._luot()

        self.assertEqual(2, len(self.tao), "lượt 2 không được tạo thêm thẻ nào: đã có hai thẻ mang dấu")
        ids = [item["id"] for item in self.tao]
        self.assertEqual([ids[0]], self._the_mang(ANH_1), "ảnh 1 phải lên đúng thẻ mang dấu ảnh 1")
        self.assertEqual([ids[1]], self._the_mang(ANH_2), "ảnh 2 phải lên đúng thẻ mang dấu ảnh 2")

    def test_the_con_nguoi_da_viet_khong_bi_dung_lai(self) -> None:
        # Bài canh: thẻ có mô tả, hay tiêu đề không phải "Idea N", là thẻ của người.
        self._dung(
            dropped=(ANH_1,),
            khac={"TASK-2026-00617": {"subject": "Hoa hồng đỏ", "description": ""}},
        )

        self._luot()

        self.assertEqual(1, len(self.tao), "không có thẻ mang dấu thì phải tạo thẻ mới như cũ")
        self.assertEqual([self.tao[0]["id"]], self._the_mang(ANH_1))

    def test_the_rong_da_bi_keo_sang_cot_khac_khong_bi_dung_lai(self) -> None:
        # Bài canh: thẻ rỗng không dấu, đã rời *Cần làm*.
        self._dung(
            dropped=(ANH_1,),
            khac={CHILD_RONG: {"subject": "Idea 3", "description": "", "status": "Working"}},
        )

        self._luot()

        self.assertEqual(1, len(self.tao))
        self.assertEqual([self.tao[0]["id"]], self._the_mang(ANH_1))

    def test_anh_da_co_the_giu_thi_khong_ghi_gi_len_the_rong(self) -> None:
        # Bài canh: ảnh đã có chủ thì không upload gì, không đụng thẻ rỗng.
        self._dung(dropped=(ANH_1,), rong=(CHILD_RONG,))
        self.details[CHILD_A]["cover_image"] = ANH_1

        self._luot()

        self.assertEqual([], self.tao)
        self.assertEqual([], self.upload, "ảnh đã có thẻ giữ thì không upload lên đâu cả")
        self.assertEqual([], self.gan)


class DauNhanAnhTests(_NhanAnhTestCase):
    """#4 (đợt 2): dấu nhận ảnh ghi trong ``CreateTask``, đọc lại ở lượt sau."""

    def _dong(self, logs, dau_cau: str) -> list:
        return [record.getMessage() for record in logs.records if dau_cau in record.getMessage()]

    def test_create_task_ghi_dau_vao_mo_ta(self) -> None:
        self._dung(dropped=(ANH_1,))

        self._luot()

        self.assertEqual(1, len(self.tao))
        description = self.tao[0]["description"]
        self.assertEqual(
            [ANH_1],
            [match.group(1).strip() for match in self.service.ERP_IDEA_INTAKE_MARKER.finditer(description)],
            "CreateTask phải mang dấu của đúng ảnh trong description, không thêm lời gọi ERP nào",
        )
        self.assertEqual(
            "",
            self.service._html_to_text(description),
            "dấu không được thành chữ khi bỏ HTML: thẻ vẫn phải trống",
        )
        self.assertTrue(
            self.service._erp_idea_is_blank({"subject": self.tao[0]["subject"], "description": description}),
            "thẻ vừa tạo chỉ có dấu thì fan-out vẫn phải coi là trống",
        )

    def test_anh_len_dung_the_mang_dau(self) -> None:
        self._dung(dropped=(ANH_1,), khac={CHILD_DAU: the_mang_dau(DAU_1)})

        self._luot()

        self.assertEqual([], self.tao, "đã có thẻ mang dấu ảnh này thì CreateTask phải chạy 0 lần")
        self.assertEqual([CHILD_DAU], self._the_mang(ANH_1), "ảnh phải lên đúng thẻ mang dấu của nó")

    def test_the_mang_dau_anh_khac_khong_bi_dung(self) -> None:
        # Bài canh: dấu là ảnh 2, ảnh thả là ảnh 1.
        self._dung(dropped=(ANH_1,), khac={CHILD_DAU: the_mang_dau(DAU_2)})

        self._luot()

        self.assertEqual(1, len(self.tao))
        self.assertEqual([self.tao[0]["id"]], self._the_mang(ANH_1))
        self.assertEqual([], self._gan_vao(CHILD_DAU), "thẻ mang dấu ảnh khác không được nhận ảnh này")

    def test_the_mang_dau_da_co_tep_khac_thi_anh_coi_nhu_co_chu(self) -> None:
        # Người đã thay ảnh trên thẻ bot tạo.  Dấu vẫn là lời nhận: không tạo
        # thẻ trùng, không ghi gì thêm.
        self._dung(
            dropped=(ANH_1,),
            khac={CHILD_DAU: the_mang_dau(DAU_1, cover_image="/private/files/doi-anh.png")},
        )

        self._luot()

        self.assertEqual([], self.tao, "ảnh đã có thẻ mang dấu thì không được tạo thẻ mới")
        self.assertEqual([], self.upload, "thẻ đã có tệp thì không upload thêm")
        self.assertEqual([], self.gan)

    def test_gan_vao_the_mang_dau_hong_thi_luot_sau_gan_lai(self) -> None:
        self._dung(dropped=(ANH_1,), khac={CHILD_DAU: the_mang_dau(DAU_1)})
        self._hong_o("upload")

        self._luot()

        self.assertEqual([], self.tao, "gắn vào thẻ mang dấu hỏng thì không được tạo thẻ mới")
        self.assertEqual([], self._the_mang(ANH_1))

        self._luot()

        self.assertEqual([], self.tao)
        self.assertEqual([CHILD_DAU], self._the_mang(ANH_1), "lượt sau phải gắn lại vào đúng thẻ mang dấu")

    def test_gan_vao_the_mang_dau_co_dong_log_rieng(self) -> None:
        # c8 đếm "đã thành thẻ con" để ra số CreateTask: gắn lại thì không
        # được dùng câu ấy.
        self._dung(dropped=(ANH_1,), khac={CHILD_DAU: the_mang_dau(DAU_1)})

        with self.assertLogs("flow_web.service", "INFO") as logs:
            self._luot()

        lines = self._dong(logs, "đã gắn vào thẻ con")
        self.assertEqual(1, len(lines), "gắn vào thẻ mang dấu phải có đúng một dòng log riêng")
        self.assertIn("17ee9ea.png", lines[0])
        self.assertIn(CHILD_DAU, lines[0])
        self.assertEqual([], self._dong(logs, "đã thành thẻ con"))

    def test_prompt_idea_khong_mang_dau(self) -> None:
        # Bài canh: ``_html_to_text`` đã bỏ chú thích HTML.
        self._dung()
        child = {
            "subject": "Idea 3",
            "description": "<p>Khăn tay đặt cạnh cây thông</p>" + DAU_1,
            "cover_image": ANH_1,
        }

        prompt = self.service._erp_idea_prompt(self.details[PARENT], child, own_image=True)

        self.assertNotIn("FLOW_V2_IDEA", prompt)
        self.assertIn("Khăn tay đặt cạnh cây thông", prompt)

    def test_prompt_idea_khong_mang_dau_bi_escape(self) -> None:
        self._dung()
        child = {
            "subject": "Idea 3",
            "description": "<p>Khăn tay đặt cạnh cây thông</p>" + DAU_1_ESCAPE,
            "cover_image": ANH_1,
        }

        prompt = self.service._erp_idea_prompt(self.details[PARENT], child, own_image=True)

        self.assertNotIn("FLOW_V2_IDEA", prompt, "ERP trả mô tả đã escape thì dấu lọt vào prompt Flow")
        self.assertIn("Khăn tay đặt cạnh cây thông", prompt)

    def test_ghi_chu_mo_ta_tool_tay_khong_mang_dau(self) -> None:
        # Tool tay đọc thẻ qua ``cards/<id>``: ``desc`` là mô tả thô, đi thẳng
        # vào Gemini (17529, 17582) và brief Flow (18685).
        card = {"desc": "<p>Khăn tay đặt cạnh cây thông</p>\n" + DAU_1}

        note = self.service._flow_operator_erp_task_description_note(card)

        self.assertNotIn("FLOW_V2_IDEA", note, "dấu nhận ảnh lọt vào ghi chú mô tả gửi Gemini và Flow")
        self.assertIn("Khăn tay đặt cạnh cây thông", note)


class FanOutBoQuaTheRongTests(_NhanAnhTestCase):
    """Câu a của a6: thẻ rỗng bị loại khỏi fan-out (``service.py:3519``)."""

    LY_DO_TRONG = "thẻ con chưa có nội dung idea (tiêu đề/mô tả trống)"

    def _ly_do(self, response) -> dict:
        return {item["task_id"]: item["reason"] for item in response.get("skipped") or []}

    def test_the_rong_khong_duoc_xep_job(self) -> None:
        # Bài canh: "Idea 3" là 6 ký tự, dưới ERP_IDEA_MIN_TEXT_CHARS = 8.
        self._dung(parent_meta=CO_CONTENT, rong=(CHILD_RONG,))

        response = self._luot()

        self.assertEqual([CHILD_A, CHILD_B], [item["task_id"] for item in response["queued"]])
        self.assertEqual(self.LY_DO_TRONG, self._ly_do(response).get(CHILD_RONG))

    def test_the_chi_mang_dau_khong_duoc_xep_job(self) -> None:
        # Bài canh (đợt 2): dấu ở dạng chú thích HTML không thành chữ.
        self._dung(parent_meta=CO_CONTENT, khac={CHILD_DAU: the_mang_dau(DAU_1)})

        response = self._luot()

        self.assertEqual([CHILD_A, CHILD_B], [item["task_id"] for item in response["queued"]])
        self.assertEqual(self.LY_DO_TRONG, self._ly_do(response).get(CHILD_DAU))

    def test_the_chi_mang_dau_bi_escape_khong_duoc_xep_job(self) -> None:
        # Đợt 2: nếu ERP trả mô tả đã escape, ``unescape`` biến dấu thành chữ,
        # thẻ không còn trống và chạy bằng ảnh thẻ cha.
        self._dung(parent_meta=CO_CONTENT, khac={CHILD_DAU: the_mang_dau(DAU_1_ESCAPE)})

        response = self._luot()

        self.assertEqual(
            [CHILD_A, CHILD_B],
            [item["task_id"] for item in response["queued"]],
            "thẻ chỉ mang dấu bị xếp job: chạy bằng ảnh thẻ cha, tốn quota",
        )
        self.assertEqual(self.LY_DO_TRONG, self._ly_do(response).get(CHILD_DAU))


# ════════════════════════════════════════════════════════════════════════
# Đợt 1 — #1 và #2
# ════════════════════════════════════════════════════════════════════════


class HangRaoTheConVuaTaoTests(_NhanAnhTestCase):
    """#1 (đợt 1): bỏ lần đọc bảng cho thẻ vừa tạo, chỉ ở đường nhận ảnh."""

    def _tao_the_ngoai_bang(self) -> str:
        """Tạo một thẻ con bằng code thật; bảng chưa kịp liệt kê nó."""
        self._dung()
        self.bang_tre = True
        with self._wire():
            child = self.service._erp_create_child_task("k", "t", PARENT, PROJECT, "Idea 9")
        # Chỉ đếm lần đọc bảng của bước gắn ảnh phía sau.
        self.doc_bang.clear()
        return child

    def test_nhan_anh_khong_doc_bang_cho_the_vua_tao(self) -> None:
        self._dung(dropped=(ANH_1,))
        self.bang_tre = True

        self._luot()

        child = self.tao[0]["id"]
        self.assertNotIn(
            child,
            self.doc_bang,
            "đường nhận ảnh vẫn đọc bảng để rào thẻ con vừa tạo; CreateTask đã ghim project và parentTask",
        )
        self.assertEqual([child], self._the_mang(ANH_1), "bảng chưa kịp liệt kê thẻ mới thì ảnh vẫn phải lên thẻ")

    def test_nhan_anh_van_rao_the_cha(self) -> None:
        # Bài canh: hàng rào nằm ở thẻ cha (14872) và không được bỏ.
        self._dung(dropped=(ANH_1,))

        self._luot()

        self.assertIn(PARENT, self.doc_bang)

    def test_goi_mac_dinh_van_rao_the_ngoai_bang(self) -> None:
        # Bài canh: không truyền tham số mới thì y như cũ.
        self._dung()
        with self._wire(), self.assertRaises(RuntimeError):
            self.service._erp_attach_file_bytes("k", "t", "TASK-2026-99999", b"x", "image/png", "a.png", False)

        self.assertIn("TASK-2026-99999", self.doc_bang)
        self.assertEqual([], self.gan)

    def test_the_vua_tao_goi_mac_dinh_van_bi_rao(self) -> None:
        # Bài canh: miễn đọc bảng chỉ đi theo tham số, không theo việc thẻ do app tạo.
        child = self._tao_the_ngoai_bang()
        with self._wire(), self.assertRaises(RuntimeError):
            self.service._erp_attach_file_bytes("k", "t", child, b"x", "image/png", "a.png", False, "", "", True)

        self.assertIn(child, self.doc_bang)
        self.assertEqual([], self.gan)

    def test_dinh_kem_tu_url_van_rao(self) -> None:
        child = self._tao_the_ngoai_bang()
        with self._wire(), patch.object(
            self.service, "_read_remote_file", return_value=(b"x", "image/png")
        ), self.assertRaises(RuntimeError):
            self.service._erp_attach_file_from_url(
                "k", "t", child, "https://example.invalid/a.png", "a.png", "image/png", False
            )

        self.assertIn(child, self.doc_bang)
        self.assertEqual([], self.gan)

    def test_dinh_kem_co_du_phong_bia_van_rao(self) -> None:
        child = self._tao_the_ngoai_bang()
        with self._wire(), self.assertRaises(RuntimeError):
            self.loop.run_until_complete(
                self.service._erp_attach_file_bytes_with_cover_fallback(
                    "job-1", 0, "k", "t", child, b"x", "image/png", "a.png", False
                )
            )

        self.assertIn(child, self.doc_bang)
        self.assertEqual([], self.gan)

    def test_tham_so_moi_mien_doc_bang_cho_the_vua_tao(self) -> None:
        child = self._tao_the_ngoai_bang()
        with self._wire():
            self.service._erp_attach_file_bytes(
                "k", "t", child, b"x", "image/png", "a.png", False, "", "", True, created_in_project=PROJECT
            )

        self.assertNotIn(child, self.doc_bang, "created_in_project phải bỏ lần đọc bảng cho thẻ app vừa tạo")
        self.assertEqual([(child, "/private/files/a.png")], self.gan)

    def test_tham_so_moi_van_choi_du_an_ngoai_danh_sach(self) -> None:
        child = self._tao_the_ngoai_bang()
        with self._wire(), self.assertRaises(RuntimeError, msg="project ngoài danh sách phải bị chối"):
            self.service._erp_attach_file_bytes(
                "k", "t", child, b"x", "image/png", "a.png", False, "", "", True, created_in_project="PROJ-9999"
            )

        self.assertEqual([], self.gan, "không một bình luận nào được lên thẻ khi project ngoài danh sách")

    def test_tham_so_moi_khong_mien_cho_the_khong_do_app_tao(self) -> None:
        # Thẻ không do tiến trình này tạo thì tham số không miễn được gì.
        self._dung(rong=(CHILD_RONG,))
        self.bang.discard(CHILD_RONG)
        with self._wire(), self.assertRaises(RuntimeError, msg="thẻ không do app tạo phải đi hàng rào cũ"):
            self.service._erp_attach_file_bytes(
                "k", "t", CHILD_RONG, b"x", "image/png", "a.png", False, "", "", True, created_in_project=PROJECT
            )

        self.assertIn(CHILD_RONG, self.doc_bang)
        self.assertEqual([], self.gan)


class LogTheConTests(_NhanAnhTestCase):
    """#2 (i) (đợt 1): dòng log hỏng nói được thẻ con nào đã tạo."""

    def _dong_hong(self, logs) -> list:
        return [
            record.getMessage()
            for record in logs.records
            if record.getMessage().startswith("Không tạo được thẻ con cho ảnh")
        ]

    def test_hong_sau_create_task_log_co_ma_the_con(self) -> None:
        self._dung(dropped=(ANH_1,))
        self._hong_o("upload")

        with self.assertLogs("flow_web.service", "WARNING") as logs:
            self._luot()

        lines = self._dong_hong(logs)
        self.assertEqual(1, len(lines), "đầu câu cũ phải giữ nguyên để c8 đếm tiếp")
        self.assertIn("17ee9ea.png", lines[0])
        self.assertIn(PARENT, lines[0])
        self.assertIn(
            self.tao[0]["id"], lines[0], "thẻ con đã tạo mà dòng log không nói mã: c8 phải đoán 02118 bằng dải số"
        )

    def test_hong_truoc_create_task_log_nhu_cu(self) -> None:
        self._dung(dropped=(ANH_1,))
        self._hong_o("tai_anh")

        with self.assertLogs("flow_web.service", "WARNING") as logs:
            self._luot()

        lines = self._dong_hong(logs)
        self.assertEqual(1, len(lines))
        self.assertIn("17ee9ea.png", lines[0])
        self.assertIn(PARENT, lines[0])


class ChuyenCotKhongJobTests(_NhanAnhTestCase):
    """#2 (ii) (đợt 1): ``_erp_advance_task_status`` hỏng mà không có job vẫn để lại dấu."""

    def _chuyen(self, job_id: str, *, hong: bool = True):
        def _update(_key, _token, _task, _status):
            if hong:
                raise RuntimeError(DEADLOCK)
            return {}

        with patch.multiple(
            self.service,
            _erp_task_detail=lambda *_a, **_k: {"name": CHILD_A, "status": "Open"},
            _erp_update_task_status=_update,
        ), patch.object(self.store, "append_log", new_callable=AsyncMock) as append_log:
            moved = self.loop.run_until_complete(self.service._erp_advance_task_status(job_id, CHILD_A, "Working"))
        return moved, append_log

    def test_khong_job_ma_hong_thi_co_dung_mot_dong_log(self) -> None:
        # Đường bot: advance_erp_pipeline(task_id) không có job, không bao giờ
        # ném, nên agent_bot.py:2897 không có gì để ghi.  Hôm nay im hẳn.
        with self.assertLogs("flow_web.service", "WARNING") as logs:
            moved, append_log = self._chuyen("")

        self.assertFalse(moved)
        self.assertEqual(1, len(logs.records), "chuyển cột hỏng mà không có job: phải đúng một dòng log")
        self.assertIn(CHILD_A, logs.records[0].getMessage())
        self.assertIn("Working", logs.records[0].getMessage())
        append_log.assert_not_awaited()

    def test_co_job_thi_ghi_vao_job_nhu_cu(self) -> None:
        # Bài canh.
        moved, append_log = self._chuyen("job-1")

        self.assertFalse(moved)
        append_log.assert_awaited_once()
        job_id, text = append_log.await_args.args
        self.assertEqual("job-1", job_id)
        self.assertIn(f"Không đổi được trạng thái Task {CHILD_A}", text)

    def test_khong_job_ma_chuyen_duoc_thi_khong_log_canh_bao(self) -> None:
        # Bài canh.
        with self.assertNoLogs("flow_web.service", "WARNING"):
            moved, _append_log = self._chuyen("", hong=False)

        self.assertTrue(moved)


class DayCotKhongJobTests(_NhanAnhTestCase):
    """#2 (iii) (đợt 1), câu 4 của a6: except ngoài của ``advance_erp_pipeline``.

    Không có job thì nhánh ấy (15161–15166) chỉ trả ``reason`` và im.
    """

    def _day(self, job_id: str):
        def _rao(_key, _token, _task):
            raise RuntimeError(DEADLOCK)

        with patch.object(self.service, "_erp_assert_task_in_project", _rao), patch.object(
            self.store, "append_log", new_callable=AsyncMock
        ) as append_log:
            result = self.loop.run_until_complete(self.service.advance_erp_pipeline(CHILD_A, job_id=job_id))
        return result, append_log

    def test_khong_job_ma_hong_thi_co_dung_mot_dong_log(self) -> None:
        with self.assertLogs("flow_web.service", "WARNING") as logs:
            result, append_log = self._day("")

        self.assertFalse(result["moved"])
        self.assertEqual(1, len(logs.records), "đẩy cột hỏng mà không có job: phải đúng một dòng log")
        message = logs.records[0].getMessage()
        self.assertIn("Không đẩy được Task", message, "cùng kiểu câu với dòng ghi vào job")
        self.assertIn(CHILD_A, message)
        append_log.assert_not_awaited()

    def test_co_job_thi_ghi_vao_job_nhu_cu(self) -> None:
        # Bài canh.
        result, append_log = self._day("job-1")

        self.assertFalse(result["moved"])
        append_log.assert_awaited_once()
        job_id, text = append_log.await_args.args
        self.assertEqual("job-1", job_id)
        self.assertIn(f"Không đẩy được Task {CHILD_A} sang cột kế", text)


if __name__ == "__main__":
    unittest.main()

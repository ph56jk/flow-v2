from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, call, patch
from urllib.error import HTTPError

from fastapi import HTTPException

from flow_web.schemas import (
    CreateJobRequest,
    ERPConfig,
    ERPConfigUpdateRequest,
    ERPIdeaBatchRequest,
    JobArtifact,
    JobRecord,
)
from flow_web.service import FlowBrowserProfile, FlowWebService
from flow_web.shot_rules import PRODUCT_SHOT_RULES
from flow_web.store import StateStore


class _Response:
    status = 200

    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class _StillRunning:
    """Stands in for a job task in flight, without leaving a real one behind."""

    def done(self) -> bool:
        return False


def _idea_parent_meta(product_type: str = "Khăn tay cô dâu thêu tay", content: str = "Có") -> str:
    """Khối Thuộc tính thẻ cha theo quy trình 11/09: bốn khoá bắt buộc + ``content``.

    Thiếu một khoá thì bot không tách thẻ con, không tạo ảnh; ``content``
    khác "Có" thì chỉ tách.  Fixture cũ khai sẵn cho đủ, để các bài này vẫn
    đo đúng thứ chúng đo.  Lời khai ``product_type`` luôn thắng tên thẻ và
    tên bảng khi chọn rule, nên bài nào đọc rule từ tên thì khai khớp tên ấy.
    """
    return "\n".join(
        [
            f"product_type: {product_type}",
            "product_group: Thêu tay",
            "fulfillment: HaviGroup",
            "sales_channel: Etsy",
            f"content: {content}",
        ]
    )


class _ErpServiceTestCase(unittest.TestCase):
    """Shared harness: a temp state store plus a credentialed FlowWebService."""

    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        state_file = root / "state.json"
        self.patches = [
            patch("flow_web.store.STATE_FILE", state_file),
            patch("flow_web.store.ensure_app_dirs", lambda: root.mkdir(parents=True, exist_ok=True)),
            patch("flow_web.service.ensure_app_dirs", lambda: root.mkdir(parents=True, exist_ok=True)),
            # Cô lập cache Gemini và bảng dữ liệu, tránh đọc cache đĩa từ data/ thật
            # (như fixture _isolated_data_dir trong tests/conftest.py của pytest).
            patch("flow_web.service.DATA_DIR", root / "data"),
        ]
        for item in self.patches:
            item.start()
        FlowWebService._visual_rule_file_cache = None
        self.store = StateStore()
        self.service = FlowWebService(self.store)
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(api_key="test-key", api_secret="test-secret", project_id="PROJ-0049")
            )
        )

    def tearDown(self) -> None:
        FlowWebService._visual_rule_file_cache = None
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()
        self.loop.close()
        asyncio.set_event_loop(None)


class HvgErpIntegrationTests(_ErpServiceTestCase):
    def test_graphql_uses_post_header_without_secret_in_url(self) -> None:
        with patch("flow_web.service.urlopen", return_value=_Response({"data": {"projectOverview": {}}})) as mocked:
            payload = self.service._erp_graphql(
                "query ProjectOverview($project: String!) { projectOverview(project: $project) }",
                {"project": "PROJ-0049"},
                "ProjectOverview",
                key="test-key",
                token="test-secret",
            )

        self.assertEqual({"projectOverview": {}}, payload)
        request = mocked.call_args.args[0]
        self.assertEqual(
            "https://erp.havigroup.llc/api/method/hvg_workspace.graphql.endpoint.graphql",
            request.full_url,
        )
        self.assertNotIn("test-key", request.full_url)
        self.assertNotIn("test-secret", request.full_url)
        self.assertEqual("token test-key:test-secret", request.get_header("Authorization"))
        self.assertEqual("Flow-v2-HaviGroup-ERP/1.0", request.get_header("User-agent"))
        self.assertEqual("POST", request.get_method())

    def test_config_stays_on_one_project_and_masks_credentials(self) -> None:
        response = self.loop.run_until_complete(
            self.service.update_erp_config(
                ERPConfigUpdateRequest(
                    api_key="new-key",
                    api_secret="new-secret",
                    base_url="https://erp.havigroup.llc",
                    project_id="PROJ-0049",
                    task_id="TASK-0001",
                    status="Open",
                )
            )
        )
        self.assertNotIn("api_key", response)
        self.assertNotIn("api_secret", response)
        self.assertEqual("PROJ-0049", response["project_id"])

        # The owner may point the app at another project, but the app still
        # works inside exactly one project and rejects anything malformed.
        switched = self.loop.run_until_complete(
            self.service.update_erp_config(ERPConfigUpdateRequest(project_id="PROJ-0013"))
        )
        self.assertEqual("PROJ-0013", switched["project_id"])
        self.assertEqual("PROJ-0013", self.service._erp_allowed_project_id())

        with self.assertRaises(HTTPException) as ctx:
            self.loop.run_until_complete(
                self.service.update_erp_config(ERPConfigUpdateRequest(project_id="not-a-project"))
            )
        self.assertEqual(400, ctx.exception.status_code)

    def test_the_agent_projects_setting_widens_the_fence_without_moving_it(self) -> None:
        # Dropping the agent bot onto a card is meant to be the only setup
        # step, so a card outside ERP_PROJECT_ID has to be reachable — but the
        # configured project must stay allowed, and stay the default.
        self.assertEqual(["PROJ-0049"], self.service._erp_allowed_project_ids())
        with patch.dict(os.environ, {"ERP_AGENT_PROJECTS": "proj-0013 ; PROJ-0051"}):
            self.assertEqual(
                ["PROJ-0049", "PROJ-0013", "PROJ-0051"], self.service._erp_allowed_project_ids()
            )
            self.assertEqual("PROJ-0013", self.service._erp_required_project_id("PROJ-0013"))
            self.assertEqual("PROJ-0049", self.service._erp_required_project_id(""))

        with self.assertRaisesRegex(RuntimeError, "PROJ-0049"):
            self.service._erp_required_project_id("PROJ-0013")

    def test_a_board_the_bot_was_added_to_is_allowed_without_editing_env(self) -> None:
        # Thêm bot vào một board trên ERP là xong. Không phải khai lại board đó
        # ở ERP_AGENT_PROJECTS nữa, nếu không "chỉ cần thêm bot" là nói dối.
        bot = SimpleNamespace(state=SimpleNamespace(projects=["PROJ-0013", "proj-0051"]))
        with patch.object(self.service, "agent_bot", return_value=bot):
            self.assertEqual(
                ["PROJ-0049", "PROJ-0013", "PROJ-0051"], self.service._erp_allowed_project_ids()
            )
            self.assertEqual("PROJ-0051", self.service._erp_required_project_id("PROJ-0051"))
            # Dự án mặc định vẫn là mặc định.
            self.assertEqual("PROJ-0049", self.service._erp_required_project_id(""))

    def test_a_board_the_bot_no_longer_sees_falls_back_out_of_the_fence(self) -> None:
        # Gỡ bot khỏi board là board đó hết chạy — phạm vi do ERP quyết.
        bot = SimpleNamespace(state=SimpleNamespace(projects=[]))
        with patch.object(self.service, "agent_bot", return_value=bot):
            self.assertEqual(["PROJ-0049"], self.service._erp_allowed_project_ids())
            with self.assertRaisesRegex(RuntimeError, "PROJ-0013"):
                self.service._erp_required_project_id("PROJ-0013")

    def test_no_bot_configured_leaves_the_fence_exactly_as_it_was(self) -> None:
        with patch.object(self.service, "agent_bot", return_value=None):
            self.assertEqual(["PROJ-0049"], self.service._erp_allowed_project_ids())

    def test_a_bot_that_cannot_be_built_does_not_take_the_fence_down_with_it(self) -> None:
        with patch.object(self.service, "agent_bot", side_effect=RuntimeError("hỏng")):
            self.assertEqual(["PROJ-0049"], self.service._erp_allowed_project_ids())

    def test_the_env_fence_and_the_bots_own_boards_add_up(self) -> None:
        bot = SimpleNamespace(state=SimpleNamespace(projects=["PROJ-0013", "PROJ-0077"]))
        with patch.dict(os.environ, {"ERP_AGENT_PROJECTS": "PROJ-0013"}), patch.object(
            self.service, "agent_bot", return_value=bot
        ):
            # PROJ-0013 khai hai lần vẫn chỉ có một chỗ trong danh sách.
            self.assertEqual(
                ["PROJ-0049", "PROJ-0013", "PROJ-0077"], self.service._erp_allowed_project_ids()
            )

    def test_a_task_is_placed_in_whichever_allowed_project_actually_holds_it(self) -> None:
        boards = {
            "PROJ-0049": {"columns": [{"status": "Open", "tasks": [{"name": "TASK-0001"}]}]},
            "PROJ-0013": {"columns": [{"status": "Open", "tasks": [{"name": "TASK-0002"}]}]},
        }
        with patch.dict(os.environ, {"ERP_AGENT_PROJECTS": "PROJ-0013"}), patch.object(
            self.service, "_erp_task_board", side_effect=lambda _k, _t, project: boards[project]
        ):
            self.assertEqual("PROJ-0049", self.service._erp_task_project_id("key", "secret", "TASK-0001"))
            self.assertEqual("PROJ-0013", self.service._erp_task_project_id("key", "secret", "TASK-0002"))
            # A card in neither board is refused rather than defaulted, or its
            # images would be published back onto the wrong project's cards.
            with self.assertRaisesRegex(RuntimeError, "TASK-0009"):
                self.service._erp_task_project_id("key", "secret", "TASK-0009")

    def test_stale_local_state_cannot_redirect_credentialed_graphql_requests(self) -> None:
        normalized = self.store._normalize_erp_config(
            ERPConfig(api_key="key", api_secret="secret", base_url="https://unexpected.example")
        )
        self.assertEqual("https://erp.havigroup.llc", normalized.base_url)

    def test_graphql_errors_and_auth_failures_are_explicit_and_redacted(self) -> None:
        with patch("flow_web.service.urlopen", return_value=_Response({"data": None, "errors": [{"message": "bad query"}]})):
            with self.assertRaisesRegex(RuntimeError, "ERP GraphQL: bad query"):
                self.service._erp_graphql("query { myWork }", {}, "MyWork", key="key", token="secret")

        for status in (401, 429):
            error = HTTPError("https://erp.havigroup.llc", status, "error", {}, io.BytesIO(b"key=key token=secret"))
            if status == 429:
                self.service._erp_rate_limiter.reset()
                with patch("flow_web.service.time.sleep") as slept:
                    with patch("flow_web.service.urlopen", side_effect=error):
                        with self.assertRaisesRegex(RuntimeError, f"HTTP {status}"):
                            self.service._erp_graphql("query { myWork }", {}, "MyWork", key="key", token="secret")
                self.assertEqual([call(10.0), call(30.0), call(60.0)], slept.call_args_list)
            else:
                with patch("flow_web.service.urlopen", side_effect=error):
                    with self.assertRaisesRegex(RuntimeError, f"HTTP {status}"):
                        self.service._erp_graphql("query { myWork }", {}, "MyWork", key="key", token="secret")

    def test_a_read_timeout_is_retried_then_named(self) -> None:
        """Đọc chậm là sự cố hay gặp nhất, và từng là sự cố duy nhất không ai đọc nổi.

        ``TimeoutError`` không phải là con của ``URLError``, nên nó từng chui
        qua cả hai nhánh bắt lỗi ở đây rồi ra thẳng route: đo trên máy thật,
        ``POST /api/erp/sku/plan`` trả về đúng một dòng ``500`` rỗng sau 44,7s
        trong khi cùng câu ``taskBoard`` đó chạy xong trong 0,5s ở lượt sau.
        """
        with patch("flow_web.service.time.sleep"):
            with patch("flow_web.service.urlopen", side_effect=TimeoutError("timed out")) as mocked:
                with self.assertRaisesRegex(RuntimeError, "không trả lời trong 30s"):
                    self.service._erp_graphql("query { myWork }", {}, "MyWork", key="key", token="secret")
        self.assertEqual(self.service.ERP_READ_ATTEMPTS, mocked.call_count)

    def test_a_read_that_recovers_on_the_second_try_still_answers(self) -> None:
        answers = [TimeoutError("timed out"), _Response({"data": {"myWork": []}})]
        with patch("flow_web.service.time.sleep"):
            with patch("flow_web.service.urlopen", side_effect=answers):
                payload = self.service._erp_graphql("query { myWork }", {}, "MyWork", key="key", token="secret")
        self.assertEqual({"myWork": []}, payload)

    def test_a_mutation_is_never_sent_twice(self) -> None:
        # Gửi lại một ``mutation`` đã hết giờ là ghi hai lần: ``addTaskComment``
        # không có khoá chống trùng, nên thẻ sẽ mọc ra hai bình luận giống hệt.
        with patch("flow_web.service.time.sleep"):
            with patch("flow_web.service.urlopen", side_effect=TimeoutError("timed out")) as mocked:
                with self.assertRaises(RuntimeError):
                    self.service._erp_graphql(
                        "mutation AddTaskComment($name: String!) { addTaskComment(name: $name) }",
                        {"name": "TASK-0001"},
                        "AddTaskComment",
                        key="key",
                        token="secret",
                    )
        self.assertEqual(1, mocked.call_count)

    def test_task_board_is_normalized_as_project_tasks(self) -> None:
        board = {
            "columns": [
                {"status": "Open", "tasks": [{"name": "TASK-0001", "subject": "Source product"}]},
            ],
            "total": 1,
        }
        with patch.object(self.service, "_erp_task_board", return_value=board):
            tasks = self.service._erp_get_json("boards/PROJ-0049/cards", "key", "secret")

        self.assertEqual(1, len(tasks))
        self.assertEqual("TASK-0001", tasks[0]["id"])
        self.assertEqual("Open", tasks[0]["idList"])
        self.assertIn("erp.havigroup.llc", tasks[0]["url"])

    def test_task_detail_checks_membership_before_reading_task(self) -> None:
        with patch.object(self.service, "_erp_assert_task_in_project") as assert_member, patch.object(
            self.service, "_erp_task_detail", return_value={"name": "TASK-0001", "subject": "Source product"}
        ):
            self.service._erp_get_json("cards/TASK-0001", "key", "secret")

        assert_member.assert_called_once_with("key", "secret", "TASK-0001")

    def test_archive_writes_only_dashboard_approved_https_artifact_urls_to_source_task(self) -> None:
        request = CreateJobRequest(
            type="image",
            erp_enabled=True,
            erp_project_id="PROJ-0049",
            erp_source_task_id="TASK-0001",
            erp_task_id="TASK-0001",
        )
        artifacts = [
            JobArtifact(media_name="approved.jpg", url="https://media.example/approved.jpg"),
            JobArtifact(media_name="rejected.jpg", url="https://media.example/rejected.jpg"),
        ]
        job = JobRecord(
            type="image",
            result={
                "dashboard_approvals": {
                    "0": {"status": "approved"},
                    "1": {"status": "rejected"},
                }
            },
        )
        self.loop.run_until_complete(self.store.add_job(job))
        with patch.object(self.service, "_erp_assert_task_in_project") as assert_task, patch.object(
            self.service,
            "_erp_attach_url",
            return_value={"id": "https://media.example/approved.jpg", "name": "approved.jpg", "url": "https://media.example/approved.jpg"},
        ) as attach:
            result = self.loop.run_until_complete(self.service._archive_erp_artifacts(job.id, request, artifacts))

        assert_task.assert_called_once_with("test-key", "test-secret", "TASK-0001")
        attach.assert_called_once()
        self.assertEqual("https://media.example/approved.jpg", attach.call_args.args[3])
        self.assertEqual(1, result["sent"])
        self.assertEqual(1, result["rejected"])

    def test_archive_waits_without_a_dashboard_decision(self) -> None:
        request = CreateJobRequest(type="image", erp_enabled=True, erp_project_id="PROJ-0049", erp_source_task_id="TASK-0001")
        artifact = JobArtifact(media_name="pending.jpg", url="https://media.example/pending.jpg")
        job = JobRecord(type="image", result={"dashboard_approvals": {}})
        self.loop.run_until_complete(self.store.add_job(job))
        with patch.object(self.service, "_erp_attach_url") as attach:
            result = self.loop.run_until_complete(self.service._archive_erp_artifacts(job.id, request, [artifact]))

        attach.assert_not_called()
        self.assertTrue(result["waiting_approval"])

    def test_resume_preserves_original_indexes_when_first_artifact_is_rejected(self) -> None:
        request = CreateJobRequest(type="image", erp_enabled=True, erp_project_id="PROJ-0049")
        rejected = JobArtifact(media_name="rejected.jpg", url="https://media.example/rejected.jpg")
        approved = JobArtifact(media_name="approved.jpg", url="https://media.example/approved.jpg")
        job = JobRecord(
            type="image",
            input=request.model_dump() if hasattr(request, "model_dump") else request.dict(),
            artifacts=[rejected, approved],
            result={
                "dashboard_approvals": {
                    "0": {"status": "rejected"},
                    "1": {"status": "approved"},
                }
            },
        )
        self.loop.run_until_complete(self.store.add_job(job))
        with patch.object(self.service, "_automation_modules_after", return_value=[{"enabled": True, "type": "erp"}]), patch.object(
            self.service, "_run_automation_post_modules", new_callable=AsyncMock, return_value={"erp": {"sent": 1}}
        ) as resume:
            self.loop.run_until_complete(self.service._resume_automation_after_approval(job.id, "approval"))

        received = resume.call_args.args[2]
        self.assertEqual(["rejected.jpg", "approved.jpg"], [item.media_name for item in received])

    def test_imported_telegram_module_is_removed_before_automation_runs(self) -> None:
        request = CreateJobRequest(
            type="image",
            erp_enabled=True,
            automation_graph={
                "modules": [
                    {"id": "flow", "type": "flow"},
                    {"id": "legacy-telegram", "type": "telegram"},
                    {"id": "approval", "type": "approval"},
                    {"id": "erp", "type": "erp"},
                ],
                "edges": [
                    {"source": "flow", "target": "legacy-telegram"},
                    {"source": "legacy-telegram", "target": "approval"},
                    {"source": "approval", "target": "erp"},
                ],
            },
        )

        graph = self.service._automation_graph_payload(request)

        self.assertNotIn("telegram", [item["type"] for item in graph["modules"]])
        module_ids = {item["id"] for item in graph["modules"]}
        self.assertTrue(all(edge["source"] in module_ids and edge["target"] in module_ids for edge in graph["edges"]))
        approval = next(item for item in graph["modules"] if item["type"] == "approval")
        self.assertEqual("dashboard", approval["settings"]["approvalMode"])

    def test_dashboard_approval_resumes_erp_only_after_final_decision(self) -> None:
        request = CreateJobRequest(type="image", erp_enabled=True, erp_project_id="PROJ-0049")
        artifact = JobArtifact(media_name="approved.jpg", url="https://media.example/approved.jpg")
        job = JobRecord(
            type="image",
            input=request.model_dump() if hasattr(request, "model_dump") else request.dict(),
            artifacts=[artifact],
            result={
                "automation_execution": {
                    "nodes": [
                        {"id": "approval", "type": "approval", "status": "running", "output": {}},
                        {"id": "erp", "type": "erp", "status": "pending", "output": {}},
                    ]
                }
            },
        )
        self.loop.run_until_complete(self.store.add_job(job))
        with patch.object(
            self.service,
            "_run_automation_post_modules",
            new_callable=AsyncMock,
            return_value={"erp": {"sent": 1}},
        ) as resume:
            approval = self.loop.run_until_complete(
                self.service.apply_dashboard_approval(job.id, 0, "approved")
            )

        self.assertEqual("approved", approval["status"])
        resume.assert_awaited_once()
        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertEqual("approved", saved.result["dashboard_approvals"]["0"]["status"])
        self.assertEqual(0, saved.result["dashboard_approval_summary"]["pending"])

    def test_dashboard_can_add_public_image_to_open_idea_review(self) -> None:
        source = JobArtifact(media_name="flow-output.jpg", url="https://media.example/flow-output.jpg")
        job = JobRecord(
            type="image",
            artifacts=[source],
            result={
                "automation_execution": {
                    "nodes": [
                        {"id": "approval", "type": "approval", "status": "running", "output": {}},
                        {"id": "erp", "type": "erp", "status": "pending", "output": {}},
                    ]
                }
            },
        )
        self.loop.run_until_complete(self.store.add_job(job))

        added = self.loop.run_until_complete(
            self.service.add_dashboard_artifact(
                job.id,
                "https://media.example/revised-idea.png",
                "Ảnh chị Phương sửa",
                "Hồ Thanh Phong",
            )
        )

        self.assertEqual("Ảnh chị Phương sửa", added["label"])
        saved = self.store.get_job(job.id)
        self.assertIsNotNone(saved)
        self.assertEqual(2, len(saved.artifacts))
        self.assertEqual("https://media.example/revised-idea.png", saved.artifacts[1].public_url)
        self.assertEqual(2, saved.result["dashboard_approval_summary"]["pending"])
        approval_node = saved.result["automation_execution"]["nodes"][0]
        self.assertEqual("running", approval_node["status"])

    def test_dashboard_rejects_unsafe_or_closed_idea_additions(self) -> None:
        job = JobRecord(
            type="image",
            artifacts=[JobArtifact(media_name="flow-output.jpg", url="https://media.example/flow-output.jpg")],
            result={
                "automation_execution": {
                    "nodes": [{"id": "approval", "type": "approval", "status": "running", "output": {}}]
                }
            },
        )
        self.loop.run_until_complete(self.store.add_job(job))

        with self.assertRaises(HTTPException) as invalid_url:
            self.loop.run_until_complete(self.service.add_dashboard_artifact(job.id, "http://media.example/nope.jpg"))
        self.assertEqual(400, invalid_url.exception.status_code)

        saved = self.store.get_job(job.id)
        saved.result["automation_execution"]["nodes"][0]["status"] = "completed"
        self.loop.run_until_complete(self.store.patch_job(job.id, result=saved.result))
        with self.assertRaises(HTTPException) as completed_review:
            self.loop.run_until_complete(self.service.add_dashboard_artifact(job.id, "https://media.example/late.jpg"))
        self.assertEqual(409, completed_review.exception.status_code)


class HvgErpIdeaFanOutTests(_ErpServiceTestCase):
    """The "Phân rã công việc" flow: one child card = one idea = one job."""

    PARENT = "TASK-2026-00202"
    CHILD_A = "TASK-2026-00615"
    CHILD_B = "TASK-2026-00616"

    def _details(
        self,
        *,
        child_a_has_flow_images: bool = False,
        child_a_comments: list | None = None,
        child_b_comments: list | None = None,
        child_b_blank: bool = False,
        child_a_cover: str = "",
        child_b_cover: str = "",
        parent_desc: str = "<p>Tạo 85 idea cho khăn tay cô dâu thêu tay mùa christmas</p>",
        parent_subject: str = "Idea",
        parent_cover: str = "/private/files/khan-tay.jpg",
        child_subjects: tuple = ("a", "b"),
        child_a_desc: str = "<p>Khăn tay đặt cạnh cây thông</p>",
        board_name: str = "",
        board_name_in_detail: bool = True,
        parent_meta: str | None = None,
    ) -> dict:
        subject_a, subject_b = child_subjects
        # ERP đính ``project_name`` lên **từng** thẻ chứ không để riêng một
        # chỗ — chép đúng hình ấy, theo payload thật của bảng PROJ-0018.
        # ``board_name_in_detail=False`` dựng ca ``taskDetail`` không trả khoá
        # ấy: lúc đó tên bảng chỉ còn đường hỏi ``taskBoard``.
        board = {"project_name": board_name} if board_name and board_name_in_detail else {}
        return {
            self.PARENT: {
                **board,
                "name": self.PARENT,
                "subject": parent_subject,
                "status": "Working",
                "description": parent_desc,
                "cover_image": parent_cover,
                "meta": _idea_parent_meta() if parent_meta is None else parent_meta,
                "children": [
                    {"name": self.CHILD_A, "subject": subject_a},
                    {"name": self.CHILD_B, "subject": subject_b},
                ],
            },
            self.CHILD_A: {
                **board,
                "name": self.CHILD_A,
                "subject": subject_a,
                # Child cards stay in Open while the parent Idea card has
                # already been moved on to Working.
                "status": "Open",
                "description": child_a_desc,
                "cover_image": child_a_cover,
                "comments": (
                    [{"content": "[FLOW_V2_ARTIFACT] https://erp.havigroup.llc/files/flow-1.png"}]
                    if child_a_has_flow_images
                    else list(child_a_comments or [])
                ),
            },
            self.CHILD_B: {
                **board,
                "name": self.CHILD_B,
                "subject": subject_b,
                "status": "Open",
                "description": "" if child_b_blank else "<p>Khăn tay trong hộp quà</p>",
                "cover_image": child_b_cover,
                "comments": list(child_b_comments or []),
            },
        }

    def _enqueue(
        self,
        request,
        *,
        child_a_has_flow_images: bool = False,
        child_a_comments: list | None = None,
        child_b_comments: list | None = None,
        child_b_blank: bool = False,
        child_a_cover: str = "",
        child_b_cover: str = "",
        parent_desc: str = "<p>Tạo 85 idea cho khăn tay cô dâu thêu tay mùa christmas</p>",
        parent_subject: str = "Idea",
        parent_cover: str = "/private/files/khan-tay.jpg",
        child_subjects: tuple = ("a", "b"),
        child_a_desc: str = "<p>Khăn tay đặt cạnh cây thông</p>",
        board_name: str = "",
        board_name_in_detail: bool = True,
        parent_meta: str | None = None,
    ) -> dict:
        details = self._details(
            child_a_has_flow_images=child_a_has_flow_images,
            child_a_comments=child_a_comments,
            child_b_comments=child_b_comments,
            child_b_blank=child_b_blank,
            child_a_cover=child_a_cover,
            child_b_cover=child_b_cover,
            parent_desc=parent_desc,
            parent_subject=parent_subject,
            parent_cover=parent_cover,
            child_subjects=child_subjects,
            child_a_desc=child_a_desc,
            board_name=board_name,
            board_name_in_detail=board_name_in_detail,
            parent_meta=parent_meta,
        )
        # ``taskBoard`` trả ``project_name`` trên từng thẻ — đúng hình payload
        # thật.  Không nêu tên bảng thì bảng cũng không có tên.
        board_payload = {
            "columns": [
                {
                    "status": "Working",
                    "tasks": [
                        dict({"project_name": board_name} if board_name else {}, name=self.PARENT)
                    ],
                }
            ]
        }
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(api_key="test-key", api_secret="test-secret", project_id="PROJ-0013")
            )
        )
        def _update_meta(_key, _token, task_id, meta, *, project=""):
            details[task_id]["meta"] = meta
            return {"name": task_id, "meta": meta}

        with patch.object(
            self.service, "_erp_task_project_id", return_value="PROJ-0013"
        ), patch.object(
            self.service, "_erp_task_detail", side_effect=lambda _key, _token, task_id: details[task_id]
        ), patch.object(
            self.service, "_erp_task_attachment_files", return_value=[]
        ), patch.object(
            self.service, "_erp_task_board", return_value=board_payload
        ), patch.object(
            self.service, "_erp_update_task_meta", side_effect=_update_meta
        ), patch.object(self.service, "_run_flow_job", new_callable=AsyncMock) as run:
            response = self.loop.run_until_complete(self.service.enqueue_erp_idea_jobs(request))
            # Let the sequential runner drain so its calls are observable.
            self.loop.run_until_complete(asyncio.sleep(0))
            self.loop.run_until_complete(asyncio.sleep(0))
        self._run_flow_job = run
        return response

    def test_each_idea_card_gets_its_own_job_writing_back_to_that_card(self) -> None:
        response = self._enqueue(ERPIdeaBatchRequest(task_id=self.PARENT, count=12))

        self.assertEqual([self.CHILD_A, self.CHILD_B], [item["task_id"] for item in response["queued"]])
        self.assertEqual("PROJ-0013", response["project_id"])
        self.assertEqual(12, response["count"])
        # The idea image lives on the parent card, including as its cover.
        self.assertTrue(response["source_attachment_id"].endswith("khan-tay.jpg"))

        jobs = [self.store.get_job(item["job_id"]) for item in response["queued"]]
        for job, child_id in zip(jobs, [self.CHILD_A, self.CHILD_B]):
            self.assertIsNotNone(job)
            self.assertEqual(child_id, job.input["erp_output_task_id"])
            self.assertEqual(self.PARENT, job.input["erp_source_task_id"])
            self.assertEqual("PROJ-0013", job.input["erp_project_id"])
            self.assertEqual(12, job.input["count"])
        self.assertIn("Khăn tay đặt cạnh cây thông", jobs[0].input["prompt"])
        self.assertIn("Khăn tay trong hộp quà", jobs[1].input["prompt"])
        self.assertNotIn("<p>", jobs[0].input["prompt"])

    def test_ideas_that_already_carry_flow_images_are_skipped_unless_asked_for(self) -> None:
        response = self._enqueue(ERPIdeaBatchRequest(task_id=self.PARENT), child_a_has_flow_images=True)
        self.assertEqual([self.CHILD_B], [item["task_id"] for item in response["queued"]])
        self.assertEqual([self.CHILD_A], [item["task_id"] for item in response["skipped"]])

        rerun = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT, include_done=True), child_a_has_flow_images=True
        )
        self.assertEqual([self.CHILD_A, self.CHILD_B], [item["task_id"] for item in rerun["queued"]])

    def test_an_idea_whose_images_are_still_awaiting_a_decision_is_not_run_again(self) -> None:
        # The card carries a full set of images nobody has answered yet. Only
        # counting the approved output would put a second set on top of them.
        pending = [{"content": "[FLOW_V2_REVIEW job-1#0] Ảnh 1/12 chờ duyệt"}]

        response = self._enqueue(ERPIdeaBatchRequest(task_id=self.PARENT), child_b_comments=pending)

        self.assertEqual([self.CHILD_A], [item["task_id"] for item in response["queued"]])
        self.assertEqual(
            [{"task_id": self.CHILD_B, "subject": "b", "reason": "đang có ảnh chờ duyệt trên thẻ"}],
            response["skipped"],
        )

    def test_an_image_only_comment_still_says_the_card_has_been_run(self) -> None:
        # New comments put nothing on the card but the picture: the markers the
        # gate reads now travel in the comment's ``meta``. Missing them would
        # hand the card a second set of images on top of the first.
        done = [{"content": "\u200b", "meta": "[FLOW_V2_ARTIFACT] flow-1.png"}]
        pending = [{"content": "\u200b", "meta": "[FLOW_V2_REVIEW job-1#0]"}]

        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT), child_a_comments=done, child_b_comments=pending
        )

        self.assertEqual([], response["queued"])
        self.assertEqual(
            [
                {"task_id": self.CHILD_A, "subject": "a", "reason": "đã có ảnh Flow"},
                {"task_id": self.CHILD_B, "subject": "b", "reason": "đang có ảnh chờ duyệt trên thẻ"},
            ],
            response["skipped"],
        )

    def test_an_idea_card_uses_its_own_picture_as_the_source(self) -> None:
        # On this board the idea is a picture: each child card's cover shows
        # the embroidery to make content for. Falling back to the parent's
        # image would ask every card the same question.
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT), child_a_cover="/private/files/tho-noel.jpg"
        )

        first, second = (self.store.get_job(item["job_id"]) for item in response["queued"])
        self.assertTrue(first.input["erp_source_attachment_ids"][0].endswith("tho-noel.jpg"))
        self.assertEqual(self.CHILD_A, first.input["erp_source_task_id"])
        self.assertEqual(self.CHILD_A, first.input["erp_output_task_id"])
        self.assertIn("ảnh idea của chính thẻ này", first.input["prompt"])
        # The card with no picture of its own still borrows the parent's.
        self.assertTrue(second.input["erp_source_attachment_ids"][0].endswith("khan-tay.jpg"))
        self.assertEqual(self.PARENT, second.input["erp_source_task_id"])

    def test_the_source_column_follows_the_card_the_image_comes_from(self) -> None:
        # ERP Source refuses to read a card outside the column it was given.
        # Handing it the parent's column killed every job with "Card ERP đã
        # chọn không nằm trong cột Open" once the source became the child card.
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT), child_a_cover="/private/files/tho-noel.jpg"
        )

        first, second = (self.store.get_job(item["job_id"]) for item in response["queued"])
        self.assertEqual("Open", first.input["erp_status_id"])
        self.assertEqual("Open", first.input["automation_graph"]["modules"][0]["settings"]["erpStatus"])
        # The card without a picture reads the parent's, so the parent's column.
        self.assertEqual("Working", second.input["erp_status_id"])
        self.assertEqual("Working", second.input["automation_graph"]["modules"][0]["settings"]["erpStatus"])

    def test_two_idea_cards_are_in_flight_at_the_same_time(self) -> None:
        # Running the cards one behind the other left the browser idle through
        # the whole watermark/upload tail of the card in front of it.
        details = self._details()
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(api_key="test-key", api_secret="test-secret", project_id="PROJ-0013")
            )
        )
        in_flight = 0
        peak = 0

        async def _run(_job_id: str, _request) -> None:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0)
            in_flight -= 1

        def _update_meta(_key, _token, task_id, meta, *, project=""):
            details[task_id]["meta"] = meta
            return {"name": task_id, "meta": meta}

        with patch.object(
            self.service, "_erp_task_project_id", return_value="PROJ-0013"
        ), patch.object(
            self.service, "_erp_task_detail", side_effect=lambda _key, _token, task_id: details[task_id]
        ), patch.object(
            self.service, "_erp_task_attachment_files", return_value=[]
        ), patch.object(
            self.service, "_erp_update_task_meta", side_effect=_update_meta
        ), patch.object(self.service, "_run_flow_job", new=_run):
            self.loop.run_until_complete(
                self.service.enqueue_erp_idea_jobs(ERPIdeaBatchRequest(task_id=self.PARENT))
            )
            for _ in range(10):
                self.loop.run_until_complete(asyncio.sleep(0))

        self.assertEqual(2, peak)

    def test_a_card_whose_idea_is_only_a_picture_is_still_run(self) -> None:
        # Title "b" and no description, but the cover carries the idea.
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT),
            child_b_blank=True,
            child_b_cover="/private/files/xe-tai-thong.jpg",
        )

        self.assertEqual([self.CHILD_A, self.CHILD_B], [item["task_id"] for item in response["queued"]])

    def test_an_idea_card_with_no_idea_text_is_not_run(self) -> None:
        # A card titled "b" with an empty description gives the same prompt as
        # every other empty card, so the run would just repeat one image.
        response = self._enqueue(ERPIdeaBatchRequest(task_id=self.PARENT), child_b_blank=True)

        self.assertEqual([self.CHILD_A], [item["task_id"] for item in response["queued"]])
        self.assertEqual(
            [
                {
                    "task_id": self.CHILD_B,
                    "subject": "b",
                    "reason": "thẻ con chưa có nội dung idea (tiêu đề/mô tả trống)",
                }
            ],
            response["skipped"],
        )

        forced = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT, include_done=True), child_b_blank=True
        )
        self.assertEqual([self.CHILD_A, self.CHILD_B], [item["task_id"] for item in forced["queued"]])

    def test_an_idea_this_app_already_ran_is_not_run_again(self) -> None:
        # The first run may still be generating, so the card itself is empty:
        # the job that targets it is the only record that it was started.
        self.loop.run_until_complete(
            self.store.add_job(
                JobRecord(type="image", status="running", input={"erp_output_task_id": self.CHILD_B})
            )
        )

        response = self._enqueue(ERPIdeaBatchRequest(task_id=self.PARENT))

        self.assertEqual([self.CHILD_A], [item["task_id"] for item in response["queued"]])
        self.assertEqual("đã có lượt chạy trong app", response["skipped"][0]["reason"])

    def test_a_run_that_failed_leaves_the_idea_free_to_run_again(self) -> None:
        self.loop.run_until_complete(
            self.store.add_job(
                JobRecord(type="image", status="failed", input={"erp_output_task_id": self.CHILD_B})
            )
        )

        response = self._enqueue(ERPIdeaBatchRequest(task_id=self.PARENT))

        self.assertEqual([self.CHILD_A, self.CHILD_B], [item["task_id"] for item in response["queued"]])

    def test_a_run_the_app_never_finished_leaves_the_idea_free_to_run_again(self) -> None:
        # "interrupted" is stamped on a job that was still running when the app
        # went down. Nothing resumes it, so treating it as a live run fenced the
        # idea card off for good and the card stayed empty forever.
        self.loop.run_until_complete(
            self.store.add_job(
                JobRecord(type="image", status="interrupted", input={"erp_output_task_id": self.CHILD_B})
            )
        )

        response = self._enqueue(ERPIdeaBatchRequest(task_id=self.PARENT))

        self.assertEqual([self.CHILD_A, self.CHILD_B], [item["task_id"] for item in response["queued"]])
        self.assertEqual([], response["skipped"])

    def test_an_idea_job_carries_the_havi_shot_rule_of_its_product(self) -> None:
        # Bot chạy cùng bộ rule với tool tay. Trước đây đường idea chỉ gửi bốn
        # dòng prompt, không đọc PRODUCT_SHOT_RULES, nên mọi ảnh bot tự chạy
        # đều ra ngoài rule.
        response = self._enqueue(ERPIdeaBatchRequest(task_id=self.PARENT))

        entry = response["queued"][0]
        self.assertEqual("bride_handkerchief", entry["product_rule_key"])
        prompt = self.store.get_job(entry["job_id"]).input["prompt"]
        rule = PRODUCT_SHOT_RULES["bride_handkerchief"]
        self.assertIn("HAVI product shot rule lock", prompt)
        self.assertIn(str(rule["lock"]).strip(), prompt)
        self.assertIn("Required shot plan", prompt)
        self.assertIn("Bride Handkerchief image 1", prompt)
        # Ý tưởng của thẻ con vẫn còn nguyên bên cạnh rule.
        self.assertIn("Khăn tay đặt cạnh cây thông", prompt)

    def test_the_idea_may_change_the_scene_but_not_the_product(self) -> None:
        response = self._enqueue(ERPIdeaBatchRequest(task_id=self.PARENT))

        prompt = self.store.get_job(response["queued"][0]["job_id"]).input["prompt"]
        self.assertIn(
            "Ý tưởng của thẻ chỉ quyết định bối cảnh và cách bày",
            prompt,
        )

    def test_the_number_of_images_follows_the_product_rule(self) -> None:
        # Rule của HAVI_Shot_Types_All_Products định số ảnh: halloween_bag là
        # 12 theo rule đồng bộ từ 3 worker Trello (09/09/2026: mọi sản phẩm tối đa 12 ảnh).
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT),
            parent_desc="<p>Tạo 85 idea cho halloween bag thêu tay</p>",
            parent_meta=_idea_parent_meta("Halloween bag"),
        )

        self.assertEqual([self.CHILD_A, self.CHILD_B], [item["task_id"] for item in response["queued"]])
        self.assertEqual(12, PRODUCT_SHOT_RULES["halloween_bag"]["target_count"])
        for item in response["queued"]:
            self.assertEqual("halloween_bag", item["product_rule_key"])
            self.assertEqual(12, self.store.get_job(item["job_id"]).input["count"])

    def test_a_pinned_count_still_wins_over_the_rule(self) -> None:
        # Nút trên dashboard vẫn chốt được số ảnh; rule chỉ điền khi không ai chốt.
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT, count=6),
            parent_desc="<p>Tạo 85 idea cho halloween bag thêu tay</p>",
            parent_meta=_idea_parent_meta("Halloween bag"),
        )

        self.assertEqual([self.CHILD_A, self.CHILD_B], [item["task_id"] for item in response["queued"]])
        for item in response["queued"]:
            self.assertEqual(6, self.store.get_job(item["job_id"]).input["count"])

    def test_an_idea_whose_product_is_not_recognised_is_not_run(self) -> None:
        # Không nhận ra sản phẩm thì không có rule để theo, mà ảnh sai rule
        # phải xoá tay trên ERP. Thà đứng im và nói lý do.  ``product_type``
        # là khoá bắt buộc, nên ở đây nó có mặt nhưng không gọi tên hàng nào.
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT),
            parent_desc="<p>Tạo 85 idea cho đồ thêu tay mùa christmas</p>",
            parent_meta=_idea_parent_meta("Đồ thêu tay"),
        )

        self.assertEqual([], response["queued"])
        self.assertEqual(
            [self.CHILD_A, self.CHILD_B], [item["task_id"] for item in response["skipped"]]
        )
        self.assertEqual(
            ["missing_product_rule", "missing_product_rule"],
            [item["skip_code"] for item in response["skipped"]],
        )
        self.assertIn("chưa nhận ra sản phẩm", response["skipped"][0]["reason"])

    def test_the_way_out_it_offers_is_one_that_actually_works(self) -> None:
        """Câu chỉ đường không được bảo người ta làm cái không ăn thua.

        Dán tên sản phẩm vào **mô tả** thẻ cha thì chữ ấy rơi chung rổ với tên
        file ảnh, mà bảng ưu tiên có thể cho tên file thắng — người vận hành
        làm đúng lời dặn xong vẫn chạy sai rule, và không hiểu vì sao.  Hai
        chỗ chắc chắn được đọc trước rổ chữ là **tên bảng** và **tiêu đề** thẻ
        cha; câu chỉ đường phải nêu cả hai, vì tên bảng đặt một lần là xong cả
        bảng còn tiêu đề thì phải nhớ làm mỗi lần mở thẻ mới.
        """
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT),
            parent_desc="<p>Tạo 85 idea cho đồ thêu tay mùa christmas</p>",
            parent_meta=_idea_parent_meta("Đồ thêu tay"),
        )

        reason = response["skipped"][0]["reason"]
        self.assertIn("tiêu đề thẻ cha", reason)
        self.assertIn("tên bảng", reason)
        self.assertNotIn("mô tả", reason)

    def test_the_rule_gate_can_be_turned_off_by_hand(self) -> None:
        # Đường lùi khi cần chữa cháy: chạy lại như trước, không cần deploy.
        with patch.dict(os.environ, {"ERP_IDEA_REQUIRE_PRODUCT_RULE": "0"}):
            response = self._enqueue(
                ERPIdeaBatchRequest(task_id=self.PARENT),
                parent_desc="<p>Tạo 85 idea cho đồ thêu tay mùa christmas</p>",
                parent_meta=_idea_parent_meta("Đồ thêu tay"),
            )

        self.assertEqual([self.CHILD_A, self.CHILD_B], [item["task_id"] for item in response["queued"]])
        self.assertEqual([], response["skipped"])

    def test_the_rule_is_read_off_the_source_image_when_gemini_is_configured(self) -> None:
        # Thẻ không ghi tên sản phẩm, nhưng ảnh nguồn thì có: đúng chỗ Gemini
        # phân loại hộ, y như đường tool tay.
        with patch.object(self.service, "_gemini_api_key", return_value="test-gemini"), patch.object(
            self.service, "_erp_download_attachment_bytes", return_value=(b"anh", "image/jpeg")
        ), patch.object(
            self.service,
            "_gemini_classify_erp_source_product_rule",
            return_value={"product_rule_key": "wedding_hoop", "confidence": 0.9, "visible_product": "wedding hoop"},
        ) as classify:
            response = self._enqueue(
                ERPIdeaBatchRequest(task_id=self.PARENT),
                parent_desc="<p>Tạo 85 idea cho đồ thêu tay mùa christmas</p>",
                parent_meta=_idea_parent_meta("Đồ thêu tay"),
            )

        self.assertTrue(classify.called)
        self.assertEqual(
            ["wedding_hoop", "wedding_hoop"], [item["product_rule_key"] for item in response["queued"]]
        )

    def test_a_vietnamese_ornament_board_gets_its_rule_without_gemini(self) -> None:
        # Bảng thật PROJ-0018 tên "XMAS Ornament Thêu Tròn", và máy chạy bot
        # chưa có khoá Gemini — chữ trên thẻ là đường nhận sản phẩm duy nhất
        # còn lại.
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT),
            parent_desc="<p>XMAS Ornament Thêu Tròn</p>",
            parent_meta=_idea_parent_meta("XMAS Ornament Thêu Tròn"),
        )

        self.assertEqual(
            [self.CHILD_A, self.CHILD_B], [item["task_id"] for item in response["queued"]]
        )
        for item in response["queued"]:
            self.assertEqual("ornament_round", item["product_rule_key"])
            self.assertEqual(12, self.store.get_job(item["job_id"]).input["count"])

    def test_a_parent_that_names_the_product_beats_the_source_file_name(self) -> None:
        # Hình thẻ thật của PROJ-0018: thẻ con tên "Idea 1", "Idea 2" — dài hơn
        # hai ký tự nên trượt đường mượn tên thẻ cha, mà tự nó không nói gì về
        # sản phẩm.  Ảnh nguồn thì tên ``..._hoop_ornament_...``, khớp
        # ``wedding_hoop`` đứng trước ``ornament_round`` trong bảng ưu tiên.
        # Kết quả cũ: bot chạy, nhưng chạy 12 ảnh sai bộ shot.
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT),
            parent_subject="Idea XMAS Ornament Thêu Tròn",
            parent_desc="",
            parent_cover="/private/files/Embroidered_church_on_hoop_ornament_202607161015.jpeg",
            child_subjects=("Idea 1", "Idea 2"),
            parent_meta=_idea_parent_meta("XMAS Ornament Thêu Tròn"),
        )

        self.assertEqual(
            [self.CHILD_A, self.CHILD_B], [item["task_id"] for item in response["queued"]]
        )
        for item in response["queued"]:
            self.assertEqual("ornament_round", item["product_rule_key"])
            self.assertEqual(12, self.store.get_job(item["job_id"]).input["count"])

    def test_a_child_renamed_after_its_sku_still_reads_the_product_off_its_parent(self) -> None:
        """Đánh số xong, thẻ con tên là ``OR_18_007`` — cái tên ấy không nói gì.

        Thẻ con có ảnh idea riêng thì chính nó là thẻ nguồn, nên tên nó là chỗ
        bộ nhận diện đọc trước tiên.  Một dãy mã thì không phải tên sản phẩm;
        đọc nó như tên sẽ chặn mất đường mượn tên thẻ cha, và cái tên file
        ``..._hoop_ornament_...`` lại thắng như cũ — 12 ảnh ``wedding_hoop``
        thay vì 14 ảnh ``ornament_round``.  Hai tính năng tự chúng đều đúng,
        chỉ đứng cạnh nhau mới hỏng.
        """
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT),
            parent_subject="Idea XMAS Ornament Thêu Tròn",
            parent_desc="",
            child_subjects=("OR_18_007", "OR_18_008"),
            child_a_cover="/private/files/Embroidered_church_on_hoop_ornament_202607161015.jpeg",
            child_a_desc="",
            parent_meta=_idea_parent_meta("XMAS Ornament Thêu Tròn"),
        )

        queued = {item["task_id"]: item for item in response["queued"]}
        self.assertIn(self.CHILD_A, queued)
        self.assertEqual("ornament_round", queued[self.CHILD_A]["product_rule_key"])
        self.assertEqual(
            12, self.store.get_job(queued[self.CHILD_A]["job_id"]).input["count"]
        )

    def test_the_board_name_alone_is_enough_to_read_the_product(self) -> None:
        """Bảng đã tên đúng sản phẩm rồi thì không phải sửa tên thẻ nào cả.

        Đây là hình thẻ **thật** của PROJ-0018 hôm nay: bảng tên *XMAS Ornament
        Thêu Tròn*, thẻ cha tên trống trơn là ``Idea``, thẻ con tên ``Idea 1``
        và có ảnh idea riêng mang chữ ``hoop`` trong tên file.

        ERP trả ``project_name`` ngay trong payload của từng thẻ, nên tên bảng
        là thứ đang nằm sẵn trong tay — không tốn thêm request nào để lấy.  Bỏ
        qua nó là bắt người vận hành đi sửa tên thẻ cha cho mỗi bảng mới, chỉ
        để nói lại một điều bảng đã nói rồi.

        Tên thẻ vẫn đọc trước: bảng nói chung cả bảng, thẻ nói riêng thẻ ấy.
        """
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT),
            parent_subject="Idea",
            parent_desc="",
            board_name="XMAS Ornament Thêu Tròn",
            child_subjects=("Idea 1", "Idea 2"),
            child_a_cover="/private/files/Embroidered_church_on_hoop_ornament_202607161015.jpeg",
            child_a_desc="",
            parent_meta=_idea_parent_meta("XMAS Ornament Thêu Tròn"),
        )

        queued = {item["task_id"]: item for item in response["queued"]}
        self.assertIn(self.CHILD_A, queued)
        self.assertEqual("ornament_round", queued[self.CHILD_A]["product_rule_key"])
        self.assertEqual(
            12, self.store.get_job(queued[self.CHILD_A]["job_id"]).input["count"]
        )

    def test_the_handkerchief_board_reads_its_product_without_gemini(self) -> None:
        """Bảng thật thứ hai của xưởng: ``XMAS Khăn Tay Thêu Tay`` (PROJ-0013).

        Bảng này 38 thẻ và không khai ``product:`` ở đâu cả — y hệt PROJ-0018,
        tên bảng là tất cả những gì có.  Trước đây nó tra ra rỗng, nên với
        ``ERP_IDEA_REQUIRE_PRODUCT_RULE`` bật sẵn thì **cả bảng bị bỏ qua**
        với lý do ``missing_product_rule``, và người vận hành không có cách
        nào chạy nó ngoài việc cắm khoá Gemini.

        Bảng luật đã tự khai ``embroidered handkerchief`` là một cách gọi của
        rule này; chỗ thiếu chỉ là cách gọi ấy bằng tiếng Việt.
        """
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT),
            parent_subject="Idea",
            parent_desc="",
            board_name="XMAS Khăn Tay Thêu Tay",
            child_subjects=("Idea 1", "Idea 2"),
            child_a_cover="/private/files/khan-tay-theu-tay-202607161015.jpeg",
            child_a_desc="",
        )

        queued = {item["task_id"]: item for item in response["queued"]}
        self.assertIn(self.CHILD_A, queued)
        self.assertEqual("bride_handkerchief", queued[self.CHILD_A]["product_rule_key"])

    def test_three_words_picked_up_from_three_places_are_not_a_product_name(self) -> None:
        """Cụm ``khăn tay thêu`` chỉ tính khi nó đứng liền một chỗ.

        Rổ chữ của đường soi ảnh gom cả tên thẻ, **tên file ảnh** và mô tả vào
        chung một chuỗi.  Nhặt rời từng chữ thì ``khan-tay.jpg`` cộng chữ
        ``thêu`` rơi tận mô tả cũng đủ ba chữ — tên file thắng cả tên bảng, mà
        runbook dặn đúng chuyện phải tránh: bảng ornament chạy ra rule khăn
        tay, ảnh sai rule thì phải xoá tay trên ERP.
        """
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT),
            parent_subject="Idea",
            parent_desc="<p>Tạo 85 idea cho đồ thêu tay mùa christmas</p>",
            board_name="XMAS Ornament Thêu Tròn",
            child_a_cover="/private/files/khan-tay.jpg",
            parent_meta=_idea_parent_meta("XMAS Ornament Thêu Tròn"),
        )

        self.assertEqual([self.CHILD_A, self.CHILD_B], [item["task_id"] for item in response["queued"]])
        for item in response["queued"]:
            self.assertEqual("ornament_round", item["product_rule_key"])

    def test_the_board_name_still_arrives_when_the_card_payload_omits_it(self) -> None:
        """``taskDetail`` không trả ``project_name`` thì hỏi thẳng ``taskBoard``.

        ``taskBoard`` chắc chắn có khoá ấy — payload thật của PROJ-0018 mang
        nó trên từng thẻ.  Hỏi đúng **một** lần cho cả lượt, vì tên bảng không
        đổi giữa các thẻ con; hỏi mỗi thẻ một lần là 85 request cho một thứ
        không đổi.
        """
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT),
            parent_subject="Idea",
            parent_desc="",
            board_name="XMAS Ornament Thêu Tròn",
            board_name_in_detail=False,
            child_subjects=("Idea 1", "Idea 2"),
            child_a_cover="/private/files/Embroidered_church_on_hoop_ornament_202607161015.jpeg",
            child_a_desc="",
            parent_meta=_idea_parent_meta("XMAS Ornament Thêu Tròn"),
        )

        queued = {item["task_id"]: item for item in response["queued"]}
        self.assertEqual("ornament_round", queued[self.CHILD_A]["product_rule_key"])
        self.assertEqual(
            12, self.store.get_job(queued[self.CHILD_A]["job_id"]).input["count"]
        )

    def test_a_child_named_idea_9_with_its_own_picture_still_reads_the_parent(self) -> None:
        """Đúng hình thẻ thật của PROJ-0018, **trước** khi đánh số.

        Chép từ bảng thật: thẻ con tên ``Idea 9``, có ảnh idea riêng tên
        ``Wooden_embroidery_hoop_ornament_...``.  Có ảnh riêng thì chính thẻ
        con là thẻ nguồn, nên tên nó là chỗ đọc trước — mà ``Idea 9`` không nói
        ra hàng gì, y hệt ``OR_18_007``.  Chữ ``hoop`` trong tên file lại khớp
        ``wedding_hoop``, đứng thứ 9 trong bảng ưu tiên còn ``ornament_round``
        thứ 26.

        Tên file ở đây là ảnh **có thật** của bảng ấy — hôm nay nó nằm trên thẻ
        cha, nhưng mỗi ảnh thả thêm lên thẻ cha lại tự thành một thẻ con mới,
        nên nó nằm trên thẻ con là chuyện của ngày mai chứ không phải chuyện
        bịa.  Ba thẻ con khác cũng có ``hoop`` trong tên file của chính nó; ba
        cái đó tình cờ vẫn ra đúng rule, cái này thì không.
        """
        response = self._enqueue(
            ERPIdeaBatchRequest(task_id=self.PARENT),
            parent_subject="Idea XMAS Ornament Thêu Tròn",
            parent_desc="",
            child_subjects=("Idea 9", "Idea 10"),
            child_a_cover="/private/files/Embroidered_church_on_hoop_ornament_202607161015.jpeg",
            child_a_desc="",
            parent_meta=_idea_parent_meta("XMAS Ornament Thêu Tròn"),
        )

        queued = {item["task_id"]: item for item in response["queued"]}
        self.assertIn(self.CHILD_A, queued)
        self.assertEqual("ornament_round", queued[self.CHILD_A]["product_rule_key"])
        self.assertEqual(
            12, self.store.get_job(queued[self.CHILD_A]["job_id"]).input["count"]
        )

    def test_the_watcher_runs_the_children_of_the_configured_idea_card(self) -> None:
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(
                    api_key="test-key",
                    api_secret="test-secret",
                    project_id="PROJ-0013",
                    task_id=self.PARENT,
                )
            )
        )
        details = self._details(child_a_has_flow_images=True)

        def _update_meta(_key, _token, task_id, meta, *, project=""):
            details[task_id]["meta"] = meta
            return {"name": task_id, "meta": meta}

        with patch.object(
            self.service, "_erp_task_project_id", return_value="PROJ-0013"
        ), patch.object(
            self.service, "_erp_task_detail", side_effect=lambda _key, _token, task_id: details[task_id]
        ), patch.object(
            self.service, "_erp_update_task_meta", side_effect=_update_meta
        ), patch.object(self.service, "_run_flow_job", new_callable=AsyncMock):
            response = self.loop.run_until_complete(self.service.autorun_erp_idea_children())
            self.loop.run_until_complete(asyncio.sleep(0))

        # Only the idea that has no images yet - nobody had to press anything.
        self.assertEqual([self.CHILD_B], [item["task_id"] for item in response["queued"]])

    def test_the_watcher_does_nothing_until_an_idea_card_is_configured(self) -> None:
        with patch.object(self.service, "_erp_task_detail") as detail:
            response = self.loop.run_until_complete(self.service.autorun_erp_idea_children())

        detail.assert_not_called()
        self.assertEqual([], response["queued"])
        self.assertIn("chưa cấu hình", response["reason"])

    def test_the_watcher_waits_for_the_run_in_flight(self) -> None:
        # One browser, one Flow session: a second fan-out on top of a running
        # one would fight it for the same window.
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(
                    api_key="test-key",
                    api_secret="test-secret",
                    project_id="PROJ-0013",
                    task_id=self.PARENT,
                )
            )
        )
        self.service._tasks["busy"] = _StillRunning()

        with patch.object(self.service, "_erp_task_detail") as detail:
            response = self.loop.run_until_complete(self.service.autorun_erp_idea_children())

        detail.assert_not_called()
        self.assertEqual("đang có lượt chạy", response["reason"])

    def test_the_watcher_holds_off_while_every_flow_profile_is_out_of_quota(self) -> None:
        # Mỗi vòng watcher vẫn xếp job cho từng thẻ con dù biết chắc lượt nào
        # cũng chết ở bước mở Flow, và job hỏng thì đẩy lịch sử thật ra khỏi
        # dashboard: sáng 19/08 sáu thẻ đã lấp trọn 50 chỗ trong ba phút một
        # vòng. Vá vẫn chạy vì đăng bù ảnh có sẵn không cần Flow.
        # Đổi 11/09 theo quy trình seller: khoá quota thì watcher vẫn đi qua
        # enqueue (chốt thuộc tính, tách thẻ con), chỉ truyền lý do để giữ job.
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(
                    api_key="test-key",
                    api_secret="test-secret",
                    project_id="PROJ-0013",
                    task_id=self.PARENT,
                )
            )
        )
        profile = FlowBrowserProfile(index=0, label="Flow profile 1", path=Path(self.tempdir.name) / "profile")
        self.service._flow_profile_quota_blocked_until = {profile.key: time.time() + 3600}

        async def _held(request, *, hold_jobs_reason=""):
            return {"parent_task_id": request.task_id, "created": [], "queued": [], "reason": hold_jobs_reason}

        with patch.object(self.service, "_flow_profile_specs", return_value=[profile]), patch.object(
            self.service, "repair_erp_idea_children", new_callable=AsyncMock, return_value={"republished": []}
        ) as repair, patch.object(self.service, "enqueue_erp_idea_jobs", side_effect=_held) as enqueue:
            response = self.loop.run_until_complete(self.service.autorun_erp_idea_children())

        enqueue.assert_awaited_once()
        self.assertEqual(self.PARENT, enqueue.await_args.args[0].task_id)
        self.assertIn("quota", enqueue.await_args.kwargs["hold_jobs_reason"])
        repair.assert_awaited_once()
        self.assertEqual([], response["queued"])
        self.assertIn("hết quota Agent", response["reason"])

    def test_the_agent_bot_holds_off_while_every_flow_profile_is_out_of_quota(self) -> None:
        # Đổi 11/09 theo quy trình seller: khoá quota thì bot vẫn đi qua
        # ``enqueue_erp_idea_jobs`` để chốt thuộc tính và tách thẻ con, chỉ
        # giữ lại bước xếp job bằng ``hold_jobs_reason``. Trước đây bài này
        # khẳng định "không gọi" — chính là lỗi seller thả ảnh cả ngày không
        # thấy thẻ con. Phần "không xếp job" đo bằng code thật ở
        # ``tests/test_tach_khi_het_quota.py``.
        profile = FlowBrowserProfile(index=0, label="Flow profile 1", path=Path(self.tempdir.name) / "profile")
        self.service._flow_profile_quota_blocked_until = {profile.key: time.time() + 3600}

        async def _held(request, *, hold_jobs_reason=""):
            return {"parent_task_id": request.task_id, "created": [], "queued": [], "reason": hold_jobs_reason}

        with patch.object(self.service, "_flow_profile_specs", return_value=[profile]), patch.object(
            self.service, "repair_erp_idea_children", new_callable=AsyncMock, return_value={"republished": []}
        ), patch.object(self.service, "enqueue_erp_idea_jobs", side_effect=_held) as enqueue:
            response = self.loop.run_until_complete(self.service._agent_bot_autorun(self.PARENT))

        enqueue.assert_awaited_once()
        self.assertEqual(self.PARENT, enqueue.await_args.args[0].task_id)
        self.assertIn("quota", enqueue.await_args.kwargs["hold_jobs_reason"])
        self.assertEqual([], response["queued"])
        self.assertIn("hết quota Agent", response["reason"])

    def test_a_profile_still_free_keeps_the_watcher_running(self) -> None:
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(
                    api_key="test-key",
                    api_secret="test-secret",
                    project_id="PROJ-0013",
                    task_id=self.PARENT,
                )
            )
        )
        blocked = FlowBrowserProfile(index=0, label="Flow profile 1", path=Path(self.tempdir.name) / "one")
        free = FlowBrowserProfile(index=1, label="Flow profile 2", path=Path(self.tempdir.name) / "two")
        self.service._flow_profile_quota_blocked_until = {blocked.key: time.time() + 3600}

        with patch.object(self.service, "_flow_profile_specs", return_value=[blocked, free]), patch.object(
            self.service, "repair_erp_idea_children", new_callable=AsyncMock, return_value={"republished": []}
        ), patch.object(
            self.service, "enqueue_erp_idea_jobs", new_callable=AsyncMock, return_value={"queued": []}
        ) as enqueue:
            self.loop.run_until_complete(self.service.autorun_erp_idea_children())

        enqueue.assert_awaited_once()

    def test_only_the_requested_child_cards_are_run(self) -> None:
        response = self._enqueue(ERPIdeaBatchRequest(task_id=self.PARENT, child_task_ids=[self.CHILD_B]))
        self.assertEqual([self.CHILD_B], [item["task_id"] for item in response["queued"]])

    def test_idea_images_land_on_the_idea_card_outside_the_parent_reply_thread(self) -> None:
        request = CreateJobRequest(
            type="image",
            erp_enabled=True,
            erp_project_id="PROJ-0049",
            erp_task_id=self.PARENT,
            erp_source_task_id=self.PARENT,
            erp_output_task_id=self.CHILD_A,
        )
        artifact = JobArtifact(media_name="idea-a.jpg", url="https://media.example/idea-a.jpg")
        job = JobRecord(type="image", result={"dashboard_approvals": {"0": {"status": "approved"}}})
        self.loop.run_until_complete(self.store.add_job(job))

        # Gắn nhãn DONE là một lượt ghi ERP riêng (tự kiểm dự án bên trong);
        # giả nó đi để bài này chỉ đo chỗ ảnh đáp xuống.
        with patch.object(self.service, "_erp_assert_task_in_project") as assert_task, patch.object(
            self.service, "_erp_source_comment_id"
        ) as source_comment, patch.object(
            self.service,
            "_erp_attach_url",
            return_value={"id": "https://media.example/idea-a.jpg", "name": "idea-a.jpg", "url": "https://media.example/idea-a.jpg"},
        ) as attach, patch.object(self.service, "_erp_add_task_label", return_value={}) as label:
            result = self.loop.run_until_complete(self.service._archive_erp_artifacts(job.id, request, [artifact]))

        assert_task.assert_called_once_with("test-key", "test-secret", self.CHILD_A)
        source_comment.assert_not_called()
        self.assertEqual(self.CHILD_A, attach.call_args.args[2])
        label.assert_called_once_with("test-key", "test-secret", self.CHILD_A, "DONE")
        self.assertEqual(1, result["sent"])

    def test_an_idea_card_receives_nothing_until_every_image_is_decided(self) -> None:
        """The reviewer's gate guards the idea card, not just the source card."""
        request = CreateJobRequest(
            type="image",
            erp_enabled=True,
            erp_project_id="PROJ-0049",
            erp_task_id=self.PARENT,
            erp_source_task_id=self.PARENT,
            erp_output_task_id=self.CHILD_A,
        )
        artifacts = [
            JobArtifact(media_name="idea-a-1.jpg", url="https://media.example/idea-a-1.jpg"),
            JobArtifact(media_name="idea-a-2.jpg", url="https://media.example/idea-a-2.jpg"),
        ]
        job = JobRecord(type="image", result={"dashboard_approvals": {"0": {"status": "approved"}}})
        self.loop.run_until_complete(self.store.add_job(job))

        with patch.object(self.service, "_erp_assert_task_in_project") as assert_task, patch.object(
            self.service, "_erp_attach_url"
        ) as attach:
            result = self.loop.run_until_complete(self.service._archive_erp_artifacts(job.id, request, artifacts))

        assert_task.assert_not_called()
        attach.assert_not_called()
        self.assertTrue(result["waiting_approval"])
        self.assertEqual(1, result["pending"])

    def test_a_rejected_idea_image_never_reaches_the_idea_card(self) -> None:
        request = CreateJobRequest(
            type="image",
            erp_enabled=True,
            erp_project_id="PROJ-0049",
            erp_task_id=self.PARENT,
            erp_source_task_id=self.PARENT,
            erp_output_task_id=self.CHILD_A,
        )
        artifacts = [
            JobArtifact(media_name="idea-a-1.jpg", url="https://media.example/idea-a-1.jpg"),
            JobArtifact(media_name="idea-a-2.jpg", url="https://media.example/idea-a-2.jpg"),
        ]
        job = JobRecord(
            type="image",
            result={"dashboard_approvals": {"0": {"status": "rejected"}, "1": {"status": "approved"}}},
        )
        self.loop.run_until_complete(self.store.add_job(job))

        with patch.object(self.service, "_erp_assert_task_in_project"), patch.object(
            self.service, "_erp_source_comment_id"
        ), patch.object(
            self.service,
            "_erp_attach_url",
            return_value={"id": "https://media.example/idea-a-2.jpg", "name": "idea-a-2.jpg", "url": "https://media.example/idea-a-2.jpg"},
        ) as attach, patch.object(self.service, "_erp_add_task_label", return_value={}):
            result = self.loop.run_until_complete(self.service._archive_erp_artifacts(job.id, request, artifacts))

        self.assertEqual(1, attach.call_count)
        self.assertEqual(self.CHILD_A, attach.call_args.args[2])
        self.assertEqual("https://media.example/idea-a-2.jpg", attach.call_args.args[3])
        # The surviving image keeps its original position, so a rejected first
        # image cannot make image 2 land on the card named as image 1.
        self.assertTrue(attach.call_args.args[4].endswith("-2.jpg"), attach.call_args.args[4])
        self.assertEqual(1, result["sent"])

    def test_a_cover_image_is_a_usable_source_attachment(self) -> None:
        attachments = self.service._erp_extract_task_attachments(
            {"name": self.PARENT, "cover_image": "/private/files/khan-tay.jpg"}
        )
        self.assertEqual(1, len(attachments))
        self.assertEqual("khan-tay.jpg", attachments[0]["name"])
        self.assertTrue(attachments[0]["url"].startswith("https://erp.havigroup.llc/"))

    def test_a_named_source_card_may_sit_outside_the_saved_source_column(self) -> None:
        """An "Idea" card lives in Working; only the auto sweep is column-locked."""
        request = CreateJobRequest(
            type="image",
            erp_enabled=True,
            erp_project_id="PROJ-0013",
            erp_status_id="Working",
            erp_task_id=self.PARENT,
            erp_source_task_id=self.PARENT,
            erp_source_attachment_ids=["private/files/khan-tay.jpg"],
            automation_graph={
                "version": 1,
                "edges": [],
                "modules": [
                    {
                        "id": "erp_source",
                        "type": "erp_source",
                        "enabled": True,
                        "settings": {"erpTask": self.PARENT, "erpStatus": "Working"},
                    },
                    {"id": "flow", "type": "flow", "enabled": True},
                ],
            },
        )
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(
                    api_key="test-key",
                    api_secret="test-secret",
                    project_id="PROJ-0013",
                    status="Open",  # the saved sweep column, not this card's column
                )
            )
        )
        job = JobRecord(type="image")
        self.loop.run_until_complete(self.store.add_job(job))

        with patch.object(
            self.service, "_erp_auto_source_list_ids", side_effect=lambda *_a, **_k: []
        ) as list_ids, patch.object(
            self.service, "_erp_task_hint_by_id", return_value={"name": self.PARENT, "status": "Working"}
        ), patch.object(
            self.service, "_download_erp_task_image_attachments", return_value=["/tmp/khan-tay.jpg"]
        ), patch.object(
            self.service, "_set_automation_module_status", new_callable=AsyncMock
        ):
            resolved = self.loop.run_until_complete(
                self.service._request_with_erp_source_images(job.id, request)
            )

        self.assertEqual("Working", list_ids.call_args.args[3])
        self.assertEqual("Working", resolved.erp_status_id)
        self.assertEqual(self.PARENT, resolved.erp_source_task_id)

    def test_the_project_guard_follows_the_configured_project(self) -> None:
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(api_key="test-key", api_secret="test-secret", project_id="PROJ-0013")
            )
        )
        self.assertEqual("PROJ-0013", self.service._erp_allowed_project_id())
        self.assertEqual("PROJ-0013", self.service._erp_required_project_id("PROJ-0013"))
        with self.assertRaisesRegex(RuntimeError, "PROJ-0013"):
            self.service._erp_required_project_id("PROJ-0049")


class HvgErpRestartResumeTests(_ErpServiceTestCase):
    """Khởi động lại máy chủ không được làm rơi hàng đợi thẻ idea.

    10/9: mỗi lần đẩy code là 69 lượt đang chờ thành ``interrupted`` và nằm
    im tới khi có người vào xếp lại bằng tay. Không ai ngồi trực thì cả lô
    đứng tới sáng.
    """

    PARENT = "TASK-2026-05384"
    OTHER_PARENT = "TASK-2026-05740"
    CHILD = "TASK-2026-05420"

    def _idea_job(self, child: str, status: str = "running", **extra) -> JobRecord:
        payload = {
            "type": "image",
            "prompt": f"idea cho {child}",
            "count": 12,
            "aspect": "square",
            "erp_enabled": True,
            "erp_task_id": self.PARENT,
            "erp_source_task_id": self.PARENT,
            "erp_output_task_id": child,
        }
        payload.update(extra)
        return JobRecord(type="image", status=status, title=f"Idea hoa ({child})", input=payload)

    def _restart(self, *jobs: JobRecord) -> None:
        for job in jobs:
            self.loop.run_until_complete(self.store.add_job(job))
        self.store = StateStore()
        self.service = FlowWebService(self.store)

    def _detail(self, task_id: str, parent: str = "") -> dict:
        return {
            "name": task_id,
            "subject": "Hoa thêu tay",
            "description": "ý tưởng",
            "parent_task": parent or self.PARENT,
            # Lượt xếp lại đọc thẻ cha để xem chốt content; thẻ cha ở đây
            # cũng dựng bằng hàm này nên khai sẵn khối Thuộc tính.
            "meta": _idea_parent_meta(),
            "attachments": [],
            "comments": [],
        }

    def _resume(self, details=None, **patches):
        details = details or {}
        run = AsyncMock()
        with patch.object(
            self.service,
            "_erp_task_detail",
            side_effect=lambda _key, _token, task_id: details.get(task_id) or self._detail(task_id),
        ), patch.object(self.service, "_run_erp_idea_jobs", new=run), patch.object(
            self.service, "_flow_quota_pause_reason", return_value=patches.get("paused", "")
        ):
            outcome = self.loop.run_until_complete(self.service.resume_interrupted_erp_idea_jobs())
            for _ in range(3):
                self.loop.run_until_complete(asyncio.sleep(0))
        return outcome, run

    def test_a_restart_puts_the_interrupted_idea_runs_back_in_the_queue(self) -> None:
        old = self._idea_job(self.CHILD, status="queued")
        plain = JobRecord(type="image", status="running", title="Ảnh tay", input={"type": "image", "prompt": "x"})
        self._restart(old, plain)

        outcome, run = self._resume()

        self.assertEqual([self.CHILD], [item["task_id"] for item in outcome["resumed"]])
        new_id = outcome["resumed"][0]["job_id"]
        self.assertNotEqual(old.id, new_id)
        fresh = self.store.get_job(new_id)
        self.assertEqual("queued", fresh.status)
        self.assertEqual(old.title, fresh.title)
        self.assertEqual(f"idea cho {self.CHILD}", fresh.input["prompt"])
        self.assertEqual(12, fresh.input["count"])
        self.assertEqual(self.CHILD, fresh.input["erp_output_task_id"])
        self.assertEqual(old.id, fresh.input["resumed_from"])
        run.assert_awaited_once()
        self.assertEqual([new_id], [job_id for job_id, _request in run.await_args.args[0]])
        # Lượt tay không phải thẻ idea: không có gì để hỏi lại ERP, để nguyên.
        self.assertEqual("interrupted", self.store.get_job(plain.id).status)

    def test_a_card_that_already_has_its_images_is_not_run_again(self) -> None:
        self._restart(self._idea_job(self.CHILD))

        with patch.object(self.service, "_erp_idea_skip_reason", return_value="đã có ảnh Flow"):
            outcome, run = self._resume()

        self.assertEqual([], outcome["resumed"])
        self.assertEqual("đã có ảnh Flow", outcome["skipped"][0]["reason"])
        run.assert_not_awaited()

    def test_a_card_cut_off_again_and_again_is_left_for_a_person(self) -> None:
        # Một thẻ làm sập app thì mỗi lần app dậy lại chạy đúng thẻ đó: vòng
        # lặp đốt lượt Flow mà không ai thấy. Có trần, quá trần thì dừng.
        limit = FlowWebService.ERP_IDEA_RESUME_MAX
        self._restart(self._idea_job(self.CHILD, resume_count=limit))

        outcome, run = self._resume()

        self.assertEqual([], outcome["resumed"])
        self.assertIn("khởi động lại", outcome["skipped"][0]["reason"])
        run.assert_not_awaited()

    def test_each_resume_counts_towards_that_ceiling(self) -> None:
        self._restart(self._idea_job(self.CHILD, resume_count=1))

        outcome, _run = self._resume()

        self.assertEqual(2, self.store.get_job(outcome["resumed"][0]["job_id"]).input["resume_count"])

    def test_a_card_the_erp_could_not_answer_for_is_tried_again_later(self) -> None:
        old = self._idea_job(self.CHILD)
        self._restart(old)

        def _down(_key, _token, _task_id):
            raise RuntimeError("ERP 503")

        with patch.object(self.service, "_erp_task_detail", side_effect=_down), patch.object(
            self.service, "_run_erp_idea_jobs", new=AsyncMock()
        ), patch.object(self.service, "_flow_quota_pause_reason", return_value=""):
            outcome = self.loop.run_until_complete(self.service.resume_interrupted_erp_idea_jobs())

        self.assertEqual([], outcome["resumed"])
        self.assertEqual([old.id], outcome["retry"])

    def test_nothing_is_resumed_while_every_flow_profile_is_out_of_quota(self) -> None:
        old = self._idea_job(self.CHILD)
        self._restart(old)

        outcome, run = self._resume(paused="hết quota Agent")

        self.assertEqual([], outcome["resumed"])
        self.assertEqual([old.id], outcome["retry"])
        run.assert_not_awaited()

    def test_each_idea_card_goes_back_to_the_queue_of_its_own_parent(self) -> None:
        other_child = "TASK-2026-05750"
        self._restart(self._idea_job(self.CHILD), self._idea_job(other_child))
        details = {other_child: self._detail(other_child, parent=self.OTHER_PARENT)}

        outcome, run = self._resume(details)

        self.assertEqual(
            {self.CHILD: self.PARENT, other_child: self.OTHER_PARENT},
            {item["task_id"]: item["parent_task_id"] for item in outcome["resumed"]},
        )
        self.assertEqual(2, run.await_count)

    def test_the_resume_and_a_fresh_fan_out_never_queue_the_same_card_twice(self) -> None:
        # Bot quét ngay lúc app dậy, cùng lúc với lượt xếp lại. Hai bên cùng
        # đọc thẻ trống, cùng thấy "chưa có lượt nào" là thẻ chạy hai lần.
        self._restart(self._idea_job(self.CHILD))
        order: list = []

        def _detail(_key, _token, task_id):
            order.append("resume đọc thẻ")
            return self._detail(task_id)

        async def _fan_out(_request):
            order.append("bot xếp lượt")
            return {"queued": []}

        async def _both():
            await asyncio.gather(
                self.service.resume_interrupted_erp_idea_jobs(),
                self.service.enqueue_erp_idea_jobs(ERPIdeaBatchRequest(task_id=self.PARENT)),
            )

        with patch.object(self.service, "_erp_task_detail", side_effect=_detail), patch.object(
            self.service, "_run_erp_idea_jobs", new=AsyncMock()
        ), patch.object(self.service, "_flow_quota_pause_reason", return_value=""), patch.object(
            self.service, "_enqueue_erp_idea_jobs_unlocked", side_effect=_fan_out
        ):
            self.loop.run_until_complete(_both())

        # Lượt xếp lại đọc thẻ con rồi thẻ cha (xem chốt content), xong hết
        # mới tới lượt bot.
        self.assertEqual(["resume đọc thẻ", "resume đọc thẻ", "bot xếp lượt"], order)


    def test_the_app_asks_again_for_the_cards_the_erp_did_not_answer_for(self) -> None:
        # Máy vừa bật lại thì mạng lên sau app: lượt hỏi đầu gặp ERP chưa trả
        # lời, và bỏ luôn thì cả lô lại nằm im như cũ.
        old = self._idea_job(self.CHILD)
        self._restart(old)
        calls: list = []

        async def _resume(job_ids=None):
            calls.append(list(job_ids or []))
            return {"resumed": [], "skipped": [], "retry": [old.id] if len(calls) == 1 else []}

        with patch.object(self.service, "resume_interrupted_erp_idea_jobs", side_effect=_resume), patch.object(
            FlowWebService, "ERP_IDEA_RESUME_DELAY_SECONDS", 0
        ), patch.object(FlowWebService, "ERP_IDEA_RESUME_RETRY_SECONDS", 0):
            self.loop.run_until_complete(self.service.resume_after_restart())

        self.assertEqual([[old.id], [old.id]], calls)


class HvgErpIdeaParentsSideBySideTests(_ErpServiceTestCase):
    """Thẻ cha thứ hai không phải đứng chờ thẻ cha đầu chạy hết.

    10/9: PN 48 thẻ chạy bảy tiếng, 5740 gắn agent xong đứng im suốt bảy
    tiếng ấy vì bot thấy "đang có lượt chạy" — lượt của một thẻ cha khác.
    """

    PARENT = "TASK-2026-05384"
    OTHER_PARENT = "TASK-2026-05740"

    def _bot_autorun(self, parent: str, *, in_flight: str = ""):
        release = asyncio.Event()

        async def _hold(_entries):
            await release.wait()

        async def _scenario():
            if in_flight:
                request = CreateJobRequest(type="image", prompt="x")
                self.service._start_erp_idea_batch(in_flight, [("job-dang-chay", request)])
                await asyncio.sleep(0)
            try:
                return await self.service._agent_bot_autorun(parent)
            finally:
                release.set()
                await asyncio.sleep(0)

        with patch.object(self.service, "_run_erp_idea_jobs", side_effect=_hold), patch.object(
            self.service, "repair_erp_idea_children", new_callable=AsyncMock, return_value={}
        ), patch.object(self.service, "_flow_quota_pause_reason", return_value=""), patch.object(
            self.service, "enqueue_erp_idea_jobs", new_callable=AsyncMock, return_value={"queued": []}
        ) as enqueue:
            response = self.loop.run_until_complete(_scenario())
        return response, enqueue

    def test_the_agent_bot_starts_a_second_parent_while_the_first_is_generating(self) -> None:
        response, enqueue = self._bot_autorun(self.OTHER_PARENT, in_flight=self.PARENT)

        enqueue.assert_awaited_once()
        self.assertNotEqual("đang có lượt chạy", response.get("reason"))

    def test_the_agent_bot_does_not_stack_a_parent_on_its_own_run(self) -> None:
        response, enqueue = self._bot_autorun(self.PARENT, in_flight=self.PARENT)

        enqueue.assert_not_awaited()
        self.assertEqual("đang có lượt chạy", response["reason"])

    def test_two_parents_take_turns_instead_of_one_waiting_for_the_other(self) -> None:
        # Cùng một trần thẻ bay cho cả máy (tải lên ERP có giới hạn), nhưng
        # hai thẻ cha thay phiên nhau chứ không để một bên chờ bên kia xong.
        started: list = []
        in_flight = 0
        peak = 0

        async def _run(job_id: str, _request) -> None:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            started.append(job_id)
            for _ in range(3):
                await asyncio.sleep(0)
            in_flight -= 1

        request = CreateJobRequest(type="image", prompt="x")
        first = [(f"a{index}", request) for index in range(1, 4)]
        second = [(f"b{index}", request) for index in range(1, 4)]

        async def _both():
            one = asyncio.ensure_future(self.service._run_erp_idea_jobs(first))
            await asyncio.sleep(0)
            two = asyncio.ensure_future(self.service._run_erp_idea_jobs(second))
            await asyncio.gather(one, two)

        with patch.dict(os.environ, {"ERP_IDEA_CONCURRENCY": "1"}), patch.object(
            self.service, "_run_flow_job", new=_run
        ):
            self.loop.run_until_complete(_both())

        self.assertEqual(1, peak)
        self.assertLess(started.index("b1"), started.index("a3"), started)


class HvgErpIdeaRepairTests(_ErpServiceTestCase):
    """Thẻ idea đứng im dù app tưởng đã chạy xong thì phải tự vá lại."""

    PARENT = "TASK-2026-00202"
    CHILD = "TASK-2026-00615"

    def setUp(self) -> None:
        # Từ 11/09/2026 chạy bù mặc định tắt; các bài này kiểm chính cơ chế chạy bù nên bật lại.
        self._topup_env = patch.dict(os.environ, {"ERP_IDEA_TOPUP": "1"}, clear=False)
        self._topup_env.start()
        self.addCleanup(self._topup_env.stop)
        super().setUp()
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(
                    api_key="test-key",
                    api_secret="test-secret",
                    project_id="PROJ-0013",
                    task_id=self.PARENT,
                )
            )
        )

    def _details(self, *, child_comments: list | None = None, child_status: str = "Open") -> dict:
        return {
            self.PARENT: {
                "name": self.PARENT,
                "subject": "Idea",
                "status": "Working",
                "description": "<p>Tạo idea cho khăn tay cô dâu thêu tay</p>",
                "cover_image": "/private/files/khan-tay.jpg",
                "meta": _idea_parent_meta(),
                "children": [{"name": self.CHILD, "subject": "Idea 1"}],
            },
            self.CHILD: {
                "name": self.CHILD,
                "subject": "Idea 1",
                "status": child_status,
                "description": "<p>Khăn tay đặt cạnh cây thông</p>",
                "cover_image": "",
                "comments": list(child_comments or []),
            },
        }

    def _job(
        self,
        *,
        images: int,
        wanted: int = 12,
        status: str = "completed",
        approvals: dict | None = None,
        created_at: str = "2026-08-18T09:00:00Z",
    ) -> JobRecord:
        job = JobRecord(
            type="image",
            status=status,
            created_at=created_at,
            input={"erp_output_task_id": self.CHILD, "count": wanted, "erp_enabled": True},
            artifacts=[
                JobArtifact(media_name=f"idea-{index}.jpg", url=f"https://media.example/idea-{index}.jpg")
                for index in range(images)
            ],
            result={"dashboard_approvals": approvals} if approvals else {},
        )
        self.loop.run_until_complete(self.store.add_job(job))
        return job

    def _review_comment(self, job_id: str, index: int) -> dict:
        """Đúng hình hài một bình luận ảnh chờ duyệt: chữ trống, dấu ở meta."""
        return {
            "name": f"cmt-{index}",
            "content": "​",
            "meta": f"[FLOW_V2_REVIEW {job_id}#{index}]",
            "attachments": [{"file_url": f"/files/flow-{index}.jpg"}],
        }

    def _repair(self, details: dict) -> tuple[dict, AsyncMock]:
        def _update_meta(_key, _token, task_id, meta, *, project=""):
            details[task_id]["meta"] = meta
            return {"name": task_id, "meta": meta}

        with patch.object(
            self.service, "_erp_task_project_id", return_value="PROJ-0013"
        ), patch.object(
            self.service, "_erp_task_detail", side_effect=lambda _key, _token, task_id: details[task_id]
        ), patch.object(
            self.service, "_erp_task_attachment_files", return_value=[]
        ), patch.object(
            self.service, "_erp_update_task_meta", side_effect=_update_meta
        ), patch.object(
            self.service, "publish_erp_review", new_callable=AsyncMock
        ) as publish, patch.object(self.service, "_run_flow_job", new_callable=AsyncMock):
            publish.return_value = {"published": 12}
            response = self.loop.run_until_complete(self.service.repair_erp_idea_children())
            self.loop.run_until_complete(asyncio.sleep(0))
        return response, publish

    def test_a_finished_run_whose_images_never_reached_the_card_is_posted_again(self) -> None:
        # The network dropped while the images were going up. The run still
        # says "completed", so from then on nothing ever looked at this card.
        job = self._job(images=12)

        response, publish = self._repair(self._details())

        publish.assert_awaited_once_with(job.id)
        self.assertEqual(
            [{"task_id": self.CHILD, "job_id": job.id, "published": 12}], response["republished"]
        )
        self.assertEqual([], response["topped_up"])

    def test_the_watcher_does_not_republish_a_job_with_manual_recaptcha_media(self) -> None:
        job = self._job(images=12)
        media_id = job.artifacts[0].media_name
        # Two independent failed passes reach the default manual-review
        # threshold. The repair watcher must stop before publish_erp_review,
        # so this test cannot write to a real ERP card.
        self.loop.run_until_complete(
            self.service._record_flow_upsample_recaptcha_rejection(
                task_id=self.CHILD,
                job_id=job.id,
                media_id=media_id,
            )
        )
        self.loop.run_until_complete(
            self.service._record_flow_upsample_recaptcha_rejection(
                task_id=self.CHILD,
                job_id=job.id,
                media_id=media_id,
            )
        )

        response, publish = self._repair(self._details())

        publish.assert_not_awaited()
        self.assertEqual([], response["republished"])
        self.assertEqual(job.id, response["skipped"][0]["job_id"])
        self.assertIn("cần xem thủ công", response["skipped"][0]["reason"])

    def test_the_rest_of_a_half_posted_batch_goes_up(self) -> None:
        job = self._job(images=12)
        details = self._details(child_comments=[self._review_comment(job.id, 0)])

        _response, publish = self._repair(details)

        publish.assert_awaited_once_with(job.id)

    def test_a_batch_already_fully_on_the_card_is_left_alone(self) -> None:
        job = self._job(images=2)
        details = self._details(
            child_comments=[self._review_comment(job.id, 0), self._review_comment(job.id, 1)]
        )

        response, publish = self._repair(details)

        publish.assert_not_awaited()
        self.assertEqual([], response["republished"])

    def test_an_older_batch_is_not_stacked_onto_a_card_that_already_shows_one(self) -> None:
        # The card shows the newer run's images. Putting the older run's
        # twelve up as well is what turns one card into a wall of duplicates.
        self._job(images=12, created_at="2026-08-15T02:00:00Z")
        newer = self._job(images=12, created_at="2026-08-15T04:00:00Z")
        details = self._details(
            child_comments=[self._review_comment(newer.id, index) for index in range(12)]
        )

        _response, publish = self._repair(details)

        publish.assert_not_awaited()

    def test_a_card_whose_images_were_all_rejected_is_not_refilled(self) -> None:
        # A blank card is not proof nothing was posted: 👎 removes the comment.
        # The decisions on the run are what tell the two apart.
        self._job(images=2, wanted=2, approvals={"0": {"status": "rejected"}, "1": {"status": "rejected"}})

        response, publish = self._repair(self._details())

        publish.assert_not_awaited()
        self.assertEqual([], response["topped_up"])

    def test_a_run_that_made_fewer_images_than_asked_is_topped_up(self) -> None:
        # Flow returned one of the twelve. Nothing on the card is wrong, so
        # there is nothing to post again - the other eleven must be made.
        job = self._job(images=1)
        details = self._details(child_comments=[self._review_comment(job.id, 0)])

        response, publish = self._repair(details)

        publish.assert_not_awaited()
        self.assertEqual([{"count": 11, "task_ids": [self.CHILD]}], [
            {"count": item["count"], "task_ids": item["task_ids"]} for item in response["topped_up"]
        ])
        queued = response["topped_up"][0]["queued"]
        self.assertEqual([self.CHILD], [item["task_id"] for item in queued])
        topped = self.store.get_job(queued[0]["job_id"])
        self.assertEqual(11, topped.input["count"])
        self.assertEqual(self.CHILD, topped.input["erp_output_task_id"])

    def test_topping_up_gives_up_after_too_many_runs(self) -> None:
        for index in range(self.service.ERP_IDEA_TOPUP_MAX_JOBS):
            self._job(images=1, created_at=f"2026-08-1{index}T09:00:00Z")
        details = self._details(
            child_comments=[self._review_comment(job_id, 0) for job_id in self.service._erp_child_job_ids(self.CHILD)]
        )

        response, _publish = self._repair(details)

        self.assertEqual([], response["topped_up"])
        self.assertIn("đã chạy quá nhiều lượt", response["skipped"][0]["reason"])

    def test_a_card_someone_closed_is_left_alone(self) -> None:
        self._job(images=1)

        response, publish = self._repair(self._details(child_status="Completed"))

        publish.assert_not_awaited()
        self.assertEqual([], response["topped_up"])

    def test_the_watcher_repairs_before_it_looks_for_new_ideas(self) -> None:
        # A card stuck behind a half-finished run is not in the "never run"
        # list, so the fan-out below would never see it.
        job = self._job(images=12)
        details = self._details()

        def _update_meta(_key, _token, task_id, meta, *, project=""):
            details[task_id]["meta"] = meta
            return {"name": task_id, "meta": meta}

        with patch.object(
            self.service, "_erp_task_project_id", return_value="PROJ-0013"
        ), patch.object(
            self.service, "_erp_task_detail", side_effect=lambda _key, _token, task_id: details[task_id]
        ), patch.object(
            self.service, "_erp_task_attachment_files", return_value=[]
        ), patch.object(
            self.service, "_erp_update_task_meta", side_effect=_update_meta
        ), patch.object(
            self.service, "publish_erp_review", new_callable=AsyncMock
        ) as publish, patch.object(self.service, "_run_flow_job", new_callable=AsyncMock):
            publish.return_value = {"published": 12}
            response = self.loop.run_until_complete(self.service.autorun_erp_idea_children())
            self.loop.run_until_complete(asyncio.sleep(0))

        publish.assert_awaited_once_with(job.id)
        self.assertEqual(
            [self.CHILD], [item["task_id"] for item in response["repaired"]["republished"]]
        )


class HvgErpIdeaIntakeTests(_ErpServiceTestCase):
    """Thả ảnh lên thẻ Idea là có thẻ con: mỗi ảnh một thẻ, không phải gõ gì."""

    PARENT = "TASK-2026-00202"
    CHILD_A = "TASK-2026-00615"
    PRODUCT = "/private/files/khan-tay.jpg"

    def _board(
        self,
        dropped: list[str],
        children: list[str] | None = None,
        files: list[str] | None = None,
        cover_image: str | None = None,
    ) -> dict:
        """A parent Idea card carrying the product photo plus dropped ideas."""
        selected_cover = self.PRODUCT if cover_image is None else cover_image
        details: dict = {
            self.PARENT: {
                "name": self.PARENT,
                "subject": "Idea",
                "status": "Working",
                "description": "<p>Khăn tay cô dâu thêu tay mùa christmas</p>",
                "cover_image": selected_cover,
                "meta": _idea_parent_meta(),
                "children": [{"name": name, "subject": "a"} for name in (children or [])],
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
        # Dropping a file straight onto the card in the ERP UI lands here, and
        # nowhere in taskDetail - hence the separate taskAttachments read.
        details["__files__"] = [
            # `name` on an ERP file row is the docname, not the file name.
            {"name": f"docname{index}", "file_name": Path(url).name, "file_url": url}
            for index, url in enumerate(files or [])
        ]
        for name in children or []:
            details[name] = {
                "name": name,
                "subject": "a",
                "status": "Open",
                "description": "<p>Khăn tay cạnh cây thông</p>",
                "cover_image": "",
                "comments": [],
            }
        return details

    def _wire(self, details: dict):
        """Stand in for every ERP write the intake makes, and record them."""
        created: list[dict] = []
        attached: list[dict] = []
        covers: list[tuple[str, str]] = []

        def _create(_key, _token, parent, project, subject, *, status="Open", description=""):
            child_id = f"TASK-NEW-{len(created)}"
            created.append({"id": child_id, "parent": parent, "project": project, "subject": subject, "status": status})
            details[parent]["children"].append({"name": child_id, "subject": subject})
            details[child_id] = {
                "name": child_id,
                "subject": subject,
                "status": status,
                "description": description,
                "cover_image": "",
                "comments": [],
            }
            return child_id

        def _download(_key, _token, _task_id, attachment):
            return f"bytes:{attachment.get('name')}".encode(), "image/jpeg"

        def _attach(
            _key, _token, task_id, data, mime, name, set_cover,
            parent_comment="", comment_text="", silent_comment=False,
        ):
            attached.append(
                {"task": task_id, "name": name, "bytes": data, "comment": comment_text, "silent": silent_comment}
            )
            # Bản sao trùng từng byte và trùng tên thì ERP dùng lại đúng tệp cũ,
            # nên thẻ con trỏ về chính đường dẫn của ảnh trên thẻ cha - đo trên
            # ERP thật. Đó cũng là thứ giữ chỗ cho ảnh, thay cho dòng chữ đánh
            # dấu ngày trước.
            url = f"/private/files/{name}"
            details[task_id]["comments"].append(
                {"name": f"cmt-{len(attached)}", "content": comment_text, "attachments": [{"file_url": url, "file_name": name}]}
            )
            return {"url": url, "name": name}

        def _cover(_key, _token, task_id, data, _mime, name):
            url = f"/private/files/{name}"
            covers.append((task_id, url))
            details[task_id]["cover_image"] = url
            details[task_id]["cover_bytes"] = data

        def _add_agent(_key, _token, task_id, bot_user):
            self.agents_added.append((task_id, bot_user))
            details[task_id].setdefault("agents", []).append({"bot_user": bot_user})

        def _update_meta(_key, _token, task_id, meta, *, project=""):
            details[task_id]["meta"] = meta
            return {"name": task_id, "meta": meta}

        self.agents_added = []
        return created, attached, covers, patch.multiple(
            self.service,
            _erp_task_project_id=lambda *_args, **_kwargs: "PROJ-0013",
            _erp_task_detail=lambda _key, _token, task_id: details[task_id],
            _erp_task_attachment_files=lambda _key, _token, task_id: (
                details.get("__files__", []) if task_id == self.PARENT else []
            ),
            _erp_create_child_task=_create,
            _erp_download_attachment_bytes=_download,
            _erp_attach_file_bytes=_attach,
            _erp_set_task_cover=_cover,
            _erp_add_task_agent=_add_agent,
            _erp_update_task_meta=_update_meta,
        )

    def _intake(self, details: dict):
        created, attached, covers, wiring = self._wire(details)
        with wiring:
            outcome, child_details = self.loop.run_until_complete(
                self.service._erp_intake_idea_images(
                    "test-key", "test-secret", self.PARENT, "PROJ-0013", details[self.PARENT]
                )
            )
        return outcome, child_details, created, attached, covers

    def test_every_image_dropped_on_the_idea_card_becomes_a_child_card(self) -> None:
        details = self._board(
            ["/private/files/tho-noel.jpg", "/private/files/xe-tai-thong.jpg"], children=[self.CHILD_A]
        )

        outcome, _details, created, attached, covers = self._intake(details)

        self.assertEqual(["TASK-NEW-0", "TASK-NEW-1"], [item["task_id"] for item in outcome])
        # Numbered on from the cards already there, so the board reads in order.
        self.assertEqual(["Idea 2", "Idea 3"], [item["subject"] for item in created])
        self.assertEqual([self.PARENT, self.PARENT], [item["parent"] for item in created])
        self.assertEqual(["PROJ-0013", "PROJ-0013"], [item["project"] for item in created])
        self.assertEqual(["Open", "Open"], [item["status"] for item in created])

        # Each new card carries its own picture, and it is that card's cover so
        # the board shows the idea rather than an empty rectangle.
        self.assertEqual(["tho-noel.jpg", "xe-tai-thong.jpg"], [item["name"] for item in attached])
        self.assertEqual(["TASK-NEW-0", "TASK-NEW-1"], [item["task"] for item in attached])
        self.assertEqual(
            [
                ("TASK-NEW-0", "/private/files/tho-noel.jpg"),
                ("TASK-NEW-1", "/private/files/xe-tai-thong.jpg"),
            ],
            covers,
        )
        # The cover is set from the same bytes the card carries, because the
        # ERP refuses a cover that is not a file of that card's own.
        self.assertEqual(
            [item["bytes"] for item in attached],
            [details[task_id]["cover_bytes"] for task_id, _url in covers],
        )

    def test_a_card_without_cover_makes_a_child_for_each_of_four_dropped_images(self) -> None:
        dropped = [
            "/private/files/idea-1.jpg",
            "/private/files/idea-2.jpg",
            "/private/files/idea-3.jpg",
            "/private/files/idea-4.jpg",
        ]
        details = self._board(dropped, cover_image="")

        outcome, _details, created, attached, covers = self._intake(details)

        self.assertEqual(4, len(outcome))
        self.assertEqual(["Idea 1", "Idea 2", "Idea 3", "Idea 4"], [item["subject"] for item in created])
        self.assertEqual([Path(url).name for url in dropped], [item["name"] for item in attached])
        self.assertEqual(
            [(f"TASK-NEW-{index}", f"/private/files/idea-{index + 1}.jpg") for index in range(4)],
            covers,
        )

    def test_a_cover_outside_dropped_images_stays_product_and_two_ideas_stay_two_children(self) -> None:
        details = self._board(
            ["/private/files/idea-1.jpg", "/private/files/idea-2.jpg"],
            cover_image=self.PRODUCT,
        )

        outcome, _details, created, attached, _covers = self._intake(details)

        self.assertEqual(2, len(outcome))
        self.assertEqual(["Idea 1", "Idea 2"], [item["subject"] for item in created])
        self.assertEqual(["idea-1.jpg", "idea-2.jpg"], [item["name"] for item in attached])

    def test_a_cover_that_is_one_dropped_image_remains_product(self) -> None:
        product = "/private/files/product.jpg"
        details = self._board(
            ["/private/files/idea-1.jpg", product, "/private/files/idea-2.jpg"],
            cover_image=product,
        )

        outcome, _details, created, attached, _covers = self._intake(details)

        self.assertEqual(2, len(outcome))
        self.assertEqual(["Idea 1", "Idea 2"], [item["subject"] for item in created])
        self.assertEqual(["idea-1.jpg", "idea-2.jpg"], [item["name"] for item in attached])

    def test_a_card_without_cover_makes_a_child_for_its_only_dropped_image(self) -> None:
        details = self._board(["/private/files/idea-only.jpg"], cover_image="")

        outcome, _details, created, attached, covers = self._intake(details)

        self.assertEqual(1, len(outcome))
        self.assertEqual(["Idea 1"], [item["subject"] for item in created])
        self.assertEqual(["idea-only.jpg"], [item["name"] for item in attached])
        self.assertEqual([("TASK-NEW-0", "/private/files/idea-only.jpg")], covers)

    def test_a_new_child_card_carries_the_parents_agent(self) -> None:
        # Gắn agent vào thẻ cha là đã nói cả cụm việc này là của bot; thẻ con
        # sinh ra với ô người phụ trách trống trông như bị bỏ quên.
        details = self._board(["/private/files/tho-noel.jpg"], children=[self.CHILD_A])
        details[self.PARENT]["agents"] = [{"bot_user": "agent-kin@bots.hvg.internal"}]

        outcome, _details, _created, _attached, _covers = self._intake(details)

        self.assertEqual(
            [("TASK-NEW-0", "agent-kin@bots.hvg.internal")], self.agents_added
        )
        self.assertEqual(["TASK-NEW-0"], [item["task_id"] for item in outcome])

    def test_a_parent_with_no_agent_hands_down_no_agent(self) -> None:
        details = self._board(["/private/files/tho-noel.jpg"], children=[self.CHILD_A])

        self._intake(details)

        self.assertEqual([], self.agents_added)

    def test_every_agent_on_the_parent_is_handed_down(self) -> None:
        details = self._board(
            ["/private/files/tho-noel.jpg", "/private/files/xe-tai-thong.jpg"], children=[self.CHILD_A]
        )
        details[self.PARENT]["agents"] = [
            {"bot_user": "agent-kin@bots.hvg.internal"},
            {"bot_user": "agent-hai@bots.hvg.internal"},
        ]

        self._intake(details)

        self.assertEqual(
            [
                ("TASK-NEW-0", "agent-kin@bots.hvg.internal"),
                ("TASK-NEW-0", "agent-hai@bots.hvg.internal"),
                ("TASK-NEW-1", "agent-kin@bots.hvg.internal"),
                ("TASK-NEW-1", "agent-hai@bots.hvg.internal"),
            ],
            self.agents_added,
        )

    def test_the_product_photo_stays_the_product_photo(self) -> None:
        # The first image on the card is what every idea is a picture *of*, and
        # a card without a picture of its own still falls back to it. Turning it
        # into an idea card would run the product photo against itself.
        details = self._board(["/private/files/tho-noel.jpg"], children=[self.CHILD_A])

        outcome, _details, _created, attached, _covers = self._intake(details)

        self.assertEqual(1, len(outcome))
        self.assertEqual(["tho-noel.jpg"], [item["name"] for item in attached])

    def test_a_card_with_only_the_product_photo_creates_nothing(self) -> None:
        details = self._board([], children=[self.CHILD_A])

        outcome, child_details, created, _attached, _covers = self._intake(details)

        self.assertEqual([], outcome)
        self.assertEqual([], created)
        # Nothing to do means nothing read either: no child card was fetched.
        self.assertEqual({}, child_details)

    def test_the_same_image_is_not_given_a_second_card(self) -> None:
        # The ledger is on the cards themselves: the child card carries the very
        # picture it was made from, so a card deleted by hand really does put
        # its image back in the queue.
        details = self._board(["/private/files/tho-noel.jpg"], children=[self.CHILD_A])
        self._intake(details)

        again, _details, created, attached, _covers = self._intake(details)

        self.assertEqual([], again)
        self.assertEqual([], created)
        self.assertEqual([], attached)

    def test_the_child_card_is_given_the_picture_and_nothing_else(self) -> None:
        # Thẻ con là chỗ người ta nhìn, không phải sổ tay của bot: không một
        # dòng chữ nào được viết lên đó, kể cả dòng mặc định của app.
        details = self._board(["/private/files/tho-noel.jpg"], children=[self.CHILD_A])

        _outcome, _details, _created, attached, _covers = self._intake(details)

        self.assertEqual([""], [item["comment"] for item in attached])
        self.assertEqual([True], [item["silent"] for item in attached])
        for comment in details["TASK-NEW-0"]["comments"]:
            self.assertEqual("", comment["content"])

    def test_the_cover_alone_is_enough_to_hold_the_place(self) -> None:
        # Ảnh dán được nhưng bình luận mất - vẫn không được tạo thẻ thứ hai.
        details = self._board(["/private/files/tho-noel.jpg"], children=[self.CHILD_A])
        self._intake(details)
        details["TASK-NEW-0"]["comments"] = []

        again, _details, created, _attached, _covers = self._intake(details)

        self.assertEqual([], again)
        self.assertEqual([], created)

    def test_the_old_written_marker_still_holds_its_place(self) -> None:
        # Thẻ sinh ra trước thay đổi này còn mang dòng đánh dấu cũ; đọc sót nó
        # là tạo lại một thẻ đã có.
        details = self._board(["/private/files/tho-noel.jpg"], children=[self.CHILD_A])
        details[self.CHILD_A]["comments"] = [
            {"name": "cu", "content": "[FLOW_V2_IDEA src=/private/files/tho-noel.jpg] tho-noel.jpg", "attachments": []}
        ]

        outcome, _details, created, _attached, _covers = self._intake(details)

        self.assertEqual([], outcome)
        self.assertEqual([], created)

    def test_flow_output_on_a_child_card_claims_nothing(self) -> None:
        # Ảnh Flow tự sinh nằm trong thẻ con không được coi là chỗ đã giữ của
        # một ảnh idea nào cả.
        details = self._board(["/private/files/tho-noel.jpg"], children=[self.CHILD_A])
        details[self.CHILD_A]["comments"] = [
            {
                "name": "art",
                "content": "[FLOW_V2_REVIEW job#0] Ảnh 1/12 chờ duyệt",
                "attachments": [{"file_url": "/private/files/flow-abc-1.png", "file_name": "flow-abc-1.png"}],
            }
        ]

        outcome, _details, created, _attached, _covers = self._intake(details)

        self.assertEqual(1, len(outcome))
        self.assertEqual(1, len(created))

    def test_a_new_card_is_run_in_the_same_pass_that_created_it(self) -> None:
        details = self._board(["/private/files/tho-noel.jpg"], children=[self.CHILD_A])
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(api_key="test-key", api_secret="test-secret", project_id="PROJ-0013")
            )
        )
        _created, _attached, _covers, wiring = self._wire(details)
        with wiring, patch.object(self.service, "_run_flow_job", new_callable=AsyncMock):
            response = self.loop.run_until_complete(
                self.service.enqueue_erp_idea_jobs(ERPIdeaBatchRequest(task_id=self.PARENT))
            )
            self.loop.run_until_complete(asyncio.sleep(0))

        self.assertEqual(["TASK-NEW-0"], [item["task_id"] for item in response["created"]])
        self.assertEqual([self.CHILD_A, "TASK-NEW-0"], [item["task_id"] for item in response["queued"]])
        job = self.store.get_job(response["queued"][1]["job_id"])
        # The new card runs on its own picture, not on the parent's product photo.
        self.assertEqual("TASK-NEW-0", job.input["erp_output_task_id"])
        self.assertEqual("TASK-NEW-0", job.input["erp_source_task_id"])
        self.assertTrue(job.input["erp_source_attachment_ids"][0].endswith("tho-noel.jpg"))

    def test_a_file_dropped_straight_onto_the_card_is_found_too(self) -> None:
        # This is what the ERP UI actually does with a drag-and-drop: the file
        # joins the card's attachment list, where taskDetail never shows it and
        # its row is keyed by docname rather than by file name.
        details = self._board([], children=[self.CHILD_A], files=["/private/files/tho-noel.jpg"])

        outcome, _details, created, attached, _covers = self._intake(details)

        self.assertEqual(["Idea 2"], [item["subject"] for item in created])
        self.assertEqual(["tho-noel.jpg"], [item["name"] for item in attached])
        self.assertEqual(["/private/files/tho-noel.jpg"], [item["source"] for item in outcome])

    def test_a_card_whose_only_images_were_dragged_on_still_runs(self) -> None:
        # The whole point of the feature: a card where the user did nothing but
        # drag pictures onto it. Every one of those files sits in the Task's own
        # attachment list, which taskDetail does not report - so the card reads
        # back with no cover, no comments and no children, and the run used to
        # be refused before the intake ever got to look.
        details = self._board(
            [],
            files=["/private/files/san-pham.jpg", "/private/files/tho-noel.jpg"],
        )
        details[self.PARENT]["cover_image"] = ""
        details[self.PARENT]["children"] = []
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(api_key="test-key", api_secret="test-secret", project_id="PROJ-0013")
            )
        )
        _created, _attached, _covers, wiring = self._wire(details)
        with wiring, patch.object(self.service, "_run_flow_job", new_callable=AsyncMock):
            response = self.loop.run_until_complete(
                self.service.enqueue_erp_idea_jobs(ERPIdeaBatchRequest(task_id=self.PARENT))
            )
            self.loop.run_until_complete(asyncio.sleep(0))

        # Không bìa thì không có tín hiệu nào cho phép chọn một ảnh làm sản
        # phẩm. Cả hai ảnh thả đều là ý tưởng và đều phải có thẻ con.
        self.assertEqual(["TASK-NEW-0", "TASK-NEW-1"], [item["task_id"] for item in response["created"]])
        self.assertEqual(["san-pham.jpg", "tho-noel.jpg"], [item["image"] for item in response["created"]])
        self.assertEqual(["TASK-NEW-0", "TASK-NEW-1"], [item["task_id"] for item in response["queued"]])
        self.assertEqual([], response["skipped"])

    def test_a_child_with_no_picture_anywhere_is_skipped_not_refused(self) -> None:
        # The parent's images all live in its attachment list, so it has no
        # source image to lend; the hand-made child has none of its own either.
        # That is one card's problem, not a reason to refuse the whole run.
        details = self._board(
            [],
            children=[self.CHILD_A],
            files=["/private/files/san-pham.jpg", "/private/files/tho-noel.jpg"],
        )
        details[self.PARENT]["cover_image"] = ""
        self.loop.run_until_complete(
            self.store.replace_erp_config(
                ERPConfig(api_key="test-key", api_secret="test-secret", project_id="PROJ-0013")
            )
        )
        _created, _attached, _covers, wiring = self._wire(details)
        with wiring, patch.object(self.service, "_run_flow_job", new_callable=AsyncMock):
            response = self.loop.run_until_complete(
                self.service.enqueue_erp_idea_jobs(ERPIdeaBatchRequest(task_id=self.PARENT))
            )
            self.loop.run_until_complete(asyncio.sleep(0))

        # Hai ảnh không bìa đều thành thẻ con; thẻ cũ không có ảnh vẫn bị bỏ
        # qua riêng nó, thay vì chặn cả lượt intake.
        self.assertEqual(["TASK-NEW-0", "TASK-NEW-1"], [item["task_id"] for item in response["queued"]])
        self.assertEqual([self.CHILD_A], [item["task_id"] for item in response["skipped"]])
        self.assertIn("chưa có ảnh nguồn", response["skipped"][0]["reason"])

    def test_the_intake_can_be_switched_off(self) -> None:
        details = self._board(["/private/files/tho-noel.jpg"], children=[self.CHILD_A])
        with patch.dict(os.environ, {"ERP_IDEA_INTAKE": "0"}):
            outcome, _details, created, _attached, _covers = self._intake(details)

        self.assertEqual([], outcome)
        self.assertEqual([], created)


class HvgErpIdeaRuleCardProductMetaTests(_ErpServiceTestCase):
    """Lời khai sản phẩm trong Thuộc tính phải thắng tên dùng để đoán."""

    PARENT = "TASK-2026-04628"
    CHILD = "TASK-2026-04629"

    def _card(
        self,
        *,
        parent_meta: str = "",
        child_meta: str = "",
        parent_subject: str = "Idea Phương",
        child_subject: str = "Idea 1",
        board_name: str = "",
    ) -> dict:
        parent = {
            "name": self.PARENT,
            "subject": parent_subject,
            "description": "",
            "meta": parent_meta,
        }
        child = {
            "name": self.CHILD,
            "subject": child_subject,
            "description": "",
            "meta": child_meta,
        }
        return self.service._erp_idea_rule_card(
            parent,
            child,
            source_detail=child,
            source_task_id=self.CHILD,
            source_attachment_id="",
            board_name=board_name,
        )

    def test_parent_product_type_beats_an_uninformative_parent_title(self) -> None:
        card = self._card(parent_meta="product_type: Ornament Thêu Tròn")

        self.assertEqual("Ornament Thêu Tròn", card["name"])

    def test_child_product_type_beats_the_parent_product_type(self) -> None:
        card = self._card(
            parent_meta="product_type: Ornament Thêu Tròn",
            child_meta="product_type: Khăn Tay Thêu Tay",
        )

        self.assertEqual("Khăn Tay Thêu Tay", card["name"])

    def test_missing_product_type_keeps_the_existing_subject_fallback(self) -> None:
        card = self._card(child_subject="Idea XMAS Ornament Thêu Tròn")

        self.assertEqual("Idea XMAS Ornament Thêu Tròn", card["name"])


if __name__ == "__main__":
    unittest.main()

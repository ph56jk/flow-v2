"""TDD cho PRD ``tasks/prd-agent-improvements.md`` — phần chạy được bằng stdlib.

Những bài ở đây chỉ đụng ``agent_brain``/``agent_chat``/``agent_bot`` và văn
bản ``static/app.js``, nên chúng chạy được trên một máy chưa cài ``fastapi``
lẫn ``flow``:

    python3 -m unittest tests.test_agent_guardrails -v

Phần cần ``flow_web.service`` nằm ở ``tests/test_agent_improvements.py``.

**Mọi bài ở đây đang ĐỎ và phải đỏ**: chúng tả hành vi *sau* khi các mục
A8, A9, C3, C4 của PRD được cài, chứ không tả hành vi hôm nay.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from flow_web import agent_brain
from flow_web.agent_bot import AgentBot, AgentBotConfig, AgentBotState
from flow_web.agent_brain import BrainVerdict
from flow_web.agent_chat import CardBrief, addressed_to_bot

BOT = "agent-kin-test-agent@bots.hvg.internal"
APP_JS = Path(__file__).resolve().parent.parent / "flow_web" / "static" / "app.js"


class _Completed:
    """Cái ``subprocess.run`` trả về, đủ để ``_run_cli`` đọc xong."""

    returncode = 0
    stdout = '{"result": "{}"}'
    stderr = ""


class BrainSubprocessEnvTests(unittest.TestCase):
    """A8 — tiến trình con đoán ý không được mang theo chùm chìa khoá.

    ``_run_cli`` chạy vì **một bình luận trên thẻ ERP**, nội dung do người
    ngoài viết. Hôm nay nó lọc đúng tiền tố ``ERP_`` và đưa tất cả phần còn
    lại sang: khoá Gemini, token Telegram, khoá OpenAI/Anthropic, bí mật của
    runner. Khoá tay một tiến trình mà vẫn đưa nó cả chùm chìa thì hàng rào
    chỉ còn một lớp.
    """

    SECRETS = {
        "ERP_API_KEY": "erp-key",
        "GEMINI_API_KEY": "gemini-key",
        "GOOGLE_API_KEY": "google-key",
        "TELEGRAM_BOT_TOKEN": "telegram-token",
        "OPENAI_API_KEY": "openai-key",
        "ANTHROPIC_API_KEY": "anthropic-key",
        "RUNNER_SHARED_SECRET": "runner-secret",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "DB_PASSWORD": "db-password",
        "FLOW_CHROME_PROFILE": "profile-1",
    }

    def _env_handed_to_the_cli(self) -> Dict[str, str]:
        captured: Dict[str, Any] = {}

        def fake_run(argv, **kwargs):
            captured.update(kwargs)
            return _Completed()

        with patch.dict(os.environ, self.SECRETS, clear=False):
            with patch.object(agent_brain.subprocess, "run", side_effect=fake_run):
                agent_brain._run_cli(["claude", "-p"], "câu hỏi", timeout_s=5, cwd="")
        env = captured.get("env")
        self.assertIsInstance(env, dict, "_run_cli phải truyền env tường minh, không kế thừa cả tiến trình")
        return dict(env)

    def test_no_secret_shaped_variable_reaches_the_cli(self) -> None:
        # So sánh trên **tên** thôi. Đưa cả env vào câu lỗi thì mỗi lần bài này
        # đỏ là một lần bí mật thật của máy bị in ra log — đúng cái nó đang tố cáo.
        leaked = sorted(name for name in self.SECRETS if name in self._env_handed_to_the_cli())
        self.assertEqual(
            [],
            leaked,
            f"tiến trình con chạy theo lời một người lạ, không được mang theo: {leaked}",
        )

    def test_the_rule_is_by_shape_not_by_one_prefix(self) -> None:
        # Một biến chưa ai nghĩ tới hôm nay vẫn phải bị chặn vì *hình dạng*
        # tên nó, chứ không phải vì có người nhớ thêm nó vào danh sách.
        extra = {
            "SOME_NEW_API_KEY": "x",
            "VENDOR_TOKEN": "y",
            "SERVICE_PASSWORD": "z",
            "APP_CLIENT_SECRET": "w",
        }
        with patch.dict(os.environ, extra, clear=False):
            env = self._env_handed_to_the_cli()
        leaked = sorted(name for name in extra if name in env)
        self.assertEqual([], leaked, f"những tên này có hình dạng của một bí mật: {leaked}")

    def test_the_cli_still_gets_what_it_needs_to_run(self) -> None:
        # Gỡ quá tay cũng là một cách làm hỏng: không có PATH thì không tìm
        # thấy lệnh, và mỗi câu khó hiểu thành một lần chờ hết giờ.
        env = self._env_handed_to_the_cli()
        self.assertIn("PATH", env)
        self.assertEqual(os.environ["PATH"], env["PATH"])

    def test_the_kept_names_are_one_named_list(self) -> None:
        # Danh sách rải rác trong thân hàm là danh sách sẽ trôi. PRD A8.2 đòi
        # một hằng số có tên để người sau đọc được nó ở một chỗ.
        allow = getattr(agent_brain, "CLI_ENV_ALLOWLIST", None)
        self.assertIsNotNone(allow, "agent_brain phải công bố CLI_ENV_ALLOWLIST")
        self.assertIn("PATH", set(allow))


class BrainCallBudgetTests(unittest.TestCase):
    """A9 — trần hỏi model phải sống lâu hơn một vòng quét.

    ``brain_max_calls`` bị đặt lại về 0 ở đầu mỗi vòng quét, mà vòng quét chạy
    mỗi ~3 phút. Trần thật vì thế là 5 × 20 = 100 lượt CLI mỗi giờ, không trần
    ngày, không đếm chi phí.
    """

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.calls: List[str] = []

        def hook(said: str, brief: CardBrief) -> BrainVerdict | None:
            self.calls.append(said)
            return None

        self.hook = hook
        self.brief = CardBrief(task="TASK-1", title="thẻ", status="Open")

    def _bot(self, **overrides: Any) -> AgentBot:
        config = AgentBotConfig(token="t0ken", bot_user=BOT)
        return AgentBot(
            config,
            client=object(),
            state=AgentBotState.load(Path(self.tempdir.name) / "state.json"),
            brain_hook=self.hook,
            brain_max_calls=2,
            **overrides,
        )

    def test_the_per_round_ceiling_still_holds(self) -> None:
        # Không được đánh đổi: trần cũ phải nguyên vẹn dưới trần mới.
        bot = self._bot()
        for _ in range(5):
            bot._guess_harder("câu lạ", self.brief)
        self.assertEqual(2, len(self.calls))

    def test_the_ceiling_survives_the_next_scan_round(self) -> None:
        bot = self._bot(brain_max_calls_per_hour=3)
        for _round in range(4):
            bot._brain_calls = 0  # đúng cái mà run_once làm ở đầu mỗi vòng
            for _ in range(5):
                bot._guess_harder("câu lạ", self.brief)
        self.assertEqual(
            3,
            len(self.calls),
            "trần giờ phải chặn được, nếu không thì mỗi vòng quét lại mở lại ví",
        )

    def test_a_daily_ceiling_exists_on_top_of_the_hourly_one(self) -> None:
        bot = self._bot(brain_max_calls_per_hour=100, brain_max_calls_per_day=4)
        for _round in range(10):
            bot._brain_calls = 0
            for _ in range(5):
                bot._guess_harder("câu lạ", self.brief)
        self.assertEqual(4, len(self.calls))

    def test_the_counters_are_kept_on_the_state_file(self) -> None:
        # Trần chỉ sống trong bộ nhớ là trần bị xoá mỗi lần khởi động lại, mà
        # khởi động lại là chuyện thường trên máy trung tâm.
        state = AgentBotState.load(Path(self.tempdir.name) / "state.json")
        self.assertTrue(
            hasattr(state, "brain_calls"),
            "AgentBotState phải giữ số lượt đã hỏi để nó sống qua khởi động lại",
        )


class BotObeysOnlyAllowedAuthorsTests(unittest.TestCase):
    """C3 — không phải ai bình luận được cũng ra lệnh được.

    ``addressed_to_bot`` hôm nay chỉ loại bình luận của chính bot và của bot
    khác. Không có lớp "ai được nói". Ai bình luận được lên thẻ là ép chạy lại
    automation, ghi thuộc tính lên thẻ, đánh số lại SKU cả cây, và làm bot chạy
    một CLI model trên máy trung tâm.
    """

    ALLOWED = ("sep@havigroup.vn", "ketoan@havigroup.vn")

    # "@bot ..." chứ không phải "kin ...": không có chữ gọi tên thì
    # ``addressed_to_bot`` trả ``False`` cho cả người trong lẫn người ngoài danh
    # sách, và câu phủ định dưới kia xanh vì một lý do chẳng liên quan gì tới
    # hàng rào tác giả.  Sửa fixture để câu ấy *thật sự* đo được C3.
    def _comment(self, content: str = "@bot ơi chạy đi", **overrides: Any) -> Dict[str, Any]:
        base = {
            "name": "cmt-1",
            "owner": "sep@havigroup.vn",
            "mine": 0,
            "is_bot": 0,
            "content": content,
            "mentions": [],
        }
        base.update(overrides)
        return base

    def test_the_decision_is_a_plain_function(self) -> None:
        # Tách khỏi bot để test được và để đọc được: PRD C3.4.
        from flow_web.agent_chat import author_is_allowed

        self.assertTrue(author_is_allowed(self._comment(), self.ALLOWED))
        self.assertFalse(author_is_allowed(self._comment(owner="nguoila@example.com"), self.ALLOWED))

    def test_it_reads_every_shape_erp_returns_the_author_in(self) -> None:
        from flow_web.agent_chat import author_is_allowed

        for field in ("owner", "by_email", "email", "user"):
            with self.subTest(field=field):
                comment = self._comment()
                comment.pop("owner")
                comment[field] = "SEP@HaviGroup.VN"  # ERP trả hoa thường tuỳ đường đọc
                self.assertTrue(author_is_allowed(comment, self.ALLOWED))

    def test_an_empty_list_keeps_todays_behaviour(self) -> None:
        # C3.2: khoá đột ngột làm bot câm trên một bảng đang chạy. Danh sách
        # trống nghĩa là chưa khoá, không phải khoá hết.
        from flow_web.agent_chat import author_is_allowed

        self.assertTrue(author_is_allowed(self._comment(owner="baicungduoc@example.com"), ()))

    def test_a_comment_with_no_author_is_refused_when_the_list_is_on(self) -> None:
        # C3.5 fail closed: thiếu thông tin tác giả trong lúc đang khoá thì
        # phải từ chối, vì cho qua nghĩa là bỏ trống hàng rào đúng lúc cần nó.
        from flow_web.agent_chat import author_is_allowed

        comment = self._comment()
        comment.pop("owner")
        self.assertFalse(author_is_allowed(comment, self.ALLOWED))

    def test_addressed_to_bot_honours_the_list(self) -> None:
        outsider = self._comment(owner="nguoila@example.com")
        self.assertFalse(
            addressed_to_bot(outsider, BOT, allowed_authors=self.ALLOWED),
            "người ngoài danh sách gọi tên bot vẫn không được coi là đang ra lệnh",
        )
        self.assertTrue(addressed_to_bot(self._comment(), BOT, allowed_authors=self.ALLOWED))

    def test_the_bot_stays_silent_rather_than_refusing_out_loud(self) -> None:
        # C3.3: trả lời một câu từ chối là xác nhận cho người lạ rằng bot có ở
        # đây và đang nghe. Im lặng, chỉ ghi log.
        from flow_web.agent_chat import author_is_allowed

        outsider = self._comment(owner="nguoila@example.com")
        self.assertFalse(author_is_allowed(outsider, self.ALLOWED))
        # Bot không được coi câu ấy là lời nói với mình, nên không có câu trả
        # lời nào để dựng. Đó là toàn bộ hàng rào: im, và ghi log.
        self.assertFalse(addressed_to_bot(outsider, BOT, allowed_authors=self.ALLOWED))


class ResetAutomationNeedsConfirmationTests(unittest.TestCase):
    """C4 (và C2.3) — hai nút không hoàn tác được phải hỏi lại.

    ``resetAutomationConfig`` xoá sạch graph automation người dùng đã dựng, và
    nút xoá khoá Gemini xoá thông tin xác thực. Cả hai nối thẳng vào nút, không
    ``window.confirm``, không đường hoàn tác.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP_JS.read_text(encoding="utf-8")

    def _body(self, opening: str, closing: str = "\n}\n") -> str:
        start = self.source.index(opening)
        end = self.source.index(closing, start)
        return self.source[start:end]

    def test_the_reset_asks_before_it_wipes(self) -> None:
        body = self._body("function resetAutomationConfig(")
        self.assertIn(
            "confirm(",
            body,
            "resetAutomationConfig xoá graph không hoàn tác được nên phải hỏi lại",
        )

    def test_the_reset_keeps_one_snapshot_to_undo_from(self) -> None:
        # C4.2: một bản chụp ngay trước khi xoá. Export có sẵn không cứu được
        # ai, vì không ai export trước một cú bấm nhầm.
        body = self._body("function resetAutomationConfig(")
        self.assertRegex(
            body,
            r"(undo|snapshot|hoanTac|backup)",
            "phải giữ một bản chụp để hoàn tác",
        )

    def test_clearing_the_api_key_asks_too(self) -> None:
        listener = self._body('elements.automationEnvClearButton?.addEventListener', "\n")
        self.assertIn("confirm", listener, "nút xoá khoá phải hỏi lại trước khi gửi")

    def test_the_clear_message_no_longer_claims_a_clean_delete(self) -> None:
        # C2.2: câu "Đã xóa Gemini key trong app." là sai trên máy có
        # .env.local — khoá vẫn sống qua fallback env.
        self.assertFalse(
            "Đã xóa Gemini key trong app." in self.source,
            "câu này hứa một việc app không làm được khi env còn khoá",
        )

    def test_only_two_confirms_is_no_longer_the_whole_story(self) -> None:
        # Ghim con số để lần sau ai gỡ một confirm đi thì bài này đỏ lên.
        confirms = len(re.findall(r"\bconfirm\s*\(", self.source))
        self.assertGreaterEqual(
            confirms,
            4,
            "hai nút không hoàn tác được ở trên phải thêm hai confirm nữa",
        )


if __name__ == "__main__":
    unittest.main()

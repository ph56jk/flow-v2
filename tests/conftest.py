"""Mặc định cho cả bộ test (mọi file, mọi lớp).

Đường tải 2K bằng giao diện Flow (FLOW_UI_UPSCALE_2K_ENABLED, đồng bộ từ 3 worker Trello
11/09/2026) mở trình duyệt thật; bật mặc định trong sản phẩm nhưng phải tắt trong test.
Bài nào cần bật thì tự ``patch.dict(os.environ, {"FLOW_UI_UPSCALE_2K_ENABLED": ""})``.
"""
import os

os.environ.setdefault("FLOW_UI_UPSCALE_2K_ENABLED", "0")


import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Không để test ghi cache Gemini (visual-rule-cache.json, gemini-usage.json) vào data/ thật.

    Cache phân loại/design inventory được ghi ra đĩa để sống qua khởi động lại; trong test
    nó làm bài sau đọc phải kết quả bài trước. Mỗi bài một thư mục riêng.
    """
    import flow_web.service as service_module

    monkeypatch.setattr(service_module, "DATA_DIR", tmp_path / "data", raising=False)
    service_module.FlowWebService._visual_rule_file_cache = None  # type: ignore[attr-defined]
    yield

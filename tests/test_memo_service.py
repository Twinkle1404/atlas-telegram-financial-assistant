"""
Tests for IC Research Memo generator.
"""
import os
from app.services import memo_service, memory_service, conversation_service


def test_export_research_memo_generates_md_file(mocker):
    mocker.patch(
        "app.ai.claude_client.simple_complete",
        return_value="# INVESTMENT COMMITTEE RESEARCH MEMO: AAPL\n\n### 1. Executive Summary\n- Strong thesis."
    )

    user = memory_service.get_or_create_user("test_memo_user", "Tester", "tester")
    conversation_service.log_message(user.id, "user", "Compare AAPL and MSFT")

    result = memo_service.export_research_memo(user.id, "AAPL")

    assert result["status"] == "exported"
    assert result["filename"].startswith("IC_Memo_AAPL_")
    assert os.path.exists(result["file_path"])

    with open(result["file_path"], "r", encoding="utf-8") as f:
        content = f.read()

    assert "INVESTMENT COMMITTEE RESEARCH MEMO: AAPL" in content

    # Cleanup
    if os.path.exists(result["file_path"]):
        os.remove(result["file_path"])

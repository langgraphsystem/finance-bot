from src.core.models.conversation import ConversationMessage
from src.core.models.document import Document
from src.core.models.session_summary import SessionSummary
from src.core.models.task import Task
from src.core.models.transaction import Transaction


def test_transaction_has_visibility():
    columns = {c.name for c in Transaction.__table__.columns}
    assert "visibility" in columns


def test_task_has_visibility():
    columns = {c.name for c in Task.__table__.columns}
    assert "visibility" in columns


def test_document_has_visibility():
    columns = {c.name for c in Document.__table__.columns}
    assert "visibility" in columns


def test_conversation_message_has_visibility():
    columns = {c.name for c in ConversationMessage.__table__.columns}
    assert "visibility" in columns


def test_session_summary_has_visibility():
    columns = {c.name for c in SessionSummary.__table__.columns}
    assert "visibility" in columns

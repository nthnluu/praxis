"""Tests for AI Chat Service.

Uses the REAL Firestore emulator for persistence and unittest.mock
for OpenAI responses — the way you'd do it in production.

Requires:
    FIRESTORE_EMULATOR_HOST=localhost:8080 pytest examples/production/ai_chat_service/test_chat_service.py -v
"""

import os
import random
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import praxis
from examples.production.ai_chat_service.specs.spec_token_budget import TokenBudgetSpec
from examples.production.ai_chat_service.specs.spec_conversation import ConversationSpec

# Skip entire module if emulator is not running
pytestmark = pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST"),
    reason="Firestore emulator not running. Set FIRESTORE_EMULATOR_HOST=localhost:8080",
)


# ============================================================
# Fixtures
# ============================================================

def _mock_openai_response(content: str = "Mock response", prompt_tokens: int = 10,
                           completion_tokens: int = 8) -> dict:
    """Factory for OpenAI-shaped response dicts."""
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


@pytest.fixture
def service():
    """Create a ChatService with real Firestore (emulator) and mocked OpenAI."""
    from examples.production.ai_chat_service.app import (
        ChatService, FirestoreDB, FirebaseAuth, RateLimiter, OpenAIClient,
    )

    db = FirestoreDB(project_id="demo-praxis-test")

    # Mock the OpenAI client idiomatically
    openai_client = MagicMock(spec=OpenAIClient)
    openai_client.system_max_tokens = 4096
    openai_client.context_window_limit = 128_000
    openai_client.chat_completion = MagicMock(
        side_effect=lambda messages, max_tokens=1000: _mock_openai_response(
            content=f"Response to: {messages[-1]['content'][:30]}",
            prompt_tokens=sum(len(m['content'].split()) for m in messages),
            completion_tokens=min(10, max_tokens),
        )
    )

    # Mock Firebase Auth — treat token as uid
    auth = MagicMock(spec=FirebaseAuth)
    auth.verify_token = MagicMock(
        side_effect=lambda token: {"uid": token, "email": f"{token}@test.com"}
    )

    rate_limiter = RateLimiter(max_rpm=1000, max_tpm=1_000_000)
    svc = ChatService(db, openai_client, auth, rate_limiter)
    return svc, db


# ============================================================
# Tests
# ============================================================

def test_send_message_round_trip(service):
    """Send a message, verify it persists in Firestore."""
    svc, db = service
    uid = f"user-{uuid.uuid4().hex[:8]}"
    user = db.create_user(uid, f"{uid}@test.com", daily_limit=50_000)

    result = svc.send_message(user, None, "Hello, world!", max_tokens=100)

    assert result["response"].startswith("Response to:")
    assert result["tokens_used"] > 0
    assert result["message_count"] == 2

    # Verify persistence in Firestore
    conv = db.get_conversation(result["conversation_id"])
    assert conv is not None
    assert conv.message_count == 2
    assert conv.messages[0].role == "user"
    assert conv.messages[1].role == "assistant"


def test_conversation_continuity(service):
    """Multiple messages in the same conversation persist correctly."""
    svc, db = service
    uid = f"user-{uuid.uuid4().hex[:8]}"
    user = db.create_user(uid, f"{uid}@test.com")

    r1 = svc.send_message(user, None, "First message", max_tokens=50)
    user = db.get_user(uid)
    r2 = svc.send_message(user, r1["conversation_id"], "Second message", max_tokens=50)
    assert r2["message_count"] == 4

    conv = db.get_conversation(r1["conversation_id"])
    assert conv.message_count == 4


def test_ownership_enforcement(service):
    """Users cannot access each other's conversations."""
    svc, db = service
    alice = db.create_user(f"alice-{uuid.uuid4().hex[:8]}", "alice@test.com")
    bob = db.create_user(f"bob-{uuid.uuid4().hex[:8]}", "bob@test.com")

    result = svc.send_message(alice, None, "Alice's message", max_tokens=50)

    with pytest.raises(HTTPException) as exc_info:
        svc.send_message(bob, result["conversation_id"], "Bob intrudes", max_tokens=50)
    assert exc_info.value.status_code == 403


def test_daily_token_limit(service):
    """Cannot exceed daily token budget."""
    svc, db = service
    uid = f"user-{uuid.uuid4().hex[:8]}"
    user = db.create_user(uid, f"{uid}@test.com", daily_limit=100)

    svc.send_message(user, None, "Hello", max_tokens=50)
    user = db.get_user(uid)

    with pytest.raises(HTTPException) as exc_info:
        svc.send_message(user, None, "More", max_tokens=200)
    assert exc_info.value.status_code == 429


def test_close_conversation(service):
    """Closed conversations reject new messages."""
    svc, db = service
    uid = f"user-{uuid.uuid4().hex[:8]}"
    user = db.create_user(uid, f"{uid}@test.com")

    result = svc.send_message(user, None, "Hello", max_tokens=50)
    conv_id = result["conversation_id"]

    user = db.get_user(uid)
    svc.close_conversation(user, conv_id)

    conv = db.get_conversation(conv_id)
    assert not conv.is_active

    user = db.get_user(uid)
    with pytest.raises(HTTPException) as exc_info:
        svc.send_message(user, conv_id, "Should fail", max_tokens=50)
    assert exc_info.value.status_code == 400


def test_token_budget_fuzz(service):
    """Fuzz: random message sequences never exceed daily token limit."""
    svc, db = service
    uid = f"fuzz-{uuid.uuid4().hex[:8]}"
    db.create_user(uid, f"{uid}@test.com", daily_limit=10_000)

    result = praxis.fuzz(
        svc, TokenBudgetSpec,
        state_extractor=lambda s: {
            "tokens_used_today": (u := db.get_user(uid)).tokens_used_today if db.get_user(uid) else 0,
            "daily_limit": u.daily_token_limit if db.get_user(uid) else 10000,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        },
        operations=[
            lambda s: s.send_message(db.get_user(uid), None, f"q{random.randint(1,100)}", max_tokens=100),
        ],
        iterations=50, seed=42,
    )
    assert result.passed, f"Token budget violated: {result}"


def test_conversation_tracking_fuzz(service):
    """Fuzz: message counts stay consistent in Firestore."""
    svc, db = service
    uid = f"conv-{uuid.uuid4().hex[:8]}"
    db.create_user(uid, f"{uid}@test.com")
    conv = db.create_conversation(uid)

    result = praxis.fuzz(
        svc, ConversationSpec,
        state_extractor=lambda s: {
            "message_count": (c := db.get_conversation(conv.id)).message_count if db.get_conversation(conv.id) else 0,
            "user_messages": sum(1 for m in c.messages if m.role == "user") if db.get_conversation(conv.id) else 0,
            "assistant_messages": sum(1 for m in c.messages if m.role == "assistant") if db.get_conversation(conv.id) else 0,
            "total_tokens": c.total_tokens if db.get_conversation(conv.id) else 0,
            "max_messages": 1000, "is_active": 1,
        },
        operations=[
            lambda s: s.send_message(db.get_user(uid), conv.id, f"m{random.randint(1,50)}", max_tokens=50),
        ],
        iterations=30, seed=42,
    )
    assert result.passed, f"Conversation tracking violated: {result}"

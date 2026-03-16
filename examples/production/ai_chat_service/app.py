"""AI Chat Service — FastAPI + Firebase Auth + Firestore + OpenAI.

Built spec-first. The six specs in specs/ were written before this file.
Every state mutation corresponds to a spec transition. Every guard
corresponds to a spec precondition. The specs ARE the architecture.

Setup:
    pip install firebase-admin openai fastapi uvicorn

Dev (emulator):
    firebase emulators:start --only firestore,auth --project demo-praxis
    FIRESTORE_EMULATOR_HOST=localhost:8080 uvicorn examples.production.ai_chat_service.app:app --reload

Production:
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json OPENAI_API_KEY=sk-... uvicorn ...
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

import firebase_admin
from firebase_admin import credentials, firestore, auth as firebase_auth_mod
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel

import praxis
from examples.production.ai_chat_service.specs.spec_token_budget import TokenBudgetSpec

logger = logging.getLogger("ai_chat_service")


# ============================================================
# Domain Models — serializable to/from Firestore documents
# ============================================================

@dataclass
class User:
    uid: str
    email: str
    tokens_used_today: int = 0
    daily_token_limit: int = 100_000
    conversations: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, uid: str, data: dict[str, Any]) -> User:
        return cls(
            uid=uid,
            email=data.get("email", ""),
            tokens_used_today=data.get("tokens_used_today", 0),
            daily_token_limit=data.get("daily_token_limit", 100_000),
            conversations=data.get("conversations", []),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class Message:
    role: str
    content: str
    tokens: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        return cls(
            role=data["role"],
            content=data["content"],
            tokens=data.get("tokens", 0),
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class Conversation:
    id: str
    user_uid: str
    messages: list[Message] = field(default_factory=list)
    total_tokens: int = 0
    max_messages: int = 1000
    is_active: bool = True
    created_at: float = field(default_factory=time.time)

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def user_message_count(self) -> int:
        return sum(1 for m in self.messages if m.role == "user")

    @property
    def assistant_message_count(self) -> int:
        return sum(1 for m in self.messages if m.role == "assistant")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_uid": self.user_uid,
            "messages": [m.to_dict() for m in self.messages],
            "total_tokens": self.total_tokens,
            "max_messages": self.max_messages,
            "is_active": self.is_active,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, conv_id: str, data: dict[str, Any]) -> Conversation:
        return cls(
            id=conv_id,
            user_uid=data["user_uid"],
            messages=[Message.from_dict(m) for m in data.get("messages", [])],
            total_tokens=data.get("total_tokens", 0),
            max_messages=data.get("max_messages", 1000),
            is_active=data.get("is_active", True),
            created_at=data.get("created_at", time.time()),
        )


# ============================================================
# Firestore — always uses the real SDK (emulator or production)
# ============================================================

class FirestoreDB:
    """Firestore storage layer. Uses the real firebase-admin SDK.

    For local development, point at the emulator:
        FIRESTORE_EMULATOR_HOST=localhost:8080

    For production, provide credentials:
        GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
    """

    def __init__(self, project_id: str = "demo-praxis"):
        from google.cloud.firestore_v1 import Client as FirestoreClient

        if os.environ.get("FIRESTORE_EMULATOR_HOST"):
            # Emulator mode: use google-cloud-firestore directly with no auth
            from google.auth.credentials import AnonymousCredentials
            self._db = FirestoreClient(
                project=project_id,
                credentials=AnonymousCredentials(),
            )
            logger.info("FirestoreDB: connected to emulator at %s",
                        os.environ["FIRESTORE_EMULATOR_HOST"])
        else:
            # Production mode: use firebase-admin with real credentials
            if firebase_admin._apps:
                firebase_admin.delete_app(firebase_admin.get_app())
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
            self._db = firestore.client()
            logger.info("FirestoreDB: connected to production Firestore")

    def get_user(self, uid: str) -> User | None:
        doc = self._db.collection("users").document(uid).get()
        if not doc.exists:
            return None
        return User.from_dict(uid, doc.to_dict())

    def create_user(self, uid: str, email: str, daily_limit: int = 100_000) -> User:
        user = User(uid=uid, email=email, daily_token_limit=daily_limit)
        self._db.collection("users").document(uid).set(user.to_dict())
        return user

    def update_user(self, user: User) -> None:
        self._db.collection("users").document(user.uid).set(user.to_dict())

    def get_conversation(self, conv_id: str) -> Conversation | None:
        doc = self._db.collection("conversations").document(conv_id).get()
        if not doc.exists:
            return None
        return Conversation.from_dict(conv_id, doc.to_dict())

    def create_conversation(self, user_uid: str) -> Conversation:
        conv = Conversation(id=uuid.uuid4().hex[:16], user_uid=user_uid)
        self._db.collection("conversations").document(conv.id).set(conv.to_dict())
        return conv

    def update_conversation(self, conv: Conversation) -> None:
        self._db.collection("conversations").document(conv.id).set(conv.to_dict())


# ============================================================
# Firebase Auth — real token verification
# ============================================================

class FirebaseAuth:
    """Firebase Auth token verifier. Uses the real firebase-admin SDK."""

    def verify_token(self, token: str) -> dict[str, str]:
        try:
            decoded = firebase_auth_mod.verify_id_token(token)
            return {"uid": decoded["uid"], "email": decoded.get("email", "")}
        except firebase_auth_mod.InvalidIdTokenError as exc:
            raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
        except firebase_auth_mod.ExpiredIdTokenError as exc:
            raise HTTPException(status_code=401, detail=f"Expired token: {exc}")
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"Auth error: {exc}")


# ============================================================
# OpenAI Client — real SDK, mock via unittest.mock in tests
# ============================================================

class OpenAIClient:
    """OpenAI API client. Uses the real openai SDK.

    In tests, mock this with unittest.mock:
        with patch.object(openai_client, 'chat_completion', return_value={...}):
            ...
    """

    def __init__(self, api_key: str | None = None, model: str = "gpt-4"):
        import openai
        self.model = model
        self.system_max_tokens = 4096
        self.context_window_limit = 128_000
        self._client = openai.OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY", ""))

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1000,
    ) -> dict[str, Any]:
        effective_max = min(max_tokens, self.system_max_tokens)
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=effective_max,
        )
        return {
            "choices": [{"message": {
                "role": "assistant",
                "content": response.choices[0].message.content,
            }}],
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }


# ============================================================
# Rate Limiter
# ============================================================

class RateLimiter:
    def __init__(self, max_rpm: int = 60, max_tpm: int = 100_000):
        self.max_requests_per_minute = max_rpm
        self.max_tokens_per_minute = max_tpm
        self._windows: dict[str, dict] = {}

    def _get_window(self, uid: str) -> dict:
        now = time.time()
        w = self._windows.get(uid)
        if w is None or now - w["start"] >= 60:
            w = {"start": now, "requests": 0, "tokens": 0}
            self._windows[uid] = w
        return w

    def check_and_consume(self, uid: str, estimated_tokens: int) -> None:
        w = self._get_window(uid)
        if w["requests"] + 1 > self.max_requests_per_minute:
            raise HTTPException(status_code=429, detail="Rate limit: too many requests")
        if w["tokens"] + estimated_tokens > self.max_tokens_per_minute:
            raise HTTPException(status_code=429, detail="Rate limit: token volume exceeded")
        w["requests"] += 1
        w["tokens"] += estimated_tokens


# ============================================================
# Chat Service
# ============================================================

class ChatService:
    def __init__(self, db: FirestoreDB, openai: OpenAIClient, auth: FirebaseAuth,
                 rate_limiter: RateLimiter | None = None):
        self.db = db
        self.openai = openai
        self.auth = auth
        self.rate_limiter = rate_limiter or RateLimiter()

    def authenticate(self, token: str) -> User:
        decoded = self.auth.verify_token(token)
        uid = decoded["uid"]
        user = self.db.get_user(uid)
        if user is None:
            user = self.db.create_user(uid, decoded.get("email", ""))
        return user

    def send_message(self, user: User, conversation_id: str | None,
                     content: str, max_tokens: int = 1000) -> dict[str, Any]:
        self.rate_limiter.check_and_consume(user.uid, max_tokens)

        if user.tokens_used_today + max_tokens > user.daily_token_limit:
            raise HTTPException(status_code=429, detail={
                "error": "Daily token limit exceeded",
                "used": user.tokens_used_today,
                "limit": user.daily_token_limit,
            })

        if conversation_id:
            conv = self.db.get_conversation(conversation_id)
            if conv is None:
                raise HTTPException(status_code=404, detail="Conversation not found")
            if conv.user_uid != user.uid:
                raise HTTPException(status_code=403, detail="Not your conversation")
        else:
            conv = self.db.create_conversation(user.uid)
            user.conversations.append(conv.id)

        if not conv.is_active:
            raise HTTPException(status_code=400, detail="Conversation is closed")
        if conv.message_count + 2 > conv.max_messages:
            raise HTTPException(status_code=400, detail="Conversation size limit reached")

        user_msg = Message(role="user", content=content, tokens=len(content.split()) * 2)
        conv.messages.append(user_msg)
        conv.total_tokens += user_msg.tokens

        api_messages = [{"role": m.role, "content": m.content} for m in conv.messages]
        response = self.openai.chat_completion(messages=api_messages, max_tokens=max_tokens)

        usage = response["usage"]
        assistant_msg = Message(
            role="assistant",
            content=response["choices"][0]["message"]["content"],
            tokens=usage["completion_tokens"],
        )
        conv.messages.append(assistant_msg)
        conv.total_tokens += assistant_msg.tokens

        user.tokens_used_today += usage["total_tokens"]
        self.db.update_user(user)
        self.db.update_conversation(conv)

        return {
            "conversation_id": conv.id,
            "response": assistant_msg.content,
            "tokens_used": usage["total_tokens"],
            "tokens_remaining": user.daily_token_limit - user.tokens_used_today,
            "message_count": conv.message_count,
        }

    def get_conversation_history(self, user: User, conversation_id: str) -> dict:
        conv = self.db.get_conversation(conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if conv.user_uid != user.uid:
            raise HTTPException(status_code=403, detail="Not your conversation")
        return {
            "id": conv.id,
            "messages": [{"role": m.role, "content": m.content, "tokens": m.tokens} for m in conv.messages],
            "total_tokens": conv.total_tokens,
            "message_count": conv.message_count,
        }

    def close_conversation(self, user: User, conversation_id: str) -> dict:
        conv = self.db.get_conversation(conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if conv.user_uid != user.uid:
            raise HTTPException(status_code=403, detail="Not your conversation")
        conv.is_active = False
        self.db.update_conversation(conv)
        return {"id": conv.id, "is_active": False}


# ============================================================
# FastAPI Application — lazy initialization
# ============================================================

# Services are initialized lazily, not at import time.
# This allows tests to import the module without needing Firestore/OpenAI.
db: FirestoreDB | None = None
openai_client: OpenAIClient | None = None
firebase_auth_instance: FirebaseAuth | None = None
rate_limiter: RateLimiter | None = None
chat_service: ChatService | None = None


def _init_services():
    """Initialize services. Called on first request or explicitly."""
    global db, openai_client, firebase_auth_instance, rate_limiter, chat_service
    if chat_service is not None:
        return
    db = FirestoreDB()
    openai_client = OpenAIClient()
    firebase_auth_instance = FirebaseAuth()
    rate_limiter = RateLimiter()
    chat_service = ChatService(db, openai_client, firebase_auth_instance, rate_limiter)


app = FastAPI(title="AI Chat Service", version="2.0.0")


@app.on_event("startup")
async def startup():
    _init_services()


class SendMessageRequest(BaseModel):
    content: str
    conversation_id: str | None = None
    max_tokens: int = 1000


async def get_current_user(authorization: str = Header(...)) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    return chat_service.authenticate(authorization.replace("Bearer ", ""))


@app.post("/chat")
async def send_message(request: SendMessageRequest, user: User = Depends(get_current_user)):
    return chat_service.send_message(user, request.conversation_id, request.content, request.max_tokens)


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, user: User = Depends(get_current_user)):
    return chat_service.get_conversation_history(user, conversation_id)


@app.post("/conversations/{conversation_id}/close")
async def close_conversation(conversation_id: str, user: User = Depends(get_current_user)):
    return chat_service.close_conversation(user, conversation_id)


@app.get("/usage")
async def get_usage(user: User = Depends(get_current_user)):
    return {
        "tokens_used_today": user.tokens_used_today,
        "daily_limit": user.daily_token_limit,
        "tokens_remaining": user.daily_token_limit - user.tokens_used_today,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}

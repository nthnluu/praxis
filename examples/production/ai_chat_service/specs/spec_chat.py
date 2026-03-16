"""Specs for the AI Chat Service — index module.

Six specs covering the critical invariants of a production chat service.
Each spec is defined in its own file for readability:

1. AuthSpec           — authentication and authorization
2. TokenBudgetSpec    — token usage and billing
3. ConversationSpec   — conversation lifecycle and integrity
4. RateLimitSpec      — API rate limiting
5. APISafetySpec      — OpenAI API call validation
6. DataIntegritySpec  — Firestore write consistency

This module re-exports the two specs used by the legacy API surface
(ChatServiceSpec, ConversationSpec) and exposes all six for new code.
"""

from examples.production.ai_chat_service.specs.spec_auth import AuthSpec
from examples.production.ai_chat_service.specs.spec_token_budget import TokenBudgetSpec
from examples.production.ai_chat_service.specs.spec_conversation import ConversationSpec
from examples.production.ai_chat_service.specs.spec_rate_limit import RateLimitSpec
from examples.production.ai_chat_service.specs.spec_api_safety import APISafetySpec
from examples.production.ai_chat_service.specs.spec_data_integrity import DataIntegritySpec

# Legacy alias — old imports reference ChatServiceSpec
ChatServiceSpec = TokenBudgetSpec

__all__ = [
    "AuthSpec",
    "TokenBudgetSpec",
    "ConversationSpec",
    "RateLimitSpec",
    "APISafetySpec",
    "DataIntegritySpec",
    "ChatServiceSpec",
]

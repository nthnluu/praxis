# AI Chat Service — Spec-First Design

This service was built spec-first. The specs were written before the implementation. A human reads the specs and knows exactly what the system guarantees. An agent reads the specs and knows exactly what constraints to satisfy. The implementation is a detail.

## Architecture

```
Client -> FastAPI -> Firebase Auth (verify token)
                  -> ChatService (business logic)
                      -> RateLimiter (per-user throttling)
                      -> OpenAI API (generate response)
                      -> Firestore (persist state)
                      -> Praxis (verify invariants)
```

## The Six Specs

### 1. AuthSpec — Authentication and Authorization
**File:** `specs/spec_auth.py`

Guarantees:
- A valid session implies the user exists
- Conversation access requires both valid session and ownership
- Transitions: `authenticate`, `validate_session`, `check_ownership`, `invalidate_session`

### 2. TokenBudgetSpec — Token Usage and Billing
**File:** `specs/spec_token_budget.py`

Guarantees:
- `tokens_used_today` never exceeds `daily_limit`
- `total_tokens == prompt_tokens + completion_tokens` (accounting identity)
- All token counts are non-negative
- Transitions: `consume_tokens`, `reset_daily_usage`

### 3. ConversationSpec — Conversation Lifecycle
**File:** `specs/spec_conversation.py`

Guarantees:
- `message_count == user_messages + assistant_messages`
- Message count never exceeds `max_messages`
- Token count never goes negative
- Closed conversations reject new messages
- Transitions: `add_user_message`, `add_assistant_response`, `close_conversation`

### 4. RateLimitSpec — API Rate Limiting
**File:** `specs/spec_rate_limit.py`

Guarantees:
- `requests_this_minute <= max_requests_per_minute`
- `tokens_this_minute <= max_tokens_per_minute`
- Transitions: `allow_request`, `reset_window`

### 5. APISafetySpec — OpenAI API Call Validation
**File:** `specs/spec_api_safety.py`

Guarantees:
- `max_tokens_requested <= system_max_tokens`
- Never send an empty message list
- `context_window_tokens <= context_window_limit`
- Transitions: `prepare_api_call`, `validate_request`

### 6. DataIntegritySpec — Firestore Write Consistency
**File:** `specs/spec_data_integrity.py`

Guarantees:
- Tokens are never charged without recording the update
- Token delta on user record matches token delta on conversation record
- Transitions: `begin_transaction`, `commit_user`, `commit_conversation`, `rollback`

## The Fuzz Testing Pattern

Each spec has a corresponding fuzz test in `test_chat_service.py`. The pattern:

```python
result = praxis.fuzz(
    service,
    TokenBudgetSpec,
    state_extractor=lambda s: {
        "tokens_used_today": db.get_user(uid).tokens_used_today,
        "daily_limit": db.get_user(uid).daily_token_limit,
        "prompt_tokens": ...,
        "completion_tokens": ...,
        "total_tokens": ...,
    },
    operations=[
        lambda s: s.send_message(user, None, "hello", max_tokens=100),
    ],
    iterations=200,
)
assert result.passed
```

The `state_extractor` maps real service state to spec state variables. `praxis.fuzz()` then verifies that every invariant holds after every operation.

## What Praxis Catches

### Broken: Token budget without check
`broken/spec_token_budget.py` — `consume_tokens` does not verify the budget before consuming:

```
INVARIANT VIOLATED: within_daily_limit
  tokens_used_today = 999990, daily_limit = 1000000
  After consume_tokens(prompt=8000, completion=5000):
    tokens_used_today' = 1012990 > daily_limit
```

### Broken: Message count out of sync
`broken/spec_conversation.py` — `add_user_message` increments `user_messages` but forgets `message_count`:

```
INVARIANT VIOLATED: count_consistent
  message_count = 0, user_messages = 1, assistant_messages = 0
  message_count (0) != user_messages + assistant_messages (1)
```

## Run It

```bash
# Verify specs are sound
praxis check examples/production/ai_chat_service/specs/

# Fuzz test the real service
pytest examples/production/ai_chat_service/test_chat_service.py -v

# Catch the bugs in broken specs
praxis check examples/production/ai_chat_service/broken/

# Run the FastAPI server (demo mode)
pip install fastapi uvicorn
uvicorn examples.production.ai_chat_service.app:app --reload
```

"""OpenAI API Call Validation Spec.

Proves:
- max_tokens requested is always positive and within system limits
- Never send an empty message list to the API
- Context window is never exceeded
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, PosInt
from praxis.decorators import require


class APISafetySpec(Spec):
    """Validates every outbound OpenAI API call before it's made."""

    max_tokens_requested: BoundedInt[0, 100000]    # 0 = no request yet
    system_max_tokens: BoundedInt[1, 100000]       # hard cap
    message_count_in_request: BoundedInt[0, 10000]
    context_window_tokens: BoundedInt[0, 200000]
    context_window_limit: BoundedInt[1, 200000]

    @invariant
    def max_tokens_within_system_cap(self):
        """Requested max_tokens never exceeds system cap."""
        return self.max_tokens_requested <= self.system_max_tokens

    @invariant
    def context_within_limit(self):
        """Total context never exceeds the model's window."""
        return self.context_window_tokens <= self.context_window_limit

    @transition
    def prepare_api_call(self, max_tokens: BoundedInt[1, 100000], msg_count: BoundedInt[1, 10000], ctx_tokens: BoundedInt[1, 200000]):
        """Validate and prepare an API call."""
        require(max_tokens <= self.system_max_tokens)
        require(msg_count > 0)
        require(ctx_tokens <= self.context_window_limit)
        self.max_tokens_requested = max_tokens
        self.message_count_in_request = msg_count
        self.context_window_tokens = ctx_tokens

    @transition
    def validate_request(self):
        """Final check before sending — all fields must be valid."""
        require(self.max_tokens_requested > 0)
        require(self.max_tokens_requested <= self.system_max_tokens)
        require(self.message_count_in_request > 0)
        require(self.context_window_tokens <= self.context_window_limit)

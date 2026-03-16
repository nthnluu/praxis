"""AST extraction — pulls structured data from Spec subclasses."""

from __future__ import annotations

import ast
import inspect
import textwrap
from dataclasses import dataclass
from typing import Any


@dataclass
class ExtractedInvariant:
    """An extracted invariant with its name, source, and AST."""
    name: str
    source: str
    ast_node: ast.FunctionDef
    message: str | None = None


@dataclass
class TransitionParam:
    """A parameter to a transition method."""
    name: str
    annotation: Any  # The Praxis type


@dataclass
class ExtractedTransition:
    """An extracted transition with its name, params, source, and AST."""
    name: str
    params: list[TransitionParam]
    source: str
    ast_node: ast.FunctionDef


@dataclass
class ExtractedInitial:
    """An extracted initial state predicate with its name, source, and AST."""
    name: str
    source: str
    ast_node: ast.FunctionDef


@dataclass
class ExtractedSpec:
    """All extracted data from a Spec subclass."""
    name: str
    state_fields: dict[str, Any]
    invariants: list[ExtractedInvariant]
    transitions: list[ExtractedTransition]
    initials: list[ExtractedInitial] = None

    def __post_init__(self):
        if self.initials is None:
            self.initials = []


def _get_method_ast(method: Any) -> tuple[str, ast.FunctionDef]:
    """Get the source code and parsed AST of a method."""
    source = textwrap.dedent(inspect.getsource(method))
    tree = ast.parse(source)
    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)
    return source, func_def


def extract_spec(spec_cls) -> ExtractedSpec:
    """Extract structured data from a Spec subclass.

    Returns state fields, invariants with ASTs, and transitions with
    parameter annotations and ASTs.
    """
    state_fields = spec_cls.state_fields()

    invariants = []
    for method in spec_cls.invariants():
        source, ast_node = _get_method_ast(method)
        invariants.append(ExtractedInvariant(
            name=method.__name__,
            source=source,
            ast_node=ast_node,
            message=getattr(method, '_praxis_invariant_message', None) or method.__doc__,
        ))

    transitions = []
    for method in spec_cls.transitions():
        source, ast_node = _get_method_ast(method)

        # Extract parameter annotations (skip 'self')
        params = []
        hints = method.__annotations__ if hasattr(method, '__annotations__') else {}
        sig = inspect.signature(method)
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            ann = hints.get(param_name)
            params.append(TransitionParam(name=param_name, annotation=ann))

        transitions.append(ExtractedTransition(
            name=method.__name__,
            params=params,
            source=source,
            ast_node=ast_node,
        ))

    initials = []
    for method in spec_cls.initials():
        source, ast_node = _get_method_ast(method)
        initials.append(ExtractedInitial(
            name=method.__name__,
            source=source,
            ast_node=ast_node,
        ))

    return ExtractedSpec(
        name=spec_cls.__name__,
        state_fields=state_fields,
        invariants=invariants,
        transitions=transitions,
        initials=initials,
    )

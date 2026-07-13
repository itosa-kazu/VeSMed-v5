"""冻结的、非图灵完备的数值表达式 IR。

模型模块不能跨 API 传 Python callback、SQL、prompt 或可执行字符串。表达式只由
下列封闭 opcode 构成；未知 opcode 必须失败。宏展开后的每个节点均计入 primitive/
authoring burden。
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log
from typing import Any, Mapping

from .contract import ContractError, validate_json_like


ALLOWED_OPS = frozenset(
    {
        "const",
        "var",
        "add",
        "sub",
        "mul",
        "div",
        "neg",
        "exp",
        "log",
        "logistic",
        "min",
        "max",
        "pow",
        "clamp",
        "if_gt",
    }
)

MAX_EXPR_DEPTH = 64
MAX_EXPR_NODES = 4_096


@dataclass(frozen=True)
class Expr:
    op: str
    args: tuple["Expr", ...] = ()
    value: float | str | None = None

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def from_data(cls, data: Mapping[str, Any] | int | float) -> "Expr":
        if cls is not Expr:
            raise ContractError("Expr.from_data 不允许通过子类构造")
        # Validate the whole transport tree before reading mapping methods or
        # recursively constructing nodes.  Each Expr adds a dict+args layer, so
        # the transport depth budget is twice the semantic depth budget.
        validate_json_like(
            data,
            label="expression",
            max_depth=MAX_EXPR_DEPTH * 2 + 4,
            max_nodes=MAX_EXPR_NODES * 8,
            max_bytes=1_048_576,
        )

        built_nodes = 0

        def build(item: Any, depth: int) -> "Expr":
            nonlocal built_nodes
            if depth > MAX_EXPR_DEPTH:
                raise ContractError(f"expression 超过 depth budget={MAX_EXPR_DEPTH}")
            built_nodes += 1
            if built_nodes > MAX_EXPR_NODES:
                raise ContractError(f"expression 超过 node budget={MAX_EXPR_NODES}")
            if type(item) in {int, float}:
                return Expr("const", value=float(item))
            if type(item) is not dict:
                raise ContractError("expression 必须是 exact dict 或 number")
            unknown: list[str] = []
            for key in dict.keys(item):
                if key not in {"op", "args", "value"}:
                    unknown.append(key)
            if unknown:
                raise ContractError(f"expression 未知字段: {sorted(unknown)}")
            op = dict.get(item, "op")
            if type(op) is not str or op not in ALLOWED_OPS:
                raise ContractError(f"未知 expression opcode: {op!r}")
            raw_args = dict.get(item, "args", ())
            if type(raw_args) not in {list, tuple}:
                raise ContractError("expression.args 必须是 exact list/tuple")
            args = tuple(build(raw_args[index], depth + 1) for index in range(len(raw_args)))
            return Expr(op, args, dict.get(item, "value"))

        expr = build(data, 0)
        expr.validate()
        return expr

    def validate(self) -> None:
        if type(self) is not Expr:
            raise ContractError("expression 节点必须是 exact Expr，不接受子类")
        arities = {
            "const": 0,
            "var": 0,
            "neg": 1,
            "exp": 1,
            "log": 1,
            "logistic": 1,
            "add": 2,
            "sub": 2,
            "mul": 2,
            "div": 2,
            "min": 2,
            "max": 2,
            "pow": 2,
            "clamp": 3,
            "if_gt": 4,
        }
        nodes = 0
        stack: list[tuple[Expr, int]] = [(self, 0)]
        while stack:
            node, depth = stack.pop()
            if type(node) is not Expr:
                raise ContractError("expression 子节点必须是 exact Expr")
            if depth > MAX_EXPR_DEPTH:
                raise ContractError(f"expression 超过 depth budget={MAX_EXPR_DEPTH}")
            nodes += 1
            if nodes > MAX_EXPR_NODES:
                raise ContractError(f"expression 超过 node budget={MAX_EXPR_NODES}")
            if type(node.op) is not str or node.op not in arities:
                raise ContractError(f"未知 expression opcode: {node.op!r}")
            if type(node.args) is not tuple:
                raise ContractError("expression.args 必须是 exact tuple")
            arity = arities[node.op]
            if len(node.args) != arity:
                raise ContractError(f"{node.op} 需要 {arity} 个参数，实际 {len(node.args)}")
            if node.op == "const":
                if type(node.value) not in {int, float} or not isfinite(float(node.value)):
                    raise ContractError("const.value 必须是有限 exact number")
            elif node.op == "var":
                if type(node.value) is not str or not node.value:
                    raise ContractError("var.value 必须是非空 exact str 变量名")
            elif node.value is not None:
                raise ContractError(f"{node.op}.value 必须为 null")
            for child in node.args:
                if type(child) is not Expr:
                    raise ContractError("expression 子节点必须是 exact Expr")
                stack.append((child, depth + 1))

    def evaluate(self, env: Mapping[str, float]) -> float:
        self.validate()
        if type(env) is not dict:
            raise ContractError("expression env 必须是 exact dict")
        for key, value in dict.items(env):
            if type(key) is not str or type(value) not in {int, float} or not isfinite(float(value)):
                raise ContractError("expression env 只接受 str -> finite exact number")

        def run(node: Expr) -> float:
            if node.op == "const":
                result = float(node.value)  # type: ignore[arg-type]
            elif node.op == "var":
                if node.value not in env:
                    raise ContractError(f"缺少变量: {node.value}")
                result = float(env[str(node.value)])
            else:
                xs = [run(arg) for arg in node.args]
                if node.op == "add":
                    result = xs[0] + xs[1]
                elif node.op == "sub":
                    result = xs[0] - xs[1]
                elif node.op == "mul":
                    result = xs[0] * xs[1]
                elif node.op == "div":
                    if xs[1] == 0:
                        raise ArithmeticError("division by zero")
                    result = xs[0] / xs[1]
                elif node.op == "neg":
                    result = -xs[0]
                elif node.op == "exp":
                    result = exp(xs[0])
                elif node.op == "log":
                    if xs[0] <= 0:
                        raise ArithmeticError("log domain")
                    result = log(xs[0])
                elif node.op == "logistic":
                    result = 1.0 / (1.0 + exp(-max(-700.0, min(700.0, xs[0]))))
                elif node.op == "min":
                    result = min(xs[0], xs[1])
                elif node.op == "max":
                    result = max(xs[0], xs[1])
                elif node.op == "pow":
                    result = xs[0] ** xs[1]
                elif node.op == "clamp":
                    result = max(xs[1], min(xs[2], xs[0]))
                elif node.op == "if_gt":
                    result = xs[2] if xs[0] > xs[1] else xs[3]
                else:  # pragma: no cover - validate makes this unreachable
                    raise ContractError(f"未知 opcode: {node.op}")
            if not isfinite(result):
                raise ArithmeticError(f"non-finite result from {node.op}")
            return result

        return run(self)

    def node_count(self) -> int:
        self.validate()
        count = 0
        stack = [self]
        while stack:
            node = stack.pop()
            count += 1
            stack.extend(node.args)
        return count

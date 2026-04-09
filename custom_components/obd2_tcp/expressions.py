"""Expression parser matching obd2-mqtt lib/ExprParser (ELMduino profile CALC)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from .const import PI


class ExprParserError(Exception):
    """Invalid expression."""


def _strcicmp(a: str, b: str) -> int:
    la = a.lower()
    lb = b.lower()
    if la < lb:
        return -1
    if la > lb:
        return 1
    return 0


class ExprParser:
    """Port of ExprParser.cpp evalExp / getToken / resolveVariables behavior."""

    DELIMITER = 1
    VARIABLE = 2
    NUMBER = 3
    FUNCTION = 4

    def __init__(self) -> None:
        self.vars: list[float] = [0.0] * 26
        self.custom_functions: dict[str, Callable[[float], float]] = {}
        self.var_resolve_function: Callable[[str], float] | None = None
        self.errormsg: str = ""
        self._exp_ptr: int = 0
        self._expression: str = ""
        self.token: str = ""
        self.tok_type: int = 0

    def set_variable(self, var: str, value: float) -> None:
        if len(var) == 1 and "A" <= var.upper() <= "Z":
            self.vars[ord(var.upper()) - ord("A")] = value

    def get_variable(self, var: str) -> float:
        if len(var) == 1 and "A" <= var.upper() <= "Z":
            return self.vars[ord(var.upper()) - ord("A")]
        return 0.0

    def add_custom_function(self, name: str, func: Callable[[float], float]) -> None:
        self.custom_functions[name.lower()] = func

    def set_custom_functions(self, funcs: Mapping[str, Callable[[float], float]]) -> None:
        for k, v in funcs.items():
            self.custom_functions[k.lower()] = v

    def set_variable_resolve_function(self, func: Callable[[str], float]) -> None:
        self.var_resolve_function = func

    def _resolve_variables(self, expression: str) -> str:
        if not expression or self.var_resolve_function is None:
            return expression

        parts: list[str] = []
        i = 0
        while i < len(expression):
            if expression[i] == "$":
                j = i + 1
                while j < len(expression):
                    c = expression[j]
                    if c.isspace() or c in "+-*/%^&|=(),":
                        break
                    j += 1
                raw = expression[i:j]
                try:
                    val = self.var_resolve_function(raw)
                except Exception:  # noqa: BLE001
                    val = 0.0
                parts.append(f"{val:.8g}")
                i = j
            else:
                parts.append(expression[i])
                i += 1
        return "".join(parts)

    def eval_exp(self, expression: str | None) -> float:
        self.errormsg = ""
        if not expression:
            self.errormsg = "No Expression Present"
            return 0.0

        self._expression = self._resolve_variables(expression)
        self._exp_ptr = 0
        self._get_token()
        if not self.token:
            self.errormsg = "No Expression Present"
            return 0.0

        result = self._eval_exp1()
        if self.token:
            self.errormsg = "Syntax Error"
        return result

    def _eval_exp1(self) -> float:
        if self.tok_type == self.VARIABLE and len(self.token) == 1:
            temp_token = self.token
            t_ptr = self._exp_ptr
            slot = ord(self.token) - ord("A")
            self._get_token()
            if self.token != "=":
                self._exp_ptr = t_ptr
                self.token = temp_token
                self.tok_type = self.VARIABLE
            else:
                self._get_token()
                result = self._eval_exp2()
                self.vars[slot] = result
                return result
        return self._eval_exp2()

    def _eval_exp2(self) -> float:
        result = self._eval_exp3()
        while self.token in ("+", "-"):
            op = self.token
            self._get_token()
            temp = self._eval_exp3()
            if op == "-":
                result -= temp
            else:
                result += temp
        return result

    def _eval_exp3(self) -> float:
        result = self._eval_exp4()
        while self.token in ("*", "/"):
            op = self.token
            self._get_token()
            temp = self._eval_exp4()
            if op == "*":
                result *= temp
            else:
                result /= temp
        return result

    def _eval_exp4(self) -> float:
        result = self._eval_exp5()
        while self.token in ("^", "&", "|"):
            op = self.token
            self._get_token()
            temp = self._eval_exp5()
            if op == "^":
                result = math.pow(result, temp)
            elif op == "&":
                result = float(int(result) & int(temp))
            elif op == "|":
                result = float(int(result) | int(temp))
        return result

    def _eval_exp5(self) -> float:
        op = ""
        if self.tok_type == self.DELIMITER and self.token in "+-":
            op = self.token
            self._get_token()
        result = self._eval_exp6()
        if op == "-":
            result = -result
        return result

    def _eval_exp6(self) -> float:
        isfunc = self.tok_type == self.FUNCTION
        temp_token = ""
        if isfunc:
            temp_token = self.token
            self._get_token()

        if self.token == "(":
            self._get_token()
            result = self._eval_exp2()
            if self.token not in ",)":
                self.errormsg = "Unbalanced Parentheses"

            if isfunc:
                result = self._apply_function_after_first_arg(temp_token, result)

            self._get_token()  # consume ')'
            return result

        if self.tok_type == self.VARIABLE:
            result = self.vars[ord(self.token) - ord("A")]
            self._get_token()
            return result

        if self.tok_type == self.NUMBER:
            try:
                result = float(self.token)
            except ValueError:
                self.errormsg = "Is not a number"
                return 0.0
            self._get_token()
            return result

        self.errormsg = "Syntax Error"
        return 0.0

    def _apply_function_after_first_arg(self, name: str, result: float) -> float:
        u = name.upper()
        if self.token == "," and u in ("MIN", "MAX"):
            self._get_token()
            try:
                val = float(self.token)
            except ValueError:
                self.errormsg = "Is not a number"
                return result
            self._get_token()
            if self.token != ")":
                self.errormsg = "Unbalanced Parentheses"
            return min(result, val) if u == "MIN" else max(result, val)

        if self.token == "," and u in ("SHL", "SHR"):
            self._get_token()
            try:
                val = float(self.token)
            except ValueError:
                self.errormsg = "Is not a number"
                return result
            self._get_token()
            if self.token != ")":
                self.errormsg = "Unbalanced Parentheses"
            if u == "SHL":
                return float(int(result) << int(val))
            return float(int(result) >> int(val))

        if u == "SIN":
            return math.sin(PI / 180 * result)
        if u == "COS":
            return math.cos(PI / 180 * result)
        if u == "TAN":
            return math.tan(PI / 180 * result)
        if u == "ASIN":
            return 180 / PI * math.asin(result)
        if u == "ACOS":
            return 180 / PI * math.acos(result)
        if u == "ATAN":
            return 180 / PI * math.atan(result)
        if u == "SINH":
            return math.sinh(result)
        if u == "COSH":
            return math.cosh(result)
        if u == "TANH":
            return math.tanh(result)
        if u == "ASINH":
            return math.asinh(result)
        if u == "ACOSH":
            return math.acosh(result)
        if u == "ATANH":
            return math.atanh(result)
        if u == "LN":
            return math.log(result)
        if u == "LOG":
            return math.log10(result)
        if u == "EXP":
            return math.exp(result)
        if u == "SQRT":
            return math.sqrt(result)
        if u == "SQR":
            return result * result
        if u == "ROUND":
            return float(round(result))
        if u == "FLOOR":
            return math.floor(result)

        for key, fn in self.custom_functions.items():
            if _strcicmp(name, key) == 0:
                return fn(result)

        self.errormsg = "Unknown Function"
        return result

    def _get_token(self) -> None:
        self.tok_type = 0
        self.token = ""
        if self._exp_ptr >= len(self._expression):
            return

        while self._exp_ptr < len(self._expression) and self._expression[self._exp_ptr].isspace():
            self._exp_ptr += 1
        if self._exp_ptr >= len(self._expression):
            return

        ch = self._expression[self._exp_ptr]
        if ch in "+-*/%^&|=(),":
            self.tok_type = self.DELIMITER
            self.token = ch
            self._exp_ptr += 1
            return

        if ch.isalpha():
            start = self._exp_ptr
            while self._exp_ptr < len(self._expression) and self._expression[self._exp_ptr] not in " +-/*%^&|=(),\t\r":
                self._exp_ptr += 1
            self.token = self._expression[start : self._exp_ptr].upper()
            while self._exp_ptr < len(self._expression) and self._expression[self._exp_ptr].isspace():
                self._exp_ptr += 1
            if self._exp_ptr < len(self._expression) and self._expression[self._exp_ptr] == "(":
                self.tok_type = self.FUNCTION
            else:
                self.tok_type = self.VARIABLE
                if len(self.token) != 1:
                    self.errormsg = "Only first letter of variables is considered"
            return

        if ch.isdigit() or ch == ".":
            start = self._exp_ptr
            while self._exp_ptr < len(self._expression) and self._expression[self._exp_ptr] not in " +-/*%^&|=(),\t\r":
                self._exp_ptr += 1
            self.token = self._expression[start : self._exp_ptr].upper()
            self.tok_type = self.NUMBER
            return


def eval_scale_expression(expr: str) -> float:
    """Evaluate scale factor string (no variables)."""
    p = ExprParser()
    return p.eval_exp(expr)

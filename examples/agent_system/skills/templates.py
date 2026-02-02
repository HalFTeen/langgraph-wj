from __future__ import annotations


def arithmetic_template(operation: str) -> str:
    if operation == "add":
        return """from __future__ import annotations


def add(a: int, b: int) -> int:
    return a + b
"""
    raise ValueError(f"Unsupported operation: {operation}")

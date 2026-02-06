"""Prompt templates for agent roles.

This module provides prompt templates for different agent roles
(Coder, Reviewer, Tester, etc.) using langchain-core PromptTemplate.
"""

from examples.agent_system.prompts.templates import (
    CODER_SYSTEM_PROMPT,
    REVIEWER_SYSTEM_PROMPT,
    get_coder_prompt,
    get_reviewer_prompt,
)

__all__ = [
    "CODER_SYSTEM_PROMPT",
    "REVIEWER_SYSTEM_PROMPT",
    "get_coder_prompt",
    "get_reviewer_prompt",
]

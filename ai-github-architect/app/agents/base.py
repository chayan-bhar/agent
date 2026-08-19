"""
Base Agent abstract class.

All LangGraph analysis agents inherit from BaseAgent. This establishes
the common contract: every agent receives the workflow state, calls the
LLM via the provider abstraction, and returns a partial state update.

Agents are stateless functions — they do not hold state between calls.
All state lives in the LangGraph RepositoryAnalysisState.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.graph.state import RepositoryAnalysisState, WorkflowError
from app.services.llm.provider import LLMProvider
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Prompt files directory
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class BaseAgent(ABC):
    """
    Abstract base for all LangGraph analysis agents.

    Subclasses implement:
      - node_name: Identifying name (matches graph node name)
      - _run: Core async logic returning a partial state update
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm
        self._logger = get_logger(self.__class__.__module__)

    @property
    @abstractmethod
    def node_name(self) -> str:
        """Return the LangGraph node name for this agent."""

    @abstractmethod
    async def _run(
        self, state: RepositoryAnalysisState
    ) -> dict[str, Any]:
        """
        Execute the agent's analysis logic.

        Args:
            state: Current workflow state (read-only by convention).

        Returns:
            Partial state update dict to be merged by LangGraph.
        """

    async def __call__(
        self, state: RepositoryAnalysisState
    ) -> dict[str, Any]:
        """
        LangGraph node entrypoint. Wraps _run with logging, timing, and error recording.
        """
        analysis_id = state.get("analysis_id", "unknown")
        self._logger.info(
            "agent_starting",
            node=self.node_name,
            analysis_id=analysis_id,
        )

        start_time = time.perf_counter()

        try:
            result = await self._run(state)

            # Track completed nodes
            completed = list(state.get("completed_nodes", []))
            if self.node_name not in completed:
                completed.append(self.node_name)
            result.setdefault("completed_nodes", completed)
            result.setdefault("current_node", self.node_name)

            duration_ms = round((time.perf_counter() - start_time) * 1000, 1)
            self._logger.info(
                "agent_completed",
                node=self.node_name,
                analysis_id=analysis_id,
                duration_ms=duration_ms,
            )
            return result

        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 1)
            self._logger.error(
                "agent_failed",
                node=self.node_name,
                analysis_id=analysis_id,
                duration_ms=duration_ms,
                error=str(exc),
                exc_info=True,
            )

            # Record error in state rather than crashing the workflow
            error_record: WorkflowError = {
                "node": self.node_name,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "retried": False,
            }
            existing_errors = list(state.get("errors", []))
            existing_errors.append(error_record)

            completed = list(state.get("completed_nodes", []))
            if self.node_name not in completed:
                completed.append(self.node_name)

            return {
                "errors": existing_errors,
                "completed_nodes": completed,
                "current_node": self.node_name,
            }

    # ── Shared utilities for subclasses ───────────────────────────────────────

    def _load_prompt(self, name: str) -> str:
        """Load a prompt template from the prompts/ directory."""
        prompt_path = _PROMPTS_DIR / f"{name}.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(
                f"Prompt file not found: {prompt_path}. "
                f"Create prompts/{name}.txt"
            )
        return prompt_path.read_text(encoding="utf-8")

    def _add_warning(self, state: RepositoryAnalysisState, message: str) -> list[str]:
        """Return updated warnings list with new warning appended."""
        warnings = list(state.get("warnings", []))
        warnings.append(f"[{self.node_name}] {message}")
        return warnings

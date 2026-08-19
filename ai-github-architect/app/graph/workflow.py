"""
LangGraph Workflow — Graph construction with real agents.

Complete workflow wiring all agent implementations to graph nodes.
"""
from __future__ import annotations

import asyncio
from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.graph.state import ApprovalFeedback, RepositoryAnalysisState
from app.utils.logging import get_logger

logger = get_logger(__name__)

# ── Node name constants ───────────────────────────────────────────────────────

NODE_DISCOVERY = "repository_discovery"
NODE_REPO_ANALYZER = "repository_analyzer"
NODE_ARCH_ANALYZER = "architecture_analyzer"
NODE_SEC_ANALYZER = "security_analyzer"
NODE_PERF_ANALYZER = "performance_analyzer"
NODE_QA_ANALYZER = "code_quality_analyzer"
NODE_IMPROVEMENT = "improvement_planner"
NODE_REPORT = "report_generator"
NODE_APPROVAL = "human_approval"


# ── Human-in-the-loop approval node ──────────────────────────────────────────


async def _node_approval(state: RepositoryAnalysisState) -> dict[str, Any]:
    """
    Human approval interrupt node.

    Uses LangGraph's interrupt() to pause the workflow and surface the
    current state to the FastAPI endpoint. The endpoint resumes the workflow
    by calling graph.invoke() with the approval decision in the state.

    When interrupted:
    - The workflow pauses here
    - The API returns the pending report for human review
    - The human calls POST /approve with their decision
    - The graph resumes from this checkpoint with the updated approval_status
    """
    analysis_id = state.get("analysis_id", "unknown")
    current_approval = state.get("approval_status", "PENDING")

    if current_approval == "PENDING":
        logger.info(
            "human_approval_interrupt",
            analysis_id=analysis_id,
            message="Waiting for human approval",
        )
        # Interrupt the graph — pause here until resumed
        interrupt({
            "analysis_id": analysis_id,
            "message": "Analysis complete. Awaiting human approval.",
            "report_available": True,
        })

    # Resumed by the API endpoint with updated approval_status in state
    completed = list(state.get("completed_nodes", []))
    if NODE_APPROVAL not in completed:
        completed.append(NODE_APPROVAL)

    return {
        "completed_nodes": completed,
        "current_node": NODE_APPROVAL,
    }


# ── Conditional routing ───────────────────────────────────────────────────────


def _route_approval(
    state: RepositoryAnalysisState,
) -> Literal["improvement_planner", "__end__"]:
    """Route based on the human approval decision."""
    status = state.get("approval_status", "PENDING")
    if status in ("REJECTED", "REVISION_REQUESTED"):
        logger.info("approval_routing", decision="revision", status=status)
        return NODE_IMPROVEMENT
    logger.info("approval_routing", decision="finalized", status=status)
    return END


# ── Graph builder ─────────────────────────────────────────────────────────────


def build_workflow(
    llm_provider=None,
    mcp_client=None,
    checkpointer=None,
) -> Any:
    """
    Build and compile the analysis workflow graph.

    Args:
        llm_provider: LLMProvider instance (lazy-imported to avoid circular imports).
        mcp_client: MCPClient instance.
        checkpointer: LangGraph checkpointer (MemorySaver or AsyncPostgresSaver).

    Returns:
        Compiled LangGraph workflow.
    """
    # Lazy imports to avoid circular dependencies and heavy startup
    from app.agents.architecture_analyzer import ArchitectureAnalyzerAgent
    from app.agents.code_quality_analyzer import CodeQualityAnalyzerAgent
    from app.agents.discovery import RepositoryDiscoveryAgent
    from app.agents.improvement_planner import ImprovementPlannerAgent
    from app.agents.performance_analyzer import PerformanceAnalyzerAgent
    from app.agents.repository_analyzer import RepositoryAnalyzerAgent
    from app.agents.report_generator import ReportGeneratorAgent
    from app.agents.security_analyzer import SecurityAnalyzerAgent

    if llm_provider is None:
        from app.services.llm.gemini_provider import get_llm_provider
        llm_provider = get_llm_provider()

    if mcp_client is None:
        from app.mcp.client import MCPClient
        mcp_client = MCPClient()

    # Instantiate all agents
    discovery_agent = RepositoryDiscoveryAgent(llm=llm_provider, mcp_client=mcp_client)
    repo_analyzer = RepositoryAnalyzerAgent(llm=llm_provider)
    arch_analyzer = ArchitectureAnalyzerAgent(llm=llm_provider)
    sec_analyzer = SecurityAnalyzerAgent(llm=llm_provider)
    perf_analyzer = PerformanceAnalyzerAgent(llm=llm_provider)
    qa_analyzer = CodeQualityAnalyzerAgent(llm=llm_provider)
    improvement_planner = ImprovementPlannerAgent(llm=llm_provider)
    report_generator = ReportGeneratorAgent(llm=llm_provider)

    builder = StateGraph(RepositoryAnalysisState)

    # ── Add nodes ─────────────────────────────────────────────────────────────
    builder.add_node(NODE_DISCOVERY, discovery_agent)
    builder.add_node(NODE_REPO_ANALYZER, repo_analyzer)
    builder.add_node(NODE_ARCH_ANALYZER, arch_analyzer)
    builder.add_node(NODE_SEC_ANALYZER, sec_analyzer)
    builder.add_node(NODE_PERF_ANALYZER, perf_analyzer)
    builder.add_node(NODE_QA_ANALYZER, qa_analyzer)
    builder.add_node(NODE_IMPROVEMENT, improvement_planner)
    builder.add_node(NODE_REPORT, report_generator)
    builder.add_node(NODE_APPROVAL, _node_approval)

    # ── Edges ─────────────────────────────────────────────────────────────────
    builder.add_edge(START, NODE_DISCOVERY)
    builder.add_edge(NODE_DISCOVERY, NODE_REPO_ANALYZER)

    # Parallel fan-out to all four specialized analyzers
    builder.add_edge(NODE_REPO_ANALYZER, NODE_ARCH_ANALYZER)
    builder.add_edge(NODE_REPO_ANALYZER, NODE_SEC_ANALYZER)
    builder.add_edge(NODE_REPO_ANALYZER, NODE_PERF_ANALYZER)
    builder.add_edge(NODE_REPO_ANALYZER, NODE_QA_ANALYZER)

    # Fan-in — all converge on improvement planner
    builder.add_edge(NODE_ARCH_ANALYZER, NODE_IMPROVEMENT)
    builder.add_edge(NODE_SEC_ANALYZER, NODE_IMPROVEMENT)
    builder.add_edge(NODE_PERF_ANALYZER, NODE_IMPROVEMENT)
    builder.add_edge(NODE_QA_ANALYZER, NODE_IMPROVEMENT)

    builder.add_edge(NODE_IMPROVEMENT, NODE_REPORT)
    builder.add_edge(NODE_REPORT, NODE_APPROVAL)

    # Conditional: approve → END, reject/revise → re-run improvement planner
    builder.add_conditional_edges(
        NODE_APPROVAL,
        _route_approval,
        {
            NODE_IMPROVEMENT: NODE_IMPROVEMENT,
            END: END,
        },
    )

    compile_kwargs: dict = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer

    graph = builder.compile(**compile_kwargs)
    logger.info(
        "workflow_compiled",
        nodes=list(builder.nodes.keys()),
        checkpointer=type(checkpointer).__name__ if checkpointer else "None",
    )
    return graph


def get_workflow() -> Any:
    """
    Return the workflow compiled with in-memory checkpointer (dev/test).

    In production (Milestone 7), replaced with AsyncPostgresSaver.
    """
    return build_workflow(checkpointer=MemorySaver())

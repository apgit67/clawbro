"""
skills/web_search.py
--------------------
Searches the live web via the Tavily API and asks Claude to answer the user's
question grounded in the fetched results, with source citations.

Use this skill for questions that need current/up-to-the-minute information that
post-dates the model's training data (news, prices, releases, "latest", "today").

Requires TAVILY_API_KEY in the environment and the optional `tavily-python`
package (`pip install tavily-python`).
"""

from __future__ import annotations

import os
import re

from core.context import ConversationContext, SkillResult
from skills.base import SkillBase

_SYSTEM_PROMPT = """\
You are a research assistant answering a question using live web search results.

You are given the user's question followed by numbered search results, each with
a title, URL, and an excerpt. Write a clear, accurate answer grounded ONLY in
those results.

Rules:
- Cite sources inline using their number, e.g. "... released in March [2]".
- If the results disagree or are inconclusive, say so plainly.
- If the results do not contain the answer, say you couldn't find it rather than
  guessing.
- End with a "Sources" list mapping each cited number to its URL.
"""

# Strong signals that the user wants *current* information from the internet.
_RECENCY_TERMS = [
    "latest",
    "current",
    "currently",
    "today",
    "tonight",
    "right now",
    "this week",
    "this month",
    "this year",
    "recent",
    "recently",
    r"\bnews\b",
    "breaking",
    r"\bnow\b",
    "as of",
    "up to date",
    "up-to-date",
    "price of",
    "stock price",
    "weather",
    "score",
    "release date",
    "who won",
    "latest version",
    r"in 20\d\d",
]

# Verbs that, combined with a recency term, indicate a web lookup.
_LOOKUP_TERMS = [
    "search the web",
    "search online",
    "google",
    "look up",
    "find out",
    "what's happening",
    "what is happening",
]

_MAX_RESULTS = 5


class WebSearchSkill(SkillBase):
    """Answers questions using live Tavily web search results, with citations."""

    name = "web_search"
    description = (
        "Searches the live web (Tavily) and answers with cited sources. "
        "Use for current/latest info that needs the internet."
    )
    version = "1.0.0"
    # Used only as a fallback by the default score(); real scoring is below.
    trigger_patterns = _RECENCY_TERMS + _LOOKUP_TERMS

    def score(self, message: str) -> float:
        """Boost when the message asks for current info or an explicit web lookup.

        A recency term ("latest", "today", "news") OR an explicit lookup phrase
        ("search the web") is enough to clear the router threshold. Combining
        both, or stacking recency terms, saturates toward 1.0 so this skill wins
        over research_summarizer for genuinely time-sensitive questions.
        """
        lowered = message.lower()
        recency = sum(1 for p in _RECENCY_TERMS if re.search(p, lowered))
        lookup = sum(1 for p in _LOOKUP_TERMS if re.search(p, lowered))

        if recency == 0 and lookup == 0:
            return 0.0

        # A single recency term ("current", "latest", "today") or one explicit
        # lookup phrase ("search the web") is enough to clear the router's 0.4
        # threshold; stacking either saturates toward 1.0.
        raw = recency * 0.45 + lookup * 0.45
        return min(raw, 1.0)

    def handle(self, context: ConversationContext) -> SkillResult:
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return self._error_result(
                "Web search is unavailable: TAVILY_API_KEY is not set. "
                "Get a key at https://tavily.com and add it to your .env."
            )

        try:
            from tavily import TavilyClient
        except ImportError:
            return self._error_result(
                "Web search requires the 'tavily-python' package. "
                "Install it with: pip install tavily-python"
            )

        query = context.message.text
        try:
            client = TavilyClient(api_key=api_key)
            response = client.search(
                query=query,
                max_results=_MAX_RESULTS,
                search_depth="basic",
                include_answer=True,
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_result(f"Web search failed: {exc}")

        results = response.get("results", []) or []
        if not results:
            return SkillResult(
                text=f"No web results found for: {query}",
                skill_name=self.name,
                success=True,
                metadata={"result_count": 0},
            )

        results_block = self._format_results(results)
        quick_answer = response.get("answer") or ""
        answer_hint = (
            f"\n\nTavily's own summary (verify against the results): {quick_answer}"
            if quick_answer
            else ""
        )

        messages = [
            {"role": "user", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Question: {query}\n\nSearch results:\n{results_block}{answer_hint}",
            },
        ]

        try:
            answer = context.claude.complete(messages)
        except Exception as exc:  # noqa: BLE001
            return self._error_result(str(exc))

        return SkillResult(
            text=answer,
            skill_name=self.name,
            success=True,
            metadata={"result_count": len(results)},
        )

    @staticmethod
    def _format_results(results: list[dict]) -> str:
        lines: list[str] = []
        for i, r in enumerate(results, start=1):
            title = r.get("title", "(untitled)")
            url = r.get("url", "")
            content = (r.get("content", "") or "").strip()
            lines.append(f"[{i}] {title}\n    URL: {url}\n    {content}")
        return "\n\n".join(lines)

"""Question answering over retrieved claims and paper text.

Two stages, deliberately separate:

1. **Retrieve.** Find the claims and sentence windows relevant to the question,
   using the same search the rest of the app uses. No model involved.
2. **Answer.** Hand the retrieved text to Claude with an instruction to answer
   only from it and to cite the claims it used.

The retrieval result is returned alongside the answer so a reader can check
what the model was shown. A generated answer with no visible grounding is worse
than no answer at all -- the whole point of this knowledge base is that claims
carry their evidence.

Budget: `XIST_KB_DAILY_TOKEN_BUDGET` is checked before each call and a small
ledger is kept in `silver/llm_usage.json`. The default is deliberately small;
an unset key disables the endpoint entirely rather than failing obscurely.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from xist_kb.query import search as q

ANSWER_MODEL = "claude-sonnet-5-5"
MAX_CLAIMS = 12
MAX_CHUNKS = 8


@dataclass
class Evidence:
    claims: list[dict]
    chunks: list[dict]


def retrieve(conn: duckdb.DuckDBPyConnection, question: str) -> Evidence:
    """Pull the claims and paper passages a question is about.

    Claims first: they are curated summaries with their own quotes. Windows
    second: they cover what the claims missed, which is most of the paper.

    The question is searched whole first, then term by term. A question asked in
    Chinese over an English corpus matches nothing as a phrase -- measured: "A-repeat
    in Xist silencing" returned zero claims -- but the Latin technical terms
    inside it ("A-repeat", "Xist") are exactly what the index is good at.

    Retrieval is restricted to papers whose full text names Xist or discusses X
    inactivation: a claim about MALAT1 is not evidence about XIST, and a model
    handed it will cite it as though it were. The in-scope vocabulary is wider
    than the literal gene name because Drosophila MSL work and older
    X-inactivation papers never write "Xist".
    """
    in_scope = ["xist", "phenomenon_only"]
    claims, _ = q.search_claims(
        conn,
        q.ClaimFilter(
            text=question, limit=MAX_CLAIMS, tiers=["P1", "P2", "P3", "S"], scopes=in_scope
        ),
    )
    if not claims:
        for term in _search_terms(question):
            claims, _ = q.search_claims(
                conn,
                q.ClaimFilter(
                    text=term, limit=MAX_CLAIMS, tiers=["P1", "P2", "P3", "S"], scopes=in_scope
                ),
            )
            if claims:
                break

    chunks, _ = q.search_chunks(
        conn, q.ChunkFilter(text=_best_chunk_query(question), limit=MAX_CHUNKS)
    )
    return Evidence(claims=claims, chunks=chunks)


# Words too common to discriminate between claims; searching for them alone
# returns an arbitrary page. Deliberately short -- the point is to drop filler,
# not to build a stopword list.
_FILLER = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "what", "which", "how", "why",
        "does", "did", "are", "was", "were", "has", "have", "from", "into", "about",
        "xist", "xci", "role", "function",
    }
)


def _search_terms(question: str) -> list[str]:
    """Candidate search terms, longest first.

    Latin technical terms are the useful ones in a mixed-language question; a
    CJK phrase is not indexed at all, so it is skipped rather than sent to a
    search that cannot match it.
    """
    terms = [
        t
        for t in re.findall(r"[A-Za-z][A-Za-z0-9\-']+", question)
        if len(t) > 2 and t.lower() not in _FILLER
    ]
    return sorted(terms, key=len, reverse=True)


def _best_chunk_query(question: str) -> str:
    """What to send the full-text index: the longest technical term, if any."""
    terms = _search_terms(question)
    return terms[0] if terms else question.strip()


def build_prompt(question: str, evidence: Evidence) -> str:
    lines = [
        "Answer the question using ONLY the material below, which was retrieved from a",
        "knowledge base of XIST/XCI literature. If the material does not answer the",
        "question, say so plainly instead of filling the gap from your own knowledge.",
        "",
        "Cite claims by their [claim:<id>] tag when you use them. When a claim's evidence",
        "was located in the paper, its quote is given; when it was not, the claim says",
        "only which section it came from -- do not describe such a claim as quoted text.",
        "",
        "## Claims",
    ]
    for c in evidence.claims:
        tier = c.get("tier") or "?"
        lines.append(f"- [claim:{c['claim_id']}] ({tier}, {c.get('paper_id')}) {c['claim']}")
        if c.get("quote"):
            lines.append(f"  quote: {c['quote']}")
        if c.get("title"):
            lines.append(f"  paper: {c['title']} ({c.get('year') or 'n.d.'})")

    lines.append("")
    lines.append("## Paper passages")
    for chunk in evidence.chunks:
        text = " ".join(chunk["text"].split())
        lines.append(f"- [{chunk['paper_id']}] {text}")

    lines.append("")
    lines.append(f"## Question\n{question}")
    return "\n".join(lines)


def _usage_path() -> Path:
    from xist_kb.paths import SILVER_DIR

    return SILVER_DIR / "llm_usage.json"


def _load_usage(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _budget_usd() -> float:
    raw = os.environ.get("XIST_KB_DAILY_TOKEN_BUDGET", "5").strip()
    try:
        return float(raw)
    except ValueError:
        return 5.0


def budget_remaining() -> dict:
    path = _usage_path()
    usage = _load_usage(path)
    today = date.today().isoformat()
    spent = float(usage.get(today, {}).get("usd", 0.0))
    limit = _budget_usd()
    return {
        "date": today,
        "spent_usd": round(spent, 4),
        "limit_usd": limit,
        "remaining_usd": round(limit - spent, 4),
    }


def _charge(usd: float, tokens: int) -> None:
    path = _usage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    usage = _load_usage(path)
    today = date.today().isoformat()
    entry = usage.setdefault(today, {"usd": 0.0, "tokens": 0, "calls": 0})
    entry["usd"] = round(float(entry.get("usd", 0)) + usd, 4)
    entry["tokens"] = int(entry.get("tokens", 0)) + tokens
    entry["calls"] = int(entry.get("calls", 0)) + 1
    path.write_text(json.dumps(usage, indent=1), encoding="utf-8")


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def answer(conn: duckdb.DuckDBPyConnection, question: str) -> dict:
    """Retrieve, ask Claude, return answer plus the evidence it saw."""
    evidence = retrieve(conn, question)
    payload: dict = {
        "question": question,
        "claims": evidence.claims,
        "chunks": evidence.chunks,
        "answer": None,
        "model": None,
        "usage": None,
        "error": None,
    }

    # Budget first: an exhausted budget needs no API key to detect, and the
    # answer "you are out of budget" is the honest one whether or not a key is
    # configured.
    remaining = budget_remaining()
    if remaining["remaining_usd"] <= 0:
        spent = remaining["spent_usd"]
        limit = remaining["limit_usd"]
        payload["error"] = f"今日 LLM 预算已用完（{spent:.2f} / {limit:.2f} USD）。"
        return payload

    if not available():
        payload["error"] = "未配置 ANTHROPIC_API_KEY，只返回检索到的证据，不生成回答。"
        return payload
    try:
        import anthropic
    except ImportError:
        payload["error"] = "服务端未安装 anthropic 包；只返回检索到的证据。"
        return payload

    client = anthropic.Anthropic()
    prompt = build_prompt(question, evidence)
    try:
        response = client.messages.create(
            model=ANSWER_MODEL,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller verbatim
        payload["error"] = f"调用模型失败：{exc}"
        return payload

    text = "".join(block.text for block in response.content if block.type == "text")
    usage = response.usage
    cost = _estimate_cost(usage.input_tokens, usage.output_tokens)
    _charge(cost, usage.input_tokens + usage.output_tokens)

    payload.update(
        {
            "answer": text,
            "model": ANSWER_MODEL,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": round(cost, 4),
            },
        }
    )
    return payload


# Sonnet-class pricing per million tokens. Hard-coded rather than fetched: the
# number is used for a self-imposed budget, and a wrong figure costs a little
# money in either direction, not correctness.
_INPUT_PER_MTOK = 3.0
_OUTPUT_PER_MTOK = 15.0


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000) * _INPUT_PER_MTOK + (
        output_tokens / 1_000_000
    ) * _OUTPUT_PER_MTOK


def today() -> str:
    return datetime.now(UTC).date().isoformat()

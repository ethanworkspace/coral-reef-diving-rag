from __future__ import annotations

import math

from .iai import IAIClient
from .store import KnowledgeStore, SearchHit


def _cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0


def retrieve(store: KnowledgeStore, query: str, client: IAIClient | None, limit: int = 6) -> list[SearchHit]:
    candidates = store.lexical_search(query, limit=24)
    if client and candidates and any(hit.embedding for hit in candidates):
        vector = client.embed([query])[0]
        candidates = sorted(
            [SearchHit(**{**hit.__dict__, "score": _cosine(vector, hit.embedding) if hit.embedding else -1.0}) for hit in candidates],
            key=lambda hit: hit.score, reverse=True
        )[:16]
    if client and candidates:
        order = client.rerank(query, [hit.text for hit in candidates], top_n=limit)
        if order:
            candidates = [
                SearchHit(**{**candidates[index].__dict__, "score": score})
                for index, score in order if 0 <= index < len(candidates)
            ]
    return candidates[:limit]


def evidence_markdown(hits: list[SearchHit]) -> str:
    if not hits:
        return "資料不足：找不到足夠的可引用資料，無法做安全、合法性或訓練權限判定。請新增正式來源或改用更具體的問題。"
    blocks = []
    for index, hit in enumerate(hits, start=1):
        excerpt = hit.text[:700] + ("…" if len(hit.text) > 700 else "")
        blocks.append(f"[{index}] `{hit.path}` — {hit.label}\n{excerpt}")
    return "\n\n".join(blocks)


def answer(query: str, hits: list[SearchHit], client: IAIClient | None) -> str:
    if not client:
        return "未呼叫 LLM；以下是可核對的檢索證據：\n\n" + evidence_markdown(hits)
    context = "\n\n".join(
        f"SOURCE [{index}] path={hit.path}; section={hit.label}\n{hit.text}"
        for index, hit in enumerate(hits, start=1)
    )
    system = """你是臺灣珊瑚礁浮潛與水肺潛水研究助理。僅依據提供的來源回答，
每個具體主張要以 [來源編號] 標示。若來源不足就明確說資料不足，不能補猜。
這不是潛水計畫、醫療建議或航海指令。絕不可因浪高低於任何值就說安全；缺少最新
波流、潮位、風、現場條件、合法性、出入口與使用者能力時，必須說無法做安全判定。
證照標籤不可自行推論深度、帶隊或環境權限。回答請用繁體中文，簡潔列出限制。"""
    return client.chat([
        {"role": "system", "content": system},
        {"role": "user", "content": f"問題：{query}\n\n可用來源：\n{context}"},
    ])

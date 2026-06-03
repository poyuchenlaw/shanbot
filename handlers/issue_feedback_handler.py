"""
員工問題反應 handler (5/17 LV1 憲法落地)

流程：
  1. postback menu=issue_feedback → set state waiting_issue_question + reply Flex
  2. 員工貼文字 → handle_question:
       (a) 寫 ticket md 到 data/issue_tickets/
       (b) ack 員工「我來想想，1-2 分鐘給你」+ clear state
       (c) spawn async task：三模型辯論 (claude sonnet ∥ llm-router ∥ gemini)
       (d) 收斂 + 自驗證 → push reply 給員工 (老闆口吻) + cc Simon
       (e) 不收斂 → escalate Simon + 跟員工說「我先請老闆看一下」

依憲法：
  - 多模型 ≥3 真實 (feedback_three_model_debate_universal_intent_constitutional)
  - 老闆口吻不是客服語氣
  - ticket md 走 ticket_lite SOP (open → claimed → verified → replied | escalated)
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import state_manager as sm
from services.claude_bridge import chat as claude_chat
from services.line_service import LineService

logger = logging.getLogger("shanbot.issue_feedback")

SHANBOT_DIR = Path(__file__).resolve().parent.parent
TICKETS_DIR = SHANBOT_DIR / "data" / "issue_tickets"
FAQ_DIR = SHANBOT_DIR / "data" / "issue_faq"

ADMIN_LINE_ID = os.environ.get("SHANBOT_ADMIN_LINE_ID", "U2a551ae0489009eb31a864860504b804")

MODEL_TIMEOUT = 60
ACK_TEXT = "✅ 收到了，我想 1-2 分鐘再給你完整回覆，老闆我也 cc 一份"
ESCALATE_USER_TEXT = "我先請老闆過目一下，等等回你"
ESCALATE_ADMIN_PREFIX = "[shanbot 問題反應 ESCALATE]"
COMPLETE_ADMIN_PREFIX = "[shanbot 問題反應 已答]"

SYSTEM_PROMPT = (
    "你是團膳公司老闆的 AI 助理。員工剛在 LINE 反應一個工作上的問題或建議。\n"
    "你的工作：(1) 判斷是否能直接回答 / 改善 (2) 給具體可執行的回覆 (3) 用老闆口吻說話\n"
    "禁止：客服語氣（您好/感謝您的提問）、轉介（請聯絡老闆/請通知管理員）、拖延（先存起來下次月會討論）\n"
    "格式：先 1-2 句直接結論，然後條列具體步驟或改善建議。"
)

BANNED_PHRASES = [
    "請聯絡老闆", "請通知管理員", "我無法處理請改用其他管道",
    "下次月會討論", "您好，感謝您的提問", "感謝您的提問",
]


def _ensure_dirs():
    TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    FAQ_DIR.mkdir(parents=True, exist_ok=True)


def _ticket_id(user_id: str) -> str:
    now = datetime.now()
    tail = (user_id or "anon")[-4:]
    return f"{now:%Y%m%d_%H%M%S}_{tail}"


def _ticket_path(tid: str) -> Path:
    return TICKETS_DIR / f"{tid}.md"


def _write_ticket(tid: str, state: str, payload: dict):
    p = _ticket_path(tid)
    meta = {
        "ticket_id": tid,
        "state": state,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        **{k: v for k, v in payload.items() if k != "body"},
    }
    front = "---\n" + "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()) + "\n---\n"
    p.write_text(front + payload.get("body", ""), encoding="utf-8")


def _update_ticket_state(tid: str, state: str, append_body: str = ""):
    p = _ticket_path(tid)
    if not p.exists():
        return
    txt = p.read_text(encoding="utf-8")
    txt = re.sub(r'^(state:).*$', f'state: "{state}"', txt, count=1, flags=re.MULTILINE)
    txt = re.sub(r'^(updated_at:).*$',
                 f'updated_at: "{datetime.now().isoformat(timespec="seconds")}"',
                 txt, count=1, flags=re.MULTILINE)
    if append_body:
        txt += "\n" + append_body
    p.write_text(txt, encoding="utf-8")


# === Multi-model debate (3 真實 source) ===

def _run_claude(prompt: str, system: str) -> Optional[str]:
    try:
        return claude_chat(prompt, system, model="sonnet", timeout=MODEL_TIMEOUT)
    except Exception as e:
        logger.warning(f"claude failed: {e}")
        return None


def _run_llm_router(prompt: str, system: str) -> Optional[str]:
    import requests
    url = os.environ.get("LLM_ROUTER_URL", "http://127.0.0.1:8010/chat")
    try:
        r = requests.post(url, json={"system": system, "prompt": prompt, "max_tokens": 2048},
                          timeout=MODEL_TIMEOUT)
        if r.status_code == 200:
            j = r.json()
            return j.get("text") or j.get("content") or r.text
        logger.warning(f"llm-router http={r.status_code}")
    except Exception as e:
        logger.warning(f"llm-router failed: {e}")
    return None


def _run_gemini(prompt: str, system: str) -> Optional[str]:
    """2026-06-03: 改走 Gemini CLI (Ultra OAuth)，API key 已撤銷不再用。"""
    import subprocess
    cli = os.environ.get("GEMINI_CLI_BIN", "/home/simon/.npm-global/bin/gemini")
    if not os.path.exists(cli):
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    full_prompt = f"{system}\n\n問題：{prompt}"
    try:
        env = os.environ.copy()
        env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
        r = subprocess.run(
            [cli, "-p", full_prompt, "-m", model, "--yolo", "--skip-trust", "-o", "text"],
            env=env, capture_output=True, text=True, timeout=MODEL_TIMEOUT,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip() or None
        logger.warning(f"gemini CLI exit={r.returncode} stderr={r.stderr[:160]}")
    except Exception as e:
        logger.warning(f"gemini CLI failed: {e}")
    return None


async def _debate(question: str) -> dict:
    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(None, _run_claude, question, SYSTEM_PROMPT),
        loop.run_in_executor(None, _run_llm_router, question, SYSTEM_PROMPT),
        loop.run_in_executor(None, _run_gemini, question, SYSTEM_PROMPT),
    ]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    answers = {}
    for name, val in zip(["claude_sonnet", "llm_router", "gemini"], raw):
        answers[name] = None if isinstance(val, Exception) else val
    alive = [k for k, v in answers.items() if v]

    if len(alive) < 2:
        return {"answers": answers, "models_alive": alive,
                "convergence": False, "verified": False, "final": None}

    scored = sorted(
        [(k, v) for k, v in answers.items() if v],
        key=lambda kv: (
            sum(1 for w in ["步驟", "建議", "作法", "改善", "處理"] if w in kv[1]),
            len(kv[1]),
        ),
        reverse=True,
    )
    final = scored[0][1]
    verified = not any(b in final for b in BANNED_PHRASES)

    return {"answers": answers, "models_alive": alive,
            "convergence": True, "verified": verified, "final": final}


# === 入口：postback ===

async def handle_postback_open(line_service: LineService, group_id: str,
                               user_id: str, reply_token: str,
                               company_id: int = 1):
    """postback menu=issue_feedback → 設 state + 提示員工"""
    _ensure_dirs()
    sm.set_state(group_id, "waiting_issue_question", {})

    flex = {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [{"type": "text", "text": "📣 問題反應", "weight": "bold",
                          "size": "lg", "color": "#FFFFFF"}],
            "backgroundColor": "#06C755", "paddingAll": "12px",
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "text", "text": "工作上有任何問題或建議？", "weight": "bold", "wrap": True},
                {"type": "text",
                 "text": "直接打字告訴我，AI 會立刻處理並回覆，老闆也會收到副本。",
                 "size": "sm", "color": "#555555", "wrap": True},
                {"type": "text", "text": "（不想反應了就回「取消」）",
                 "size": "xs", "color": "#888888", "wrap": True, "margin": "md"},
            ],
        },
    }
    try:
        line_service.reply_flex(reply_token, "請輸入你的問題", flex)
    except Exception as e:
        logger.error(f"reply_flex failed: {e}")


# === 入口：文字 (state machine) ===

async def handle_question(line_service: LineService, text: str, group_id: str,
                          user_id: str, reply_token: str,
                          company_id: int = 1) -> Optional[str]:
    """waiting_issue_question 狀態下的文字訊息"""
    _ensure_dirs()
    txt = (text or "").strip()
    if not txt:
        return "請打字描述你的問題"
    if txt in ("取消", "cancel", "算了"):
        sm.clear_state(group_id)
        return "好，取消了"

    tid = _ticket_id(user_id)
    _write_ticket(tid, "open", {
        "employee_id": user_id,
        "group_id": group_id,
        "company_id": company_id,
        "question": txt,
        "body": f"## 問題\n\n{txt}\n",
    })
    sm.clear_state(group_id)

    asyncio.create_task(_solve_and_reply(line_service, tid, txt, user_id, group_id, company_id))
    return ACK_TEXT


async def _solve_and_reply(line_service: LineService, tid: str, question: str,
                           user_id: str, group_id: str, company_id: int):
    _update_ticket_state(tid, "claimed")
    try:
        result = await _debate(question)
    except Exception as e:
        logger.error(f"debate crashed: {e}")
        result = {"convergence": False, "verified": False, "final": None,
                  "models_alive": [], "answers": {}}

    body_append = "\n## Debate\n\n"
    for name, ans in result.get("answers", {}).items():
        body_append += f"### {name}\n\n{ans or '(no response)'}\n\n"
    body_append += (f"\n## Convergence\n\nalive={result['models_alive']} "
                    f"converged={result['convergence']} verified={result['verified']}\n")

    if result["convergence"] and result["verified"] and result["final"]:
        _update_ticket_state(tid, "verified", body_append + f"\n## Reply\n\n{result['final']}\n")
        try:
            line_service.push(user_id, result["final"], company_id=company_id)
            _update_ticket_state(tid, "replied")
            line_service.push(ADMIN_LINE_ID,
                              f"{COMPLETE_ADMIN_PREFIX} {tid}\n問題: {question[:80]}\n"
                              f"回覆: {result['final'][:200]}",
                              company_id=company_id)
            _write_faq(tid, question, result["final"])
        except Exception as e:
            logger.error(f"push reply failed: {e}")
            _update_ticket_state(tid, "reply_push_failed")
    else:
        _update_ticket_state(tid, "escalated", body_append)
        reason = []
        if not result["convergence"]:
            reason.append(f"alive={len(result['models_alive'])}/3 未收斂")
        if not result["verified"]:
            reason.append("自驗證禁詞檢測未過")
        try:
            line_service.push(user_id, ESCALATE_USER_TEXT, company_id=company_id)
            line_service.push(ADMIN_LINE_ID,
                              f"{ESCALATE_ADMIN_PREFIX} {tid}\n員工: {user_id}\n"
                              f"問題: {question}\n原因: {' / '.join(reason)}\n"
                              f"卡片: data/issue_tickets/{tid}.md",
                              company_id=company_id)
        except Exception as e:
            logger.error(f"push escalate failed: {e}")


def _write_faq(tid: str, question: str, answer: str):
    """收斂後的 Q&A 寫進 FAQ 庫（5/17 LV1 P2 部分落地）"""
    try:
        date = datetime.now().strftime("%Y%m%d")
        p = FAQ_DIR / f"{date}.md"
        block = f"\n## {tid}\n\n**Q:** {question}\n\n**A:** {answer}\n"
        with p.open("a", encoding="utf-8") as f:
            f.write(block)
    except Exception as e:
        logger.warning(f"FAQ write failed: {e}")

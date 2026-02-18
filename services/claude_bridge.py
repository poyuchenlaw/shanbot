"""Claude Code CLI subprocess bridge"""

import os
import json
import subprocess
import logging

logger = logging.getLogger("shanbot.claude")

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
DEFAULT_TIMEOUT = 60


def chat(prompt: str, system: str = "", model: str = "sonnet",
         timeout: int = DEFAULT_TIMEOUT) -> str | None:
    """呼叫 Claude CLI 非互動模式"""
    return _run_claude(prompt, system, model, timeout)


def _run_claude(prompt: str, system_prompt: str = "", model: str = "sonnet",
                timeout: int = DEFAULT_TIMEOUT, max_turns: int = 1) -> str | None:
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json",
           "--model", model, "--max-turns", str(max_turns)]
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.path.dirname(os.path.dirname(__file__)),
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            return data.get("result", "")
        if result.stderr:
            logger.warning(f"Claude stderr: {result.stderr[:200]}")
        return None
    except subprocess.TimeoutExpired:
        logger.warning(f"Claude timeout ({timeout}s)")
        return None
    except FileNotFoundError:
        logger.warning("Claude CLI not found")
        return None
    except Exception as e:
        logger.warning(f"Claude error: {e}")
        return None

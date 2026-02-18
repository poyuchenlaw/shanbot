"""排程管理器 — 心跳報告、行情同步、月底提醒"""

import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("shanbot.scheduler")


class BaseScheduler:
    """排程器基類"""

    def __init__(self, name: str):
        self.name = name
        self._running = False
        self._task = None

    def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Scheduler started: {self.name}")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info(f"Scheduler stopped: {self.name}")

    async def _loop(self):
        raise NotImplementedError

    def _seconds_until(self, hour: int, minute: int = 0) -> float:
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        return (target - now).total_seconds()


class HeartbeatScheduler(BaseScheduler):
    """每日 16:00 心跳報告"""

    def __init__(self, line_service, target_chat_id: str = ""):
        super().__init__("heartbeat-16:00")
        self.line_service = line_service
        self.target_chat_id = target_chat_id

    async def _loop(self):
        while self._running:
            wait = self._seconds_until(16, 0)
            logger.info(f"Heartbeat: next in {wait/3600:.1f}h")
            await asyncio.sleep(wait)
            if self._running and self.target_chat_id:
                await self._execute()

    async def _execute(self):
        try:
            import state_manager as sm
            stats = sm.get_staging_stats()
            pending = stats.get("pending", 0)
            confirmed = stats.get("confirmed", 0)
            total_amount = stats.get("total_amount", 0)

            lines = ["📊 小膳每日心跳報告", f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]

            if pending:
                lines.append(f"⚠️ 待確認採購單：{pending} 筆")
            if confirmed:
                lines.append(f"✅ 已確認：{confirmed} 筆（合計 ${total_amount:,.0f}）")
            if not pending and not confirmed:
                lines.append("📭 今日無採購記錄")

            # 月底提醒
            now = datetime.now()
            if now.day >= 25:
                month_stats = sm.get_staging_stats(now.strftime("%Y-%m"))
                month_pending = month_stats.get("pending", 0)
                if month_pending:
                    lines.append(f"\n🔔 月底提醒：本月還有 {month_pending} 筆待確認！")

            report = "\n".join(lines)
            if self.line_service:
                self.line_service.push(self.target_chat_id, report)
            logger.info("Heartbeat sent")
        except Exception as e:
            logger.error(f"Heartbeat error: {e}", exc_info=True)


class MarketSyncScheduler(BaseScheduler):
    """每日 07:00 同步農業部行情"""

    def __init__(self):
        super().__init__("market-sync-07:00")

    async def _loop(self):
        while self._running:
            wait = self._seconds_until(7, 0)
            logger.info(f"Market sync: next in {wait/3600:.1f}h")
            await asyncio.sleep(wait)
            if self._running:
                await self._execute()

    async def _execute(self):
        try:
            from services.market_service import sync_all_market_data
            result = await sync_all_market_data()
            logger.info(f"Market sync done: {result}")
        except Exception as e:
            logger.error(f"Market sync error: {e}", exc_info=True)


class MonthlySummaryScheduler(BaseScheduler):
    """每月 1 號 09:00 推送上月統整"""

    def __init__(self, line_service, target_chat_id: str = ""):
        super().__init__("monthly-summary")
        self.line_service = line_service
        self.target_chat_id = target_chat_id

    async def _loop(self):
        while self._running:
            # 計算到下個月 1 號 09:00
            now = datetime.now()
            if now.day == 1 and now.hour < 9:
                target = now.replace(hour=9, minute=0, second=0, microsecond=0)
            else:
                if now.month == 12:
                    target = now.replace(year=now.year + 1, month=1, day=1,
                                         hour=9, minute=0, second=0, microsecond=0)
                else:
                    target = now.replace(month=now.month + 1, day=1,
                                         hour=9, minute=0, second=0, microsecond=0)
            wait = (target - now).total_seconds()
            logger.info(f"Monthly summary: next in {wait/86400:.1f}d")
            await asyncio.sleep(wait)
            if self._running and self.target_chat_id:
                await self._execute()

    async def _execute(self):
        try:
            import state_manager as sm
            now = datetime.now()
            last_month = (now.replace(day=1) - timedelta(days=1))
            ym = last_month.strftime("%Y-%m")

            stats = sm.get_staging_stats(ym)
            total = stats.get("total", 0)
            confirmed = stats.get("confirmed", 0)
            pending = stats.get("pending", 0)
            amount = stats.get("total_amount", 0)
            tax = stats.get("total_tax", 0)

            lines = [
                f"📋 {ym} 月度彙整",
                f"📊 採購記錄：{total} 筆（確認 {confirmed} / 待處理 {pending}）",
                f"💰 總金額：${amount:,.0f}",
                f"🧾 進項稅額：${tax:,.0f}",
            ]
            if pending:
                lines.append(f"\n⚠️ 還有 {pending} 筆未確認，請儘速處理！")
            else:
                lines.append("\n✅ 全部已確認。可執行「匯出」生成稅務報表。")

            report = "\n".join(lines)
            if self.line_service:
                self.line_service.push(self.target_chat_id, report)
            logger.info(f"Monthly summary sent for {ym}")
        except Exception as e:
            logger.error(f"Monthly summary error: {e}", exc_info=True)

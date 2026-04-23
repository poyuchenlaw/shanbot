"""排程管理器 — 心跳報告、行情同步、月底提醒、webhook 自檢"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

import requests

logger = logging.getLogger("shanbot.scheduler")

EXPECTED_WEBHOOK_URL = "https://shanbot.kuangshin.tw/webhook"


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
        """多租戶心跳：彙整所有公司 + 推送到 primary group"""
        try:
            import state_manager as sm

            lines = ["📊 小膳每日心跳報告", f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]

            # 按公司統計
            companies = sm.get_all_companies()
            total_pending = 0
            total_confirmed = 0
            total_amount_all = 0

            for company in companies:
                cid = company["id"]
                stats = sm.get_staging_stats(company_id=cid)
                pending = stats.get("pending", 0) or 0
                confirmed = stats.get("confirmed", 0) or 0
                amount = stats.get("total_amount", 0) or 0

                if pending or confirmed:
                    lines.append(f"【{company['short_name']}】")
                    if pending:
                        lines.append(f"  ⚠️ 待確認：{pending} 筆")
                    if confirmed:
                        lines.append(f"  ✅ 已確認：{confirmed} 筆（${amount:,.0f}）")
                    total_pending += pending
                    total_confirmed += confirmed
                    total_amount_all += amount

            if not total_pending and not total_confirmed:
                lines.append("📭 今日無採購記錄")
            else:
                lines.append(f"\n📋 合計：{total_pending} 待確認 / {total_confirmed} 已確認 / ${total_amount_all:,.0f}")

            # 月底提醒
            now = datetime.now()
            if now.day >= 25:
                ym = now.strftime("%Y-%m")
                month_pending = 0
                for company in companies:
                    ms = sm.get_staging_stats(ym, company_id=company["id"])
                    month_pending += (ms.get("pending", 0) or 0)
                if month_pending:
                    lines.append(f"\n🔔 月底提醒：本月還有 {month_pending} 筆待確認！")

            report = "\n".join(lines)
            if self.line_service:
                self.line_service.push(self.target_chat_id, report)
            logger.info("Heartbeat sent (multi-tenant)")
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
            from services import flex_builder as fb

            now = datetime.now()
            last_month = (now.replace(day=1) - timedelta(days=1))
            ym = last_month.strftime("%Y-%m")

            stats = sm.get_staging_stats(ym)
            total = stats.get("total", 0)
            confirmed = stats.get("confirmed", 0)
            pending = stats.get("pending", 0)
            amount = stats.get("total_amount", 0)
            tax = stats.get("total_tax", 0)

            mc = sm.get_monthly_cost(ym)
            summary = {
                "total_count": total,
                "total_amount": amount,
                "total_tax": tax,
                "pending": pending,
                "invoice_count": mc.get("invoice_count", 0) if mc else 0,
                "receipt_count": mc.get("receipt_count", 0) if mc else 0,
            }

            # 檢查是否已有確認記錄
            existing = sm.get_report_confirmation(ym, "monthly")
            if existing:
                cid = existing["id"]
            else:
                cid = sm.upsert_report_confirmation(
                    ym, "monthly", summary_data=summary,
                )

            if self.line_service and self.target_chat_id:
                # 推送 Flex 確認卡片（一則 push）
                flex = fb.build_report_confirmation_flex(
                    cid, ym, "monthly", summary,
                )
                self.line_service.push_flex(
                    self.target_chat_id,
                    f"📋 {ym} 月度彙整 — 請確認",
                    flex,
                )

            logger.info(f"Monthly summary sent for {ym}")
        except Exception as e:
            logger.error(f"Monthly summary error: {e}", exc_info=True)


class MonthEndAnalysisScheduler(BaseScheduler):
    """每月最後一天 20:00 自動跑完整做賬 + 財務分析報告

    自動偵測是否為月底，執行：
    1. 完整做賬 Pipeline（確認→分錄→報表→稽核→結帳）
    2. 月度財務分析報告（趨勢+風險+建議）
    3. 推送摘要到 LINE 群組
    """

    def __init__(self, line_service, target_chat_id: str = ""):
        super().__init__("month-end-analysis-20:00")
        self.line_service = line_service
        self.target_chat_id = target_chat_id

    async def _loop(self):
        import calendar

        while self._running:
            now = datetime.now()
            y, m = now.year, now.month
            last_day = calendar.monthrange(y, m)[1]

            # 計算到本月最後一天 20:00
            target = now.replace(day=last_day, hour=20, minute=0, second=0, microsecond=0)
            if now >= target:
                # 已過本月月底 → 等下個月
                if m == 12:
                    next_y, next_m = y + 1, 1
                else:
                    next_y, next_m = y, m + 1
                next_last_day = calendar.monthrange(next_y, next_m)[1]
                target = now.replace(year=next_y, month=next_m, day=next_last_day,
                                     hour=20, minute=0, second=0, microsecond=0)

            wait = (target - now).total_seconds()
            logger.info(f"MonthEndAnalysis: next run on {target.strftime('%Y-%m-%d %H:%M')}, "
                        f"in {wait/86400:.1f}d")
            await asyncio.sleep(wait)

            if self._running:
                await self._execute()

    async def _execute(self):
        """月底自動執行：做賬 + 財務分析 + 推送"""
        try:
            year_month = datetime.now().strftime("%Y-%m")
            logger.info(f"MonthEndAnalysis: starting for {year_month}")

            # 1. 完整做賬 Pipeline
            from services.pipeline_service import run_full_pipeline, format_pipeline_summary
            pipeline_result = run_full_pipeline(
                year_month=year_month,
                auto_confirm=True,
                skip_tax_export=True,  # 月底不做稅務匯出（雙月才需要）
            )
            pipeline_summary = format_pipeline_summary(pipeline_result)
            logger.info(f"MonthEndAnalysis: pipeline done - "
                        f"{'SUCCESS' if pipeline_result['overall_success'] else 'PARTIAL'}")

            # 2. 財務分析報告
            from services.financial_analysis_service import (
                generate_monthly_analysis, generate_analysis_excel,
            )
            analysis = generate_monthly_analysis(year_month)
            analysis_path = generate_analysis_excel(year_month)
            logger.info(f"MonthEndAnalysis: analysis generated - {len(analysis['risks'])} risks")

            # 3. 推送到 LINE
            if self.line_service and self.target_chat_id:
                # 推送財務分析摘要
                msg = analysis["summary_text"]
                self.line_service.push_message(self.target_chat_id, msg)

                # 推送 Pipeline 狀態（精簡版）
                status_msg = (
                    f"📋 {year_month} 月底自動結帳完成\n"
                    f"{'✅ 全部成功' if pipeline_result['overall_success'] else '⚠️ 部分異常'}\n"
                    f"產出 {len(pipeline_result['files_generated'])} 個報表檔案"
                )
                self.line_service.push_message(self.target_chat_id, status_msg)

            logger.info(f"MonthEndAnalysis: complete for {year_month}")

        except Exception as e:
            logger.error(f"MonthEndAnalysis error: {e}", exc_info=True)
            # 錯誤也推送通知
            if self.line_service and self.target_chat_id:
                try:
                    self.line_service.push_message(
                        self.target_chat_id,
                        f"⚠️ 月底自動做賬發生錯誤：{str(e)[:200]}"
                    )
                except Exception:
                    pass


class WebhookGuardScheduler(BaseScheduler):
    """每 6 小時驗證 LINE webhook URL 是否正確，異常則自動修復。

    防止 webhook URL 被變更（如 ngrok 測試後忘記恢復）導致 Bot 完全斷線。
    """

    CHECK_INTERVAL_HOURS = 6

    def __init__(self):
        super().__init__("webhook-guard-6h")
        self._token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

    async def _loop(self):
        # 啟動後立即檢查一次
        if self._running:
            await self._execute()
        while self._running:
            await asyncio.sleep(self.CHECK_INTERVAL_HOURS * 3600)
            if self._running:
                await self._execute()

    async def _execute(self):
        if not self._token:
            logger.warning("WebhookGuard: LINE_CHANNEL_ACCESS_TOKEN not set, skipping")
            return
        try:
            await asyncio.to_thread(self._check_and_fix)
        except Exception as e:
            logger.error(f"WebhookGuard error: {e}", exc_info=True)

    def _check_and_fix(self):
        headers = {"Authorization": f"Bearer {self._token}"}

        # 1. 查詢目前 webhook URL
        try:
            resp = requests.get(
                "https://api.line.me/v2/bot/channel/webhook/endpoint",
                headers=headers, timeout=10,
            )
            if resp.status_code != 200:
                logger.error(f"WebhookGuard: GET endpoint failed {resp.status_code}")
                return
            info = resp.json()
        except Exception as e:
            logger.error(f"WebhookGuard: GET endpoint error: {e}")
            return

        current_url = info.get("endpoint", "")
        is_active = info.get("active", False)

        # 2. 判斷是否需要修復
        needs_fix = False
        if current_url != EXPECTED_WEBHOOK_URL:
            logger.warning(
                f"WebhookGuard: URL MISMATCH — "
                f"expected={EXPECTED_WEBHOOK_URL} actual={current_url}"
            )
            needs_fix = True
        if not is_active:
            logger.warning("WebhookGuard: webhook is INACTIVE")
            needs_fix = True

        if not needs_fix:
            logger.info(f"WebhookGuard: OK — {current_url} (active={is_active})")
            return

        # 3. 自動修復
        try:
            resp = requests.put(
                "https://api.line.me/v2/bot/channel/webhook/endpoint",
                headers={**headers, "Content-Type": "application/json"},
                json={"endpoint": EXPECTED_WEBHOOK_URL},
                timeout=10,
            )
            if resp.status_code == 200:
                logger.warning(
                    f"WebhookGuard: AUTO-FIXED webhook URL → {EXPECTED_WEBHOOK_URL}"
                )
            else:
                logger.error(f"WebhookGuard: fix failed {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"WebhookGuard: fix error: {e}")

        # 4. 驗證修復結果
        try:
            resp = requests.post(
                "https://api.line.me/v2/bot/channel/webhook/test",
                headers={**headers, "Content-Type": "application/json"},
                json={"endpoint": EXPECTED_WEBHOOK_URL},
                timeout=15,
            )
            test = resp.json()
            if test.get("success"):
                logger.info(f"WebhookGuard: verify OK — status={test.get('statusCode')}")
            else:
                logger.error(f"WebhookGuard: verify FAILED — {test}")
        except Exception as e:
            logger.error(f"WebhookGuard: verify error: {e}")


class ExternalAPIGuardScheduler(BaseScheduler):
    """每 12 小時檢查外部 API 可用性（農業部 + LINE API）。

    不修復（外部 API 不可控），但記錄狀態供 /health 查詢。
    """

    CHECK_INTERVAL_HOURS = 12

    def __init__(self):
        super().__init__("api-guard-12h")
        self.last_status: dict = {}

    async def _loop(self):
        # 啟動後延遲 60 秒再首次檢查（避免啟動風暴）
        await asyncio.sleep(60)
        if self._running:
            await self._execute()
        while self._running:
            await asyncio.sleep(self.CHECK_INTERVAL_HOURS * 3600)
            if self._running:
                await self._execute()

    async def _execute(self):
        try:
            status = await asyncio.to_thread(self._check_apis)
            self.last_status = status
            ok = sum(1 for v in status.values() if v == "ok")
            total = len(status)
            if ok == total:
                logger.info(f"APIGuard: all {total} APIs healthy")
            else:
                failed = {k: v for k, v in status.items() if v != "ok"}
                logger.warning(f"APIGuard: {total - ok}/{total} APIs unhealthy: {failed}")
        except Exception as e:
            logger.error(f"APIGuard error: {e}", exc_info=True)

    def _check_apis(self) -> dict:
        from datetime import date as _date
        results = {}

        # 農業部 FarmTransData
        try:
            resp = requests.get(
                "https://data.moa.gov.tw/Service/OpenData/FromM/FarmTransData.aspx",
                params={"$top": "1"}, timeout=10,
            )
            results["moa_farm"] = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
        except Exception as e:
            results["moa_farm"] = f"error: {str(e)[:50]}"

        # 農業部 PoultryTransType
        try:
            resp = requests.get(
                "https://data.moa.gov.tw/api/v1/PoultryTransType_BoiledChicken_Eggs/",
                params={"$top": "1"}, timeout=10,
            )
            results["moa_poultry"] = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
        except Exception as e:
            results["moa_poultry"] = f"error: {str(e)[:50]}"

        # 農業部 PorkTransType
        try:
            resp = requests.get(
                "https://data.moa.gov.tw/api/v1/PorkTransType/",
                params={"$top": "1"}, timeout=10,
            )
            results["moa_pork"] = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
        except Exception as e:
            results["moa_pork"] = f"error: {str(e)[:50]}"

        # LINE Messaging API
        token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        if token:
            try:
                resp = requests.get(
                    "https://api.line.me/v2/bot/info",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
                results["line_api"] = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
            except Exception as e:
                results["line_api"] = f"error: {str(e)[:50]}"
        else:
            results["line_api"] = "no_token"

        return results

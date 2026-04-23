#!/usr/bin/env python3
"""shanbot watchdog — 三條業務 invariant 自動巡檢，違反就 LINE 推 admin。

每天 09:00 由 PM2 cron 跑（見 ecosystem.config.js 的 watchdog app）。
也可手動：python3 tools/watchdog.py --dry-run

三條 invariant：
  I1. pending > N 天 = 異常        （default N=7）
  I2. 月報表 > M 天沒更新 = 異常    （default M=14）
  I3. GDrive 實檔數 ≠ DB confirmed 數 = 異常（含根目錄 fallback）

退出碼：0 = 全綠，1 = 至少一條違反
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import state_manager as sm


ALERT_LIMIT_PENDING_DAYS = 7
ALERT_LIMIT_REPORT_STALE_DAYS = 14
ALL_COMPANIES = [1, 2, 3, 4, 5]


def _age_days(ts_str: str) -> float:
    try:
        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - ts).total_seconds() / 86400
    except Exception:
        return 0.0


def check_pending_age(threshold_days: int) -> list[dict]:
    """I1：撈出 pending > threshold 天的紀錄，依公司彙總。"""
    alerts: list[dict] = []
    for cid in ALL_COMPANIES:
        rows = sm.get_pending_stagings(company_id=cid)
        old = [r for r in rows if _age_days(r.get("created_at", "")) >= threshold_days]
        if old:
            oldest = max(_age_days(r.get("created_at", "")) for r in old)
            alerts.append({
                "invariant": "I1",
                "company_id": cid,
                "count": len(old),
                "oldest_age_days": round(oldest, 1),
                "msg": f"公司 #{cid}: {len(old)} 筆 pending 超過 {threshold_days} 天（最久 {oldest:.0f} 天）",
            })
    return alerts


def check_report_freshness(threshold_days: int) -> list[dict]:
    """I2：data/reports/ 內 .xlsx 檔修改時間 > threshold 天。"""
    alerts: list[dict] = []
    reports_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "data", "reports")
    if not os.path.isdir(reports_dir):
        return alerts

    now = datetime.now()
    for fname in os.listdir(reports_dir):
        if not fname.endswith(".xlsx"):
            continue
        fp = os.path.join(reports_dir, fname)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(fp))
            age = (now - mtime).total_seconds() / 86400
        except Exception:
            continue
        if age >= threshold_days:
            alerts.append({
                "invariant": "I2",
                "filename": fname,
                "stale_days": round(age, 1),
                "msg": f"報表 {fname} 已 {age:.0f} 天沒更新（最後 {mtime.strftime('%m-%d')}）",
            })
    return alerts


def check_gdrive_db_drift() -> list[dict]:
    """I3：跑 reconcile_gdrive 內部邏輯，但只看本月跟前一個月，求快。"""
    from tools.reconcile_gdrive import reconcile

    alerts: list[dict] = []
    now = datetime.now()
    months = [now.strftime("%Y-%m")]
    if now.month > 1:
        months.append(f"{now.year}-{now.month - 1:02d}")
    else:
        months.append(f"{now.year - 1}-12")

    for cid in ALL_COMPANIES:
        for ym in months:
            try:
                diffs = reconcile(cid, ym, rebuild_index=False)
            except Exception as e:
                alerts.append({
                    "invariant": "I3",
                    "company_id": cid,
                    "year_month": ym,
                    "msg": f"公司 #{cid} {ym} reconcile 失敗：{e}",
                })
                continue
            if diffs:
                by_type: dict[str, int] = {}
                for d in diffs:
                    by_type[d["type"]] = by_type.get(d["type"], 0) + 1
                summary = ", ".join(f"{t}={n}" for t, n in by_type.items())
                alerts.append({
                    "invariant": "I3",
                    "company_id": cid,
                    "year_month": ym,
                    "diff_count": len(diffs),
                    "msg": f"公司 #{cid} {ym} 對帳異常：{summary}",
                })
    return alerts


def push_to_admin(alerts: list[dict], dry_run: bool):
    """把所有 alert 統一彙總一則，推給 ADMIN_LINE_USER_ID 環境變數設定的對象。"""
    admin_id = os.environ.get("SHANBOT_ADMIN_LINE_ID", "")
    if not admin_id:
        print("⚠️  未設 SHANBOT_ADMIN_LINE_ID，跳過 LINE 推送（仍會印到 stdout）")
        return

    lines = [f"🚨 shanbot watchdog 告警（{datetime.now().strftime('%Y-%m-%d %H:%M')}）", ""]
    for a in alerts:
        lines.append(f"[{a['invariant']}] {a['msg']}")
    msg = "\n".join(lines)

    if dry_run:
        print(f"\n--- DRY-RUN LINE 推送預覽 (to={admin_id[:12]}...) ---")
        print(msg)
        return

    try:
        from services.company_service import init_companies
        init_companies()
        from services.line_service import LineService
        line = LineService()
        # 告警走公司 1 (福利社) 的 token 推給 admin
        ok = line.push(admin_id, msg, company_id=1)
        print(f"LINE 推送 {'成功' if ok else '失敗'}")
    except Exception as e:
        print(f"LINE 推送 EXC: {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pending-days", type=int, default=ALERT_LIMIT_PENDING_DAYS)
    p.add_argument("--report-stale-days", type=int, default=ALERT_LIMIT_REPORT_STALE_DAYS)
    p.add_argument("--skip-gdrive", action="store_true", help="跳過 I3 GDrive 對帳（慢）")
    p.add_argument("--dry-run", action="store_true", help="只印不推 LINE")
    args = p.parse_args()

    sm.init_db()

    print(f"shanbot watchdog @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    all_alerts: list[dict] = []

    print(f"\n[I1] 檢查 pending > {args.pending_days} 天...")
    a1 = check_pending_age(args.pending_days)
    for a in a1:
        print(f"  ⚠️  {a['msg']}")
    all_alerts.extend(a1)

    print(f"\n[I2] 檢查報表 > {args.report_stale_days} 天沒更新...")
    a2 = check_report_freshness(args.report_stale_days)
    for a in a2:
        print(f"  ⚠️  {a['msg']}")
    all_alerts.extend(a2)

    if not args.skip_gdrive:
        print(f"\n[I3] 檢查 GDrive ↔ DB 漂移（本月 + 前月）...")
        a3 = check_gdrive_db_drift()
        for a in a3:
            print(f"  ⚠️  {a['msg']}")
        all_alerts.extend(a3)

    print(f"\n{'='*60}")
    print(f"總計 {len(all_alerts)} 條告警")
    print(f"{'='*60}")

    if all_alerts:
        push_to_admin(all_alerts, args.dry_run)
        sys.exit(1)

    print("✅ 全綠，無告警")
    sys.exit(0)


if __name__ == "__main__":
    main()

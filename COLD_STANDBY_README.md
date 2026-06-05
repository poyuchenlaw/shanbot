# ⚠️ 本 instance 為冷備（COLD STANDBY）— 2026-06-05 18:50 Cymon 設定（Simon 拍板遷回 VPS）

- **正式環境在 VPS**（46.224.145.18，ssh vps）`~/shanbot`，cloudflared tunnel a1c464c2 服務 shanbot.kuangshin.tw（DNS 已 --overwrite-dns 改指）
- 本機（台中 WSL）今天 18:30 前是活體；資料已完整遷出（rsync data/ → VPS，MAX id=605、integrity ok）
- 本機已停用：pm2 shanbot / shanbot-watchdog（已 delete + save）、cloudflared config-cymon.yml 的 shanbot ingress（備份 config-cymon.yml.bak_20260605）
- 本機 data/ 為 18:30 切換時點快照，**之後的新資料只在 VPS**，不可直接拿來復活
- 復活步驟：VPS rsync data/ 回來 → git pull → 還原 config-cymon.yml ingress → DNS route 改回 69dd7557 → pm2 start ecosystem.config.js
- 歷史教訓：千萬不要兩邊同時聲明 shanbot.kuangshin.tw（5/18-6/5 split-brain 事故，見 memory lesson shanbot-split-brain-dual-active-fixed-wrong-side）

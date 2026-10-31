/* Stock CRM enumerations -> Traditional Chinese labels (closed lists, see stockcrm/db.py). */
export const L = {
  stage: { watch: "觀察", hold: "持有", exited: "已出場" } as Record<string, string>,
  tier: { core: "核心", satellite: "衛星", watch: "觀察", blacklist: "黑名單" } as Record<string, string>,
  thesis: { intact: "成立", shaken: "動搖", broken: "失效" } as Record<string, string>,
  kind: {
    buy: "買進", sell: "賣出", add: "加碼", trim: "減碼", news: "新聞", earnings: "財報", call: "法說", thought: "想法", review: "回顧", alert: "警示",
  } as Record<string, string>,
  rkind: { price: "到價", earnings: "財報", revenue: "營收", review: "回顧", other: "其他" } as Record<string, string>,
  conf: { high: "高", medium: "中", low: "低" } as Record<string, string>,
  pkind: {
    interaction: "互動紀錄", edge: "供應鏈關係", thesis_status: "論點狀態", reminder: "提醒", driver: "驅動因子",
    driver_value: "驅動因子數值", checkpoint: "檢查點", checkpoint_resolve: "檢查點結果", metric: "標準指標",
  } as Record<string, string>,
  effect: { supports: "支持", weakens: "削弱", confirms: "確認" } as Record<string, string>,
  signal: { no_data: "無資料", on_track: "符合", ahead: "超前", behind: "落後", weakened: "被削弱" } as Record<string, string>,
  cstatus: { pending: "待確認", confirmed: "已確認", missed: "未達成" } as Record<string, string>,
  metric: { revenue_m: "月營收", revenue_q: "季營收", gross_margin: "毛利率", opex: "營業費用", eps: "EPS", shares: "股數" } as Record<string, string>,
  relation: { customer: "客戶", partner: "夥伴", holding: "成分股" } as Record<string, string>,
};

export const JOB_L: Record<string, string> = {
  backup: "備份", fetch_monthly: "月營收", fetch_quarterly: "季報", fetch_shares: "股數", quality: "品質檢查", morning: "早晨簡報", health: "健康度",
};
export const Q_L: Record<string, string> = {
  edges_without_source: "沒有來源的供應鏈關係",
  critical_drivers_without_model: "沒有模型值的關鍵驅動因子",
  holdings_without_invalidation: "沒有失效條件的持股",
  holdings_without_drivers: "沒有驅動因子的持股",
  proposals_pending_too_long: "放超過兩週沒批的提案",
  stale_holdings: "超過 30 天沒更新的持股",
  overdue_checkpoints: "逾期檢查點",
  tw_companies_missing_recent_revenue: "月營收不是最新的台股公司",
};

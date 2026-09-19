export interface StatusMeta {
  label: string;
  tone: "default" | "success" | "warning" | "danger" | "info" | "muted";
}

const STATUS_MAP: Record<string, StatusMeta> = {
  completed: { label: "已完成", tone: "success" },
  success: { label: "成功", tone: "success" },
  listed: { label: "上架成功", tone: "success" },
  approved: { label: "已通过", tone: "success" },
  published: { label: "已发布", tone: "success" },
  selected: { label: "已选定", tone: "success" },
  running: { label: "进行中", tone: "info" },
  collecting: { label: "采集中", tone: "info" },
  processing: { label: "处理中", tone: "info" },
  queued: { label: "排队中", tone: "muted" },
  sourcing: { label: "搜货中", tone: "info" },
  editing: { label: "编辑中", tone: "muted" },
  listing: { label: "生成 Listing", tone: "info" },
  listing_ready: { label: "Listing 已生成", tone: "info" },
  pending_review: { label: "待审核", tone: "warning" },
  needs_fix: { label: "待修复", tone: "danger" },
  reviewing: { label: "审核中", tone: "warning" },
  candidate: { label: "候选", tone: "muted" },
  draft: { label: "草稿", tone: "muted" },
  awaiting_pull: { label: "待拉取", tone: "info" },
  submitted: { label: "已提交", tone: "info" },
  pushed: { label: "已推送", tone: "warning" },
  partial: { label: "部分完成", tone: "warning" },
  publishing: { label: "发布中", tone: "info" },
  // 流水线失败分类（不是推送失败）
  attr_missing: { label: "属性缺失", tone: "danger" },
  image_failed: { label: "图片失败", tone: "danger" },
  sourcing_failed: { label: "搜货失败", tone: "danger" },
  listing_failed: { label: "Listing 失败", tone: "danger" },
  pipeline_failed: { label: "处理失败", tone: "danger" },
  failed: { label: "失败", tone: "danger" },
  publish_failed: { label: "推送失败", tone: "danger" },
  rejected: { label: "已驳回", tone: "danger" },
};

export function getStatusMeta(status: string): StatusMeta {
  return STATUS_MAP[status] ?? { label: status, tone: "default" };
}

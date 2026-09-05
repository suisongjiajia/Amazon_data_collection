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
  listing_ready: { label: "Listing 已生成", tone: "info" },
  pending_review: { label: "待审核", tone: "warning" },
  reviewing: { label: "审核中", tone: "warning" },
  candidate: { label: "候选", tone: "muted" },
  draft: { label: "草稿", tone: "muted" },
  editing: { label: "编辑中", tone: "muted" },
  awaiting_pull: { label: "待拉取", tone: "info" },
  submitted: { label: "待拉取", tone: "info" },
  processing: { label: "待拉取", tone: "info" },
  pushed: { label: "已推送", tone: "warning" },
  partial: { label: "已推送", tone: "warning" },
  failed: { label: "推送失败", tone: "danger" },
  rejected: { label: "已驳回", tone: "danger" },
};

export function getStatusMeta(status: string): StatusMeta {
  return STATUS_MAP[status] ?? { label: status, tone: "default" };
}

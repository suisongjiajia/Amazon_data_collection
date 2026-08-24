import type { OzonViewKey } from "../types/ozon-workflow";

export interface ErpModuleDefinition {
  key: OzonViewKey;
  label: string;
  shortLabel: string;
  description: string;
  group: string;
  step: number;
  icon: string;
}

export const ERP_MODULES: ErpModuleDefinition[] = [
  {
    key: "ozon-collect",
    label: "商品采集",
    shortLabel: "采集",
    description: "从 Ozon 采集商品与热销数据",
    group: "供应链",
    step: 1,
    icon: "采",
  },
  {
    key: "sourcing",
    label: "货源匹配",
    shortLabel: "货源",
    description: "1688 以图搜货并选定供应商",
    group: "供应链",
    step: 2,
    icon: "源",
  },
  {
    key: "product-edit",
    label: "商品编辑",
    shortLabel: "编辑",
    description: "编辑标题、描述与 SKU 价格库存",
    group: "商品中心",
    step: 3,
    icon: "编",
  },
  {
    key: "review",
    label: "审核中心",
    shortLabel: "审核",
    description: "审核待发布商品内容",
    group: "商品中心",
    step: 4,
    icon: "审",
  },
  {
    key: "ozon-publish",
    label: "Ozon 发布",
    shortLabel: "发布",
    description: "将审核通过商品发布到 Ozon",
    group: "销售运营",
    step: 5,
    icon: "发",
  },
];

export function getModuleDefinition(key: OzonViewKey): ErpModuleDefinition {
  return ERP_MODULES.find((item) => item.key === key) ?? ERP_MODULES[0];
}

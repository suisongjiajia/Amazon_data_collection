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
    key: "shop-pipeline",
    label: "店铺流水线",
    shortLabel: "流水线",
    description: "店铺流行 Top50 → 搜货选供 → AI Listing → 审核发布",
    group: "供应链",
    step: 2,
    icon: "线",
  },
  {
    key: "sourcing",
    label: "货源匹配",
    shortLabel: "货源",
    description: "1688 以图搜货并选定供应商",
    group: "供应链",
    step: 3,
    icon: "源",
  },
  {
    key: "product-edit",
    label: "商品编辑",
    shortLabel: "编辑",
    description: "编辑产品信息，并生成可上架 Listing",
    group: "商品中心",
    step: 4,
    icon: "编",
  },
  {
    key: "review",
    label: "审核中心",
    shortLabel: "审核",
    description: "核对商品、供应商与价格后通过；通过后自动推送",
    group: "商品中心",
    step: 5,
    icon: "审",
  },
  {
    key: "ozon-publish",
    label: "Ozon 发布",
    shortLabel: "发布",
    description: "推送 Listing，查看报错并支持修复后再推",
    group: "销售运营",
    step: 6,
    icon: "发",
  },
];

export function getModuleDefinition(key: OzonViewKey): ErpModuleDefinition {
  return ERP_MODULES.find((item) => item.key === key) ?? ERP_MODULES[0];
}

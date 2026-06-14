<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";

type ViewKey =
  | "collections"
  | "raw-products"
  | "selections"
  | "products"
  | "drafts"
  | "publish";

type ValidationLevel = "pass" | "warn" | "fail";

interface CollectionTask {
  id: number;
  task_no: string;
  source_url: string;
  marketplace?: string | null;
  status: string;
  total_count: number;
  success_count: number;
  fail_count: number;
  error_message?: string | null;
  created_at: string;
  finished_at?: string | null;
}

interface RawProduct {
  id: number;
  asin?: string | null;
  source_url?: string | null;
  title?: string | null;
  price_text?: string | null;
  rating?: string | null;
  review_count?: string | null;
  main_image_url?: string | null;
  brand?: string | null;
  size?: string | null;
  color?: string | null;
  variant_attributes?: Record<string, string> | null;
  bullet_points?: string[] | null;
  marketplace?: string | null;
  selection_id?: number | null;
  selection_status?: string | null;
}

interface Selection {
  id: number;
  raw_product_id: number;
  selection_status: string;
  score?: number | null;
  owner?: string | null;
  remark?: string | null;
  raw_asin?: string | null;
  raw_title?: string | null;
  raw_price_text?: string | null;
  raw_marketplace?: string | null;
  raw_main_image_url?: string | null;
  raw_source_url?: string | null;
  raw_brand?: string | null;
}

interface ProductVariant {
  id: number;
  sku: string;
  variant_key?: string | null;
  color?: string | null;
  size?: string | null;
  cost_price?: number | null;
  stock_qty: number;
  variant_attributes?: Record<string, string> | null;
}

interface ProductMaster {
  id: number;
  spu_code: string;
  product_name: string;
  brand?: string | null;
  target_marketplace?: string | null;
  status: string;
  default_cost?: number | null;
  base_attributes?: Record<string, unknown> | null;
  variants: ProductVariant[];
}

interface ListingDraftVariant {
  id: number;
  variant_id: number;
  seller_sku: string;
  price?: number | null;
  quantity: number;
  fulfillment_channel: string;
  external_product_id?: string | null;
  external_product_id_type?: string | null;
  variant_key?: string | null;
  color?: string | null;
  size?: string | null;
}

interface ListingDraft {
  id: number;
  product_master_id: number;
  product_name: string;
  spu_code: string;
  marketplace: string;
  shop_name: string;
  status: string;
  title: string;
  bullet_points?: string[] | null;
  description?: string | null;
  search_terms?: string | null;
  attributes?: Record<string, unknown> | null;
  current_version_no: number;
  variants: ListingDraftVariant[];
}

interface PublishTaskItem {
  id: number;
  draft_id: number;
  variant_id: number;
  seller_sku: string;
  amazon_submission_id?: string | null;
  status: string;
  error_message?: string | null;
  issues?: Array<{ field: string; message: string }> | null;
}

interface PublishTask {
  id: number;
  task_no: string;
  shop_name?: string | null;
  marketplace?: string | null;
  submit_type: string;
  status: string;
  total_count: number;
  success_count: number;
  fail_count: number;
  created_at: string;
  finished_at?: string | null;
  items: PublishTaskItem[];
}

interface ListingLive {
  id: number;
  seller_sku: string;
  marketplace: string;
  shop_name: string;
  listing_status: string;
  asin?: string | null;
  price?: number | null;
  quantity: number;
  updated_at: string;
}

interface ViewDefinition {
  key: ViewKey;
  label: string;
  meta: string;
}

interface FilterOption {
  value: string;
  label: string;
}

interface ValidationItem {
  label: string;
  detail: string;
  level: ValidationLevel;
}

const rawPageSize = 8;
const selectionPageSize = 8;
const productPageSize = 6;

const views: ViewDefinition[] = [
  { key: "collections", label: "采集任务", meta: "输入链接并沉淀原始快照" },
  { key: "raw-products", label: "原始商品库", meta: "查看采集原料，筛选候选商品" },
  { key: "selections", label: "选品池", meta: "把可做的品筛出来" },
  { key: "products", label: "商品中心", meta: "沉淀内部 SPU / SKU" },
  { key: "drafts", label: "Listing 草稿", meta: "优化标题、卖点和发布参数" },
  { key: "publish", label: "发布中心", meta: "跟踪模拟发布和回写状态" },
];

const rawStatusOptions: FilterOption[] = [
  { value: "all", label: "全部状态" },
  { value: "new", label: "未入池" },
  { value: "reviewing", label: "待分析" },
  { value: "converted", label: "已转商品" },
];

const selectionStatusOptions: FilterOption[] = [
  { value: "all", label: "全部状态" },
  { value: "reviewing", label: "待分析" },
  { value: "converted", label: "已转商品" },
];

const productStatusOptions: FilterOption[] = [
  { value: "all", label: "全部状态" },
  { value: "draft", label: "草稿中" },
  { value: "ready", label: "待发布" },
];

const draftStatusOptions = [
  { value: "draft", label: "草稿" },
  { value: "reviewing", label: "待检查" },
  { value: "ready", label: "待发布" },
];

const activeView = ref<ViewKey>("collections");
const loading = ref(false);
const notice = ref("");
const error = ref("");
const collectionUrl = ref("");
const defaultShopName = ref("演示店铺");
const defaultMarketplace = ref("www.amazon.com");
const selectedDraftId = ref<number | null>(null);

const filters = reactive({
  rawQuery: "",
  rawMarketplace: "all",
  rawStatus: "all",
  rawPage: 1,
  selectionQuery: "",
  selectionStatus: "all",
  selectionPage: 1,
  productQuery: "",
  productMarketplace: "all",
  productStatus: "all",
  productPage: 1,
  draftQuery: "",
});

const state = reactive({
  collections: [] as CollectionTask[],
  rawProducts: [] as RawProduct[],
  selections: [] as Selection[],
  products: [] as ProductMaster[],
  drafts: [] as ListingDraft[],
  publishTasks: [] as PublishTask[],
  liveListings: [] as ListingLive[],
});

const draftEditor = reactive({
  title: "",
  bulletText: "",
  description: "",
  searchTerms: "",
  status: "draft",
});

const selectedDraft = computed<ListingDraft | null>(() => {
  if (selectedDraftId.value === null) {
    return null;
  }
  return state.drafts.find((draft) => draft.id === selectedDraftId.value) ?? null;
});

const heroContent = computed(() => {
  switch (activeView.value) {
    case "collections":
      return {
        kicker: "采集入口",
        title: "把 Amazon 链接转成可复用的原始商品资产",
        description:
          "先稳定沉淀任务记录和原始快照，再做筛选、建档和发布。这样数据不会只停留在一次性的采集结果里。",
        aside: "建议先从单个商品链接开始验证整条链路。",
      };
    case "raw-products":
      return {
        kicker: "数据筛选",
        title: "原始商品库是选品、比价和后续建档的原料层",
        description:
          "这里展示的是采集回来的快照，不是最终可发布数据。先看标题、价格、评分、评论量和变体，再决定是否进入选品池。",
        aside: "优先保留结构清晰、变体明确、评论基础不错的商品。",
      };
    case "selections":
      return {
        kicker: "选品转化",
        title: "把候选商品转成内部商品对象，避免流程断档",
        description:
          "选品池的作用是把“值得继续”的商品单独拿出来。确认继续做以后，再转成商品主档和 SKU。",
        aside: "选品阶段先小批量推进，避免把低质量数据推到后面。",
      };
    case "products":
      return {
        kicker: "商品中台",
        title: "商品中心承接 SPU、SKU、成本和变体规则",
        description:
          "这一层开始脱离采集页，转成你自己的商品数据结构。后续不同站点、不同店铺的 Listing 都从这里派生。",
        aside: "建议后续把供应商、成本和图片也补进这里。",
      };
    case "drafts":
      return {
        kicker: "文案生产",
        title: "Listing 草稿页要同时支持编辑、校验和发布前检查",
        description:
          "这里是你经验价值最高的页面。标题、五点、描述、关键词、价格和库存都应该先在草稿层统一处理。",
        aside: "先把草稿页打磨顺，再接真实 Amazon 发布逻辑。",
      };
    case "publish":
      return {
        kicker: "发布追踪",
        title: "先把任务流和问题定位能力搭好，再接自动化发布",
        description:
          "当前展示的是模拟发布结果和线上状态表。目标是先看清成功率、失败原因和回写记录，再继续做自动化重试。",
        aside: "真正的发布体验，关键不在提交，而在回写和排错。",
      };
  }
});

const summaryCards = computed(() => [
  { label: "采集任务", hint: "累计任务数", value: state.collections.length.toString() },
  { label: "原始商品", hint: "待进一步筛选", value: state.rawProducts.length.toString() },
  { label: "选品池", hint: "进入评估流程", value: state.selections.length.toString() },
  { label: "商品主档", hint: "内部 SPU", value: state.products.length.toString() },
  { label: "Listing 草稿", hint: "待优化或待发", value: state.drafts.length.toString() },
  { label: "已回写 SKU", hint: "模拟发布后写入", value: state.liveListings.length.toString() },
]);

const workflowChecklist = computed(() => [
  {
    label: "采集",
    value: state.collections.length,
    detail: state.collections.length > 0 ? "已有任务记录" : "先创建第一条采集任务",
  },
  {
    label: "筛选",
    value: state.selections.length,
    detail: state.selections.length > 0 ? "已有候选商品" : "从原始商品库加入选品池",
  },
  {
    label: "建档",
    value: state.products.length,
    detail: state.products.length > 0 ? "可继续生成草稿" : "把选品转成商品主档",
  },
  {
    label: "发布",
    value: state.publishTasks.length,
    detail: state.publishTasks.length > 0 ? "发布任务已开始回写" : "先跑一轮模拟发布",
  },
]);

const latestCollectionTask = computed(() => state.collections[0] ?? null);
const latestPublishTask = computed(() => state.publishTasks[0] ?? null);

const rawMarketplaceOptions = computed<FilterOption[]>(() => {
  const marketplaces = Array.from(
    new Set(state.rawProducts.map((item) => item.marketplace).filter(Boolean)),
  ) as string[];
  return [{ value: "all", label: "全部站点" }].concat(
    marketplaces.map((marketplace) => ({
      value: marketplace,
      label: getMarketplaceLabel(marketplace),
    })),
  );
});

const productMarketplaceOptions = computed<FilterOption[]>(() => {
  const marketplaces = Array.from(
    new Set(state.products.map((item) => item.target_marketplace).filter(Boolean)),
  ) as string[];
  return [{ value: "all", label: "全部站点" }].concat(
    marketplaces.map((marketplace) => ({
      value: marketplace,
      label: getMarketplaceLabel(marketplace),
    })),
  );
});

const filteredRawProducts = computed(() => {
  return state.rawProducts.filter((item) => {
    const query = filters.rawQuery.trim().toLowerCase();
    const matchesQuery =
      query.length === 0 ||
      [item.asin, item.title, item.brand, item.price_text].some((value) =>
        normalizeText(value).includes(query),
      );
    const matchesMarketplace =
      filters.rawMarketplace === "all" || item.marketplace === filters.rawMarketplace;
    const itemStatus = item.selection_status ?? "new";
    const matchesStatus = filters.rawStatus === "all" || itemStatus === filters.rawStatus;
    return matchesQuery && matchesMarketplace && matchesStatus;
  });
});

const rawTotalPages = computed(() => Math.max(1, Math.ceil(filteredRawProducts.value.length / rawPageSize)));
const rawCurrentPage = computed(() => Math.min(filters.rawPage, rawTotalPages.value));
const paginatedRawProducts = computed(() =>
  paginate(filteredRawProducts.value, rawCurrentPage.value, rawPageSize),
);

const filteredSelections = computed(() => {
  return state.selections.filter((item) => {
    const query = filters.selectionQuery.trim().toLowerCase();
    const matchesQuery =
      query.length === 0 ||
      [item.raw_asin, item.raw_title, item.raw_brand, item.raw_price_text].some((value) =>
        normalizeText(value).includes(query),
      );
    const matchesStatus =
      filters.selectionStatus === "all" || item.selection_status === filters.selectionStatus;
    return matchesQuery && matchesStatus;
  });
});

const selectionTotalPages = computed(() =>
  Math.max(1, Math.ceil(filteredSelections.value.length / selectionPageSize)),
);
const selectionCurrentPage = computed(() => Math.min(filters.selectionPage, selectionTotalPages.value));
const paginatedSelections = computed(() =>
  paginate(filteredSelections.value, selectionCurrentPage.value, selectionPageSize),
);

const filteredProducts = computed(() => {
  return state.products.filter((item) => {
    const query = filters.productQuery.trim().toLowerCase();
    const matchesQuery =
      query.length === 0 ||
      [item.spu_code, item.product_name, item.brand].some((value) =>
        normalizeText(value).includes(query),
      );
    const matchesMarketplace =
      filters.productMarketplace === "all" || item.target_marketplace === filters.productMarketplace;
    const matchesStatus = filters.productStatus === "all" || item.status === filters.productStatus;
    return matchesQuery && matchesMarketplace && matchesStatus;
  });
});

const productTotalPages = computed(() =>
  Math.max(1, Math.ceil(filteredProducts.value.length / productPageSize)),
);
const productCurrentPage = computed(() => Math.min(filters.productPage, productTotalPages.value));
const paginatedProducts = computed(() =>
  paginate(filteredProducts.value, productCurrentPage.value, productPageSize),
);

const filteredDrafts = computed(() => {
  const query = filters.draftQuery.trim().toLowerCase();
  if (!query) {
    return state.drafts;
  }

  return state.drafts.filter((draft) =>
    [draft.product_name, draft.spu_code, draft.shop_name, draft.marketplace].some((value) =>
      normalizeText(value).includes(query),
    ),
  );
});

const draftPreviewBullets = computed(() =>
  draftEditor.bulletText
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean),
);

const draftStats = computed(() => {
  const draft = selectedDraft.value;
  if (!draft) {
    return {
      totalSkuCount: 0,
      pricedSkuCount: 0,
      stockedSkuCount: 0,
      codedSkuCount: 0,
    };
  }

  return {
    totalSkuCount: draft.variants.length,
    pricedSkuCount: draft.variants.filter((item) => Number(item.price) > 0).length,
    stockedSkuCount: draft.variants.filter((item) => Number(item.quantity) > 0).length,
    codedSkuCount: draft.variants.filter((item) => normalizeText(item.external_product_id).length > 0).length,
  };
});

const draftValidationItems = computed<ValidationItem[]>(() => {
  const titleLength = draftEditor.title.trim().length;
  const bullets = draftPreviewBullets.value;
  const descriptionLength = draftEditor.description.trim().length;
  const searchTermLength = draftEditor.searchTerms.trim().length;
  const stats = draftStats.value;
  const hasDraft = selectedDraft.value !== null;

  if (!hasDraft) {
    return [];
  }

  return [
    {
      label: "标题长度",
      detail:
        titleLength >= 80
          ? `当前 ${titleLength} 字，长度可用`
          : `当前 ${titleLength} 字，建议再补充卖点词`,
      level: titleLength >= 80 ? "pass" : titleLength >= 45 ? "warn" : "fail",
    },
    {
      label: "五点卖点",
      detail:
        bullets.length >= 5 ? `已填写 ${bullets.length} 条` : `已填写 ${bullets.length} 条，建议至少 5 条`,
      level: bullets.length >= 5 ? "pass" : bullets.length >= 3 ? "warn" : "fail",
    },
    {
      label: "详情描述",
      detail:
        descriptionLength >= 120
          ? `当前 ${descriptionLength} 字，内容充足`
          : `当前 ${descriptionLength} 字，描述可继续补充`,
      level: descriptionLength >= 120 ? "pass" : descriptionLength >= 50 ? "warn" : "fail",
    },
    {
      label: "Search Terms",
      detail:
        searchTermLength > 0
          ? `已填写 ${searchTermLength} 字`
          : "尚未填写 Search Terms",
      level: searchTermLength > 0 ? "pass" : "warn",
    },
    {
      label: "SKU 价格",
      detail:
        stats.pricedSkuCount === stats.totalSkuCount
          ? `${stats.pricedSkuCount}/${stats.totalSkuCount} 个 SKU 已填写价格`
          : `${stats.pricedSkuCount}/${stats.totalSkuCount} 个 SKU 已填写价格`,
      level:
        stats.totalSkuCount > 0 && stats.pricedSkuCount === stats.totalSkuCount
          ? "pass"
          : stats.pricedSkuCount > 0
            ? "warn"
            : "fail",
    },
    {
      label: "SKU 库存",
      detail:
        stats.stockedSkuCount === stats.totalSkuCount
          ? `${stats.stockedSkuCount}/${stats.totalSkuCount} 个 SKU 有库存`
          : `${stats.stockedSkuCount}/${stats.totalSkuCount} 个 SKU 有库存`,
      level:
        stats.totalSkuCount > 0 && stats.stockedSkuCount === stats.totalSkuCount
          ? "pass"
          : stats.stockedSkuCount > 0
            ? "warn"
            : "fail",
    },
  ];
});

const draftReadinessSummary = computed(() => {
  const items = draftValidationItems.value;
  const passCount = items.filter((item) => item.level === "pass").length;
  const failCount = items.filter((item) => item.level === "fail").length;
  const warnCount = items.filter((item) => item.level === "warn").length;

  return {
    passCount,
    failCount,
    warnCount,
    label:
      failCount === 0 && warnCount === 0
        ? "可直接进入发布前检查"
        : failCount === 0
          ? "基本可用，但仍建议补充优化"
          : "还有关键项未完成",
  };
});

watch(
  () => [filters.rawQuery, filters.rawMarketplace, filters.rawStatus],
  () => {
    filters.rawPage = 1;
  },
);

watch(
  () => [filters.selectionQuery, filters.selectionStatus],
  () => {
    filters.selectionPage = 1;
  },
);

watch(
  () => [filters.productQuery, filters.productMarketplace, filters.productStatus],
  () => {
    filters.productPage = 1;
  },
);

watch(filteredDrafts, (drafts) => {
  if (drafts.length === 0) {
    selectedDraftId.value = null;
    syncDraftEditor();
    return;
  }

  if (!drafts.some((draft) => draft.id === selectedDraftId.value)) {
    selectedDraftId.value = drafts[0].id;
    syncDraftEditor();
  }
});

watch(
  () => selectedDraftId.value,
  () => {
    syncDraftEditor();
  },
);

function normalizeText(value?: string | null): string {
  return (value ?? "").trim().toLowerCase();
}

function paginate<T>(items: T[], page: number, pageSize: number): T[] {
  const start = (page - 1) * pageSize;
  return items.slice(start, start + pageSize);
}

function goRawPage(nextPage: number): void {
  filters.rawPage = Math.min(Math.max(1, nextPage), rawTotalPages.value);
}

function goSelectionPage(nextPage: number): void {
  filters.selectionPage = Math.min(Math.max(1, nextPage), selectionTotalPages.value);
}

function goProductPage(nextPage: number): void {
  filters.productPage = Math.min(Math.max(1, nextPage), productTotalPages.value);
}

function syncDraftEditor(): void {
  const draft = selectedDraft.value;
  if (!draft) {
    draftEditor.title = "";
    draftEditor.bulletText = "";
    draftEditor.description = "";
    draftEditor.searchTerms = "";
    draftEditor.status = "draft";
    return;
  }

  draftEditor.title = draft.title ?? "";
  draftEditor.bulletText = (draft.bullet_points ?? []).join("\n");
  draftEditor.description = draft.description ?? "";
  draftEditor.searchTerms = draft.search_terms ?? "";
  draftEditor.status = draft.status ?? "draft";
}

async function apiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  const rawText = await response.text();
  let payload: unknown = null;

  if (rawText) {
    try {
      payload = JSON.parse(rawText);
    } catch {
      payload = rawText;
    }
  }

  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : `请求失败，状态码 ${response.status}`;
    throw new Error(detail);
  }

  return payload as T;
}

async function refreshWorkspace(): Promise<void> {
  loading.value = true;
  error.value = "";

  try {
    const [collections, rawProducts, selections, products, drafts, publishTasks, liveListings] =
      await Promise.all([
        apiRequest<CollectionTask[]>("/api/collections"),
        apiRequest<RawProduct[]>("/api/raw-products"),
        apiRequest<Selection[]>("/api/selections"),
        apiRequest<ProductMaster[]>("/api/products"),
        apiRequest<ListingDraft[]>("/api/listing-drafts"),
        apiRequest<PublishTask[]>("/api/publish-tasks"),
        apiRequest<ListingLive[]>("/api/listing-live"),
      ]);

    state.collections = collections;
    state.rawProducts = rawProducts;
    state.selections = selections;
    state.products = products;
    state.drafts = drafts;
    state.publishTasks = publishTasks;
    state.liveListings = liveListings;

    if (state.drafts.length > 0) {
      const stillSelected = state.drafts.some((draft) => draft.id === selectedDraftId.value);
      selectedDraftId.value = stillSelected ? selectedDraftId.value : state.drafts[0].id;
    } else {
      selectedDraftId.value = null;
    }
    syncDraftEditor();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载工作台数据失败。";
  } finally {
    loading.value = false;
  }
}

function flash(message: string): void {
  notice.value = message;
  window.setTimeout(() => {
    if (notice.value === message) {
      notice.value = "";
    }
  }, 3000);
}

function formatDate(value?: string | null): string {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatNumber(value?: number | null): string {
  if (value === undefined || value === null) {
    return "-";
  }
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
}

function variantPreview(variant: { color?: string | null; size?: string | null; variant_key?: string | null }): string {
  return variant.variant_key || [variant.color, variant.size].filter(Boolean).join(" / ") || "基础款";
}

function getStatusLabel(status?: string | null): string {
  if (!status) {
    return "-";
  }

  const map: Record<string, string> = {
    running: "进行中",
    completed: "已完成",
    completed_with_issues: "完成但有问题",
    failed: "失败",
    reviewing: "待分析",
    converted: "已转商品",
    draft: "草稿",
    ready: "待发布",
    success: "成功",
    pending: "待处理",
    published: "已上架",
    new: "未入池",
    simulation: "模拟发布",
  };

  return map[status] ?? status;
}

function getMarketplaceLabel(value?: string | null): string {
  if (!value) {
    return "-";
  }

  const map: Record<string, string> = {
    "www.amazon.com": "美国站",
    "www.amazon.co.uk": "英国站",
    "www.amazon.de": "德国站",
    "www.amazon.fr": "法国站",
    "www.amazon.it": "意大利站",
    "www.amazon.es": "西班牙站",
    "www.amazon.ca": "加拿大站",
    "www.amazon.co.jp": "日本站",
  };

  return map[value] ?? value;
}

function getViewCount(view: ViewKey): number {
  switch (view) {
    case "collections":
      return state.collections.length;
    case "raw-products":
      return state.rawProducts.length;
    case "selections":
      return state.selections.length;
    case "products":
      return state.products.length;
    case "drafts":
      return state.drafts.length;
    case "publish":
      return state.publishTasks.length;
  }
}

async function createCollectionTask(): Promise<void> {
  const trimmed = collectionUrl.value.trim();
  if (!trimmed) {
    error.value = "请先输入 Amazon 链接。";
    return;
  }

  loading.value = true;
  error.value = "";

  try {
    await apiRequest("/api/collections", {
      method: "POST",
      body: JSON.stringify({ url: trimmed }),
    });
    collectionUrl.value = "";
    flash("采集任务已完成，结果已进入原始商品库。");
    await refreshWorkspace();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "采集任务执行失败。";
  } finally {
    loading.value = false;
  }
}

async function addToSelection(rawProductId: number): Promise<void> {
  try {
    await apiRequest("/api/selections", {
      method: "POST",
      body: JSON.stringify({ raw_product_id: rawProductId }),
    });
    flash("商品已加入选品池。");
    await refreshWorkspace();
    activeView.value = "selections";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加入选品池失败。";
  }
}

async function createProduct(selectionId: number): Promise<void> {
  try {
    await apiRequest("/api/products", {
      method: "POST",
      body: JSON.stringify({
        selection_id: selectionId,
        target_marketplace: defaultMarketplace.value,
      }),
    });
    flash("商品主档已创建。");
    await refreshWorkspace();
    activeView.value = "products";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "创建商品主档失败。";
  }
}

async function createDraft(productMasterId: number): Promise<void> {
  try {
    const draft = await apiRequest<ListingDraft>("/api/listing-drafts", {
      method: "POST",
      body: JSON.stringify({
        product_master_id: productMasterId,
        shop_name: defaultShopName.value,
        marketplace: defaultMarketplace.value,
      }),
    });
    flash("Listing 草稿已生成。");
    await refreshWorkspace();
    selectedDraftId.value = draft.id;
    syncDraftEditor();
    activeView.value = "drafts";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "生成草稿失败。";
  }
}

async function saveDraft(): Promise<void> {
  if (!selectedDraft.value) {
    return;
  }

  try {
    await apiRequest(`/api/listing-drafts/${selectedDraft.value.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: draftEditor.title,
        bullet_points: draftPreviewBullets.value,
        description: draftEditor.description,
        search_terms: draftEditor.searchTerms,
        status: draftEditor.status,
        change_note: "工作台手工修改",
      }),
    });
    flash("草稿内容已保存。");
    await refreshWorkspace();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存草稿失败。";
  }
}

async function saveDraftVariant(variant: ListingDraftVariant): Promise<void> {
  try {
    await apiRequest(`/api/listing-draft-variants/${variant.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        price: variant.price,
        quantity: variant.quantity,
        fulfillment_channel: variant.fulfillment_channel,
        external_product_id: variant.external_product_id,
        external_product_id_type: variant.external_product_id_type,
      }),
    });
    flash(`SKU ${variant.seller_sku} 已保存。`);
    await refreshWorkspace();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存 SKU 参数失败。";
  }
}

async function publishDraft(draftId: number): Promise<void> {
  try {
    await apiRequest("/api/publish-tasks", {
      method: "POST",
      body: JSON.stringify({
        draft_ids: [draftId],
        shop_name: defaultShopName.value,
        marketplace: defaultMarketplace.value,
        simulate: true,
      }),
    });
    flash("模拟发布已执行，请到发布中心查看结果。");
    await refreshWorkspace();
    activeView.value = "publish";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "创建发布任务失败。";
  }
}

onMounted(() => {
  void refreshWorkspace();
});
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <div class="brand-card">
        <p class="eyebrow">Amazon 外贸工作台</p>
        <h1>选品与上架中台</h1>
        <p class="brand-copy">
          这不是单纯的采集页，而是一条从采集、选品、建档到 Listing 草稿和发布回写的业务链路。
        </p>
        <div class="brand-tags">
          <span>V1 骨架</span>
          <span>前后端已打通</span>
          <span>支持模拟发布</span>
        </div>
      </div>

      <nav class="nav-list" aria-label="工作台模块">
        <button
          v-for="view in views"
          :key="view.key"
          type="button"
          class="nav-item"
          :class="{ active: activeView === view.key }"
          @click="activeView = view.key"
        >
          <div>
            <span>{{ view.label }}</span>
            <small>{{ view.meta }}</small>
          </div>
          <em>{{ getViewCount(view.key) }}</em>
        </button>
      </nav>

      <section class="side-panel">
        <div class="side-title">
          <h2>默认配置</h2>
          <small>生成草稿和发布任务时自动带入</small>
        </div>
        <label>
          <span>店铺名称</span>
          <input v-model="defaultShopName" type="text" placeholder="例如：美国站主店铺" />
        </label>
        <label>
          <span>默认站点</span>
          <input v-model="defaultMarketplace" type="text" placeholder="www.amazon.com" />
        </label>
      </section>

      <section class="side-panel">
        <div class="side-title">
          <h2>推进节奏</h2>
          <small>建议先把全链路跑通，再接复杂自动化</small>
        </div>
        <ol class="flow-list">
          <li v-for="step in workflowChecklist" :key="step.label">
            <div class="flow-head">
              <strong>{{ step.label }}</strong>
              <span>{{ step.value }}</span>
            </div>
            <p>{{ step.detail }}</p>
          </li>
        </ol>
      </section>
    </aside>

    <main class="content">
      <header class="hero-card">
        <div class="hero-copy">
          <p class="eyebrow">{{ heroContent.kicker }}</p>
          <h2>{{ heroContent.title }}</h2>
          <p>{{ heroContent.description }}</p>
        </div>
        <div class="hero-side">
          <button type="button" class="secondary-button" @click="refreshWorkspace">刷新工作台</button>
          <p class="hero-note">{{ heroContent.aside }}</p>
        </div>
      </header>

      <section class="metric-grid">
        <article v-for="card in summaryCards" :key="card.label" class="metric-card">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.hint }}</small>
        </article>
      </section>

      <p v-if="notice" class="notice success">{{ notice }}</p>
      <p v-if="error" class="notice error">{{ error }}</p>
      <p v-if="loading" class="notice neutral">正在同步数据，请稍候...</p>

      <section v-if="activeView === 'collections'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">采集任务</p>
            <h3>输入链接，直接进入原始商品库</h3>
          </div>
          <p>你可以先采集商品页、店铺页或类目页，系统会把采集结果自动落到任务记录和快照库里。</p>
        </div>

        <div class="hero-strip">
          <div class="hero-strip-card accent">
            <span>最近采集任务</span>
            <strong>{{ latestCollectionTask ? getStatusLabel(latestCollectionTask.status) : "暂无任务" }}</strong>
            <small v-if="latestCollectionTask">
              {{ latestCollectionTask.success_count }}/{{ latestCollectionTask.total_count }} 条结果已保存
            </small>
            <small v-else>先输入一条 Amazon 链接开始验证。</small>
          </div>
          <div class="hero-strip-card">
            <span>最近发布任务</span>
            <strong>{{ latestPublishTask ? getStatusLabel(latestPublishTask.status) : "暂未发布" }}</strong>
            <small v-if="latestPublishTask">
              {{ latestPublishTask.success_count }}/{{ latestPublishTask.total_count }} 个 SKU 已处理
            </small>
            <small v-else>发布中心还没有任务记录。</small>
          </div>
        </div>

        <form class="input-bar" @submit.prevent="createCollectionTask">
          <input
            v-model="collectionUrl"
            type="url"
            placeholder="粘贴 Amazon 链接，例如：https://www.amazon.com/dp/B0BRKPBMVY"
          />
          <button type="submit">开始采集</button>
        </form>

        <div class="grid-two">
          <article class="subpanel">
            <div class="subpanel-head">
              <h4>最近任务</h4>
              <span>{{ state.collections.length }} 条</span>
            </div>
            <div v-if="state.collections.length" class="stack-list">
              <article v-for="task in state.collections" :key="task.id" class="task-card">
                <div class="row-head">
                  <strong>{{ task.task_no }}</strong>
                  <span class="status-pill" :data-status="task.status">
                    {{ getStatusLabel(task.status) }}
                  </span>
                </div>
                <p class="row-copy">{{ task.source_url }}</p>
                <div class="meta-line">
                  <span>{{ getMarketplaceLabel(task.marketplace) }}</span>
                  <span>{{ task.success_count }}/{{ task.total_count }} 条入库</span>
                  <span>{{ formatDate(task.created_at) }}</span>
                </div>
                <p v-if="task.error_message" class="hint-text">{{ task.error_message }}</p>
              </article>
            </div>
            <p v-else class="empty-state">还没有采集任务，先输入一条链接试试。</p>
          </article>

          <article class="subpanel">
            <div class="subpanel-head">
              <h4>最新快照预览</h4>
              <span>{{ Math.min(state.rawProducts.length, 5) }} 条</span>
            </div>
            <div v-if="state.rawProducts.length" class="stack-list">
              <article v-for="item in state.rawProducts.slice(0, 5)" :key="item.id" class="snapshot-card">
                <img
                  v-if="item.main_image_url"
                  :src="item.main_image_url"
                  :alt="item.title || '商品图片'"
                />
                <div>
                  <strong>{{ item.title || "未命名商品" }}</strong>
                  <p class="meta-line compact">
                    <span>{{ item.asin || "-" }}</span>
                    <span>{{ item.price_text || "-" }}</span>
                  </p>
                  <p class="hint-text">
                    {{ getMarketplaceLabel(item.marketplace) }} · {{ item.brand || "品牌待补充" }}
                  </p>
                </div>
              </article>
            </div>
            <p v-else class="empty-state">采集完成后，这里会展示最新入库的商品快照。</p>
          </article>
        </div>
      </section>

      <section v-if="activeView === 'raw-products'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">原始商品库</p>
            <h3>先看原料，再决定是否进入选品池</h3>
          </div>
          <p>这里保留的是采集回来的参考数据，用来辅助选品，不建议直接当成最终上架信息使用。</p>
        </div>

        <div class="toolbar">
          <label class="toolbar-field grow">
            <span>搜索商品</span>
            <input
              v-model="filters.rawQuery"
              type="text"
              placeholder="按 ASIN、标题、品牌、价格搜索"
            />
          </label>
          <label class="toolbar-field">
            <span>站点筛选</span>
            <select v-model="filters.rawMarketplace">
              <option v-for="option in rawMarketplaceOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </label>
          <label class="toolbar-field">
            <span>状态筛选</span>
            <select v-model="filters.rawStatus">
              <option v-for="option in rawStatusOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </label>
        </div>

        <div class="toolbar-meta">
          <span>匹配到 {{ filteredRawProducts.length }} 条商品</span>
          <span>第 {{ rawCurrentPage }} / {{ rawTotalPages }} 页</span>
        </div>

        <div v-if="paginatedRawProducts.length" class="catalog-grid">
          <article v-for="item in paginatedRawProducts" :key="item.id" class="catalog-card">
            <div class="catalog-media">
              <img
                v-if="item.main_image_url"
                :src="item.main_image_url"
                :alt="item.title || '商品图片'"
                class="catalog-thumb"
              />
              <span class="market-badge">{{ getMarketplaceLabel(item.marketplace) }}</span>
            </div>
            <div class="catalog-body">
              <div class="row-head">
                <strong>{{ item.asin || "暂无 ASIN" }}</strong>
                <span class="status-pill" :data-status="item.selection_status || 'new'">
                  {{ getStatusLabel(item.selection_status || "new") }}
                </span>
              </div>
              <h4>{{ item.title || "未命名商品" }}</h4>
              <div class="meta-line">
                <span>{{ item.price_text || "价格待采集" }}</span>
                <span>{{ item.rating || "暂无评分" }}</span>
                <span>{{ item.review_count || "暂无评论" }}</span>
              </div>
              <p class="hint-text">{{ item.brand || "品牌待补充" }}</p>
              <div v-if="item.variant_attributes" class="tag-row">
                <span
                  v-for="(value, key) in item.variant_attributes"
                  :key="`${item.id}-${key}`"
                  class="tag-chip"
                >
                  {{ key }}：{{ value }}
                </span>
              </div>
              <ul v-if="item.bullet_points?.length" class="bullet-preview">
                <li v-for="point in item.bullet_points.slice(0, 2)" :key="point">{{ point }}</li>
              </ul>
              <div class="card-actions">
                <button
                  type="button"
                  class="inline-button"
                  :disabled="Boolean(item.selection_id)"
                  @click="addToSelection(item.id)"
                >
                  {{ item.selection_id ? "已进入选品池" : "加入选品池" }}
                </button>
                <a
                  v-if="item.source_url"
                  class="text-link"
                  :href="item.source_url"
                  target="_blank"
                  rel="noreferrer"
                >
                  查看原链接
                </a>
              </div>
            </div>
          </article>
        </div>
        <p v-else class="empty-state">当前筛选条件下没有匹配商品。</p>

        <div class="pager" v-if="filteredRawProducts.length > rawPageSize">
          <button type="button" class="pager-button" :disabled="rawCurrentPage <= 1" @click="goRawPage(rawCurrentPage - 1)">
            上一页
          </button>
          <span>第 {{ rawCurrentPage }} / {{ rawTotalPages }} 页</span>
          <button
            type="button"
            class="pager-button"
            :disabled="rawCurrentPage >= rawTotalPages"
            @click="goRawPage(rawCurrentPage + 1)"
          >
            下一页
          </button>
        </div>
      </section>

      <section v-if="activeView === 'selections'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">选品池</p>
            <h3>把候选品转成商品主档</h3>
          </div>
          <p>这里的目标是把“觉得可做”的商品和“真正开始建档”的商品区分开，不要直接跳过这一步。</p>
        </div>

        <div class="toolbar">
          <label class="toolbar-field grow">
            <span>搜索候选品</span>
            <input
              v-model="filters.selectionQuery"
              type="text"
              placeholder="按 ASIN、标题、品牌、价格搜索"
            />
          </label>
          <label class="toolbar-field">
            <span>状态筛选</span>
            <select v-model="filters.selectionStatus">
              <option v-for="option in selectionStatusOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </label>
        </div>

        <div class="toolbar-meta">
          <span>匹配到 {{ filteredSelections.length }} 条候选品</span>
          <span>第 {{ selectionCurrentPage }} / {{ selectionTotalPages }} 页</span>
        </div>

        <div v-if="paginatedSelections.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>候选商品</th>
                <th>参考 ASIN</th>
                <th>站点</th>
                <th>状态</th>
                <th>负责人</th>
                <th>动作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in paginatedSelections" :key="item.id">
                <td>
                  <strong>{{ item.raw_title || "未命名商品" }}</strong>
                  <p class="cell-copy">{{ item.raw_price_text || "价格待补充" }}</p>
                </td>
                <td>{{ item.raw_asin || "-" }}</td>
                <td>{{ getMarketplaceLabel(item.raw_marketplace) }}</td>
                <td>
                  <span class="status-pill" :data-status="item.selection_status">
                    {{ getStatusLabel(item.selection_status) }}
                  </span>
                </td>
                <td>{{ item.owner || "-" }}</td>
                <td>
                  <button
                    type="button"
                    class="inline-button"
                    :disabled="item.selection_status === 'converted'"
                    @click="createProduct(item.id)"
                  >
                    {{ item.selection_status === "converted" ? "已转商品" : "生成商品主档" }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="empty-state">当前筛选条件下没有候选商品。</p>

        <div class="pager" v-if="filteredSelections.length > selectionPageSize">
          <button
            type="button"
            class="pager-button"
            :disabled="selectionCurrentPage <= 1"
            @click="goSelectionPage(selectionCurrentPage - 1)"
          >
            上一页
          </button>
          <span>第 {{ selectionCurrentPage }} / {{ selectionTotalPages }} 页</span>
          <button
            type="button"
            class="pager-button"
            :disabled="selectionCurrentPage >= selectionTotalPages"
            @click="goSelectionPage(selectionCurrentPage + 1)"
          >
            下一页
          </button>
        </div>
      </section>

      <section v-if="activeView === 'products'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">商品中心</p>
            <h3>用内部商品对象承接后续草稿和发布</h3>
          </div>
          <p>这里更像你自己的商品中台。站点、成本、SKU 和变体都应该在这一层逐步稳定下来。</p>
        </div>

        <div class="toolbar">
          <label class="toolbar-field grow">
            <span>搜索商品主档</span>
            <input
              v-model="filters.productQuery"
              type="text"
              placeholder="按 SPU、商品名、品牌搜索"
            />
          </label>
          <label class="toolbar-field">
            <span>站点筛选</span>
            <select v-model="filters.productMarketplace">
              <option v-for="option in productMarketplaceOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </label>
          <label class="toolbar-field">
            <span>状态筛选</span>
            <select v-model="filters.productStatus">
              <option v-for="option in productStatusOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </label>
        </div>

        <div class="toolbar-meta">
          <span>匹配到 {{ filteredProducts.length }} 个商品主档</span>
          <span>第 {{ productCurrentPage }} / {{ productTotalPages }} 页</span>
        </div>

        <div v-if="paginatedProducts.length" class="product-grid">
          <article v-for="product in paginatedProducts" :key="product.id" class="product-panel">
            <div class="product-head">
              <div>
                <p class="mini-code">{{ product.spu_code }}</p>
                <h4>{{ product.product_name }}</h4>
              </div>
              <span class="status-pill" :data-status="product.status">
                {{ getStatusLabel(product.status) }}
              </span>
            </div>

            <div class="meta-line">
              <span>{{ product.brand || "品牌待补充" }}</span>
              <span>{{ getMarketplaceLabel(product.target_marketplace) }}</span>
              <span>默认成本 {{ formatNumber(product.default_cost) }}</span>
            </div>

            <div class="variant-stack">
              <article v-for="variant in product.variants" :key="variant.id" class="variant-row">
                <div>
                  <strong>{{ variant.sku }}</strong>
                  <p class="cell-copy">{{ variantPreview(variant) }}</p>
                </div>
                <div class="variant-meta">
                  <span>成本 {{ formatNumber(variant.cost_price) }}</span>
                  <span>库存 {{ variant.stock_qty }}</span>
                </div>
              </article>
            </div>

            <div class="card-actions">
              <button type="button" class="inline-button" @click="createDraft(product.id)">
                生成 Listing 草稿
              </button>
            </div>
          </article>
        </div>
        <p v-else class="empty-state">当前筛选条件下没有商品主档。</p>

        <div class="pager" v-if="filteredProducts.length > productPageSize">
          <button
            type="button"
            class="pager-button"
            :disabled="productCurrentPage <= 1"
            @click="goProductPage(productCurrentPage - 1)"
          >
            上一页
          </button>
          <span>第 {{ productCurrentPage }} / {{ productTotalPages }} 页</span>
          <button
            type="button"
            class="pager-button"
            :disabled="productCurrentPage >= productTotalPages"
            @click="goProductPage(productCurrentPage + 1)"
          >
            下一页
          </button>
        </div>
      </section>

      <section v-if="activeView === 'drafts'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Listing 草稿</p>
            <h3>把编辑、校验和预览集中到一个页面</h3>
          </div>
          <p>这里才是最贴近你运营经验的地方。草稿页应该既能写文案，也能看风险，还能检查 SKU 参数是否齐全。</p>
        </div>

        <div class="toolbar">
          <label class="toolbar-field grow">
            <span>搜索草稿</span>
            <input
              v-model="filters.draftQuery"
              type="text"
              placeholder="按商品名、SPU、店铺、站点搜索"
            />
          </label>
        </div>

        <div class="toolbar-meta">
          <span>匹配到 {{ filteredDrafts.length }} 份草稿</span>
          <span v-if="selectedDraft">当前选中：{{ selectedDraft.product_name }}</span>
        </div>

        <div v-if="filteredDrafts.length" class="draft-layout">
          <aside class="draft-sidebar">
            <button
              v-for="draft in filteredDrafts"
              :key="draft.id"
              type="button"
              class="draft-nav-card"
              :class="{ active: selectedDraftId === draft.id }"
              @click="selectedDraftId = draft.id"
            >
              <strong>{{ draft.product_name }}</strong>
              <span>{{ getMarketplaceLabel(draft.marketplace) }}</span>
              <small>{{ draft.shop_name }} · 第 {{ draft.current_version_no }} 版</small>
            </button>
          </aside>

          <div v-if="selectedDraft" class="draft-main">
            <div class="draft-top-grid">
              <div class="draft-header-card">
                <div>
                  <p class="eyebrow">{{ selectedDraft.spu_code }}</p>
                  <h4>{{ selectedDraft.product_name }}</h4>
                  <p class="hint-text">
                    {{ selectedDraft.shop_name }} · {{ getMarketplaceLabel(selectedDraft.marketplace) }} ·
                    当前状态：{{ getStatusLabel(selectedDraft.status) }}
                  </p>
                </div>
                <div class="editor-actions">
                  <button type="button" class="secondary-button" @click="saveDraft">保存草稿</button>
                  <button type="button" @click="publishDraft(selectedDraft.id)">模拟发布</button>
                </div>
              </div>

              <div class="draft-summary-card">
                <div class="summary-row">
                  <span>就绪判断</span>
                  <strong>{{ draftReadinessSummary.label }}</strong>
                </div>
                <div class="summary-metrics">
                  <article>
                    <span>通过项</span>
                    <strong>{{ draftReadinessSummary.passCount }}</strong>
                  </article>
                  <article>
                    <span>警告项</span>
                    <strong>{{ draftReadinessSummary.warnCount }}</strong>
                  </article>
                  <article>
                    <span>失败项</span>
                    <strong>{{ draftReadinessSummary.failCount }}</strong>
                  </article>
                </div>
              </div>
            </div>

            <div class="draft-workspace">
              <div class="editor-card">
                <div class="subpanel-head">
                  <h4>文案编辑区</h4>
                  <span>保存后会写入草稿版本</span>
                </div>
                <div class="editor-grid">
                  <label>
                    <span>标题</span>
                    <input v-model="draftEditor.title" type="text" />
                  </label>
                  <label>
                    <span>草稿状态</span>
                    <select v-model="draftEditor.status">
                      <option v-for="option in draftStatusOptions" :key="option.value" :value="option.value">
                        {{ option.label }}
                      </option>
                    </select>
                  </label>
                  <label class="full-span">
                    <span>五点卖点</span>
                    <textarea
                      v-model="draftEditor.bulletText"
                      rows="6"
                      placeholder="每行填写一条卖点"
                    />
                  </label>
                  <label class="full-span">
                    <span>详情描述</span>
                    <textarea v-model="draftEditor.description" rows="5" />
                  </label>
                  <label class="full-span">
                    <span>Search Terms</span>
                    <textarea v-model="draftEditor.searchTerms" rows="3" />
                  </label>
                </div>
              </div>

              <div class="draft-side-stack">
                <article class="editor-card">
                  <div class="subpanel-head">
                    <h4>发布前检查</h4>
                    <span>{{ draftValidationItems.length }} 项</span>
                  </div>
                  <div class="validation-list">
                    <article
                      v-for="item in draftValidationItems"
                      :key="item.label"
                      class="validation-item"
                      :data-level="item.level"
                    >
                      <div class="validation-head">
                        <strong>{{ item.label }}</strong>
                        <span>{{ item.level === "pass" ? "通过" : item.level === "warn" ? "提醒" : "缺失" }}</span>
                      </div>
                      <p>{{ item.detail }}</p>
                    </article>
                  </div>
                </article>

                <article class="editor-card">
                  <div class="subpanel-head">
                    <h4>草稿预览</h4>
                    <span>模拟页面结构</span>
                  </div>
                  <div class="preview-card">
                    <p class="preview-shop">
                      {{ defaultShopName }} · {{ getMarketplaceLabel(selectedDraft.marketplace) }}
                    </p>
                    <h5>{{ draftEditor.title || "这里会显示你的标题" }}</h5>
                    <div class="preview-meta">
                      <span>{{ draftStats.totalSkuCount }} 个 SKU</span>
                      <span>{{ draftStats.pricedSkuCount }} 个已填价格</span>
                      <span>{{ draftStats.stockedSkuCount }} 个有库存</span>
                    </div>
                    <ul class="preview-bullets">
                      <li v-for="bullet in draftPreviewBullets.slice(0, 5)" :key="bullet">{{ bullet }}</li>
                    </ul>
                    <p class="preview-description">
                      {{ draftEditor.description || "这里会显示详情描述内容。" }}
                    </p>
                  </div>
                </article>
              </div>
            </div>

            <div class="editor-card">
              <div class="subpanel-head">
                <h4>SKU 参数</h4>
                <span>{{ selectedDraft.variants.length }} 个 SKU</span>
              </div>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>卖家 SKU</th>
                      <th>规格</th>
                      <th>价格</th>
                      <th>库存</th>
                      <th>配送方式</th>
                      <th>外部编码</th>
                      <th>保存</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="variant in selectedDraft.variants" :key="variant.id">
                      <td>{{ variant.seller_sku }}</td>
                      <td>{{ variantPreview(variant) }}</td>
                      <td>
                        <input v-model.number="variant.price" type="number" min="0" step="0.01" />
                      </td>
                      <td>
                        <input v-model.number="variant.quantity" type="number" min="0" step="1" />
                      </td>
                      <td>
                        <select v-model="variant.fulfillment_channel">
                          <option value="FBM">FBM</option>
                          <option value="FBA">FBA</option>
                        </select>
                      </td>
                      <td>
                        <input
                          v-model="variant.external_product_id"
                          type="text"
                          placeholder="UPC / EAN / GTIN"
                        />
                      </td>
                      <td>
                        <button type="button" class="inline-button" @click="saveDraftVariant(variant)">
                          保存
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
        <p v-else class="empty-state">没有匹配的草稿，试着清空搜索条件或先生成一份草稿。</p>
      </section>

      <section v-if="activeView === 'publish'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">发布中心</p>
            <h3>先把任务流和问题定位能力搭好，再接自动化发布</h3>
          </div>
          <p>当前展示的是模拟发布结果和线上状态表。重点不是“有没有提交”，而是“出了问题能不能看明白”。</p>
        </div>

        <div class="grid-two">
          <article class="subpanel">
            <div class="subpanel-head">
              <h4>发布任务</h4>
              <span>{{ state.publishTasks.length }} 条</span>
            </div>
            <div v-if="state.publishTasks.length" class="stack-list">
              <article v-for="task in state.publishTasks" :key="task.id" class="task-card publish-card">
                <div class="row-head">
                  <strong>{{ task.task_no }}</strong>
                  <span class="status-pill" :data-status="task.status">
                    {{ getStatusLabel(task.status) }}
                  </span>
                </div>
                <div class="meta-line">
                  <span>{{ task.shop_name || "-" }}</span>
                  <span>{{ getMarketplaceLabel(task.marketplace) }}</span>
                  <span>{{ task.success_count }}/{{ task.total_count }} 成功</span>
                </div>
                <ul class="issue-list">
                  <li v-for="item in task.items.slice(0, 3)" :key="item.id">
                    <strong>{{ item.seller_sku }}</strong>
                    <span>{{ getStatusLabel(item.status) }}</span>
                    <span v-if="item.error_message"> · {{ item.error_message }}</span>
                  </li>
                </ul>
              </article>
            </div>
            <p v-else class="empty-state">还没有发布任务，先从草稿页跑一次模拟发布。</p>
          </article>

          <article class="subpanel">
            <div class="subpanel-head">
              <h4>线上状态表</h4>
              <span>{{ state.liveListings.length }} 条</span>
            </div>
            <div v-if="state.liveListings.length" class="table-wrap slim">
              <table>
                <thead>
                  <tr>
                    <th>卖家 SKU</th>
                    <th>状态</th>
                    <th>站点</th>
                    <th>价格</th>
                    <th>库存</th>
                    <th>更新时间</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in state.liveListings" :key="item.id">
                    <td>{{ item.seller_sku }}</td>
                    <td>
                      <span class="status-pill" :data-status="item.listing_status">
                        {{ getStatusLabel(item.listing_status) }}
                      </span>
                    </td>
                    <td>{{ getMarketplaceLabel(item.marketplace) }}</td>
                    <td>{{ formatNumber(item.price) }}</td>
                    <td>{{ item.quantity }}</td>
                    <td>{{ formatDate(item.updated_at) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="empty-state">模拟发布成功后，这里会看到写回的 SKU 状态。</p>
          </article>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";

type ViewKey = "collections" | "families" | "selections" | "products" | "drafts" | "publish";
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

interface RawProductVariant {
  id: number;
  family_id: number;
  asin?: string | null;
  source_url?: string | null;
  title?: string | null;
  price_text?: string | null;
  main_image_url?: string | null;
  size?: string | null;
  color?: string | null;
  variant_attributes?: Record<string, string> | null;
}

interface RawProductFamily {
  id: number;
  task_id?: number | null;
  family_key: string;
  marketplace?: string | null;
  source_url?: string | null;
  title?: string | null;
  brand?: string | null;
  rating?: string | null;
  review_count?: string | null;
  main_image_url?: string | null;
  variant_dimensions?: string[] | null;
  bullet_points?: string[] | null;
  selection_id?: number | null;
  selection_status?: string | null;
  selection_score?: number | null;
  selection_owner?: string | null;
  selection_remark?: string | null;
  product_master_id?: number | null;
  variant_count: number;
  variants: RawProductVariant[];
}

interface Selection {
  id: number;
  raw_product_family_id: number;
  selection_status: string;
  score?: number | null;
  owner?: string | null;
  remark?: string | null;
  family_key?: string | null;
  family_parent_asin?: string | null;
  family_marketplace?: string | null;
  family_source_url?: string | null;
  family_title?: string | null;
  family_brand?: string | null;
  family_rating?: string | null;
  family_review_count?: string | null;
  family_main_image_url?: string | null;
  variant_dimensions?: string[] | null;
  family_variant_count: number;
  selected_variant_count: number;
  variants: RawProductVariant[];
}

interface ProductVariant {
  id: number;
  raw_product_variant_id?: number | null;
  sku: string;
  variant_key?: string | null;
  color?: string | null;
  size?: string | null;
  cost_price?: number | null;
  stock_qty: number;
  raw_asin?: string | null;
  raw_price_text?: string | null;
  variant_attributes?: Record<string, string> | null;
}

interface ProductMaster {
  id: number;
  selection_id: number;
  raw_product_family_id: number;
  family_title?: string | null;
  family_main_image_url?: string | null;
  variant_dimensions?: string[] | null;
  spu_code: string;
  product_name: string;
  brand?: string | null;
  target_marketplace?: string | null;
  status: string;
  default_cost?: number | null;
  base_attributes?: Record<string, unknown> | null;
  variant_count: number;
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
  parent_asin?: string | null;
  price?: number | null;
  quantity: number;
  updated_at: string;
}

interface ViewDefinition {
  key: ViewKey;
  label: string;
  meta: string;
}

interface ValidationItem {
  label: string;
  detail: string;
  level: ValidationLevel;
}

const views: ViewDefinition[] = [
  { key: "collections", label: "采集任务", meta: "任务与最近入库结果" },
  { key: "families", label: "商品族库", meta: "按 family 浏览原始数据" },
  { key: "selections", label: "选品池", meta: "按 family 选品并圈定变体" },
  { key: "products", label: "商品中心", meta: "1 SPU + 多 SKU 建档结果" },
  { key: "drafts", label: "Listing 草稿", meta: "编辑多 SKU 草稿" },
  { key: "publish", label: "发布中心", meta: "模拟发布与回写结果" },
];

const activeView = ref<ViewKey>("collections");
const loading = ref(false);
const notice = ref("");
const error = ref("");
const collectionUrl = ref("");
const defaultShopName = ref("Demo Shop");
const defaultMarketplace = ref("www.amazon.com");
const selectedDraftId = ref<number | null>(null);

const filters = reactive({
  familyQuery: "",
  familyMarketplace: "all",
  selectionQuery: "",
  productQuery: "",
  draftQuery: "",
});

const state = reactive({
  collections: [] as CollectionTask[],
  families: [] as RawProductFamily[],
  selections: [] as Selection[],
  products: [] as ProductMaster[],
  drafts: [] as ListingDraft[],
  publishTasks: [] as PublishTask[],
  liveListings: [] as ListingLive[],
});

const selectionScopeState = reactive<Record<number, number[]>>({});
const familyExpandedState = reactive<Record<number, boolean>>({});
const selectionExpandedState = reactive<Record<number, boolean>>({});

const draftEditor = reactive({
  title: "",
  bulletText: "",
  description: "",
  searchTerms: "",
  status: "draft",
});

const heroContent = computed(() => {
  switch (activeView.value) {
    case "collections":
      return {
        kicker: "Collection",
        title: "采集先落成商品族，再进入后续业务流转",
        description: "原始层只保留 family 与 variant。采集成功后，选品、建档和草稿都基于同一套结构继续推进。",
        aside: "当前设计中，单个 selection 会生成 1 个 SPU 和多个 SKU。",
      };
    case "families":
      return {
        kicker: "Raw Layer",
        title: "原始商品列表已经替换为商品族列表",
        description: "这里展示 family 聚合结果，以及每个 family 下的全部原始变体。",
        aside: "如果一个 family 已入选或已建档，会直接显示在卡片状态上。",
      };
    case "selections":
      return {
        kicker: "Selection",
        title: "选品以商品族为单位，变体范围单独控制",
        description: "选品后默认纳入全量变体。你可以在这里缩小 variant scope，再生成 SPU 和多 SKU。",
        aside: "这一步决定了最终会创建哪些 SKU。",
      };
    case "products":
      return {
        kicker: "Catalog",
        title: "建档结果已经切换到 1 SPU + 多 SKU",
        description: "每个 product master 对应一个 selection；其下的 SKU 来自选中的 variant scope。",
        aside: "产品层不再直接绑定单个原始快照。",
      };
    case "drafts":
      return {
        kicker: "Draft",
        title: "多 SKU 草稿统一编辑、校验和发布",
        description: "草稿按 SPU 管理，价格、库存和编码按 SKU 逐条维护。",
        aside: "发布前检查主要看文案完整度和 SKU 参数完整度。",
      };
    case "publish":
      return {
        kicker: "Publish",
        title: "发布任务与线上回写状态分开展示",
        description: "先确保模拟发布和错误定位闭环稳定，再接真实发布。",
        aside: "当前展示的是发布任务和已回写的 live SKU 状态。",
      };
  }
});

const summaryCards = computed(() => [
  { label: "采集任务", hint: "累计任务数", value: String(state.collections.length) },
  { label: "商品族", hint: "原始 family 数", value: String(state.families.length) },
  { label: "选品池", hint: "已创建 selection", value: String(state.selections.length) },
  { label: "SPU", hint: "已建档商品主档", value: String(state.products.length) },
  { label: "草稿", hint: "待发布草稿", value: String(state.drafts.length) },
  { label: "Live SKU", hint: "已回写 SKU", value: String(state.liveListings.length) },
]);

const familyMarketplaceOptions = computed(() => {
  const values = Array.from(new Set(state.families.map((item) => item.marketplace).filter(Boolean))) as string[];
  return [{ value: "all", label: "全部站点" }].concat(
    values.map((value) => ({ value, label: getMarketplaceLabel(value) })),
  );
});

const filteredFamilies = computed(() => {
  const query = filters.familyQuery.trim().toLowerCase();
  return state.families.filter((family) => {
    const matchesQuery =
      query.length === 0 ||
      [family.title, family.brand, family.family_key].some((value) =>
        normalizeText(value).includes(query),
      );
    const matchesMarketplace =
      filters.familyMarketplace === "all" || family.marketplace === filters.familyMarketplace;
    return matchesQuery && matchesMarketplace;
  });
});

const filteredSelections = computed(() => {
  const query = filters.selectionQuery.trim().toLowerCase();
  return state.selections.filter((selection) => {
    if (!query) {
      return true;
    }
    return [selection.family_title, selection.family_brand, selection.family_key].some((value) =>
      normalizeText(value).includes(query),
    );
  });
});

const filteredProducts = computed(() => {
  const query = filters.productQuery.trim().toLowerCase();
  return state.products.filter((product) => {
    if (!query) {
      return true;
    }
    return [product.spu_code, product.product_name, product.brand].some((value) =>
      normalizeText(value).includes(query),
    );
  });
});

const filteredDrafts = computed(() => {
  const query = filters.draftQuery.trim().toLowerCase();
  return state.drafts.filter((draft) => {
    if (!query) {
      return true;
    }
    return [draft.product_name, draft.spu_code, draft.shop_name, draft.marketplace].some((value) =>
      normalizeText(value).includes(query),
    );
  });
});

const selectedDraft = computed<ListingDraft | null>(() => {
  if (selectedDraftId.value === null) {
    return null;
  }
  return state.drafts.find((draft) => draft.id === selectedDraftId.value) ?? null;
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
    return { totalSkuCount: 0, pricedSkuCount: 0, stockedSkuCount: 0 };
  }
  return {
    totalSkuCount: draft.variants.length,
    pricedSkuCount: draft.variants.filter((item) => Number(item.price) > 0).length,
    stockedSkuCount: draft.variants.filter((item) => Number(item.quantity) > 0).length,
  };
});

const draftValidationItems = computed<ValidationItem[]>(() => {
  if (!selectedDraft.value) {
    return [];
  }

  const titleLength = draftEditor.title.trim().length;
  const bulletCount = draftPreviewBullets.value.length;
  const descriptionLength = draftEditor.description.trim().length;
  const stats = draftStats.value;

  return [
    {
      label: "标题长度",
      detail: titleLength >= 80 ? `当前 ${titleLength} 字` : `当前 ${titleLength} 字，建议补足`,
      level: titleLength >= 80 ? "pass" : titleLength >= 45 ? "warn" : "fail",
    },
    {
      label: "卖点条数",
      detail: bulletCount >= 5 ? `已填写 ${bulletCount} 条` : `当前 ${bulletCount} 条，建议至少 5 条`,
      level: bulletCount >= 5 ? "pass" : bulletCount >= 3 ? "warn" : "fail",
    },
    {
      label: "详情描述",
      detail:
        descriptionLength >= 120 ? `当前 ${descriptionLength} 字` : `当前 ${descriptionLength} 字，建议补足`,
      level: descriptionLength >= 120 ? "pass" : descriptionLength >= 50 ? "warn" : "fail",
    },
    {
      label: "SKU 价格",
      detail: `${stats.pricedSkuCount}/${stats.totalSkuCount} 个 SKU 已填写价格`,
      level:
        stats.totalSkuCount > 0 && stats.pricedSkuCount === stats.totalSkuCount
          ? "pass"
          : stats.pricedSkuCount > 0
            ? "warn"
            : "fail",
    },
    {
      label: "SKU 库存",
      detail: `${stats.stockedSkuCount}/${stats.totalSkuCount} 个 SKU 已填写库存`,
      level:
        stats.totalSkuCount > 0 && stats.stockedSkuCount === stats.totalSkuCount
          ? "pass"
          : stats.stockedSkuCount > 0
            ? "warn"
            : "fail",
    },
  ];
});

watch(
  selectedDraft,
  (draft) => {
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
  },
  { immediate: true },
);

onMounted(() => {
  void refreshAll();
});

async function refreshAll(): Promise<void> {
  await withLoading(async () => {
    const [collections, families, selections, products, drafts, publishTasks, liveListings] = await Promise.all([
      apiRequest<CollectionTask[]>("/api/collections"),
      apiRequest<RawProductFamily[]>("/api/raw-product-families"),
      apiRequest<Selection[]>("/api/selections"),
      apiRequest<ProductMaster[]>("/api/products"),
      apiRequest<ListingDraft[]>("/api/listing-drafts"),
      apiRequest<PublishTask[]>("/api/publish-tasks"),
      apiRequest<ListingLive[]>("/api/listing-live"),
    ]);

    state.collections = collections;
    state.families = families;
    state.selections = selections;
    state.products = products;
    state.drafts = drafts;
    state.publishTasks = publishTasks;
    state.liveListings = liveListings;

    for (const family of families) {
      if (!(family.id in familyExpandedState)) {
        familyExpandedState[family.id] = false;
      }
    }
    for (const selection of selections) {
      selectionScopeState[selection.id] = selection.variants.map((variant) => variant.id);
      if (!(selection.id in selectionExpandedState)) {
        selectionExpandedState[selection.id] = true;
      }
    }

    if (drafts.length > 0) {
      if (!selectedDraftId.value || !drafts.some((draft) => draft.id === selectedDraftId.value)) {
        selectedDraftId.value = drafts[0].id;
      }
    } else {
      selectedDraftId.value = null;
    }
  });
}

async function submitCollection(): Promise<void> {
  const url = collectionUrl.value.trim();
  if (!url) {
    error.value = "请先输入采集链接";
    return;
  }

  await withLoading(async () => {
    await apiRequest("/api/collections", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    notice.value = "采集任务已提交并完成入库";
    collectionUrl.value = "";
    await refreshAll();
  });
}

async function addToSelection(familyId: number): Promise<void> {
  await withLoading(async () => {
    await apiRequest("/api/selections", {
      method: "POST",
      body: JSON.stringify({ raw_product_family_id: familyId }),
    });
    notice.value = "商品族已加入选品池";
    activeView.value = "selections";
    await refreshAll();
  });
}

async function saveSelectionScope(selectionId: number): Promise<void> {
  const variantIds = selectionScopeState[selectionId] ?? [];
  if (variantIds.length === 0) {
    error.value = "至少保留一个变体";
    return;
  }

  await withLoading(async () => {
    await apiRequest(`/api/selections/${selectionId}/variant-scope`, {
      method: "PUT",
      body: JSON.stringify({ raw_product_variant_ids: variantIds }),
    });
    notice.value = "变体范围已更新";
    await refreshAll();
  });
}

async function createProduct(selectionId: number): Promise<void> {
  await withLoading(async () => {
    await apiRequest("/api/products", {
      method: "POST",
      body: JSON.stringify({
        selection_id: selectionId,
        target_marketplace: defaultMarketplace.value,
      }),
    });
    notice.value = "已生成 1 个 SPU 和对应多个 SKU";
    activeView.value = "products";
    await refreshAll();
  });
}

async function createDraft(productMasterId: number): Promise<void> {
  await withLoading(async () => {
    await apiRequest("/api/listing-drafts", {
      method: "POST",
      body: JSON.stringify({
        product_master_id: productMasterId,
        shop_name: defaultShopName.value,
        marketplace: defaultMarketplace.value,
      }),
    });
    notice.value = "Listing 草稿已创建";
    activeView.value = "drafts";
    await refreshAll();
  });
}

async function saveDraft(): Promise<void> {
  if (!selectedDraft.value) {
    return;
  }

  await withLoading(async () => {
    await apiRequest(`/api/listing-drafts/${selectedDraft.value!.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: draftEditor.title,
        bullet_points: draftPreviewBullets.value,
        description: draftEditor.description,
        search_terms: draftEditor.searchTerms,
        status: draftEditor.status,
      }),
    });
    notice.value = "草稿已保存";
    await refreshAll();
  });
}

async function saveDraftVariant(variant: ListingDraftVariant): Promise<void> {
  await withLoading(async () => {
    await apiRequest(`/api/listing-draft-variants/${variant.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        price: variant.price,
        quantity: variant.quantity,
        fulfillment_channel: variant.fulfillment_channel,
        external_product_id: variant.external_product_id,
        external_product_id_type: variant.external_product_id ? "UPC" : null,
      }),
    });
    notice.value = `SKU ${variant.seller_sku} 已保存`;
    await refreshAll();
  });
}

async function publishDraft(draftId: number): Promise<void> {
  await withLoading(async () => {
    await apiRequest("/api/publish-tasks", {
      method: "POST",
      body: JSON.stringify({
        draft_ids: [draftId],
        shop_name: defaultShopName.value,
        marketplace: defaultMarketplace.value,
        simulate: true,
      }),
    });
    notice.value = "模拟发布已完成";
    activeView.value = "publish";
    await refreshAll();
  });
}

function toggleVariantInScope(selectionId: number, variantId: number): void {
  const current = selectionScopeState[selectionId] ?? [];
  if (current.includes(variantId)) {
    if (current.length === 1) {
      return;
    }
    selectionScopeState[selectionId] = current.filter((item) => item !== variantId);
    return;
  }
  selectionScopeState[selectionId] = current.concat(variantId);
}

function isVariantSelected(selectionId: number, variantId: number): boolean {
  return (selectionScopeState[selectionId] ?? []).includes(variantId);
}

function variantPreview(variant: {
  variant_key?: string | null;
  variant_attributes?: Record<string, string> | null;
  color?: string | null;
  size?: string | null;
}): string {
  if (variant.variant_key) {
    return variant.variant_key;
  }
  const parts = Object.entries(variant.variant_attributes ?? {})
    .filter(([, value]) => Boolean(value))
    .map(([key, value]) => `${key}: ${value}`);
  if (parts.length > 0) {
    return parts.join(" / ");
  }
  return [variant.color, variant.size].filter(Boolean).join(" / ") || "默认变体";
}

function selectionCoverage(selection: Selection): string {
  return `${selection.selected_variant_count}/${selection.family_variant_count} 个变体`;
}

function familyLeadPrice(family: RawProductFamily): string {
  return family.variants.find((variant) => normalizeText(variant.price_text).length > 0)?.price_text ?? "价格待补充";
}

function selectionLeadPrice(selection: Selection): string {
  return selection.variants.find((variant) => normalizeText(variant.price_text).length > 0)?.price_text ?? "价格待补充";
}

function formatDate(value?: string | null): string {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function formatNumber(value?: number | null): string {
  if (value === null || value === undefined) {
    return "-";
  }
  return Number(value).toFixed(2);
}

function getStatusLabel(status?: string | null): string {
  switch (status) {
    case "completed":
      return "已完成";
    case "running":
      return "进行中";
    case "failed":
      return "失败";
    case "reviewing":
      return "待分析";
    case "converted":
      return "已建档";
    case "draft":
      return "草稿";
    case "ready":
      return "待发布";
    case "success":
      return "成功";
    case "completed_with_issues":
      return "有问题";
    case "published":
      return "已发布";
    default:
      return status || "-";
  }
}

function getMarketplaceLabel(value?: string | null): string {
  if (!value) {
    return "未设置";
  }
  return value
    .replace("www.", "")
    .replace(".amazon.", " Amazon ")
    .replace(".com", "")
    .replace(".co.uk", " UK")
    .replace(".de", " DE")
    .replace(".jp", " JP");
}

function normalizeText(value?: string | null): string {
  return (value ?? "").toString().trim().toLowerCase();
}

async function apiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

async function withLoading(action: () => Promise<void>): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    await action();
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <section class="brand-card">
        <p class="eyebrow">Amazon Workflow</p>
        <h1>Family First</h1>
        <p class="brand-copy">
          原始层拆成商品族与变体，选品按 family，建档生成 1 个 SPU 和多个 SKU。
        </p>
        <div class="brand-tags">
          <span>Raw Family</span>
          <span>Variant Scope</span>
          <span>SPU + SKU</span>
        </div>
      </section>

      <nav class="nav-list">
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
          <em>{{ views.findIndex((item) => item.key === view.key) + 1 }}</em>
        </button>
      </nav>

      <section class="side-panel">
        <div class="side-title">
          <small>新采集</small>
          <h2>直接入库商品族</h2>
        </div>
        <label>
          <span>Amazon 链接</span>
          <input v-model="collectionUrl" type="text" placeholder="https://www.amazon.com/dp/..." />
        </label>
        <button type="button" :disabled="loading" @click="submitCollection">
          {{ loading ? "处理中..." : "开始采集" }}
        </button>
      </section>

      <section class="side-panel">
        <div class="side-title">
          <small>默认发布参数</small>
          <h2>草稿 / 发布</h2>
        </div>
        <label>
          <span>店铺名</span>
          <input v-model="defaultShopName" type="text" />
        </label>
        <label>
          <span>站点</span>
          <input v-model="defaultMarketplace" type="text" />
        </label>
      </section>
    </aside>

    <main class="content">
      <section class="hero-card">
        <div class="hero-copy">
          <p class="eyebrow">{{ heroContent.kicker }}</p>
          <h2>{{ heroContent.title }}</h2>
          <p>{{ heroContent.description }}</p>
        </div>
        <div class="hero-side">
          <p class="hero-note">{{ heroContent.aside }}</p>
          <button type="button" class="secondary-button" :disabled="loading" @click="refreshAll">
            刷新数据
          </button>
        </div>
      </section>

      <section class="metric-grid">
        <article v-for="card in summaryCards" :key="card.label" class="metric-card">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.hint }}</small>
        </article>
      </section>

      <p v-if="notice" class="notice success">{{ notice }}</p>
      <p v-if="error" class="notice error">{{ error }}</p>

      <section v-if="activeView === 'collections'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Tasks</p>
            <h3>采集任务记录</h3>
          </div>
          <p>任务完成后，原始层直接生成 family + variants，不再写入单体 raw snapshot。</p>
        </div>

        <div class="table-wrap" v-if="state.collections.length">
          <table>
            <thead>
              <tr>
                <th>任务号</th>
                <th>来源</th>
                <th>站点</th>
                <th>状态</th>
                <th>成功 / 总数</th>
                <th>完成时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="task in state.collections" :key="task.id">
                <td>{{ task.task_no }}</td>
                <td>{{ task.source_url }}</td>
                <td>{{ getMarketplaceLabel(task.marketplace) }}</td>
                <td>
                  <span class="status-pill" :data-status="task.status">
                    {{ getStatusLabel(task.status) }}
                  </span>
                </td>
                <td>{{ task.success_count }} / {{ task.total_count }}</td>
                <td>{{ formatDate(task.finished_at || task.created_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="empty-state">还没有采集任务。</p>
      </section>

      <section v-if="activeView === 'families'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Families</p>
            <h3>商品族列表</h3>
          </div>
          <p>每张卡代表一个 raw product family，卡内展开展示采集回来的原始变体。</p>
        </div>

        <div class="toolbar">
          <label class="toolbar-field grow">
            <span>搜索商品族</span>
            <input v-model="filters.familyQuery" type="text" placeholder="标题 / 品牌 / family key" />
          </label>
          <label class="toolbar-field">
            <span>站点</span>
            <select v-model="filters.familyMarketplace">
              <option v-for="option in familyMarketplaceOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </label>
        </div>

        <div class="catalog-grid" v-if="filteredFamilies.length">
          <article v-for="family in filteredFamilies" :key="family.id" class="catalog-card">
            <div class="catalog-media">
              <span class="market-badge">{{ getMarketplaceLabel(family.marketplace) }}</span>
              <img
                class="catalog-thumb"
                :src="family.main_image_url || family.variants[0]?.main_image_url || ''"
                :alt="family.title || 'family image'"
              />
            </div>

            <div class="catalog-body">
              <h4>{{ family.title || "未命名商品族" }}</h4>
              <div class="meta-line compact">
                <span>{{ family.brand || "品牌待补充" }}</span>
                <span>{{ familyLeadPrice(family) }}</span>
                <span>{{ family.variant_count }} 个变体</span>
                <span v-if="family.rating">{{ family.rating }}</span>
              </div>

              <div class="tag-row">
                <span v-for="dimension in family.variant_dimensions || []" :key="dimension" class="tag-chip">
                  {{ dimension }}
                </span>
              </div>

              <div class="card-actions">
                <span v-if="family.selection_status" class="status-pill" :data-status="family.selection_status">
                  {{ getStatusLabel(family.selection_status) }}
                </span>
                <span v-if="family.product_master_id" class="status-pill" data-status="converted">已生成 SPU</span>
                <button
                  type="button"
                  class="inline-button"
                  :disabled="Boolean(family.selection_id)"
                  @click="addToSelection(family.id)"
                >
                  {{ family.selection_id ? "已加入选品池" : "加入选品池" }}
                </button>
                <button
                  type="button"
                  class="secondary-button inline-button"
                  @click="familyExpandedState[family.id] = !familyExpandedState[family.id]"
                >
                  {{ familyExpandedState[family.id] ? "收起变体" : "展开变体" }}
                </button>
              </div>

              <div v-if="familyExpandedState[family.id]" class="variant-stack">
                <article v-for="variant in family.variants" :key="variant.id" class="variant-row">
                  <div>
                    <strong>{{ variant.asin || "无 ASIN" }}</strong>
                    <p class="cell-copy">{{ variantPreview(variant) }}</p>
                  </div>
                  <div class="variant-meta">
                    <span>{{ variant.price_text || "价格待补充" }}</span>
                    <span v-if="variant.source_url">
                      <a class="text-link" :href="variant.source_url" target="_blank" rel="noreferrer">查看链接</a>
                    </span>
                  </div>
                </article>
              </div>
            </div>
          </article>
        </div>
        <p v-else class="empty-state">当前没有匹配的商品族。</p>
      </section>

      <section v-if="activeView === 'selections'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Selections</p>
            <h3>选品池与变体范围</h3>
          </div>
          <p>创建 selection 后默认包含全部变体。这里可以缩小范围，再生成 SPU 和多 SKU。</p>
        </div>

        <div class="toolbar">
          <label class="toolbar-field grow">
            <span>搜索选品</span>
            <input v-model="filters.selectionQuery" type="text" placeholder="标题 / 品牌 / family key" />
          </label>
        </div>

        <div class="stack-list" v-if="filteredSelections.length">
          <article v-for="selection in filteredSelections" :key="selection.id" class="task-card">
            <div class="row-head">
              <div>
                <strong>{{ selection.family_title || "未命名商品族" }}</strong>
                <p class="hint-text">
                  {{ selection.family_brand || "品牌待补充" }} ·
                  {{ getMarketplaceLabel(selection.family_marketplace) }} ·
                  {{ selectionLeadPrice(selection) }} ·
                  {{ selectionCoverage(selection) }}
                </p>
              </div>
              <span class="status-pill" :data-status="selection.selection_status">
                {{ getStatusLabel(selection.selection_status) }}
              </span>
            </div>

            <div class="card-actions">
              <button
                type="button"
                class="secondary-button inline-button"
                @click="selectionExpandedState[selection.id] = !selectionExpandedState[selection.id]"
              >
                {{ selectionExpandedState[selection.id] ? "收起变体" : "展开变体" }}
              </button>
              <button type="button" class="inline-button" @click="saveSelectionScope(selection.id)">
                保存变体范围
              </button>
              <button
                type="button"
                class="inline-button"
                :disabled="selection.selection_status === 'converted'"
                @click="createProduct(selection.id)"
              >
                {{ selection.selection_status === "converted" ? "已建档" : "生成 SPU + SKU" }}
              </button>
            </div>

            <div v-if="selectionExpandedState[selection.id]" class="variant-stack">
              <label
                v-for="variant in selection.variants"
                :key="variant.id"
                class="variant-row selector-row"
              >
                <div class="selector-main">
                  <input
                    type="checkbox"
                    :checked="isVariantSelected(selection.id, variant.id)"
                    @change="toggleVariantInScope(selection.id, variant.id)"
                  />
                  <div>
                    <strong>{{ variant.asin || "无 ASIN" }}</strong>
                    <p class="cell-copy">{{ variantPreview(variant) }}</p>
                  </div>
                </div>
                <div class="variant-meta">
                  <span>{{ variant.price_text || "价格待补充" }}</span>
                </div>
              </label>
            </div>
          </article>
        </div>
        <p v-else class="empty-state">选品池为空，先去商品族列表加入候选。</p>
      </section>

      <section v-if="activeView === 'products'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Products</p>
            <h3>SPU 与多 SKU 建档结果</h3>
          </div>
          <p>每个 product master 来自一个 family 级 selection，其下 SKU 来自当前 variant scope。</p>
        </div>

        <div class="toolbar">
          <label class="toolbar-field grow">
            <span>搜索商品</span>
            <input v-model="filters.productQuery" type="text" placeholder="SPU / 商品名 / 品牌" />
          </label>
        </div>

        <div class="product-grid" v-if="filteredProducts.length">
          <article v-for="product in filteredProducts" :key="product.id" class="product-panel">
            <div class="product-head">
              <div>
                <p class="mini-code">{{ product.spu_code }}</p>
                <h4>{{ product.product_name }}</h4>
              </div>
              <span class="status-pill" :data-status="product.status">
                {{ getStatusLabel(product.status) }}
              </span>
            </div>

            <img
              v-if="product.family_main_image_url"
              class="catalog-thumb"
              :src="product.family_main_image_url"
              :alt="product.product_name"
            />

            <div class="meta-line">
              <span>{{ product.brand || "品牌待补充" }}</span>
              <span>{{ getMarketplaceLabel(product.target_marketplace) }}</span>
              <span>{{ product.variants.length }} 个 SKU</span>
              <span>默认成本 {{ formatNumber(product.default_cost) }}</span>
            </div>

            <div class="variant-stack">
              <article v-for="variant in product.variants" :key="variant.id" class="variant-row">
                <div>
                  <strong>{{ variant.sku }}</strong>
                  <p class="cell-copy">{{ variantPreview(variant) }}</p>
                </div>
                <div class="variant-meta">
                  <span>{{ variant.raw_asin || "-" }}</span>
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
        <p v-else class="empty-state">还没有商品主档。</p>
      </section>

      <section v-if="activeView === 'drafts'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Drafts</p>
            <h3>Listing 草稿编辑</h3>
          </div>
          <p>草稿层沿用多 SKU 结构，文案统一编辑，价格库存按 SKU 单独维护。</p>
        </div>

        <div class="toolbar">
          <label class="toolbar-field grow">
            <span>搜索草稿</span>
            <input v-model="filters.draftQuery" type="text" placeholder="商品名 / SPU / 店铺 / 站点" />
          </label>
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
              <small>{{ draft.shop_name }} · V{{ draft.current_version_no }}</small>
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
                    {{ selectedDraft.variants.length }} 个 SKU
                  </p>
                </div>
                <div class="editor-actions">
                  <button type="button" class="secondary-button" @click="saveDraft">保存草稿</button>
                  <button type="button" @click="publishDraft(selectedDraft.id)">模拟发布</button>
                </div>
              </div>

              <div class="draft-summary-card">
                <div class="summary-row">
                  <span>当前状态</span>
                  <strong>{{ getStatusLabel(draftEditor.status) }}</strong>
                </div>
                <div class="summary-metrics">
                  <article>
                    <span>SKU 总数</span>
                    <strong>{{ draftStats.totalSkuCount }}</strong>
                  </article>
                  <article>
                    <span>已填价格</span>
                    <strong>{{ draftStats.pricedSkuCount }}</strong>
                  </article>
                  <article>
                    <span>已填库存</span>
                    <strong>{{ draftStats.stockedSkuCount }}</strong>
                  </article>
                </div>
              </div>
            </div>

            <div class="draft-workspace">
              <div class="editor-card">
                <div class="subpanel-head">
                  <h4>文案编辑</h4>
                  <span>保存后会生成新版本</span>
                </div>
                <div class="editor-grid">
                  <label>
                    <span>标题</span>
                    <input v-model="draftEditor.title" type="text" />
                  </label>
                  <label>
                    <span>状态</span>
                    <select v-model="draftEditor.status">
                      <option value="draft">草稿</option>
                      <option value="reviewing">待分析</option>
                      <option value="ready">待发布</option>
                    </select>
                  </label>
                  <label class="full-span">
                    <span>五点卖点</span>
                    <textarea v-model="draftEditor.bulletText" rows="6" />
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
                        <span>
                          {{ item.level === "pass" ? "通过" : item.level === "warn" ? "提醒" : "缺失" }}
                        </span>
                      </div>
                      <p>{{ item.detail }}</p>
                    </article>
                  </div>
                </article>

                <article class="editor-card">
                  <div class="subpanel-head">
                    <h4>预览</h4>
                    <span>草稿视图</span>
                  </div>
                  <div class="preview-card">
                    <p class="preview-shop">{{ defaultShopName }} · {{ getMarketplaceLabel(selectedDraft.marketplace) }}</p>
                    <h5>{{ draftEditor.title || "这里显示草稿标题" }}</h5>
                    <div class="preview-meta">
                      <span>{{ draftStats.totalSkuCount }} 个 SKU</span>
                      <span>{{ draftStats.pricedSkuCount }} 个已填价格</span>
                      <span>{{ draftStats.stockedSkuCount }} 个有库存</span>
                    </div>
                    <ul class="preview-bullets">
                      <li v-for="bullet in draftPreviewBullets.slice(0, 5)" :key="bullet">{{ bullet }}</li>
                    </ul>
                    <p class="preview-description">
                      {{ draftEditor.description || "这里显示详情描述。" }}
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
                      <th>Seller SKU</th>
                      <th>规格</th>
                      <th>价格</th>
                      <th>库存</th>
                      <th>配送</th>
                      <th>外部编码</th>
                      <th>保存</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="variant in selectedDraft.variants" :key="variant.id">
                      <td>{{ variant.seller_sku }}</td>
                      <td>{{ variantPreview(variant) }}</td>
                      <td><input v-model.number="variant.price" type="number" min="0" step="0.01" /></td>
                      <td><input v-model.number="variant.quantity" type="number" min="0" step="1" /></td>
                      <td>
                        <select v-model="variant.fulfillment_channel">
                          <option value="FBM">FBM</option>
                          <option value="FBA">FBA</option>
                        </select>
                      </td>
                      <td><input v-model="variant.external_product_id" type="text" placeholder="UPC / EAN / GTIN" /></td>
                      <td>
                        <button type="button" class="inline-button" @click="saveDraftVariant(variant)">保存</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
        <p v-else class="empty-state">还没有草稿，先从商品中心创建一个。</p>
      </section>

      <section v-if="activeView === 'publish'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Publish</p>
            <h3>发布任务与 Live SKU</h3>
          </div>
          <p>这里展示模拟发布结果和已回写的 SKU 状态。</p>
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
            <p v-else class="empty-state">还没有发布任务。</p>
          </article>

          <article class="subpanel">
            <div class="subpanel-head">
              <h4>Live SKU</h4>
              <span>{{ state.liveListings.length }} 条</span>
            </div>
            <div v-if="state.liveListings.length" class="table-wrap slim">
              <table>
                <thead>
                  <tr>
                    <th>Seller SKU</th>
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
            <p v-else class="empty-state">还没有已回写的 SKU 状态。</p>
          </article>
        </div>
      </section>
    </main>
  </div>
</template>

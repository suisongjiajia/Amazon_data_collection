<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";

type ViewKey = "intake" | "selections" | "listing" | "publish";
type IntakeTab = "families" | "tasks";
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
  parent_asin?: string | null;
  source_url?: string | null;
  title?: string | null;
  price_text?: string | null;
  main_image_url?: string | null;
  size?: string | null;
  color?: string | null;
  variant_attributes?: Record<string, string> | null;
  snapshot_time?: string | null;
  raw_payload?: Record<string, unknown> | null;
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
  { key: "intake", label: "采集入库", meta: "采集链接、任务与商品族" },
  { key: "selections", label: "选品池", meta: "按 family 选品并圈定变体" },
  { key: "listing", label: "Listing 工作台", meta: "SPU 建档与草稿编辑" },
  { key: "publish", label: "发布中心", meta: "模拟发布与回写结果" },
];

const activeView = ref<ViewKey>("intake");
const intakeTab = ref<IntakeTab>("families");
const loading = ref(false);
const notice = ref("");
const error = ref("");
const collectionUrl = ref("");
const defaultShopName = ref("Demo Shop");
const defaultMarketplace = ref("www.amazon.com");
const selectedDraftId = ref<number | null>(null);
const selectedFamilyId = ref<number | null>(null);
const selectedSelectionId = ref<number | null>(null);
const expandedVariantId = ref<number | null>(null);

const filters = reactive({
  familyQuery: "",
  familyMarketplace: "all",
  selectionQuery: "",
  listingQuery: "",
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

const draftEditor = reactive({
  title: "",
  bulletText: "",
  description: "",
  searchTerms: "",
  status: "draft",
});

const heroContent = computed(() => {
  switch (activeView.value) {
    case "intake":
      return {
        kicker: "Intake",
        title: "采集入库：发起采集并管理商品族",
        description: "在同一模块完成链接采集、查看任务记录与浏览入库商品族。",
        aside: "商品族是后续选品与上架的原始数据层。",
      };
    case "selections":
      return {
        kicker: "Selection",
        title: "选品以商品族为单位，变体范围单独控制",
        description: "选品后默认纳入全量变体。你可以在这里缩小 variant scope，再生成 SPU 和多 SKU。",
        aside: "这一步决定了最终会创建哪些 SKU。",
      };
    case "listing":
      return {
        kicker: "Listing",
        title: "Listing 工作台：建档、草稿与发布前编辑",
        description: "以 SPU 为主查看建档结果，在同一页面创建和编辑 Listing 草稿。",
        aside: "发布前检查主要看文案完整度和 SKU 参数完整度。",
      };
    case "publish":
      return {
        kicker: "Publish",
        title: "发布任务与线上回写状态",
        description: "先确保模拟发布和错误定位闭环稳定，再接真实发布。",
        aside: "当前展示的是发布任务和已回写的 live SKU 状态。",
      };
  }
});

const summaryCards = computed(() => [
  {
    label: "采集入库",
    hint: `${state.collections.length} 任务 · ${state.families.length} 商品族`,
    value: String(state.families.length),
  },
  { label: "选品池", hint: "已创建 selection", value: String(state.selections.length) },
  {
    label: "Listing",
    hint: `${state.products.length} SPU · ${state.drafts.length} 草稿`,
    value: String(state.drafts.length || state.products.length),
  },
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

const filteredListingProducts = computed(() => {
  const query = filters.listingQuery.trim().toLowerCase();
  return state.products.filter((product) => {
    if (!query) {
      return true;
    }
    const drafts = getDraftsForProduct(product.id);
    const productMatches = [product.spu_code, product.product_name, product.brand].some((value) =>
      normalizeText(value).includes(query),
    );
    const draftMatches = drafts.some((draft) =>
      [draft.product_name, draft.spu_code, draft.shop_name, draft.marketplace, draft.title].some((value) =>
        normalizeText(value).includes(query),
      ),
    );
    return productMatches || draftMatches;
  });
});

const collectionListRows = computed(() =>
  state.collections.map((task) => {
    const linkedFamilies = state.families.filter((family) => family.task_id === task.id);
    const lead = linkedFamilies[0];
    const title =
      linkedFamilies.length > 1
        ? `${lead?.title ?? "未命名商品"} 等 ${linkedFamilies.length} 个商品族`
        : (lead?.title ?? "待解析标题");
    return {
      task,
      title,
      image: lead ? getFamilyImage(lead) : "",
      sourceUrl: task.source_url,
      marketplace: task.marketplace ?? lead?.marketplace,
    };
  }),
);

const selectedFamily = computed(() => {
  if (selectedFamilyId.value === null) {
    return null;
  }
  return state.families.find((family) => family.id === selectedFamilyId.value) ?? null;
});

const selectedSelection = computed(() => {
  if (selectedSelectionId.value === null) {
    return null;
  }
  return state.selections.find((selection) => selection.id === selectedSelectionId.value) ?? null;
});

const selectedSelectionFamily = computed(() => {
  if (!selectedSelection.value) {
    return null;
  }
  return getSelectionVariantFamily(selectedSelection.value);
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

watch(activeView, (view) => {
  if (view !== "intake") {
    selectedFamilyId.value = null;
    expandedVariantId.value = null;
  }
  if (view !== "selections") {
    selectedSelectionId.value = null;
  }
  if (view !== "listing") {
    selectedDraftId.value = null;
  }
});

watch(selectedFamilyId, () => {
  expandedVariantId.value = null;
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

    for (const selection of selections) {
      selectionScopeState[selection.id] = selection.variants.map((variant) => variant.id);
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
    activeView.value = "intake";
    intakeTab.value = "tasks";
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
    activeView.value = "listing";
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
    activeView.value = "listing";
    await refreshAll();
    const created = state.drafts.find((draft) => draft.product_master_id === productMasterId);
    if (created) {
      selectedDraftId.value = created.id;
    }
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

function getFamilyImage(family: RawProductFamily | Selection): string {
  if ("family_main_image_url" in family && family.family_main_image_url) {
    return family.family_main_image_url;
  }
  if ("main_image_url" in family && family.main_image_url) {
    return family.main_image_url;
  }
  const variants = "variants" in family ? family.variants : [];
  return variants[0]?.main_image_url ?? "";
}

function getFamilyStatusLabel(family: RawProductFamily): string {
  if (family.product_master_id) {
    return "已建档";
  }
  if (family.selection_status) {
    return getStatusLabel(family.selection_status);
  }
  return "已采集";
}

function getFamilyStatusKey(family: RawProductFamily): string {
  if (family.product_master_id) {
    return "converted";
  }
  if (family.selection_status) {
    return family.selection_status;
  }
  return "completed";
}

function getDraftImage(draft: ListingDraft): string {
  const product = state.products.find((item) => item.id === draft.product_master_id);
  return product?.family_main_image_url ?? "";
}

function truncateUrl(value?: string | null, maxLength = 56): string {
  if (!value) {
    return "—";
  }
  return value.length > maxLength ? `${value.slice(0, maxLength)}…` : value;
}

function openFamilyDetail(familyId: number): void {
  intakeTab.value = "families";
  selectedFamilyId.value = familyId;
  expandedVariantId.value = null;
}

function closeFamilyDetail(): void {
  selectedFamilyId.value = null;
  expandedVariantId.value = null;
}

function openSelectionDetail(selectionId: number): void {
  selectedSelectionId.value = selectionId;
  expandedVariantId.value = null;
}

function closeSelectionDetail(): void {
  selectedSelectionId.value = null;
  expandedVariantId.value = null;
}

function getFamilyContextForSelection(selection: Selection): RawProductFamily | null {
  return state.families.find((family) => family.id === selection.raw_product_family_id) ?? null;
}

function getSelectionVariantFamily(selection: Selection): RawProductFamily {
  const family = getFamilyContextForSelection(selection);
  if (family) {
    return family;
  }

  return {
    id: selection.raw_product_family_id,
    family_key: selection.family_key || "",
    title: selection.family_title,
    brand: selection.family_brand,
    marketplace: selection.family_marketplace,
    source_url: selection.family_source_url,
    variant_count: selection.family_variant_count,
    variants: selection.variants,
  };
}

function getDraftsForProduct(productId: number): ListingDraft[] {
  return state.drafts.filter((draft) => draft.product_master_id === productId);
}

function openDraftEditor(draftId: number): void {
  selectedDraftId.value = draftId;
}

function openListingForProduct(productId: number): void {
  const drafts = getDraftsForProduct(productId);
  if (drafts.length > 0) {
    selectedDraftId.value = drafts[0].id;
    return;
  }
  void createDraft(productId);
}

function toggleVariantDetail(variantId: number): void {
  expandedVariantId.value = expandedVariantId.value === variantId ? null : variantId;
}

function isVariantExpanded(variantId: number): boolean {
  return expandedVariantId.value === variantId;
}

function getVariantTitle(variant: RawProductVariant, family?: RawProductFamily | null): string {
  return variant.title || family?.title || "未命名变体";
}

function getVariantImage(variant: RawProductVariant): string {
  return variant.main_image_url ?? "";
}

function getVariantBulletPoints(
  variant: RawProductVariant,
  family?: RawProductFamily | null,
): string[] {
  const payload = variant.raw_payload;
  const fromPayload = payload?.bulletPoints;
  if (Array.isArray(fromPayload)) {
    const bullets = fromPayload.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
    if (bullets.length > 0) {
      return bullets;
    }
  }

  return (family?.bullet_points ?? []).filter((item) => item.trim().length > 0);
}

function getVariantAttributeEntries(variant: RawProductVariant): Array<[string, string]> {
  const entries: Array<[string, string]> = [];
  const seen = new Set<string>();

  for (const [key, value] of Object.entries(variant.variant_attributes ?? {})) {
    if (!value) {
      continue;
    }
    entries.push([key, value]);
    seen.add(key.toLowerCase());
  }

  if (variant.color && !seen.has("color")) {
    entries.unshift(["Color", variant.color]);
  }
  if (variant.size && !seen.has("size")) {
    entries.unshift(["Size", variant.size]);
  }

  return entries;
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
    </aside>

    <main class="content">
      <div class="content-top">
        <section class="hero-card hero-card-compact">
          <div class="hero-copy">
            <p class="eyebrow">{{ heroContent.kicker }}</p>
            <h2>{{ heroContent.title }}</h2>
          </div>
          <div class="hero-side">
            <button type="button" class="secondary-button" :disabled="loading" @click="refreshAll">
              刷新数据
            </button>
          </div>
        </section>

        <section class="metric-grid metric-grid-compact">
          <article v-for="card in summaryCards" :key="card.label" class="metric-card">
            <span>{{ card.label }}</span>
            <strong>{{ card.value }}</strong>
            <small>{{ card.hint }}</small>
          </article>
        </section>

        <p v-if="notice" class="notice success">{{ notice }}</p>
        <p v-if="error" class="notice error">{{ error }}</p>
      </div>

      <div class="content-scroll">
      <section v-if="activeView === 'intake'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Intake</p>
            <h3>{{ selectedFamily && intakeTab === 'families' ? "商品族详情" : "采集入库" }}</h3>
          </div>
          <p>
            {{
              selectedFamily && intakeTab === "families"
                ? "查看商品族完整信息与全部变体。"
                : "发起采集、查看任务记录，或浏览已入库的商品族。"
            }}
          </p>
        </div>

        <div class="action-bar">
          <label class="action-bar-field grow">
            <span>Amazon 采集链接</span>
            <input v-model="collectionUrl" type="text" placeholder="https://www.amazon.com/dp/..." />
          </label>
          <button type="button" class="action-bar-button" :disabled="loading" @click="submitCollection">
            {{ loading ? "处理中..." : "开始采集" }}
          </button>
        </div>

        <div v-if="!selectedFamily" class="module-tabs">
          <button
            type="button"
            class="module-tab"
            :class="{ active: intakeTab === 'families' }"
            @click="intakeTab = 'families'"
          >
            商品族
          </button>
          <button
            type="button"
            class="module-tab"
            :class="{ active: intakeTab === 'tasks' }"
            @click="intakeTab = 'tasks'"
          >
            任务记录
          </button>
        </div>

        <template v-if="intakeTab === 'tasks' && !selectedFamily">
          <div class="table-wrap list-table" v-if="collectionListRows.length">
            <table>
              <thead>
                <tr>
                  <th class="col-product">商品</th>
                  <th>采集链接</th>
                  <th>站点</th>
                  <th>状态</th>
                  <th>成功 / 总数</th>
                  <th>完成时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in collectionListRows" :key="row.task.id">
                  <td>
                    <div class="list-product-cell">
                      <div class="list-thumb" :class="{ placeholder: !row.image }">
                        <img v-if="row.image" :src="row.image" :alt="row.title" />
                        <span v-else>无图</span>
                      </div>
                      <div class="list-product-copy">
                        <strong class="list-title">{{ row.title }}</strong>
                        <span class="list-subtitle">{{ row.task.task_no }}</span>
                      </div>
                    </div>
                  </td>
                  <td>
                    <a
                      class="text-link url-cell"
                      :href="row.sourceUrl"
                      target="_blank"
                      rel="noreferrer"
                      :title="row.sourceUrl"
                    >
                      {{ truncateUrl(row.sourceUrl) }}
                    </a>
                  </td>
                  <td>{{ getMarketplaceLabel(row.marketplace) }}</td>
                  <td>
                    <span class="status-pill" :data-status="row.task.status">
                      {{ getStatusLabel(row.task.status) }}
                    </span>
                  </td>
                  <td>{{ row.task.success_count }} / {{ row.task.total_count }}</td>
                  <td>{{ formatDate(row.task.finished_at || row.task.created_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="empty-state">还没有采集任务。</p>
        </template>

        <template v-else-if="intakeTab === 'families' && !selectedFamily">
          <div class="toolbar toolbar-compact">
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

          <div class="table-wrap list-table" v-if="filteredFamilies.length">
            <table>
              <thead>
                <tr>
                  <th class="col-product">商品</th>
                  <th>采集链接</th>
                  <th>站点</th>
                  <th>状态</th>
                  <th>变体数</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="family in filteredFamilies" :key="family.id">
                  <td>
                    <div class="list-product-cell">
                      <div class="list-thumb" :class="{ placeholder: !getFamilyImage(family) }">
                        <img v-if="getFamilyImage(family)" :src="getFamilyImage(family)" :alt="family.title || 'family'" />
                        <span v-else>无图</span>
                      </div>
                      <div class="list-product-copy">
                        <strong class="list-title">{{ family.title || "未命名商品族" }}</strong>
                        <span class="list-subtitle">{{ family.brand || "品牌待补充" }} · {{ familyLeadPrice(family) }}</span>
                      </div>
                    </div>
                  </td>
                  <td>
                    <a
                      v-if="family.source_url"
                      class="text-link url-cell"
                      :href="family.source_url"
                      target="_blank"
                      rel="noreferrer"
                      :title="family.source_url"
                    >
                      {{ truncateUrl(family.source_url) }}
                    </a>
                    <span v-else>—</span>
                  </td>
                  <td>{{ getMarketplaceLabel(family.marketplace) }}</td>
                  <td>
                    <span class="status-pill" :data-status="getFamilyStatusKey(family)">
                      {{ getFamilyStatusLabel(family) }}
                    </span>
                  </td>
                  <td>{{ family.variant_count }}</td>
                  <td>
                    <div class="list-actions">
                      <button type="button" class="secondary-button inline-button" @click="openFamilyDetail(family.id)">
                        查看详情
                      </button>
                      <button
                        type="button"
                        class="inline-button"
                        :disabled="Boolean(family.selection_id)"
                        @click="addToSelection(family.id)"
                      >
                        {{ family.selection_id ? "已入选" : "加入选品" }}
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="empty-state">当前没有匹配的商品族。</p>
        </template>

        <div v-else-if="intakeTab === 'families'" class="detail-panel">
          <button type="button" class="secondary-button back-button" @click="closeFamilyDetail">返回列表</button>

          <div class="detail-hero">
            <div class="list-thumb detail-thumb" :class="{ placeholder: !getFamilyImage(selectedFamily) }">
              <img
                v-if="getFamilyImage(selectedFamily)"
                :src="getFamilyImage(selectedFamily)"
                :alt="selectedFamily.title || 'family'"
              />
              <span v-else>无图</span>
            </div>
            <div class="detail-hero-copy">
              <h4>{{ selectedFamily.title || "未命名商品族" }}</h4>
              <div class="meta-line compact">
                <span>{{ selectedFamily.brand || "品牌待补充" }}</span>
                <span>{{ getMarketplaceLabel(selectedFamily.marketplace) }}</span>
                <span>{{ familyLeadPrice(selectedFamily) }}</span>
                <span v-if="selectedFamily.rating">{{ selectedFamily.rating }}</span>
                <span v-if="selectedFamily.review_count">{{ selectedFamily.review_count }}</span>
              </div>
              <div class="tag-row">
                <span v-for="dimension in selectedFamily.variant_dimensions || []" :key="dimension" class="tag-chip">
                  {{ dimension }}
                </span>
              </div>
              <div class="card-actions">
                <span class="status-pill" :data-status="getFamilyStatusKey(selectedFamily)">
                  {{ getFamilyStatusLabel(selectedFamily) }}
                </span>
                <a
                  v-if="selectedFamily.source_url"
                  class="text-link"
                  :href="selectedFamily.source_url"
                  target="_blank"
                  rel="noreferrer"
                >
                  打开采集链接
                </a>
                <button
                  type="button"
                  class="inline-button"
                  :disabled="Boolean(selectedFamily.selection_id)"
                  @click="addToSelection(selectedFamily.id)"
                >
                  {{ selectedFamily.selection_id ? "已加入选品池" : "加入选品池" }}
                </button>
              </div>
            </div>
          </div>

          <div v-if="selectedFamily.bullet_points?.length" class="detail-block">
            <h5>五点描述</h5>
            <ul class="bullet-preview">
              <li v-for="bullet in selectedFamily.bullet_points" :key="bullet">{{ bullet }}</li>
            </ul>
          </div>

          <div class="detail-block">
            <div class="subpanel-head">
              <h5>变体列表</h5>
              <span>{{ selectedFamily.variant_count }} 个子类</span>
            </div>
            <div class="variant-card-list">
              <article
                v-for="variant in selectedFamily.variants"
                :key="variant.id"
                class="variant-card"
                :class="{ expanded: isVariantExpanded(variant.id) }"
              >
                <div class="variant-card-head">
                  <div class="variant-card-media">
                    <img
                      v-if="getVariantImage(variant)"
                      :src="getVariantImage(variant)"
                      :alt="getVariantTitle(variant, selectedFamily)"
                    />
                    <span v-else class="variant-card-placeholder">无图</span>
                  </div>

                  <div class="variant-card-body">
                    <div class="variant-card-line">
                      <h6 class="variant-card-title">{{ getVariantTitle(variant, selectedFamily) }}</h6>
                      <span class="spec-chip">{{ variantPreview(variant) }}</span>
                      <span v-if="variant.asin" class="asin-chip">{{ variant.asin }}</span>
                    </div>
                  </div>

                  <div class="variant-card-side">
                    <strong class="variant-price-text">{{ variant.price_text || "—" }}</strong>
                    <div class="variant-card-actions">
                      <button
                        type="button"
                        class="ghost-button"
                        :class="{ active: isVariantExpanded(variant.id) }"
                        @click="toggleVariantDetail(variant.id)"
                      >
                        {{ isVariantExpanded(variant.id) ? "收起" : "详情" }}
                      </button>
                      <a
                        v-if="variant.source_url"
                        class="ghost-button ghost-link"
                        :href="variant.source_url"
                        target="_blank"
                        rel="noreferrer"
                      >
                        Amazon
                      </a>
                    </div>
                  </div>
                </div>

                <div v-if="isVariantExpanded(variant.id)" class="variant-card-detail">
                  <div class="variant-detail-meta">
                    <div v-if="variant.parent_asin" class="variant-meta-item">
                      <span>Parent ASIN</span>
                      <strong>{{ variant.parent_asin }}</strong>
                    </div>
                    <div v-if="variant.snapshot_time" class="variant-meta-item">
                      <span>采集时间</span>
                      <strong>{{ formatDate(variant.snapshot_time) }}</strong>
                    </div>
                    <div v-if="variant.source_url" class="variant-meta-item variant-meta-item-wide">
                      <span>采集链接</span>
                      <a class="text-link" :href="variant.source_url" target="_blank" rel="noreferrer">
                        {{ truncateUrl(variant.source_url, 80) }}
                      </a>
                    </div>
                  </div>

                  <div v-if="getVariantBulletPoints(variant, selectedFamily).length" class="variant-detail-section">
                    <strong>五点描述</strong>
                    <ul class="variant-bullet-list">
                      <li v-for="bullet in getVariantBulletPoints(variant, selectedFamily)" :key="bullet">
                        {{ bullet }}
                      </li>
                    </ul>
                  </div>

                  <div v-if="getVariantAttributeEntries(variant).length" class="variant-attr-grid">
                    <article
                      v-for="[key, value] in getVariantAttributeEntries(variant)"
                      :key="`${variant.id}-${key}`"
                    >
                      <span>{{ key }}</span>
                      <strong>{{ value }}</strong>
                    </article>
                  </div>
                </div>
              </article>
            </div>
          </div>
        </div>
      </section>

      <section v-if="activeView === 'selections'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Selections</p>
            <h3>{{ selectedSelection ? "选品详情" : "选品池列表" }}</h3>
          </div>
          <p>
            {{
              selectedSelection
                ? "调整变体范围后保存，再生成 SPU 和多 SKU。"
                : "列表浏览已选商品族，进入详情可管理变体范围。"
            }}
          </p>
        </div>

        <template v-if="!selectedSelection">
          <div class="toolbar toolbar-compact">
            <label class="toolbar-field grow">
              <span>搜索选品</span>
              <input v-model="filters.selectionQuery" type="text" placeholder="标题 / 品牌 / family key" />
            </label>
          </div>

          <div class="table-wrap list-table" v-if="filteredSelections.length">
            <table>
              <thead>
                <tr>
                  <th class="col-product">商品</th>
                  <th>采集链接</th>
                  <th>站点</th>
                  <th>状态</th>
                  <th>变体范围</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="selection in filteredSelections" :key="selection.id">
                  <td>
                    <div class="list-product-cell">
                      <div class="list-thumb" :class="{ placeholder: !getFamilyImage(selection) }">
                        <img
                          v-if="getFamilyImage(selection)"
                          :src="getFamilyImage(selection)"
                          :alt="selection.family_title || 'selection'"
                        />
                        <span v-else>无图</span>
                      </div>
                      <div class="list-product-copy">
                        <strong class="list-title">{{ selection.family_title || "未命名商品族" }}</strong>
                        <span class="list-subtitle">
                          {{ selection.family_brand || "品牌待补充" }} · {{ selectionLeadPrice(selection) }}
                        </span>
                      </div>
                    </div>
                  </td>
                  <td>
                    <a
                      v-if="selection.family_source_url"
                      class="text-link url-cell"
                      :href="selection.family_source_url"
                      target="_blank"
                      rel="noreferrer"
                      :title="selection.family_source_url"
                    >
                      {{ truncateUrl(selection.family_source_url) }}
                    </a>
                    <span v-else>—</span>
                  </td>
                  <td>{{ getMarketplaceLabel(selection.family_marketplace) }}</td>
                  <td>
                    <span class="status-pill" :data-status="selection.selection_status">
                      {{ getStatusLabel(selection.selection_status) }}
                    </span>
                  </td>
                  <td>{{ selectionCoverage(selection) }}</td>
                  <td>
                    <div class="list-actions">
                      <button type="button" class="secondary-button inline-button" @click="openSelectionDetail(selection.id)">
                        查看详情
                      </button>
                      <button
                        type="button"
                        class="inline-button"
                        :disabled="selection.selection_status === 'converted'"
                        @click="createProduct(selection.id)"
                      >
                        {{ selection.selection_status === "converted" ? "已建档" : "生成 SPU" }}
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="empty-state">选品池为空，先去商品族列表加入候选。</p>
        </template>

        <div v-else class="detail-panel">
          <button type="button" class="secondary-button back-button" @click="closeSelectionDetail">返回列表</button>

          <div class="detail-hero">
            <div class="list-thumb detail-thumb" :class="{ placeholder: !getFamilyImage(selectedSelection) }">
              <img
                v-if="getFamilyImage(selectedSelection)"
                :src="getFamilyImage(selectedSelection)"
                :alt="selectedSelection.family_title || 'selection'"
              />
              <span v-else>无图</span>
            </div>
            <div class="detail-hero-copy">
              <h4>{{ selectedSelection.family_title || "未命名商品族" }}</h4>
              <div class="meta-line compact">
                <span>{{ selectedSelection.family_brand || "品牌待补充" }}</span>
                <span>{{ getMarketplaceLabel(selectedSelection.family_marketplace) }}</span>
                <span>{{ selectionLeadPrice(selectedSelection) }}</span>
                <span>{{ selectionCoverage(selectedSelection) }}</span>
              </div>
              <div class="card-actions">
                <span class="status-pill" :data-status="selectedSelection.selection_status">
                  {{ getStatusLabel(selectedSelection.selection_status) }}
                </span>
                <button type="button" class="inline-button" @click="saveSelectionScope(selectedSelection.id)">
                  保存变体范围
                </button>
                <button
                  type="button"
                  class="inline-button"
                  :disabled="selectedSelection.selection_status === 'converted'"
                  @click="createProduct(selectedSelection.id)"
                >
                  {{ selectedSelection.selection_status === "converted" ? "已建档" : "生成 SPU + SKU" }}
                </button>
              </div>
            </div>
          </div>

          <div class="detail-block">
            <div class="subpanel-head">
              <h5>变体范围</h5>
              <span>勾选需要纳入建档的变体，点击详情查看完整信息</span>
            </div>
            <div class="variant-card-list">
              <article
                v-for="variant in selectedSelection.variants"
                :key="variant.id"
                class="variant-card variant-card-selectable"
                :class="{
                  expanded: isVariantExpanded(variant.id),
                  selected: isVariantSelected(selectedSelection.id, variant.id),
                }"
              >
                <div class="variant-card-head">
                  <label class="variant-select-check" @click.stop>
                    <input
                      type="checkbox"
                      :checked="isVariantSelected(selectedSelection.id, variant.id)"
                      @change="toggleVariantInScope(selectedSelection.id, variant.id)"
                    />
                  </label>

                  <div class="variant-card-media">
                    <img
                      v-if="getVariantImage(variant)"
                      :src="getVariantImage(variant)"
                      :alt="getVariantTitle(variant, selectedSelectionFamily)"
                    />
                    <span v-else class="variant-card-placeholder">无图</span>
                  </div>

                  <div class="variant-card-body">
                    <div class="variant-card-line">
                      <h6 class="variant-card-title">
                        {{ getVariantTitle(variant, selectedSelectionFamily) }}
                      </h6>
                      <span class="spec-chip">{{ variantPreview(variant) }}</span>
                      <span v-if="variant.asin" class="asin-chip">{{ variant.asin }}</span>
                    </div>
                  </div>

                  <div class="variant-card-side">
                    <strong class="variant-price-text">{{ variant.price_text || "—" }}</strong>
                    <div class="variant-card-actions">
                      <button
                        type="button"
                        class="ghost-button"
                        :class="{ active: isVariantExpanded(variant.id) }"
                        @click="toggleVariantDetail(variant.id)"
                      >
                        {{ isVariantExpanded(variant.id) ? "收起" : "详情" }}
                      </button>
                      <a
                        v-if="variant.source_url"
                        class="ghost-button ghost-link"
                        :href="variant.source_url"
                        target="_blank"
                        rel="noreferrer"
                      >
                        Amazon
                      </a>
                    </div>
                  </div>
                </div>

                <div v-if="isVariantExpanded(variant.id)" class="variant-card-detail">
                  <div class="variant-detail-meta">
                    <div v-if="variant.parent_asin" class="variant-meta-item">
                      <span>Parent ASIN</span>
                      <strong>{{ variant.parent_asin }}</strong>
                    </div>
                    <div v-if="variant.snapshot_time" class="variant-meta-item">
                      <span>采集时间</span>
                      <strong>{{ formatDate(variant.snapshot_time) }}</strong>
                    </div>
                    <div v-if="variant.source_url" class="variant-meta-item variant-meta-item-wide">
                      <span>采集链接</span>
                      <a class="text-link" :href="variant.source_url" target="_blank" rel="noreferrer">
                        {{ truncateUrl(variant.source_url, 80) }}
                      </a>
                    </div>
                  </div>

                  <div
                    v-if="selectedSelectionFamily && getVariantBulletPoints(variant, selectedSelectionFamily).length"
                    class="variant-detail-section"
                  >
                    <strong>五点描述</strong>
                    <ul class="variant-bullet-list">
                      <li
                        v-for="bullet in getVariantBulletPoints(variant, selectedSelectionFamily)"
                        :key="bullet"
                      >
                        {{ bullet }}
                      </li>
                    </ul>
                  </div>

                  <div v-if="getVariantAttributeEntries(variant).length" class="variant-attr-grid">
                    <article
                      v-for="[key, value] in getVariantAttributeEntries(variant)"
                      :key="`${variant.id}-${key}`"
                    >
                      <span>{{ key }}</span>
                      <strong>{{ value }}</strong>
                    </article>
                  </div>
                </div>
              </article>
            </div>
          </div>
        </div>
      </section>

      <section v-if="activeView === 'listing'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Listing</p>
            <h3>Listing 工作台</h3>
          </div>
          <p>以 SPU 为主查看建档结果，在同一页面创建和编辑 Listing 草稿。</p>
        </div>

        <div class="action-bar action-bar-muted">
          <label class="action-bar-field">
            <span>店铺名</span>
            <input v-model="defaultShopName" type="text" />
          </label>
          <label class="action-bar-field">
            <span>站点</span>
            <input v-model="defaultMarketplace" type="text" />
          </label>
        </div>

        <div class="toolbar toolbar-compact">
          <label class="toolbar-field grow">
            <span>搜索 SPU / 草稿</span>
            <input v-model="filters.listingQuery" type="text" placeholder="SPU / 商品名 / 店铺 / 站点 / 标题" />
          </label>
        </div>

        <div class="table-wrap list-table" v-if="filteredListingProducts.length">
          <table>
            <thead>
              <tr>
                <th class="col-product">商品</th>
                <th>SPU</th>
                <th>站点</th>
                <th>状态</th>
                <th>SKU 数</th>
                <th>草稿</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="product in filteredListingProducts"
                :key="product.id"
                :class="{ 'row-active': selectedDraft?.product_master_id === product.id }"
              >
                <td>
                  <div class="list-product-cell">
                    <div class="list-thumb" :class="{ placeholder: !product.family_main_image_url }">
                      <img
                        v-if="product.family_main_image_url"
                        :src="product.family_main_image_url"
                        :alt="product.product_name"
                      />
                      <span v-else>无图</span>
                    </div>
                    <div class="list-product-copy">
                      <strong class="list-title">{{ product.product_name }}</strong>
                      <span class="list-subtitle">{{ product.brand || "品牌待补充" }}</span>
                    </div>
                  </div>
                </td>
                <td>{{ product.spu_code }}</td>
                <td>{{ getMarketplaceLabel(product.target_marketplace) }}</td>
                <td>
                  <span class="status-pill" :data-status="product.status">
                    {{ getStatusLabel(product.status) }}
                  </span>
                </td>
                <td>{{ product.variants.length }}</td>
                <td>{{ getDraftsForProduct(product.id).length }}</td>
                <td>
                  <button
                    v-if="getDraftsForProduct(product.id).length"
                    type="button"
                    class="secondary-button inline-button"
                    @click="openListingForProduct(product.id)"
                  >
                    编辑草稿
                  </button>
                  <button v-else type="button" class="inline-button" @click="createDraft(product.id)">
                    生成草稿
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="empty-state">还没有商品主档，请先从选品池建档。</p>

        <div
          v-if="selectedDraft && getDraftsForProduct(selectedDraft.product_master_id).length > 1"
          class="module-tabs module-tabs-inline"
        >
          <button
            v-for="draft in getDraftsForProduct(selectedDraft.product_master_id)"
            :key="draft.id"
            type="button"
            class="module-tab"
            :class="{ active: selectedDraftId === draft.id }"
            @click="openDraftEditor(draft.id)"
          >
            {{ draft.shop_name }} · V{{ draft.current_version_no }}
          </button>
        </div>

        <div v-if="selectedDraft" class="draft-main draft-main-below">
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
      </section>

      <section v-if="activeView === 'publish'" class="panel-shell">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Publish</p>
            <h3>发布中心列表</h3>
          </div>
          <p>发布任务与已回写 Live SKU 均以列表展示。</p>
        </div>

        <div class="action-bar action-bar-muted">
          <label class="action-bar-field">
            <span>店铺名</span>
            <input v-model="defaultShopName" type="text" />
          </label>
          <label class="action-bar-field">
            <span>站点</span>
            <input v-model="defaultMarketplace" type="text" />
          </label>
        </div>

        <div class="detail-block">
          <div class="subpanel-head">
            <h4>发布任务</h4>
            <span>{{ state.publishTasks.length }} 条</span>
          </div>
          <div class="table-wrap list-table" v-if="state.publishTasks.length">
            <table>
              <thead>
                <tr>
                  <th>任务号</th>
                  <th>店铺</th>
                  <th>站点</th>
                  <th>类型</th>
                  <th>状态</th>
                  <th>成功 / 总数</th>
                  <th>完成时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="task in state.publishTasks" :key="task.id">
                  <td>{{ task.task_no }}</td>
                  <td>{{ task.shop_name || "—" }}</td>
                  <td>{{ getMarketplaceLabel(task.marketplace) }}</td>
                  <td>{{ task.submit_type === "simulation" ? "模拟" : "手动" }}</td>
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
          <p v-else class="empty-state">还没有发布任务。</p>
        </div>

        <div class="detail-block">
          <div class="subpanel-head">
            <h4>Live SKU</h4>
            <span>{{ state.liveListings.length }} 条</span>
          </div>
          <div class="table-wrap list-table" v-if="state.liveListings.length">
            <table>
              <thead>
                <tr>
                  <th>Seller SKU</th>
                  <th>ASIN</th>
                  <th>状态</th>
                  <th>店铺</th>
                  <th>站点</th>
                  <th>价格</th>
                  <th>库存</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in state.liveListings" :key="item.id">
                  <td>{{ item.seller_sku }}</td>
                  <td>{{ item.asin || "—" }}</td>
                  <td>
                    <span class="status-pill" :data-status="item.listing_status">
                      {{ getStatusLabel(item.listing_status) }}
                    </span>
                  </td>
                  <td>{{ item.shop_name }}</td>
                  <td>{{ getMarketplaceLabel(item.marketplace) }}</td>
                  <td>{{ formatNumber(item.price) }}</td>
                  <td>{{ item.quantity }}</td>
                  <td>{{ formatDate(item.updated_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="empty-state">还没有已回写的 SKU 状态。</p>
        </div>
      </section>
      </div>
    </main>
  </div>
</template>

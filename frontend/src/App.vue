<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";

import IntakeView from "./components/IntakeView.vue";
import ListingView from "./components/ListingView.vue";
import PublishView from "./components/PublishView.vue";
import SelectionsView from "./components/SelectionsView.vue";
import { apiRequest } from "./lib/api";
import type {
  CollectionListRow,
  DraftEditorState,
  ListingDraft,
  ListingDraftVariant,
  ListingLive,
  ProductMaster,
  PublishTask,
  RawProductFamily,
  RawProductVariant,
  Selection,
  ValidationItem,
  ViewDefinition,
  ViewKey,
  WorkflowFilters,
  WorkflowState,
} from "./types/workflow";
import type { WorkflowActions, WorkflowHelpers } from "./types/view-context";

const views: ViewDefinition[] = [
  { key: "intake", label: "Intake", meta: "Collect URLs and review raw families" },
  { key: "selections", label: "Selections", meta: "Control variant scope before SPU creation" },
  { key: "listing", label: "Listing", meta: "Create SPUs, drafts, and SKU content" },
  { key: "publish", label: "Publish", meta: "Simulate publishing and inspect live SKUs" },
];

const activeView = ref<ViewKey>("intake");
const intakeTab = ref<"families" | "tasks">("families");
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

const ui = reactive({
  activeView,
  intakeTab,
  loading,
  notice,
  error,
  collectionUrl,
  defaultShopName,
  defaultMarketplace,
  selectedDraftId,
  selectedFamilyId,
  selectedSelectionId,
  expandedVariantId,
});

const filters = reactive<WorkflowFilters>({
  familyQuery: "",
  familyMarketplace: "all",
  selectionQuery: "",
  listingQuery: "",
});

const state = reactive<WorkflowState>({
  collections: [],
  families: [],
  selections: [],
  products: [],
  drafts: [],
  publishTasks: [],
  liveListings: [],
});

const selectionScopeState = reactive<Record<number, number[]>>({});

const draftEditor = reactive<DraftEditorState>({
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
        title: "Collect product families and review the raw catalog layer",
      };
    case "selections":
      return {
        kicker: "Selection",
        title: "Lock variant scope before generating SPUs and SKUs",
      };
    case "listing":
      return {
        kicker: "Listing",
        title: "Manage SPUs, listing drafts, and SKU-level content",
      };
    case "publish":
      return {
        kicker: "Publish",
        title: "Track publish tasks and simulated live listings",
      };
  }
});

const summaryCards = computed(() => [
  {
    label: "Families",
    hint: `${state.collections.length} tasks`,
    value: String(state.families.length),
  },
  {
    label: "Selections",
    hint: "review pool",
    value: String(state.selections.length),
  },
  {
    label: "Drafts",
    hint: `${state.products.length} SPUs`,
    value: String(state.drafts.length || state.products.length),
  },
  {
    label: "Live SKU",
    hint: "published records",
    value: String(state.liveListings.length),
  },
]);

const familyMarketplaceOptions = computed(() => {
  const values = Array.from(new Set(state.families.map((item) => item.marketplace).filter(Boolean))) as string[];
  return [{ value: "all", label: "All marketplaces" }].concat(
    values.map((value) => ({ value, label: getMarketplaceLabel(value) })),
  );
});

const filteredFamilies = computed(() => {
  const query = filters.familyQuery.trim().toLowerCase();
  return state.families.filter((family) => {
    const matchesQuery =
      query.length === 0 ||
      [family.title, family.brand, family.family_key].some((value) => normalizeText(value).includes(query));
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

const collectionListRows = computed<CollectionListRow[]>(() =>
  state.collections.map((task) => {
    const linkedFamilies = state.families.filter((family) => family.task_id === task.id);
    const lead = linkedFamilies[0];
    const title =
      linkedFamilies.length > 1
        ? `${lead?.title ?? "Unnamed family"} +${linkedFamilies.length - 1} more`
        : (lead?.title ?? "Pending title");
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
      label: "Title length",
      detail:
        titleLength >= 80
          ? `Current length: ${titleLength}`
          : `Current length: ${titleLength}, expand it before publish`,
      level: titleLength >= 80 ? "pass" : titleLength >= 45 ? "warn" : "fail",
    },
    {
      label: "Bullet count",
      detail:
        bulletCount >= 5
          ? `Prepared ${bulletCount} bullets`
          : `Prepared ${bulletCount} bullets, target at least 5`,
      level: bulletCount >= 5 ? "pass" : bulletCount >= 3 ? "warn" : "fail",
    },
    {
      label: "Description",
      detail:
        descriptionLength >= 120
          ? `Current length: ${descriptionLength}`
          : `Current length: ${descriptionLength}, expand it before publish`,
      level: descriptionLength >= 120 ? "pass" : descriptionLength >= 50 ? "warn" : "fail",
    },
    {
      label: "SKU pricing",
      detail: `${stats.pricedSkuCount}/${stats.totalSkuCount} SKUs priced`,
      level:
        stats.totalSkuCount > 0 && stats.pricedSkuCount === stats.totalSkuCount
          ? "pass"
          : stats.pricedSkuCount > 0
            ? "warn"
            : "fail",
    },
    {
      label: "SKU stock",
      detail: `${stats.stockedSkuCount}/${stats.totalSkuCount} SKUs stocked`,
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
      apiRequest("/api/collections") as Promise<WorkflowState["collections"]>,
      apiRequest("/api/raw-product-families") as Promise<WorkflowState["families"]>,
      apiRequest("/api/selections") as Promise<WorkflowState["selections"]>,
      apiRequest("/api/products") as Promise<WorkflowState["products"]>,
      apiRequest("/api/listing-drafts") as Promise<WorkflowState["drafts"]>,
      apiRequest("/api/publish-tasks") as Promise<WorkflowState["publishTasks"]>,
      apiRequest("/api/listing-live") as Promise<WorkflowState["liveListings"]>,
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
    error.value = "Please enter an Amazon URL first.";
    return;
  }

  await withLoading(async () => {
    await apiRequest("/api/collections", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    notice.value = "Collection task submitted and saved.";
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
    notice.value = "Family added to the selection pool.";
    activeView.value = "selections";
    await refreshAll();
  });
}

async function saveSelectionScope(selectionId: number): Promise<void> {
  const variantIds = selectionScopeState[selectionId] ?? [];
  if (variantIds.length === 0) {
    error.value = "Keep at least one variant in scope.";
    return;
  }

  await withLoading(async () => {
    await apiRequest(`/api/selections/${selectionId}/variant-scope`, {
      method: "PUT",
      body: JSON.stringify({ raw_product_variant_ids: variantIds }),
    });
    notice.value = "Variant scope updated.";
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
    notice.value = "SPU and SKU records created.";
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
    notice.value = "Listing draft created.";
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
    await apiRequest(`/api/listing-drafts/${selectedDraft.value.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: draftEditor.title,
        bullet_points: draftPreviewBullets.value,
        description: draftEditor.description,
        search_terms: draftEditor.searchTerms,
        status: draftEditor.status,
      }),
    });
    notice.value = "Draft saved.";
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
    notice.value = `SKU ${variant.seller_sku} saved.`;
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
    notice.value = "Publish simulation completed.";
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
  return [variant.color, variant.size].filter(Boolean).join(" / ") || "Default variant";
}

function selectionCoverage(selection: Selection): string {
  return `${selection.selected_variant_count}/${selection.family_variant_count} variants`;
}

function familyLeadPrice(family: RawProductFamily): string {
  return family.variants.find((variant) => normalizeText(variant.price_text).length > 0)?.price_text ?? "Price pending";
}

function selectionLeadPrice(selection: Selection): string {
  return selection.variants.find((variant) => normalizeText(variant.price_text).length > 0)?.price_text ?? "Price pending";
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
      return "Completed";
    case "running":
      return "Running";
    case "failed":
      return "Failed";
    case "reviewing":
      return "Reviewing";
    case "converted":
      return "Converted";
    case "draft":
      return "Draft";
    case "ready":
      return "Ready";
    case "success":
      return "Success";
    case "completed_with_issues":
      return "With issues";
    case "published":
      return "Published";
    default:
      return status || "-";
  }
}

function getMarketplaceLabel(value?: string | null): string {
  if (!value) {
    return "Not set";
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
  return family.main_image_url ?? family.variants[0]?.main_image_url ?? "";
}

function getFamilyStatusLabel(family: RawProductFamily): string {
  if (family.product_master_id) {
    return "Converted";
  }
  if (family.selection_id) {
    return "In selection";
  }
  return "Collected";
}

function getFamilyStatusKey(family: RawProductFamily): string {
  if (family.product_master_id) {
    return "converted";
  }
  if (family.selection_id) {
    return family.selection_status || "reviewing";
  }
  return "completed";
}

function getDraftImage(draft: ListingDraft): string {
  return state.products.find((product) => product.id === draft.product_master_id)?.family_main_image_url ?? "";
}

function truncateUrl(value?: string | null, maxLength = 56): string {
  if (!value) {
    return "-";
  }
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 3)}...`;
}

function openFamilyDetail(familyId: number): void {
  selectedFamilyId.value = familyId;
}

function closeFamilyDetail(): void {
  selectedFamilyId.value = null;
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
  return (
    getFamilyContextForSelection(selection) ?? {
      id: selection.raw_product_family_id,
      family_key: selection.family_key ?? String(selection.raw_product_family_id),
      marketplace: selection.family_marketplace,
      source_url: selection.family_source_url,
      title: selection.family_title,
      brand: selection.family_brand,
      rating: selection.family_rating,
      review_count: selection.family_review_count,
      main_image_url: selection.family_main_image_url,
      variant_dimensions: selection.variant_dimensions ?? [],
      bullet_points: [],
      selection_id: selection.id,
      selection_status: selection.selection_status,
      variant_count: selection.family_variant_count,
      variants: selection.variants,
    }
  );
}

function getDraftsForProduct(productId: number): ListingDraft[] {
  return state.drafts.filter((draft) => draft.product_master_id === productId);
}

function openDraftEditor(draftId: number): void {
  selectedDraftId.value = draftId;
}

function openListingForProduct(productId: number): void {
  const draft = getDraftsForProduct(productId)[0];
  if (draft) {
    selectedDraftId.value = draft.id;
  }
}

function toggleVariantDetail(variantId: number): void {
  expandedVariantId.value = expandedVariantId.value === variantId ? null : variantId;
}

function isVariantExpanded(variantId: number): boolean {
  return expandedVariantId.value === variantId;
}

function getVariantTitle(variant: RawProductVariant, family?: RawProductFamily | null): string {
  return variant.title || family?.title || variant.asin || "Unnamed variant";
}

function getVariantImage(variant: RawProductVariant): string {
  return variant.main_image_url ?? "";
}

function getVariantBulletPoints(variant: RawProductVariant, family?: RawProductFamily | null): string[] {
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

const helpers: WorkflowHelpers = {
  variantPreview,
  selectionCoverage,
  familyLeadPrice,
  selectionLeadPrice,
  formatDate,
  formatNumber,
  getStatusLabel,
  getMarketplaceLabel,
  getFamilyImage,
  getFamilyStatusLabel,
  getFamilyStatusKey,
  getDraftImage,
  truncateUrl,
  getDraftsForProduct,
  isVariantExpanded,
  isVariantSelected,
  getVariantTitle,
  getVariantImage,
  getVariantBulletPoints,
  getVariantAttributeEntries,
};

const actions: WorkflowActions = {
  refreshAll,
  submitCollection,
  addToSelection,
  saveSelectionScope,
  createProduct,
  createDraft,
  saveDraft,
  saveDraftVariant,
  publishDraft,
  openFamilyDetail,
  closeFamilyDetail,
  openSelectionDetail,
  closeSelectionDetail,
  openDraftEditor,
  openListingForProduct,
  toggleVariantDetail,
  toggleVariantInScope,
};
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <section class="brand-card">
        <p class="eyebrow">Amazon Workflow</p>
        <h1>Family First</h1>
        <p class="brand-copy">
          Start from raw product families, narrow variant scope, then create SPUs, listing drafts, and publish tasks.
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
              Refresh
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
        <IntakeView
          v-if="activeView === 'intake'"
          :ui="ui"
          :filters="filters"
          :collection-list-rows="collectionListRows"
          :family-marketplace-options="familyMarketplaceOptions"
          :filtered-families="filteredFamilies"
          :selected-family="selectedFamily"
          :helpers="helpers"
          :actions="actions"
        />

        <SelectionsView
          v-else-if="activeView === 'selections'"
          :filters="filters"
          :filtered-selections="filteredSelections"
          :selected-selection="selectedSelection"
          :selected-selection-family="selectedSelectionFamily"
          :helpers="helpers"
          :actions="actions"
        />

        <ListingView
          v-else-if="activeView === 'listing'"
          :ui="ui"
          :filters="filters"
          :filtered-listing-products="filteredListingProducts"
          :selected-draft="selectedDraft"
          :draft-editor="draftEditor"
          :draft-stats="draftStats"
          :draft-preview-bullets="draftPreviewBullets"
          :draft-validation-items="draftValidationItems"
          :helpers="helpers"
          :actions="actions"
        />

        <PublishView
          v-else
          :state="state"
          :ui="ui"
          :helpers="helpers"
        />
      </div>
    </main>
  </div>
</template>

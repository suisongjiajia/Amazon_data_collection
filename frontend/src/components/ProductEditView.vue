<script setup lang="ts">
import { computed, ref } from "vue";

import { apiRequest, apiUploadImages } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";
import { getModuleDefinition } from "../config/modules";
import type { AiProductEditResponse, ListingPreview, OzonProductFamily, ProductEdit } from "../types/ozon-workflow";
import ErpBadge from "./erp/ErpBadge.vue";
import ErpButton from "./erp/ErpButton.vue";
import ErpCard from "./erp/ErpCard.vue";
import ErpEmpty from "./erp/ErpEmpty.vue";
import ErpPageHeader from "./erp/ErpPageHeader.vue";
import ErpProductCell from "./erp/ErpProductCell.vue";
import ErpStatGrid from "./erp/ErpStatGrid.vue";
import ListingPreviewPanel from "./ListingPreviewPanel.vue";

interface EditDraftVariant {
  id: number | null;
  sku: string;
  title: string;
  price: number | null;
  quantity: number;
  variant_attributes: Record<string, string>;
}

interface EditDraft {
  editId: number | null;
  rawProductFamilyId: number;
  status: string | null;
  title: string;
  description: string;
  bullet_points: string[];
  images: string[];
  attributes: Record<string, string>;
  listing_notes: string;
  variants: EditDraftVariant[];
}

const store = useAppStore();
const module = getModuleDefinition("product-edit");
const selectedFamilyId = ref<number | null>(null);
const draft = ref<EditDraft | null>(null);
const saving = ref(false);
const aiGenerating = ref(false);
const buildingListing = ref(false);
const submittingReview = ref(false);
const suggestingPrice = ref(false);
const rehostingImages = ref(false);
const uploadingImages = ref(false);
const showImageUrlEditor = ref(false);
const dragImageIndex = ref<number | null>(null);
const cancellingEdit = ref(false);
const cancellingFamilyId = ref<number | null>(null);
const listingPreview = ref<ListingPreview | null>(null);
const resolvingCategory = ref(false);

const isBusy = computed(
  () =>
    saving.value ||
    aiGenerating.value ||
    buildingListing.value ||
    submittingReview.value ||
    suggestingPrice.value ||
    rehostingImages.value ||
    uploadingImages.value ||
    resolvingCategory.value ||
    cancellingEdit.value,
);

const editByFamily = computed(() => {
  const map = new Map<number, ProductEdit>();
  for (const edit of store.state.value.edits) {
    map.set(edit.raw_product_family_id, edit);
  }
  return map;
});

const currentProduct = computed(() => {
  if (selectedFamilyId.value == null) return null;
  return store.state.value.ozonProducts.find((item) => item.id === selectedFamilyId.value) ?? null;
});

const bulletPointsText = computed({
  get: () => (draft.value?.bullet_points ?? []).join("\n"),
  set: (value: string) => {
    if (!draft.value) return;
    draft.value.bullet_points = value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  },
});

const imagesText = computed({
  get: () => (draft.value?.images ?? []).join("\n"),
  set: (value: string) => {
    if (!draft.value) return;
    draft.value.images = value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .slice(0, 15);
  },
});

const MAX_IMAGES = 15;
const REQUIRED_IMAGES = 5; // 1 主图 + 4 附图

const imageRequirementMet = computed(() => (draft.value?.images.length ?? 0) >= REQUIRED_IMAGES);
const imageRequirementHint = computed(() => {
  const count = draft.value?.images.length ?? 0;
  if (count >= REQUIRED_IMAGES) {
    return `已满足：主图 1 + 附图 ${Math.min(count - 1, 4)}（当前共 ${count} 张）`;
  }
  return `还差 ${REQUIRED_IMAGES - count} 张：需主图 1 + 附图 4（当前 ${count}/${REQUIRED_IMAGES}）`;
});

function removeImageAt(index: number): void {
  if (!draft.value) return;
  draft.value.images = draft.value.images.filter((_, i) => i !== index);
}

function moveImage(from: number, to: number): void {
  if (!draft.value) return;
  if (from === to || from < 0 || to < 0) return;
  const list = [...draft.value.images];
  if (from >= list.length || to >= list.length) return;
  const [item] = list.splice(from, 1);
  list.splice(to, 0, item);
  draft.value.images = list;
}

function onImageDragStart(index: number): void {
  dragImageIndex.value = index;
}

function onImageDrop(index: number): void {
  if (dragImageIndex.value == null) return;
  moveImage(dragImageIndex.value, index);
  dragImageIndex.value = null;
}

function onImageDragEnd(): void {
  dragImageIndex.value = null;
}

async function uploadLocalImages(event: Event): Promise<void> {
  const current = draft.value;
  if (!current || uploadingImages.value) return;
  const input = event.target as HTMLInputElement;
  const selected = Array.from(input.files || []);
  input.value = "";
  if (!selected.length) return;

  const remain = MAX_IMAGES - current.images.length;
  if (remain <= 0) {
    store.showError(`最多 ${MAX_IMAGES} 张图片，请先删除后再上传`);
    return;
  }
  const files = selected.slice(0, remain);
  if (selected.length > remain) {
    store.showNotice(`已达上限，仅上传前 ${remain} 张`);
  }

  uploadingImages.value = true;
  store.showNotice("正在上传图片到 OSS…");
  try {
    const sku = current.variants[0]?.sku || `OZON-${current.rawProductFamilyId}`;
    const result = await apiUploadImages(files, { sku });
    const next = [...current.images, ...result.images].slice(0, MAX_IMAGES);
    current.images = next;
    const failCount = result.errors?.length || 0;
    store.showNotice(
      failCount
        ? `已上传 ${result.count} 张，失败 ${failCount} 张`
        : `已上传 ${result.count} 张图片`,
    );
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    uploadingImages.value = false;
  }
}

const attributeEntries = computed(() => {
  if (!draft.value) return [];
  return Object.entries(draft.value.attributes);
});

const PACKAGE_ATTR_KEYS = ["length_mm", "width_mm", "height_mm", "weight_g"] as const;

const otherAttributeEntries = computed(() =>
  attributeEntries.value.filter(
    ([key]) =>
      key !== "description_category_id" &&
      key !== "type_id" &&
      key !== "category_resolve_error" &&
      key !== "package_defaults" &&
      key !== "ozon_auto_attributes" &&
      !(PACKAGE_ATTR_KEYS as readonly string[]).includes(key),
  ),
);

function packageAttr(key: (typeof PACKAGE_ATTR_KEYS)[number]): string {
  return draft.value?.attributes?.[key] || "";
}

function setPackageAttr(key: (typeof PACKAGE_ATTR_KEYS)[number], value: string): void {
  if (!draft.value) return;
  const text = value.trim();
  if (!text) {
    const next = { ...draft.value.attributes };
    delete next[key];
    draft.value.attributes = next;
    return;
  }
  draft.value.attributes = { ...draft.value.attributes, [key]: text };
}

const hasCategoryIds = computed(() => {
  const attrs = draft.value?.attributes;
  return Boolean(attrs?.description_category_id && attrs?.type_id);
});

const priceCurrencyLabel = computed(() => {
  const code = String(draft.value?.attributes?.currency_code || "CNY").trim().toUpperCase() || "CNY";
  if (code === "RUB") return "价格 (₽)";
  if (code === "CNY") return "价格 (¥ / CNY)";
  return `价格 (${code})`;
});

const isUnsavedDraft = computed(() => draft.value != null && draft.value.editId == null);

function productPrice(item: OzonProductFamily): string {
  return item.price_text || item.variants?.[0]?.price_text || "-";
}

function parsePrice(text?: string | null): number | null {
  if (!text) return null;
  const normalized = text.replace(/[^\d.,]/g, "").replace(",", ".");
  const value = Number.parseFloat(normalized);
  return Number.isFinite(value) ? value : null;
}

function editForFamily(familyId: number): ProductEdit | undefined {
  return editByFamily.value.get(familyId);
}

function hasPersistedEdit(familyId: number): boolean {
  return editByFamily.value.has(familyId);
}

function canCancelEdit(status: string | null): boolean {
  return status == null || status === "draft" || status === "editing" || status === "rejected" || status === "listing_ready";
}

function canSubmitReview(draftValue: EditDraft): boolean {
  if (!draftValue.editId) return false;
  if (draftValue.images.length < REQUIRED_IMAGES) return false;
  return draftValue.status === "listing_ready";
}

function canBuildListing(draftValue: EditDraft): boolean {
  if (!draftValue.editId) return false;
  if (draftValue.images.length < REQUIRED_IMAGES) return false;
  const status = draftValue.status ?? "draft";
  return (
    status === "draft" ||
    status === "editing" ||
    status === "rejected" ||
    status === "needs_fix" ||
    status === "listing_ready"
  );
}

function buildDraftFromProduct(product: OzonProductFamily): EditDraft {
  const defaultTitle = product.title || "未命名商品";
  const variants =
    product.variants.length > 0
      ? product.variants.map((variant) => {
          const externalId = variant.external_id || String(variant.id);
          const attrs = (variant.variant_attributes || {}) as Record<string, string>;
          const label = Object.values(attrs).filter(Boolean).join(" / ");
          return {
            id: null,
            sku: `OZON-${externalId}`,
            title: variant.title || (label ? `${defaultTitle} (${label})` : defaultTitle),
            price: parsePrice(variant.price_text),
            quantity: 99,
            variant_attributes: { ...attrs },
          };
        })
      : [
          {
            id: null,
            sku: `OZON-${product.external_id || product.id}`,
            title: defaultTitle,
            price: parsePrice(product.price_text || product.variants?.[0]?.price_text),
            quantity: 99,
            variant_attributes: {},
          },
        ];

  const images = product.main_image_url ? [product.main_image_url] : [];

  return {
    editId: null,
    rawProductFamilyId: product.id,
    status: null,
    title: defaultTitle,
    description: "",
    bullet_points: [],
    images,
    attributes: {
      description_category_id: product.category_id || "",
      type_id: product.type_id || "",
    },
    listing_notes: "",
    variants,
  };
}

function buildDraftFromEdit(edit: ProductEdit): EditDraft {
  return {
    editId: edit.id,
    rawProductFamilyId: edit.raw_product_family_id,
    status: edit.status,
    title: edit.title,
    description: edit.description || "",
    bullet_points: edit.bullet_points || [],
    images: edit.images || [],
    attributes: {
      description_category_id: "",
      type_id: "",
      ...(edit.attributes || {}),
    },
    listing_notes: "",
    variants: edit.variants.map((variant) => ({
      id: variant.id,
      sku: variant.sku,
      title: variant.title || edit.title,
      price: variant.price,
      quantity: variant.quantity,
      variant_attributes: { ...(variant.variant_attributes || {}) },
    })),
  };
}

function variantSpecText(variant: EditDraftVariant): string {
  const attrs = variant.variant_attributes || {};
  const parts = Object.entries(attrs)
    .filter(([, value]) => String(value || "").trim())
    .map(([key, value]) => `${key}: ${value}`);
  return parts.length ? parts.join(" · ") : "-";
}

function applyAiSuggestion(response: AiProductEditResponse): void {
  const current = draft.value;
  if (!current) return;
  const suggestion = response.suggestion;
  current.title = suggestion.title || current.title;
  current.description = suggestion.description || current.description;
  current.bullet_points = suggestion.bullet_points || [];
  current.images = suggestion.images?.length ? suggestion.images : current.images;
  current.attributes = {
    ...current.attributes,
    ...(suggestion.attributes || {}),
  };
  // 采集到的上架 ID 优先保留
  for (const key of ["description_category_id", "type_id"] as const) {
    const existing = current.attributes[key];
    const incoming = suggestion.attributes?.[key];
    if (existing) current.attributes[key] = existing;
    else if (incoming) current.attributes[key] = incoming;
  }
  current.listing_notes = suggestion.listing_notes || "";

  if (suggestion.variants?.length) {
    current.variants = suggestion.variants.map((variant, index) => {
      const existing = current.variants[index];
      return {
        id: existing?.id ?? null,
        sku: variant.sku || existing?.sku || `OZON-${current.rawProductFamilyId}`,
        title: variant.title || current.title,
        price: variant.price ?? existing?.price ?? null,
        quantity: variant.quantity ?? existing?.quantity ?? 0,
      };
    });
  }
}

async function generateWithAi(): Promise<void> {
  const current = draft.value;
  if (!current || aiGenerating.value) return;
  aiGenerating.value = true;
  store.showNotice("AI 生成中，请稍候…");
  try {
    const response = await apiRequest<AiProductEditResponse>("/api/product-edits/ai-generate", {
      method: "POST",
      body: JSON.stringify({
        raw_product_family_id: current.rawProductFamilyId,
        rehost_images: true,
      }),
    });
    applyAiSuggestion(response);
    const hints: string[] = ["AI 已生成上架内容"];
    if (response.pricing) hints.push("价格已按公式计算");
    if (response.image_rehost?.count) hints.push(`图片已转存 ${response.image_rehost.count} 张`);
    if (response.suggestion.attributes?.pricing_error) {
      hints.push(`定价警告: ${response.suggestion.attributes.pricing_error}`);
    }
    if (response.suggestion.attributes?.image_rehost_error) {
      hints.push(`图片转存警告: ${response.suggestion.attributes.image_rehost_error}`);
    }
    store.showNotice(hints.join("；") + "，请检查后保存");
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    aiGenerating.value = false;
  }
}

async function suggestPrice(): Promise<void> {
  const current = draft.value;
  if (!current || suggestingPrice.value) return;
  suggestingPrice.value = true;
  store.showNotice("正在计算建议价…");
  try {
    const result = await apiRequest<{
      pricing: {
        list_price: number;
        price_rub: number;
        currency_code?: string;
        stock_qty: number;
        formula: string;
      };
      listing_notes?: string;
      freight?: { channel_name: string; freight_cny: number };
    }>("/api/product-edits/suggest-price", {
      method: "POST",
      body: JSON.stringify({ raw_product_family_id: current.rawProductFamilyId }),
    });
    const listPrice = result.pricing.list_price ?? result.pricing.price_rub;
    const currency = result.pricing.currency_code || "CNY";
    for (const variant of current.variants) {
      variant.price = listPrice;
      variant.quantity = result.pricing.stock_qty;
    }
    current.attributes = {
      ...current.attributes,
      pricing_formula: result.pricing.formula,
      currency_code: currency,
      freight_channel: result.freight?.channel_name || "",
      freight_cny: String(result.freight?.freight_cny ?? ""),
    };
    if (result.listing_notes) current.listing_notes = result.listing_notes;
    store.showNotice(`建议价 ${listPrice} ${currency}，库存 ${result.pricing.stock_qty}`);
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    suggestingPrice.value = false;
  }
}

async function rehostImages(): Promise<void> {
  const current = draft.value;
  if (!current || rehostingImages.value) return;
  rehostingImages.value = true;
  store.showNotice("正在转存图片到 OSS…");
  try {
    const result = await apiRequest<{ images: string[]; count: number }>(
      "/api/product-edits/rehost-images",
      {
        method: "POST",
        body: JSON.stringify({
          raw_product_family_id: current.rawProductFamilyId,
          images: current.images,
          sku: current.variants[0]?.sku,
        }),
      },
    );
    current.images = result.images;
    store.showNotice(`已转存 ${result.count} 张图片到 OSS`);
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    rehostingImages.value = false;
  }
}

function openEdit(familyId: number): void {
  const product = store.state.value.ozonProducts.find((item) => item.id === familyId);
  if (!product) return;
  selectedFamilyId.value = familyId;
  const existing = editForFamily(familyId);
  draft.value = existing ? buildDraftFromEdit(existing) : buildDraftFromProduct(product);
  listingPreview.value = null;
  if (existing?.listing_payload) {
    listingPreview.value = {
      ok: true,
      issues: existing.listing_payload.issues || [],
      summary: existing.listing_payload.summary || {
        title: existing.title,
        description: existing.description,
        bullet_points: existing.bullet_points || [],
        images: existing.images || [],
        variants: existing.variants,
      },
      payload_items: existing.listing_payload.payload_items || [],
      stock_items: existing.listing_payload.stock_items || [],
      saved_listing: existing.listing_payload,
      listing_built_at: existing.listing_built_at,
    };
  }
  void autoResolveCategoryIfNeeded();
}

async function autoResolveCategoryIfNeeded(): Promise<void> {
  const current = draft.value;
  if (!current) return;
  if (current.attributes.description_category_id && current.attributes.type_id) return;
  await resolveCategory(false);
}

async function resolveCategory(showSuccessNotice = true): Promise<void> {
  const current = draft.value;
  if (!current || resolvingCategory.value) return;
  resolvingCategory.value = true;
  if (showSuccessNotice) store.showNotice("正在获取类目…");
  try {
    // 未保存时先按 family 解析；已保存则写入 edit attributes
    if (!current.editId) {
      const resolved = await apiRequest<{
        description_category_id: string;
        type_id: string;
      }>(`/api/ozon/products/${current.rawProductFamilyId}/resolve-category`, {
        method: "POST",
      });
      current.attributes.description_category_id = String(resolved.description_category_id);
      current.attributes.type_id = String(resolved.type_id);
      delete current.attributes.category_resolve_error;
      await store.refreshAll();
      if (showSuccessNotice) {
        store.showNotice(
          `已自动获取类目 ${resolved.description_category_id} / type ${resolved.type_id}`,
        );
      }
      return;
    }

    const result = await apiRequest<{
      description_category_id: string;
      type_id: string;
      edit?: ProductEdit;
    }>(`/api/product-edits/${current.editId}/resolve-category`, { method: "POST" });
    current.attributes.description_category_id = String(result.description_category_id);
    current.attributes.type_id = String(result.type_id);
    delete current.attributes.category_resolve_error;
    await store.refreshAll();
    const fresh = editForFamily(current.rawProductFamilyId);
    if (fresh) draft.value = buildDraftFromEdit(fresh);
    if (showSuccessNotice) {
      store.showNotice(
        `已自动获取类目 ${result.description_category_id} / type ${result.type_id}`,
      );
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (current.attributes) current.attributes.category_resolve_error = message;
    store.showError(message);
  } finally {
    resolvingCategory.value = false;
  }
}

function closeEdit(): void {
  selectedFamilyId.value = null;
  draft.value = null;
  listingPreview.value = null;
}

async function cancelEdit(): Promise<void> {
  const current = draft.value;
  if (!current) {
    closeEdit();
    return;
  }
  if (cancellingEdit.value) return;

  if (current.editId && canCancelEdit(current.status)) {
    cancellingEdit.value = true;
    store.showNotice("正在取消编辑…");
    try {
      await apiRequest(`/api/product-edits/${current.editId}`, { method: "DELETE" });
      store.showNotice("已取消编辑");
      await store.refreshAll();
    } catch (err) {
      store.showError(err instanceof Error ? err.message : String(err));
      return;
    } finally {
      cancellingEdit.value = false;
    }
  }

  closeEdit();
}

async function cancelEditFromList(familyId: number): Promise<void> {
  const edit = editForFamily(familyId);
  if (!edit || !canCancelEdit(edit.status) || cancellingFamilyId.value != null) return;
  cancellingFamilyId.value = familyId;
  store.showNotice("正在取消编辑…");
  try {
    await apiRequest(`/api/product-edits/${edit.id}`, { method: "DELETE" });
    store.showNotice("已取消编辑");
    if (selectedFamilyId.value === familyId) {
      closeEdit();
    }
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    cancellingFamilyId.value = null;
  }
}

async function saveEdit(): Promise<void> {
  const current = draft.value;
  if (!current || saving.value) return;

  saving.value = true;
  store.showNotice("正在保存产品信息…");
  try {
    let editId = current.editId;
    if (!editId) {
      const created = await apiRequest<ProductEdit>(
        `/api/product-edits?raw_product_family_id=${current.rawProductFamilyId}`,
        { method: "POST" },
      );
      editId = created.id;
      current.editId = editId;
      current.status = created.status;
      for (const variant of current.variants) {
        const matched = created.variants.find((item) => item.sku === variant.sku);
        if (matched) variant.id = matched.id;
      }
    }

    await apiRequest(`/api/product-edits/${editId}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: current.title,
        description: current.description,
        bullet_points: current.bullet_points,
        images: current.images,
        attributes: current.attributes,
      }),
    });

    for (const variant of current.variants) {
      if (variant.id == null) continue;
      await apiRequest(`/api/product-edit-variants/${variant.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: variant.title,
          price: variant.price,
          quantity: variant.quantity,
          variant_attributes: variant.variant_attributes || {},
        }),
      });
    }

    store.showNotice("产品信息已保存（尚未生成 Listing）");
    await store.refreshAll();
    const fresh = editForFamily(current.rawProductFamilyId);
    if (fresh) {
      draft.value = buildDraftFromEdit(fresh);
      listingPreview.value = null;
    }
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    saving.value = false;
  }
}

async function buildListing(): Promise<void> {
  const current = draft.value;
  if (!current?.editId) {
    store.showError("请先保存产品信息，再生成 Listing");
    return;
  }
  if (current.images.length < REQUIRED_IMAGES) {
    store.showError(`图片不足：需要 1 张主图 + 4 张附图（共 ${REQUIRED_IMAGES} 张），当前 ${current.images.length} 张`);
    return;
  }
  if (buildingListing.value) return;
  buildingListing.value = true;
  store.showNotice("正在生成 Listing…");
  try {
    const result = await apiRequest<ListingPreview & { edit?: ProductEdit; saved?: boolean }>(
      `/api/product-edits/${current.editId}/build-listing`,
      { method: "POST" },
    );
    listingPreview.value = result;
    if (!result.ok) {
      store.showError("Listing 校验未通过，请根据下方问题修复后再生成");
      return;
    }
    store.showNotice("Listing 已生成并通过校验，可提交审核");
    await store.refreshAll();
    const fresh = editForFamily(current.rawProductFamilyId);
    if (fresh) draft.value = buildDraftFromEdit(fresh);
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    buildingListing.value = false;
  }
}

async function submitReview(): Promise<void> {
  const current = draft.value;
  if (!current?.editId) {
    store.showError("请先保存并生成 Listing");
    return;
  }
  if (current.images.length < REQUIRED_IMAGES) {
    store.showError(`图片不足：需要 1 张主图 + 4 张附图（共 ${REQUIRED_IMAGES} 张），当前 ${current.images.length} 张`);
    return;
  }
  if (current.status !== "listing_ready") {
    store.showError("请先生成 Listing 并通过校验后再提交审核");
    return;
  }
  if (submittingReview.value) return;
  submittingReview.value = true;
  store.showNotice("正在提交审核…");
  try {
    await apiRequest(`/api/product-edits/${current.editId}/submit-review`, { method: "POST" });
    // 先本地切换状态，立刻隐藏按钮，避免连点
    if (draft.value?.editId === current.editId) {
      draft.value.status = "pending_review";
    }
    store.showNotice("Listing 已提交审核，请到「审核」模块处理");
    await store.refreshAll();
    const fresh = editForFamily(current.rawProductFamilyId);
    if (fresh) draft.value = buildDraftFromEdit(fresh);
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    submittingReview.value = false;
  }
}
</script>

<template>
  <div class="erp-stack">
    <ErpPageHeader
      :title="selectedFamilyId ? '商品编辑详情' : module.label"
      :description="
        selectedFamilyId
          ? isUnsavedDraft
            ? '当前为本地草稿：先保存产品信息，再生成 Listing，最后提交审核'
            : '先保存产品信息 → 生成可上架 Listing → 提交审核'
          : module.description
      "
    >
      <template v-if="selectedFamilyId" #actions>
        <ErpButton variant="ghost" size="sm" @click="closeEdit">返回列表</ErpButton>
        <ErpButton
          v-if="draft && canCancelEdit(draft.status)"
          variant="danger"
          size="sm"
          :disabled="cancellingEdit || isBusy"
          @click="cancelEdit"
        >
          {{ cancellingEdit ? "取消中…" : "取消编辑" }}
        </ErpButton>
      </template>
    </ErpPageHeader>

    <template v-if="!selectedFamilyId">
      <ErpStatGrid
        :items="[
          { label: '可编辑商品', value: store.state.value.ozonProducts.length },
          { label: '已保存编辑', value: store.state.value.edits.length },
          { label: '待审核', value: store.stats.value.pendingReview },
          { label: '已通过', value: store.stats.value.approved },
        ]"
      />

      <ErpCard title="商品编辑" :description="`${store.state.value.ozonProducts.length} 条`" padding="none">
        <div v-if="store.state.value.ozonProducts.length" class="erp-table-wrap">
          <table class="erp-table">
            <thead>
              <tr>
                <th>商品</th>
                <th>价格</th>
                <th>编辑状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in store.state.value.ozonProducts" :key="item.id">
                <td>
                  <ErpProductCell
                    :image-url="item.main_image_url"
                    :title="item.title"
                    :subtitle="`SKU ${item.external_id || '-'} · ${productPrice(item)}`"
                  />
                </td>
                <td>{{ productPrice(item) }}</td>
                <td>
                  <ErpBadge v-if="editForFamily(item.id)" :status="editForFamily(item.id)!.status" />
                  <span v-else class="erp-text-muted">未编辑</span>
                </td>
                <td>
                  <div class="erp-table-actions">
                    <ErpButton variant="secondary" size="sm" @click="openEdit(item.id)">
                      {{ hasPersistedEdit(item.id) ? "进入编辑" : "开始编辑" }}
                    </ErpButton>
                    <ErpButton
                      v-if="editForFamily(item.id) && canCancelEdit(editForFamily(item.id)!.status)"
                      variant="ghost"
                      size="sm"
                      :disabled="cancellingFamilyId === item.id"
                      @click="cancelEditFromList(item.id)"
                    >
                      {{ cancellingFamilyId === item.id ? "取消中…" : "取消编辑" }}
                    </ErpButton>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <ErpEmpty v-else message="暂无商品，请先在采集模块添加 Ozon 商品" />
      </ErpCard>
    </template>

    <template v-else-if="currentProduct && draft">
      <ErpCard padding="none">
        <div class="erp-card__body">
          <div class="erp-detail-hero">
            <ErpProductCell
              size="lg"
              :image-url="currentProduct.main_image_url"
              :title="currentProduct.title"
              :subtitle="currentProduct.brand || `SKU ${currentProduct.external_id || '-'}`"
            />
            <div class="erp-detail-hero__copy">
              <div class="erp-detail-hero__meta">
                <span>{{ productPrice(currentProduct) }}</span>
                <span>类目 {{ currentProduct.category_name || "-" }}</span>
                <span>排名 {{ currentProduct.sales_rank ?? "-" }}</span>
              </div>
              <ErpBadge v-if="draft.editId" :status="draft.status || 'draft'" />
              <span v-else class="erp-badge" data-tone="warning">未保存</span>
            </div>
          </div>
        </div>
      </ErpCard>

      <ErpCard title="产品信息" description="此处保存的是产品内容；上架包请点「生成 Listing」">
        <div class="erp-editor-actions" style="margin-bottom: 14px">
          <ErpButton :disabled="isBusy" @click="generateWithAi">
            {{ aiGenerating ? "AI 生成中…" : "AI 一键生成" }}
          </ErpButton>
          <ErpButton variant="secondary" :disabled="isBusy" @click="suggestPrice">
            {{ suggestingPrice ? "计算中…" : "计算建议价" }}
          </ErpButton>
          <ErpButton variant="secondary" :disabled="isBusy" @click="resolveCategory(true)">
            {{ resolvingCategory ? "获取类目中…" : "自动获取类目" }}
          </ErpButton>
        </div>
        <div class="erp-editor-grid">
          <label class="erp-field">
            <span>标题（俄语）</span>
            <input v-model="draft.title" type="text" />
          </label>
          <div class="erp-detail-item">
            <span>description_category_id</span>
            <strong>{{ draft.attributes.description_category_id || "-" }}</strong>
          </div>
          <div class="erp-detail-item">
            <span>type_id</span>
            <strong>{{ draft.attributes.type_id || "-" }}</strong>
          </div>
          <label class="erp-field">
            <span>描述（俄语）</span>
            <textarea v-model="draft.description" rows="6" />
          </label>
          <label class="erp-field">
            <span>卖点（每行一条）</span>
            <textarea v-model="bulletPointsText" rows="5" />
          </label>
          <div class="erp-field erp-field--full">
            <span>
              商品图片（必须 1 主图 + 4 附图，最多 {{ MAX_IMAGES }} 张；第一张为主图，可拖拽排序）
            </span>
            <p
              class="erp-image-editor__hint"
              :class="{ 'is-ok': imageRequirementMet, 'is-bad': !imageRequirementMet }"
            >
              {{ imageRequirementHint }}
            </p>
            <div class="erp-image-editor">
              <div v-if="draft.images.length" class="erp-image-editor__grid">
                <div
                  v-for="(url, index) in draft.images"
                  :key="`${url}-${index}`"
                  class="erp-image-editor__item"
                  :class="{ 'is-dragging': dragImageIndex === index }"
                  draggable="true"
                  @dragstart="onImageDragStart(index)"
                  @dragover.prevent
                  @drop.prevent="onImageDrop(index)"
                  @dragend="onImageDragEnd"
                >
                  <img :src="url" :alt="`图片 ${index + 1}`" />
                  <span v-if="index === 0" class="erp-image-editor__badge">主图</span>
                  <span v-else-if="index <= 4" class="erp-image-editor__badge erp-image-editor__badge--extra">
                    附图{{ index }}
                  </span>
                  <span class="erp-image-editor__index">{{ index + 1 }}</span>
                  <div class="erp-image-editor__actions">
                    <button
                      type="button"
                      class="erp-image-editor__btn"
                      :disabled="index === 0 || isBusy"
                      title="前移"
                      @click="moveImage(index, index - 1)"
                    >
                      ←
                    </button>
                    <button
                      type="button"
                      class="erp-image-editor__btn"
                      :disabled="index >= draft.images.length - 1 || isBusy"
                      title="后移"
                      @click="moveImage(index, index + 1)"
                    >
                      →
                    </button>
                    <button
                      type="button"
                      class="erp-image-editor__btn erp-image-editor__btn--danger"
                      :disabled="isBusy"
                      title="删除"
                      @click="removeImageAt(index)"
                    >
                      删
                    </button>
                  </div>
                </div>
              </div>
              <ErpEmpty v-else message="暂无图片，请本地上传或粘贴 URL" />

              <div class="erp-image-editor__toolbar">
                <label class="erp-upload-btn" :class="{ 'is-disabled': isBusy || draft.images.length >= MAX_IMAGES }">
                  {{ uploadingImages ? "上传中…" : "本地上传" }}
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp,image/gif,.jpg,.jpeg,.png,.webp,.gif"
                    multiple
                    :disabled="isBusy || draft.images.length >= MAX_IMAGES"
                    @change="uploadLocalImages"
                  />
                </label>
                <ErpButton
                  variant="secondary"
                  size="sm"
                  :disabled="isBusy || !draft.images.length"
                  @click="rehostImages"
                >
                  {{ rehostingImages ? "转存中…" : "现有链接转存 OSS" }}
                </ErpButton>
                <ErpButton
                  variant="ghost"
                  size="sm"
                  :disabled="isBusy"
                  @click="showImageUrlEditor = !showImageUrlEditor"
                >
                  {{ showImageUrlEditor ? "收起 URL 编辑" : "高级：编辑 URL" }}
                </ErpButton>
              </div>

              <label v-if="showImageUrlEditor" class="erp-field" style="margin-top: 10px">
                <span>图片 URL（每行一条）</span>
                <textarea v-model="imagesText" rows="4" placeholder="https://..." />
              </label>
            </div>
          </div>
        </div>

        <div class="erp-editor-grid" style="margin-top: 14px">
          <label class="erp-field">
            <span>长度 (mm) *</span>
            <input
              type="number"
              min="1"
              step="1"
              :value="packageAttr('length_mm')"
              @input="setPackageAttr('length_mm', ($event.target as HTMLInputElement).value)"
              placeholder="必填，真实包裹长度"
            />
          </label>
          <label class="erp-field">
            <span>宽度 (mm) *</span>
            <input
              type="number"
              min="1"
              step="1"
              :value="packageAttr('width_mm')"
              @input="setPackageAttr('width_mm', ($event.target as HTMLInputElement).value)"
              placeholder="必填，真实包裹宽度"
            />
          </label>
          <label class="erp-field">
            <span>高度 (mm) *</span>
            <input
              type="number"
              min="1"
              step="1"
              :value="packageAttr('height_mm')"
              @input="setPackageAttr('height_mm', ($event.target as HTMLInputElement).value)"
              placeholder="必填，真实包裹高度"
            />
          </label>
          <label class="erp-field">
            <span>重量 (g) *</span>
            <input
              type="number"
              min="1"
              step="1"
              :value="packageAttr('weight_g')"
              @input="setPackageAttr('weight_g', ($event.target as HTMLInputElement).value)"
              placeholder="必填，真实商品重量"
            />
          </label>
        </div>
        <p class="erp-detail-text" style="margin-top: 8px">
          长宽高填「包装后」尺寸（不是展开尺寸），重量填含包装克数。
          体积很大但重量很轻时，Ozon 会报「尺寸或重量不正确」。
        </p>

        <div v-if="otherAttributeEntries.length" class="erp-detail-grid" style="margin-top: 14px">
          <div v-for="[key, value] in otherAttributeEntries" :key="key" class="erp-detail-item">
            <span>{{ key }}</span>
            <strong>{{ value }}</strong>
          </div>
        </div>
        <p v-if="!hasCategoryIds" class="erp-detail-text" style="margin-top: 12px">
          类目/类型自动获取（需配置 OZON_COOKIE）。打开编辑或生成 Listing 时会自动补全。
        </p>
        <p
          v-if="draft.attributes.category_resolve_error"
          class="erp-detail-text"
          style="margin-top: 8px; color: #991b1b"
        >
          自动获取失败：{{ draft.attributes.category_resolve_error }}
        </p>

        <p v-if="draft.listing_notes" class="erp-detail-text" style="margin-top: 14px">
          AI 说明：{{ draft.listing_notes }}
        </p>

        <div class="erp-table-wrap" style="margin-top: 16px">
          <table class="erp-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>规格</th>
                <th>变体标题</th>
                <th>{{ priceCurrencyLabel }}</th>
                <th>库存</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(variant, index) in draft.variants" :key="variant.id ?? `${variant.sku}-${index}`">
                <td>{{ variant.sku }}</td>
                <td>{{ variantSpecText(variant) }}</td>
                <td><input v-model="variant.title" type="text" /></td>
                <td><input v-model.number="variant.price" type="number" min="0" step="1" /></td>
                <td><input v-model.number="variant.quantity" type="number" min="0" /></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="erp-editor-actions" style="margin-top: 14px">
          <ErpButton variant="secondary" :disabled="isBusy" @click="saveEdit">
            {{ saving ? "保存中…" : "保存产品信息" }}
          </ErpButton>
          <ErpButton
            v-if="draft.editId && ['draft','editing','rejected','needs_fix','listing_ready'].includes(draft.status ?? 'draft')"
            :disabled="isBusy || !imageRequirementMet"
            @click="buildListing"
          >
            {{ buildingListing ? "生成中…" : imageRequirementMet ? "生成 Listing" : `补齐图片后再生成（${draft.images.length}/5）` }}
          </ErpButton>
          <ErpButton
            v-if="canSubmitReview(draft) || submittingReview"
            :disabled="isBusy || !imageRequirementMet"
            @click="submitReview"
          >
            {{ submittingReview ? "提交中…" : "提交审核" }}
          </ErpButton>
        </div>
      </ErpCard>

      <ErpCard v-if="listingPreview" title="Listing 上架包" description="审核与发布将基于此快照">
        <ListingPreviewPanel :preview="listingPreview" :show-payload="true" />
      </ErpCard>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { apiRequest } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";
import { getModuleDefinition } from "../config/modules";
import type { ListingPreview, ProductEdit, SupplierCandidate } from "../types/ozon-workflow";
import { resolveEditImage, formatMoney, resolveCurrencyCode } from "../utils/product-display";
import ErpBadge from "./erp/ErpBadge.vue";
import ErpButton from "./erp/ErpButton.vue";
import ErpCard from "./erp/ErpCard.vue";
import ErpEmpty from "./erp/ErpEmpty.vue";
import ErpPageHeader from "./erp/ErpPageHeader.vue";
import ErpProductCell from "./erp/ErpProductCell.vue";
import ErpStatGrid from "./erp/ErpStatGrid.vue";
import ListingPreviewPanel from "./ListingPreviewPanel.vue";

interface ReviewListingBundle {
  edit: ProductEdit;
  preview: ListingPreview;
  saved_listing?: ListingPreview["saved_listing"];
  product?: Record<string, unknown>;
  suppliers?: SupplierCandidate[];
  selected_supplier?: SupplierCandidate | null;
  pricing?: Record<string, unknown> | null;
  price_summary?: {
    list_price?: number | null;
    currency_code?: string | null;
    formula?: string | null;
    freight_cny?: string | null;
    freight_channel?: string | null;
    pricing_error?: string | null;
  };
  pipeline_item?: Record<string, unknown> | null;
  pipeline_error?: string | null;
  failure_kind?: string | null;
}

type ListFilter = "all" | "pending_review" | "needs_fix";

const store = useAppStore();
const module = getModuleDefinition("review");
const selectedEditId = ref<number | null>(null);
const listingBundle = ref<ReviewListingBundle | null>(null);
const reviewNote = ref("通过");
const loadingDetail = ref(false);
const reviewingAction = ref<"approve" | "reject" | "fix" | null>(null);
const listFilter = ref<ListFilter>("all");
const priceDrafts = ref<Record<number, number | null>>({});
const priceDirty = ref(false);
const savingPrice = ref(false);

const pendingEdits = computed(() =>
  store.state.value.edits.filter(
    (item) => item.status === "pending_review" || item.status === "needs_fix",
  ),
);

const pendingReviewCount = computed(
  () => pendingEdits.value.filter((item) => item.status === "pending_review").length,
);
const needsFixCount = computed(
  () => pendingEdits.value.filter((item) => item.status === "needs_fix").length,
);

const filteredEdits = computed(() => {
  if (listFilter.value === "all") return pendingEdits.value;
  return pendingEdits.value.filter((item) => item.status === listFilter.value);
});

const selectedEdit = computed(() =>
  pendingEdits.value.find((item) => item.id === selectedEditId.value) ?? null,
);

const isNeedsFix = computed(() => listingBundle.value?.edit?.status === "needs_fix");
const isReviewing = computed(() => reviewingAction.value != null);

const suppliers = computed(() => listingBundle.value?.suppliers || []);
const selectedSupplier = computed(() => listingBundle.value?.selected_supplier || null);
const priceSummary = computed(() => listingBundle.value?.price_summary || null);
const pricingDetail = computed(() => {
  const pricing = listingBundle.value?.pricing;
  if (!pricing || typeof pricing !== "object") return null;
  return pricing as {
    pricing?: Record<string, unknown>;
    freight?: Record<string, unknown>;
    error?: string;
  };
});

const pipelineError = computed(
  () =>
    listingBundle.value?.pipeline_error ||
    listingBundle.value?.edit?.attributes?.pipeline_error ||
    "",
);

const imageCount = computed(() => {
  const images = listingBundle.value?.edit?.images || [];
  return images.filter((url) => typeof url === "string" && url.trim()).length;
});

const previewImages = computed(() => {
  const images = listingBundle.value?.edit?.images || [];
  return images.filter((url) => typeof url === "string" && url.trim()).slice(0, 5);
});

const currencyCode = computed(() =>
  resolveCurrencyCode(
    listingBundle.value?.edit?.attributes,
    String(priceSummary.value?.currency_code || "CNY"),
  ),
);

const editableVariants = computed(() => listingBundle.value?.edit?.variants || []);

function syncPriceDrafts(edit: ProductEdit): void {
  const next: Record<number, number | null> = {};
  for (const variant of edit.variants || []) {
    next[variant.id] = variant.price ?? null;
  }
  priceDrafts.value = next;
  priceDirty.value = false;
}

function onPriceInput(variantId: number, raw: string): void {
  const text = raw.trim();
  if (!text) {
    priceDrafts.value = { ...priceDrafts.value, [variantId]: null };
  } else {
    const num = Number(text);
    priceDrafts.value = {
      ...priceDrafts.value,
      [variantId]: Number.isFinite(num) ? num : priceDrafts.value[variantId] ?? null,
    };
  }
  priceDirty.value = true;
}

function applyPriceToAll(raw: string): void {
  const num = Number(raw);
  if (!Number.isFinite(num) || num <= 0) return;
  const next: Record<number, number | null> = {};
  for (const variant of editableVariants.value) {
    next[variant.id] = num;
  }
  priceDrafts.value = next;
  priceDirty.value = true;
}

async function savePrices(): Promise<boolean> {
  if (selectedEditId.value == null || savingPrice.value) return false;
  const variant_prices = editableVariants.value.map((variant) => {
    const price = priceDrafts.value[variant.id];
    if (price == null || !(price > 0)) {
      throw new Error(`请为变体 ${variant.sku} 填写大于 0 的售价`);
    }
    return { variant_id: variant.id, price };
  });
  savingPrice.value = true;
  try {
    const result = await apiRequest<{
      ok: boolean;
      message?: string;
      bundle?: ReviewListingBundle;
    }>(`/api/reviews/${selectedEditId.value}/prices`, {
      method: "PATCH",
      body: JSON.stringify({ variant_prices }),
    });
    if (result.bundle) {
      listingBundle.value = result.bundle;
      syncPriceDrafts(result.bundle.edit);
    } else {
      await openListing(selectedEditId.value);
    }
    if (!result.ok) {
      store.showError(result.message || "价格已保存，但 Listing 未重建成功");
      return false;
    }
    store.showNotice(result.message || "价格已更新");
    await store.refreshAll();
    return true;
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
    return false;
  } finally {
    savingPrice.value = false;
  }
}

watch(
  filteredEdits,
  (list) => {
    if (!list.length) {
      if (!pendingEdits.value.length) {
        selectedEditId.value = null;
        listingBundle.value = null;
      }
      return;
    }
    if (selectedEditId.value == null || !list.some((item) => item.id === selectedEditId.value)) {
      void openListing(list[0].id);
    }
  },
  { immediate: true },
);

async function openListing(editId: number): Promise<void> {
  selectedEditId.value = editId;
  loadingDetail.value = true;
  try {
    listingBundle.value = await apiRequest(`/api/reviews/${editId}/listing`);
    syncPriceDrafts(listingBundle.value.edit);
    reviewNote.value =
      listingBundle.value?.edit?.status === "needs_fix" ? "修复后重新提交" : "通过并自动推送";
  } catch (err) {
    listingBundle.value = null;
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    loadingDetail.value = false;
  }
}

async function approve(): Promise<void> {
  if (selectedEditId.value == null || reviewingAction.value || isNeedsFix.value) return;
  if (imageCount.value < 5) {
    store.showError(`图片不足：需要 1 张主图 + 4 张附图（共 5 张），当前 ${imageCount.value} 张，无法推送`);
    return;
  }
  reviewingAction.value = "approve";
  store.showNotice("正在通过并自动推送…");
  try {
    if (priceDirty.value) {
      const ok = await savePrices();
      if (!ok) return;
    }
    await apiRequest(`/api/reviews/${selectedEditId.value}/approve`, {
      method: "POST",
      body: JSON.stringify({
        note: reviewNote.value || "通过",
        auto_publish: true,
      }),
    });
    store.showNotice("已通过并开始自动推送 / 拉取状态");
    selectedEditId.value = null;
    listingBundle.value = null;
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    reviewingAction.value = null;
  }
}

async function reject(): Promise<void> {
  if (selectedEditId.value == null || reviewingAction.value) return;
  if (isNeedsFix.value) {
    await openForFix();
    return;
  }
  reviewingAction.value = "reject";
  store.showNotice("正在驳回…");
  try {
    await apiRequest(`/api/reviews/${selectedEditId.value}/reject`, {
      method: "POST",
      body: JSON.stringify({ note: reviewNote.value || "需修改" }),
    });
    store.showNotice("已驳回，请回到商品编辑修复后重新生成 Listing");
    selectedEditId.value = null;
    listingBundle.value = null;
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    reviewingAction.value = null;
  }
}

async function openForFix(): Promise<void> {
  if (selectedEditId.value == null || reviewingAction.value) return;
  reviewingAction.value = "fix";
  try {
    await apiRequest(`/api/product-edits/${selectedEditId.value}/reopen`, { method: "POST" });
    store.showNotice("已打开编辑，请补齐属性/图片后重新生成 Listing 并提交审核");
    store.setModule("product-edit");
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    reviewingAction.value = null;
  }
}

function shortTitle(title: string | null | undefined, max = 42): string {
  const text = (title || "未命名").trim();
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

function listSubtitle(edit: ProductEdit): string {
  const price = formatMoney(edit.variants?.[0]?.price, resolveCurrencyCode(edit.attributes));
  const sku = `${edit.variants?.length || 0} SKU`;
  const imgs = `${edit.images?.length || 0} 图`;
  return `${price} · ${sku} · ${imgs}`;
}
</script>

<template>
  <div class="erp-stack">
    <ErpPageHeader :title="module.label" :description="module.description" />

    <ErpStatGrid
      :items="[
        { label: '待处理', value: pendingEdits.length, hint: '待审 + 待修复' },
        { label: '待审核', value: pendingReviewCount },
        { label: '待修复', value: needsFixCount },
      ]"
    />

    <div class="review-layout">
      <ErpCard title="待处理列表" :description="`${filteredEdits.length} / ${pendingEdits.length} 条`" padding="none">
        <div class="review-filters">
          <button
            type="button"
            class="review-filter"
            :class="{ active: listFilter === 'all' }"
            @click="listFilter = 'all'"
          >
            全部 {{ pendingEdits.length }}
          </button>
          <button
            type="button"
            class="review-filter"
            :class="{ active: listFilter === 'pending_review' }"
            @click="listFilter = 'pending_review'"
          >
            待审核 {{ pendingReviewCount }}
          </button>
          <button
            type="button"
            class="review-filter"
            :class="{ active: listFilter === 'needs_fix' }"
            @click="listFilter = 'needs_fix'"
          >
            待修复 {{ needsFixCount }}
          </button>
        </div>

        <div v-if="filteredEdits.length" class="review-list">
          <button
            v-for="edit in filteredEdits"
            :key="edit.id"
            type="button"
            class="review-list__item"
            :class="{ 'is-selected': edit.id === selectedEditId }"
            @click="openListing(edit.id)"
          >
            <ErpProductCell
              :image-url="resolveEditImage(edit)"
              :title="shortTitle(edit.title, 36)"
              :subtitle="listSubtitle(edit)"
            />
            <ErpBadge :status="edit.status" />
          </button>
        </div>
        <ErpEmpty v-else message="当前筛选下暂无条目" />
      </ErpCard>

      <div class="review-detail">
        <ErpCard
          title="审核详情"
          :description="
            selectedEdit
              ? isNeedsFix
                ? '流水线未通过，请先修复再提交'
                : '核对后通过将自动推送到 Ozon'
              : '从左侧选择一条'
          "
        >
          <div v-if="loadingDetail" class="review-loading">加载中…</div>
          <template v-else-if="listingBundle">
            <!-- 商品头：纵向清晰，避免挤在一行截断 -->
            <div class="review-hero">
              <div class="review-hero__media">
                <img
                  v-if="resolveEditImage(listingBundle.edit)"
                  :src="resolveEditImage(listingBundle.edit) || ''"
                  :alt="listingBundle.edit.title"
                />
                <div v-else class="review-hero__placeholder">无图</div>
              </div>
              <div class="review-hero__body">
                <div class="review-hero__badges">
                  <ErpBadge :status="listingBundle.edit.status" />
                  <ErpBadge
                    v-if="listingBundle.failure_kind && listingBundle.failure_kind !== 'needs_fix'"
                    :status="String(listingBundle.failure_kind)"
                  />
                </div>
                <h2 class="review-hero__title">{{ listingBundle.edit.title || "未命名商品" }}</h2>
                <div class="review-hero__meta">
                  <span v-if="listingBundle.edit.family_external_id">
                    Ozon ID {{ listingBundle.edit.family_external_id }}
                  </span>
                  <span>{{ listingBundle.edit.variants?.length || 0 }} SKU</span>
                  <span :class="{ 'is-warn': imageCount < 5 }">图片 {{ imageCount }}/5</span>
                  <span>
                    {{
                      formatMoney(
                        listingBundle.edit.variants?.[0]?.price,
                        resolveCurrencyCode(listingBundle.edit.attributes),
                      )
                    }}
                  </span>
                </div>
                <p v-if="listingBundle.edit.family_title" class="review-hero__source">
                  源品：{{ listingBundle.edit.family_title }}
                </p>
              </div>
            </div>

            <div v-if="isNeedsFix || pipelineError" class="review-alert">
              <strong>{{ isNeedsFix ? "需要修复后才能推送" : "提示" }}</strong>
              <p>{{ pipelineError || "Listing 校验未通过，请补齐属性、尺寸或图片。" }}</p>
              <ErpButton
                :disabled="isReviewing || store.loading.value"
                @click="openForFix"
              >
                {{ reviewingAction === "fix" ? "打开中…" : "去编辑修复" }}
              </ErpButton>
            </div>

            <div v-if="previewImages.length" class="review-thumbs">
              <div
                v-for="(url, index) in previewImages"
                :key="`${url}-${index}`"
                class="review-thumbs__item"
              >
                <img :src="url" :alt="`图 ${index + 1}`" />
                <span>{{ index === 0 ? "主图" : `附图${index}` }}</span>
              </div>
            </div>

            <section class="review-section">
              <h3 class="review-section__title">供应商</h3>
              <div v-if="selectedSupplier || suppliers.length" class="supplier-card">
                <ErpProductCell
                  :image-url="(selectedSupplier || suppliers[0])?.image_url || ''"
                  :title="
                    shortTitle(
                      (selectedSupplier || suppliers[0])?.product_title ||
                        (selectedSupplier || suppliers[0])?.supplier_name,
                      48,
                    )
                  "
                  :subtitle="`${(selectedSupplier || suppliers[0])?.supplier_name || '-'} · ${(selectedSupplier || suppliers[0])?.price_text || '-'} · 分 ${(selectedSupplier || suppliers[0])?.match_score ?? '-'}`"
                />
                <ErpBadge status="selected" />
              </div>
              <p v-else class="review-muted">暂无供应商</p>
              <p v-if="suppliers.length > 1" class="review-muted">另有 {{ suppliers.length - 1 }} 个候选未展开</p>
            </section>

            <section class="review-section">
              <h3 class="review-section__title">价格（可修改）</h3>
              <div class="price-grid">
                <div class="price-cell">
                  <span>运费</span>
                  <strong>{{ priceSummary?.freight_cny || "-" }} CNY</strong>
                </div>
                <div class="price-cell">
                  <span>渠道</span>
                  <strong>{{ priceSummary?.freight_channel || "-" }}</strong>
                </div>
                <div class="price-cell">
                  <span>统一改价（应用到全部变体）</span>
                  <input
                    class="price-input"
                    type="number"
                    min="0.01"
                    step="0.01"
                    :placeholder="String(priceSummary?.list_price ?? '')"
                    :disabled="isNeedsFix || savingPrice || isReviewing"
                    @change="applyPriceToAll(($event.target as HTMLInputElement).value)"
                  />
                </div>
              </div>
              <p class="review-formula">
                建议公式：{{ priceSummary?.formula || pricingDetail?.pricing?.formula || "暂无" }}
              </p>

              <div v-if="editableVariants.length" class="variant-price-list">
                <div
                  v-for="variant in editableVariants"
                  :key="variant.id"
                  class="variant-price-row"
                >
                  <div class="variant-price-row__meta">
                    <strong>{{ variant.sku }}</strong>
                    <span>{{ variant.title || "变体" }}</span>
                  </div>
                  <label class="variant-price-row__field">
                    <span>售价（{{ currencyCode }}）</span>
                    <input
                      class="price-input"
                      type="number"
                      min="0.01"
                      step="0.01"
                      :value="priceDrafts[variant.id] ?? ''"
                      :disabled="isNeedsFix || savingPrice || isReviewing"
                      @input="onPriceInput(variant.id, ($event.target as HTMLInputElement).value)"
                    />
                  </label>
                </div>
              </div>

              <div class="price-actions">
                <ErpButton
                  variant="secondary"
                  :disabled="isNeedsFix || !priceDirty || savingPrice || isReviewing"
                  @click="savePrices"
                >
                  {{ savingPrice ? "保存中…" : "保存价格" }}
                </ErpButton>
                <span v-if="priceDirty" class="price-dirty">未保存，通过前会自动保存</span>
              </div>
            </section>

            <ListingPreviewPanel
              v-if="!isNeedsFix"
              :preview="listingBundle.preview"
              :summary="listingBundle.saved_listing?.summary || listingBundle.preview.summary"
              :show-payload="false"
              title="上架内容摘要"
            />

            <div class="review-actions">
              <label class="erp-field erp-field--grow">
                <span>备注</span>
                <input v-model="reviewNote" type="text" placeholder="通过 / 修改原因" />
              </label>
              <div class="review-actions__btns">
                <template v-if="isNeedsFix">
                  <ErpButton :disabled="isReviewing || store.loading.value" @click="openForFix">
                    {{ reviewingAction === "fix" ? "打开中…" : "去编辑修复" }}
                  </ErpButton>
                </template>
                <template v-else>
                  <ErpButton :disabled="isReviewing || store.loading.value || imageCount < 5" @click="approve">
                    {{ reviewingAction === "approve" ? "推送中…" : "通过并推送" }}
                  </ErpButton>
                  <ErpButton variant="danger" :disabled="isReviewing || store.loading.value" @click="reject">
                    {{ reviewingAction === "reject" ? "驳回中…" : "驳回" }}
                  </ErpButton>
                </template>
              </div>
            </div>
          </template>
          <ErpEmpty v-else message="请选择左侧待处理商品" />
        </ErpCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.review-layout {
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.review-filters {
  display: flex;
  gap: 6px;
  padding: 10px 12px;
  border-bottom: 1px solid rgba(16, 24, 40, 0.08);
}

.review-filter {
  border: 1px solid rgba(16, 24, 40, 0.12);
  background: #fff;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  color: #475467;
}

.review-filter.active {
  background: rgba(21, 83, 100, 0.1);
  border-color: rgba(21, 83, 100, 0.35);
  color: #155364;
  font-weight: 600;
}

.review-list {
  display: flex;
  flex-direction: column;
  max-height: min(70vh, 720px);
  overflow: auto;
}

.review-list__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  border: 0;
  border-bottom: 1px solid rgba(16, 24, 40, 0.06);
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.review-list__item:hover {
  background: rgba(21, 83, 100, 0.04);
}

.review-list__item.is-selected {
  background: rgba(21, 83, 100, 0.08);
}

.review-loading {
  padding: 24px 0;
  color: #667085;
  font-size: 14px;
}

.review-hero {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.review-hero__media,
.review-hero__placeholder {
  width: 112px;
  height: 112px;
  border-radius: 10px;
  overflow: hidden;
  background: #f2f4f7;
}

.review-hero__media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.review-hero__placeholder {
  display: grid;
  place-items: center;
  color: #98a2b3;
  font-size: 13px;
}

.review-hero__body {
  min-width: 0;
}

.review-hero__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.review-hero__title {
  margin: 0 0 8px;
  font-size: 16px;
  line-height: 1.45;
  font-weight: 650;
  color: #101828;
  word-break: break-word;
}

.review-hero__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-bottom: 6px;
  font-size: 12px;
  color: #667085;
}

.review-hero__meta .is-warn {
  color: #b42318;
  font-weight: 600;
}

.review-hero__source {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: #98a2b3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.review-alert {
  display: grid;
  gap: 8px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 10px;
  background: #fef3f2;
  border: 1px solid #fecdca;
}

.review-alert strong {
  color: #b42318;
  font-size: 13px;
}

.review-alert p {
  margin: 0;
  color: #912018;
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.review-thumbs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.review-thumbs__item {
  width: 64px;
  text-align: center;
}

.review-thumbs__item img {
  width: 64px;
  height: 64px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid rgba(16, 24, 40, 0.08);
}

.review-thumbs__item span {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  color: #667085;
}

.review-section {
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(16, 24, 40, 0.08);
}

.review-section__title {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 650;
  color: #344054;
}

.supplier-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px;
  border-radius: 8px;
  background: rgba(21, 83, 100, 0.05);
}

.price-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.price-cell {
  padding: 10px 12px;
  border-radius: 8px;
  background: #f9fafb;
}

.price-cell span {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: #667085;
}

.price-cell strong {
  font-size: 15px;
  color: #101828;
}

.price-input {
  width: 100%;
  box-sizing: border-box;
  margin-top: 2px;
  padding: 8px 10px;
  border: 1px solid rgba(16, 24, 40, 0.14);
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
}

.price-input:focus {
  outline: 2px solid rgba(21, 83, 100, 0.25);
  border-color: #155364;
}

.variant-price-list {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.variant-price-row {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(120px, 0.8fr);
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f9fafb;
}

.variant-price-row__meta {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.variant-price-row__meta strong {
  font-size: 13px;
  color: #101828;
}

.variant-price-row__meta span {
  font-size: 12px;
  color: #667085;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.variant-price-row__field span {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: #667085;
}

.price-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}

.price-dirty {
  font-size: 12px;
  color: #b54708;
}

.review-formula {
  margin: 8px 0 0;
  font-size: 12px;
  color: #667085;
  word-break: break-all;
}

.review-muted {
  margin: 6px 0 0;
  font-size: 12px;
  color: #98a2b3;
}

.review-actions {
  display: grid;
  gap: 12px;
  margin-top: 8px;
  padding-top: 4px;
  position: sticky;
  bottom: 0;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.85), #fff 40%);
}

.review-actions__btns {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 960px) {
  .review-layout {
    grid-template-columns: 1fr;
  }

  .review-hero {
    grid-template-columns: 88px minmax(0, 1fr);
  }

  .review-hero__media,
  .review-hero__placeholder {
    width: 88px;
    height: 88px;
  }

  .price-grid {
    grid-template-columns: 1fr;
  }

  .variant-price-row {
    grid-template-columns: 1fr;
  }
}
</style>

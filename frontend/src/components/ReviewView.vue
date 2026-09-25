<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { apiRequest } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";
import { getModuleDefinition } from "../config/modules";
import type { ListingPreview, ProductEdit, SupplierCandidate } from "../types/ozon-workflow";
import { resolveEditImage } from "../utils/product-display";
import { getStatusMeta } from "../utils/status";
import AuditCard, { type AuditCardModel, type AuditSavePayload } from "./AuditCard.vue";
import ErpEmpty from "./erp/ErpEmpty.vue";
import ErpPageHeader from "./erp/ErpPageHeader.vue";
import ErpStatGrid from "./erp/ErpStatGrid.vue";

interface ReviewListingBundle {
  edit: ProductEdit;
  preview: ListingPreview;
  suppliers?: SupplierCandidate[];
  selected_supplier?: SupplierCandidate | null;
  pipeline_error?: string | null;
  failure_kind?: string | null;
}

type ListFilter = "all" | "pending_review" | "needs_fix";

const store = useAppStore();
const module = getModuleDefinition("review");
const listFilter = ref<ListFilter>("all");
const openEditId = ref<number | null>(null);
const bundles = ref<Record<number, ReviewListingBundle>>({});
const syncKeys = ref<Record<number, number>>({});
const busyId = ref<number | null>(null);
const selectedIds = ref<number[]>([]);
const batchBusy = ref(false);
const batchProgress = ref("");

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
const filteredIdSet = computed(() => new Set(filteredEdits.value.map((item) => item.id)));
const selectedInView = computed(() =>
  selectedIds.value.filter((id) => filteredIdSet.value.has(id)),
);
const allSelected = computed(
  () => filteredEdits.value.length > 0 && selectedInView.value.length === filteredEdits.value.length,
);
const someSelected = computed(
  () => selectedInView.value.length > 0 && selectedInView.value.length < filteredEdits.value.length,
);
const pageBusy = computed(() => busyId.value != null || batchBusy.value);

watch(filteredEdits, (edits) => {
  const keep = new Set(edits.map((item) => item.id));
  selectedIds.value = selectedIds.value.filter((id) => keep.has(id));
});

function isSelected(editId: number): boolean {
  return selectedIds.value.includes(editId);
}

function toggleSelected(editId: number, checked: boolean): void {
  if (checked) {
    if (!selectedIds.value.includes(editId)) {
      selectedIds.value = [...selectedIds.value, editId];
    }
    return;
  }
  selectedIds.value = selectedIds.value.filter((id) => id !== editId);
}

function toggleSelectAll(checked: boolean): void {
  if (!checked) {
    selectedIds.value = selectedIds.value.filter((id) => !filteredIdSet.value.has(id));
    return;
  }
  const merged = new Set(selectedIds.value);
  for (const edit of filteredEdits.value) merged.add(edit.id);
  selectedIds.value = [...merged];
}

function galleryCount(edit: ProductEdit): number {
  const bundle = bundles.value[edit.id];
  const source = bundle?.edit ?? edit;
  return galleryImages(source).length;
}

function attrText(attrs: Record<string, unknown> | null | undefined, keys: string[], fallback: string): string {
  for (const key of keys) {
    const value = attrs?.[key];
    if (value != null && String(value).trim()) return String(value).trim();
  }
  return fallback;
}

function positiveInt(raw: string, fallback: number): number {
  const num = Number(raw);
  return Number.isFinite(num) && num > 0 ? Math.round(num) : fallback;
}

function productUrl(edit: ProductEdit): string | null {
  const direct = edit.family_source_url?.trim();
  if (direct && /^https?:\/\//i.test(direct)) return direct;
  const externalId = edit.family_external_id?.trim();
  if (externalId) return `https://www.ozon.ru/product/${externalId}/`;
  return null;
}

function optionalMm(raw: unknown): number | null {
  const num = Number(raw);
  if (!Number.isFinite(num) || num <= 0) return null;
  return Math.round(num);
}

function galleryImages(edit: ProductEdit): string[] {
  const urls: string[] = [];
  const push = (url: string | null | undefined) => {
    const text = url?.trim();
    if (text && !urls.includes(text)) urls.push(text);
  };
  for (const url of edit.images || []) push(typeof url === "string" ? url : "");
  if (urls.length) return urls;
  push(edit.family_main_image_url);
  for (const variant of edit.variants || []) push(variant.image_url);
  return urls;
}

function variantColor(variant: ProductEdit["variants"][number]): string {
  return attrText(
    variant.variant_attributes as Record<string, unknown> | null,
    ["Цвет", "Цвет товара", "Название цвета", "颜色", "color"],
    "",
  );
}

function modelFor(edit: ProductEdit): AuditCardModel {
  const bundle = bundles.value[edit.id];
  const source = bundle?.edit ?? edit;
  const attrs = (source.attributes || {}) as Record<string, unknown>;
  const manual = String(attrs.package_manual || "") === "1";
  const supplier = bundle?.selected_supplier
    || (bundle?.suppliers || []).find((item) => item.status === "selected")
    || null;
  const failureKind = bundle?.failure_kind && bundle.failure_kind !== "needs_fix"
    ? getStatusMeta(String(bundle.failure_kind)).label
    : "";
  const failureReason = String(bundle?.pipeline_error || attrs.pipeline_error || failureKind || "").trim();
  const images = (source.images || []).filter((url) => typeof url === "string" && url.trim());

  return {
    editId: source.id,
    title: source.title,
    imageUrl: resolveEditImage(source),
    externalId: source.family_external_id,
    productUrl: productUrl(source),
    skuCount: source.variants?.length || 0,
    imageCount: images.length,
    status: source.status,
    failureReason,
    supplierName: supplier?.supplier_name || supplier?.shop_name || null,
    supplierPrice: supplier?.price_text || null,
    matchScore: supplier?.match_score ?? null,
    packageManual: manual,
    aspect: String(attrs.variant_aspect || "") === "size" ? "size" : "color",
    depthMm: manual ? positiveInt(attrText(attrs, ["Длина, мм", "depth_mm", "length_mm"], "100"), 100) : 100,
    widthMm: manual ? positiveInt(attrText(attrs, ["Ширина, мм", "width_mm"], "100"), 100) : 100,
    heightMm: manual ? positiveInt(attrText(attrs, ["Высота, мм", "height_mm"], "100"), 100) : 100,
    weightG: manual ? positiveInt(attrText(attrs, ["Вес, г", "weight_g", "Вес товара, г"], "200"), 200) : 200,
    netDepthMm: optionalMm(attrs.net_depth_mm),
    netWidthMm: optionalMm(attrs.net_width_mm),
    netHeightMm: optionalMm(attrs.net_height_mm),
    images: galleryImages(source),
    variants: (source.variants || []).map((variant) => {
      const variantAttrs = (variant.variant_attributes || {}) as Record<string, unknown>;
      const attrImages = Array.isArray(variantAttrs.images)
        ? (variantAttrs.images as unknown[]).filter((url): url is string => typeof url === "string" && !!url.trim())
        : [];
      const primary = String(variant.image_url || variantAttrs.image_url || "").trim();
      const images: string[] = [];
      const seen = new Set<string>();
      for (const url of [primary, ...attrImages]) {
        const text = String(url || "").trim();
        if (!text || seen.has(text)) continue;
        seen.add(text);
        images.push(text);
      }
      // 旧数据变体图不足时：把商品级图拷入，作为该 listing 的初始主图+副图
      if (images.length < 5) {
        for (const url of source.images || []) {
          const text = String(url || "").trim();
          if (!text || seen.has(text)) continue;
          seen.add(text);
          images.push(text);
        }
      }
      return {
        id: variant.id,
        sku: variant.sku,
        title: (variant.title || source.title || "").trim(),
        imageUrl: images[0] || primary || null,
        images,
        color: variantColor(variant),
        size: attrText(variantAttrs, ["Размер", "Размер товара", "尺码"], ""),
        price: variant.price ?? null,
        quantity: variant.quantity ?? 99,
        netDepth: optionalMm(variantAttrs.net_depth_mm) ?? optionalMm(attrs.net_depth_mm),
        netWidth: optionalMm(variantAttrs.net_width_mm) ?? optionalMm(attrs.net_width_mm),
        netHeight: optionalMm(variantAttrs.net_height_mm) ?? optionalMm(attrs.net_height_mm),
      };
    }),
  };
}

function bumpSync(editId: number): void {
  syncKeys.value = { ...syncKeys.value, [editId]: (syncKeys.value[editId] ?? 0) + 1 };
}

async function toggle(editId: number, opened: boolean): Promise<void> {
  openEditId.value = opened ? editId : null;
  if (!opened || bundles.value[editId]) return;
  try {
    const bundle = await apiRequest<ReviewListingBundle>(`/api/reviews/${editId}/listing`);
    bundles.value = { ...bundles.value, [editId]: bundle };
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  }
}

async function saveContent(editId: number, payload: AuditSavePayload): Promise<boolean> {
  const result = await apiRequest<{ ok?: boolean; message?: string; bundle?: ReviewListingBundle }>(
    `/api/reviews/${editId}/content`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
  if (result.bundle) {
    bundles.value = { ...bundles.value, [editId]: result.bundle };
    bumpSync(editId);
  }
  store.showNotice(result.message || "已保存");
  if (!result.ok) {
    store.showError(result.message || "已保存，但 Listing 仍未通过");
    await store.refreshAll();
    return false;
  }
  await store.refreshAll();
  return true;
}

async function onApprove(editId: number, payload: AuditSavePayload): Promise<void> {
  if (pageBusy.value) return;
  const edit = pendingEdits.value.find((item) => item.id === editId);
  if (!edit) return;
  if (payload.images.length < 5) {
    store.showError(`图片不足：需要 5 张，当前 ${payload.images.length} 张，无法推送`);
    return;
  }
  busyId.value = editId;
  store.showNotice("正在通过并自动推送…");
  try {
    const ok = await saveContent(editId, payload);
    if (!ok) return;
    await apiRequest(`/api/reviews/${editId}/approve`, {
      method: "POST",
      body: JSON.stringify({ note: "通过并自动推送", auto_publish: true }),
    });
    store.showNotice("已通过并开始自动推送 / 拉取状态");
    if (openEditId.value === editId) openEditId.value = null;
    selectedIds.value = selectedIds.value.filter((id) => id !== editId);
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    busyId.value = null;
  }
}

async function onSave(editId: number, payload: AuditSavePayload): Promise<void> {
  if (pageBusy.value) return;
  busyId.value = editId;
  try {
    await saveContent(editId, payload);
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    busyId.value = null;
  }
}

async function onReject(editId: number): Promise<void> {
  if (pageBusy.value) return;
  busyId.value = editId;
  store.showNotice("正在驳回…");
  try {
    await apiRequest(`/api/reviews/${editId}/reject`, {
      method: "POST",
      body: JSON.stringify({ note: "需修改" }),
    });
    store.showNotice("已驳回");
    if (openEditId.value === editId) openEditId.value = null;
    selectedIds.value = selectedIds.value.filter((id) => id !== editId);
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    busyId.value = null;
  }
}

async function batchApproveSelected(): Promise<void> {
  if (pageBusy.value || !selectedInView.value.length) return;
  const targets = filteredEdits.value.filter((edit) => selectedInView.value.includes(edit.id));
  const skipFix = targets.filter((edit) => edit.status === "needs_fix");
  const skipImages = targets.filter(
    (edit) => edit.status === "pending_review" && galleryCount(edit) < 5,
  );
  const queue = targets.filter(
    (edit) => edit.status === "pending_review" && galleryCount(edit) >= 5,
  );
  if (!queue.length) {
    const reasons: string[] = [];
    if (skipFix.length) reasons.push(`${skipFix.length} 条待修复需先处理`);
    if (skipImages.length) reasons.push(`${skipImages.length} 条图片不足 5 张`);
    store.showError(reasons.join("；") || "没有可批量通过的商品");
    return;
  }
  batchBusy.value = true;
  let okCount = 0;
  const errors: string[] = [];
  try {
    for (let index = 0; index < queue.length; index += 1) {
      const edit = queue[index];
      batchProgress.value = `批量通过 ${index + 1}/${queue.length}：${edit.title || edit.id}`;
      store.showNotice(batchProgress.value);
      try {
        await apiRequest(`/api/reviews/${edit.id}/approve`, {
          method: "POST",
          body: JSON.stringify({ note: "批量通过并自动推送", auto_publish: true }),
        });
        okCount += 1;
        selectedIds.value = selectedIds.value.filter((id) => id !== edit.id);
        if (openEditId.value === edit.id) openEditId.value = null;
      } catch (err) {
        errors.push(`${edit.family_external_id || edit.id}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    await store.refreshAll();
    const skipped = skipFix.length + skipImages.length;
    const parts = [`已通过并推送 ${okCount} 条`];
    if (skipped) parts.push(`跳过 ${skipped} 条`);
    if (errors.length) parts.push(`失败 ${errors.length} 条`);
    store.showNotice(parts.join("，"));
    if (errors.length) store.showError(errors.slice(0, 3).join("；"));
  } finally {
    batchBusy.value = false;
    batchProgress.value = "";
  }
}

async function batchRejectSelected(): Promise<void> {
  if (pageBusy.value || !selectedInView.value.length) return;
  const targets = filteredEdits.value.filter((edit) => selectedInView.value.includes(edit.id));
  const queue = targets.filter((edit) => edit.status === "pending_review" || edit.status === "needs_fix");
  const skipped = targets.length - queue.length;
  if (!queue.length) {
    store.showError("没有可驳回的商品（仅待审核/待修复可驳回）");
    return;
  }
  if (!window.confirm(`确定驳回选中的 ${queue.length} 条商品？${skipped ? `（另有 ${skipped} 条状态不符将跳过）` : ""}`)) {
    return;
  }
  batchBusy.value = true;
  let okCount = 0;
  const errors: string[] = [];
  try {
    for (let index = 0; index < queue.length; index += 1) {
      const edit = queue[index];
      batchProgress.value = `批量驳回 ${index + 1}/${queue.length}`;
      store.showNotice(batchProgress.value);
      try {
        await apiRequest(`/api/reviews/${edit.id}/reject`, {
          method: "POST",
          body: JSON.stringify({ note: "批量驳回" }),
        });
        okCount += 1;
        selectedIds.value = selectedIds.value.filter((id) => id !== edit.id);
        if (openEditId.value === edit.id) openEditId.value = null;
      } catch (err) {
        errors.push(`${edit.family_external_id || edit.id}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    await store.refreshAll();
    const parts = [`已驳回 ${okCount} 条`];
    if (skipped) parts.push(`跳过 ${skipped} 条`);
    if (errors.length) parts.push(`失败 ${errors.length} 条`);
    store.showNotice(parts.join("，"));
    if (errors.length) store.showError(errors.slice(0, 3).join("；"));
  } finally {
    batchBusy.value = false;
    batchProgress.value = "";
  }
}
</script>

<template>
  <div class="erp-stack review-page">
    <ErpPageHeader :title="module.label" :description="module.description" />

    <ErpStatGrid
      :items="[
        { label: '待处理', value: pendingEdits.length, hint: '待审 + 待修复' },
        { label: '待审核', value: pendingReviewCount },
        { label: '待修复', value: needsFixCount },
      ]"
    />

    <div class="review-filters">
      <button type="button" :class="{ active: listFilter === 'all' }" @click="listFilter = 'all'">
        全部 {{ pendingEdits.length }}
      </button>
      <button type="button" :class="{ active: listFilter === 'pending_review' }" @click="listFilter = 'pending_review'">
        待审核 {{ pendingReviewCount }}
      </button>
      <button type="button" :class="{ active: listFilter === 'needs_fix' }" @click="listFilter = 'needs_fix'">
        待修复 {{ needsFixCount }}
      </button>
    </div>

    <div v-if="filteredEdits.length" class="review-batch">
      <label class="review-batch__check">
        <input
          type="checkbox"
          :checked="allSelected"
          :indeterminate.prop="someSelected"
          :disabled="pageBusy"
          @change="toggleSelectAll(($event.target as HTMLInputElement).checked)"
        />
        全选当前列表
      </label>
      <span class="review-batch__count">已选 {{ selectedInView.length }}</span>
      <span v-if="batchProgress" class="review-batch__progress">{{ batchProgress }}</span>
      <div class="review-batch__actions">
        <button
          type="button"
          class="btn-primary"
          :disabled="pageBusy || !selectedInView.length"
          @click="batchApproveSelected"
        >
          批量通过并推送
        </button>
        <button
          type="button"
          class="btn-ghost"
          :disabled="pageBusy || !selectedInView.length"
          @click="batchRejectSelected"
        >
          批量驳回
        </button>
      </div>
    </div>

    <div v-if="filteredEdits.length" class="review-list">
      <div
        v-for="edit in filteredEdits"
        :key="edit.id"
        class="review-row"
        :class="{ 'is-selected': isSelected(edit.id) }"
      >
        <label class="review-row__check">
          <input
            type="checkbox"
            :checked="isSelected(edit.id)"
            :disabled="pageBusy"
            @change="toggleSelected(edit.id, ($event.target as HTMLInputElement).checked)"
          />
        </label>
        <AuditCard
          class="review-row__card"
          :item="modelFor(edit)"
          :sync-key="syncKeys[edit.id] ?? 0"
          :open="openEditId === edit.id"
          :busy="pageBusy"
          @update:open="toggle(edit.id, $event)"
          @approve="onApprove(edit.id, $event)"
          @save="onSave(edit.id, $event)"
          @reject="onReject(edit.id)"
          @open-sourcing="store.setModule('sourcing')"
        />
      </div>
    </div>
    <ErpEmpty v-else message="没有待审核或待修复的商品" />
  </div>
</template>

<style scoped>
.review-page {
  background: transparent;
}
.review-filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.review-filters button {
  border: 1px solid var(--erp-border, #e5e7eb);
  background: #fff;
  border-radius: 999px;
  padding: 6px 14px;
  cursor: pointer;
  color: #344054;
}
.review-filters button.active {
  background: #155364;
  border-color: #155364;
  color: #fff;
}
.review-batch {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
  padding: 10px 14px;
  border: 1px solid var(--erp-border, #e5e7eb);
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 1px 0 rgba(16, 24, 40, 0.04);
}
.review-batch__check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #344054;
  cursor: pointer;
  user-select: none;
}
.review-batch__count {
  color: #667085;
  font-size: 13px;
}
.review-batch__progress {
  color: #155364;
  font-size: 13px;
}
.review-batch__actions {
  margin-left: auto;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.review-batch .btn-primary,
.review-batch .btn-ghost {
  border-radius: 8px;
  padding: 7px 12px;
  cursor: pointer;
  font: inherit;
}
.review-batch .btn-primary {
  border: 1px solid #155364;
  background: #155364;
  color: #fff;
}
.review-batch .btn-ghost {
  border: 1px solid var(--erp-border, #e5e7eb);
  background: #fff;
  color: #344054;
}
.review-batch button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.review-list {
  display: grid;
  gap: 16px;
}
.review-row {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}
.review-row.is-selected .review-row__card {
  outline: 2px solid rgba(21, 83, 100, 0.35);
  outline-offset: 0;
}
.review-row__check {
  display: flex;
  justify-content: center;
  padding-top: 22px;
  cursor: pointer;
}
.review-row__card {
  min-width: 0;
}
</style>

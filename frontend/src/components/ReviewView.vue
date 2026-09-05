<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { apiRequest } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";
import { getModuleDefinition } from "../config/modules";
import type { ListingPreview, ProductEdit } from "../types/ozon-workflow";
import { resolveEditImage, resolveEditSubtitle, formatMoney, resolveCurrencyCode } from "../utils/product-display";
import ErpBadge from "./erp/ErpBadge.vue";
import ErpButton from "./erp/ErpButton.vue";
import ErpCard from "./erp/ErpCard.vue";
import ErpEmpty from "./erp/ErpEmpty.vue";
import ErpPageHeader from "./erp/ErpPageHeader.vue";
import ErpProductCell from "./erp/ErpProductCell.vue";
import ErpStatGrid from "./erp/ErpStatGrid.vue";
import ListingPreviewPanel from "./ListingPreviewPanel.vue";

const store = useAppStore();
const module = getModuleDefinition("review");
const selectedEditId = ref<number | null>(null);
const listingBundle = ref<{
  edit: ProductEdit;
  preview: ListingPreview;
  saved_listing?: ListingPreview["saved_listing"];
} | null>(null);
const reviewNote = ref("通过");
const loadingDetail = ref(false);

const pendingEdits = computed(() =>
  store.state.value.edits.filter((item) => item.status === "pending_review"),
);

const selectedEdit = computed(() =>
  pendingEdits.value.find((item) => item.id === selectedEditId.value) ?? null,
);

watch(
  pendingEdits,
  (list) => {
    if (!list.length) {
      selectedEditId.value = null;
      listingBundle.value = null;
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
    reviewNote.value = "通过";
  } catch (err) {
    listingBundle.value = null;
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    loadingDetail.value = false;
  }
}

async function approve(): Promise<void> {
  if (selectedEditId.value == null) return;
  try {
    await apiRequest(`/api/reviews/${selectedEditId.value}/approve`, {
      method: "POST",
      body: JSON.stringify({ note: reviewNote.value || "通过" }),
    });
    store.showNotice("Listing 审核通过");
    selectedEditId.value = null;
    listingBundle.value = null;
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  }
}

async function reject(): Promise<void> {
  if (selectedEditId.value == null) return;
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
  }
}
</script>

<template>
  <div class="erp-stack">
    <ErpPageHeader :title="module.label" :description="module.description" />

    <ErpStatGrid
      :items="[
        { label: '待审核 Listing', value: pendingEdits.length, hint: '需处理' },
        { label: '已通过', value: store.stats.value.approved },
        { label: '编辑总数', value: store.state.value.edits.length },
      ]"
    />

    <div class="review-layout">
      <ErpCard title="待审列表" :description="`${pendingEdits.length} 条 · 点行查看详情`" padding="none">
        <div v-if="pendingEdits.length" class="erp-table-wrap">
          <table class="erp-table">
            <thead>
              <tr>
                <th>商品</th>
                <th>价格</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="edit in pendingEdits"
                :key="edit.id"
                class="is-clickable"
                :class="{ 'is-selected': edit.id === selectedEditId }"
                @click="openListing(edit.id)"
              >
                <td>
                  <ErpProductCell
                    :image-url="resolveEditImage(edit)"
                    :title="edit.title"
                    :subtitle="resolveEditSubtitle(edit)"
                  />
                </td>
                <td>{{ formatMoney(edit.variants?.[0]?.price, resolveCurrencyCode(edit.attributes)) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <ErpEmpty v-else message="暂无待审 Listing。请在商品编辑中生成 Listing 并提交审核。" />
      </ErpCard>

      <ErpCard
        title="Listing 审核详情"
        :description="selectedEdit ? '核对主图、标题、价格与上架字段后通过或驳回' : '选择左侧条目查看完整上架内容'"
      >
        <div v-if="loadingDetail" class="erp-detail-text">加载中…</div>
        <template v-else-if="listingBundle">
          <div class="erp-detail-hero" style="margin-bottom: 16px">
            <ErpProductCell
              size="lg"
              :image-url="resolveEditImage(listingBundle.edit)"
              :title="listingBundle.edit.title"
              :subtitle="resolveEditSubtitle(listingBundle.edit)"
            />
            <div class="erp-detail-hero__copy">
              <div class="erp-detail-hero__meta">
                <ErpBadge :status="listingBundle.edit.status" />
                <span v-if="listingBundle.edit.family_external_id">
                  Ozon ID {{ listingBundle.edit.family_external_id }}
                </span>
                <span v-if="listingBundle.edit.category_name">
                  {{ listingBundle.edit.category_name }}
                </span>
                <span>类目 {{ listingBundle.preview.summary.description_category_id || "-" }}</span>
                <span>type_id {{ listingBundle.preview.summary.type_id || "-" }}</span>
              </div>
              <p v-if="listingBundle.edit.family_title" class="erp-detail-text">
                源品标题：{{ listingBundle.edit.family_title }}
              </p>
            </div>
          </div>

          <ListingPreviewPanel
            :preview="listingBundle.preview"
            :summary="listingBundle.saved_listing?.summary || listingBundle.preview.summary"
            :show-payload="true"
            title="待审上架内容"
          />

          <div class="erp-form-row" style="margin-top: 16px">
            <label class="erp-field erp-field--grow">
              <span>审核备注</span>
              <input v-model="reviewNote" type="text" placeholder="通过 / 需修改原因" />
            </label>
          </div>
          <div class="erp-editor-actions" style="margin-top: 12px">
            <ErpButton :disabled="store.loading.value" @click="approve">通过</ErpButton>
            <ErpButton variant="danger" :disabled="store.loading.value" @click="reject">驳回</ErpButton>
          </div>
        </template>
        <ErpEmpty v-else message="请选择待审 Listing" />
      </ErpCard>
    </div>
  </div>
</template>

<style scoped>
.review-layout {
  display: grid;
  grid-template-columns: minmax(300px, 0.95fr) minmax(360px, 1.35fr);
  gap: 16px;
  align-items: start;
}

.erp-table tr.is-clickable {
  cursor: pointer;
}

.erp-table tr.is-selected td {
  background: rgba(21, 83, 100, 0.06);
}

@media (max-width: 960px) {
  .review-layout {
    grid-template-columns: 1fr;
  }
}
</style>

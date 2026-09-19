<script setup lang="ts">
import { computed, ref } from "vue";

import { apiRequest } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";
import { getModuleDefinition } from "../config/modules";
import type { SourcingDetail, SupplierCandidate } from "../types/ozon-workflow";
import ErpBadge from "./erp/ErpBadge.vue";
import ErpButton from "./erp/ErpButton.vue";
import ErpCard from "./erp/ErpCard.vue";
import ErpEmpty from "./erp/ErpEmpty.vue";
import ErpPageHeader from "./erp/ErpPageHeader.vue";
import ErpProductCell from "./erp/ErpProductCell.vue";
import ErpStatGrid from "./erp/ErpStatGrid.vue";

const store = useAppStore();
const module = getModuleDefinition("sourcing");

const selectedFamilyId = ref<number | null>(null);
const detailLoading = ref(false);
const detail = ref<SourcingDetail | null>(null);
const searchingFamilyId = ref<number | null>(null);
const selectingCandidateId = ref<number | null>(null);

const candidateCountByFamily = computed(() => {
  const counts = new Map<number, number>();
  for (const item of store.state.value.candidates) {
    counts.set(item.raw_product_family_id, (counts.get(item.raw_product_family_id) ?? 0) + 1);
  }
  return counts;
});

const selectedCountByFamily = computed(() => {
  const counts = new Map<number, number>();
  for (const item of store.state.value.candidates) {
    if (item.status !== "selected") continue;
    counts.set(item.raw_product_family_id, (counts.get(item.raw_product_family_id) ?? 0) + 1);
  }
  return counts;
});

const isSearching = computed(() => searchingFamilyId.value != null);

function productPrice(item: { price_text?: string | null; variants?: Array<{ price_text?: string | null }> }): string {
  return item.price_text || item.variants?.[0]?.price_text || "-";
}

function candidateCount(familyId: number): number {
  return candidateCountByFamily.value.get(familyId) ?? 0;
}

function selectedCount(familyId: number): number {
  return selectedCountByFamily.value.get(familyId) ?? 0;
}

function hasSuppliers(familyId: number): boolean {
  return candidateCount(familyId) > 0;
}

function isFamilySearching(familyId: number): boolean {
  return searchingFamilyId.value === familyId;
}

function searchButtonLabel(familyId: number): string {
  return isFamilySearching(familyId) ? "搜货中…" : "搜 1688";
}

function supplierRegion(candidate: SupplierCandidate): string {
  const raw = candidate.raw_payload;
  if (!raw) return "-";
  const parts = [raw.companyProvince, raw.companyCity].filter(Boolean);
  return parts.length ? parts.join(" · ") : "-";
}

function supplierMeta(candidate: SupplierCandidate, key: string): string {
  const value = candidate.raw_payload?.[key];
  return value != null && String(value).trim() ? String(value) : "-";
}

async function openDetail(familyId: number): Promise<void> {
  selectedFamilyId.value = familyId;
  detailLoading.value = true;
  detail.value = null;
  try {
    detail.value = await apiRequest<SourcingDetail>(`/api/sourcing/detail/${familyId}`);
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
    selectedFamilyId.value = null;
  } finally {
    detailLoading.value = false;
  }
}

function closeDetail(): void {
  selectedFamilyId.value = null;
  detail.value = null;
}

async function searchSuppliers(familyId: number): Promise<void> {
  if (searchingFamilyId.value != null) return;
  searchingFamilyId.value = familyId;
  store.showNotice("正在以图搜货，请稍候…");
  try {
    await apiRequest("/api/sourcing/search", {
      method: "POST",
      body: JSON.stringify({ raw_product_family_id: familyId }),
    });
    store.showNotice("货源搜索完成");
    await store.refreshAll();
    if (selectedFamilyId.value === familyId) {
      await openDetail(familyId);
    }
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    searchingFamilyId.value = null;
  }
}

async function selectCandidate(candidateId: number): Promise<void> {
  if (selectingCandidateId.value != null) return;
  selectingCandidateId.value = candidateId;
  store.showNotice("正在选定供应商…");
  try {
    await apiRequest(`/api/sourcing/candidates/${candidateId}/select`, { method: "POST" });
    store.showNotice("已选定供应商");
    await store.refreshAll();
    if (selectedFamilyId.value != null) {
      await openDetail(selectedFamilyId.value);
    }
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    selectingCandidateId.value = null;
  }
}

async function unselectCandidate(candidateId: number): Promise<void> {
  if (selectingCandidateId.value != null) return;
  selectingCandidateId.value = candidateId;
  store.showNotice("正在取消选定…");
  try {
    await apiRequest(`/api/sourcing/candidates/${candidateId}/unselect`, { method: "POST" });
    store.showNotice("已取消选定");
    await store.refreshAll();
    if (selectedFamilyId.value != null) {
      await openDetail(selectedFamilyId.value);
    }
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    selectingCandidateId.value = null;
  }
}
</script>

<template>
  <div class="erp-stack">
    <ErpPageHeader
      :title="selectedFamilyId ? '商品货源详情' : module.label"
      :description="selectedFamilyId ? '查看 Ozon 商品与对应 1688 供应商' : module.description"
    >
      <template v-if="selectedFamilyId" #actions>
        <ErpButton variant="secondary" size="sm" @click="closeDetail">返回列表</ErpButton>
      </template>
    </ErpPageHeader>

    <template v-if="!selectedFamilyId">
      <ErpStatGrid
        :items="[
          { label: '待搜货商品', value: store.state.value.ozonProducts.length },
          { label: '货源候选', value: store.stats.value.candidates },
          { label: '已选定', value: store.state.value.candidates.filter((c) => c.status === 'selected').length },
        ]"
      />

      <ErpCard title="商品货源" :description="`${store.state.value.ozonProducts.length} 条`" padding="none">
        <div v-if="isSearching" class="sourcing-searching-banner">
          正在以图搜货中，通常需要十几秒，请勿重复点击…
        </div>
        <div v-if="store.state.value.ozonProducts.length" class="erp-table-wrap">
          <table class="erp-table">
            <thead>
              <tr>
                <th>商品</th>
                <th>价格</th>
                <th>货源数</th>
                <th>已选货源数</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in store.state.value.ozonProducts"
                :key="item.id"
                :class="{ 'erp-row--busy': isFamilySearching(item.id) }"
              >
                <td>
                  <ErpProductCell
                    :image-url="item.main_image_url"
                    :title="item.title"
                    :subtitle="`SKU ${item.external_id || '-'}`"
                  />
                </td>
                <td>{{ productPrice(item) }}</td>
                <td>{{ candidateCount(item.id) }}</td>
                <td>{{ selectedCount(item.id) }}</td>
                <td>
                  <div class="erp-table-actions">
                    <ErpButton
                      variant="secondary"
                      size="sm"
                      :disabled="isSearching"
                      @click="openDetail(item.id)"
                    >
                      {{ hasSuppliers(item.id) ? "查看货源" : "查看" }}
                    </ErpButton>
                    <ErpButton
                      v-if="!hasSuppliers(item.id) || isFamilySearching(item.id)"
                      size="sm"
                      :disabled="isSearching"
                      @click="searchSuppliers(item.id)"
                    >
                      {{ searchButtonLabel(item.id) }}
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

    <template v-else>
      <p v-if="detailLoading" class="erp-detail-text">加载详情中…</p>

      <template v-else-if="detail">
        <ErpCard padding="none">
          <div class="erp-card__body">
            <div class="erp-detail-hero">
              <ErpProductCell
                size="lg"
                :image-url="detail.product.main_image_url"
                :title="detail.product.title"
                :subtitle="detail.product.brand"
              />
              <div class="erp-detail-hero__copy">
                <div class="erp-detail-hero__meta">
                  <span>SKU {{ detail.product.sku || detail.product.external_id || "-" }}</span>
                  <span>{{ detail.product.price_text || "-" }}</span>
                  <span>评分 {{ detail.product.rating || "-" }}</span>
                  <span>评论 {{ detail.product.review_count || "-" }}</span>
                </div>
                <div class="erp-table-actions">
                  <a
                    v-if="detail.product.source_url"
                    :href="detail.product.source_url"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Ozon 商品页
                  </a>
                  <ErpButton
                    v-if="!detail.candidates.length || isFamilySearching(detail.product.id)"
                    size="sm"
                    :disabled="isSearching"
                    @click="searchSuppliers(detail.product.id)"
                  >
                    {{ searchButtonLabel(detail.product.id) }}
                  </ErpButton>
                </div>
              </div>
            </div>
          </div>
        </ErpCard>

        <ErpCard title="商品信息">
          <div class="erp-detail-grid">
            <div class="erp-detail-item"><span>尺寸</span><strong>{{ detail.product.size || "-" }}</strong></div>
            <div class="erp-detail-item"><span>重量</span><strong>{{ detail.product.weight || "-" }}</strong></div>
            <div class="erp-detail-item"><span>类目</span><strong>{{ detail.product.category_name || "-" }}</strong></div>
            <div class="erp-detail-item"><span>类目 ID</span><strong>{{ detail.product.description_category_id || "-" }}</strong></div>
            <div class="erp-detail-item"><span>type_id</span><strong>{{ detail.product.type_id || "-" }}</strong></div>
            <div class="erp-detail-item"><span>热销排名</span><strong>{{ detail.product.sales_rank ?? "-" }}</strong></div>
          </div>
          <p class="erp-detail-text" style="margin-top: 14px">
            {{ detail.product.description || "暂无描述（采集时未获取 Ozon 详情页描述）" }}
          </p>
          <div
            v-if="detail.product.attributes && Object.keys(detail.product.attributes).length"
            class="erp-detail-grid"
            style="margin-top: 14px"
          >
            <div
              v-for="(value, key) in detail.product.attributes"
              :key="key"
              class="erp-detail-item"
            >
              <span>{{ key }}</span>
              <strong>{{ value }}</strong>
            </div>
          </div>
          <div v-if="detail.product.images?.length > 1" class="erp-image-strip" style="margin-top: 12px">
            <img v-for="(img, i) in detail.product.images" :key="`${img}-${i}`" :src="img" alt="商品图" />
          </div>
        </ErpCard>

        <ErpCard title="1688 供应商" :description="`${detail.candidates.length} 条`">
          <div v-if="detail.candidates.length" class="erp-stack">
            <article v-for="item in detail.candidates" :key="item.id" class="erp-supplier-card">
              <div class="erp-supplier-card__head">
                <ErpProductCell
                  :image-url="item.image_url"
                  :title="item.product_title"
                  :subtitle="`${item.supplier_name || '-'} · ${item.price_text || '-'} · 匹配 ${item.match_score ?? '-'}`"
                />
                <div class="erp-table-actions">
                  <ErpBadge :status="item.status" />
                  <ErpButton
                    v-if="item.status !== 'selected'"
                    size="sm"
                    :disabled="selectingCandidateId != null || isSearching"
                    @click="selectCandidate(item.id)"
                  >
                    {{ selectingCandidateId === item.id ? "选定中…" : "选定" }}
                  </ErpButton>
                  <ErpButton
                    v-else
                    size="sm"
                    variant="ghost"
                    :disabled="selectingCandidateId != null || isSearching"
                    @click="unselectCandidate(item.id)"
                  >
                    {{ selectingCandidateId === item.id ? "取消中…" : "取消选定" }}
                  </ErpButton>
                </div>
              </div>
              <div class="erp-detail-grid">
                <div class="erp-detail-item"><span>地区</span><strong>{{ supplierRegion(item) }}</strong></div>
                <div class="erp-detail-item"><span>月销量</span><strong>{{ item.min_order_qty || supplierMeta(item, "monthSold") }}</strong></div>
                <div class="erp-detail-item"><span>复购率</span><strong>{{ supplierMeta(item, "repurchaseRate") }}</strong></div>
                <div class="erp-detail-item"><span>综合评分</span><strong>{{ supplierMeta(item, "compositeScore") }}</strong></div>
              </div>
              <a v-if="item.product_url" :href="item.product_url" target="_blank" rel="noreferrer">打开 1688 商品页</a>
            </article>
          </div>
          <ErpEmpty v-else message="暂无货源">
            <ErpButton
              size="sm"
              :disabled="isSearching"
              style="margin-top: 12px"
              @click="searchSuppliers(detail.product.id)"
            >
              {{ searchButtonLabel(detail.product.id) }}
            </ErpButton>
            <p v-if="isFamilySearching(detail.product.id)" class="erp-detail-text" style="margin-top: 8px">
              正在以图搜货中，请稍候…
            </p>
          </ErpEmpty>
        </ErpCard>
      </template>
    </template>
  </div>
</template>

<style scoped>
.sourcing-searching-banner {
  margin: 12px 16px 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 13px;
  line-height: 1.4;
}

:deep(.erp-row--busy) {
  background: #f8fafc;
}

:deep(.erp-row--busy) .erp-btn--primary {
  opacity: 0.85;
}
</style>

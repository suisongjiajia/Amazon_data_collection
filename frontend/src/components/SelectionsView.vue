<script setup lang="ts">
import { toRef } from "vue";
import type { RawProductFamily, Selection, WorkflowFilters } from "../types/workflow";
import type { WorkflowActions, WorkflowHelpers } from "../types/view-context";

const props = defineProps<{
  filters: WorkflowFilters;
  filteredSelections: Selection[];
  selectedSelection: Selection | null;
  selectedSelectionFamily: RawProductFamily | null;
  helpers: WorkflowHelpers;
  actions: Pick<
    WorkflowActions,
    "openSelectionDetail" | "createProduct" | "closeSelectionDetail" | "saveSelectionScope" | "toggleVariantInScope" | "toggleVariantDetail"
  >;
}>();

const filters = props.filters;
const filteredSelections = toRef(props, "filteredSelections");
const selectedSelection = toRef(props, "selectedSelection");
const selectedSelectionFamily = toRef(props, "selectedSelectionFamily");

const {
  variantPreview,
  selectionCoverage,
  selectionLeadPrice,
  formatDate,
  getStatusLabel,
  getMarketplaceLabel,
  getFamilyImage,
  truncateUrl,
  isVariantExpanded,
  isVariantSelected,
  getVariantTitle,
  getVariantImage,
  getVariantBulletPoints,
  getVariantAttributeEntries,
} = props.helpers;

const { openSelectionDetail, createProduct, closeSelectionDetail, saveSelectionScope, toggleVariantInScope, toggleVariantDetail } =
  props.actions;
</script>

<template>
  <section class="panel-shell">
    <div class="panel-header">
      <div>
        <p class="eyebrow">选品</p>
        <h3>{{ selectedSelection ? "选品详情" : "选品列表" }}</h3>
      </div>
      <p>
        {{ selectedSelection ? "勾选变体后创建 SPU" : "管理待建品商品族" }}
      </p>
    </div>

    <template v-if="!selectedSelection">
      <div class="toolbar toolbar-compact">
        <label class="toolbar-field grow">
          <span>搜索选品</span>
          <input v-model="filters.selectionQuery" type="text" placeholder="标题 / 品牌 / 商品族键" />
        </label>
      </div>

      <div class="table-wrap list-table" v-if="filteredSelections.length">
        <table>
          <thead>
            <tr>
              <th class="col-product">商品</th>
              <th>来源链接</th>
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
                    <img v-if="getFamilyImage(selection)" :src="getFamilyImage(selection)" :alt="selection.family_title || '选品'" />
                    <span v-else>暂无图片</span>
                  </div>
                  <div class="list-product-copy">
                    <strong class="list-title">{{ selection.family_title || "未命名商品族" }}</strong>
                    <span class="list-subtitle">
                      {{ selection.family_brand || "品牌待定" }} · {{ selectionLeadPrice(selection) }}
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
                <span v-else>-</span>
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
                    打开
                  </button>
                  <button
                    type="button"
                    class="inline-button"
                    :disabled="selection.selection_status === 'converted'"
                    @click="createProduct(selection.id)"
                  >
                    {{ selection.selection_status === "converted" ? "已转化" : "创建 SPU" }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty-state">暂无选品，请先从采集加入。</p>
    </template>

    <div v-else class="detail-panel">
      <button type="button" class="secondary-button back-button" @click="closeSelectionDetail">返回列表</button>

      <div class="detail-hero">
        <div class="list-thumb detail-thumb" :class="{ placeholder: !getFamilyImage(selectedSelection) }">
          <img v-if="getFamilyImage(selectedSelection)" :src="getFamilyImage(selectedSelection)" :alt="selectedSelection.family_title || '选品'" />
          <span v-else>暂无图片</span>
        </div>
        <div class="detail-hero-copy">
          <h4>{{ selectedSelection.family_title || "未命名商品族" }}</h4>
          <div class="meta-line compact">
            <span>{{ selectedSelection.family_brand || "品牌待定" }}</span>
            <span>{{ getMarketplaceLabel(selectedSelection.family_marketplace) }}</span>
            <span>{{ selectionLeadPrice(selectedSelection) }}</span>
            <span>{{ selectionCoverage(selectedSelection) }}</span>
          </div>
          <div class="card-actions">
            <span class="status-pill" :data-status="selectedSelection.selection_status">
              {{ getStatusLabel(selectedSelection.selection_status) }}
            </span>
            <button type="button" class="inline-button" @click="saveSelectionScope(selectedSelection.id)">
              保存范围
            </button>
            <button
              type="button"
              class="inline-button"
              :disabled="selectedSelection.selection_status === 'converted'"
              @click="createProduct(selectedSelection.id)"
            >
              {{ selectedSelection.selection_status === "converted" ? "已转化" : "创建 SPU + SKU" }}
            </button>
          </div>
        </div>
      </div>

      <div class="detail-block">
        <div class="subpanel-head">
          <h5>变体范围</h5>
          <span>勾选要纳入的变体</span>
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
                <span v-else class="variant-card-placeholder">暂无图片</span>
              </div>

              <div class="variant-card-body">
                <div class="variant-card-line">
                  <h6 class="variant-card-title">{{ getVariantTitle(variant, selectedSelectionFamily) }}</h6>
                  <span class="spec-chip">{{ variantPreview(variant) }}</span>
                  <span v-if="variant.asin" class="asin-chip">{{ variant.asin }}</span>
                </div>
              </div>

              <div class="variant-card-side">
                <strong class="variant-price-text">{{ variant.price_text || "-" }}</strong>
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
                  <span>父 ASIN</span>
                  <strong>{{ variant.parent_asin }}</strong>
                </div>
                <div v-if="variant.snapshot_time" class="variant-meta-item">
                  <span>采集时间</span>
                  <strong>{{ formatDate(variant.snapshot_time) }}</strong>
                </div>
                <div v-if="variant.source_url" class="variant-meta-item variant-meta-item-wide">
                  <span>来源链接</span>
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
                  <li v-for="bullet in getVariantBulletPoints(variant, selectedSelectionFamily)" :key="bullet">
                    {{ bullet }}
                  </li>
                </ul>
              </div>

              <div v-if="getVariantAttributeEntries(variant).length" class="variant-attr-grid">
                <article v-for="[key, value] in getVariantAttributeEntries(variant)" :key="`${variant.id}-${key}`">
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
</template>

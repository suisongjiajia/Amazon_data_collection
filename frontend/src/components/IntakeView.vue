<script setup lang="ts">
import { toRef } from "vue";
import type { CollectionListRow, RawProductFamily, WorkflowFilters, WorkflowUiState } from "../types/workflow";
import type { SelectOption, WorkflowActions, WorkflowHelpers } from "../types/view-context";

const props = defineProps<{
  ui: WorkflowUiState;
  filters: WorkflowFilters;
  collectionListRows: CollectionListRow[];
  familyMarketplaceOptions: SelectOption[];
  filteredFamilies: RawProductFamily[];
  selectedFamily: RawProductFamily | null;
  helpers: WorkflowHelpers;
  actions: Pick<
    WorkflowActions,
    "submitCollection" | "addToSelection" | "openFamilyDetail" | "closeFamilyDetail" | "toggleVariantDetail"
  >;
}>();

const loading = toRef(props.ui, "loading");
const collectionUrl = toRef(props.ui, "collectionUrl");
const intakeTab = toRef(props.ui, "intakeTab");
const filters = props.filters;
const collectionListRows = toRef(props, "collectionListRows");
const familyMarketplaceOptions = toRef(props, "familyMarketplaceOptions");
const filteredFamilies = toRef(props, "filteredFamilies");
const selectedFamily = toRef(props, "selectedFamily");

const {
  variantPreview,
  familyLeadPrice,
  formatDate,
  getStatusLabel,
  getMarketplaceLabel,
  getFamilyImage,
  getFamilyStatusLabel,
  getFamilyStatusKey,
  truncateUrl,
  isVariantExpanded,
  getVariantTitle,
  getVariantImage,
  getVariantBulletPoints,
  getVariantAttributeEntries,
} = props.helpers;

const { submitCollection, addToSelection, openFamilyDetail, closeFamilyDetail, toggleVariantDetail } = props.actions;
</script>

<template>
  <section class="panel-shell">
    <div class="panel-header">
      <div>
        <p class="eyebrow">采集</p>
        <h3>{{ selectedFamily && intakeTab === "families" ? "商品族详情" : "采集入口" }}</h3>
      </div>
      <p>
        {{ selectedFamily && intakeTab === "families" ? "查看变体明细" : "提交链接，查看任务与商品族" }}
      </p>
    </div>

    <div class="action-bar">
      <label class="action-bar-field grow">
        <span>Amazon 链接</span>
        <input v-model="collectionUrl" type="text" placeholder="https://www.amazon.com/dp/..." />
      </label>
      <button type="button" class="action-bar-button" :disabled="loading" @click="submitCollection">
        {{ loading ? "提交中..." : "开始采集" }}
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
        任务
      </button>
    </div>

    <template v-if="intakeTab === 'tasks' && !selectedFamily">
      <div class="table-wrap list-table" v-if="collectionListRows.length">
        <table>
          <thead>
            <tr>
              <th class="col-product">商品</th>
              <th>来源链接</th>
              <th>站点</th>
              <th>状态</th>
              <th>成功 / 总计</th>
              <th>完成时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in collectionListRows" :key="row.task.id">
              <td>
                <div class="list-product-cell">
                  <div class="list-thumb" :class="{ placeholder: !row.image }">
                    <img v-if="row.image" :src="row.image" :alt="row.title" />
                    <span v-else>暂无图片</span>
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
      <p v-else class="empty-state">暂无采集任务。</p>
    </template>

    <template v-else-if="intakeTab === 'families' && !selectedFamily">
      <div class="toolbar toolbar-compact">
        <label class="toolbar-field grow">
          <span>搜索商品族</span>
          <input v-model="filters.familyQuery" type="text" placeholder="标题 / 品牌 / 商品族键" />
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
              <th>来源链接</th>
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
                    <img v-if="getFamilyImage(family)" :src="getFamilyImage(family)" :alt="family.title || '商品族'" />
                    <span v-else>暂无图片</span>
                  </div>
                  <div class="list-product-copy">
                    <strong class="list-title">{{ family.title || "未命名商品族" }}</strong>
                    <span class="list-subtitle">{{ family.brand || "品牌待定" }} · {{ familyLeadPrice(family) }}</span>
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
                <span v-else>-</span>
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
                    打开
                  </button>
                  <button
                    type="button"
                    class="inline-button"
                    :disabled="Boolean(family.selection_id)"
                    @click="addToSelection(family.id)"
                  >
                    {{ family.selection_id ? "已加入" : "加入选品" }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty-state">没有匹配的商品族。</p>
    </template>

    <div v-else-if="intakeTab === 'families'" class="detail-panel">
      <button type="button" class="secondary-button back-button" @click="closeFamilyDetail">返回列表</button>

      <div class="detail-hero">
        <div class="list-thumb detail-thumb" :class="{ placeholder: !getFamilyImage(selectedFamily) }">
          <img v-if="getFamilyImage(selectedFamily)" :src="getFamilyImage(selectedFamily)" :alt="selectedFamily.title || '商品族'" />
          <span v-else>暂无图片</span>
        </div>
        <div class="detail-hero-copy">
          <h4>{{ selectedFamily.title || "未命名商品族" }}</h4>
          <div class="meta-line compact">
            <span>{{ selectedFamily.brand || "品牌待定" }}</span>
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
              打开来源
            </a>
            <button
              type="button"
              class="inline-button"
              :disabled="Boolean(selectedFamily.selection_id)"
              @click="addToSelection(selectedFamily.id)"
            >
              {{ selectedFamily.selection_id ? "已加入选品" : "加入选品" }}
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
          <h5>变体</h5>
          <span>{{ selectedFamily.variant_count }} 条记录</span>
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
                <img v-if="getVariantImage(variant)" :src="getVariantImage(variant)" :alt="getVariantTitle(variant, selectedFamily)" />
                <span v-else class="variant-card-placeholder">暂无图片</span>
              </div>

              <div class="variant-card-body">
                <div class="variant-card-line">
                  <h6 class="variant-card-title">{{ getVariantTitle(variant, selectedFamily) }}</h6>
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

              <div v-if="getVariantBulletPoints(variant, selectedFamily).length" class="variant-detail-section">
                <strong>五点描述</strong>
                <ul class="variant-bullet-list">
                  <li v-for="bullet in getVariantBulletPoints(variant, selectedFamily)" :key="bullet">
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

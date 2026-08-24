<script setup lang="ts">
import { toRef } from "vue";
import type {
  DraftEditorState,
  DraftStats,
  ListingDraft,
  ProductMaster,
  ValidationItem,
  WorkflowFilters,
  WorkflowUiState,
} from "../types/workflow";
import type { WorkflowActions, WorkflowHelpers } from "../types/view-context";

const props = defineProps<{
  ui: WorkflowUiState;
  filters: WorkflowFilters;
  filteredListingProducts: ProductMaster[];
  selectedDraft: ListingDraft | null;
  draftEditor: DraftEditorState;
  draftStats: DraftStats;
  draftPreviewBullets: string[];
  draftValidationItems: ValidationItem[];
  helpers: WorkflowHelpers;
  actions: Pick<
    WorkflowActions,
    "createDraft" | "openListingForProduct" | "openDraftEditor" | "saveDraft" | "publishDraft" | "saveDraftVariant"
  >;
}>();

const defaultShopName = toRef(props.ui, "defaultShopName");
const defaultMarketplace = toRef(props.ui, "defaultMarketplace");
const selectedDraftId = toRef(props.ui, "selectedDraftId");
const filters = props.filters;
const selectedDraft = toRef(props, "selectedDraft");
const filteredListingProducts = toRef(props, "filteredListingProducts");
const draftEditor = props.draftEditor;
const draftStats = toRef(props, "draftStats");
const draftPreviewBullets = toRef(props, "draftPreviewBullets");
const draftValidationItems = toRef(props, "draftValidationItems");

const { variantPreview, getStatusLabel, getMarketplaceLabel, getDraftsForProduct } = props.helpers;
const { createDraft, openListingForProduct, openDraftEditor, saveDraft, publishDraft, saveDraftVariant } = props.actions;

function validationLevelLabel(level: string): string {
  switch (level) {
    case "pass":
      return "通过";
    case "warn":
      return "警告";
    case "fail":
      return "未通过";
    default:
      return level;
  }
}
</script>

<template>
  <section class="panel-shell">
    <div class="panel-header">
      <div>
        <p class="eyebrow">草稿</p>
        <h3>上架草稿</h3>
      </div>
      <p>编辑文案、价格与库存</p>
    </div>

    <div class="action-bar action-bar-muted">
      <label class="action-bar-field">
        <span>店铺名称</span>
        <input v-model="defaultShopName" type="text" />
      </label>
      <label class="action-bar-field">
        <span>站点</span>
        <input v-model="defaultMarketplace" type="text" />
      </label>
    </div>

    <div class="toolbar toolbar-compact">
      <label class="toolbar-field grow">
        <span>搜索 SPU 或草稿</span>
        <input
          v-model="filters.listingQuery"
          type="text"
          placeholder="SPU / 商品 / 店铺 / 站点 / 标题"
        />
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
            <th>草稿数</th>
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
                  <img v-if="product.family_main_image_url" :src="product.family_main_image_url" :alt="product.product_name" />
                  <span v-else>暂无图片</span>
                </div>
                <div class="list-product-copy">
                  <strong class="list-title">{{ product.product_name }}</strong>
                  <span class="list-subtitle">{{ product.brand || "品牌待定" }}</span>
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
                打开草稿
              </button>
              <button v-else type="button" class="inline-button" @click="createDraft(product.id)">
                创建草稿
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="empty-state">暂无 SPU，请先在选品中创建。</p>

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
            <span>状态</span>
            <strong>{{ getStatusLabel(draftEditor.status) }}</strong>
          </div>
          <div class="summary-metrics">
            <article>
              <span>SKU 总数</span>
              <strong>{{ draftStats.totalSkuCount }}</strong>
            </article>
            <article>
              <span>已定价</span>
              <strong>{{ draftStats.pricedSkuCount }}</strong>
            </article>
            <article>
              <span>有库存</span>
              <strong>{{ draftStats.stockedSkuCount }}</strong>
            </article>
          </div>
        </div>
      </div>

      <div class="draft-workspace">
        <div class="editor-card">
          <div class="subpanel-head">
            <h4>草稿文案</h4>
            <span>保存会生成新版本</span>
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
                <option value="reviewing">审核中</option>
                <option value="ready">待发布</option>
              </select>
            </label>
            <label class="full-span">
              <span>五点描述</span>
              <textarea v-model="draftEditor.bulletText" rows="6" />
            </label>
            <label class="full-span">
              <span>商品描述</span>
              <textarea v-model="draftEditor.description" rows="5" />
            </label>
            <label class="full-span">
              <span>搜索词</span>
              <textarea v-model="draftEditor.searchTerms" rows="3" />
            </label>
          </div>
        </div>

        <div class="draft-side-stack">
          <article class="editor-card">
            <div class="subpanel-head">
              <h4>校验</h4>
              <span>{{ draftValidationItems.length }} 项检查</span>
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
                  <span>{{ validationLevelLabel(item.level) }}</span>
                </div>
                <p>{{ item.detail }}</p>
              </article>
            </div>
          </article>

          <article class="editor-card">
            <div class="subpanel-head">
              <h4>预览</h4>
              <span>草稿快照</span>
            </div>
            <div class="preview-card">
              <p class="preview-shop">{{ defaultShopName }} · {{ getMarketplaceLabel(selectedDraft.marketplace) }}</p>
              <h5>{{ draftEditor.title || "标题预览" }}</h5>
              <div class="preview-meta">
                <span>{{ draftStats.totalSkuCount }} 个 SKU</span>
                <span>{{ draftStats.pricedSkuCount }} 已定价</span>
                <span>{{ draftStats.stockedSkuCount }} 有库存</span>
              </div>
              <ul class="preview-bullets">
                <li v-for="bullet in draftPreviewBullets.slice(0, 5)" :key="bullet">{{ bullet }}</li>
              </ul>
              <p class="preview-description">
                {{ draftEditor.description || "商品描述预览将显示在这里。" }}
              </p>
            </div>
          </article>
        </div>
      </div>

      <div class="editor-card">
        <div class="subpanel-head">
          <h4>SKU 参数</h4>
          <span>{{ selectedDraft.variants.length }} 条记录</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>卖家 SKU</th>
                <th>变体</th>
                <th>价格</th>
                <th>库存</th>
                <th>履约方式</th>
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
</template>

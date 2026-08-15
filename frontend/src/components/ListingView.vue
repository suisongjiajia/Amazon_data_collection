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
</script>

<template>
  <section class="panel-shell">
    <div class="panel-header">
      <div>
        <p class="eyebrow">Listing</p>
        <h3>SPU and Draft Workspace</h3>
      </div>
      <p>Create listing drafts from SPUs, edit copy, then complete SKU-level pricing and inventory.</p>
    </div>

    <div class="action-bar action-bar-muted">
      <label class="action-bar-field">
        <span>Shop Name</span>
        <input v-model="defaultShopName" type="text" />
      </label>
      <label class="action-bar-field">
        <span>Marketplace</span>
        <input v-model="defaultMarketplace" type="text" />
      </label>
    </div>

    <div class="toolbar toolbar-compact">
      <label class="toolbar-field grow">
        <span>Search SPUs or Drafts</span>
        <input
          v-model="filters.listingQuery"
          type="text"
          placeholder="SPU / product / shop / marketplace / title"
        />
      </label>
    </div>

    <div class="table-wrap list-table" v-if="filteredListingProducts.length">
      <table>
        <thead>
          <tr>
            <th class="col-product">Product</th>
            <th>SPU</th>
            <th>Marketplace</th>
            <th>Status</th>
            <th>SKUs</th>
            <th>Drafts</th>
            <th>Action</th>
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
                  <span v-else>No image</span>
                </div>
                <div class="list-product-copy">
                  <strong class="list-title">{{ product.product_name }}</strong>
                  <span class="list-subtitle">{{ product.brand || "Brand pending" }}</span>
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
                Open Draft
              </button>
              <button v-else type="button" class="inline-button" @click="createDraft(product.id)">
                Create Draft
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="empty-state">No SPUs yet. Create one from the selection pool first.</p>

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
              {{ selectedDraft.variants.length }} SKUs
            </p>
          </div>
          <div class="editor-actions">
            <button type="button" class="secondary-button" @click="saveDraft">Save Draft</button>
            <button type="button" @click="publishDraft(selectedDraft.id)">Simulate Publish</button>
          </div>
        </div>

        <div class="draft-summary-card">
          <div class="summary-row">
            <span>Status</span>
            <strong>{{ getStatusLabel(draftEditor.status) }}</strong>
          </div>
          <div class="summary-metrics">
            <article>
              <span>Total SKUs</span>
              <strong>{{ draftStats.totalSkuCount }}</strong>
            </article>
            <article>
              <span>Priced</span>
              <strong>{{ draftStats.pricedSkuCount }}</strong>
            </article>
            <article>
              <span>In Stock</span>
              <strong>{{ draftStats.stockedSkuCount }}</strong>
            </article>
          </div>
        </div>
      </div>

      <div class="draft-workspace">
        <div class="editor-card">
          <div class="subpanel-head">
            <h4>Draft Copy</h4>
            <span>Saving creates a new version</span>
          </div>
          <div class="editor-grid">
            <label>
              <span>Title</span>
              <input v-model="draftEditor.title" type="text" />
            </label>
            <label>
              <span>Status</span>
              <select v-model="draftEditor.status">
                <option value="draft">Draft</option>
                <option value="reviewing">Reviewing</option>
                <option value="ready">Ready</option>
              </select>
            </label>
            <label class="full-span">
              <span>Bullet Points</span>
              <textarea v-model="draftEditor.bulletText" rows="6" />
            </label>
            <label class="full-span">
              <span>Description</span>
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
              <h4>Validation</h4>
              <span>{{ draftValidationItems.length }} checks</span>
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
                  <span>{{ item.level }}</span>
                </div>
                <p>{{ item.detail }}</p>
              </article>
            </div>
          </article>

          <article class="editor-card">
            <div class="subpanel-head">
              <h4>Preview</h4>
              <span>Draft snapshot</span>
            </div>
            <div class="preview-card">
              <p class="preview-shop">{{ defaultShopName }} · {{ getMarketplaceLabel(selectedDraft.marketplace) }}</p>
              <h5>{{ draftEditor.title || "Draft title preview" }}</h5>
              <div class="preview-meta">
                <span>{{ draftStats.totalSkuCount }} SKUs</span>
                <span>{{ draftStats.pricedSkuCount }} priced</span>
                <span>{{ draftStats.stockedSkuCount }} stocked</span>
              </div>
              <ul class="preview-bullets">
                <li v-for="bullet in draftPreviewBullets.slice(0, 5)" :key="bullet">{{ bullet }}</li>
              </ul>
              <p class="preview-description">
                {{ draftEditor.description || "Description preview appears here." }}
              </p>
            </div>
          </article>
        </div>
      </div>

      <div class="editor-card">
        <div class="subpanel-head">
          <h4>SKU Parameters</h4>
          <span>{{ selectedDraft.variants.length }} records</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Seller SKU</th>
                <th>Variant</th>
                <th>Price</th>
                <th>Quantity</th>
                <th>Fulfillment</th>
                <th>External ID</th>
                <th>Save</th>
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
                  <button type="button" class="inline-button" @click="saveDraftVariant(variant)">Save</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

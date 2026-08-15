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
        <p class="eyebrow">Selections</p>
        <h3>{{ selectedSelection ? "Selection Detail" : "Selection Pool" }}</h3>
      </div>
      <p>
        {{ selectedSelection ? "Refine variant scope, then generate SPUs and SKUs." : "Review selected families and open detail to control variant scope." }}
      </p>
    </div>

    <template v-if="!selectedSelection">
      <div class="toolbar toolbar-compact">
        <label class="toolbar-field grow">
          <span>Search Selections</span>
          <input v-model="filters.selectionQuery" type="text" placeholder="title / brand / family key" />
        </label>
      </div>

      <div class="table-wrap list-table" v-if="filteredSelections.length">
        <table>
          <thead>
            <tr>
              <th class="col-product">Product</th>
              <th>Source URL</th>
              <th>Marketplace</th>
              <th>Status</th>
              <th>Variant Scope</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="selection in filteredSelections" :key="selection.id">
              <td>
                <div class="list-product-cell">
                  <div class="list-thumb" :class="{ placeholder: !getFamilyImage(selection) }">
                    <img v-if="getFamilyImage(selection)" :src="getFamilyImage(selection)" :alt="selection.family_title || 'selection'" />
                    <span v-else>No image</span>
                  </div>
                  <div class="list-product-copy">
                    <strong class="list-title">{{ selection.family_title || "Unnamed family" }}</strong>
                    <span class="list-subtitle">
                      {{ selection.family_brand || "Brand pending" }} · {{ selectionLeadPrice(selection) }}
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
                    Open
                  </button>
                  <button
                    type="button"
                    class="inline-button"
                    :disabled="selection.selection_status === 'converted'"
                    @click="createProduct(selection.id)"
                  >
                    {{ selection.selection_status === "converted" ? "Converted" : "Create SPU" }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty-state">Selection pool is empty. Add families from Intake first.</p>
    </template>

    <div v-else class="detail-panel">
      <button type="button" class="secondary-button back-button" @click="closeSelectionDetail">Back to List</button>

      <div class="detail-hero">
        <div class="list-thumb detail-thumb" :class="{ placeholder: !getFamilyImage(selectedSelection) }">
          <img v-if="getFamilyImage(selectedSelection)" :src="getFamilyImage(selectedSelection)" :alt="selectedSelection.family_title || 'selection'" />
          <span v-else>No image</span>
        </div>
        <div class="detail-hero-copy">
          <h4>{{ selectedSelection.family_title || "Unnamed family" }}</h4>
          <div class="meta-line compact">
            <span>{{ selectedSelection.family_brand || "Brand pending" }}</span>
            <span>{{ getMarketplaceLabel(selectedSelection.family_marketplace) }}</span>
            <span>{{ selectionLeadPrice(selectedSelection) }}</span>
            <span>{{ selectionCoverage(selectedSelection) }}</span>
          </div>
          <div class="card-actions">
            <span class="status-pill" :data-status="selectedSelection.selection_status">
              {{ getStatusLabel(selectedSelection.selection_status) }}
            </span>
            <button type="button" class="inline-button" @click="saveSelectionScope(selectedSelection.id)">
              Save Scope
            </button>
            <button
              type="button"
              class="inline-button"
              :disabled="selectedSelection.selection_status === 'converted'"
              @click="createProduct(selectedSelection.id)"
            >
              {{ selectedSelection.selection_status === "converted" ? "Converted" : "Create SPU + SKU" }}
            </button>
          </div>
        </div>
      </div>

      <div class="detail-block">
        <div class="subpanel-head">
          <h5>Variant Scope</h5>
          <span>Select the variants that should be included in the product build.</span>
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
                <span v-else class="variant-card-placeholder">No image</span>
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
                    {{ isVariantExpanded(variant.id) ? "Collapse" : "Detail" }}
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
                  <span>Parent ASIN</span>
                  <strong>{{ variant.parent_asin }}</strong>
                </div>
                <div v-if="variant.snapshot_time" class="variant-meta-item">
                  <span>Captured At</span>
                  <strong>{{ formatDate(variant.snapshot_time) }}</strong>
                </div>
                <div v-if="variant.source_url" class="variant-meta-item variant-meta-item-wide">
                  <span>Source URL</span>
                  <a class="text-link" :href="variant.source_url" target="_blank" rel="noreferrer">
                    {{ truncateUrl(variant.source_url, 80) }}
                  </a>
                </div>
              </div>

              <div
                v-if="selectedSelectionFamily && getVariantBulletPoints(variant, selectedSelectionFamily).length"
                class="variant-detail-section"
              >
                <strong>Bullet Points</strong>
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

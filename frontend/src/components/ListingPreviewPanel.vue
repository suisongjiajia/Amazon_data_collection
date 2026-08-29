<script setup lang="ts">
import type { ListingPreview, ListingSummary } from "../types/ozon-workflow";

const props = withDefaults(
  defineProps<{
    preview?: ListingPreview | null;
    summary?: ListingSummary | null;
    title?: string;
    showPayload?: boolean;
  }>(),
  {
    preview: null,
    summary: null,
    title: "Listing 预览",
    showPayload: false,
  },
);

const resolvedSummary = () =>
  props.summary || props.preview?.summary || props.preview?.saved_listing?.summary || null;

const issues = () => props.preview?.issues || props.preview?.saved_listing?.issues || [];
const payloadItems = () => props.preview?.payload_items || props.preview?.saved_listing?.payload_items || [];
</script>

<template>
  <div class="listing-preview">
    <div class="listing-preview__header">
      <strong>{{ title }}</strong>
      <span v-if="preview" class="erp-badge" :data-tone="preview.ok ? 'success' : 'danger'">
        {{ preview.ok ? "校验通过" : "校验未通过" }}
      </span>
    </div>

    <div v-if="issues().length" class="listing-preview__issues">
      <div
        v-for="issue in issues()"
        :key="`${issue.code}-${issue.message}`"
        class="listing-preview__issue"
        :data-severity="issue.severity"
      >
        [{{ issue.severity }}] {{ issue.message }}
      </div>
    </div>

    <template v-if="resolvedSummary()">
      <div class="erp-detail-grid">
        <div class="erp-detail-item">
          <span>标题</span>
          <strong>{{ resolvedSummary()!.title || "-" }}</strong>
        </div>
        <div class="erp-detail-item">
          <span>类目 ID</span>
          <strong>{{ resolvedSummary()!.description_category_id || "-" }}</strong>
        </div>
        <div class="erp-detail-item">
          <span>type_id</span>
          <strong>{{ resolvedSummary()!.type_id || "-" }}</strong>
        </div>
        <div class="erp-detail-item">
          <span>履约</span>
          <strong>{{ resolvedSummary()!.fulfillment || "rFBS" }}</strong>
        </div>
        <div class="erp-detail-item">
          <span>品牌模式</span>
          <strong>{{ resolvedSummary()!.brand_mode || "no_brand" }}</strong>
        </div>
        <div class="erp-detail-item">
          <span>图片数</span>
          <strong>{{ resolvedSummary()!.images?.length ?? 0 }}</strong>
        </div>
      </div>

      <div class="listing-preview__block">
        <span class="listing-preview__label">描述</span>
        <pre class="listing-preview__text">{{ resolvedSummary()!.description || "（空）" }}</pre>
      </div>

      <div v-if="resolvedSummary()!.bullet_points?.length" class="listing-preview__block">
        <span class="listing-preview__label">卖点</span>
        <ul class="listing-preview__list">
          <li v-for="(point, index) in resolvedSummary()!.bullet_points" :key="index">{{ point }}</li>
        </ul>
      </div>

      <div v-if="resolvedSummary()!.images?.length" class="listing-preview__images">
        <img
          v-for="(url, index) in resolvedSummary()!.images!.slice(0, 8)"
          :key="`${url}-${index}`"
          :src="url"
          :alt="`listing-${index}`"
        />
      </div>

      <div class="erp-table-wrap" style="margin-top: 12px">
        <table class="erp-table">
          <thead>
            <tr>
              <th>SKU</th>
              <th>标题</th>
              <th>价格</th>
              <th>库存</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(variant, index) in resolvedSummary()!.variants || []" :key="variant.sku || index">
              <td>{{ variant.sku || "-" }}</td>
              <td>{{ variant.title || "-" }}</td>
              <td>{{ variant.price ?? "-" }}</td>
              <td>{{ variant.quantity ?? "-" }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="showPayload && payloadItems().length" class="listing-preview__block">
        <span class="listing-preview__label">将提交的 Payload（摘要）</span>
        <pre class="listing-preview__text">{{ JSON.stringify(payloadItems(), null, 2) }}</pre>
      </div>
    </template>
  </div>
</template>

<style scoped>
.listing-preview__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.listing-preview__issues {
  display: grid;
  gap: 6px;
  margin-bottom: 12px;
}

.listing-preview__issue {
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13px;
  background: rgba(180, 83, 9, 0.08);
  color: #92400e;
}

.listing-preview__issue[data-severity="error"] {
  background: rgba(185, 28, 28, 0.08);
  color: #991b1b;
}

.listing-preview__block {
  margin-top: 12px;
}

.listing-preview__label {
  display: block;
  margin-bottom: 6px;
  color: #64748b;
  font-size: 12px;
}

.listing-preview__text {
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.04);
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.5;
  max-height: 280px;
  overflow: auto;
}

.listing-preview__list {
  margin: 0;
  padding-left: 18px;
}

.listing-preview__images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.listing-preview__images img {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.08);
}
</style>

<script setup lang="ts">
import { computed, ref } from "vue";

import { apiRequest } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";
import { getModuleDefinition } from "../config/modules";
import type { AiProductEditResponse, OzonProductFamily, ProductEdit } from "../types/ozon-workflow";
import ErpBadge from "./erp/ErpBadge.vue";
import ErpButton from "./erp/ErpButton.vue";
import ErpCard from "./erp/ErpCard.vue";
import ErpEmpty from "./erp/ErpEmpty.vue";
import ErpPageHeader from "./erp/ErpPageHeader.vue";
import ErpProductCell from "./erp/ErpProductCell.vue";
import ErpStatGrid from "./erp/ErpStatGrid.vue";

interface EditDraftVariant {
  id: number | null;
  sku: string;
  title: string;
  price: number | null;
  quantity: number;
}

interface EditDraft {
  editId: number | null;
  rawProductFamilyId: number;
  status: string | null;
  title: string;
  description: string;
  bullet_points: string[];
  images: string[];
  attributes: Record<string, string>;
  listing_notes: string;
  variants: EditDraftVariant[];
}

const store = useAppStore();
const module = getModuleDefinition("product-edit");
const selectedFamilyId = ref<number | null>(null);
const draft = ref<EditDraft | null>(null);
const saving = ref(false);
const aiGenerating = ref(false);

const editByFamily = computed(() => {
  const map = new Map<number, ProductEdit>();
  for (const edit of store.state.value.edits) {
    map.set(edit.raw_product_family_id, edit);
  }
  return map;
});

const currentProduct = computed(() => {
  if (selectedFamilyId.value == null) return null;
  return store.state.value.ozonProducts.find((item) => item.id === selectedFamilyId.value) ?? null;
});

const bulletPointsText = computed({
  get: () => (draft.value?.bullet_points ?? []).join("\n"),
  set: (value: string) => {
    if (!draft.value) return;
    draft.value.bullet_points = value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  },
});

const imagesText = computed({
  get: () => (draft.value?.images ?? []).join("\n"),
  set: (value: string) => {
    if (!draft.value) return;
    draft.value.images = value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  },
});

const attributeEntries = computed(() => {
  if (!draft.value) return [];
  return Object.entries(draft.value.attributes);
});

const isUnsavedDraft = computed(() => draft.value != null && draft.value.editId == null);

function productPrice(item: OzonProductFamily): string {
  return item.price_text || item.variants?.[0]?.price_text || "-";
}

function parsePrice(text?: string | null): number | null {
  if (!text) return null;
  const normalized = text.replace(/[^\d.,]/g, "").replace(",", ".");
  const value = Number.parseFloat(normalized);
  return Number.isFinite(value) ? value : null;
}

function editForFamily(familyId: number): ProductEdit | undefined {
  return editByFamily.value.get(familyId);
}

function hasPersistedEdit(familyId: number): boolean {
  return editByFamily.value.has(familyId);
}

function canCancelEdit(status: string | null): boolean {
  return status == null || status === "draft" || status === "editing" || status === "rejected";
}

function canSubmitReview(draftValue: EditDraft): boolean {
  if (!draftValue.editId) return false;
  const status = draftValue.status ?? "draft";
  return status === "draft" || status === "editing" || status === "rejected";
}

function buildDraftFromProduct(product: OzonProductFamily): EditDraft {
  const defaultTitle = product.title || "未命名商品";
  const variants =
    product.variants.length > 0
      ? product.variants.map((variant) => ({
          id: null,
          sku: `OZON-${product.external_id || variant.id}`,
          title: variant.title || defaultTitle,
          price: parsePrice(variant.price_text),
          quantity: 0,
        }))
      : [
          {
            id: null,
            sku: `OZON-${product.external_id || product.id}`,
            title: defaultTitle,
            price: parsePrice(product.price_text || product.variants?.[0]?.price_text),
            quantity: 0,
          },
        ];

  const images = product.main_image_url ? [product.main_image_url] : [];

  return {
    editId: null,
    rawProductFamilyId: product.id,
    status: null,
    title: defaultTitle,
    description: "",
    bullet_points: [],
    images,
    attributes: {},
    listing_notes: "",
    variants,
  };
}

function buildDraftFromEdit(edit: ProductEdit): EditDraft {
  return {
    editId: edit.id,
    rawProductFamilyId: edit.raw_product_family_id,
    status: edit.status,
    title: edit.title,
    description: edit.description || "",
    bullet_points: edit.bullet_points || [],
    images: edit.images || [],
    attributes: edit.attributes || {},
    listing_notes: "",
    variants: edit.variants.map((variant) => ({
      id: variant.id,
      sku: variant.sku,
      title: variant.title || edit.title,
      price: variant.price,
      quantity: variant.quantity,
    })),
  };
}

function applyAiSuggestion(response: AiProductEditResponse): void {
  const current = draft.value;
  if (!current) return;
  const suggestion = response.suggestion;
  current.title = suggestion.title || current.title;
  current.description = suggestion.description || current.description;
  current.bullet_points = suggestion.bullet_points || [];
  current.images = suggestion.images?.length ? suggestion.images : current.images;
  current.attributes = suggestion.attributes || {};
  current.listing_notes = suggestion.listing_notes || "";

  if (suggestion.variants?.length) {
    current.variants = suggestion.variants.map((variant, index) => {
      const existing = current.variants[index];
      return {
        id: existing?.id ?? null,
        sku: variant.sku || existing?.sku || `OZON-${current.rawProductFamilyId}`,
        title: variant.title || current.title,
        price: variant.price ?? existing?.price ?? null,
        quantity: variant.quantity ?? existing?.quantity ?? 0,
      };
    });
  }
}

async function generateWithAi(): Promise<void> {
  const current = draft.value;
  if (!current) return;
  aiGenerating.value = true;
  try {
    const response = await apiRequest<AiProductEditResponse>("/api/product-edits/ai-generate", {
      method: "POST",
      body: JSON.stringify({ raw_product_family_id: current.rawProductFamilyId }),
    });
    applyAiSuggestion(response);
    store.showNotice("AI 已生成上架内容，请检查后保存");
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    aiGenerating.value = false;
  }
}

function openEdit(familyId: number): void {
  const product = store.state.value.ozonProducts.find((item) => item.id === familyId);
  if (!product) return;
  selectedFamilyId.value = familyId;
  const existing = editForFamily(familyId);
  draft.value = existing ? buildDraftFromEdit(existing) : buildDraftFromProduct(product);
}

function closeEdit(): void {
  selectedFamilyId.value = null;
  draft.value = null;
}

async function cancelEdit(): Promise<void> {
  const current = draft.value;
  if (!current) {
    closeEdit();
    return;
  }

  if (current.editId && canCancelEdit(current.status)) {
    try {
      await apiRequest(`/api/product-edits/${current.editId}`, { method: "DELETE" });
      store.showNotice("已取消编辑");
      await store.refreshAll();
    } catch (err) {
      store.showError(err instanceof Error ? err.message : String(err));
      return;
    }
  }

  closeEdit();
}

async function cancelEditFromList(familyId: number): Promise<void> {
  const edit = editForFamily(familyId);
  if (!edit || !canCancelEdit(edit.status)) return;
  try {
    await apiRequest(`/api/product-edits/${edit.id}`, { method: "DELETE" });
    store.showNotice("已取消编辑");
    if (selectedFamilyId.value === familyId) {
      closeEdit();
    }
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  }
}

async function saveEdit(): Promise<void> {
  const current = draft.value;
  if (!current) return;

  saving.value = true;
  try {
    let editId = current.editId;
    if (!editId) {
      const created = await apiRequest<ProductEdit>(
        `/api/product-edits?raw_product_family_id=${current.rawProductFamilyId}`,
        { method: "POST" },
      );
      editId = created.id;
      current.editId = editId;
      current.status = created.status;
      for (const variant of current.variants) {
        const matched = created.variants.find((item) => item.sku === variant.sku);
        if (matched) variant.id = matched.id;
      }
    }

    await apiRequest(`/api/product-edits/${editId}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: current.title,
        description: current.description,
        bullet_points: current.bullet_points,
        images: current.images,
        attributes: current.attributes,
      }),
    });

    for (const variant of current.variants) {
      if (variant.id == null) continue;
      await apiRequest(`/api/product-edit-variants/${variant.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: variant.title,
          price: variant.price,
          quantity: variant.quantity,
        }),
      });
    }

    store.showNotice("已保存到数据库");
    await store.refreshAll();
    const fresh = editForFamily(current.rawProductFamilyId);
    if (fresh) {
      draft.value = buildDraftFromEdit(fresh);
    }
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    saving.value = false;
  }
}

async function submitReview(): Promise<void> {
  const current = draft.value;
  if (!current?.editId) {
    store.showError("请先保存编辑内容后再提交审核");
    return;
  }
  try {
    await apiRequest(`/api/product-edits/${current.editId}/submit-review`, { method: "POST" });
    store.showNotice("已提交审核");
    await store.refreshAll();
    const fresh = editForFamily(current.rawProductFamilyId);
    if (fresh) draft.value = buildDraftFromEdit(fresh);
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  }
}
</script>

<template>
  <div class="erp-stack">
    <ErpPageHeader
      :title="selectedFamilyId ? '商品编辑详情' : module.label"
      :description="
        selectedFamilyId
          ? isUnsavedDraft
            ? '当前为本地草稿，点击保存后才会写入数据库'
            : '编辑该 Ozon 商品；可用 AI 生成俄语上架内容，保存后提交审核'
          : module.description
      "
    >
      <template v-if="selectedFamilyId" #actions>
        <ErpButton variant="ghost" size="sm" @click="closeEdit">返回列表</ErpButton>
        <ErpButton
          v-if="draft && canCancelEdit(draft.status)"
          variant="danger"
          size="sm"
          @click="cancelEdit"
        >
          取消编辑
        </ErpButton>
      </template>
    </ErpPageHeader>

    <template v-if="!selectedFamilyId">
      <ErpStatGrid
        :items="[
          { label: '可编辑商品', value: store.state.value.ozonProducts.length },
          { label: '已保存编辑', value: store.state.value.edits.length },
          { label: '待审核', value: store.stats.value.pendingReview },
          { label: '已通过', value: store.stats.value.approved },
        ]"
      />

      <ErpCard title="商品编辑" :description="`${store.state.value.ozonProducts.length} 条`" padding="none">
        <div v-if="store.state.value.ozonProducts.length" class="erp-table-wrap">
          <table class="erp-table">
            <thead>
              <tr>
                <th>商品</th>
                <th>价格</th>
                <th>编辑状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in store.state.value.ozonProducts" :key="item.id">
                <td>
                  <ErpProductCell
                    :image-url="item.main_image_url"
                    :title="item.title"
                    :subtitle="`SKU ${item.external_id || '-'}`"
                  />
                </td>
                <td>{{ productPrice(item) }}</td>
                <td>
                  <ErpBadge v-if="editForFamily(item.id)" :status="editForFamily(item.id)!.status" />
                  <span v-else class="erp-text-muted">未编辑</span>
                </td>
                <td>
                  <div class="erp-table-actions">
                    <ErpButton variant="secondary" size="sm" @click="openEdit(item.id)">
                      {{ hasPersistedEdit(item.id) ? "进入编辑" : "开始编辑" }}
                    </ErpButton>
                    <ErpButton
                      v-if="editForFamily(item.id) && canCancelEdit(editForFamily(item.id)!.status)"
                      variant="ghost"
                      size="sm"
                      @click="cancelEditFromList(item.id)"
                    >
                      取消编辑
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

    <template v-else-if="currentProduct && draft">
      <ErpCard padding="none">
        <div class="erp-card__body">
          <div class="erp-detail-hero">
            <ErpProductCell
              size="lg"
              :image-url="currentProduct.main_image_url"
              :title="currentProduct.title"
              :subtitle="currentProduct.brand || `SKU ${currentProduct.external_id || '-'}`"
            />
            <div class="erp-detail-hero__copy">
              <div class="erp-detail-hero__meta">
                <span>{{ productPrice(currentProduct) }}</span>
                <span>类目 {{ currentProduct.category_name || "-" }}</span>
                <span>排名 {{ currentProduct.sales_rank ?? "-" }}</span>
              </div>
              <ErpBadge v-if="draft.editId" :status="draft.status || 'draft'" />
              <span v-else class="erp-badge" data-tone="warning">未保存</span>
            </div>
          </div>
        </div>
      </ErpCard>

      <ErpCard title="编辑内容" description="AI 生成后请检查并保存，才会写入数据库">
        <div class="erp-editor-actions" style="margin-bottom: 14px">
          <ErpButton :disabled="aiGenerating || saving" @click="generateWithAi">
            {{ aiGenerating ? "AI 生成中…" : "AI 一键生成" }}
          </ErpButton>
        </div>
        <div class="erp-editor-grid">
          <label class="erp-field">
            <span>标题（俄语）</span>
            <input v-model="draft.title" type="text" />
          </label>
          <label class="erp-field">
            <span>描述（俄语）</span>
            <textarea v-model="draft.description" rows="6" />
          </label>
          <label class="erp-field">
            <span>卖点（每行一条）</span>
            <textarea v-model="bulletPointsText" rows="5" />
          </label>
          <label class="erp-field">
            <span>图片 URL（每行一条）</span>
            <textarea v-model="imagesText" rows="4" />
          </label>
        </div>

        <div v-if="attributeEntries.length" class="erp-detail-grid" style="margin-top: 14px">
          <div v-for="[key, value] in attributeEntries" :key="key" class="erp-detail-item">
            <span>{{ key }}</span>
            <strong>{{ value }}</strong>
          </div>
        </div>

        <p v-if="draft.listing_notes" class="erp-detail-text" style="margin-top: 14px">
          AI 说明：{{ draft.listing_notes }}
        </p>

        <div class="erp-editor-actions" style="margin-top: 14px">
          <ErpButton variant="secondary" :disabled="saving" @click="saveEdit">
            {{ saving ? "保存中…" : "保存" }}
          </ErpButton>
          <ErpButton v-if="canSubmitReview(draft)" @click="submitReview">提交审核</ErpButton>
        </div>

        <div class="erp-table-wrap" style="margin-top: 16px">
          <table class="erp-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>变体标题</th>
                <th>价格 (₽)</th>
                <th>库存</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(variant, index) in draft.variants" :key="variant.id ?? `${variant.sku}-${index}`">
                <td>{{ variant.sku }}</td>
                <td><input v-model="variant.title" type="text" /></td>
                <td><input v-model.number="variant.price" type="number" min="0" step="1" /></td>
                <td><input v-model.number="variant.quantity" type="number" min="0" /></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="erp-detail-text" style="margin-top: 12px">保存后变体价格与库存会一并提交；真实上架请在发布模块关闭「模拟发布」。</p>
      </ErpCard>
    </template>
  </div>
</template>

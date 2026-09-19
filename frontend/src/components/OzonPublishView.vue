<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { apiRequest } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";
import { getModuleDefinition } from "../config/modules";
import type { ListingPreview, OzonPublishTask, ProductEdit } from "../types/ozon-workflow";
import { resolveEditImage, resolveEditSubtitle, resolvePublishTaskImage, formatMoney, resolveCurrencyCode } from "../utils/product-display";
import ErpBadge from "./erp/ErpBadge.vue";
import ErpButton from "./erp/ErpButton.vue";
import ErpCard from "./erp/ErpCard.vue";
import ErpEmpty from "./erp/ErpEmpty.vue";
import ErpPageHeader from "./erp/ErpPageHeader.vue";
import ErpProductCell from "./erp/ErpProductCell.vue";
import ErpStatGrid from "./erp/ErpStatGrid.vue";
import ListingPreviewPanel from "./ListingPreviewPanel.vue";

const store = useAppStore();
const module = getModuleDefinition("ozon-publish");
const shopName = ref("演示店铺");
const simulatePublish = ref(false);
const selectedTaskId = ref<number | null>(null);
const taskDetail = ref<OzonPublishTask | null>(null);
const selectedEditId = ref<number | null>(null);
const refreshing = ref(false);
const publishingEditId = ref<number | null>(null);
const reopeningEditId = ref<number | null>(null);
const healingEditId = ref<number | null>(null);
const republishingEditId = ref<number | null>(null);

const isPublishingBusy = computed(
  () =>
    publishingEditId.value != null ||
    reopeningEditId.value != null ||
    healingEditId.value != null ||
    republishingEditId.value != null ||
    refreshing.value,
);

const approvedEdits = computed(() =>
  store.state.value.edits.filter((item) => item.status === "approved"),
);

const failedTasks = computed(() =>
  store.state.value.publishTasks.filter((item) => item.status === "failed"),
);

const pendingConfirmTasks = computed(() =>
  store.state.value.publishTasks.filter(
    (item) =>
      item.status === "awaiting_pull" ||
      item.status === "submitted" ||
      item.status === "running" ||
      item.status === "pushed" ||
      item.status === "partial",
  ),
);

const selectedEdit = computed(() =>
  approvedEdits.value.find((item) => item.id === selectedEditId.value) ?? null,
);

watch(
  () => store.state.value.publishTasks,
  (tasks) => {
    if (!tasks.length) {
      selectedTaskId.value = null;
      taskDetail.value = null;
      return;
    }
    if (selectedTaskId.value == null) {
      void openTask(tasks[0].id);
    }
  },
  { immediate: true },
);

function canRefresh(task: OzonPublishTask): boolean {
  return [
    "awaiting_pull",
    "submitted",
    "running",
    "processing",
    "pushed",
    "partial",
    "failed",
    "listed",
    "completed",
  ].includes(task.status);
}

function resultLabel(task: OzonPublishTask): string {
  if (task.status === "awaiting_pull" || task.status === "submitted" || task.status === "running") {
    return `待拉取 · ${task.total_count} SKU`;
  }
  if (task.status === "pushed" || task.status === "partial") {
    return `已推送（待可售）· ${task.total_count} SKU`;
  }
  if (task.status === "listed" || task.status === "completed") {
    return `上架成功 ${task.success_count}/${task.total_count} SKU`;
  }
  if (task.status === "failed") {
    return `推送失败 ${task.fail_count}/${task.total_count}`;
  }
  return `${task.success_count} 成功 / ${task.fail_count} 其它 / ${task.total_count}`;
}

async function publish(editId: number): Promise<void> {
  if (publishingEditId.value != null) return;
  publishingEditId.value = editId;
  store.showNotice(simulatePublish.value ? "正在模拟推送…" : "正在推送到 Ozon…");
  try {
    const task = await apiRequest<OzonPublishTask>("/api/ozon/publish-tasks", {
      method: "POST",
      body: JSON.stringify({
        edit_id: editId,
        shop_name: shopName.value,
        simulate: simulatePublish.value,
        auto_follow: !simulatePublish.value,
      }),
    });
    store.showNotice(
      simulatePublish.value
        ? "模拟任务已推送，状态为「待拉取」，请点击「拉取上架状态」"
        : "已推送到 Ozon。系统将自动拉取状态；若不可售会补库存/修复并重推，直到可售",
    );
    await store.refreshAll();
    await openTask(task.id);
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
    await store.refreshAll();
  } finally {
    publishingEditId.value = null;
  }
}

async function openTask(taskId: number): Promise<void> {
  selectedTaskId.value = taskId;
  try {
    taskDetail.value = await apiRequest<OzonPublishTask>(`/api/ozon/publish-tasks/${taskId}`);
  } catch (err) {
    taskDetail.value = store.state.value.publishTasks.find((item) => item.id === taskId) ?? null;
    store.showError(err instanceof Error ? err.message : String(err));
  }
}

async function refreshStatus(): Promise<void> {
  if (selectedTaskId.value == null || refreshing.value) return;
  refreshing.value = true;
  store.showNotice("正在拉取上架状态…");
  try {
    const task = await apiRequest<OzonPublishTask>(
      `/api/ozon/publish-tasks/${selectedTaskId.value}/refresh-status`,
      { method: "POST" },
    );
    taskDetail.value = task;
    if (task.status === "listed" || task.status === "completed") {
      store.showNotice("拉取完成：上架成功（可售）");
    } else if (task.status === "failed") {
      store.showError(task.error_message || "拉取完成：推送失败，请查看明细");
    } else if (task.status === "pushed" || task.status === "partial") {
      store.showNotice(task.error_message || "已推送：商品在 Ozon 但尚不可售，请检查库存/校验后再次拉取");
    } else if (task.status === "awaiting_pull" || task.status === "submitted") {
      store.showNotice("仍待拉取：Ozon 还在处理，请稍后再拉");
    } else {
      store.showNotice(`当前状态：${task.status}`);
    }
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
    await store.refreshAll();
  } finally {
    refreshing.value = false;
  }
}

function selectApproved(edit: ProductEdit): void {
  selectedEditId.value = edit.id;
}

async function reopenEdit(editId: number): Promise<void> {
  if (reopeningEditId.value != null) return;
  reopeningEditId.value = editId;
  store.showNotice("正在重新打开编辑…");
  try {
    await apiRequest<ProductEdit>(`/api/ozon/publish-tasks/reopen-edit/${editId}`, {
      method: "POST",
    });
    store.showNotice("已重新打开编辑，请修复后重新生成 Listing 并审核");
    store.setModule("product-edit");
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    reopeningEditId.value = null;
  }
}

async function aiHealAndRepublish(editId: number): Promise<void> {
  if (healingEditId.value != null) return;
  healingEditId.value = editId;
  store.showNotice("AI 正在按报错修复尺寸/属性并重推，请稍候…");
  try {
    const result = await apiRequest<{ message?: string; publish_task?: OzonPublishTask }>(
      `/api/ozon/publish-tasks/ai-heal/${editId}`,
      { method: "POST" },
    );
    store.showNotice(result.message || "AI 修复完成并已重新推送");
    if (result.publish_task?.id) {
      selectedTaskId.value = result.publish_task.id;
      taskDetail.value = result.publish_task;
    }
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
    await store.refreshAll();
  } finally {
    healingEditId.value = null;
  }
}

async function republishListed(editId: number): Promise<void> {
  if (republishingEditId.value != null) return;
  republishingEditId.value = editId;
  store.showNotice("正在重新生成 Listing（含完整图库）并推送更新…");
  try {
    const result = await apiRequest<{ message?: string; publish_task?: OzonPublishTask }>(
      `/api/ozon/publish-tasks/republish/${editId}`,
      { method: "POST" },
    );
    store.showNotice(result.message || "已重新推送更新，后台将自动拉取状态");
    if (result.publish_task?.id) {
      selectedTaskId.value = result.publish_task.id;
      taskDetail.value = result.publish_task;
    }
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
    await store.refreshAll();
  } finally {
    republishingEditId.value = null;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function payloadPreview(task: OzonPublishTask): ListingPreview {
  const payloads = task.items
    .map((item) => asRecord(item.submission_payload))
    .filter((item): item is Record<string, unknown> => Boolean(item));
  const first = payloads[0] || {};
  const images: string[] = [];
  const main = resolvePublishTaskImage(task);
  if (main) images.push(main);
  if (Array.isArray(task.edit_images)) {
    for (const url of task.edit_images) {
      if (typeof url === "string" && url && !images.includes(url)) images.push(url);
    }
  }
  const payloadImages = first.images;
  if (Array.isArray(payloadImages)) {
    for (const url of payloadImages) {
      if (typeof url === "string" && url && !images.includes(url)) images.push(url);
    }
  }

  const summary = {
    title: String(first.name || task.edit_title || ""),
    description: String(first.description || ""),
    bullet_points: [] as string[],
    images,
    description_category_id: (first.description_category_id as string | number | null) ?? null,
    type_id: (first.type_id as string | number | null) ?? null,
    fulfillment: "rFBS",
    brand_mode: "no_brand",
    variants: task.items.map((item) => {
      const payload = asRecord(item.submission_payload) || {};
      return {
        sku: item.seller_sku,
        title: String(payload.name || item.seller_sku),
        price:
          payload.price != null && payload.price !== ""
            ? Number(payload.price)
            : null,
        quantity:
          payload.quantity != null && payload.quantity !== ""
            ? Number(payload.quantity)
            : null,
      };
    }),
  };

  const issues = [];
  if (task.error_message) {
    issues.push({
      code: "PUBLISH_ERROR",
      severity: "error" as const,
      message: task.error_message,
    });
  }
  for (const item of task.items) {
    if (item.status !== "failed") continue;
    const detail = [item.error_code, item.error_message].filter(Boolean).join(" · ");
    if (!detail) continue;
    // 任务级已汇总时避免重复刷屏
    if (task.error_message && task.error_message.includes(detail)) continue;
    issues.push({
      code: item.error_code || "ITEM_IMPORT_ERROR",
      severity: "error" as const,
      message: `${item.seller_sku}: ${detail}`,
    });
  }
  const hasSubmission = Boolean(first.description_category_id || first.type_id || first.name || first.price);
  if (hasSubmission && (!first.description_category_id || !first.type_id)) {
    issues.push({
      code: "MISSING_CATEGORY_TYPE",
      severity: "error" as const,
      message: "提交载荷缺少 description_category_id 或 type_id",
    });
  }

  return {
    ok: hasSubmission
      ? Boolean(first.description_category_id && first.type_id) && !task.error_message
      : !task.error_message,
    issues,
    summary,
    payload_items: payloads,
    stock_items: [],
  };
}
</script>

<template>
  <div class="erp-stack">
    <ErpPageHeader :title="module.label" :description="module.description" />

    <ErpStatGrid
      :items="[
        { label: '可发布', value: approvedEdits.length, hint: '已通过审核' },
        { label: '待拉取/已推送', value: pendingConfirmTasks.length, hint: '需拉取确认可售' },
        { label: '推送失败', value: failedTasks.length, hint: '需修复再推' },
      ]"
    />

    <ErpCard title="发布配置">
      <div class="erp-form-row">
        <label class="erp-field">
          <span>店铺名称</span>
          <input v-model="shopName" type="text" />
        </label>
        <label class="erp-field erp-field--inline">
          <span>模拟发布（不调用 Ozon API）</span>
          <input v-model="simulatePublish" type="checkbox" />
        </label>
      </div>
      <p class="erp-detail-text">
        状态说明：推送成功→「待拉取」；拉取后有档案但不可售→「已推送」；确认可售→「上架成功」；推送时报错→「推送失败」。
        拉取时会调用 `/v1/barcode/generate` 生成条码，并尝试推 rFBS 库存。
      </p>
    </ErpCard>

    <div class="publish-top-layout">
      <ErpCard title="可发布 Listing" :description="`${approvedEdits.length} 条 · 点行查看商品`" padding="none">
        <div v-if="approvedEdits.length" class="erp-table-wrap">
          <table class="erp-table">
            <thead>
              <tr>
                <th>商品</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="edit in approvedEdits"
                :key="edit.id"
                class="is-clickable"
                :class="{ 'is-selected': edit.id === selectedEditId }"
                @click="selectApproved(edit)"
              >
                <td>
                  <ErpProductCell
                    :image-url="resolveEditImage(edit)"
                    :title="edit.title"
                    :subtitle="resolveEditSubtitle(edit)"
                  />
                </td>
                <td><ErpBadge :status="edit.status" /></td>
                <td @click.stop>
                  <div class="erp-table-actions">
                    <ErpButton
                      size="sm"
                      :disabled="isPublishingBusy || store.loading.value"
                      @click="publish(edit.id)"
                    >
                      {{ publishingEditId === edit.id ? "推送中…" : "推送到 Ozon" }}
                    </ErpButton>
                    <ErpButton
                      size="sm"
                      variant="ghost"
                      :disabled="isPublishingBusy"
                      @click="reopenEdit(edit.id)"
                    >
                      {{ reopeningEditId === edit.id ? "打开中…" : "回编辑" }}
                    </ErpButton>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <ErpEmpty v-else message="暂无已通过审核的 Listing" />
      </ErpCard>

      <ErpCard title="选中商品详情" description="确认主图与价格后再推送">
        <template v-if="selectedEdit">
          <div class="erp-detail-hero">
            <ErpProductCell
              size="lg"
              :image-url="resolveEditImage(selectedEdit)"
              :title="selectedEdit.title"
              :subtitle="resolveEditSubtitle(selectedEdit)"
            />
            <div class="erp-detail-hero__copy">
              <div class="erp-detail-hero__meta">
                <ErpBadge :status="selectedEdit.status" />
                <span v-if="selectedEdit.family_external_id">Ozon ID {{ selectedEdit.family_external_id }}</span>
                <span v-if="selectedEdit.category_name">{{ selectedEdit.category_name }}</span>
              </div>
              <p v-if="selectedEdit.family_title" class="erp-detail-text">源品：{{ selectedEdit.family_title }}</p>
              <p class="erp-detail-text">{{ selectedEdit.description || "暂无描述" }}</p>
            </div>
          </div>
          <div v-if="selectedEdit.images?.length" class="erp-image-strip" style="margin-top: 12px">
            <img
              v-for="(img, i) in selectedEdit.images"
              :key="`${img}-${i}`"
              :src="img"
              alt="商品图"
            />
          </div>
          <div class="erp-table-wrap" style="margin-top: 12px">
            <table class="erp-table">
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>价格</th>
                  <th>库存</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="variant in selectedEdit.variants" :key="variant.id">
                  <td>{{ variant.sku }}</td>
                  <td>{{ formatMoney(variant.price, resolveCurrencyCode(selectedEdit.attributes)) }}</td>
                  <td>{{ variant.quantity }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <ErpEmpty v-else message="点击左侧可发布商品查看详情" />
      </ErpCard>
    </div>

    <div class="publish-layout">
      <ErpCard title="发布任务" :description="`${store.state.value.publishTasks.length} 条`" padding="none">
        <div v-if="store.state.value.publishTasks.length" class="erp-table-wrap">
          <table class="erp-table">
            <thead>
              <tr>
                <th>商品</th>
                <th>状态</th>
                <th>结果</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="task in store.state.value.publishTasks"
                :key="task.id"
                class="is-clickable"
                :class="{ 'is-selected': task.id === selectedTaskId }"
                @click="openTask(task.id)"
              >
                <td>
                  <ErpProductCell
                    :image-url="resolvePublishTaskImage(task)"
                    :title="task.edit_title || `任务 ${task.task_no}`"
                    :subtitle="`${task.task_no}${task.family_external_id ? ` · ${task.family_external_id}` : ''}`"
                  />
                </td>
                <td><ErpBadge :status="task.status" /></td>
                <td>{{ resultLabel(task) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <ErpEmpty v-else message="暂无发布任务" />
      </ErpCard>

      <ErpCard title="任务详情" description="先看明细状态；点「拉取上架状态」确认 Ozon 是否真正成功">
        <template v-if="taskDetail">
          <div class="erp-detail-hero" style="margin-bottom: 12px">
            <ErpProductCell
              size="lg"
              :image-url="resolvePublishTaskImage(taskDetail)"
              :title="taskDetail.edit_title || taskDetail.task_no"
              :subtitle="taskDetail.family_title || taskDetail.task_no"
            />
            <div class="erp-detail-hero__copy">
              <div class="erp-detail-hero__meta">
                <ErpBadge :status="taskDetail.status" />
                <span>{{ taskDetail.shop_name || "-" }}</span>
                <span v-if="taskDetail.ozon_import_task_id">
                  Ozon 任务 {{ taskDetail.ozon_import_task_id }}
                </span>
                <span v-if="taskDetail.family_external_id">源 SKU {{ taskDetail.family_external_id }}</span>
              </div>
            </div>
          </div>

          <p v-if="taskDetail.error_message" class="listing-error">
            {{ taskDetail.error_message }}
          </p>

          <div class="erp-table-wrap" style="margin-top: 12px">
            <table class="erp-table">
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>上架状态</th>
                  <th>Ozon 商品 ID</th>
                  <th>错误码</th>
                  <th>错误信息</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in taskDetail.items" :key="item.id">
                  <td>{{ item.seller_sku }}</td>
                  <td><ErpBadge :status="item.status" /></td>
                  <td>{{ item.ozon_product_id || "-" }}</td>
                  <td>{{ item.error_code || "-" }}</td>
                  <td>{{ item.error_message || "-" }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="erp-editor-actions" style="margin-top: 12px">
            <ErpButton
              v-if="canRefresh(taskDetail)"
              :disabled="isPublishingBusy"
              @click="refreshStatus"
            >
              {{ refreshing ? "拉取中…" : "拉取上架状态" }}
            </ErpButton>
            <ErpButton
              v-if="taskDetail.status === 'listed' || taskDetail.status === 'completed' || taskDetail.edit_status === 'published' || taskDetail.status === 'running' || taskDetail.status === 'awaiting_pull' || taskDetail.status === 'pushed' || taskDetail.status === 'partial'"
              :disabled="isPublishingBusy"
              @click="republishListed(taskDetail.edit_id)"
            >
              {{ republishingEditId === taskDetail.edit_id ? "更新推送中…" : "更新上架内容" }}
            </ErpButton>
            <ErpButton
              v-if="taskDetail.status === 'failed' || taskDetail.status === 'pushed' || taskDetail.status === 'partial' || taskDetail.edit_status === 'approved'"
              variant="secondary"
              :disabled="isPublishingBusy"
              @click="publish(taskDetail.edit_id)"
            >
              {{ publishingEditId === taskDetail.edit_id ? "推送中…" : "再次推送" }}
            </ErpButton>
            <ErpButton
              v-if="taskDetail.status === 'failed' || taskDetail.status === 'pushed' || taskDetail.status === 'partial'"
              :disabled="isPublishingBusy"
              @click="aiHealAndRepublish(taskDetail.edit_id)"
            >
              {{ healingEditId === taskDetail.edit_id ? "AI 修复中…" : "AI 修复并重推" }}
            </ErpButton>
            <ErpButton
              variant="ghost"
              :disabled="isPublishingBusy"
              @click="reopenEdit(taskDetail.edit_id)"
            >
              {{ reopeningEditId === taskDetail.edit_id ? "打开中…" : "回编辑修复" }}
            </ErpButton>
          </div>

          <div style="margin-top: 16px">
            <ListingPreviewPanel
              :preview="payloadPreview(taskDetail)"
              :show-payload="false"
              title="本次提交内容（类目 / 类型 / 价格 / 库存）"
            />
          </div>
        </template>
        <ErpEmpty v-else message="点击左侧任务查看详情" />
      </ErpCard>
    </div>
  </div>
</template>

<style scoped>
.publish-top-layout,
.publish-layout {
  display: grid;
  grid-template-columns: minmax(300px, 1fr) minmax(340px, 1.1fr);
  gap: 16px;
  align-items: start;
}

.erp-table tr.is-clickable {
  cursor: pointer;
}

.erp-table tr.is-selected td {
  background: rgba(21, 83, 100, 0.06);
}

.listing-error {
  margin: 12px 0 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(185, 28, 28, 0.08);
  color: #991b1b;
  font-size: 13px;
}

@media (max-width: 960px) {
  .publish-top-layout,
  .publish-layout {
    grid-template-columns: 1fr;
  }
}
</style>

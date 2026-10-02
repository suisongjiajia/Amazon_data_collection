<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { apiRequest } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";
import { getModuleDefinition } from "../config/modules";
import type { ListingPreview, OzonPublishTask, ProductEdit } from "../types/ozon-workflow";
import { resolvePublishTaskImage } from "../utils/product-display";
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
const selectedTaskIds = ref<number[]>([]);
const refreshing = ref(false);
const batchBusy = ref(false);
const publishingEditId = ref<number | null>(null);
const reopeningEditId = ref<number | null>(null);
const healingEditId = ref<number | null>(null);
const republishingEditId = ref<number | null>(null);
const batchProgress = ref("");

const isPublishingBusy = computed(
  () =>
    publishingEditId.value != null ||
    reopeningEditId.value != null ||
    healingEditId.value != null ||
    republishingEditId.value != null ||
    refreshing.value ||
    batchBusy.value,
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

const allTaskIds = computed(() => store.state.value.publishTasks.map((task) => task.id));

const allSelected = computed(
  () =>
    allTaskIds.value.length > 0 &&
    allTaskIds.value.every((id) => selectedTaskIds.value.includes(id)),
);

const selectedTasks = computed(() =>
  store.state.value.publishTasks.filter((task) => selectedTaskIds.value.includes(task.id)),
);

watch(
  () => store.state.value.publishTasks,
  (tasks) => {
    const alive = new Set(tasks.map((task) => task.id));
    selectedTaskIds.value = selectedTaskIds.value.filter((id) => alive.has(id));
    if (!tasks.length) {
      selectedTaskId.value = null;
      taskDetail.value = null;
      return;
    }
    if (selectedTaskId.value == null || !alive.has(selectedTaskId.value)) {
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

function publishStatusLabel(status: string): string | undefined {
  if (status === "running" || status === "processing" || status === "submitted" || status === "awaiting_pull") {
    return "Ozon 处理中";
  }
  if (status === "pushed" || status === "partial") {
    return "已推送，还不可售";
  }
  return undefined;
}

function resultLabel(task: OzonPublishTask): string {
  if (task.status === "awaiting_pull" || task.status === "submitted" || task.status === "running") {
    return `已提交，等 Ozon 处理 · ${task.total_count} SKU`;
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

function toggleTask(taskId: number, checked: boolean): void {
  if (checked) {
    if (!selectedTaskIds.value.includes(taskId)) {
      selectedTaskIds.value = [...selectedTaskIds.value, taskId];
    }
    return;
  }
  selectedTaskIds.value = selectedTaskIds.value.filter((id) => id !== taskId);
}

function toggleSelectAll(checked: boolean): void {
  selectedTaskIds.value = checked ? [...allTaskIds.value] : [];
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

async function refreshOne(taskId: number): Promise<OzonPublishTask> {
  return apiRequest<OzonPublishTask>(`/api/ozon/publish-tasks/${taskId}/refresh-status`, {
    method: "POST",
  });
}

async function refreshStatus(): Promise<void> {
  if (selectedTaskId.value == null || refreshing.value) return;
  refreshing.value = true;
  store.showNotice("正在拉取上架状态…");
  try {
    const task = await refreshOne(selectedTaskId.value);
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

async function reopenEdit(editId: number): Promise<void> {
  if (reopeningEditId.value != null) return;
  reopeningEditId.value = editId;
  store.showNotice("正在重新打开编辑…");
  try {
    await apiRequest<ProductEdit>(`/api/ozon/publish-tasks/reopen-edit/${editId}`, {
      method: "POST",
    });
    store.showNotice("已退回审核中心，可继续修改");
    store.setModule("review");
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

async function runBatch(
  label: string,
  tasks: OzonPublishTask[],
  worker: (task: OzonPublishTask) => Promise<void>,
): Promise<void> {
  if (!tasks.length || batchBusy.value) return;
  batchBusy.value = true;
  const total = tasks.length;
  let ok = 0;
  let done = 0;
  const errors: string[] = [];
  batchProgress.value = `${label}：0/${total}`;
  store.showNotice(`${label}：0/${total}…`);
  try {
    for (const task of tasks) {
      const tip = `${task.task_no || `#${task.id}`}`;
      batchProgress.value = `${label}：${done}/${total} · 进行中 ${tip}`;
      store.showNotice(`${label}：${done + 1}/${total} · ${tip}`);
      try {
        await worker(task);
        ok += 1;
      } catch (err) {
        errors.push(`${task.task_no}: ${err instanceof Error ? err.message : String(err)}`);
      }
      done += 1;
      batchProgress.value = `${label}：${done}/${total} · 成功 ${ok} · 失败 ${errors.length}`;
      store.showNotice(batchProgress.value);
    }
    await store.refreshAll();
    if (selectedTaskId.value != null) {
      await openTask(selectedTaskId.value);
    }
    if (errors.length) {
      store.showError(`${label}完成：成功 ${ok}/${total}，失败 ${errors.length}。${errors[0]}`);
    } else {
      store.showNotice(`${label}完成：全部 ${ok} 条成功`);
    }
  } finally {
    batchBusy.value = false;
    batchProgress.value = "";
  }
}

async function batchRefresh(): Promise<void> {
  const tasks = selectedTasks.value.filter((task) => canRefresh(task));
  await runBatch("批量拉取状态", tasks, async (task) => {
    const updated = await refreshOne(task.id);
    if (selectedTaskId.value === task.id) {
      taskDetail.value = updated;
    }
  });
}

async function batchRepublish(): Promise<void> {
  const tasks = selectedTasks.value.filter(
    (task) => task.status === "failed" || task.status === "pushed" || task.status === "partial",
  );
  await runBatch("批量再次推送", tasks, async (task) => {
    await apiRequest<OzonPublishTask>("/api/ozon/publish-tasks", {
      method: "POST",
      body: JSON.stringify({
        edit_id: task.edit_id,
        shop_name: shopName.value,
        simulate: simulatePublish.value,
        auto_follow: !simulatePublish.value,
      }),
    });
  });
}

async function batchHeal(): Promise<void> {
  const tasks = selectedTasks.value.filter(
    (task) => task.status === "failed" || task.status === "pushed" || task.status === "partial",
  );
  await runBatch("批量 AI 修复", tasks, async (task) => {
    await apiRequest(`/api/ozon/publish-tasks/ai-heal/${task.edit_id}`, { method: "POST" });
  });
}

async function batchReopen(): Promise<void> {
  const tasks = selectedTasks.value;
  const uniqueEditIds = [...new Set(tasks.map((task) => task.edit_id))];
  if (!uniqueEditIds.length || batchBusy.value) return;
  batchBusy.value = true;
  const total = uniqueEditIds.length;
  batchProgress.value = `批量回编辑：0/${total}`;
  store.showNotice(`批量回编辑：0/${total}…`);
  try {
    let done = 0;
    for (const editId of uniqueEditIds) {
      store.showNotice(`批量回编辑：${done + 1}/${total} · edit #${editId}`);
      batchProgress.value = `批量回编辑：${done + 1}/${total}`;
      await apiRequest(`/api/ozon/publish-tasks/reopen-edit/${editId}`, { method: "POST" });
      done += 1;
      batchProgress.value = `批量回编辑：${done}/${total}`;
    }
    store.showNotice(`批量回编辑完成：${total} 个商品已退回审核中心`);
    store.setModule("review");
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    batchBusy.value = false;
    batchProgress.value = "";
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
        { label: '发布任务', value: store.state.value.publishTasks.length, hint: '全部任务' },
        { label: '待拉取/已推送', value: pendingConfirmTasks.length, hint: '需拉取确认可售' },
        { label: '推送失败', value: failedTasks.length, hint: '可批量修复再推' },
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
        在「发布任务」勾选多条后可批量拉取状态、再次推送、AI 修复或回编辑。单个任务仍可在右侧详情操作。
      </p>
    </ErpCard>

    <div class="publish-layout">
      <ErpCard
        title="发布任务"
        :description="`${store.state.value.publishTasks.length} 条 · 已选 ${selectedTaskIds.length}`"
        padding="none"
      >
        <div v-if="store.state.value.publishTasks.length" class="batch-bar">
          <label class="batch-check">
            <input
              type="checkbox"
              :checked="allSelected"
              :disabled="isPublishingBusy"
              @change="toggleSelectAll(($event.target as HTMLInputElement).checked)"
            />
            全选
          </label>
          <span v-if="batchProgress" class="batch-progress">{{ batchProgress }}</span>
          <span v-else class="batch-progress batch-progress--idle">已选 {{ selectedTaskIds.length }}</span>
          <ErpButton
            size="sm"
            variant="secondary"
            :disabled="isPublishingBusy || !selectedTaskIds.length"
            @click="batchRefresh"
          >
            批量拉取状态
          </ErpButton>
          <ErpButton
            size="sm"
            variant="secondary"
            :disabled="isPublishingBusy || !selectedTaskIds.length"
            @click="batchRepublish"
          >
            批量再次推送
          </ErpButton>
          <ErpButton
            size="sm"
            :disabled="isPublishingBusy || !selectedTaskIds.length"
            @click="batchHeal"
          >
            批量 AI 修复
          </ErpButton>
          <ErpButton
            size="sm"
            variant="ghost"
            :disabled="isPublishingBusy || !selectedTaskIds.length"
            @click="batchReopen"
          >
            批量回编辑
          </ErpButton>
        </div>
        <div v-if="store.state.value.publishTasks.length" class="erp-table-wrap">
          <table class="erp-table">
            <thead>
              <tr>
                <th class="col-check"></th>
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
                <td class="col-check" @click.stop>
                  <input
                    type="checkbox"
                    :checked="selectedTaskIds.includes(task.id)"
                    :disabled="isPublishingBusy"
                    @change="toggleTask(task.id, ($event.target as HTMLInputElement).checked)"
                  />
                </td>
                <td>
                  <ErpProductCell
                    :image-url="resolvePublishTaskImage(task)"
                    :title="task.edit_title || `任务 ${task.task_no}`"
                    :subtitle="`${task.task_no}${task.family_external_id ? ` · ${task.family_external_id}` : ''}`"
                  />
                </td>
                <td><ErpBadge :status="task.status" :label="publishStatusLabel(task.status)" /></td>
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
                <ErpBadge :status="taskDetail.status" :label="publishStatusLabel(taskDetail.status)" />
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
              v-if="taskDetail.status === 'listed' || taskDetail.status === 'completed' || taskDetail.edit_status === 'published' || taskDetail.status === 'pushed' || taskDetail.status === 'partial'"
              :disabled="isPublishingBusy"
              @click="republishListed(taskDetail.edit_id)"
            >
              {{ republishingEditId === taskDetail.edit_id ? "更新推送中…" : "更新上架内容" }}
            </ErpButton>
            <ErpButton
              v-if="taskDetail.status === 'failed' || taskDetail.status === 'pushed' || taskDetail.status === 'partial'"
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
.publish-layout {
  display: grid;
  grid-template-columns: minmax(300px, 1fr) minmax(340px, 1.1fr);
  gap: 16px;
  align-items: start;
}

.batch-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 10px 12px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
}

.batch-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-right: 4px;
  font-size: 13px;
  color: #344054;
}

.batch-progress {
  flex: 1 1 160px;
  min-width: 120px;
  font-size: 12px;
  color: #027a48;
  font-variant-numeric: tabular-nums;
}

.batch-progress--idle {
  color: #667085;
}

.col-check {
  width: 36px;
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
  .publish-layout {
    grid-template-columns: 1fr;
  }
}
</style>

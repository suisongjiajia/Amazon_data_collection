<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { apiRequest } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";
import { getModuleDefinition } from "../config/modules";
import type { OzonPublishTask, ProductEdit } from "../types/ozon-workflow";
import { resolveEditImage, resolveEditSubtitle, resolvePublishTaskImage } from "../utils/product-display";
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
const simulatePublish = ref(true);
const selectedTaskId = ref<number | null>(null);
const taskDetail = ref<OzonPublishTask | null>(null);
const selectedEditId = ref<number | null>(null);

const approvedEdits = computed(() =>
  store.state.value.edits.filter((item) => item.status === "approved"),
);

const failedTasks = computed(() =>
  store.state.value.publishTasks.filter((item) => item.status === "failed"),
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

async function publish(editId: number): Promise<void> {
  try {
    const task = await apiRequest<OzonPublishTask>("/api/ozon/publish-tasks", {
      method: "POST",
      body: JSON.stringify({
        edit_id: editId,
        shop_name: shopName.value,
        simulate: simulatePublish.value,
      }),
    });
    store.showNotice(simulatePublish.value ? "模拟发布完成" : "已提交 Ozon 发布");
    await store.refreshAll();
    await openTask(task.id);
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
    await store.refreshAll();
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

function selectApproved(edit: ProductEdit): void {
  selectedEditId.value = edit.id;
}

async function reopenEdit(editId: number): Promise<void> {
  try {
    await apiRequest<ProductEdit>(`/api/ozon/publish-tasks/reopen-edit/${editId}`, {
      method: "POST",
    });
    store.showNotice("已重新打开编辑，请修复后重新生成 Listing 并审核");
    store.setModule("product-edit");
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  }
}

function payloadPreview(task: OzonPublishTask) {
  const images: string[] = [];
  const main = resolvePublishTaskImage(task);
  if (main) images.push(main);
  if (Array.isArray(task.edit_images)) {
    for (const url of task.edit_images) {
      if (typeof url === "string" && url && !images.includes(url)) images.push(url);
    }
  }
  const summary = {
    title: task.edit_title,
    description: "",
    bullet_points: [] as string[],
    images,
    variants: task.items.map((item) => ({
      sku: item.seller_sku,
      title: item.seller_sku,
      price: null,
      quantity: null,
    })),
  };
  return {
    ok: task.status === "completed" || task.status === "submitted",
    issues: task.error_message
      ? [{ code: "PUBLISH_ERROR", severity: "error" as const, message: task.error_message }]
      : [],
    summary,
    payload_items: task.items
      .map((item) => item.submission_payload)
      .filter((item): item is Record<string, unknown> => Boolean(item)),
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
        { label: '失败任务', value: failedTasks.length, hint: '需修复再推' },
        { label: '发布任务', value: store.stats.value.publishTasks },
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
      <p v-if="!simulatePublish" class="erp-detail-text">
        将使用 .env 中的 OZON_SELLER_CLIENT_ID / OZON_SELLER_API_KEY 调用真实上架接口。
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
                    <ErpButton size="sm" :disabled="store.loading.value" @click="publish(edit.id)">
                      推送到 Ozon
                    </ErpButton>
                    <ErpButton size="sm" variant="ghost" @click="reopenEdit(edit.id)">回编辑</ErpButton>
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
                  <td>{{ variant.price ?? "-" }}₽</td>
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
                <td>{{ task.success_count }} / {{ task.total_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <ErpEmpty v-else message="暂无发布任务" />
      </ErpCard>

      <ErpCard title="任务详情" description="查看报错、提交载荷，并支持回编辑修复后再推">
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
                <span v-if="taskDetail.family_external_id">Ozon ID {{ taskDetail.family_external_id }}</span>
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
                  <th>状态</th>
                  <th>错误码</th>
                  <th>错误信息</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in taskDetail.items" :key="item.id">
                  <td>{{ item.seller_sku }}</td>
                  <td><ErpBadge :status="item.status" /></td>
                  <td>{{ item.error_code || "-" }}</td>
                  <td>{{ item.error_message || "-" }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="erp-editor-actions" style="margin-top: 12px">
            <ErpButton
              v-if="taskDetail.status === 'failed' || taskDetail.edit_status === 'approved'"
              variant="secondary"
              @click="publish(taskDetail.edit_id)"
            >
              再次推送
            </ErpButton>
            <ErpButton
              v-if="taskDetail.edit_status !== 'published'"
              variant="ghost"
              @click="reopenEdit(taskDetail.edit_id)"
            >
              回编辑修复
            </ErpButton>
          </div>

          <div style="margin-top: 16px">
            <ListingPreviewPanel
              :preview="payloadPreview(taskDetail)"
              :show-payload="true"
              title="本次提交 Payload"
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

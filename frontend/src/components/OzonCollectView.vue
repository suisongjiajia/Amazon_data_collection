<script setup lang="ts">
import { computed, ref } from "vue";

import { apiRequest } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";
import { getModuleDefinition } from "../config/modules";
import type { OzonCollectionTask, OzonProductFamily } from "../types/ozon-workflow";
import ErpBadge from "./erp/ErpBadge.vue";
import ErpButton from "./erp/ErpButton.vue";
import ErpCard from "./erp/ErpCard.vue";
import ErpEmpty from "./erp/ErpEmpty.vue";
import ErpPageHeader from "./erp/ErpPageHeader.vue";
import ErpProductCell from "./erp/ErpProductCell.vue";
import ErpStatGrid from "./erp/ErpStatGrid.vue";

const store = useAppStore();
const module = getModuleDefinition("ozon-collect");
const collectionUrl = ref("");
const collecting = ref(false);
const retryingTaskId = ref<number | null>(null);
const pipelineTaskId = ref<number | null>(null);

function productCollectUrl(item: Pick<OzonProductFamily, "source_url" | "external_id">): string | null {
  const direct = item.source_url?.trim();
  if (direct) return direct;
  const externalId = item.external_id?.trim();
  if (externalId) return `https://www.ozon.ru/product/${externalId}/`;
  return null;
}

function truncateUrl(value: string, maxLength = 48): string {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1)}…`;
}

function taskSourceUrl(task: OzonCollectionTask): string {
  const fromParams =
    typeof task.strategy_params?.url === "string" ? task.strategy_params.url.trim() : "";
  return fromParams || task.source_url?.trim() || "";
}

function canRetry(task: OzonCollectionTask): boolean {
  return Boolean(taskSourceUrl(task) || task.strategy_type);
}

const productRows = computed(() =>
  store.state.value.ozonProducts.map((item) => ({
    item,
    collectUrl: productCollectUrl(item),
  })),
);

const failedTaskCount = computed(
  () => store.state.value.ozonTasks.filter((task) => task.status === "failed").length,
);

async function submitCollection(): Promise<void> {
  const url = collectionUrl.value.trim();
  if (!url) {
    store.showError("请先输入 Ozon 链接");
    return;
  }
  if (collecting.value) return;
  collecting.value = true;
  store.showNotice("正在采集，请稍候…");
  try {
    await apiRequest("/api/ozon/collect", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    store.showNotice("采集完成");
    collectionUrl.value = "";
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
    await store.refreshAll();
  } finally {
    collecting.value = false;
  }
}

async function retryTask(task: OzonCollectionTask): Promise<void> {
  if (!canRetry(task)) {
    store.showError("该任务没有可重试的链接或策略");
    return;
  }
  if (retryingTaskId.value != null || collecting.value) return;
  retryingTaskId.value = task.id;
  store.showNotice("正在重新采集…");
  try {
    await apiRequest(`/api/ozon/collections/${task.id}/retry`, { method: "POST" });
    store.showNotice(`已重新采集：${task.task_no}`);
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
    await store.refreshAll();
  } finally {
    retryingTaskId.value = null;
  }
}

async function startPipelineFromTask(task: OzonCollectionTask): Promise<void> {
  if (task.status !== "completed" || !task.success_count) {
    store.showError("仅已完成且有商品的采集任务可转入流水线");
    return;
  }
  if (pipelineTaskId.value != null || collecting.value) return;
  pipelineTaskId.value = task.id;
  store.showNotice("正在用已采商品启动流水线（不再重采）…");
  try {
    const job = await apiRequest<{ job_no: string }>("/api/shop-pipeline/from-collection", {
      method: "POST",
      body: JSON.stringify({
        collection_task_id: task.id,
        limit: task.success_count || undefined,
      }),
    });
    store.showNotice(`流水线已启动：${job.job_no}，可到「店铺流水线」查看进度`);
    store.setModule("shop-pipeline");
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    pipelineTaskId.value = null;
  }
}
</script>

<template>
  <div class="erp-stack">
    <ErpPageHeader :title="module.label" :description="module.description" />

    <ErpStatGrid
      :items="[
        { label: '商品总数', value: store.stats.value.products, hint: '已入库 Ozon 商品' },
        { label: '采集任务', value: store.stats.value.collectionTasks, hint: '历史任务' },
        { label: '失败任务', value: failedTaskCount, hint: '可点重新采集' },
        { label: '待审商品', value: store.stats.value.pendingReview, hint: '编辑审核' },
      ]"
    />

    <ErpCard title="链接采集" description="粘贴 Ozon 商品或店铺链接。Cookie 只配 .env 的 OZON_COOKIE 一套即可（采集与类目解析共用）">
      <div class="erp-form-row">
        <label class="erp-field erp-field--grow">
          <span>Ozon 链接</span>
          <input
            v-model="collectionUrl"
            type="text"
            placeholder="https://www.ozon.ru/product/... 或 seller 链接"
          />
        </label>
        <ErpButton :disabled="collecting || store.loading.value" @click="submitCollection">
          {{ collecting ? "采集中…" : "开始采集" }}
        </ErpButton>
      </div>
    </ErpCard>

    <ErpCard title="商品列表" :description="`${store.state.value.ozonProducts.length} 条`" padding="none">
      <div v-if="productRows.length" class="erp-table-wrap">
        <table class="erp-table">
          <thead>
            <tr>
              <th>商品</th>
              <th>采集链接</th>
              <th>价格</th>
              <th>排名</th>
              <th>品牌</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="{ item, collectUrl } in productRows" :key="item.id">
              <td>
                <ErpProductCell
                  :image-url="item.main_image_url"
                  :title="item.title"
                  :subtitle="item.external_id"
                />
              </td>
              <td>
                <a
                  v-if="collectUrl"
                  class="text-link url-cell"
                  :href="collectUrl"
                  target="_blank"
                  rel="noreferrer"
                  :title="collectUrl"
                >
                  {{ truncateUrl(collectUrl) }}
                </a>
                <span v-else>-</span>
              </td>
              <td>{{ item.variants?.[0]?.price_text ?? "-" }}</td>
              <td>{{ item.sales_rank ?? "-" }}</td>
              <td>{{ item.brand || "-" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <ErpEmpty v-else message="暂无商品，请先粘贴链接采集" />
    </ErpCard>

    <ErpCard title="采集任务" :description="`${store.state.value.ozonTasks.length} 条`" padding="none">
      <div v-if="store.state.value.ozonTasks.length" class="erp-table-wrap">
        <table class="erp-table">
          <thead>
            <tr>
              <th>任务编号</th>
              <th>链接 / 说明</th>
              <th>类型</th>
              <th>状态</th>
              <th>成功 / 总计</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in store.state.value.ozonTasks" :key="task.id">
              <td>{{ task.task_no }}</td>
              <td>
                <div class="task-meta">
                  <a
                    v-if="taskSourceUrl(task)"
                    class="text-link url-cell"
                    :href="taskSourceUrl(task)"
                    target="_blank"
                    rel="noreferrer"
                    :title="taskSourceUrl(task)"
                  >
                    {{ truncateUrl(taskSourceUrl(task), 40) }}
                  </a>
                  <span v-else>-</span>
                  <span v-if="task.error_message" class="task-error" :title="task.error_message">
                    {{ truncateUrl(task.error_message, 60) }}
                  </span>
                </div>
              </td>
              <td>{{ task.strategy_type }}</td>
              <td><ErpBadge :status="task.status" /></td>
              <td>{{ task.success_count }} / {{ task.total_count }}</td>
              <td>
                <div class="task-actions">
                  <ErpButton
                    v-if="task.status === 'completed' && task.success_count > 0"
                    size="sm"
                    :disabled="pipelineTaskId === task.id || collecting"
                    @click="startPipelineFromTask(task)"
                  >
                    {{ pipelineTaskId === task.id ? "启动中…" : "跑流水线" }}
                  </ErpButton>
                  <ErpButton
                    size="sm"
                    variant="secondary"
                    :disabled="!canRetry(task) || retryingTaskId === task.id || collecting"
                    @click="retryTask(task)"
                  >
                    {{
                      retryingTaskId === task.id
                        ? "重采中…"
                        : task.status === "failed"
                          ? "重新采集"
                          : "再采一次"
                    }}
                  </ErpButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <ErpEmpty v-else message="暂无采集任务" />
    </ErpCard>
  </div>
</template>

<style scoped>
.task-meta {
  display: grid;
  gap: 4px;
  max-width: 320px;
}

.task-error {
  color: #991b1b;
  font-size: 12px;
  line-height: 1.4;
}

.task-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>

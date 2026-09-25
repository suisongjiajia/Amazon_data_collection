<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";

import { apiRequest } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";
import { getModuleDefinition } from "../config/modules";
import type { ShopPipelineJob } from "../types/ozon-workflow";
import ErpBadge from "./erp/ErpBadge.vue";
import ErpButton from "./erp/ErpButton.vue";
import ErpCard from "./erp/ErpCard.vue";
import ErpEmpty from "./erp/ErpEmpty.vue";
import ErpPageHeader from "./erp/ErpPageHeader.vue";
import ErpProductCell from "./erp/ErpProductCell.vue";
import ErpStatGrid from "./erp/ErpStatGrid.vue";

const props = withDefaults(
  defineProps<{
    embedded?: boolean;
  }>(),
  { embedded: false },
);

const store = useAppStore();
const module = getModuleDefinition("ozon-collect");
const shopUrl = ref("");
const topN = ref(50);
const starting = ref(false);
const jobs = ref<ShopPipelineJob[]>([]);
const selectedJobId = ref<number | null>(null);
const selectedJob = ref<ShopPipelineJob | null>(null);
const loadingJobs = ref(false);
const retrying = ref(false);
const deletingId = ref<number | null>(null);
let pollTimer: ReturnType<typeof setInterval> | null = null;

const FAIL_STATUSES = new Set([
  "failed",
  "attr_missing",
  "image_failed",
  "sourcing_failed",
  "listing_failed",
  "pipeline_failed",
  "needs_fix",
  "publish_failed",
]);

function isFailStatus(status: string): boolean {
  return FAIL_STATUSES.has(status);
}

const selectedItems = computed(() => selectedJob.value?.items || []);

const runningCount = computed(
  () =>
    jobs.value.filter((job) =>
      ["queued", "collecting", "processing"].includes(job.status),
    ).length,
);

async function refreshJobs(): Promise<void> {
  loadingJobs.value = true;
  try {
    jobs.value = await apiRequest<ShopPipelineJob[]>("/api/shop-pipeline/jobs?limit=30");
    if (selectedJobId.value != null) {
      await openJob(selectedJobId.value, false);
    } else if (jobs.value.length) {
      await openJob(jobs.value[0].id, false);
    }
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    loadingJobs.value = false;
  }
}

async function openJob(jobId: number, showLoading = true): Promise<void> {
  selectedJobId.value = jobId;
  if (showLoading) loadingJobs.value = true;
  try {
    selectedJob.value = await apiRequest<ShopPipelineJob>(`/api/shop-pipeline/jobs/${jobId}`);
  } catch (err) {
    selectedJob.value = null;
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    if (showLoading) loadingJobs.value = false;
  }
}

async function startPipeline(): Promise<void> {
  const url = shopUrl.value.trim();
  if (!url) {
    store.showError("请粘贴 Ozon 或 1688 店铺链接");
    return;
  }
  if (starting.value) return;
  starting.value = true;
  const is1688 = /1688\.com|alibaba\.com/i.test(url);
  store.showNotice(
    is1688
      ? "已启动 1688 整店采集（调试 Chrome / CDP）…"
      : "已启动店铺流水线（后台采集 + 批量处理）…",
  );
  try {
    const result = await apiRequest<Record<string, unknown>>("/api/shop-pipeline/start", {
      method: "POST",
      body: JSON.stringify({ shop_url: url, top_n: topN.value || 50 }),
    });
    shopUrl.value = "";
    if (is1688 || result.families || result.count != null) {
      const count = Number(result.count ?? (Array.isArray(result.families) ? result.families.length : 0));
      store.showNotice(
        String(result.message || `1688 店铺已采集 ${count} 个商品（后续再接类目与上架）`),
      );
      await store.refreshAll();
      return;
    }
    const job = result as unknown as ShopPipelineJob;
    selectedJobId.value = job.id;
    selectedJob.value = job;
    store.showNotice(`流水线已创建：${job.job_no}`);
    await refreshJobs();
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    starting.value = false;
  }
}

async function retryFailed(): Promise<void> {
  if (selectedJobId.value == null || retrying.value) return;
  retrying.value = true;
  try {
    selectedJob.value = await apiRequest(
      `/api/shop-pipeline/jobs/${selectedJobId.value}/retry-failed`,
      { method: "POST" },
    );
    store.showNotice("已重试失败明细");
    await refreshJobs();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    retrying.value = false;
  }
}

async function retryItem(itemId: number): Promise<void> {
  if (retrying.value) return;
  retrying.value = true;
  try {
    await apiRequest(`/api/shop-pipeline/items/${itemId}/retry`, { method: "POST" });
    store.showNotice("已重试该商品");
    if (selectedJobId.value != null) await openJob(selectedJobId.value);
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    retrying.value = false;
  }
}

async function deleteItem(itemId: number): Promise<void> {
  if (deletingId.value != null) return;
  deletingId.value = itemId;
  try {
    await apiRequest(`/api/shop-pipeline/items/${itemId}`, { method: "DELETE" });
    store.showNotice("已从任务中删除");
    if (selectedJobId.value != null) await openJob(selectedJobId.value);
    await refreshJobs();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    deletingId.value = null;
  }
}

onMounted(() => {
  void refreshJobs();
  pollTimer = setInterval(() => {
    if (runningCount.value > 0 || selectedJob.value?.status === "processing") {
      void refreshJobs();
    }
  }, 8000);
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>

<template>
  <div class="erp-stack">
    <ErpPageHeader
      v-if="!props.embedded"
      :title="module.label"
      description="店铺流行 Top50 → 搜货选供 → AI Listing → 进入审核"
    />

    <ErpStatGrid
      :items="[
        { label: '流水线任务', value: jobs.length },
        { label: '进行中', value: runningCount, hint: '采集/处理中' },
        { label: '当前成功', value: selectedJob?.success_count ?? 0 },
        { label: '当前失败', value: selectedJob?.fail_count ?? 0 },
      ]"
    />

    <ErpCard
      title="启动店铺流水线"
      description="Ozon 店铺：采集→搜货→AI→审核。1688 店铺：采集后自动匹配类目/AI/进审核"
    >
      <div class="erp-form-row">
        <label class="erp-field erp-field--grow">
          <span>店铺链接</span>
          <input
            v-model="shopUrl"
            type="text"
            placeholder="Ozon /seller/... 或 1688 店铺 https://shopXXXX.1688.com/"
            @keyup.enter="startPipeline"
          />
        </label>
        <label class="erp-field" style="width: 120px">
          <span>Top N</span>
          <input v-model.number="topN" type="number" min="1" max="200" />
        </label>
        <ErpButton :disabled="starting || store.loading.value" @click="startPipeline">
          {{ starting ? "启动中…" : "开始流水线" }}
        </ErpButton>
      </div>
    </ErpCard>

    <div class="pipeline-layout">
      <ErpCard title="任务列表" :description="`${jobs.length} 条`" padding="none">
        <div v-if="jobs.length" class="erp-table-wrap">
          <table class="erp-table">
            <thead>
              <tr>
                <th>编号</th>
                <th>状态</th>
                <th>进度</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="job in jobs"
                :key="job.id"
                class="is-clickable"
                :class="{ 'is-selected': job.id === selectedJobId }"
                @click="openJob(job.id)"
              >
                <td>
                  <div class="job-cell">
                    <strong>{{ job.job_no }}</strong>
                    <span class="muted">{{ job.seller_slug || "店铺" }} · Top {{ job.top_n }}</span>
                  </div>
                </td>
                <td><ErpBadge :status="job.status" /></td>
                <td>{{ job.success_count }}/{{ job.total_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <ErpEmpty v-else message="暂无流水线任务" />
      </ErpCard>

      <ErpCard
        title="任务明细"
        :description="selectedJob ? `${selectedJob.job_no} · ${selectedItems.length} 品` : '选择左侧任务'"
      >
        <div v-if="selectedJob" class="erp-editor-actions" style="margin-bottom: 12px">
          <ErpButton
            variant="secondary"
            :disabled="retrying || !(selectedJob.fail_count > 0)"
            @click="retryFailed"
          >
            重试全部失败
          </ErpButton>
          <ErpButton variant="secondary" :disabled="loadingJobs" @click="refreshJobs">
            刷新
          </ErpButton>
        </div>
        <p v-if="selectedJob?.error_message" class="erp-detail-text" style="color: #b42318">
          {{ selectedJob.error_message }}
        </p>
        <div v-if="selectedItems.length" class="erp-table-wrap">
          <table class="erp-table">
            <thead>
              <tr>
                <th>#</th>
                <th>商品</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in selectedItems" :key="item.id">
                <td>{{ item.sales_rank ?? "-" }}</td>
                <td>
                  <ErpProductCell
                    :image-url="item.family_main_image_url || ''"
                    :title="item.family_title || `Family #${item.raw_product_family_id}`"
                    :subtitle="item.family_external_id || ''"
                  />
                  <p v-if="item.error_message" class="item-error">{{ item.error_message }}</p>
                </td>
                <td><ErpBadge :status="item.status" /></td>
                <td>
                  <div class="item-actions">
                    <ErpButton
                      v-if="isFailStatus(item.status)"
                      size="sm"
                      variant="secondary"
                      :disabled="retrying || deletingId != null"
                      @click="retryItem(item.id)"
                    >
                      重试
                    </ErpButton>
                    <ErpButton
                      size="sm"
                      variant="ghost"
                      :disabled="deletingId != null"
                      @click="deleteItem(item.id)"
                    >
                      {{ deletingId === item.id ? "删除中…" : "删除" }}
                    </ErpButton>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <ErpEmpty v-else-if="selectedJob" message="暂无明细（采集中或尚未入库）" />
        <ErpEmpty v-else message="请选择流水线任务" />
      </ErpCard>
    </div>
  </div>
</template>

<style scoped>
.pipeline-layout {
  display: grid;
  grid-template-columns: minmax(280px, 0.9fr) minmax(360px, 1.4fr);
  gap: 16px;
  align-items: start;
}

.job-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.muted {
  color: #667085;
  font-size: 12px;
}

.item-error {
  margin: 6px 0 0;
  color: #b42318;
  font-size: 12px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.item-actions {
  display: flex;
  gap: 6px;
  align-items: center;
}

.erp-table tr.is-clickable {
  cursor: pointer;
}

.erp-table tr.is-selected td {
  background: rgba(21, 83, 100, 0.06);
}

@media (max-width: 960px) {
  .pipeline-layout {
    grid-template-columns: 1fr;
  }
}
</style>

<script setup lang="ts">
import { apiRequest } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";
import { getModuleDefinition } from "../config/modules";
import ErpBadge from "./erp/ErpBadge.vue";
import ErpButton from "./erp/ErpButton.vue";
import ErpCard from "./erp/ErpCard.vue";
import ErpEmpty from "./erp/ErpEmpty.vue";
import ErpPageHeader from "./erp/ErpPageHeader.vue";
import ErpStatGrid from "./erp/ErpStatGrid.vue";

const store = useAppStore();
const module = getModuleDefinition("review");

const pendingEdits = () => store.state.value.edits.filter((item) => item.status === "pending_review");

async function approve(editId: number): Promise<void> {
  try {
    await apiRequest(`/api/reviews/${editId}/approve`, {
      method: "POST",
      body: JSON.stringify({ note: "通过" }),
    });
    store.showNotice("审核通过");
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  }
}

async function reject(editId: number): Promise<void> {
  try {
    await apiRequest(`/api/reviews/${editId}/reject`, {
      method: "POST",
      body: JSON.stringify({ note: "需修改" }),
    });
    store.showNotice("已驳回");
    await store.refreshAll();
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  }
}
</script>

<template>
  <div class="erp-stack">
    <ErpPageHeader :title="module.label" :description="module.description" />

    <ErpStatGrid
      :items="[
        { label: '待审核', value: pendingEdits().length, hint: '需处理' },
        { label: '已通过', value: store.stats.value.approved },
        { label: '编辑总数', value: store.state.value.edits.length },
      ]"
    />

    <ErpCard title="待审列表" :description="`${pendingEdits().length} 条待处理`" padding="none">
      <div v-if="pendingEdits().length" class="erp-table-wrap">
        <table class="erp-table">
          <thead>
            <tr>
              <th>标题</th>
              <th>状态</th>
              <th>SKU 数</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="edit in pendingEdits()" :key="edit.id">
              <td>{{ edit.title }}</td>
              <td><ErpBadge :status="edit.status" /></td>
              <td>{{ edit.variants.length }}</td>
              <td>
                <div class="erp-table-actions">
                  <ErpButton size="sm" :disabled="store.loading.value" @click="approve(edit.id)">通过</ErpButton>
                  <ErpButton size="sm" variant="danger" @click="reject(edit.id)">驳回</ErpButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <ErpEmpty v-else message="暂无待审商品，编辑模块提交后将出现在此处" />
    </ErpCard>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";

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
const module = getModuleDefinition("ozon-publish");
const shopName = ref("演示店铺");
const simulatePublish = ref(true);

const approvedEdits = () => store.state.value.edits.filter((item) => item.status === "approved");

async function publish(editId: number): Promise<void> {
  try {
    await apiRequest("/api/ozon/publish-tasks", {
      method: "POST",
      body: JSON.stringify({
        edit_id: editId,
        shop_name: shopName.value,
        simulate: simulatePublish.value,
      }),
    });
    store.showNotice("已提交 Ozon 发布");
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
        { label: '可发布', value: approvedEdits().length, hint: '已通过审核' },
        { label: '发布任务', value: store.stats.value.publishTasks },
        { label: '商品总数', value: store.stats.value.products },
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

    <ErpCard title="可发布商品" :description="`${approvedEdits().length} 条`" padding="none">
      <div v-if="approvedEdits().length" class="erp-table-wrap">
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
            <tr v-for="edit in approvedEdits()" :key="edit.id">
              <td>{{ edit.title }}</td>
              <td><ErpBadge :status="edit.status" /></td>
              <td>{{ edit.variants.length }}</td>
              <td>
                <ErpButton size="sm" :disabled="store.loading.value" @click="publish(edit.id)">
                  发布到 Ozon
                </ErpButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <ErpEmpty v-else message="暂无已通过审核的商品" />
    </ErpCard>

    <ErpCard title="发布任务" :description="`${store.state.value.publishTasks.length} 条`" padding="none">
      <div v-if="store.state.value.publishTasks.length" class="erp-table-wrap">
        <table class="erp-table">
          <thead>
            <tr>
              <th>任务编号</th>
              <th>店铺</th>
              <th>状态</th>
              <th>成功 / 总计</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in store.state.value.publishTasks" :key="task.id">
              <td>{{ task.task_no }}</td>
              <td>{{ task.shop_name || "-" }}</td>
              <td><ErpBadge :status="task.status" /></td>
              <td>{{ task.success_count }} / {{ task.total_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <ErpEmpty v-else message="暂无发布任务" />
    </ErpCard>
  </div>
</template>

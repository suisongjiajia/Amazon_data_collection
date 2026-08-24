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
import ErpProductCell from "./erp/ErpProductCell.vue";
import ErpStatGrid from "./erp/ErpStatGrid.vue";

const store = useAppStore();
const module = getModuleDefinition("ozon-collect");
const collectionUrl = ref("");

async function submitCollection(): Promise<void> {
  const url = collectionUrl.value.trim();
  if (!url) {
    store.showError("请先输入 Ozon 链接");
    return;
  }
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
        { label: '货源候选', value: store.stats.value.candidates, hint: '1688 匹配' },
        { label: '待审商品', value: store.stats.value.pendingReview, hint: '编辑审核' },
      ]"
    />

    <ErpCard title="链接采集" description="粘贴 Ozon 商品或店铺链接。遇 403 请将 Cookie 配置到 .env 的 OZON_COOKIE">
      <div class="erp-form-row">
        <label class="erp-field erp-field--grow">
          <span>Ozon 链接</span>
          <input
            v-model="collectionUrl"
            type="text"
            placeholder="https://www.ozon.ru/product/... 或 seller 链接"
          />
        </label>
        <ErpButton :disabled="store.loading.value" @click="submitCollection">
          {{ store.loading.value ? "采集中…" : "开始采集" }}
        </ErpButton>
      </div>
    </ErpCard>

    <ErpCard title="商品列表" :description="`${store.state.value.ozonProducts.length} 条`" padding="none">
      <div v-if="store.state.value.ozonProducts.length" class="erp-table-wrap">
        <table class="erp-table">
          <thead>
            <tr>
              <th>商品</th>
              <th>价格</th>
              <th>排名</th>
              <th>品牌</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in store.state.value.ozonProducts" :key="item.id">
              <td>
                <ErpProductCell
                  :image-url="item.main_image_url"
                  :title="item.title"
                  :subtitle="item.external_id"
                />
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
              <th>类型</th>
              <th>状态</th>
              <th>成功 / 总计</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in store.state.value.ozonTasks" :key="task.id">
              <td>{{ task.task_no }}</td>
              <td>{{ task.strategy_type }}</td>
              <td><ErpBadge :status="task.status" /></td>
              <td>{{ task.success_count }} / {{ task.total_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <ErpEmpty v-else message="暂无采集任务" />
    </ErpCard>
  </div>
</template>

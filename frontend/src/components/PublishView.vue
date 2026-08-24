<script setup lang="ts">
import { toRef } from "vue";
import type { WorkflowState, WorkflowUiState } from "../types/workflow";
import type { WorkflowHelpers } from "../types/view-context";

const props = defineProps<{
  state: WorkflowState;
  ui: WorkflowUiState;
  helpers: WorkflowHelpers;
}>();

const state = props.state;
const defaultShopName = toRef(props.ui, "defaultShopName");
const defaultMarketplace = toRef(props.ui, "defaultMarketplace");
const { formatDate, formatNumber, getStatusLabel, getMarketplaceLabel } = props.helpers;
</script>

<template>
  <section class="panel-shell">
    <div class="panel-header">
      <div>
        <p class="eyebrow">发布</p>
        <h3>发布管理</h3>
      </div>
      <p>任务与在线 SKU</p>
    </div>

    <div class="action-bar action-bar-muted">
      <label class="action-bar-field">
        <span>店铺名称</span>
        <input v-model="defaultShopName" type="text" />
      </label>
      <label class="action-bar-field">
        <span>站点</span>
        <input v-model="defaultMarketplace" type="text" />
      </label>
    </div>

    <div class="detail-block">
      <div class="subpanel-head">
        <h4>发布任务</h4>
        <span>{{ state.publishTasks.length }} 条记录</span>
      </div>
      <div class="table-wrap list-table" v-if="state.publishTasks.length">
        <table>
          <thead>
            <tr>
              <th>任务编号</th>
              <th>店铺</th>
              <th>站点</th>
              <th>类型</th>
              <th>状态</th>
              <th>成功 / 总计</th>
              <th>完成时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in state.publishTasks" :key="task.id">
              <td>{{ task.task_no }}</td>
              <td>{{ task.shop_name || "-" }}</td>
              <td>{{ getMarketplaceLabel(task.marketplace) }}</td>
              <td>{{ task.submit_type === "simulation" ? "模拟" : "手动" }}</td>
              <td>
                <span class="status-pill" :data-status="task.status">
                  {{ getStatusLabel(task.status) }}
                </span>
              </td>
              <td>{{ task.success_count }} / {{ task.total_count }}</td>
              <td>{{ formatDate(task.finished_at || task.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty-state">暂无发布任务。</p>
    </div>

    <div class="detail-block">
      <div class="subpanel-head">
        <h4>在线 SKU</h4>
        <span>{{ state.liveListings.length }} 条记录</span>
      </div>
      <div class="table-wrap list-table" v-if="state.liveListings.length">
        <table>
          <thead>
            <tr>
              <th>卖家 SKU</th>
              <th>ASIN</th>
              <th>状态</th>
              <th>店铺</th>
              <th>站点</th>
              <th>价格</th>
              <th>库存</th>
              <th>更新时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in state.liveListings" :key="item.id">
              <td>{{ item.seller_sku }}</td>
              <td>{{ item.asin || "-" }}</td>
              <td>
                <span class="status-pill" :data-status="item.listing_status">
                  {{ getStatusLabel(item.listing_status) }}
                </span>
              </td>
              <td>{{ item.shop_name }}</td>
              <td>{{ getMarketplaceLabel(item.marketplace) }}</td>
              <td>{{ formatNumber(item.price) }}</td>
              <td>{{ item.quantity }}</td>
              <td>{{ formatDate(item.updated_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty-state">暂无在线 SKU 记录。</p>
    </div>
  </section>
</template>

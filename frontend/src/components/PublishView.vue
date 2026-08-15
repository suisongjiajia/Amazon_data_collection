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
        <p class="eyebrow">Publish</p>
        <h3>Publish Center</h3>
      </div>
      <p>Review publish tasks and the live SKU records written back from simulation.</p>
    </div>

    <div class="action-bar action-bar-muted">
      <label class="action-bar-field">
        <span>Shop Name</span>
        <input v-model="defaultShopName" type="text" />
      </label>
      <label class="action-bar-field">
        <span>Marketplace</span>
        <input v-model="defaultMarketplace" type="text" />
      </label>
    </div>

    <div class="detail-block">
      <div class="subpanel-head">
        <h4>Publish Tasks</h4>
        <span>{{ state.publishTasks.length }} records</span>
      </div>
      <div class="table-wrap list-table" v-if="state.publishTasks.length">
        <table>
          <thead>
            <tr>
              <th>Task No.</th>
              <th>Shop</th>
              <th>Marketplace</th>
              <th>Type</th>
              <th>Status</th>
              <th>Success / Total</th>
              <th>Completed At</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in state.publishTasks" :key="task.id">
              <td>{{ task.task_no }}</td>
              <td>{{ task.shop_name || "-" }}</td>
              <td>{{ getMarketplaceLabel(task.marketplace) }}</td>
              <td>{{ task.submit_type === "simulation" ? "Simulation" : "Manual" }}</td>
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
      <p v-else class="empty-state">No publish tasks yet.</p>
    </div>

    <div class="detail-block">
      <div class="subpanel-head">
        <h4>Live SKUs</h4>
        <span>{{ state.liveListings.length }} records</span>
      </div>
      <div class="table-wrap list-table" v-if="state.liveListings.length">
        <table>
          <thead>
            <tr>
              <th>Seller SKU</th>
              <th>ASIN</th>
              <th>Status</th>
              <th>Shop</th>
              <th>Marketplace</th>
              <th>Price</th>
              <th>Quantity</th>
              <th>Updated At</th>
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
      <p v-else class="empty-state">No live SKU records yet.</p>
    </div>
  </section>
</template>

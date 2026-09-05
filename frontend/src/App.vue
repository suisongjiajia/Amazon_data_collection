<script setup lang="ts">
import { onMounted } from "vue";

import OzonCollectView from "./components/OzonCollectView.vue";
import OzonPublishView from "./components/OzonPublishView.vue";
import ProductEditView from "./components/ProductEditView.vue";
import ReviewView from "./components/ReviewView.vue";
import SourcingView from "./components/SourcingView.vue";
import ErpLayout from "./components/erp/ErpLayout.vue";
import { useAppStore } from "./composables/useAppStore";

const store = useAppStore();

onMounted(() => {
  void store.refreshAll();
});
</script>

<template>
  <ErpLayout
    :active-module="store.activeModule.value"
    :loading="store.loading.value"
    :stats="store.stats.value"
    :notice="store.notice.value"
    :error="store.error.value"
    :health="store.health.value"
    @update:module="store.setModule"
    @refresh="store.refreshAll"
  >
    <OzonCollectView v-if="store.activeModule.value === 'ozon-collect'" />
    <SourcingView v-else-if="store.activeModule.value === 'sourcing'" />
    <ProductEditView v-else-if="store.activeModule.value === 'product-edit'" />
    <ReviewView v-else-if="store.activeModule.value === 'review'" />
    <OzonPublishView v-else />
  </ErpLayout>
</template>

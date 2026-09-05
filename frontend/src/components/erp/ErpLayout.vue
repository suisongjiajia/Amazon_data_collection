<script setup lang="ts">
import { computed } from "vue";

import { ERP_MODULES, getModuleDefinition } from "../../config/modules";
import type { OzonHealth } from "../../composables/useAppStore";
import type { OzonViewKey } from "../../types/ozon-workflow";
import ErpButton from "./ErpButton.vue";

const props = defineProps<{
  activeModule: OzonViewKey;
  loading: boolean;
  stats: {
    products: number;
    candidates: number;
    pendingReview: number;
    approved: number;
    publishTasks: number;
    collectionTasks: number;
  };
  notice?: string;
  error?: string;
  health?: OzonHealth | null;
}>();

const emit = defineEmits<{
  "update:module": [key: OzonViewKey];
  refresh: [];
}>();

const currentModule = computed(() => getModuleDefinition(props.activeModule));

const moduleGroups = computed(() => {
  const groups = new Map<string, typeof ERP_MODULES>();
  for (const module of ERP_MODULES) {
    const list = groups.get(module.group) ?? [];
    list.push(module);
    groups.set(module.group, list);
  }
  return Array.from(groups.entries());
});

const failedChecks = computed(() =>
  (props.health?.checks || []).filter((item) => item.required && !item.ok),
);
</script>

<template>
  <div class="erp-app">
    <aside class="erp-sidebar">
      <div class="erp-sidebar__brand">
        <div class="erp-sidebar__logo">OZ</div>
        <div>
          <strong>Ozon ERP</strong>
          <span>跨境商品运营系统</span>
        </div>
      </div>

      <nav class="erp-sidebar__nav">
        <div v-for="[group, modules] in moduleGroups" :key="group" class="erp-nav-group">
          <span class="erp-nav-group__label">{{ group }}</span>
          <button
            v-for="module in modules"
            :key="module.key"
            type="button"
            class="erp-nav-item"
            :class="{ active: activeModule === module.key }"
            @click="emit('update:module', module.key)"
          >
            <span class="erp-nav-item__icon">{{ module.icon }}</span>
            <span class="erp-nav-item__copy">
              <strong>{{ module.label }}</strong>
              <small>步骤 {{ module.step }} · {{ module.shortLabel }}</small>
            </span>
          </button>
        </div>
      </nav>

      <div class="erp-sidebar__footer">
        <div class="erp-sidebar__meta">
          <span>商品 {{ stats.products }}</span>
          <span>任务 {{ stats.collectionTasks }}</span>
        </div>
      </div>
    </aside>

    <div class="erp-main">
      <header class="erp-topbar">
        <div class="erp-topbar__breadcrumb">
          <span>工作台</span>
          <span class="erp-topbar__sep">/</span>
          <span>{{ currentModule.group }}</span>
          <span class="erp-topbar__sep">/</span>
          <strong>{{ currentModule.label }}</strong>
        </div>
        <div class="erp-topbar__actions">
          <ErpButton variant="secondary" size="sm" :disabled="loading" @click="emit('refresh')">
            {{ loading ? "刷新中…" : "刷新数据" }}
          </ErpButton>
        </div>
      </header>

      <div v-if="failedChecks.length" class="erp-alert erp-alert--danger">
        <strong>开店配置未就绪：</strong>
        {{ health?.summary || failedChecks.map((item) => item.message).join("；") }}
        <div class="erp-alert__hint">
          只需维护一套 OZON_COOKIE（采集与类目解析共用）。API 密钥与仓库 ID 仍需在 .env 配置。
        </div>
      </div>
      <div v-else-if="health?.ok" class="erp-alert erp-alert--success">
        配置体检通过：Cookie / Seller API / 仓库已就绪
      </div>
      <div v-if="notice" class="erp-alert erp-alert--success">{{ notice }}</div>
      <div v-if="error" class="erp-alert erp-alert--danger">{{ error }}</div>

      <main class="erp-content">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
.erp-alert__hint {
  margin-top: 6px;
  font-size: 12px;
  opacity: 0.9;
}
</style>

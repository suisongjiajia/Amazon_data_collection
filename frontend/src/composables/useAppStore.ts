import { computed, readonly, ref } from "vue";

import { apiRequest } from "../lib/api";
import type {
  OzonCollectionTask,
  OzonProductFamily,
  OzonPublishTask,
  OzonViewKey,
  OzonWorkflowState,
  ProductEdit,
  SupplierCandidate,
} from "../types/ozon-workflow";

export interface OzonHealthCheck {
  key: string;
  label: string;
  ok: boolean;
  required: boolean;
  message: string;
  hint?: string;
}

export interface OzonHealth {
  ok: boolean;
  summary: string;
  checks: OzonHealthCheck[];
  failed_required: string[];
}

const state = ref<OzonWorkflowState>({
  ozonTasks: [],
  ozonProducts: [],
  candidates: [],
  edits: [],
  publishTasks: [],
});

const loading = ref(false);
const activeModule = ref<OzonViewKey>("ozon-collect");
const notice = ref("");
const error = ref("");
const health = ref<OzonHealth | null>(null);

export function useAppStore() {
  const stats = computed(() => ({
    products: state.value.ozonProducts.length,
    candidates: state.value.candidates.length,
    pendingReview: state.value.edits.filter((item) => item.status === "pending_review").length,
    approved: state.value.edits.filter((item) => item.status === "approved").length,
    publishTasks: state.value.publishTasks.length,
    collectionTasks: state.value.ozonTasks.length,
  }));

  async function refreshAll(): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      const [ozonTasks, ozonProducts, candidates, edits, publishTasks, ozonHealth] =
        await Promise.all([
          apiRequest<OzonCollectionTask[]>("/api/ozon/collections"),
          apiRequest<OzonProductFamily[]>("/api/ozon/products"),
          apiRequest<SupplierCandidate[]>("/api/sourcing/candidates"),
          apiRequest<ProductEdit[]>("/api/product-edits"),
          apiRequest<OzonPublishTask[]>("/api/ozon/publish-tasks"),
          apiRequest<OzonHealth>("/api/ozon/health").catch(() => null),
        ]);
      state.value = { ozonTasks, ozonProducts, candidates, edits, publishTasks };
      health.value = ozonHealth;
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
  }

  function setModule(key: OzonViewKey): void {
    activeModule.value = key;
  }

  function showNotice(message: string): void {
    notice.value = message;
    error.value = "";
  }

  function showError(message: string): void {
    error.value = message;
  }

  function clearMessages(): void {
    notice.value = "";
    error.value = "";
  }

  return {
    state: readonly(state),
    loading: readonly(loading),
    activeModule: readonly(activeModule),
    notice: readonly(notice),
    error: readonly(error),
    health: readonly(health),
    stats,
    refreshAll,
    setModule,
    showNotice,
    showError,
    clearMessages,
  };
}

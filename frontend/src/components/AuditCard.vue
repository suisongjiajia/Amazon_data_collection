<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";

import { apiUploadImages } from "../lib/api";
import { useAppStore } from "../composables/useAppStore";

export interface AuditVariant {
  id: number;
  sku: string;
  title: string;
  imageUrl?: string | null;
  /** 该规格自己的一组图；第一张为上架主图 */
  images: string[];
  color: string;
  size: string;
  price: number | null;
  quantity: number;
  netDepth: number | null;
  netWidth: number | null;
  netHeight: number | null;
}

export interface AuditCardModel {
  editId: number;
  title: string;
  imageUrl?: string | null;
  externalId?: string | null;
  productUrl?: string | null;
  skuCount: number;
  imageCount: number;
  status: string;
  failureReason?: string | null;
  supplierName?: string | null;
  supplierPrice?: string | null;
  matchScore?: number | null;
  packageManual: boolean;
  aspect: "color" | "size";
  depthMm: number;
  widthMm: number;
  heightMm: number;
  weightG: number;
  netDepthMm: number | null;
  netWidthMm: number | null;
  netHeightMm: number | null;
  images: string[];
  variants: AuditVariant[];
}

export interface AuditSavePayload {
  depth_mm: number;
  width_mm: number;
  height_mm: number;
  weight_g: number;
  net_depth_mm: number | null;
  net_width_mm: number | null;
  net_height_mm: number | null;
  variants: Array<{
    variant_id: number;
    price: number | null;
    color: string;
    quantity: number;
    title: string;
    size: string;
    image_url?: string | null;
    images?: string[];
    net_depth_mm: number | null;
    net_width_mm: number | null;
    net_height_mm: number | null;
  }>;
  images: string[];
  variant_aspect: "color" | "size";
}

const props = defineProps<{
  item: AuditCardModel;
  syncKey?: number;
  busy?: boolean;
}>();

const open = defineModel<boolean>("open", { default: false });
const store = useAppStore();
const previewUrl = ref<string | null>(null);
const variantFileInput = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
const variantDrag = ref<{ variantId: number; index: number } | null>(null);
const uploadTargetVariantId = ref<number | null>(null);
const pasteTargetVariantId = ref<number | null>(null);

const emit = defineEmits<{
  approve: [payload: AuditSavePayload];
  save: [payload: AuditSavePayload];
  reject: [];
  openSourcing: [];
}>();

const form = reactive({
  depth: 100,
  width: 100,
  height: 100,
  weight: 200,
  netDepth: null as number | null,
  netWidth: null as number | null,
  netHeight: null as number | null,
  images: [] as string[],
  aspect: "color" as "color" | "size",
  variants: [] as AuditVariant[],
});

watch(
  () => props.syncKey ?? 0,
  () => resetForm(),
  { immediate: true },
);

function resetForm(): void {
  const item = props.item;
  form.depth = item.depthMm;
  form.width = item.widthMm;
  form.height = item.heightMm;
  form.weight = item.weightG;
  form.netDepth = item.netDepthMm;
  form.netWidth = item.netWidthMm;
  form.netHeight = item.netHeightMm;
  form.aspect = item.aspect;
  form.variants = item.variants.map((variant) => normalizeVariant(variant, item.images));
  form.images = uniqUrls(form.variants.flatMap((variant) => variant.images));
  pasteTargetVariantId.value = form.variants[0]?.id ?? null;
}

function uniqUrls(urls: Array<string | null | undefined>): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of urls) {
    const url = String(raw || "").trim();
    if (!url || seen.has(url)) continue;
    seen.add(url);
    out.push(url);
  }
  return out;
}

function normalizeVariant(variant: AuditVariant, productImages: string[] = []): AuditVariant {
  let images = uniqUrls([...(variant.images || []), variant.imageUrl]);
  // 旧数据只有商品级图：拷入该变体，作为独立 listing 的初始主图+副图
  if (images.length <= 1 && productImages.length) {
    images = uniqUrls([images[0], ...productImages]);
  }
  return {
    ...variant,
    images,
    imageUrl: images[0] || variant.imageUrl || null,
  };
}

const packageWeightHint = computed(() => {
  const depth = Number(form.depth) || 0;
  const width = Number(form.width) || 0;
  const height = Number(form.height) || 0;
  const weight = Number(form.weight) || 0;
  if (depth <= 0 || width <= 0 || height <= 0 || weight <= 0) return "";
  const volume = (depth * width * height) / 1000;
  const minWeight = Math.max(50, Math.ceil(volume * 0.003));
  if (weight >= minWeight) return "";
  return `这个尺寸大约 ${Math.round(volume)} cm³，重量至少要 ${minWeight}g。保存时会拦住，否则 Ozon 会报尺寸或重量不正确。`;
});
const isNeedsFix = computed(() => props.item.status === "needs_fix");
const minVariantImages = computed(() => {
  if (!form.variants.length) return 0;
  return Math.min(...form.variants.map((variant) => variant.images.length));
});
const imageOk = computed(() => form.variants.length > 0 && form.variants.every((variant) => variant.images.length >= 5));
const packageTouched = computed(() => {
  const item = props.item;
  return (
    item.packageManual
    || form.depth !== item.depthMm
    || form.width !== item.widthMm
    || form.height !== item.heightMm
    || form.weight !== item.weightG
  );
});

const stages = computed(() => {
  const reviewState = isNeedsFix.value ? "error" : "current";
  return [
    { key: "collect", label: "采集", state: "done" },
    { key: "source", label: "1688搜货", state: "done" },
    { key: "ai", label: "AI生成", state: "done" },
    { key: "review", label: isNeedsFix.value ? "待修复" : "待审核", state: reviewState },
    { key: "push", label: "推送Ozon", state: "wait" },
    { key: "listed", label: "可售", state: "wait" },
  ];
});

function optionalMm(value: number | null): number | null {
  const num = Number(value);
  if (!Number.isFinite(num) || num <= 0) return null;
  return Math.round(num);
}

function payload(): AuditSavePayload {
  const variants = form.variants.map((variant) => {
    const images = uniqUrls(variant.images || []);
    return {
      variant_id: variant.id,
      price: variant.price,
      color: variant.color.trim(),
      quantity: Number(variant.quantity) || 0,
      title: variant.title.trim(),
        size: variant.size.trim(),
      image_url: images[0] || null,
      images,
      net_depth_mm: null,
      net_width_mm: null,
      net_height_mm: null,
    };
  });
  // 商品级 images 仅作列表缩略图镜像，上架按各变体 images
  return {
    depth_mm: Number(form.depth),
    width_mm: Number(form.width),
    height_mm: Number(form.height),
    weight_g: Number(form.weight),
    net_depth_mm: optionalMm(form.netDepth),
    net_width_mm: optionalMm(form.netWidth),
    net_height_mm: optionalMm(form.netHeight),
    images: uniqUrls(variants.flatMap((variant) => variant.images)).slice(0, 15),
    variant_aspect: form.aspect,
    variants,
  };
}

function findVariant(variantId: number): AuditVariant | undefined {
  return form.variants.find((item) => item.id === variantId);
}

function removeVariantImage(variantId: number, index: number): void {
  const variant = findVariant(variantId);
  if (!variant) return;
  const removed = variant.images[index];
  variant.images.splice(index, 1);
  variant.imageUrl = variant.images[0] || null;
  if (previewUrl.value === removed) previewUrl.value = null;
}

function moveVariantImage(variantId: number, from: number, to: number): void {
  const variant = findVariant(variantId);
  if (!variant) return;
  if (from === to || from < 0 || to < 0 || from >= variant.images.length || to >= variant.images.length) return;
  const [item] = variant.images.splice(from, 1);
  variant.images.splice(to, 0, item);
  variant.imageUrl = variant.images[0] || null;
}

function openVariantUpload(variantId: number): void {
  pasteTargetVariantId.value = variantId;
  uploadTargetVariantId.value = variantId;
  variantFileInput.value?.click();
}

async function uploadToVariant(variantId: number, files: File[]): Promise<void> {
  const variant = findVariant(variantId);
  if (!variant || !files.length || uploading.value) return;
  const room = 15 - variant.images.length;
  if (room <= 0) {
    store.showError("每个 listing 最多 15 张图");
    return;
  }
  uploading.value = true;
  try {
    const prepared = await Promise.all(files.slice(0, room).map((file) => cropToOzonSquare(file)));
    const result = await apiUploadImages(prepared, {
      sku: variant.sku || props.item.externalId || "variant",
    });
    for (const url of result.images || []) {
      if (url && !variant.images.includes(url)) variant.images.push(url);
    }
    variant.imageUrl = variant.images[0] || null;
    const failed = result.errors?.map((item) => item.error).filter(Boolean) || [];
    if (failed.length) store.showError(failed.join("；"));
    else store.showNotice(`已上传 ${result.images?.length || 0} 张到 ${variant.sku}`);
  } catch (err) {
    store.showError(err instanceof Error ? err.message : String(err));
  } finally {
    uploading.value = false;
  }
}

async function onPickVariantImages(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  input.value = "";
  const variantId = uploadTargetVariantId.value;
  uploadTargetVariantId.value = null;
  if (!variantId || !files.length) return;
  await uploadToVariant(variantId, files);
}

async function cropToOzonSquare(file: File): Promise<File> {
  const bitmap = await createImageBitmap(file);
  const side = Math.min(bitmap.width, bitmap.height);
  const sx = Math.floor((bitmap.width - side) / 2);
  const sy = Math.floor((bitmap.height - side) / 2);
  const canvas = document.createElement("canvas");
  canvas.width = 1000;
  canvas.height = 1000;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("无法裁剪图片");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, 1000, 1000);
  ctx.drawImage(bitmap, sx, sy, side, side, 0, 0, 1000, 1000);
  bitmap.close();
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
  if (!blob) throw new Error("裁剪失败");
  const name = file.name.replace(/\.\w+$/, "") || "image";
  return new File([blob], `${name}.jpg`, { type: "image/jpeg" });
}

function onPasteImages(event: ClipboardEvent): void {
  const target = event.target as HTMLElement | null;
  if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
  const files: File[] = [];
  for (const item of Array.from(event.clipboardData?.items || [])) {
    if (item.kind === "file" && item.type.startsWith("image/")) {
      const file = item.getAsFile();
      if (file) files.push(file);
    }
  }
  if (!files.length) return;
  const variantId = pasteTargetVariantId.value ?? form.variants[0]?.id;
  if (!variantId) return;
  event.preventDefault();
  void uploadToVariant(variantId, files);
}

function onPrimary(): void {
  if (props.busy) return;
  if (isNeedsFix.value) {
    emit("save", payload());
    return;
  }
  if (!imageOk.value) return;
  emit("approve", payload());
}
</script>

<template>
  <article class="audit-card" :class="{ 'is-fix': isNeedsFix }">
    <ol class="audit-timeline" aria-label="流程轨迹">
      <li v-for="stage in stages" :key="stage.key" :class="`is-${stage.state}`">
        {{ stage.label }}
      </li>
    </ol>

    <p v-if="isNeedsFix" class="audit-alert">
      待修复<span v-if="item.failureReason">：{{ item.failureReason }}</span>
    </p>

    <div class="audit-head">
      <img v-if="item.imageUrl" class="audit-cover" :src="item.imageUrl" alt="" />
      <div v-else class="audit-cover audit-cover--empty">无图</div>

      <div class="audit-head__main">
        <h3>
          <a
            v-if="item.productUrl"
            class="audit-title-link"
            :href="item.productUrl"
            target="_blank"
            rel="noreferrer"
          >{{ item.title || "未命名商品" }}</a>
          <template v-else>{{ item.title || "未命名商品" }}</template>
        </h3>
        <p>
          <span v-if="item.externalId">Ozon {{ item.externalId }}</span>
          <span>SKU {{ item.skuCount }}</span>
          <span :class="{ 'is-bad': !imageOk }">图集 {{ minVariantImages }}/5（每 listing）</span>
        </p>
        <p class="audit-muted">
          供应商 {{ item.supplierName || "展开后加载" }}
          <template v-if="item.supplierPrice"> · {{ item.supplierPrice }}</template>
          <template v-if="item.matchScore != null"> · 匹配 {{ item.matchScore }}</template>
        </p>
      </div>

      <div class="audit-package">
        <span>包装 {{ form.depth }}×{{ form.width }}×{{ form.height }} mm · {{ form.weight }} g</span>
        <span v-if="packageTouched" class="audit-tag">人工改过</span>
      </div>
    </div>

    <div v-if="open" class="audit-edit" tabindex="0" @paste="onPasteImages">
        <p class="audit-section">包装尺寸</p>
        <div class="audit-metrics">
          <label>长 <input v-model.number="form.depth" type="number" min="1" /> mm</label>
          <label>宽 <input v-model.number="form.width" type="number" min="1" /> mm</label>
          <label>高 <input v-model.number="form.height" type="number" min="1" /> mm</label>
          <label>重量 <input v-model.number="form.weight" type="number" min="1" /> g</label>
        </div>
        <p v-if="packageWeightHint" class="audit-warn">{{ packageWeightHint }}</p>

        <div class="audit-aspect">
          <span>合卡区分属性（双轴时建议用颜色，值已含「款式 · 尺码」）</span>
          <button type="button" :class="{ active: form.aspect === 'color' }" @click="form.aspect = 'color'">颜色/款式</button>
          <button type="button" :class="{ active: form.aspect === 'size' }" @click="form.aspect = 'size'">尺码</button>
        </div>

        <p class="audit-section">
          每个变体 = 一个 listing：自己的主图 + 副图（第 1 张主图，其余副图；每套至少 5 张）
        </p>
        <input
          ref="variantFileInput"
          type="file"
          accept="image/*"
          multiple
          hidden
          @change="onPickVariantImages"
        />
        <div
          v-for="variant in form.variants"
          :key="variant.id"
          class="audit-variant"
          :class="{ 'is-active': pasteTargetVariantId === variant.id }"
          @click="pasteTargetVariantId = variant.id"
        >
          <div class="audit-variant__head">
            <span>{{ variant.sku }}</span>
            <span :class="{ 'is-bad': variant.images.length < 5 }">
              {{ variant.images.length }}/5 · 主图+副图
            </span>
          </div>
          <div class="audit-variant__gallery">
            <div
              v-for="(url, index) in variant.images"
              :key="`${variant.id}-${url}-${index}`"
              class="audit-thumb"
              draggable="true"
              @dragstart="variantDrag = { variantId: variant.id, index }"
              @dragover.prevent
              @drop="
                moveVariantImage(
                  variant.id,
                  variantDrag?.variantId === variant.id ? (variantDrag?.index ?? index) : index,
                  index,
                );
                variantDrag = null;
              "
            >
              <button type="button" :class="{ active: url === previewUrl }" @click="previewUrl = url">
                <img :src="url" alt="" />
              </button>
              <span v-if="index === 0" class="audit-thumb__badge">主</span>
              <span v-else class="audit-thumb__badge audit-thumb__badge--sec">副</span>
              <button type="button" class="audit-thumb__remove" title="删除" @click="removeVariantImage(variant.id, index)">×</button>
            </div>
            <div class="audit-variant__add">
              <button type="button" :disabled="uploading || variant.images.length >= 15" @click="openVariantUpload(variant.id)">
                {{ uploading && uploadTargetVariantId === variant.id ? "上传中…" : "上传主图/副图" }}
              </button>
              <span class="audit-muted">点此块后可粘贴图片</span>
            </div>
          </div>
          <p v-if="!variant.images.length" class="audit-muted">该 listing 还没有图片</p>
          <div class="audit-variant__title">
            <label>标题 <input v-model="variant.title" type="text" /></label>
          </div>
          <div class="audit-variant__fields">
            <label>颜色/款式 <input v-model="variant.color" type="text" placeholder="如 棕色小熊" /></label>
            <label>尺码 <input v-model="variant.size" type="text" placeholder="如 S(33×30×32CM)" /></label>
            <label>价格 <input v-model.number="variant.price" type="number" min="0" step="0.01" /></label>
            <label>数量 <input v-model.number="variant.quantity" type="number" min="0" /></label>
          </div>
        </div>
        <p v-if="!form.variants.length" class="audit-muted">没有变体，无法改价。</p>
    </div>

    <footer>
      <button type="button" class="btn-text" @click="open = !open">
        {{ open ? "收起编辑" : "编辑图片 / 颜色 / 尺寸 / 价格" }}
      </button>
      <div class="audit-actions">
        <button v-if="isNeedsFix" type="button" class="btn-text" :disabled="busy" @click="emit('openSourcing')">
          去换供应商
        </button>
        <button type="button" class="btn-ghost" :disabled="busy || uploading" @click="emit('save', payload())">
          保存
        </button>
        <button type="button" class="btn-ghost" :disabled="busy || uploading" @click="emit('reject')">驳回</button>
        <button
          type="button"
          class="btn-primary"
          :disabled="busy || uploading || (!isNeedsFix && !imageOk)"
          @click="onPrimary"
        >
          {{
            isNeedsFix
              ? "保存并重新生成"
              : imageOk
                ? "保存并通过推送"
                : "每个 listing 需 ≥5 张图"
          }}
        </button>
      </div>
    </footer>
    <Teleport to="body">
      <div v-if="previewUrl" class="audit-lightbox" @click="previewUrl = null">
        <div class="audit-lightbox__panel" @click.stop>
          <button type="button" class="audit-lightbox__close" @click="previewUrl = null">关闭</button>
          <img :src="previewUrl" alt="" />
        </div>
      </div>
    </Teleport>
  </article>
</template>

<style scoped>
.audit-card {
  background: var(--erp-surface, #fff);
  border: 1px solid var(--erp-border, #e5e7eb);
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.06);
  padding: 20px 24px;
  display: grid;
  gap: 16px;
}
.audit-card.is-fix {
  border-color: #f59e0b;
  background: #fffbeb;
}
.audit-timeline {
  display: flex;
  gap: 8px 16px;
  list-style: none;
  margin: 0;
  padding: 0;
  flex-wrap: wrap;
}
.audit-timeline li {
  font-size: 12px;
  color: #9ca3af;
}
.audit-timeline li.is-done { color: #10b981; }
.audit-timeline li.is-current { color: #f59e0b; font-weight: 650; }
.audit-timeline li.is-error { color: #ef4444; font-weight: 650; }
.audit-alert {
  margin: 0;
  color: #b45309;
  line-height: 1.5;
}
.audit-head {
  display: grid;
  grid-template-columns: 80px minmax(0, 1fr) auto;
  gap: 16px;
  align-items: start;
}
.audit-cover {
  width: 80px;
  height: 80px;
  object-fit: cover;
  border-radius: 8px;
  background: #f3f4f6;
}
.audit-cover--empty {
  display: grid;
  place-items: center;
  color: #9ca3af;
  font-size: 12px;
}
.audit-head__main h3 {
  margin: 0 0 6px;
  font-size: 16px;
  line-height: 1.45;
}
.audit-title-link {
  color: inherit;
  text-decoration: none;
}
.audit-title-link:hover {
  color: #2563eb;
  text-decoration: underline;
}
.audit-head__main p {
  margin: 0;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  color: #4b5563;
  font-size: 13px;
}
.audit-muted {
  color: #6b7280 !important;
  margin-top: 4px !important;
}
.audit-warn {
  color: #b42318;
  font-size: 12px;
  margin: 6px 0 0;
}
.is-bad { color: #ef4444; }
.audit-package {
  display: grid;
  justify-items: end;
  gap: 6px;
  font-size: 13px;
  color: #374151;
  text-align: right;
}
.audit-tag {
  background: #fffbeb;
  color: #b45309;
  border: 1px solid #fcd34d;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 12px;
}
.audit-section {
  grid-column: 1 / -1;
  margin: 4px 0 0;
  font-size: 13px;
  font-weight: 650;
  color: #111827;
}
.audit-gallery {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.audit-gallery span {
  font-size: 12px;
  color: #6b7280;
  margin-right: 2px;
}
.audit-gallery button {
  width: 48px;
  height: 48px;
  padding: 0;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #e5e7eb;
  background: #fff;
  cursor: pointer;
}
.audit-thumb {
  position: relative;
}
.audit-thumb__remove {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 16px !important;
  height: 16px !important;
  border-radius: 999px !important;
  background: #111827 !important;
  color: #fff;
  font-size: 12px;
  line-height: 14px;
}
.audit-image-add {
  display: flex;
  align-items: center;
}
.audit-image-add button {
  width: auto !important;
  height: 48px !important;
  padding: 0 12px !important;
  border: 1px dashed #d1d5db !important;
  background: #fff !important;
  color: #374151;
}
.audit-gallery img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.audit-gallery button.active {
  border-color: #2563eb;
}
.audit-lightbox {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(17, 24, 39, 0.55);
}
.audit-lightbox__panel {
  display: grid;
  gap: 8px;
  justify-items: end;
  max-width: min(720px, 100%);
}
.audit-lightbox__close {
  border: 0;
  background: transparent;
  color: #fff;
  cursor: pointer;
  padding: 0;
}
.audit-lightbox img {
  width: auto;
  max-width: min(720px, calc(100vw - 48px));
  max-height: min(70vh, 640px);
  object-fit: contain;
  border-radius: 8px;
  background: #fff;
}
.audit-edit {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  padding: 16px;
  border-radius: 10px;
  background: #f9fafb;
}
.audit-edit label,
.audit-variant label {
  display: grid;
  gap: 4px;
  font-size: 12px;
  color: #6b7280;
}
.audit-edit input,
.audit-variant input {
  width: 100%;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 8px 10px;
  background: #fff;
  box-sizing: border-box;
}
.audit-metrics {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 160px));
  gap: 8px;
}
.audit-aspect {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #374151;
}
.audit-aspect button {
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 999px;
  padding: 4px 12px;
  cursor: pointer;
}
.audit-aspect button.active {
  background: #111827;
  border-color: #111827;
  color: #fff;
}
.audit-variant {
  grid-column: 1 / -1;
  display: grid;
  gap: 10px;
  align-items: start;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
}
.audit-variant.is-active {
  border-color: #111827;
  box-shadow: 0 0 0 1px #111827;
}
.audit-variant__head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: #6b7280;
}
.audit-variant__head .is-bad {
  color: #b91c1c;
  font-weight: 600;
}
.audit-variant__gallery {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: flex-start;
}
.audit-variant__add {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 120px;
}
.audit-variant__add button {
  font-size: 12px;
  padding: 8px 10px;
  border: 1px dashed #d1d5db;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
}
.audit-variant__add button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.audit-thumb__badge {
  position: absolute;
  left: 2px;
  bottom: 2px;
  font-size: 10px;
  line-height: 1;
  padding: 2px 4px;
  border-radius: 4px;
  background: #111827;
  color: #fff;
  pointer-events: none;
}
.audit-thumb__badge--sec {
  background: #6b7280;
}
.audit-variant__fields {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1.2fr) 110px 90px;
  gap: 8px;
}
.audit-variant__title {
  display: grid;
  gap: 4px;
}
.audit-variant__title input {
  width: 100%;
}
.audit-variant img,
.audit-variant__ph {
  width: 56px;
  height: 56px;
  object-fit: cover;
  border-radius: 6px;
  background: #e5e7eb;
}
footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.audit-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.btn-primary,
.btn-ghost,
.btn-text {
  border-radius: 8px;
  padding: 8px 14px;
  cursor: pointer;
}
.btn-primary {
  border: 0;
  background: #2563eb;
  color: #fff;
}
.btn-primary:disabled {
  background: #9ca3af;
  cursor: not-allowed;
}
.btn-ghost,
.btn-text {
  border: 1px solid #e5e7eb;
  background: #fff;
  color: #374151;
}
.btn-ghost:disabled,
.btn-text:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

@media (max-width: 860px) {
  .audit-head {
    grid-template-columns: 80px minmax(0, 1fr);
  }
  .audit-package {
    grid-column: 1 / -1;
    justify-items: start;
    text-align: left;
  }
  .audit-edit,
  .audit-variant {
    grid-template-columns: 1fr;
  }
}
</style>

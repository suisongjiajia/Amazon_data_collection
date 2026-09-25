import type { OzonPublishTask, ProductEdit } from "../types/ozon-workflow";

export function resolveCurrencyCode(
  attributes?: Record<string, string> | null,
  fallback = "CNY",
): string {
  const raw = String(attributes?.currency_code || "").trim().toUpperCase();
  return raw || fallback;
}

export function formatMoney(
  price: number | string | null | undefined,
  currencyCode = "CNY",
): string {
  if (price == null || price === "") return "-";
  const code = (currencyCode || "CNY").toUpperCase();
  const symbol = code === "RUB" ? "₽" : code === "CNY" ? "¥" : `${code} `;
  return `${price}${symbol === `${code} ` ? ` ${code}` : symbol}`;
}

export function resolveEditImage(edit: Pick<ProductEdit, "images" | "family_main_image_url" | "variants">): string | null {
  const fromImages = edit.images?.find((url) => typeof url === "string" && url.trim());
  if (fromImages) return fromImages;
  if (edit.family_main_image_url) return edit.family_main_image_url;
  const fromVariant = edit.variants?.find((item) => item.image_url)?.image_url;
  return fromVariant || null;
}

export function resolveEditSubtitle(edit: ProductEdit): string {
  const parts: string[] = [];
  if (edit.family_title && edit.family_title !== edit.title) {
    parts.push(`源品 ${edit.family_title}`);
  }
  const prices = (edit.variants || [])
    .map((item) => item.price)
    .filter((price): price is number => typeof price === "number" && Number.isFinite(price));
  if (prices.length) {
    const code = resolveCurrencyCode(edit.attributes);
    const min = Math.min(...prices.map(Number));
    const max = Math.max(...prices.map(Number));
    parts.push(min === max ? formatMoney(min, code) : `${formatMoney(min, code)}–${formatMoney(max, code)}`);
  }
  parts.push(`${edit.variants?.length || 0} SKU`);
  return parts.join(" · ");
}

export function resolvePublishTaskImage(task: OzonPublishTask): string | null {
  const images = task.edit_images;
  if (Array.isArray(images)) {
    const first = images.find((url) => typeof url === "string" && url.trim());
    if (first) return first;
  }
  return task.main_image_url || null;
}

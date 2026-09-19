const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/$/, "");

function buildApiUrl(path: string): string {
  if (/^https?:\/\//.test(path)) {
    return path;
  }

  if (!API_BASE_URL) {
    return path;
  }

  if (path.startsWith("/")) {
    return `${API_BASE_URL}${path}`;
  }

  return `${API_BASE_URL}/${path}`;
}

export async function apiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const headers: HeadersInit = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(init?.headers ?? {}),
  };

  const response = await fetch(buildApiUrl(url), {
    ...init,
    headers,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item: { msg?: string }) => item?.msg || String(item)).join("; ")
          : `Request failed: ${response.status}`;
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export async function apiUploadImages(
  files: File[],
  options?: { sku?: string },
): Promise<{ images: string[]; count: number; errors?: Array<{ file?: string; error: string }> }> {
  const form = new FormData();
  form.append("sku", options?.sku || "item");
  for (const file of files) {
    form.append("files", file);
  }
  return apiRequest("/api/product-edits/upload-images", {
    method: "POST",
    body: form,
  });
}

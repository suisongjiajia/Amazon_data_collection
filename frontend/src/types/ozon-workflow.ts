export type OzonViewKey = "ozon-collect" | "sourcing" | "product-edit" | "review" | "ozon-publish";

export interface OzonViewDefinition {
  key: OzonViewKey;
  label: string;
  meta: string;
}

export interface OzonCollectionTask {
  id: number;
  task_no: string;
  strategy_type: string;
  strategy_params?: Record<string, unknown> | null;
  status: string;
  total_count: number;
  success_count: number;
  fail_count: number;
  created_at: string;
  finished_at?: string | null;
}

export interface OzonProductFamily {
  id: number;
  external_id?: string | null;
  title?: string | null;
  brand?: string | null;
  main_image_url?: string | null;
  sales_rank?: number | null;
  category_name?: string | null;
  hot_score?: number | null;
  price_text?: string | null;
  variant_count: number;
  variants: Array<{
    id: number;
    price_text?: string | null;
    title?: string | null;
    size?: string | null;
    variant_attributes?: Record<string, string> | null;
  }>;
}

export interface OzonProductDetail {
  id: number;
  external_id?: string | null;
  sku?: string | null;
  title?: string | null;
  brand?: string | null;
  source_url?: string | null;
  main_image_url?: string | null;
  rating?: string | null;
  review_count?: string | null;
  category_name?: string | null;
  sales_rank?: number | null;
  hot_score?: number | null;
  price_text?: string | null;
  description?: string | null;
  images?: string[];
  size?: string | null;
  weight?: string | null;
  attributes?: Record<string, string>;
  variant_count?: number;
  variants?: OzonProductFamily["variants"];
}

export interface SupplierCandidateRawPayload {
  monthSold?: string;
  repurchaseRate?: string;
  compositeScore?: string;
  companyCity?: string;
  companyProvince?: string;
  offerPublishTime?: string;
  offerId?: string;
  title?: string;
  translateTitle?: string;
  price?: string;
  normalizationScore?: string;
  [key: string]: unknown;
}

export interface SupplierCandidate {
  id: number;
  raw_product_family_id: number;
  supplier_name?: string | null;
  shop_name?: string | null;
  product_title?: string | null;
  product_url?: string | null;
  image_url?: string | null;
  price_text?: string | null;
  min_order_qty?: string | null;
  match_score?: number | null;
  status: string;
  raw_payload?: SupplierCandidateRawPayload | null;
}

export interface SourcingDetail {
  product: OzonProductDetail;
  candidates: SupplierCandidate[];
}

export interface AiProductEditSuggestion {
  title: string;
  description: string;
  bullet_points: string[];
  images: string[];
  attributes: Record<string, string>;
  variants: Array<{
    sku: string;
    title: string;
    price: number | null;
    quantity: number;
  }>;
  listing_notes?: string;
}

export interface AiProductEditResponse {
  context: Record<string, unknown>;
  suggestion: AiProductEditSuggestion;
}

export interface ProductEdit {
  id: number;
  raw_product_family_id: number;
  title: string;
  description?: string | null;
  bullet_points?: string[] | null;
  images?: string[] | null;
  attributes?: Record<string, string> | null;
  status: string;
  family_title?: string | null;
  family_main_image_url?: string | null;
  variants: ProductEditVariant[];
}

export interface ProductEditVariant {
  id: number;
  sku: string;
  title?: string | null;
  price?: number | null;
  quantity: number;
  image_url?: string | null;
}

export interface OzonPublishTask {
  id: number;
  task_no: string;
  edit_id: number;
  shop_name?: string | null;
  status: string;
  total_count: number;
  success_count: number;
  fail_count: number;
  created_at: string;
  items: Array<{
    id: number;
    seller_sku: string;
    status: string;
    ozon_product_id?: string | null;
  }>;
}

export interface OzonWorkflowState {
  ozonTasks: OzonCollectionTask[];
  ozonProducts: OzonProductFamily[];
  candidates: SupplierCandidate[];
  edits: ProductEdit[];
  publishTasks: OzonPublishTask[];
}

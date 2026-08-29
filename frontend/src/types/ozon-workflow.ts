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
  source_url?: string | null;
  main_image_url?: string | null;
  sales_rank?: number | null;
  category_id?: string | null;
  type_id?: string | null;
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
  description_category_id?: string | null;
  type_id?: string | null;
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
  pricing?: Record<string, unknown> | null;
  image_rehost?: { images?: string[]; errors?: Array<{ url: string; error: string }>; count?: number } | null;
}

export interface ListingIssue {
  code: string;
  severity: "error" | "warning" | string;
  message: string;
}

export interface ListingSummary {
  title?: string | null;
  description?: string | null;
  bullet_points?: string[];
  images?: string[];
  description_category_id?: string | number | null;
  type_id?: string | number | null;
  fulfillment?: string | null;
  brand_mode?: string | null;
  attributes?: Record<string, string | number | null>;
  variants?: Array<{
    sku?: string | null;
    title?: string | null;
    price?: number | null;
    quantity?: number | null;
    image_url?: string | null;
  }>;
  payload_item_count?: number;
}

export interface ListingPreview {
  ok: boolean;
  issues: ListingIssue[];
  summary: ListingSummary;
  payload_items: Record<string, unknown>[];
  stock_items: Record<string, unknown>[];
  build_error?: string | null;
  edit_id?: number;
  edit_status?: string;
  listing_built_at?: string | null;
  saved?: boolean;
  saved_listing?: {
    summary?: ListingSummary;
    payload_items?: Record<string, unknown>[];
    stock_items?: Record<string, unknown>[];
    issues?: ListingIssue[];
  } | null;
}

export interface ProductEdit {
  id: number;
  raw_product_family_id: number;
  title: string;
  description?: string | null;
  bullet_points?: string[] | null;
  images?: string[] | null;
  attributes?: Record<string, string> | null;
  listing_payload?: ListingPreview["saved_listing"];
  listing_built_at?: string | null;
  status: string;
  family_title?: string | null;
  family_main_image_url?: string | null;
  family_external_id?: string | null;
  category_name?: string | null;
  sales_rank?: number | null;
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
  edit_title?: string | null;
  edit_status?: string | null;
  edit_images?: string[] | null;
  family_title?: string | null;
  family_external_id?: string | null;
  main_image_url?: string | null;
  shop_name?: string | null;
  status: string;
  total_count: number;
  success_count: number;
  fail_count: number;
  error_message?: string | null;
  created_at: string;
  finished_at?: string | null;
  items: Array<{
    id: number;
    seller_sku: string;
    status: string;
    ozon_product_id?: string | null;
    error_code?: string | null;
    error_message?: string | null;
    submission_payload?: Record<string, unknown> | null;
    response_payload?: Record<string, unknown> | null;
  }>;
}

export interface OzonWorkflowState {
  ozonTasks: OzonCollectionTask[];
  ozonProducts: OzonProductFamily[];
  candidates: SupplierCandidate[];
  edits: ProductEdit[];
  publishTasks: OzonPublishTask[];
}

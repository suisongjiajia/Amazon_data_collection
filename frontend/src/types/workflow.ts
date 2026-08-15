export type ViewKey = "intake" | "selections" | "listing" | "publish";
export type IntakeTab = "families" | "tasks";
export type ValidationLevel = "pass" | "warn" | "fail";

export interface ViewDefinition {
  key: ViewKey;
  label: string;
  meta: string;
}

export interface ValidationItem {
  label: string;
  detail: string;
  level: ValidationLevel;
}

export interface CollectionTask {
  id: number;
  task_no: string;
  source_url: string;
  marketplace?: string | null;
  status: string;
  total_count: number;
  success_count: number;
  fail_count: number;
  error_message?: string | null;
  created_at: string;
  finished_at?: string | null;
}

export interface RawProductVariant {
  id: number;
  family_id: number;
  asin?: string | null;
  parent_asin?: string | null;
  source_url?: string | null;
  title?: string | null;
  price_text?: string | null;
  main_image_url?: string | null;
  size?: string | null;
  color?: string | null;
  variant_attributes?: Record<string, string> | null;
  snapshot_time?: string | null;
  raw_payload?: Record<string, unknown> | null;
}

export interface RawProductFamily {
  id: number;
  task_id?: number | null;
  family_key: string;
  marketplace?: string | null;
  source_url?: string | null;
  title?: string | null;
  brand?: string | null;
  rating?: string | null;
  review_count?: string | null;
  main_image_url?: string | null;
  variant_dimensions?: string[] | null;
  bullet_points?: string[] | null;
  selection_id?: number | null;
  selection_status?: string | null;
  selection_score?: number | null;
  selection_owner?: string | null;
  selection_remark?: string | null;
  product_master_id?: number | null;
  variant_count: number;
  variants: RawProductVariant[];
}

export interface Selection {
  id: number;
  raw_product_family_id: number;
  selection_status: string;
  score?: number | null;
  owner?: string | null;
  remark?: string | null;
  family_key?: string | null;
  family_parent_asin?: string | null;
  family_marketplace?: string | null;
  family_source_url?: string | null;
  family_title?: string | null;
  family_brand?: string | null;
  family_rating?: string | null;
  family_review_count?: string | null;
  family_main_image_url?: string | null;
  variant_dimensions?: string[] | null;
  family_variant_count: number;
  selected_variant_count: number;
  variants: RawProductVariant[];
}

export interface ProductVariant {
  id: number;
  raw_product_variant_id?: number | null;
  sku: string;
  variant_key?: string | null;
  color?: string | null;
  size?: string | null;
  cost_price?: number | null;
  stock_qty: number;
  raw_asin?: string | null;
  raw_price_text?: string | null;
  variant_attributes?: Record<string, string> | null;
}

export interface ProductMaster {
  id: number;
  selection_id: number;
  raw_product_family_id: number;
  family_title?: string | null;
  family_main_image_url?: string | null;
  variant_dimensions?: string[] | null;
  spu_code: string;
  product_name: string;
  brand?: string | null;
  target_marketplace?: string | null;
  status: string;
  default_cost?: number | null;
  base_attributes?: Record<string, unknown> | null;
  variant_count: number;
  variants: ProductVariant[];
}

export interface ListingDraftVariant {
  id: number;
  variant_id: number;
  seller_sku: string;
  price?: number | null;
  quantity: number;
  fulfillment_channel: string;
  external_product_id?: string | null;
  external_product_id_type?: string | null;
  variant_key?: string | null;
  color?: string | null;
  size?: string | null;
}

export interface ListingDraft {
  id: number;
  product_master_id: number;
  product_name: string;
  spu_code: string;
  marketplace: string;
  shop_name: string;
  status: string;
  title: string;
  bullet_points?: string[] | null;
  description?: string | null;
  search_terms?: string | null;
  attributes?: Record<string, unknown> | null;
  current_version_no: number;
  variants: ListingDraftVariant[];
}

export interface PublishTaskItem {
  id: number;
  draft_id: number;
  variant_id: number;
  seller_sku: string;
  amazon_submission_id?: string | null;
  status: string;
  error_message?: string | null;
  issues?: Array<{ field: string; message: string }> | null;
}

export interface PublishTask {
  id: number;
  task_no: string;
  shop_name?: string | null;
  marketplace?: string | null;
  submit_type: string;
  status: string;
  total_count: number;
  success_count: number;
  fail_count: number;
  created_at: string;
  finished_at?: string | null;
  items: PublishTaskItem[];
}

export interface ListingLive {
  id: number;
  seller_sku: string;
  marketplace: string;
  shop_name: string;
  listing_status: string;
  asin?: string | null;
  parent_asin?: string | null;
  price?: number | null;
  quantity: number;
  updated_at: string;
}

export interface WorkflowFilters {
  familyQuery: string;
  familyMarketplace: string;
  selectionQuery: string;
  listingQuery: string;
}

export interface WorkflowState {
  collections: CollectionTask[];
  families: RawProductFamily[];
  selections: Selection[];
  products: ProductMaster[];
  drafts: ListingDraft[];
  publishTasks: PublishTask[];
  liveListings: ListingLive[];
}

export interface WorkflowUiState {
  activeView: ViewKey;
  intakeTab: IntakeTab;
  loading: boolean;
  notice: string;
  error: string;
  collectionUrl: string;
  defaultShopName: string;
  defaultMarketplace: string;
  selectedDraftId: number | null;
  selectedFamilyId: number | null;
  selectedSelectionId: number | null;
  expandedVariantId: number | null;
}

export interface CollectionListRow {
  task: CollectionTask;
  title: string;
  image: string;
  sourceUrl: string;
  marketplace?: string | null;
}

export interface DraftEditorState {
  title: string;
  bulletText: string;
  description: string;
  searchTerms: string;
  status: string;
}

export interface DraftStats {
  totalSkuCount: number;
  pricedSkuCount: number;
  stockedSkuCount: number;
}

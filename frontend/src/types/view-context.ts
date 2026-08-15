import type {
  ListingDraft,
  ListingDraftVariant,
  RawProductFamily,
  RawProductVariant,
  Selection,
} from "./workflow";

export interface SelectOption {
  value: string;
  label: string;
}

export interface WorkflowActions {
  refreshAll: () => Promise<void>;
  submitCollection: () => Promise<void>;
  addToSelection: (familyId: number) => Promise<void>;
  saveSelectionScope: (selectionId: number) => Promise<void>;
  createProduct: (selectionId: number) => Promise<void>;
  createDraft: (productMasterId: number) => Promise<void>;
  saveDraft: () => Promise<void>;
  saveDraftVariant: (variant: ListingDraftVariant) => Promise<void>;
  publishDraft: (draftId: number) => Promise<void>;
  openFamilyDetail: (familyId: number) => void;
  closeFamilyDetail: () => void;
  openSelectionDetail: (selectionId: number) => void;
  closeSelectionDetail: () => void;
  openDraftEditor: (draftId: number) => void;
  openListingForProduct: (productId: number) => void;
  toggleVariantDetail: (variantId: number) => void;
  toggleVariantInScope: (selectionId: number, variantId: number) => void;
}

export interface WorkflowHelpers {
  variantPreview: (
    variant:
      | RawProductVariant
      | ListingDraftVariant
      | { variant_attributes?: Record<string, string> | null; color?: string | null; size?: string | null },
  ) => string;
  selectionCoverage: (selection: Selection) => string;
  familyLeadPrice: (family: RawProductFamily) => string;
  selectionLeadPrice: (selection: Selection) => string;
  formatDate: (value?: string | null) => string;
  formatNumber: (value?: number | null) => string;
  getStatusLabel: (status?: string | null) => string;
  getMarketplaceLabel: (value?: string | null) => string;
  getFamilyImage: (family: RawProductFamily | Selection) => string;
  getFamilyStatusLabel: (family: RawProductFamily) => string;
  getFamilyStatusKey: (family: RawProductFamily) => string;
  getDraftImage: (draft: ListingDraft) => string;
  truncateUrl: (value?: string | null, maxLength?: number) => string;
  getDraftsForProduct: (productId: number) => ListingDraft[];
  isVariantExpanded: (variantId: number) => boolean;
  isVariantSelected: (selectionId: number, variantId: number) => boolean;
  getVariantTitle: (variant: RawProductVariant, family?: RawProductFamily | null) => string;
  getVariantImage: (variant: RawProductVariant) => string;
  getVariantBulletPoints: (variant: RawProductVariant, family?: RawProductFamily | null) => string[];
  getVariantAttributeEntries: (variant: RawProductVariant) => Array<[string, string]>;
}

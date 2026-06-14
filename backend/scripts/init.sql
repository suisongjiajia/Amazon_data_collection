CREATE TABLE IF NOT EXISTS collection_task (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    task_no         VARCHAR(64)     NOT NULL,
    source_type     VARCHAR(32)     NOT NULL DEFAULT 'url',
    source_url      VARCHAR(1024)   NOT NULL,
    marketplace     VARCHAR(255)    NULL,
    status          VARCHAR(32)     NOT NULL,
    total_count     INT             NOT NULL DEFAULT 0,
    success_count   INT             NOT NULL DEFAULT 0,
    fail_count      INT             NOT NULL DEFAULT 0,
    error_message   TEXT            NULL,
    started_at      DATETIME        NULL,
    finished_at     DATETIME        NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_collection_task_no (task_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS raw_product_family (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    task_id             BIGINT UNSIGNED NULL,
    family_key          VARCHAR(64)     NOT NULL,
    parent_asin         VARCHAR(32)     NULL,
    marketplace         VARCHAR(255)    NULL,
    source_url          VARCHAR(1024)   NULL,
    title               VARCHAR(1024)   NULL,
    brand               VARCHAR(255)    NULL,
    rating              VARCHAR(64)     NULL,
    review_count        VARCHAR(64)     NULL,
    main_image_url      VARCHAR(1024)   NULL,
    variant_dimensions  JSON            NULL,
    bullet_points       JSON            NULL,
    raw_payload         JSON            NULL,
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_raw_product_family_key (family_key),
    CONSTRAINT fk_raw_product_family_task FOREIGN KEY (task_id) REFERENCES collection_task (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS raw_product_variant (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    family_id           BIGINT UNSIGNED NOT NULL,
    asin                VARCHAR(32)     NOT NULL,
    parent_asin         VARCHAR(32)     NULL,
    source_url          VARCHAR(1024)   NULL,
    title               VARCHAR(1024)   NULL,
    price_text          VARCHAR(128)    NULL,
    main_image_url      VARCHAR(1024)   NULL,
    size                VARCHAR(128)    NULL,
    color               VARCHAR(128)    NULL,
    variant_attributes  JSON            NULL,
    raw_payload         JSON            NULL,
    snapshot_time       DATETIME        NULL,
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_raw_product_variant_asin (asin),
    CONSTRAINT fk_raw_product_variant_family FOREIGN KEY (family_id) REFERENCES raw_product_family (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS selection_pool (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    raw_product_family_id BIGINT UNSIGNED NOT NULL,
    selection_status      VARCHAR(32)     NOT NULL DEFAULT 'reviewing',
    score                 DECIMAL(10, 2)  NULL,
    owner                 VARCHAR(128)    NULL,
    remark                TEXT            NULL,
    created_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_selection_family (raw_product_family_id),
    CONSTRAINT fk_selection_family FOREIGN KEY (raw_product_family_id) REFERENCES raw_product_family (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS selection_variant_scope (
    id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    selection_id           BIGINT UNSIGNED NOT NULL,
    raw_product_variant_id BIGINT UNSIGNED NOT NULL,
    created_at             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_selection_variant_scope (selection_id, raw_product_variant_id),
    CONSTRAINT fk_selection_variant_scope_selection FOREIGN KEY (selection_id) REFERENCES selection_pool (id) ON DELETE CASCADE,
    CONSTRAINT fk_selection_variant_scope_variant FOREIGN KEY (raw_product_variant_id) REFERENCES raw_product_variant (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS product_master (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    selection_id        BIGINT UNSIGNED NOT NULL,
    spu_code            VARCHAR(64)     NOT NULL,
    product_name        VARCHAR(512)    NOT NULL,
    brand               VARCHAR(255)    NULL,
    target_marketplace  VARCHAR(255)    NULL,
    status              VARCHAR(32)     NOT NULL DEFAULT 'draft',
    default_cost        DECIMAL(10, 2)  NULL,
    base_attributes     JSON            NULL,
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_product_master_selection (selection_id),
    UNIQUE KEY uk_product_master_spu_code (spu_code),
    CONSTRAINT fk_product_master_selection FOREIGN KEY (selection_id) REFERENCES selection_pool (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS product_variant (
    id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    product_master_id      BIGINT UNSIGNED NOT NULL,
    raw_product_variant_id BIGINT UNSIGNED NULL,
    sku                    VARCHAR(64)     NOT NULL,
    variant_key            VARCHAR(255)    NULL,
    color                  VARCHAR(128)    NULL,
    size                   VARCHAR(128)    NULL,
    cost_price             DECIMAL(10, 2)  NULL,
    stock_qty              INT             NOT NULL DEFAULT 0,
    variant_attributes     JSON            NULL,
    created_at             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_product_variant_sku (sku),
    CONSTRAINT fk_product_variant_master FOREIGN KEY (product_master_id) REFERENCES product_master (id),
    CONSTRAINT fk_product_variant_raw_variant FOREIGN KEY (raw_product_variant_id) REFERENCES raw_product_variant (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS listing_draft (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    product_master_id   BIGINT UNSIGNED NOT NULL,
    marketplace         VARCHAR(255)    NOT NULL,
    shop_name           VARCHAR(255)    NOT NULL,
    status              VARCHAR(32)     NOT NULL DEFAULT 'draft',
    title               VARCHAR(1024)   NOT NULL,
    bullet_points       JSON            NULL,
    description         TEXT            NULL,
    search_terms        TEXT            NULL,
    attributes          JSON            NULL,
    current_version_no  INT             NOT NULL DEFAULT 1,
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_listing_draft_master FOREIGN KEY (product_master_id) REFERENCES product_master (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS listing_draft_variant (
    id                       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    draft_id                 BIGINT UNSIGNED NOT NULL,
    variant_id               BIGINT UNSIGNED NOT NULL,
    seller_sku               VARCHAR(64)     NOT NULL,
    price                    DECIMAL(10, 2)  NULL,
    quantity                 INT             NOT NULL DEFAULT 0,
    fulfillment_channel      VARCHAR(32)     NOT NULL DEFAULT 'FBM',
    external_product_id      VARCHAR(64)     NULL,
    external_product_id_type VARCHAR(32)     NULL,
    payload                  JSON            NULL,
    created_at               DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_listing_draft_variant_pair (draft_id, variant_id),
    CONSTRAINT fk_listing_draft_variant_draft FOREIGN KEY (draft_id) REFERENCES listing_draft (id),
    CONSTRAINT fk_listing_draft_variant_variant FOREIGN KEY (variant_id) REFERENCES product_variant (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS listing_draft_version (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    draft_id            BIGINT UNSIGNED NOT NULL,
    version_no          INT             NOT NULL,
    title               VARCHAR(1024)   NOT NULL,
    bullet_points       JSON            NULL,
    description         TEXT            NULL,
    search_terms        TEXT            NULL,
    attributes          JSON            NULL,
    change_note         VARCHAR(255)    NULL,
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_listing_draft_version (draft_id, version_no),
    CONSTRAINT fk_listing_draft_version_draft FOREIGN KEY (draft_id) REFERENCES listing_draft (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS publish_task (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    task_no             VARCHAR(64)     NOT NULL,
    shop_name           VARCHAR(255)    NULL,
    marketplace         VARCHAR(255)    NULL,
    submit_type         VARCHAR(32)     NOT NULL DEFAULT 'simulation',
    status              VARCHAR(32)     NOT NULL,
    total_count         INT             NOT NULL DEFAULT 0,
    success_count       INT             NOT NULL DEFAULT 0,
    fail_count          INT             NOT NULL DEFAULT 0,
    error_message       TEXT            NULL,
    submitted_at        DATETIME        NULL,
    finished_at         DATETIME        NULL,
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_publish_task_no (task_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS publish_task_item (
    id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    task_id                 BIGINT UNSIGNED NOT NULL,
    draft_id                BIGINT UNSIGNED NOT NULL,
    draft_variant_id        BIGINT UNSIGNED NOT NULL,
    variant_id              BIGINT UNSIGNED NOT NULL,
    seller_sku              VARCHAR(64)     NOT NULL,
    amazon_submission_id    VARCHAR(128)    NULL,
    status                  VARCHAR(32)     NOT NULL,
    error_code              VARCHAR(64)     NULL,
    error_message           TEXT            NULL,
    issues                  JSON            NULL,
    submission_payload      JSON            NULL,
    retried_times           INT             NOT NULL DEFAULT 0,
    created_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_publish_task_item_task FOREIGN KEY (task_id) REFERENCES publish_task (id),
    CONSTRAINT fk_publish_task_item_draft FOREIGN KEY (draft_id) REFERENCES listing_draft (id),
    CONSTRAINT fk_publish_task_item_draft_variant FOREIGN KEY (draft_variant_id) REFERENCES listing_draft_variant (id),
    CONSTRAINT fk_publish_task_item_variant FOREIGN KEY (variant_id) REFERENCES product_variant (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS listing_live (
    id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    publish_task_item_id BIGINT UNSIGNED NULL,
    draft_id             BIGINT UNSIGNED NOT NULL,
    variant_id           BIGINT UNSIGNED NOT NULL,
    shop_name            VARCHAR(255)    NOT NULL,
    marketplace          VARCHAR(255)    NOT NULL,
    seller_sku           VARCHAR(64)     NOT NULL,
    asin                 VARCHAR(32)     NULL,
    parent_asin          VARCHAR(32)     NULL,
    listing_status       VARCHAR(32)     NOT NULL,
    price                DECIMAL(10, 2)  NULL,
    quantity             INT             NOT NULL DEFAULT 0,
    live_payload         JSON            NULL,
    last_sync_at         DATETIME        NULL,
    created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_listing_live_shop_sku (shop_name, marketplace, seller_sku),
    CONSTRAINT fk_listing_live_publish_task_item FOREIGN KEY (publish_task_item_id) REFERENCES publish_task_item (id),
    CONSTRAINT fk_listing_live_draft FOREIGN KEY (draft_id) REFERENCES listing_draft (id),
    CONSTRAINT fk_listing_live_variant FOREIGN KEY (variant_id) REFERENCES product_variant (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

from __future__ import annotations

from db.connection import get_connection

# Ozon 工作流 + 采集底层表（Amazon/Ozon 采集共用 raw 表）
ACTIVE_TABLES = [
    "collection_task",
    "raw_product_family",
    "raw_product_variant",
    "sourcing_task",
    "supplier_candidate",
    "product_edit",
    "product_edit_variant",
    "review_record",
    "ozon_publish_task",
    "ozon_publish_item",
]

# 已废弃：Amazon 选品/草稿/发布链路及历史遗留表
LEGACY_TABLES = [
    "ozon_publish_item",
    "ozon_publish_task",
    "review_record",
    "product_edit_variant",
    "product_edit",
    "supplier_candidate",
    "sourcing_task",
    "listing_live",
    "publish_task_item",
    "publish_task",
    "listing_draft_version",
    "listing_draft_variant",
    "listing_draft",
    "product_variant",
    "product_master",
    "selection_variant_scope",
    "selection_pool",
    "raw_product_variant",
    "raw_product_family",
    "raw_product_snapshot",
    "products",
    "collection_task",
]

TABLE_COMMENTS: dict[str, str] = {
    "collection_task": "采集任务表，记录 Ozon/Amazon 链接或策略采集任务",
    "raw_product_family": "原始商品族表，按平台商品 ID 聚合标题、图片等",
    "raw_product_variant": "原始商品变体表，记录 SKU/价格等变体快照",
    "sourcing_task": "1688 以图搜货任务表",
    "supplier_candidate": "供应商候选货源表",
    "product_edit": "Ozon 商品编辑草稿表",
    "product_edit_variant": "Ozon 商品编辑变体表",
    "review_record": "商品审核记录表",
    "ozon_publish_task": "Ozon 发布任务表",
    "ozon_publish_item": "Ozon 发布明细表",
}

CREATE_TABLE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS collection_task (
        id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
        task_no         VARCHAR(64)     NOT NULL COMMENT '任务编号',
        source_type     VARCHAR(32)     NOT NULL DEFAULT 'url' COMMENT '来源类型',
        source_url      VARCHAR(1024)   NOT NULL COMMENT '采集链接',
        marketplace     VARCHAR(255)    NULL COMMENT '站点域名',
        platform        VARCHAR(32)     NOT NULL DEFAULT 'amazon' COMMENT '平台：amazon/ozon',
        strategy_type   VARCHAR(32)     NULL COMMENT '策略类型',
        strategy_params JSON            NULL COMMENT '策略参数',
        status          VARCHAR(32)     NOT NULL COMMENT '状态：running/completed/failed',
        total_count     INT             NOT NULL DEFAULT 0 COMMENT '总条数',
        success_count   INT             NOT NULL DEFAULT 0 COMMENT '成功条数',
        fail_count      INT             NOT NULL DEFAULT 0 COMMENT '失败条数',
        error_message   TEXT            NULL COMMENT '错误信息',
        started_at      DATETIME        NULL COMMENT '开始时间',
        finished_at     DATETIME        NULL COMMENT '结束时间',
        created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (id),
        UNIQUE KEY uk_collection_task_no (task_no),
        KEY idx_collection_task_status (status),
        KEY idx_collection_task_platform (platform),
        KEY idx_collection_task_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
      COMMENT='采集任务表'
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_product_family (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
        task_id             BIGINT UNSIGNED NULL COMMENT '关联采集任务',
        family_key          VARCHAR(64)     NOT NULL COMMENT '族唯一键',
        parent_asin         VARCHAR(32)     NULL COMMENT '父 ASIN（Amazon）',
        marketplace         VARCHAR(255)    NULL COMMENT '站点域名',
        platform            VARCHAR(32)     NOT NULL DEFAULT 'amazon' COMMENT '平台：amazon/ozon',
        external_id         VARCHAR(64)     NULL COMMENT '平台商品 ID',
        source_url          VARCHAR(1024)   NULL COMMENT '商品链接',
        title               VARCHAR(1024)   NULL COMMENT '标题',
        brand               VARCHAR(255)    NULL COMMENT '品牌',
        rating              VARCHAR(64)     NULL COMMENT '评分',
        review_count        VARCHAR(64)     NULL COMMENT '评论数',
        main_image_url      VARCHAR(1024)   NULL COMMENT '主图 URL',
        sales_rank          INT             NULL COMMENT '销量排名',
        category_id         VARCHAR(64)     NULL COMMENT '类目 ID / description_category_id',
        type_id             VARCHAR(64)     NULL COMMENT 'Ozon type_id',
        category_name       VARCHAR(255)    NULL COMMENT '类目名称',
        hot_score           DECIMAL(10, 2)  NULL COMMENT '热销分',
        variant_dimensions  JSON            NULL COMMENT '变体维度',
        bullet_points       JSON            NULL COMMENT '卖点列表',
        raw_payload         JSON            NULL COMMENT '原始 JSON',
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (id),
        UNIQUE KEY uk_raw_product_family_key (family_key),
        KEY idx_raw_product_family_task_id (task_id),
        KEY idx_raw_product_family_platform (platform),
        KEY idx_raw_product_family_marketplace (marketplace),
        KEY idx_raw_product_family_created_at (created_at),
        CONSTRAINT fk_raw_product_family_task FOREIGN KEY (task_id) REFERENCES collection_task (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
      COMMENT='原始商品族表'
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_product_variant (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
        family_id           BIGINT UNSIGNED NOT NULL COMMENT '所属商品族',
        asin                VARCHAR(32)     NOT NULL COMMENT 'ASIN 或变体唯一键',
        external_id         VARCHAR(64)     NULL COMMENT '平台 SKU/商品 ID',
        parent_asin         VARCHAR(32)     NULL COMMENT '父 ASIN',
        source_url          VARCHAR(1024)   NULL COMMENT '变体链接',
        title               VARCHAR(1024)   NULL COMMENT '变体标题',
        price_text          VARCHAR(128)    NULL COMMENT '价格文本',
        main_image_url      VARCHAR(1024)   NULL COMMENT '主图 URL',
        size                VARCHAR(128)    NULL COMMENT '尺码',
        color               VARCHAR(128)    NULL COMMENT '颜色',
        variant_attributes  JSON            NULL COMMENT '变体属性',
        raw_payload         JSON            NULL COMMENT '原始 JSON',
        snapshot_time       DATETIME        NULL COMMENT '快照时间',
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (id),
        UNIQUE KEY uk_raw_product_variant_asin (asin),
        KEY idx_raw_product_variant_family_id (family_id),
        KEY idx_raw_product_variant_created_at (created_at),
        CONSTRAINT fk_raw_product_variant_family FOREIGN KEY (family_id) REFERENCES raw_product_family (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
      COMMENT='原始商品变体表'
    """,
    """
    CREATE TABLE IF NOT EXISTS sourcing_task (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
        task_no             VARCHAR(64)     NOT NULL COMMENT '任务编号',
        raw_product_family_id BIGINT UNSIGNED NOT NULL COMMENT '关联 Ozon 商品',
        image_url           VARCHAR(1024)   NOT NULL COMMENT '搜图 URL',
        source_platform     VARCHAR(32)     NOT NULL DEFAULT '1688' COMMENT '货源平台',
        status              VARCHAR(32)     NOT NULL COMMENT '状态',
        candidate_count     INT             NOT NULL DEFAULT 0 COMMENT '候选数量',
        error_message       TEXT            NULL COMMENT '错误信息',
        started_at          DATETIME        NULL COMMENT '开始时间',
        finished_at         DATETIME        NULL COMMENT '结束时间',
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (id),
        UNIQUE KEY uk_sourcing_task_no (task_no),
        KEY idx_sourcing_task_family_id (raw_product_family_id),
        KEY idx_sourcing_task_status (status),
        CONSTRAINT fk_sourcing_task_family FOREIGN KEY (raw_product_family_id) REFERENCES raw_product_family (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
      COMMENT='1688 以图搜货任务表'
    """,
    """
    CREATE TABLE IF NOT EXISTS supplier_candidate (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
        sourcing_task_id    BIGINT UNSIGNED NULL COMMENT '关联搜货任务',
        raw_product_family_id BIGINT UNSIGNED NOT NULL COMMENT '关联 Ozon 商品',
        supplier_name       VARCHAR(255)    NULL COMMENT '供应商名称',
        shop_name           VARCHAR(255)    NULL COMMENT '店铺名称',
        product_title       VARCHAR(1024)   NULL COMMENT '货源标题',
        product_url         VARCHAR(1024)   NULL COMMENT '货源链接',
        image_url           VARCHAR(1024)   NULL COMMENT '货源图片',
        price_text          VARCHAR(128)    NULL COMMENT '价格文本',
        min_order_qty       VARCHAR(64)     NULL COMMENT '起订量',
        match_score         DECIMAL(5, 2)   NULL COMMENT '匹配分',
        status              VARCHAR(32)     NOT NULL DEFAULT 'candidate' COMMENT '状态',
        raw_payload         JSON            NULL COMMENT '原始 JSON',
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (id),
        KEY idx_supplier_candidate_family_id (raw_product_family_id),
        KEY idx_supplier_candidate_task_id (sourcing_task_id),
        KEY idx_supplier_candidate_status (status),
        CONSTRAINT fk_supplier_candidate_task FOREIGN KEY (sourcing_task_id) REFERENCES sourcing_task (id),
        CONSTRAINT fk_supplier_candidate_family FOREIGN KEY (raw_product_family_id) REFERENCES raw_product_family (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
      COMMENT='供应商候选货源表'
    """,
    """
    CREATE TABLE IF NOT EXISTS product_edit (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
        raw_product_family_id BIGINT UNSIGNED NOT NULL COMMENT '关联原始商品',
        title               VARCHAR(1024)   NOT NULL COMMENT '编辑标题',
        description         TEXT            NULL COMMENT '商品描述',
        bullet_points       JSON            NULL COMMENT '卖点',
        images              JSON            NULL COMMENT '图片列表',
        attributes          JSON            NULL COMMENT '扩展属性',
        listing_payload     JSON            NULL COMMENT '已生成的上架 Listing 快照',
        listing_built_at    DATETIME        NULL COMMENT 'Listing 生成时间',
        status              VARCHAR(32)     NOT NULL DEFAULT 'editing' COMMENT '状态',
        target_platform     VARCHAR(32)     NOT NULL DEFAULT 'ozon' COMMENT '目标平台',
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (id),
        UNIQUE KEY uk_product_edit_family (raw_product_family_id),
        KEY idx_product_edit_status (status),
        CONSTRAINT fk_product_edit_family FOREIGN KEY (raw_product_family_id) REFERENCES raw_product_family (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
      COMMENT='Ozon 商品编辑草稿表'
    """,
    """
    CREATE TABLE IF NOT EXISTS product_edit_variant (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
        edit_id             BIGINT UNSIGNED NOT NULL COMMENT '关联编辑草稿',
        raw_product_variant_id BIGINT UNSIGNED NULL COMMENT '关联原始变体',
        sku                 VARCHAR(64)     NOT NULL COMMENT '卖家 SKU',
        title               VARCHAR(1024)   NULL COMMENT '变体标题',
        price               DECIMAL(10, 2)  NULL COMMENT '售价',
        quantity            INT             NOT NULL DEFAULT 0 COMMENT '库存',
        image_url           VARCHAR(1024)   NULL COMMENT '变体图片',
        variant_attributes  JSON            NULL COMMENT '变体属性',
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (id),
        UNIQUE KEY uk_product_edit_variant_sku (edit_id, sku),
        KEY idx_product_edit_variant_edit_id (edit_id),
        CONSTRAINT fk_product_edit_variant_edit FOREIGN KEY (edit_id) REFERENCES product_edit (id) ON DELETE CASCADE,
        CONSTRAINT fk_product_edit_variant_raw FOREIGN KEY (raw_product_variant_id) REFERENCES raw_product_variant (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
      COMMENT='Ozon 商品编辑变体表'
    """,
    """
    CREATE TABLE IF NOT EXISTS review_record (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
        edit_id             BIGINT UNSIGNED NOT NULL COMMENT '关联编辑草稿',
        result              VARCHAR(32)     NOT NULL COMMENT '审核结果',
        note                TEXT            NULL COMMENT '审核备注',
        reviewer            VARCHAR(128)    NULL COMMENT '审核人',
        auto_reviewed       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否自动审核',
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        PRIMARY KEY (id),
        KEY idx_review_record_edit_id (edit_id),
        CONSTRAINT fk_review_record_edit FOREIGN KEY (edit_id) REFERENCES product_edit (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
      COMMENT='商品审核记录表'
    """,
    """
    CREATE TABLE IF NOT EXISTS ozon_publish_task (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
        task_no             VARCHAR(64)     NOT NULL COMMENT '任务编号',
        edit_id             BIGINT UNSIGNED NOT NULL COMMENT '关联编辑草稿',
        shop_name           VARCHAR(255)    NULL COMMENT '店铺名称',
        status              VARCHAR(32)     NOT NULL COMMENT '状态',
        submit_type         VARCHAR(32)     NOT NULL DEFAULT 'api' COMMENT '提交方式',
        total_count         INT             NOT NULL DEFAULT 0 COMMENT '总条数',
        success_count       INT             NOT NULL DEFAULT 0 COMMENT '成功条数',
        fail_count          INT             NOT NULL DEFAULT 0 COMMENT '失败条数',
        error_message       TEXT            NULL COMMENT '错误信息',
        submitted_at        DATETIME        NULL COMMENT '提交时间',
        finished_at         DATETIME        NULL COMMENT '完成时间',
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (id),
        UNIQUE KEY uk_ozon_publish_task_no (task_no),
        KEY idx_ozon_publish_task_status (status),
        CONSTRAINT fk_ozon_publish_task_edit FOREIGN KEY (edit_id) REFERENCES product_edit (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
      COMMENT='Ozon 发布任务表'
    """,
    """
    CREATE TABLE IF NOT EXISTS ozon_publish_item (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
        task_id             BIGINT UNSIGNED NOT NULL COMMENT '关联发布任务',
        edit_variant_id     BIGINT UNSIGNED NOT NULL COMMENT '关联编辑变体',
        seller_sku          VARCHAR(64)     NOT NULL COMMENT '卖家 SKU',
        ozon_product_id     VARCHAR(64)     NULL COMMENT 'Ozon 商品 ID',
        ozon_offer_id       VARCHAR(64)     NULL COMMENT 'Ozon offer ID',
        status              VARCHAR(32)     NOT NULL COMMENT '状态',
        error_code          VARCHAR(64)     NULL COMMENT '错误码',
        error_message       TEXT            NULL COMMENT '错误信息',
        submission_payload  JSON            NULL COMMENT '提交载荷',
        response_payload    JSON            NULL COMMENT '响应载荷',
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (id),
        KEY idx_ozon_publish_item_task_id (task_id),
        KEY idx_ozon_publish_item_status (status),
        CONSTRAINT fk_ozon_publish_item_task FOREIGN KEY (task_id) REFERENCES ozon_publish_task (id),
        CONSTRAINT fk_ozon_publish_item_variant FOREIGN KEY (edit_variant_id) REFERENCES product_edit_variant (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
      COMMENT='Ozon 发布明细表'
    """,
]

JSON_FIELDS = {
    "variant_dimensions",
    "variant_attributes",
    "bullet_points",
    "raw_payload",
    "attributes",
    "payload",
    "submission_payload",
    "listing_payload",
    "images",
    "edit_images",
    "response_payload",
    "strategy_params",
}


def init_db() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for statement in CREATE_TABLE_STATEMENTS:
                cursor.execute(statement)
    from db.migrations import run_migrations

    run_migrations()
    drop_legacy_tables()
    apply_table_comments()


def drop_legacy_tables() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table_name in LEGACY_TABLES:
                if table_name in ACTIVE_TABLES:
                    continue
                cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")


def clear_all_data() -> None:
    truncate_order = [
        "ozon_publish_item",
        "ozon_publish_task",
        "review_record",
        "product_edit_variant",
        "product_edit",
        "supplier_candidate",
        "sourcing_task",
        "raw_product_variant",
        "raw_product_family",
        "collection_task",
    ]
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table_name in truncate_order:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name = %s
                    """,
                    (table_name,),
                )
                exists = cursor.fetchone()[0]
                if exists:
                    cursor.execute(f"TRUNCATE TABLE `{table_name}`")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")


def apply_table_comments() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for table_name, comment in TABLE_COMMENTS.items():
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name = %s
                    """,
                    (table_name,),
                )
                if cursor.fetchone()[0]:
                    escaped = comment.replace("'", "''")
                    cursor.execute(f"ALTER TABLE `{table_name}` COMMENT = '{escaped}'")


DROP_TABLES = LEGACY_TABLES


def reset_db() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table_name in LEGACY_TABLES:
                cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            for statement in CREATE_TABLE_STATEMENTS:
                cursor.execute(statement)
    apply_table_comments()

PRAGMA foreign_keys = ON;

CREATE TABLE dataset_metadata (
    dataset_version TEXT PRIMARY KEY,
    is_simulated INTEGER NOT NULL CHECK (is_simulated IN (0, 1)),
    timezone TEXT NOT NULL,
    coverage_start TEXT NOT NULL,
    coverage_end_exclusive TEXT NOT NULL,
    CHECK (coverage_start < coverage_end_exclusive)
);

CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY NOT NULL,
    customer_type TEXT NOT NULL CHECK (customer_type IN ('new', 'returning')),
    created_at TEXT NOT NULL,
    dataset_version TEXT NOT NULL REFERENCES dataset_metadata(dataset_version)
);

CREATE TABLE orders (
    order_id TEXT PRIMARY KEY NOT NULL,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    region TEXT NOT NULL CHECK (region IN ('华东', '华南', '华北', '西部')),
    ordered_at TEXT NOT NULL,
    paid_at TEXT,
    payment_status TEXT NOT NULL CHECK (payment_status IN ('paid', 'cancelled', 'failed')),
    paid_amount_fen INTEGER NOT NULL CHECK (typeof(paid_amount_fen) = 'integer' AND paid_amount_fen >= 0),
    dataset_version TEXT NOT NULL REFERENCES dataset_metadata(dataset_version),
    CHECK ((payment_status = 'paid' AND paid_at IS NOT NULL)
        OR (payment_status != 'paid' AND paid_at IS NULL AND paid_amount_fen = 0)),
    CHECK (paid_at IS NULL OR paid_at >= ordered_at)
);

CREATE TABLE refunds (
    refund_id TEXT PRIMARY KEY NOT NULL,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    requested_at TEXT NOT NULL,
    refunded_at TEXT,
    refund_status TEXT NOT NULL CHECK (refund_status IN ('success', 'failed', 'pending')),
    refund_amount_fen INTEGER NOT NULL CHECK (typeof(refund_amount_fen) = 'integer' AND refund_amount_fen > 0),
    dataset_version TEXT NOT NULL REFERENCES dataset_metadata(dataset_version),
    CHECK ((refund_status = 'success' AND refunded_at IS NOT NULL)
        OR (refund_status != 'success' AND refunded_at IS NULL)),
    CHECK (refunded_at IS NULL OR refunded_at >= requested_at)
);

CREATE TABLE data_quality_issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    severity TEXT NOT NULL CHECK (severity IN ('warning')),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    table_name TEXT,
    row_number INTEGER,
    field_name TEXT
);

CREATE INDEX idx_orders_paid_at ON orders(paid_at);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_refunds_refunded_at ON refunds(refunded_at);
CREATE INDEX idx_refunds_order ON refunds(order_id);

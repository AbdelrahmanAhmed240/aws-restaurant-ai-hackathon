"""
Rest_Ai-Agent — Isolated Visual Database & Instance Explorer
============================================================
A 100% read-only, safe, standalone visual explorer designed for educational exploration
of the SQLite database (instance/restaurant.db) and all files in instance/.

Features:
- 100% Read-Only mode: opens SQLite with uri=True and mode=ro. Zero risk of database modification.
- Interactive, responsive web UI with Mermaid.js ERD (zoomable, pannable, table focus).
- Full database overview: tables, record counts, sizes, engine info.
- Paginated table browser with column types, primary keys, and foreign keys.
- Complete inventory and analysis of all files in instance/ (including backups).
- Built-in educational guide explaining databases, tables, keys, relationships, and SQLAlchemy.

Usage:
    python db_explorer.py
Then open http://127.0.0.1:5050 in your browser.
"""

import http.server
import json
import os
import sqlite3
import sys
import urllib.parse
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
DB_PATH = INSTANCE_DIR / "restaurant.db"
PORT = 5050


def get_instance_inventory():
    """Scans instance/ and reports all files, backups, sizes, and their roles."""
    items = []
    if not INSTANCE_DIR.exists():
        return {"exists": False, "items": []}

    for root, dirs, files in os.walk(INSTANCE_DIR):
        for d in dirs:
            dp = Path(root) / d
            items.append({
                "name": dp.name,
                "relative_path": str(dp.relative_to(INSTANCE_DIR)),
                "type": "directory",
                "size_bytes": 0,
                "size_human": "-",
                "role": "Directory",
                "explanation": "Nested folder within instance directory."
            })
        for f in files:
            fp = Path(root) / f
            size = fp.stat().st_size
            human_size = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / (1024*1024):.2f} MB"
            
            # Determine role based on file extension and purpose
            if f == "restaurant.db":
                role = "Primary SQLite Database"
                explanation = "Active relational database used by the Flask application, SQLAlchemy models, and chat drafts."
            elif f.endswith(".bak"):
                role = "Database Backup"
                explanation = "Historical database snapshot preserved for recovery. Contains older seed orders and customers."
            elif f.endswith(("-wal", ".wal")):
                role = "Write-Ahead Log (WAL)"
                explanation = "SQLite temporary transaction log. Never delete while database is open."
            elif f.endswith(("-shm", ".shm")):
                role = "Shared-Memory Index"
                explanation = "SQLite shared-memory index file used for WAL coordination."
            else:
                role = "Artifact"
                explanation = "File stored inside instance directory."

            items.append({
                "name": f,
                "relative_path": str(fp.relative_to(INSTANCE_DIR)),
                "type": "file",
                "size_bytes": size,
                "size_human": human_size,
                "role": role,
                "explanation": explanation
            })
    return {"exists": True, "path": str(INSTANCE_DIR), "items": items}


def get_db_metadata():
    """Reads schema, tables, column info, counts, and foreign keys in strict read-only mode."""
    if not DB_PATH.exists():
        return {"ok": False, "error": f"Database file not found at {DB_PATH}"}

    try:
        # Strict read-only SQLite connection
        conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        cur = conn.cursor()

        cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name;")
        table_rows = [r for r in cur.fetchall() if not r[0].startswith("sqlite_")]
        
        tables = {}
        for t_name, ddl in table_rows:
            # Row count
            cur.execute(f"SELECT COUNT(*) FROM {t_name};")
            row_count = cur.fetchone()[0]

            # Columns info
            cur.execute(f"PRAGMA table_info({t_name});")
            col_rows = cur.fetchall()
            columns = []
            for cid, name, col_type, notnull, default_val, pk in col_rows:
                columns.append({
                    "cid": cid,
                    "name": name,
                    "type": col_type or "TEXT",
                    "notnull": bool(notnull),
                    "default_value": default_val,
                    "pk": bool(pk)
                })

            # Foreign Keys
            cur.execute(f"PRAGMA foreign_key_list({t_name});")
            fk_rows = cur.fetchall()
            foreign_keys = []
            for fk_id, seq, to_table, from_col, to_col, on_update, on_delete, match in fk_rows:
                foreign_keys.append({
                    "from_col": from_col,
                    "to_table": to_table,
                    "to_col": to_col,
                    "on_update": on_update,
                    "on_delete": on_delete
                })

            tables[t_name] = {
                "name": t_name,
                "row_count": row_count,
                "columns": columns,
                "foreign_keys": foreign_keys,
                "ddl": ddl
            }

        conn.close()

        # Database file size
        file_size = DB_PATH.stat().st_size
        return {
            "ok": True,
            "path": str(DB_PATH),
            "size_bytes": file_size,
            "size_human": f"{file_size / 1024:.1f} KB",
            "table_count": len(tables),
            "tables": tables
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_table_records(table_name: str, page: int = 1, per_page: int = 10):
    """Fetches paginated records in strict read-only mode."""
    if not DB_PATH.exists():
        return {"ok": False, "error": "Database not found."}

    # Validate table_name against sqlite_master
    try:
        conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (table_name,))
        if not cur.fetchone():
            conn.close()
            return {"ok": False, "error": f"Table '{table_name}' does not exist."}

        cur.execute(f"SELECT COUNT(*) FROM {table_name};")
        total = cur.fetchone()[0]

        offset = max(0, (page - 1) * per_page)
        cur.execute(f"SELECT * FROM {table_name} LIMIT ? OFFSET ?;", (per_page, offset))
        rows = cur.fetchall()

        cur.execute(f"PRAGMA table_info({table_name});")
        col_names = [c[1] for c in cur.fetchall()]

        records = []
        for r in rows:
            rec = {}
            for col_idx, col_name in enumerate(col_names):
                val = r[col_idx]
                # Format string representations safely
                if isinstance(val, bytes):
                    val = "<binary data>"
                rec[col_name] = val
            records.append(rec)

        conn.close()
        return {
            "ok": True,
            "table": table_name,
            "total_rows": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
            "columns": col_names,
            "records": records
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rest_Ai-Agent — Database & Instance Visual Explorer</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <style>
        :root {
            --sidebar-width: 280px;
            --primary-accent: #2563eb;
            --bg-canvas: #f8fafc;
        }
        body {
            background-color: var(--bg-canvas);
            font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            color: #1e293b;
        }
        .navbar-brand {
            font-weight: 700;
            letter-spacing: -0.5px;
        }
        .card {
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.05);
        }
        .card-header {
            background-color: #ffffff;
            border-bottom: 1px solid #f1f5f9;
            font-weight: 600;
        }
        .stat-card {
            transition: transform 0.2s;
        }
        .stat-card:hover {
            transform: translateY(-2px);
        }
        .badge-pk {
            background-color: #ef4444;
            color: #ffffff;
            font-weight: 600;
            font-size: 0.7rem;
            padding: 2px 6px;
            border-radius: 4px;
        }
        .badge-fk {
            background-color: #3b82f6;
            color: #ffffff;
            font-weight: 600;
            font-size: 0.7rem;
            padding: 2px 6px;
            border-radius: 4px;
        }
        .badge-col {
            background-color: #f1f5f9;
            color: #475569;
            font-size: 0.75rem;
            border: 1px solid #cbd5e1;
        }
        #mermaid-graph-container {
            min-height: 480px;
            background-color: #ffffff;
            border-radius: 12px;
            overflow: auto;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 24px;
        }
        .table-nav-btn.active {
            background-color: var(--primary-accent);
            color: white !important;
            font-weight: 600;
        }
        pre.sql-box {
            background-color: #0f172a;
            color: #f8fafc;
            padding: 12px;
            border-radius: 8px;
            font-size: 0.85rem;
            max-height: 200px;
            overflow-y: auto;
        }
    </style>
</head>
<body>

<!-- Navigation -->
<nav class="navbar navbar-expand-lg navbar-dark bg-dark sticky-top px-3">
    <div class="container-fluid">
        <a class="navbar-brand d-flex align-items-center gap-2" href="#">
            <i class="bi bi-database-fill-gear text-primary fs-4"></i>
            <span>Rest_Ai-Agent <span class="badge bg-primary fs-7">Database Explorer</span></span>
        </a>
        <div class="d-flex align-items-center gap-3">
            <span class="badge bg-success py-2 px-3"><i class="bi bi-shield-lock-fill me-1"></i>Strict Read-Only Mode</span>
            <button class="btn btn-outline-light btn-sm" onclick="loadAll()"><i class="bi bi-arrow-clockwise me-1"></i>Refresh</button>
        </div>
    </div>
</nav>

<div class="container-fluid py-4 px-4">

    <!-- Top Status / Stats Bar -->
    <div class="row g-3 mb-4" id="stats-row">
        <div class="col-md-3">
            <div class="card stat-card p-3">
                <div class="text-muted small fw-semibold">DATABASE STATUS</div>
                <div class="d-flex align-items-center justify-content-between mt-2">
                    <h4 class="mb-0 fw-bold text-success" id="stat-status"><i class="bi bi-check-circle-fill me-1"></i>Connected</h4>
                    <i class="bi bi-hdd-fill text-muted fs-3"></i>
                </div>
                <div class="small text-muted mt-2 text-truncate" id="stat-path" title="Path">instance/restaurant.db</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card stat-card p-3">
                <div class="text-muted small fw-semibold">TOTAL TABLES</div>
                <div class="d-flex align-items-center justify-content-between mt-2">
                    <h4 class="mb-0 fw-bold text-primary" id="stat-tables">-</h4>
                    <i class="bi bi-table text-muted fs-3"></i>
                </div>
                <div class="small text-muted mt-2">Relational SQLite Schema</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card stat-card p-3">
                <div class="text-muted small fw-semibold">DATABASE SIZE</div>
                <div class="d-flex align-items-center justify-content-between mt-2">
                    <h4 class="mb-0 fw-bold" id="stat-size">-</h4>
                    <i class="bi bi-file-earmark-binary text-muted fs-3"></i>
                </div>
                <div class="small text-muted mt-2">Single File on Disk</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card stat-card p-3">
                <div class="text-muted small fw-semibold">INSTANCE ARTIFACTS</div>
                <div class="d-flex align-items-center justify-content-between mt-2">
                    <h4 class="mb-0 fw-bold text-info" id="stat-instance-files">-</h4>
                    <i class="bi bi-folder2-open text-muted fs-3"></i>
                </div>
                <div class="small text-muted mt-2">Live DB + Backup Snapshots</div>
            </div>
        </div>
    </div>

    <!-- Navigation Tabs -->
    <ul class="nav nav-pills mb-4 gap-2 bg-white p-2 rounded-3 border" id="mainTab" role="tablist">
        <li class="nav-item" role="presentation">
            <button class="nav-link active fw-semibold" id="erd-tab" data-bs-toggle="pill" data-bs-target="#erd-pane">
                <i class="bi bi-diagram-3-fill me-2"></i>Entity-Relationship Diagram (ERD)
            </button>
        </li>
        <li class="nav-item" role="presentation">
            <button class="nav-link fw-semibold" id="browser-tab" data-bs-toggle="pill" data-bs-target="#browser-pane">
                <i class="bi bi-table me-2"></i>Table Data & Schema Browser
            </button>
        </li>
        <li class="nav-item" role="presentation">
            <button class="nav-link fw-semibold" id="instance-tab" data-bs-toggle="pill" data-bs-target="#instance-pane">
                <i class="bi bi-folder-fill me-2"></i>`instance/` Directory Inventory
            </button>
        </li>
        <li class="nav-item" role="presentation">
            <button class="nav-link fw-semibold" id="edu-tab" data-bs-toggle="pill" data-bs-target="#edu-pane">
                <i class="bi bi-mortarboard-fill me-2"></i>Beginner Educational Guide
            </button>
        </li>
    </ul>

    <!-- Tab Contents -->
    <div class="tab-content" id="mainTabContent">

        <!-- 1. ERD TAB -->
        <div class="tab-pane fade show active" id="erd-pane" role="tabpanel">
            <div class="card mb-4">
                <div class="card-header d-flex justify-content-between align-items-center py-3">
                    <div>
                        <h5 class="mb-0 fw-bold"><i class="bi bi-diagram-3 me-2 text-primary"></i>Visual Database Entity-Relationship Diagram (ERD)</h5>
                        <p class="text-muted small mb-0 mt-1">Rendered directly from SQLite foreign-key constraints and SQLAlchemy model relationships.</p>
                    </div>
                    <div class="d-flex gap-2">
                        <button class="btn btn-outline-secondary btn-sm" onclick="renderERD('all')">View All Tables</button>
                        <select class="form-select form-select-sm" id="erd-table-focus" onchange="renderERD(this.value)" style="width: 180px;">
                            <option value="all">Focus Table...</option>
                        </select>
                    </div>
                </div>
                <div class="card-body">
                    <div class="alert alert-info py-2 px-3 small d-flex align-items-center gap-2 mb-3">
                        <i class="bi bi-info-circle-fill fs-5"></i>
                        <div>
                            <strong>Relationship Legend:</strong> Solid arrows represent <strong>Enforced Foreign Keys</strong> (e.g. <code>orders.customer_id &rarr; customers.id</code> and <code>chat_messages.session_id &rarr; chat_sessions.session_id</code>). Notice historical preservation: <code>customer_id</code> is nullable so orders persist when customers are deleted.
                        </div>
                    </div>
                    <div id="mermaid-graph-container">
                        <div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 2. TABLE BROWSER TAB -->
        <div class="tab-pane fade" id="browser-pane" role="tabpanel">
            <div class="row g-4">
                <!-- Table Selection Sidebar -->
                <div class="col-md-3">
                    <div class="card">
                        <div class="card-header py-3">
                            <span class="fw-bold"><i class="bi bi-list-columns-reverse me-2"></i>Tables</span>
                        </div>
                        <div class="list-group list-group-flush p-2" id="tables-sidebar">
                            <!-- Populated dynamically -->
                        </div>
                    </div>
                </div>

                <!-- Table Details and Records -->
                <div class="col-md-9">
                    <div class="card mb-4" id="table-details-card">
                        <div class="card-header py-3 d-flex justify-content-between align-items-center">
                            <div>
                                <h5 class="mb-0 fw-bold" id="active-table-title">Select a Table</h5>
                                <span class="text-muted small" id="active-table-subtitle"></span>
                            </div>
                            <span class="badge bg-secondary fs-7" id="active-table-badge">-</span>
                        </div>
                        <div class="card-body">

                            <!-- Columns & Keys Schema -->
                            <h6 class="fw-bold mb-2"><i class="bi bi-columns me-2 text-primary"></i>Columns & Foreign Keys</h6>
                            <div class="table-responsive mb-4">
                                <table class="table table-sm table-bordered align-middle mb-0">
                                    <thead class="table-light">
                                        <tr>
                                            <th>Column Name</th>
                                            <th>Data Type</th>
                                            <th>Constraints</th>
                                            <th>Foreign Key Relationship</th>
                                        </tr>
                                    </thead>
                                    <tbody id="columns-tbody"></tbody>
                                </table>
                            </div>

                            <!-- Records Preview -->
                            <div class="d-flex justify-content-between align-items-center mb-2">
                                <h6 class="fw-bold mb-0"><i class="bi bi-eye me-2 text-success"></i>Paginated Data Preview</h6>
                                <div class="d-flex align-items-center gap-2">
                                    <span class="small text-muted" id="pagination-info">Showing 0 of 0</span>
                                    <div class="btn-group btn-group-sm">
                                        <button class="btn btn-outline-secondary" id="btn-prev-page" onclick="changePage(-1)"><i class="bi bi-chevron-left"></i></button>
                                        <button class="btn btn-outline-secondary" id="btn-next-page" onclick="changePage(1)"><i class="bi bi-chevron-right"></i></button>
                                    </div>
                                </div>
                            </div>
                            <div class="table-responsive border rounded-3 mb-4" style="max-height: 380px;">
                                <table class="table table-sm table-hover align-middle mb-0" id="records-table">
                                    <thead class="table-light sticky-top" id="records-thead"></thead>
                                    <tbody id="records-tbody"></tbody>
                                </table>
                            </div>

                            <!-- DDL Definition -->
                            <details class="mt-2">
                                <summary class="text-muted small fw-semibold cursor-pointer">View Raw SQLite CREATE TABLE DDL</summary>
                                <pre class="sql-box mt-2" id="ddl-box"></pre>
                            </details>

                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 3. INSTANCE INVENTORY TAB -->
        <div class="tab-pane fade" id="instance-pane" role="tabpanel">
            <div class="card">
                <div class="card-header py-3">
                    <h5 class="mb-0 fw-bold"><i class="bi bi-folder2-open me-2 text-warning"></i>`instance/` Directory File Inventory</h5>
                    <p class="text-muted small mb-0 mt-1">Inspected files inside the Flask instance storage location.</p>
                </div>
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-hover align-middle mb-0">
                            <thead class="table-light">
                                <tr>
                                    <th>File Name</th>
                                    <th>Classification / Role</th>
                                    <th>Size</th>
                                    <th>Description & Purpose</th>
                                </tr>
                            </thead>
                            <tbody id="instance-files-tbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <!-- 4. EDUCATIONAL GUIDE TAB -->
        <div class="tab-pane fade" id="edu-pane" role="tabpanel">
            <div class="card p-4">
                <h4 class="fw-bold mb-3 text-primary"><i class="bi bi-mortarboard-fill me-2"></i>Database & Relationship Fundamentals (Beginner Guide)</h4>
                <p class="text-muted">This guide explains how relational databases and SQLAlchemy work using real tables from your <strong>Rest_Ai-Agent</strong> application.</p>

                <div class="row g-4 mt-2">
                    <div class="col-md-6">
                        <div class="p-3 border rounded-3 bg-light h-100">
                            <h6 class="fw-bold text-dark"><i class="bi bi-1-circle-fill text-primary me-2"></i>What is a Database Table, Row, and Column?</h6>
                            <p class="small text-muted mb-2">Think of a database table like an organized spreadsheet:</p>
                            <ul class="small text-muted mb-0">
                                <li><strong>Table:</strong> Represents a collection of a single entity (e.g. <code>products</code>, <code>customers</code>, <code>orders</code>).</li>
                                <li><strong>Column (Attribute):</strong> A defined property with a specific data type (e.g. <code>price</code> is a <code>FLOAT</code>, <code>name</code> is a <code>VARCHAR</code>).</li>
                                <li><strong>Row (Record / Tuple):</strong> A single concrete item (e.g. Row #1 is the dish <code>Break Meal</code> priced at <code>235.0 EGP</code>).</li>
                            </ul>
                        </div>
                    </div>

                    <div class="col-md-6">
                        <div class="p-3 border rounded-3 bg-light h-100">
                            <h6 class="fw-bold text-dark"><i class="bi bi-2-circle-fill text-primary me-2"></i>Primary Key (PK) vs Foreign Key (FK)</h6>
                            <ul class="small text-muted mb-0">
                                <li><strong>Primary Key (PK):</strong> A column (like <code>orders.id</code> or <code>customers.id</code>) that guarantees every row is uniquely identifiable. No two rows can share the same PK.</li>
                                <li><strong>Foreign Key (FK):</strong> A column in one table that references the Primary Key of another table (e.g. <code>orders.customer_id</code> points to <code>customers.id</code>). This builds the "relationship" between the two tables.</li>
                            </ul>
                        </div>
                    </div>

                    <div class="col-md-6">
                        <div class="p-3 border rounded-3 bg-light h-100">
                            <h6 class="fw-bold text-dark"><i class="bi bi-3-circle-fill text-primary me-2"></i>One-to-Many Relationships (1 : N)</h6>
                            <p class="small text-muted mb-2">In this restaurant system:</p>
                            <ul class="small text-muted mb-0">
                                <li><strong>Customer &rarr; Orders:</strong> One customer can place many orders over time. Hence, the <code>orders</code> table holds the foreign key <code>customer_id</code>.</li>
                                <li><strong>Order &rarr; Order Items:</strong> One order can have multiple dishes (e.g. 1 Broasted + 1 Water). The <code>order_items</code> table holds <code>order_id</code>.</li>
                                <li><strong>ChatSession &rarr; ChatMessages:</strong> One conversation session has many messages. The <code>chat_messages</code> table holds <code>session_id</code>.</li>
                            </ul>
                        </div>
                    </div>

                    <div class="col-md-6">
                        <div class="p-3 border rounded-3 bg-light h-100">
                            <h6 class="fw-bold text-dark"><i class="bi bi-4-circle-fill text-primary me-2"></i>SQLAlchemy Relationship vs Database FK Constraint</h6>
                            <p class="small text-muted mb-2">Crucial interview distinction:</p>
                            <ul class="small text-muted mb-0">
                                <li><strong>Database Foreign Key:</strong> A physical constraint enforced by the SQLite engine preventing invalid IDs.</li>
                                <li><strong>SQLAlchemy <code>db.relationship()</code>:</strong> A Python convenience property on your model class (e.g. <code>customer.orders</code>). It lets Python access <code>customer.orders</code> as a Python list automatically, without manually writing SQL JOIN statements!</li>
                            </ul>
                        </div>
                    </div>
                </div>

                <div class="alert alert-warning py-3 px-3 mt-4 small mb-0">
                    <h6 class="fw-bold text-dark mb-1"><i class="bi bi-shield-exclamation text-warning me-2"></i>Historical Preservation Architectural Pattern</h6>
                    In <code>app/models/order.py</code>, notice that <code>customer_id</code> is <strong>nullable</strong>, and <code>Order</code> also stores static copies of <code>customer_name</code> and <code>customer_phone</code>. Why? If an admin deletes a customer profile, the app sets <code>customer_id = None</code> instead of deleting the order! All past revenue, accounting, and order histories remain 100% safe.
                </div>
            </div>
        </div>

    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
    mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' });

    let dbData = null;
    let currentTable = null;
    let currentPage = 1;

    async function loadAll() {
        try {
            // 1. Fetch metadata
            const resMeta = await fetch('/api/metadata');
            dbData = await resMeta.json();

            if (!dbData.ok) {
                alert("Database Error: " + dbData.error);
                return;
            }

            // Update stats
            document.getElementById('stat-tables').innerText = dbData.table_count;
            document.getElementById('stat-size').innerText = dbData.size_human;
            document.getElementById('stat-path').innerText = dbData.path;

            // Populate table focus dropdown
            const focusSel = document.getElementById('erd-table-focus');
            focusSel.innerHTML = '<option value="all">Focus Table...</option>';
            const sidebar = document.getElementById('tables-sidebar');
            sidebar.innerHTML = '';

            const tableNames = Object.keys(dbData.tables);
            tableNames.forEach((tName, idx) => {
                const t = dbData.tables[tName];
                focusSel.innerHTML += `<option value="${tName}">${tName} (${t.row_count})</option>`;
                
                const btn = document.createElement('button');
                btn.className = `list-group-item list-group-item-action d-flex justify-content-between align-items-center table-nav-btn ${idx === 0 ? 'active' : ''}`;
                btn.id = `btn-tbl-${tName}`;
                btn.innerHTML = `<span><i class="bi bi-table me-2"></i>${tName}</span><span class="badge bg-secondary rounded-pill">${t.row_count}</span>`;
                btn.onclick = () => selectTable(tName);
                sidebar.appendChild(btn);
            });

            // 2. Fetch inventory
            const resInv = await fetch('/api/instance');
            const invData = await resInv.json();
            document.getElementById('stat-instance-files').innerText = invData.items.length;

            const tbodyInv = document.getElementById('instance-files-tbody');
            tbodyInv.innerHTML = '';
            invData.items.forEach(it => {
                const badgeClass = it.name.endsWith('.db') ? 'bg-success' : (it.name.endsWith('.bak') ? 'bg-info' : 'bg-secondary');
                tbodyInv.innerHTML += `
                    <tr>
                        <td class="fw-bold"><code>${it.name}</code></td>
                        <td><span class="badge ${badgeClass}">${it.role}</span></td>
                        <td>${it.size_human}</td>
                        <td class="small text-muted">${it.explanation}</td>
                    </tr>
                `;
            });

            // 3. Render ERD and select first table
            renderERD('all');
            if (tableNames.length > 0) {
                selectTable(tableNames[0]);
            }
        } catch (e) {
            console.error(e);
        }
    }

    function renderERD(focusTable = 'all') {
        if (!dbData || !dbData.tables) return;
        const tables = dbData.tables;
        let mmd = "erDiagram\n";

        // Generate entity definitions
        for (const [tName, tInfo] of Object.entries(tables)) {
            if (focusTable !== 'all' && tName !== focusTable) {
                // Check if related
                const isRelated = tInfo.foreign_keys.some(fk => fk.to_table === focusTable) || 
                                  (tables[focusTable] && tables[focusTable].foreign_keys.some(fk => fk.to_table === tName));
                if (!isRelated) continue;
            }

            mmd += `    ${tName} {\n`;
            tInfo.columns.forEach(col => {
                let cleanType = col.type.replace(/[^a-zA-Z0-9]/g, '_');
                let tag = col.pk ? "PK" : (tInfo.foreign_keys.some(fk => fk.from_col === col.name) ? "FK" : "");
                mmd += `        ${cleanType} ${col.name} ${tag}\n`;
            });
            mmd += `    }\n`;
        }

        // Generate relationships
        for (const [tName, tInfo] of Object.entries(tables)) {
            tInfo.foreign_keys.forEach(fk => {
                // fk.from_col in tName references fk.to_col in fk.to_table
                // In erDiagram: Target ||--o{ Source : "has"
                let target = fk.to_table;
                if (target === "orders_old") target = "orders"; // Normalize alias if present

                if (tables[target]) {
                    if (focusTable === 'all' || tName === focusTable || target === focusTable) {
                        mmd += `    ${target} ||--o{ ${tName} : "references ${fk.from_col}"\n`;
                    }
                }
            });
        }

        const container = document.getElementById('mermaid-graph-container');
        container.innerHTML = `<div class="mermaid">${mmd}</div>`;
        mermaid.run();
    }

    async function selectTable(tName) {
        currentTable = tName;
        currentPage = 1;

        // Active state in sidebar
        document.querySelectorAll('.table-nav-btn').forEach(b => b.classList.remove('active'));
        const activeBtn = document.getElementById(`btn-tbl-${tName}`);
        if (activeBtn) activeBtn.classList.add('active');

        const tInfo = dbData.tables[tName];
        document.getElementById('active-table-title').innerText = tName;
        document.getElementById('active-table-subtitle').innerText = `${tInfo.columns.length} Columns · SQLite Table`;
        document.getElementById('active-table-badge').innerText = `${tInfo.row_count} Total Rows`;
        document.getElementById('ddl-box').innerText = tInfo.ddl || "-- No DDL available";

        // Populate Columns Schema Table
        const colTbody = document.getElementById('columns-tbody');
        colTbody.innerHTML = '';
        tInfo.columns.forEach(c => {
            const isFK = tInfo.foreign_keys.find(fk => fk.from_col === c.name);
            colTbody.innerHTML += `
                <tr>
                    <td class="fw-semibold"><code>${c.name}</code></td>
                    <td><span class="badge badge-col">${c.type}</span></td>
                    <td>
                        ${c.pk ? '<span class="badge badge-pk me-1">PRIMARY KEY</span>' : ''}
                        ${c.notnull ? '<span class="badge bg-light text-dark border me-1">NOT NULL</span>' : '<span class="text-muted small">Nullable</span>'}
                    </td>
                    <td>
                        ${isFK ? `<span class="badge badge-fk me-1">FK</span> references <code>${isFK.to_table}.${isFK.to_col}</code>` : '<span class="text-muted small">—</span>'}
                    </td>
                </tr>
            `;
        });

        // Load Records
        await loadTableRecords();
    }

    async function loadTableRecords() {
        if (!currentTable) return;
        try {
            const res = await fetch(`/api/records?table=${currentTable}&page=${currentPage}&per_page=10`);
            const data = await res.json();
            if (!data.ok) return;

            document.getElementById('pagination-info').innerText = `Page ${data.page} of ${data.total_pages} (${data.total_rows} total rows)`;
            document.getElementById('btn-prev-page').disabled = data.page <= 1;
            document.getElementById('btn-next-page').disabled = data.page >= data.total_pages;

            // Render Header
            const thead = document.getElementById('records-thead');
            thead.innerHTML = '<tr>' + data.columns.map(c => `<th>${c}</th>`).join('') + '</tr>';

            // Render Rows
            const tbody = document.getElementById('records-tbody');
            tbody.innerHTML = '';
            if (data.records.length === 0) {
                tbody.innerHTML = `<tr><td colspan="${data.columns.length}" class="text-center py-4 text-muted">Table contains zero records.</td></tr>`;
            } else {
                data.records.forEach(row => {
                    let tr = '<tr>';
                    data.columns.forEach(col => {
                        let val = row[col];
                        if (val === null || val === undefined) {
                            tr += '<td class="text-muted fst-italic small">NULL</td>';
                        } else if (typeof val === 'boolean') {
                            tr += `<td><span class="badge ${val ? 'bg-success' : 'bg-secondary'}">${val}</span></td>`;
                        } else {
                            tr += `<td>${val}</td>`;
                        }
                    });
                    tr += '</tr>';
                    tbody.innerHTML += tr;
                });
            }
        } catch (e) {
            console.error(e);
        }
    }

    function changePage(delta) {
        currentPage += delta;
        loadTableRecords();
    }

    window.onload = loadAll;
</script>
</body>
</html>
"""


class ReadOnlyExplorerHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler that only serves read-only metadata and the visual UI."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))

        elif path == "/api/metadata":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = get_db_metadata()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

        elif path == "/api/instance":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = get_instance_inventory()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

        elif path == "/api/records":
            table_name = query.get("table", [""])[0]
            page = int(query.get("page", [1])[0])
            per_page = int(query.get("per_page", [10])[0])
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = get_table_records(table_name, page, per_page)
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def log_message(self, format, *args):
        # Keep terminal output quiet and clean
        pass


def run_explorer(port=PORT):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), ReadOnlyExplorerHandler)
    print("=======================================================================")
    print(f"  Rest_Ai-Agent — Database & Instance Visual Explorer (Read-Only)      ")
    print("=======================================================================")
    print(f"  [OK] Connected to: {DB_PATH}")
    print(f"  [OK] Serving locally at: http://127.0.0.1:{port}")
    print("  [OK] 100% Read-Only mode: Safe for existing databases and backups.")
    print("  Press Ctrl+C to stop the explorer anytime.")
    print("=======================================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping visual database explorer...")
        server.server_close()


if __name__ == "__main__":
    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run_explorer(port_arg)

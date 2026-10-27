import sqlite3
import os
import shutil
import sys


def _app_base_dir():
    """
    Returns the folder to store app data in.

    Normal .py file:
        data folder is created beside this file.

    Frozen EXE:
        data folder is created beside the EXE.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))

    return os.path.dirname(os.path.abspath(__file__))


BASE = _app_base_dir()
DATA_DIR = os.path.join(BASE, "data")
DB_PATH = os.path.join(DATA_DIR, "billing.db")
BACKUP_PATH = os.path.join(DATA_DIR, "billing_backup.db")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _restore_if_needed():
    """
    Restore the backup only when the main database does not exist
    or is clearly empty/corrupted.
    """
    _ensure_data_dir()

    if not os.path.exists(BACKUP_PATH):
        return

    if not os.path.exists(DB_PATH):
        shutil.copy2(BACKUP_PATH, DB_PATH)
        return

    try:
        if os.path.getsize(DB_PATH) < 100:
            shutil.copy2(BACKUP_PATH, DB_PATH)
    except OSError:
        pass


def conn():
    _ensure_data_dir()
    _restore_if_needed()

    connection = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA synchronous = FULL")

    return connection


def _make_backup():
    """
    Create a safe SQLite backup without deleting the main database.
    """
    _ensure_data_dir()

    if not os.path.exists(DB_PATH):
        return

    temp_path = BACKUP_PATH + ".tmp"

    try:
        source = sqlite3.connect(DB_PATH, timeout=30)
        destination = sqlite3.connect(temp_path, timeout=30)

        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
            source.close()

        os.replace(temp_path, BACKUP_PATH)

    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


def _add_column_if_missing(cursor, table_name, column_name, column_definition):
    """
    Add a column only when it does not already exist.
    """
    columns = [
        row["name"]
        for row in cursor.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    ]

    if column_name not in columns:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN "
            f"{column_name} {column_definition}"
        )


def _table_exists(cursor, table_name):
    row = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    ).fetchone()
    return row is not None


def _godown_products_needs_repair(cursor):
    """
    True when a `godown_products` table already exists but its columns
    or its FOREIGN KEY targets don't match what this version of the app
    expects (godown_id -> godowns.id, product_id -> products.id).

    This happens when an OLDER build of the app already created a table
    with this name against a different schema (for example, back when
    Godowns were per-customer instead of global) — `CREATE TABLE IF NOT
    EXISTS` silently does nothing in that case, so the stale, mismatched
    FOREIGN KEY stays in place forever and every new insert into it then
    fails with "FOREIGN KEY constraint failed", even though the rest of
    the app is using the new, correct table names and ids.
    """
    if not _table_exists(cursor, "godown_products"):
        return False  # nothing exists yet -> CREATE TABLE IF NOT EXISTS below will make it fresh

    cols = {r["name"] for r in cursor.execute("PRAGMA table_info(godown_products)")}
    if not {"id", "godown_id", "product_id"} <= cols:
        return True

    fks = cursor.execute("PRAGMA foreign_key_list(godown_products)").fetchall()
    referenced_tables = {(fk["table"] or "").lower() for fk in fks}
    # A healthy table has FOREIGN KEYs pointing at BOTH godowns and products.
    return not ({"godowns", "products"} <= referenced_tables)


def _repair_godown_products_table(cursor):
    """
    Rebuild `godown_products` with the correct schema, carrying over any
    old (godown_id, product_id) pairs that still point at rows which
    genuinely exist in the current `godowns` / `products` tables. Rows
    that don't resolve any more are simply dropped (they were already
    orphaned/meaningless).
    """
    if not _godown_products_needs_repair(cursor):
        return

    cursor.execute("ALTER TABLE godown_products RENAME TO godown_products_old_backup")

    cursor.execute('''
        CREATE TABLE godown_products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            godown_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            UNIQUE(godown_id, product_id),
            FOREIGN KEY(godown_id) REFERENCES godowns(id) ON DELETE CASCADE,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        )
    ''')

    try:
        old_cols = {r["name"] for r in cursor.execute("PRAGMA table_info(godown_products_old_backup)")}
        if {"godown_id", "product_id"} <= old_cols:
            old_rows = cursor.execute(
                "SELECT godown_id, product_id FROM godown_products_old_backup"
            ).fetchall()
            for r in old_rows:
                gid, pid = r["godown_id"], r["product_id"]
                g_ok = cursor.execute("SELECT 1 FROM godowns WHERE id=?", (gid,)).fetchone()
                p_ok = cursor.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone()
                if g_ok and p_ok:
                    cursor.execute(
                        "INSERT OR IGNORE INTO godown_products(godown_id, product_id) VALUES(?,?)",
                        (gid, pid)
                    )
    except sqlite3.Error:
        pass

    # Keep the old table renamed instead of dropping it outright, just in
    # case something needs to be recovered manually later. It is harmless
    # sitting there unused. If you'd rather it be removed automatically,
    # uncomment the next line.
    # cursor.execute("DROP TABLE IF EXISTS godown_products_old_backup")


def init_db():
    """
    Create all tables and safely migrate old databases.

    IMPORTANT:
    The old GST/from/to/route columns are intentionally kept in the
    database for compatibility with old records and old code.

    They are set to zero/empty values for Challans. Do not physically
    delete database columns because old SELECT statements may depend
    on their positions.
    """
    _ensure_data_dir()
    _restore_if_needed()

    sql = """
    CREATE TABLE IF NOT EXISTS customers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT,
        contact_no TEXT,
        email TEXT,
        state TEXT,
        gstin TEXT,
        contact_person TEXT
    );

    CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT NOT NULL,
        hsn_sac TEXT,
        unit TEXT DEFAULT 'Nos',
        price REAL DEFAULT 0,
        weight_kg REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS routes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_city TEXT NOT NULL,
        to_city TEXT NOT NULL,
        rate REAL DEFAULT 0,
        rate_type TEXT DEFAULT 'Per Kg'
    );

    CREATE TABLE IF NOT EXISTS quotations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT UNIQUE,
        date TEXT,
        customer_id INTEGER,
        gst_rate REAL DEFAULT 0,
        subtotal REAL DEFAULT 0,
        cgst REAL DEFAULT 0,
        sgst REAL DEFAULT 0,
        total REAL DEFAULT 0,
        notes TEXT,
        shipping REAL DEFAULT 0,
        place_of_supply TEXT,
        time TEXT,
        FOREIGN KEY(customer_id) REFERENCES customers(id)
    );

    CREATE TABLE IF NOT EXISTS quotation_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quotation_id INTEGER,
        product_id INTEGER,
        item_name TEXT,
        hsn_sac TEXT,
        qty REAL,
        unit TEXT,
        price REAL,
        amount REAL,
        weight_kg REAL,
        FOREIGN KEY(quotation_id)
            REFERENCES quotations(id)
            ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS challans(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT UNIQUE,
        date TEXT,
        time TEXT,
        place_of_supply TEXT,
        customer_id INTEGER,
        godown TEXT,

        gst_rate REAL DEFAULT 0,
        subtotal REAL DEFAULT 0,
        cgst REAL DEFAULT 0,
        sgst REAL DEFAULT 0,

        freight REAL DEFAULT 0,
        total REAL DEFAULT 0,
        description TEXT,

        from_city TEXT,
        to_city TEXT,
        freight_rate REAL DEFAULT 0,
        freight_rate_type TEXT DEFAULT 'Per Kg',

        gst_mode TEXT DEFAULT 'NO_GST',

        FOREIGN KEY(customer_id) REFERENCES customers(id)
    );

    CREATE TABLE IF NOT EXISTS challan_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        challan_id INTEGER,
        product_id INTEGER,
        item_name TEXT,
        hsn_sac TEXT,
        qty REAL,
        unit TEXT,
        price REAL,
        amount REAL,
        weight_kg REAL,
        FOREIGN KEY(challan_id)
            REFERENCES challans(id)
            ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS invoices(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT UNIQUE,
        date TEXT,
        time TEXT,
        customer_id INTEGER,
        godown TEXT,

        gst_rate REAL DEFAULT 0,
        subtotal REAL DEFAULT 0,
        cgst REAL DEFAULT 0,
        sgst REAL DEFAULT 0,

        freight REAL DEFAULT 0,
        total REAL DEFAULT 0,
        payment_mode TEXT,
        received REAL DEFAULT 0,
        balance REAL DEFAULT 0,
        notes TEXT,

        FOREIGN KEY(customer_id) REFERENCES customers(id)
    );

    CREATE TABLE IF NOT EXISTS invoice_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER,
        product_id INTEGER,
        item_name TEXT,
        hsn_sac TEXT,
        qty REAL,
        unit TEXT,
        price REAL,
        amount REAL,
        weight_kg REAL,
        FOREIGN KEY(invoice_id)
            REFERENCES invoices(id)
            ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS invoice_challans(
        invoice_id INTEGER,
        challan_id INTEGER,
        PRIMARY KEY(invoice_id, challan_id),
        FOREIGN KEY(invoice_id) REFERENCES invoices(id),
        FOREIGN KEY(challan_id) REFERENCES challans(id)
    );

    CREATE TABLE IF NOT EXISTS customer_godowns(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        godown_name TEXT NOT NULL,
        UNIQUE(customer_id, godown_name),
        FOREIGN KEY(customer_id)
            REFERENCES customers(id)
            ON DELETE CASCADE
    );

    -- GLOBAL Godowns list (not tied to any single customer any more).
    -- Product Master's "+" popup, and the Challan / Invoice screens,
    -- all read/write this same table.
    CREATE TABLE IF NOT EXISTS godowns(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    );
    """

    with conn() as c:
        c.executescript(sql)

        # IMPORTANT: repair a possibly-stale `godown_products` table
        # (created by an older build of the app against a different
        # schema) BEFORE the "CREATE TABLE IF NOT EXISTS" for it below,
        # since that statement is a no-op once the table already exists
        # under any schema, correct or not.
        _repair_godown_products_table(c)

        c.execute('''
            CREATE TABLE IF NOT EXISTS godown_products(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                godown_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                UNIQUE(godown_id, product_id),
                FOREIGN KEY(godown_id)
                    REFERENCES godowns(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(product_id)
                    REFERENCES products(id)
                    ON DELETE CASCADE
            )
        ''')

        # Safe migrations for old databases.
        _add_column_if_missing(c, "customers", "email", "TEXT")

        _add_column_if_missing(
            c, "quotations", "shipping", "REAL DEFAULT 0"
        )
        _add_column_if_missing(
            c, "quotations", "place_of_supply", "TEXT"
        )
        _add_column_if_missing(
            c, "quotations", "time", "TEXT"
        )

        _add_column_if_missing(c, "challans", "time", "TEXT")
        _add_column_if_missing(c, "challans", "godown", "TEXT")
        _add_column_if_missing(
            c, "challans", "gst_mode", "TEXT DEFAULT 'NO_GST'"
        )

        _add_column_if_missing(c, "invoices", "time", "TEXT")
        _add_column_if_missing(c, "invoices", "godown", "TEXT")

        # Payment Mode (Cash / Credit / NEFT) for Challan and Invoice.
        # Old rows keep NULL/blank until they are edited and saved again.
        _add_column_if_missing(c, "challans", "payment_mode", "TEXT")
        _add_column_if_missing(c, "invoices", "payment_mode", "TEXT")

        # Vehicle (optional free text) for Challan and Invoice.
        _add_column_if_missing(c, "challans", "vehicle", "TEXT")
        _add_column_if_missing(c, "invoices", "vehicle", "TEXT")

        # ---- Migrate old per-customer Godown names into the new GLOBAL
        # ---- godowns table (one-time, safe to re-run: INSERT OR IGNORE).
        # No data is deleted; customer_godowns is left untouched so any
        # old code/reports that still read it keep working.
        try:
            old_names = c.execute(
                "SELECT DISTINCT godown_name FROM customer_godowns "
                "WHERE godown_name IS NOT NULL AND TRIM(godown_name) != ''"
            ).fetchall()
            for row in old_names:
                name = (row["godown_name"] or "").strip()
                if name:
                    c.execute(
                        "INSERT OR IGNORE INTO godowns(name) VALUES(?)",
                        (name,)
                    )
        except sqlite3.Error:
            pass

        # Existing challans are now treated as WITHOUT GST.
        # Old columns remain in the DB so no data shifts.
        c.execute("""
            UPDATE challans
            SET
                gst_rate = 0,
                cgst = 0,
                sgst = 0,
                gst_mode = 'NO_GST'
        """)

        # Do not allow NULL numeric values in old records.
        c.execute("""
            UPDATE challans
            SET
                subtotal = COALESCE(subtotal, 0),
                freight = COALESCE(freight, 0),
                total = COALESCE(total, 0),
                freight_rate = COALESCE(freight_rate, 0)
        """)

        c.execute("""
            UPDATE quotation_items
            SET
                qty = COALESCE(qty, 0),
                price = COALESCE(price, 0),
                amount = COALESCE(amount, 0),
                weight_kg = COALESCE(weight_kg, 0)
        """)

        c.execute("""
            UPDATE challan_items
            SET
                qty = COALESCE(qty, 0),
                price = COALESCE(price, 0),
                amount = COALESCE(amount, 0),
                weight_kg = COALESCE(weight_kg, 0)
        """)

        c.execute("""
            UPDATE invoice_items
            SET
                qty = COALESCE(qty, 0),
                price = COALESCE(price, 0),
                amount = COALESCE(amount, 0),
                weight_kg = COALESCE(weight_kg, 0)
        """)

    _make_backup()


def ensure_godown(name):
    """
    Make sure a Godown with this exact name exists in the GLOBAL
    `godowns` table, and return its id. Safe to call from any screen
    right before mapping a product to it, so a stale/typed name can
    never cause a FOREIGN KEY failure on godown_products.
    """
    name = (name or "").strip()
    if not name:
        return None
    with conn() as c:
        row = c.execute(
            "SELECT id FROM godowns WHERE lower(name)=lower(?)", (name,)
        ).fetchone()
        if row:
            return row["id"]
        cur = c.execute("INSERT INTO godowns(name) VALUES(?)", (name,))
        return cur.lastrowid


def next_number(table, prefix, width=4):
    """
    Generate the next number using the latest row id.
    """
    allowed_tables = {
        "customers",
        "products",
        "routes",
        "quotations",
        "quotation_items",
        "challans",
        "challan_items",
        "invoices",
        "invoice_items",
        "invoice_challans",
        "customer_godowns",
        "godowns",
        "godown_products",
    }

    if table not in allowed_tables:
        raise ValueError(f"Invalid table name: {table}")

    with conn() as c:
        row = c.execute(
            f"SELECT id FROM {table} ORDER BY id DESC LIMIT 1"
        ).fetchone()

        next_id = (row["id"] + 1) if row else 1

    return f"{prefix}{next_id:0{width}d}"


def backup_database():
    """
    Create and return the database backup path.
    """
    _make_backup()
    return BACKUP_PATH


def restore_database():
    """
    Restore the database from billing_backup.db.
    """
    _ensure_data_dir()

    if not os.path.exists(BACKUP_PATH):
        raise FileNotFoundError(
            "billing_backup.db was not found."
        )

    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            raise PermissionError(
                "Close the application before restoring the database."
            )

    shutil.copy2(BACKUP_PATH, DB_PATH)

    return DB_PATH


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
    print(f"Database path: {DB_PATH}")
    print(f"Backup path: {BACKUP_PATH}")
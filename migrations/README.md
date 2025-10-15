# Database Migrations

## Quick Start

### Apply Migration to Supabase

1. Open your Supabase project dashboard
2. Go to **SQL Editor** (left sidebar)
3. Click **New Query**
4. Copy the entire content of `001_initial_schema.sql`
5. Paste into the editor
6. Click **Run** (or press Cmd/Ctrl + Enter)
7. You should see "Success. No rows returned"

### Verify Migration

Run this query in SQL Editor:
```sql
SELECT * FROM schema_migrations;
```

You should see:
```
version | name                | applied_at
--------|---------------------|-------------------
1       | 001_initial_schema  | 2025-10-15 ...
```

### Check Table Structure

```sql
\d agent_states
```

Or:
```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'agent_states';
```

## Migration History

| Version | File | Description | Date |
|---------|------|-------------|------|
| 001 | `001_initial_schema.sql` | Initial agent_states table | 2025-10-15 |

## Future Migrations

To add a new migration:
1. Create `002_description.sql`
2. Add your ALTER TABLE or other changes
3. Include tracking: `INSERT INTO schema_migrations (version, name) VALUES (2, '002_description');`
4. Apply manually via Supabase SQL Editor

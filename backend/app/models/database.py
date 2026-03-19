"""
Database models / query helpers.

Sprint 1: Set up Supabase client initialisation and raw SQL helpers.
"""

# The project uses Supabase's Python client for database access.
# For complex queries (upserts with ON CONFLICT), we use raw SQL
# via supabase.rpc() or the postgrest client.
#
# No ORM (SQLAlchemy) is used — the schema is managed via SQL
# migrations in supabase/migrations/.

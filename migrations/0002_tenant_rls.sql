-- Enforce tenant isolation for the non-owner application database role.
-- The API must set rag.organization_id locally in each transaction from a
-- verified identity. Missing context intentionally matches no tenant rows.
BEGIN;

DO $create_role$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_app') THEN
        EXECUTE 'CREATE ROLE rag_app NOLOGIN';
    END IF;
END;
$create_role$;

GRANT USAGE ON SCHEMA rag TO rag_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA rag TO rag_app;
REVOKE ALL ON rag.schema_migrations FROM rag_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA rag
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rag_app;

ALTER TABLE rag.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.organizations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON rag.organizations
    USING (id = NULLIF(current_setting('rag.organization_id', true), '')::uuid)
    WITH CHECK (id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);

ALTER TABLE rag.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.users FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON rag.users
    USING (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);

ALTER TABLE rag.access_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.access_groups FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON rag.access_groups
    USING (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);

ALTER TABLE rag.user_group_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.user_group_memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON rag.user_group_memberships
    USING (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);

ALTER TABLE rag.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.documents FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON rag.documents
    USING (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);

ALTER TABLE rag.document_access_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.document_access_groups FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON rag.document_access_groups
    USING (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);

ALTER TABLE rag.ingestion_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.ingestion_jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON rag.ingestion_jobs
    USING (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);

ALTER TABLE rag.outbox_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.outbox_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON rag.outbox_events
    USING (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);

ALTER TABLE rag.document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.document_chunks FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON rag.document_chunks
    USING (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);

INSERT INTO rag.schema_migrations (version) VALUES ('0002_tenant_rls');
COMMIT;

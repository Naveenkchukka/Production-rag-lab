-- Make document and chunk reads require an active user's document group.
-- The API must set both GUCs transaction-locally from a verified identity.
BEGIN;

DROP POLICY tenant_scope ON rag.documents;
CREATE POLICY documents_select_by_group ON rag.documents
    FOR SELECT
    USING (
        organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid
        AND EXISTS (
            SELECT 1
            FROM rag.document_access_groups dag
            JOIN rag.user_group_memberships ugm
              ON ugm.organization_id = dag.organization_id
             AND ugm.group_id = dag.group_id
            JOIN rag.users u
              ON u.organization_id = ugm.organization_id
             AND u.id = ugm.user_id
            WHERE dag.organization_id = rag.documents.organization_id
              AND dag.document_id = rag.documents.id
              AND ugm.user_id = NULLIF(current_setting('rag.user_id', true), '')::uuid
              AND u.status = 'active'
        )
    );
CREATE POLICY documents_insert_tenant ON rag.documents
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);
CREATE POLICY documents_update_tenant ON rag.documents
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);
CREATE POLICY documents_delete_tenant ON rag.documents
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);

DROP POLICY tenant_scope ON rag.document_chunks;
CREATE POLICY chunks_select_by_document_group ON rag.document_chunks
    FOR SELECT
    USING (
        organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid
        AND EXISTS (
            SELECT 1
            FROM rag.documents d
            WHERE d.organization_id = rag.document_chunks.organization_id
              AND d.id = rag.document_chunks.document_id
        )
    );
CREATE POLICY chunks_insert_tenant ON rag.document_chunks
    FOR INSERT
    WITH CHECK (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);
CREATE POLICY chunks_update_tenant ON rag.document_chunks
    FOR UPDATE
    USING (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);
CREATE POLICY chunks_delete_tenant ON rag.document_chunks
    FOR DELETE
    USING (organization_id = NULLIF(current_setting('rag.organization_id', true), '')::uuid);

INSERT INTO rag.schema_migrations (version) VALUES ('0003_document_group_rls');
COMMIT;

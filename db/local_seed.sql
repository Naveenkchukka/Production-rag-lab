-- Local-only seed for the fictional Nimbu Mart course corpus.
-- Safe to reapply: organization and access-group rows are upserted by stable keys.
BEGIN;

INSERT INTO rag.organizations (id, slug, name)
VALUES (
    '819e5ef7-fb19-4b82-8c50-b9f44e93fa9b',
    'nimbu-sandbox',
    'Nimbu Mart (Fictional Training Data)'
)
ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name;

INSERT INTO rag.access_groups (id, organization_id, name)
VALUES
    ('f013d904-e071-4ee1-b2f2-3fa9ab4d80d0', '819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', 'public'),
    ('67cb957a-1e4f-4fc9-81b7-e17ef2460001', '819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', 'employees'),
    ('67cb957a-1e4f-4fc9-81b7-e17ef2460002', '819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', 'hr')
ON CONFLICT (organization_id, name) DO NOTHING;

-- Local-only identities for verifying document-group access. These are not
-- authentication credentials; the API will later derive user IDs from auth.
INSERT INTO rag.users (id, organization_id, auth_subject, status)
VALUES
    ('10000000-0000-4000-8000-000000000001', '819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', 'local-demo-public', 'active'),
    ('10000000-0000-4000-8000-000000000002', '819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', 'local-demo-employee', 'active'),
    ('10000000-0000-4000-8000-000000000003', '819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', 'local-demo-hr', 'active'),
    ('10000000-0000-4000-8000-000000000004', '819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', 'local-ingestion-worker', 'active')
ON CONFLICT (organization_id, auth_subject) DO NOTHING;

INSERT INTO rag.user_group_memberships (organization_id, user_id, group_id)
VALUES
    ('819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', '10000000-0000-4000-8000-000000000001', 'f013d904-e071-4ee1-b2f2-3fa9ab4d80d0'),
    ('819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', '10000000-0000-4000-8000-000000000002', 'f013d904-e071-4ee1-b2f2-3fa9ab4d80d0'),
    ('819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', '10000000-0000-4000-8000-000000000002', '67cb957a-1e4f-4fc9-81b7-e17ef2460001'),
    ('819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', '10000000-0000-4000-8000-000000000003', 'f013d904-e071-4ee1-b2f2-3fa9ab4d80d0'),
    ('819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', '10000000-0000-4000-8000-000000000003', '67cb957a-1e4f-4fc9-81b7-e17ef2460001'),
    ('819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', '10000000-0000-4000-8000-000000000003', '67cb957a-1e4f-4fc9-81b7-e17ef2460002'),
    ('819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', '10000000-0000-4000-8000-000000000004', 'f013d904-e071-4ee1-b2f2-3fa9ab4d80d0'),
    ('819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', '10000000-0000-4000-8000-000000000004', '67cb957a-1e4f-4fc9-81b7-e17ef2460001'),
    ('819e5ef7-fb19-4b82-8c50-b9f44e93fa9b', '10000000-0000-4000-8000-000000000004', '67cb957a-1e4f-4fc9-81b7-e17ef2460002')
ON CONFLICT DO NOTHING;

COMMIT;

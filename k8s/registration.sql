-- Seed for the marketplace row of this module. defineModule() in src/Module.tsx is the runtime
-- source of truth: every publish overwrites roles, route and version. Keep both in agreement.
-- Idempotent; the publisher repository (source_repo) must be set for the OIDC publish to be accepted.
BEGIN;
INSERT INTO marketplace_modules (
    id, name, display_name, description, remote_entry_url, scope, exposed_module, version, author,
    category, icon_url, route_path, label, required_plan_level, is_local, is_active,
    required_roles, metadata
) VALUES (
    'fast-navigator', 'fast-navigator', 'FaST · Plan de abonado',
    'Legal fertilisation plan per farm and campaign (RD 1051/2022).',
    '/modules/fast-navigator/mf-manifest.json', 'fast-navigator', './Module', '1.0.0', 'nkz-os',
    'analytics', 'leaf', '/fast-navigator', 'FaST · Plan de abonado', 0, false, true,
    ARRAY['Farmer', 'TechnicalConsultant', 'TenantAdmin'],
    '{
      "icon": "leaf",
      "api_prefix": "/api/fast",
      "backend_service": "http://fast-navigator-service:8000",
      "backend_mount": "/api/fast",
      "requires_auth": true,
      "source_repo": "nkz-os/nkz-module-fast-navigator",
      "deploy_method": "dist_endpoint",
      "hostApiVersion": "^2.0.0",
      "description_i18n": {
        "es": "Plan de abonado legal por explotación y campaña (RD 1051/2022): necesidades de N, P y K con su procedencia.",
        "en": "Legal fertilisation plan per farm and campaign (RD 1051/2022): N, P and K needs with their sources.",
        "eu": "Ustiategi eta kanpaina bakoitzeko ongarritze-plan legala (RD 1051/2022): N, P eta K beharrak, iturriekin.",
        "fr": "Plan de fertilisation réglementaire par exploitation et campagne (RD 1051/2022) : besoins en N, P et K avec leurs sources.",
        "ca": "Pla d''adobat legal per explotació i campanya (RD 1051/2022): necessitats de N, P i K amb les seves fonts.",
        "pt": "Plano de fertilização legal por exploração e campanha (RD 1051/2022): necessidades de N, P e K com as suas fontes."
      }
    }'::jsonb
) ON CONFLICT (id) DO UPDATE SET
    display_name = EXCLUDED.display_name, description = EXCLUDED.description,
    remote_entry_url = EXCLUDED.remote_entry_url, scope = EXCLUDED.scope,
    exposed_module = EXCLUDED.exposed_module, icon_url = EXCLUDED.icon_url,
    route_path = EXCLUDED.route_path, label = EXCLUDED.label,
    required_roles = EXCLUDED.required_roles, is_active = true,
    metadata = COALESCE(marketplace_modules.metadata, '{}'::jsonb) || EXCLUDED.metadata,
    updated_at = NOW();
COMMIT;

# Trial data boundary

Allowed: repository fixtures, generated outputs, and publicly accessible procurement sources documented in `sources.yaml`.

Forbidden: Chromie production/staging databases, Supabase projects, internal APIs, customer files, customer prompts, secrets, production schemas, copied database dumps, and employee credentials.

Do not request production access. Do not add secrets to git. A public-source adapter must be optional and must store its raw response outside git. If a source requires login, payment, CAPTCHA bypass, or terms-violating automation, stop and document it.


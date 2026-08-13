# Security Policy

## Supported versions

Security fixes are applied to the latest minor release on the `main` branch.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub private
vulnerability reporting from the repository's **Security** tab and include:

- affected version or commit;
- reproduction steps or a minimal proof of concept;
- expected impact;
- suggested mitigation, when available.

Never include real credentials, customer data, or unauthorized targets. The
demo tools operate on synthetic in-memory data only.

## Security model

The optional API key is intentionally minimal and is not a replacement for an
identity provider, network policy, secret manager, or per-tool authorization.
Production deployments should place the service behind authenticated ingress,
use durable external systems, and replace the in-process lock manager when
running multiple replicas.

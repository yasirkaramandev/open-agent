# OAuth threat model

- Authorization uses server-generated state, nonce, and PKCE. State is constant-time compared and
  single-use. Sessions rotate after callback.
- Redirect URI scheme, authority, and path must exactly match the configured URI; query and fragment
  injection are rejected.
- The initial grant requests identity plus YouTube read scope. Write scopes are incremental and
  contextual.
- Tokens are exchanged server-side and envelope-encrypted. The database stores ciphertext,
  credential revision, key version, expiry, granted scopes, and revocation time.
- Cookie settings are Secure, HttpOnly, SameSite=Lax with CSRF tokens on mutating requests.
- Object authorization checks workspace membership and role on every account/proposal resource.
- Disconnect revokes Google consent where requested, deletes encrypted credentials, cancels pending
  writes, and schedules bounded cached-data deletion.
- OAuth and YouTube HTTP clients enforce HTTPS host allowlists, response size limits, timeouts, and
  no redirects to untrusted hosts.

The example does not implement Google login automation and never handles a Google account password
or browser session material.

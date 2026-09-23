(() => {
  const issuer = 'https://idp.omnilink.ch/realms/omnilink';
  const storageKey = 'middleware-keycloak-oidc';
  const callbackPath = `${window.location.origin}${window.location.pathname}`;
  let token = sessionStorage.getItem(`${storageKey}:token`) || '';
  let expiresAt = Number(sessionStorage.getItem(`${storageKey}:expiresAt`) || 0);

  function base64Url(bytes) {
    let value = '';
    bytes.forEach(byte => { value += String.fromCharCode(byte); });
    return btoa(value).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function randomString(length = 64) {
    const bytes = new Uint8Array(length);
    crypto.getRandomValues(bytes);
    return base64Url(bytes);
  }

  async function challenge(verifier) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    return base64Url(new Uint8Array(digest));
  }

  function setStatus(message, error = false) {
    const element = document.getElementById('keycloakStatus');
    if (element) {
      element.textContent = message;
      element.dataset.error = error ? 'true' : 'false';
    }
  }

  function clientId() {
    return document.getElementById('keycloakClientId')?.value.trim() || sessionStorage.getItem(`${storageKey}:clientId`) || '';
  }

  async function login() {
    const id = clientId();
    if (!id) throw new Error('Bitte zuerst die Keycloak Client-ID eingeben.');
    sessionStorage.setItem(`${storageKey}:clientId`, id);
    const verifier = randomString();
    const state = randomString(32);
    sessionStorage.setItem(`${storageKey}:verifier`, verifier);
    sessionStorage.setItem(`${storageKey}:state`, state);
    const params = new URLSearchParams({
      client_id: id,
      redirect_uri: callbackPath,
      response_type: 'code',
      scope: 'openid profile email',
      state,
      code_challenge: await challenge(verifier),
      code_challenge_method: 'S256'
    });
    window.location.assign(`${issuer}/protocol/openid-connect/auth?${params}`);
  }

  async function completeLogin() {
    const query = new URLSearchParams(window.location.search);
    const code = query.get('code');
    if (!code) return;
    if (query.get('state') !== sessionStorage.getItem(`${storageKey}:state`)) throw new Error('Ungültiger Keycloak-State.');
    const verifier = sessionStorage.getItem(`${storageKey}:verifier`);
    const response = await fetch(`${issuer}/protocol/openid-connect/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ grant_type: 'authorization_code', client_id: clientId(), redirect_uri: callbackPath, code, code_verifier: verifier })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error_description || `Keycloak Token-Fehler (HTTP ${response.status}).`);
    token = data.access_token;
    expiresAt = Date.now() + (Number(data.expires_in || 300) * 1000);
    sessionStorage.setItem(`${storageKey}:token`, token);
    sessionStorage.setItem(`${storageKey}:expiresAt`, String(expiresAt));
    sessionStorage.removeItem(`${storageKey}:verifier`);
    sessionStorage.removeItem(`${storageKey}:state`);
    window.history.replaceState({}, document.title, window.location.pathname + window.location.hash);
    setStatus('Keycloak-Token aktiv.');
  }

  function headers() {
    if (token && expiresAt > Date.now() + 5000) return { Authorization: `Bearer ${token}` };
    return {};
  }

  function logout() {
    token = '';
    expiresAt = 0;
    sessionStorage.removeItem(`${storageKey}:token`);
    sessionStorage.removeItem(`${storageKey}:expiresAt`);
    setStatus('Kein Keycloak-Token aktiv.');
  }

  window.keycloakAuthHeaders = headers;
  window.keycloakLogin = login;
  window.keycloakLogout = logout;
  window.addEventListener('DOMContentLoaded', async () => {
    const loginButton = document.getElementById('keycloakLoginBtn');
    const logoutButton = document.getElementById('keycloakLogoutBtn');
    loginButton?.addEventListener('click', () => login().catch(error => setStatus(error.message, true)));
    logoutButton?.addEventListener('click', logout);
    try {
      await completeLogin();
      if (token && expiresAt > Date.now()) setStatus('Keycloak-Token aktiv.');
    } catch (error) {
      setStatus(error.message, true);
    }
  });
})();

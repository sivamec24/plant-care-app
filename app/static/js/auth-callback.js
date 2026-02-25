/**
 * Supabase Auth Callback Handler
 *
 * Extracts auth tokens from URL hash and forwards to backend.
 * Runs on /auth/callback page only.
 *
 * Security notes:
 * - Tokens are never logged or stored in localStorage
 * - URL is cleared after extraction to prevent token leakage
 * - HTTPS enforced by Supabase and our CSP
 */
(function() {
  // --- Plant-themed loading messages ---
  const plantLoadingPhrases = [
    'Planting seeds…',
    'Watering your garden…',
    'Checking the soil…',
    'Letting roots grow…',
    'Nurturing seedlings…',
    'Adding fertilizer…',
    'Adjusting sunlight…',
    'Pruning branches…',
    'Harvesting results…',
    'Cultivating your space…'
  ];

  let loadingPhraseInterval = null;
  let currentPhraseIndex = 0;

  function rotateLoadingMessage() {
    const loadingPhrase = document.getElementById('loading-phrase');
    if (!loadingPhrase) return;

    currentPhraseIndex = (currentPhraseIndex + 1) % plantLoadingPhrases.length;
    loadingPhrase.textContent = plantLoadingPhrases[currentPhraseIndex];
  }

  function startLoadingRotation() {
    const loadingPhrase = document.getElementById('loading-phrase');
    if (!loadingPhrase) return;

    currentPhraseIndex = 0;
    loadingPhrase.textContent = plantLoadingPhrases[currentPhraseIndex];
    loadingPhraseInterval = setInterval(rotateLoadingMessage, 2000);
  }

  function stopLoadingRotation() {
    if (loadingPhraseInterval) {
      clearInterval(loadingPhraseInterval);
      loadingPhraseInterval = null;
    }
  }

  // Start rotating loading messages
  startLoadingRotation();

  const statusEl = document.getElementById('status-message');

  if (!statusEl) {
    // Status element not found, fail silently
    return;
  }

  // Extract tokens from URL hash
  const hash = window.location.hash.substring(1); // Remove leading #
  const params = new URLSearchParams(hash);

  const accessToken = params.get('access_token');
  const refreshToken = params.get('refresh_token');
  const errorCode = params.get('error_code');
  const errorDescription = params.get('error_description');

  // Handle errors from Supabase
  if (errorCode) {
    stopLoadingRotation();
    statusEl.setAttribute('role', 'alert');

    // Provide user-friendly error messages
    let userMessage = '';
    if (errorCode === 'otp_expired' || errorDescription.includes('expired') || errorDescription.includes('invalid')) {
      userMessage = 'This magic link has already been used or has expired. Please request a new one.';
    } else if (errorCode === 'access_denied') {
      userMessage = 'Access was denied. Please try signing up again.';
    } else {
      userMessage = 'Authentication failed: ' + (errorDescription || errorCode);
    }

    statusEl.textContent = userMessage + ' Redirecting to sign up in 3 seconds...';

    // Redirect to signup with error message after 3 seconds
    setTimeout(function() {
      window.location.href = '/auth/signup';
    }, 3000);
    return;
  }

  // Check if tokens present
  if (!accessToken) {
    stopLoadingRotation();
    statusEl.textContent = 'No authentication token found. Redirecting...';
    setTimeout(function() {
      window.location.href = '/auth/signup';
    }, 2000);
    return;
  }

  // Clear the hash from URL (security: don't leave tokens in address bar)
  history.replaceState(null, '', window.location.pathname);

  // Forward tokens to backend callback endpoint
  const callbackUrl = new URL('/auth/callback', window.location.origin);
  callbackUrl.searchParams.set('access_token', accessToken);
  if (refreshToken) {
    callbackUrl.searchParams.set('refresh_token', refreshToken);
  }

  // Preserve 'next' parameter if present
  const nextParam = params.get('next');
  if (nextParam) {
    callbackUrl.searchParams.set('next', nextParam);
  }

  statusEl.textContent = 'Finalizing authentication...';

  // Redirect to backend with tokens in query params (HTTPS only)
  window.location.href = callbackUrl.toString();
})();

/**
 * Return the stable identity that owns enterprise UI state.
 *
 * Supabase replaces the Session object whenever it refreshes an access token.
 * The user identity, however, remains unchanged. React effects that validate
 * enterprise access must depend on this value instead of the Session object so
 * a routine token refresh cannot unmount the active portal.
 */
export function getEnterpriseSessionIdentity(session) {
  const userId = session?.user?.id;
  return typeof userId === 'string' && userId.trim() ? userId : null;
}

const CURRENT_CONVERSATION_PREFIX = 'enterprise-kb:current-conversation:';

function getBrowserSessionStorage() {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null;
  }
}

function currentConversationKey(userId) {
  return `${CURRENT_CONVERSATION_PREFIX}${userId}`;
}

/** Read the active chat for this user and browser tab, if one was stored. */
export function getCurrentEnterpriseConversationId(
  userId,
  storage = getBrowserSessionStorage(),
) {
  if (!userId || !storage) return null;
  try {
    const value = storage.getItem(currentConversationKey(userId));
    return typeof value === 'string' && value.trim() ? value : null;
  } catch {
    return null;
  }
}

/** Persist or clear the active chat without making storage a hard dependency. */
export function setCurrentEnterpriseConversationId(
  userId,
  conversationId,
  storage = getBrowserSessionStorage(),
) {
  if (!userId || !storage) return;
  try {
    const key = currentConversationKey(userId);
    if (conversationId) storage.setItem(key, conversationId);
    else storage.removeItem(key);
  } catch {
    // Browsers can deny storage access. The in-memory chat must still work.
  }
}

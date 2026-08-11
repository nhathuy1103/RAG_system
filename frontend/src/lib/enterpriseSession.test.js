import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { describe, it } from 'node:test';

import {
  getCurrentEnterpriseConversationId,
  getEnterpriseSessionIdentity,
  setCurrentEnterpriseConversationId,
} from './enterpriseSession.js';

function sessionFor(userId, accessToken) {
  return {
    access_token: accessToken,
    refresh_token: `refresh-${accessToken}`,
    expires_at: 1_900_000_000,
    user: { id: userId },
  };
}

describe('getEnterpriseSessionIdentity', () => {
  it('stays stable when TOKEN_REFRESHED replaces the session for the same user', () => {
    const initialSession = sessionFor('user-1', 'access-token-before-refresh');
    const refreshedSession = sessionFor('user-1', 'access-token-after-refresh');

    assert.notDeepEqual(refreshedSession, initialSession);
    assert.equal(
      getEnterpriseSessionIdentity(refreshedSession),
      getEnterpriseSessionIdentity(initialSession),
    );
  });

  it('stays stable when SIGNED_IN is emitted again for the same user', () => {
    const currentSession = sessionFor('user-1', 'current-access-token');
    const repeatedSignedInSession = sessionFor('user-1', 'signed-in-access-token');

    assert.equal(getEnterpriseSessionIdentity(currentSession), 'user-1');
    assert.equal(getEnterpriseSessionIdentity(repeatedSignedInSession), 'user-1');
  });

  it('changes only when the authenticated user changes or signs out', () => {
    assert.equal(getEnterpriseSessionIdentity(sessionFor('user-1', 'token-1')), 'user-1');
    assert.equal(getEnterpriseSessionIdentity(sessionFor('user-2', 'token-2')), 'user-2');
    assert.equal(getEnterpriseSessionIdentity(null), null);
    assert.equal(getEnterpriseSessionIdentity({ user: null }), null);
  });
});

describe('current enterprise conversation storage', () => {
  function createMemoryStorage() {
    const values = new Map();
    return {
      getItem(key) {
        return values.get(key) ?? null;
      },
      setItem(key, value) {
        values.set(key, value);
      },
      removeItem(key) {
        values.delete(key);
      },
    };
  }

  it('isolates the active conversation by authenticated user', () => {
    const storage = createMemoryStorage();

    setCurrentEnterpriseConversationId('user-1', 'conversation-1', storage);
    setCurrentEnterpriseConversationId('user-2', 'conversation-2', storage);

    assert.equal(getCurrentEnterpriseConversationId('user-1', storage), 'conversation-1');
    assert.equal(getCurrentEnterpriseConversationId('user-2', storage), 'conversation-2');
    assert.equal(getCurrentEnterpriseConversationId('user-3', storage), null);
  });

  it('clears only the current user conversation', () => {
    const storage = createMemoryStorage();
    setCurrentEnterpriseConversationId('user-1', 'conversation-1', storage);
    setCurrentEnterpriseConversationId('user-2', 'conversation-2', storage);

    setCurrentEnterpriseConversationId('user-1', null, storage);

    assert.equal(getCurrentEnterpriseConversationId('user-1', storage), null);
    assert.equal(getCurrentEnterpriseConversationId('user-2', storage), 'conversation-2');
  });

  it('fails safely when browser storage access is denied', () => {
    const deniedStorage = {
      getItem() {
        throw new Error('storage denied');
      },
      setItem() {
        throw new Error('storage denied');
      },
      removeItem() {
        throw new Error('storage denied');
      },
    };

    assert.equal(getCurrentEnterpriseConversationId('user-1', deniedStorage), null);
    assert.doesNotThrow(() => {
      setCurrentEnterpriseConversationId('user-1', 'conversation-1', deniedStorage);
      setCurrentEnterpriseConversationId('user-1', null, deniedStorage);
    });
  });
});

describe('App enterprise-session lifecycle contract', () => {
  it('keys enterprise account verification by user identity, not the session object', async () => {
    const appSource = await readFile(new URL('../App.tsx', import.meta.url), 'utf8');

    assert.match(
      appSource,
      /getEnterpriseSessionIdentity\(session\)/,
      'App must derive a stable identity from the Supabase session',
    );
    assert.match(
      appSource,
      /\}, \[enterpriseSessionIdentity\]\);/,
      'enterprise verification must rerun only when the authenticated user changes',
    );
    assert.doesNotMatch(
      appSource,
      /\}, \[session\]\);/,
      'depending on the full session remounts the portal after token refresh',
    );
  });
});

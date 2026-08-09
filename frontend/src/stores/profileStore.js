import { create } from 'zustand';
import { getProfile, updateProfile } from '../lib/api';

export const useProfileStore = create((set) => ({
  profile: null,
  loading: false,
  error: null,

  fetchProfile: async () => {
    set({ loading: true, error: null });
    try {
      const profile = await getProfile();
      set({ profile, loading: false });
      return profile;
    } catch (err) {
      set({ error: err.message, loading: false });
      throw err;
    }
  },

  saveProfile: async (data) => {
    const updated = await updateProfile(data);
    set({ profile: updated });
    return updated;
  },
}));

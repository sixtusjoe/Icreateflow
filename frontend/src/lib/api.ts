import axios from "axios";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
});

// Attach JWT token to all requests
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("icreate_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// Redirect to login on 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("icreate_token");
      if (window.location.pathname !== "/login" && window.location.pathname !== "/register") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

// --- Auth ---
export const authLogin = (email: string, password: string) =>
  api.post("/api/auth/login", { email, password }).then((r) => r.data);
export const authRegister = (email: string, password: string, name: string) =>
  api.post("/api/auth/register", { email, password, name }).then((r) => r.data);
export const authMe = () => api.get("/api/auth/me").then((r) => r.data);
export const updateProfile = (data: { name?: string; email?: string }) =>
  api.put("/api/auth/profile", data).then((r) => r.data);
export const changePassword = (current_password: string, new_password: string) =>
  api.put("/api/auth/password", { current_password, new_password }).then((r) => r.data);

// --- Admin ---
export const getUsers = () => api.get("/api/admin/users").then((r) => r.data);
export const updateUser = (id: number, data: { role?: string; status?: string; name?: string }) =>
  api.put(`/api/admin/users/${id}`, data).then((r) => r.data);
export const approveUser = (id: number) =>
  api.post(`/api/admin/users/${id}/approve`).then((r) => r.data);
export const getSiteConfig = () => api.get("/api/admin/site-config").then((r) => r.data);
export const updateSiteConfig = (key: string, value: string) =>
  api.put("/api/admin/site-config", { key, value }).then((r) => r.data);
export const getAdminStats = () => api.get("/api/admin/stats").then((r) => r.data);
export const getCacheStats = () => api.get("/api/admin/cache-stats").then((r) => r.data);
export const clearCache = (target: "video_renders" | "caption_variants" | "passthrough_clips" | "all", older_than_days?: number) =>
  api.post("/api/admin/cache/clear", { target, older_than_days: older_than_days ?? null }).then((r) => r.data);
export const getBrandCacheStats = () => api.get("/api/admin/brand-cache-stats").then((r) => r.data);
export const clearBrandCache = (target: "output" | "uploads" | "all", older_than_date?: string) =>
  api.post("/api/admin/brand-cache/clear", { target, older_than_date: older_than_date ?? null }).then((r) => r.data);

// --- User Settings (per-user API keys) ---
export const getUserSettings = () => api.get("/api/user-settings").then((r) => r.data);
export const updateUserSetting = (key: string, value: string) =>
  api.put("/api/user-settings", { key, value }).then((r) => r.data);

// --- Brands ---
export const getBrands = () => api.get("/api/brands").then((r) => r.data);
export const getBrand = (id: number) =>
  api.get(`/api/brands/${id}`).then((r) => r.data);
export const createBrand = (data: {
  name: string;
  slug: string;
  background_color?: string;
  timezone?: string;
  default_post_times?: string;
}) => api.post("/api/brands", data).then((r) => r.data);
export const updateBrand = (
  id: number,
  data: Record<string, string | undefined>
) => api.put(`/api/brands/${id}`, data).then((r) => r.data);
export const deleteBrand = (id: number) =>
  api.delete(`/api/brands/${id}`).then((r) => r.data);

// --- Accounts ---
export const createAccount = (
  brandId: number,
  data: { name: string; role?: string; tiktok_handle?: string; youtube_handle?: string; instagram_handle?: string; facebook_handle?: string }
) => api.post(`/api/brands/${brandId}/accounts`, data).then((r) => r.data);
export const updateAccount = (
  id: number,
  data: Record<string, string | undefined>
) => api.put(`/api/accounts/${id}`, data).then((r) => r.data);
export const deleteAccount = (id: number) =>
  api.delete(`/api/accounts/${id}`).then((r) => r.data);

// --- Posts ---
export const getPosts = (params?: { brand_id?: number; date?: string }) =>
  api.get("/api/posts", { params }).then((r) => r.data);
export const getPost = (id: number) =>
  api.get(`/api/posts/${id}`).then((r) => r.data);
export const deletePost = (id: number) =>
  api.delete(`/api/posts/${id}`).then((r) => r.data);

export const importTikTokPost = (data: {
  tiktok_url: string;
  brand_id: number;
  post_number?: number;
  caption?: string;
}) => api.post("/api/posts/import", data).then((r) => r.data);

export const uploadSlidesManually = (
  brandId: number,
  postNumber: number,
  caption: string,
  files: File[]
) => {
  const form = new FormData();
  form.append("brand_id", String(brandId));
  form.append("post_number", String(postNumber));
  form.append("caption", caption);
  files.forEach((f) => form.append("files", f));
  return api.post("/api/posts/upload-slides", form).then((r) => r.data);
};

// --- Slides ---
export const updateSlide = (
  postId: number,
  slideNumber: number,
  data: {
    type?: string;
    has_face?: boolean;
    title_text?: string;
    body_text?: string;
    cta_text?: string;
  }
) => api.put(`/api/posts/${postId}/slides/${slideNumber}`, data).then((r) => r.data);

export const uploadSlideImage = (
  postId: number,
  slideNumber: number,
  file: File
) => {
  const form = new FormData();
  form.append("file", file);
  return api
    .post(`/api/posts/${postId}/slides/${slideNumber}/image`, form)
    .then((r) => r.data);
};

// --- Variations ---
export const updateVariation = (id: number, action: string) =>
  api.put(`/api/variations/${id}/action`, { action }).then((r) => r.data);

export const uploadVariationImage = (id: number, file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.post(`/api/variations/${id}/upload`, form).then((r) => r.data);
};

export const generateVariationImage = (
  id: number,
  prompt: string,
  aspect_ratio: string = "3:4"
) =>
  api
    .post(`/api/variations/${id}/generate`, { prompt, aspect_ratio })
    .then((r) => r.data);

export const approveVariation = (id: number) =>
  api.post(`/api/variations/${id}/approve`).then((r) => r.data);

// --- Generation ---
export const generatePost = (postId: number) =>
  api.post(`/api/posts/${postId}/generate`).then((r) => r.data);
export const getGenerationStatus = (postId: number) =>
  api.get(`/api/posts/${postId}/generate/status`).then((r) => r.data);

// --- Schedule ---
export const schedulePost = (
  postId: number,
  data: { scheduled_time?: string; caption?: string; music_track_id?: number }
) => api.put(`/api/posts/${postId}/schedule`, data).then((r) => r.data);
export const getSchedule = (brandId?: number) =>
  api.get("/api/schedule", { params: brandId ? { brand_id: brandId } : {} }).then((r) => r.data);
export const postNow = (postId: number) =>
  api.post(`/api/posts/${postId}/post-now`).then((r) => r.data);

// --- Music ---
export const getMusicTracks = (platform?: string) =>
  api.get("/api/music", { params: platform ? { platform } : {} }).then((r) => r.data);
export const uploadMusicTrack = (name: string, genre: string, file: File) => {
  const form = new FormData();
  form.append("name", name);
  form.append("genre", genre);
  form.append("file", file);
  return api.post("/api/music", form).then((r) => r.data);
};
export const updateMusicTrack = (
  id: number,
  data: { platforms_allowed?: string; name?: string; genre?: string },
) => api.put(`/api/music/${id}`, data).then((r) => r.data);
export const deleteMusicTrack = (id: number) =>
  api.delete(`/api/music/${id}`).then((r) => r.data);

// --- Re-run OCR ---
export const rerunOcr = (postId: number) =>
  api.post(`/api/posts/${postId}/rerun-ocr`).then((r) => r.data);

// --- Output slides preview ---
export const getOutputSlides = (postId: number) =>
  api.get(`/api/posts/${postId}/output-slides`).then((r) => r.data);

export const regenerateSlide = (postId: number, data: {
  account_id: number; slide_number: number;
  title_text?: string; body_text?: string; cta_text?: string;
  font_size_title?: number; font_size_body?: number; font_size_cta?: number;
  y_ratio_title?: number; y_ratio_body?: number; y_ratio_cta?: number;
  x_ratio_title?: number; x_ratio_body?: number; x_ratio_cta?: number;
  scale_title?: number; scale_body?: number; scale_cta?: number;
  font_weight?: string; text_style?: string;
}) => api.post(`/api/posts/${postId}/regenerate-slide`, data).then((r) => r.data);

export const regenerateVideo = (
  postId: number,
  accountId: number,
  platform?: "youtube" | "instagram" | "facebook",
) =>
  api
    .post(`/api/posts/${postId}/regenerate-video`, { account_id: accountId, platform })
    .then((r) => r.data);

export const updatePostMusic = (
  postId: number,
  data: {
    youtube_music_track_id?: number | null;
    instagram_music_track_id?: number | null;
    facebook_music_track_id?: number | null;
  },
) => api.put(`/api/posts/${postId}/music`, data).then((r) => r.data);

// --- Downloads ---
export const downloadFile = async (postId: number, accountId?: number) => {
  const url = accountId
    ? `/api/posts/${postId}/download/${accountId}`
    : `/api/posts/${postId}/download`;
  const resp = await api.get(url, { responseType: "blob" });
  const blob = new Blob([resp.data], { type: "application/zip" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  const disposition = resp.headers["content-disposition"];
  const filename = disposition?.match(/filename="?(.+?)"?$/)?.[1] || `post_${postId}.zip`;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
};
export const getDownloadUrl = (postId: number, accountId?: number) =>
  accountId
    ? `${api.defaults.baseURL}/api/posts/${postId}/download/${accountId}`
    : `${api.defaults.baseURL}/api/posts/${postId}/download`;

// --- Settings (global) ---
export const getSettings = () =>
  api.get("/api/settings").then((r) => r.data);
export const updateSetting = (key: string, value: string) =>
  api.put("/api/settings", { key, value }).then((r) => r.data);

// --- Stats ---
export const getStats = () => api.get("/api/stats").then((r) => r.data);

// --- File URL helper ---
// Encode per segment so forward-slashes remain literal (Apache's AllowEncodedSlashes=Off
// rejects %2F in URL paths, which would break reverse-proxy file serving otherwise).
export const fileUrl = (path: string) =>
  `${api.defaults.baseURL}/api/files/${path
    .split("/")
    .filter(Boolean)
    .map(encodeURIComponent)
    .join("/")}`;

// --- Admin: cross-user resource management ---
export const getAdminBrands = () => api.get("/api/admin/brands").then((r) => r.data);
export const deleteAdminBrand = (id: number) =>
  api.delete(`/api/admin/brands/${id}`).then((r) => r.data);
export const getAdminPosts = (params?: { user_id?: number; brand_id?: number; status?: string }) =>
  api.get("/api/admin/posts", { params }).then((r) => r.data);
export const deleteAdminPost = (id: number) =>
  api.delete(`/api/admin/posts/${id}`).then((r) => r.data);
export const getAdminAccounts = () => api.get("/api/admin/accounts").then((r) => r.data);
export const getAdminMusic = () => api.get("/api/admin/music").then((r) => r.data);
export const deleteAdminMusic = (id: number) =>
  api.delete(`/api/admin/music/${id}`).then((r) => r.data);
export const getAdminSchedule = () => api.get("/api/admin/schedule").then((r) => r.data);
export const getAdminApiKeys = () => api.get("/api/admin/api-keys").then((r) => r.data);
export const deleteAdminUser = (id: number) =>
  api.delete(`/api/admin/users/${id}`).then((r) => r.data);

// --- Admin: OAuth app credentials ---
export const getOAuthApps = () => api.get("/api/admin/oauth-apps").then((r) => r.data);
export const updateOAuthApp = (
  platform: string,
  data: { client_id?: string; client_secret?: string; api_key?: string; redirect_base?: string },
) => api.put(`/api/admin/oauth-apps/${platform}`, data).then((r) => r.data);

// --- OAuth connect (user-scoped) ---
// `kind` is "account" (brand accounts) or "variation" (artist accounts).
export const startOAuth = (
  platform: string,
  id: number,
  kind: "account" | "variation" = "account",
) => {
  const params = kind === "variation" ? { variation_id: id } : { account_id: id };
  return api.get(`/api/oauth/${platform}/start`, { params }).then((r) => r.data);
};
export const disconnectOAuth = (
  platform: string,
  id: number,
  kind: "account" | "variation" = "account",
) => {
  const params = kind === "variation" ? { variation_id: id } : { account_id: id };
  return api.post(`/api/oauth/${platform}/disconnect`, null, { params }).then((r) => r.data);
};

// --- Meta multi-asset assignment ---
// One Meta OAuth grant can authorize multiple Pages + IG accounts. After the
// popup posts the granted asset list, the user picks one and we finalize via
// this endpoint.
export type MetaAsset = {
  page_id: string | null;
  page_name: string | null;
  page_access_token: string | null;
  ig_user_id: string | null;
  ig_handle: string | null;
};
export const assignMetaAsset = (data: {
  assign_token: string;
  page_id?: string | null;
  ig_user_id?: string | null;
}) => api.post(`/api/oauth/meta/assign`, data).then((r) => r.data);

// --- Clipping: Artists ---
export const getArtists = () => api.get("/api/artists").then((r) => r.data);
export const getArtist = (id: number) => api.get(`/api/artists/${id}`).then((r) => r.data);
export const getArtistBySlug = (slug: string) =>
  api.get(`/api/artists/by-slug/${encodeURIComponent(slug)}`).then((r) => r.data);
export const createArtist = (data: {
  name: string;
  slug: string;
  timezone?: string;
  posts_per_day?: number;
  window_start?: string;
  window_end?: string;
}) => api.post("/api/artists", data).then((r) => r.data);
export const updateArtist = (id: number, data: Record<string, string | number | undefined>) =>
  api.put(`/api/artists/${id}`, data).then((r) => r.data);
export const deleteArtist = (id: number) =>
  api.delete(`/api/artists/${id}`).then((r) => r.data);

// --- Clipping: Variations ---
export const createVariation = (
  artistId: number,
  data: {
    name: string;
    tiktok_handle?: string;
    youtube_handle?: string;
    instagram_handle?: string;
    facebook_handle?: string;
  },
) => api.post(`/api/artists/${artistId}/variations`, data).then((r) => r.data);
export const updateArtistVariation = (id: number, data: Record<string, string | undefined>) =>
  api.put(`/api/variations/${id}`, data).then((r) => r.data);
export const deleteArtistVariation = (id: number) =>
  api.delete(`/api/variations/${id}`).then((r) => r.data);
export const refreshVariationProfile = (id: number) =>
  api.post(`/api/variations/${id}/refresh-profile`).then((r) => r.data);
export const refreshAccountProfile = (id: number) =>
  api.post(`/api/accounts/${id}/refresh-profile`).then((r) => r.data);

// --- Clipping: Clips ---
export const listClips = (artistId: number) =>
  api.get(`/api/artists/${artistId}/clips`).then((r) => r.data);
export const uploadClip = (artistId: number, file: File, caption = "") => {
  const form = new FormData();
  form.append("file", file);
  form.append("caption", caption);
  return api.post(`/api/artists/${artistId}/clips/upload`, form).then((r) => r.data);
};
export const syncGdriveClips = (artistId: number, folder_url: string) =>
  api.post(`/api/artists/${artistId}/clips/gdrive`, { folder_url }).then((r) => r.data);
export const updateClip = (id: number, data: { caption?: string }) =>
  api.put(`/api/clips/${id}`, data).then((r) => r.data);
export const deleteClip = (id: number) =>
  api.delete(`/api/clips/${id}`).then((r) => r.data);

// --- Clipping: Dashboard + feed ---
export const getArtistDashboard = (id: number) =>
  api.get(`/api/artists/${id}/dashboard`).then((r) => r.data);
export const getArtistFeed = (id: number) =>
  api.get(`/api/artists/${id}/feed`).then((r) => r.data);

// --- Admin: artists ---
export const getAdminArtists = () => api.get("/api/admin/artists").then((r) => r.data);
export const deleteAdminArtist = (id: number) =>
  api.delete(`/api/admin/artists/${id}`).then((r) => r.data);

// --- Clipping: Promotion + Campaigns ---
export const startPromotion = (
  artistId: number,
  data: { view_target?: number; campaign_name?: string },
) => api.post(`/api/artists/${artistId}/promotion/start`, data).then((r) => r.data);
export const stopPromotion = (artistId: number) =>
  api.post(`/api/artists/${artistId}/promotion/stop`).then((r) => r.data);
export const togglePausePromotion = (artistId: number) =>
  api.post(`/api/artists/${artistId}/promotion/toggle-pause`).then((r) => r.data);
export const resetPromotion = (
  artistId: number,
  data: { view_target?: number; campaign_name?: string; delete_clips?: boolean },
) => api.post(`/api/artists/${artistId}/promotion/reset`, data).then((r) => r.data);
export const listCampaigns = (artistId: number) =>
  api.get(`/api/artists/${artistId}/campaigns`).then((r) => r.data);
export const downloadStatsCsv = async (
  artistId: number,
  opts: { slug: string; campaign_id?: number },
) => {
  const params = opts.campaign_id ? { campaign_id: opts.campaign_id } : {};
  const resp = await api.get(`/api/artists/${artistId}/stats.csv`, {
    params,
    responseType: "blob",
  });
  const blob = new Blob([resp.data], { type: "text/csv" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  const suffix = opts.campaign_id ? `-campaign${opts.campaign_id}` : "";
  link.download = `${opts.slug}-stats${suffix}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
};

// --- Admin: error logs ---
export const getAdminErrorLogs = (params?: { limit?: number; source?: string }) =>
  api.get("/api/admin/error-logs", { params }).then((r) => r.data);
export const clearAdminErrorLogs = () =>
  api.delete("/api/admin/error-logs").then((r) => r.data);

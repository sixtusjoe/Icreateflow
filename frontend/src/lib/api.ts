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
export const getSiteConfig = () => api.get("/api/admin/site-config").then((r) => r.data);
export const updateSiteConfig = (key: string, value: string) =>
  api.put("/api/admin/site-config", { key, value }).then((r) => r.data);
export const getAdminStats = () => api.get("/api/admin/stats").then((r) => r.data);

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
  api.put(`/api/variations/${id}`, { action }).then((r) => r.data);

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

// --- Music ---
export const getMusicTracks = () => api.get("/api/music").then((r) => r.data);
export const uploadMusicTrack = (name: string, genre: string, file: File) => {
  const form = new FormData();
  form.append("name", name);
  form.append("genre", genre);
  form.append("file", file);
  return api.post("/api/music", form).then((r) => r.data);
};
export const deleteMusicTrack = (id: number) =>
  api.delete(`/api/music/${id}`).then((r) => r.data);

// --- Downloads ---
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
export const fileUrl = (path: string) =>
  `${api.defaults.baseURL}/api/files/${encodeURIComponent(path)}`;

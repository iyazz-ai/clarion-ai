import { request } from "./client";

export const getFeed = (params, signal) =>
  request("/api/feed/", params, signal);

export const getStories = (params, signal) =>
  request("/api/stories/", params, signal);

export const getStory = (id, signal) =>
  request(`/api/stories/${id}/`, {}, signal);

export const getTrending = (params, signal) =>
  request("/api/trending/", params, signal);
// Local development keeps working with no setup (http://127.0.0.1:8000).
// A PRODUCTION build must be told where the API lives, otherwise visitors'
// browsers would try to reach THEIR OWN localhost. Set VITE_API_URL when you
// build (see frontend/.env.example).
const API_URL =
  import.meta.env.VITE_API_URL ||
  (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");

if (!API_URL) {
  throw new Error(
    "VITE_API_URL is not set. Set it to your backend URL before building " +
      "for production (e.g. VITE_API_URL=https://api.example.com)."
  );
}

const BASE_URL = API_URL.replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function request(path, params = {}, signal) {
  const url = new URL(`${BASE_URL}${path}`);

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });

  let response;
  try {
    response = await fetch(url, {
      signal,
      headers: { Accept: "application/json" },
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(
      "Can't reach the Clarion API. Check that the backend is running."
    );
  }

  if (!response.ok) {
    throw new ApiError(
      response.status === 404
        ? "We couldn't find that."
        : `The Clarion API returned an error (${response.status}).`,
      response.status
    );
  }

  return response.json();
}
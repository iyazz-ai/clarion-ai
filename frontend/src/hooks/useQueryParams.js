import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Keeps filters + page in the URL so views are shareable
 * and survive refresh. Changing a filter resets to page 1.
 */
export function useQueryParams() {
  const [params, setParams] = useSearchParams();

  const get = (key, fallback = "") => params.get(key) ?? fallback;

  const set = useCallback(
    (patch, { keepPage = false } = {}) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (!keepPage) next.delete("page");

          Object.entries(patch).forEach(([key, value]) => {
            const isEmpty =
              value === "" ||
              value === null ||
              value === undefined ||
              (key === "page" && Number(value) === 1);

            if (isEmpty) next.delete(key);
            else next.set(key, String(value));
          });

          return next;
        },
        { replace: true }
      );
    },
    [setParams]
  );

  return { get, set, params };
}
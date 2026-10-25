import { useEffect, useState } from "react";
import { getStories } from "../api/clarion";
import { useApi } from "../hooks/useApi";
import { useQueryParams } from "../hooks/useQueryParams";
import { CATEGORIES } from "../components/CategoryTabs";
import StoryList from "../components/StoryList";
import Pagination from "../components/Pagination";
import { EmptyState, ErrorState, LoadingList } from "../components/States";

const IMPORTANCE = [
  { value: "", label: "Any importance" },
  { value: "50", label: "50+" },
  { value: "70", label: "70+" },
  { value: "85", label: "85+" },
];

export default function SearchPage() {
  const { get, set } = useQueryParams();

  const query = get("search");
  const category = get("category");
  const source = get("source");
  const minImportance = get("min_importance");
  const from = get("from");
  const to = get("to");
  const page = Number(get("page", 1)) || 1;

  // Typing is local + debounced so we don't hit the API on every keystroke.
  const [input, setInput] = useState(query);
  const [knownSources, setKnownSources] = useState([]);

  // Keep the box in sync when the URL changes without typing (browser
  // back/forward, a link, clearing filters). The trim() check avoids eating a
  // trailing space while the user is still typing.
  useEffect(() => {
    setInput((current) => (current.trim() === query ? current : query));
  }, [query]);

  useEffect(() => {
    if (input === query) return;
    const timer = setTimeout(() => set({ search: input.trim() }), 350);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input]);

  const { data, loading, error, retry } = useApi(
    (signal) =>
      getStories(
        {
          search: query,
          category,
          source,
          min_importance: minImportance,
          from,
          to,
          page,
        },
        signal
      ),
    [query, category, source, minImportance, from, to, page]
  );

  // Collect source names we've seen to suggest while typing.
  useEffect(() => {
    if (!data?.results) return;
    setKnownSources((prev) => {
      const next = new Set(prev);
      data.results.forEach((s) => s.sources?.forEach((name) => next.add(name)));
      return [...next].sort();
    });
  }, [data]);

  const hasFilters = query || category || source || minImportance || from || to;

  const reset = () => {
    setInput("");
    set({
      search: "",
      category: "",
      source: "",
      min_importance: "",
      from: "",
      to: "",
    });
  };

  const changePage = (next) => {
    set({ page: next }, { keepPage: true });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <>
      <section className="intro">
        <p className="eyebrow">Search</p>
        <h1>Find a story</h1>
      </section>

      <div className="searchbar">
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.7" />
          <path d="M16 16L21 21" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
        </svg>
        <input
          type="search"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Search AI stories…"
          autoFocus
          aria-label="Search stories"
        />
      </div>

      <div className="filters">
        <label>
          <span>Category</span>
          <select value={category} onChange={(e) => set({ category: e.target.value })}>
            <option value="">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </label>

        <label>
          <span>Source</span>
          <input
            list="known-sources"
            value={source}
            onChange={(e) => set({ source: e.target.value })}
            placeholder="e.g. OpenAI"
          />
          <datalist id="known-sources">
            {knownSources.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </label>

        <label>
          <span>Importance</span>
          <select value={minImportance} onChange={(e) => set({ min_importance: e.target.value })}>
            {IMPORTANCE.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

        <label>
          <span>From</span>
          <input type="date" value={from} max={to || undefined} onChange={(e) => set({ from: e.target.value })} />
        </label>

        <label>
          <span>To</span>
          <input type="date" value={to} min={from || undefined} onChange={(e) => set({ to: e.target.value })} />
        </label>

        {hasFilters && (
          <button className="btn-link" onClick={reset}>Clear all</button>
        )}
      </div>

      {data && !loading && !error && (
        <p className="result-count">
          {data.count} {data.count === 1 ? "story" : "stories"}
        </p>
      )}

      {loading && <LoadingList rows={3} />}
      {error && <ErrorState error={error} onRetry={retry} />}

      {!loading && !error && data && (
        <>
          {data.results.length === 0 ? (
            <EmptyState
              title="No matching stories"
              text="Try different keywords or loosen a filter."
              actionLabel="Clear filters"
              onAction={reset}
            />
          ) : (
            <StoryList stories={data.results} />
          )}

          <Pagination
            page={data.page}
            totalPages={data.total_pages}
            onChange={changePage}
          />
        </>
      )}
    </>
  );
}
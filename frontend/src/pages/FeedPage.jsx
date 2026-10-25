import { getFeed } from "../api/clarion";
import { useApi } from "../hooks/useApi";
import { useQueryParams } from "../hooks/useQueryParams";
import CategoryTabs from "../components/CategoryTabs";
import StoryList from "../components/StoryList";
import Pagination from "../components/Pagination";
import { EmptyState, ErrorState, LoadingList } from "../components/States";

// "top" = Clarion's ranking (importance + freshness + corroboration).
const SORTS = [
  { value: "top", label: "Top stories" },
  { value: "latest", label: "Latest" },
  { value: "important", label: "Most important" },
];

export default function FeedPage() {
  const { get, set } = useQueryParams();
  const page = Number(get("page", 1)) || 1;
  const sort = get("sort", "top");
  const category = get("category");

  const { data, loading, error, retry } = useApi(
    (signal) =>
      getFeed({ page, sort, category }, signal),
    [page, sort, category]
  );

  const changePage = (next) => {
    set({ page: next }, { keepPage: true });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <>
      <section className="intro">
        <p className="eyebrow">Today in AI</p>
        <h1>Stay ahead in the rapidly changing world of AI.</h1>
        <p className="intro-text">
  Clarion doesn't give you more AI news. It gives you less noise.
</p>
    </section>

      <div className="toolbar">
        <CategoryTabs value={category} onChange={(c) => set({ category: c })} />

        <div className="segmented" role="group" aria-label="Sort">
          {SORTS.map((option) => (
            <button
              key={option.value}
              className={sort === option.value ? "active" : ""}
              onClick={() => set({ sort: option.value })}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {loading && <LoadingList />}
      {error && <ErrorState error={error} onRetry={retry} />}

      {!loading && !error && data && (
        <>
          {data.results.length === 0 ? (
            <EmptyState
              title="No stories here yet"
              text="Try another category or sort order."
              actionLabel="Show all stories"
              onAction={() => set({ category: "", sort: "" })}
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
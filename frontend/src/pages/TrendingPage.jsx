import { getTrending } from "../api/clarion";
import { useApi } from "../hooks/useApi";
import { useQueryParams } from "../hooks/useQueryParams";
import StoryList from "../components/StoryList";
import Pagination from "../components/Pagination";
import { EmptyState, ErrorState, LoadingList } from "../components/States";

export default function TrendingPage() {
  const { get, set } = useQueryParams();
  const page = Number(get("page", 1)) || 1;

  const { data, loading, error, retry } = useApi(
    (signal) => getTrending({ page }, signal),
    [page]
  );

  const changePage = (next) => {
    set({ page: next }, { keepPage: true });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <>
      <section className="intro">
        <p className="eyebrow">Trending</p>
        <h1>Gaining attention</h1>
        <p className="intro-text">
          Stories rising in Clarion's internal ranking right now.
        </p>
      </section>

      {loading && <LoadingList />}
      {error && <ErrorState error={error} onRetry={retry} />}

      {!loading && !error && data && (
        <>
          {data.results.length === 0 ? (
            <EmptyState
              title="Nothing is trending right now"
              text="Check back soon — rankings update as new stories arrive."
            />
          ) : (
            <StoryList
              stories={data.results}
              startRank={(data.page - 1) * data.page_size + 1}
            />
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
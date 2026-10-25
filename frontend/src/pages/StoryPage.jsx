import { useLocation, useNavigate, useParams } from "react-router-dom";
import { getStory } from "../api/clarion";
import { useApi } from "../hooks/useApi";
import ImportanceMeter from "../components/ImportanceMeter";
import { ErrorState } from "../components/States";
import { formatDate } from "../utils/format";

export default function StoryPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  const { data: story, loading, error, retry } = useApi(
    (signal) => getStory(id, signal),
    [id]
  );

  // "default" means this is the first page in the session (e.g. a shared link).
  const goBack = () => {
    if (location.key !== "default") navigate(-1);
    else navigate("/");
  };

  return (
    <>
      <button className="back" onClick={goBack}>
        ← Back
      </button>

      {loading && (
        <div className="detail" aria-busy="true">
          <div className="sk sk-line sk-short" />
          <div className="sk sk-title" />
          <div className="sk sk-title sk-medium" />
          <div className="sk sk-line" />
          <div className="sk sk-line sk-medium" />
        </div>
      )}

      {error && <ErrorState error={error} onRetry={error.status === 404 ? undefined : retry} />}

      {story && (
        <article className="detail">
          <div className="story-meta">
            <span className="category">{story.category || "Other"}</span>
            <span className="dot" />
            <time dateTime={story.first_published_at}>
              {formatDate(story.first_published_at)}
            </time>
          </div>

          <h1 className="detail-title">{story.title}</h1>

          <div className="detail-stats">
            <div>
              <span className="label">Importance</span>
              <ImportanceMeter score={story.importance_score} />
            </div>
            <div>
              <span className="label">Coverage</span>
              <strong>
                {story.article_count} {story.article_count === 1 ? "article" : "articles"}
              </strong>
            </div>
          </div>

          {story.summary && (
            <section className="detail-section">
              <span className="label">What happened</span>
              <p className="detail-summary">{story.summary}</p>
            </section>
          )}

          {story.why_it_matters && (
            <section className="detail-section why-block">
              <span className="label">Why it matters</span>
              <p>{story.why_it_matters}</p>
            </section>
          )}

          {story.sources?.length > 0 && (
            <section className="detail-section">
              <span className="label">Sources</span>
              <div className="chips static">
                {story.sources.map((name) => (
                  <span className="chip" key={name}>{name}</span>
                ))}
              </div>
            </section>
          )}

          {story.articles?.length > 0 && (
            <section className="detail-section">
              <span className="label">Related articles</span>
              <ul className="articles">
                {story.articles.map((article) => (
                  <li key={article.id}>
                    <a
                      href={article.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="article"
                    >
                      <div className="article-text">
                        <span className="article-source">
                          {article.source}
                          {article.author && <> · {article.author}</>}
                          {article.published_at && <> · {formatDate(article.published_at)}</>}
                        </span>
                        <span className="article-title">{article.title}</span>
                        <span className="article-cta">Read original ↗</span>
                      </div>

                      {article.image_url && (
                        <img
                          src={article.image_url}
                          alt=""
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          onError={(e) => (e.currentTarget.style.display = "none")}
                        />
                      )}
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </article>
      )}
    </>
  );
}
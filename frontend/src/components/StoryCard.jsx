import { Link } from "react-router-dom";
import ImportanceMeter from "./ImportanceMeter";
import { formatRelative, formatSources } from "../utils/format";

export default function StoryCard({ story, rank }) {
  const count = story.article_count ?? 0;

  return (
    <Link to={`/stories/${story.id}`} className="story">
      <div className="story-meta">
        {rank && (
          <span className="story-rank">{String(rank).padStart(2, "0")}</span>
        )}
        <span className="category">{story.category || "Other"}</span>
        <span className="dot" />
        <time dateTime={story.latest_article_at || story.first_published_at}>
          {formatRelative(story.latest_article_at || story.first_published_at)}
        </time>
        <span className="story-arrow" aria-hidden="true">→</span>
      </div>

      <h3 className="story-title">{story.title}</h3>

      {story.summary && <p className="story-summary">{story.summary}</p>}

      {story.why_it_matters && (
        <div className="why">
          <span className="label">Why it matters</span>
          <p>{story.why_it_matters}</p>
        </div>
      )}

      <div className="story-footer">
        <span className="story-source">
          {formatSources(story.sources)}
          <span className="dot" />
          {count} {count === 1 ? "article" : "articles"}
        </span>
        <ImportanceMeter score={story.importance_score} showLabel={false} />
      </div>
    </Link>
  );
}
import StoryCard from "./StoryCard";

export default function StoryList({ stories, startRank }) {
  return (
    <div className="story-list">
      {stories.map((story, index) => (
        <StoryCard
          key={story.id}
          story={story}
          rank={startRank ? startRank + index : undefined}
        />
      ))}
    </div>
  );
}
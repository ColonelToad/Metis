"""
Reddit sentiment tracker for energy market signals.

Monitors r/energy subreddit for discussions about:
- Natural gas prices/supply
- LNG exports/imports
- Oil market dynamics
- Energy policy changes
- Renewable energy developments

Tracks sentiment trends to identify:
- Supply/demand shocks
- Policy impacts
- Market sentiment shifts
"""

import feedparser
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
import hashlib
import json

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"

# Reddit feed URLs for energy subreddit
REDDIT_FEEDS = {
    "new": "https://www.reddit.com/r/energy/new/.rss",
    "hot": "https://www.reddit.com/r/energy/hot/.rss",
    "top": "https://www.reddit.com/r/energy/top/.rss",
    "natural_gas": "https://www.reddit.com/r/energy/search.rss?q=natural+gas",
}

# Keywords for signal detection
ENERGY_KEYWORDS = {
    "natural_gas": ["natural gas", "lng", "ngc", "natural gas carrier", "export", "import"],
    "crude_oil": ["crude", "wti", "brent", "oil price", "petroleum"],
    "refining": ["refining", "refinery", "margins", "crack spread"],
    "shipping": ["shipping", "rates", "freight", "vessel", "port"],
    "supply_shock": ["shortage", "outage", "emergency", "disruption", "force majeure"],
    "policy": ["legislation", "policy", "regulation", "tariff", "sanctions"],
}


@dataclass
class RedditPost:
    """Reddit post data model."""
    title: str
    url: str
    published: datetime
    author: str
    subreddit: str
    post_id: str  # Hash of URL for deduplication
    score: Optional[int] = None
    num_comments: Optional[int] = None
    content: str = ""


class RedditSentimentTracker:
    """Track sentiment and signals from r/energy subreddit."""
    
    def __init__(self):
        self.posts: List[RedditPost] = []
        self.seen_posts: set = set()
    
    def fetch_feed(self, feed_url: str, feed_name: str = "feed") -> List[RedditPost]:
        """Fetch and parse a single Reddit RSS feed."""
        try:
            feed = feedparser.parse(feed_url)
            posts = []
            
            if feed.status == 200 and feed.entries:
                for entry in feed.entries:
                    # Create unique post ID
                    post_id = hashlib.md5(entry.link.encode()).hexdigest()
                    
                    # Skip duplicates
                    if post_id in self.seen_posts:
                        continue
                    
                    self.seen_posts.add(post_id)
                    
                    # Parse date
                    try:
                        published = datetime(*entry.published_parsed[:6])
                    except (AttributeError, TypeError):
                        published = datetime.now()
                    
                    # Extract author from link (Reddit format)
                    author = "unknown"
                    if "author=" in entry.link:
                        author = entry.link.split("author=")[1].split("&")[0]
                    
                    post = RedditPost(
                        title=entry.get("title", ""),
                        url=entry.get("link", ""),
                        published=published,
                        author=author,
                        subreddit="energy",
                        post_id=post_id,
                        content=entry.get("summary", ""),
                    )
                    
                    posts.append(post)
                    logger.debug(f"Fetched post from {feed_name}: {post.title[:60]}...")
                
                logger.info(f"Successfully fetched {len(posts)} new posts from {feed_name}")
            else:
                logger.warning(f"Feed fetch failed for {feed_name}: status={feed.status}")
            
            return posts
            
        except Exception as e:
            logger.error(f"Error fetching {feed_name}: {e}")
            return []
    
    def fetch_all_feeds(self) -> List[RedditPost]:
        """Fetch posts from all configured Reddit feeds."""
        all_posts = []
        
        for feed_name, feed_url in REDDIT_FEEDS.items():
            logger.info(f"Fetching {feed_name} feed...")
            posts = self.fetch_feed(feed_url, feed_name)
            all_posts.extend(posts)
        
        self.posts.extend(all_posts)
        logger.info(f"Total unique posts fetched: {len(all_posts)}")
        
        return all_posts
    
    def detect_signal_keywords(self, text: str) -> Dict[str, bool]:
        """Detect energy-related keywords in post text."""
        text_lower = text.lower()
        detected = {}
        
        for signal_type, keywords in ENERGY_KEYWORDS.items():
            detected[signal_type] = any(
                keyword in text_lower for keyword in keywords
            )
        
        return detected
    
    def analyze_posts(self, posts: List[RedditPost]) -> pd.DataFrame:
        """Analyze posts and extract signals."""
        results = []
        
        for post in posts:
            combined_text = f"{post.title} {post.content}"
            signals = self.detect_signal_keywords(combined_text)
            
            result = {
                "date": post.published,
                "title": post.title,
                "url": post.url,
                "author": post.author,
                "content_length": len(post.content),
            }
            
            # Add signal detection
            result.update({f"signal_{k}": v for k, v in signals.items()})
            
            results.append(result)
        
        return pd.DataFrame(results)
    
    def save_posts(self, posts: List[RedditPost], output_path: Optional[Path] = None) -> Path:
        """Save posts to CSV and JSON."""
        if output_path is None:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            output_path = OUTPUT_DIR / f"reddit_energy_posts.csv"
        
        # Convert to DataFrame
        df = pd.DataFrame([
            {
                "date": post.published,
                "title": post.title,
                "url": post.url,
                "author": post.author,
                "post_id": post.post_id,
                "content": post.content[:500],  # Truncate for CSV
            }
            for post in posts
        ])
        
        # Analyze for signals
        analysis_df = self.analyze_posts(posts)
        
        # Merge
        if len(df) > 0:
            df = df.merge(analysis_df[["date", "title", "signal_natural_gas", 
                                        "signal_crude_oil", "signal_shipping", 
                                        "signal_supply_shock"]], 
                          on=["date", "title"], 
                          how="left")
        
        # Save CSV
        df.to_csv(output_path, index=False)
        logger.info(f"Saved {len(df)} posts to {output_path}")
        
        # Save metadata
        metadata = {
            "fetched_at": datetime.now().isoformat(),
            "total_posts": len(df),
            "date_range": f"{df['date'].min()} to {df['date'].max()}" if len(df) > 0 else "N/A",
            "feeds": list(REDDIT_FEEDS.keys()),
            "signals_tracked": list(ENERGY_KEYWORDS.keys()),
        }
        
        metadata_path = output_path.with_suffix(".json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
        
        logger.info(f"Saved metadata to {metadata_path}")
        
        return output_path
    
    def get_signal_summary(self, analysis_df: pd.DataFrame) -> Dict[str, int]:
        """Get summary of detected signals."""
        signal_cols = [c for c in analysis_df.columns if c.startswith("signal_")]
        
        summary = {}
        for col in signal_cols:
            signal_name = col.replace("signal_", "")
            summary[signal_name] = int(analysis_df[col].sum())
        
        return summary


def ingest_reddit_sentiment():
    """Main ingestion function for Reddit sentiment."""
    logger.info("Starting Reddit sentiment ingestion...")
    
    tracker = RedditSentimentTracker()
    
    # Fetch all feeds
    posts = tracker.fetch_all_feeds()
    
    if posts:
        # Save to disk
        output_path = tracker.save_posts(posts)
        
        # Analyze and print summary
        analysis_df = tracker.analyze_posts(posts)
        signal_summary = tracker.get_signal_summary(analysis_df)
        
        logger.info("Signal Detection Summary:")
        for signal, count in signal_summary.items():
            logger.info(f"  {signal}: {count} posts")
        
        return posts, analysis_df
    else:
        logger.warning("No posts fetched")
        return [], pd.DataFrame()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    posts, analysis = ingest_reddit_sentiment()
    if len(analysis) > 0:
        print("\nRecent posts with signals:")
        signal_cols = [c for c in analysis.columns if c.startswith("signal_")]
        print(analysis[["date", "title"] + signal_cols].head(10))

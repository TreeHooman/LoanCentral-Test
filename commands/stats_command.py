import re
import logging
from datetime import UTC, datetime, timedelta
import traceback

logger = logging.getLogger("LoanCentral")

# Command trigger - this will be used by the CommandManager
COMMAND_TRIGGER = "$stats"

def process_stats_command(comment):
    """Process $stats command"""
    # Import here to avoid circular imports
    from utils import get_db_connection, reddit
    
    # Updated regex to make /u/ optional by using (?:/u/|u/) pattern
    m = re.search(r"\$stats\s+(?:/u/|u/)([^\s]+)", comment.body, re.IGNORECASE)
    if not m:
        return
    
    user = m.group(1).lower()
    
    try:
        redditor = reddit.redditor(user)
        # Fetch comments (up to PRAW limit to avoid rate limits)
        comments = list(redditor.comments.new(limit=100))
        
        now = datetime.now(UTC)
        # Total and recent comments
        total_comments = len(comments)
        cutoff = now - timedelta(days=180)
        recent_comments = [c for c in comments if datetime.fromtimestamp(c.created_utc, UTC) >= cutoff]
        
        if not comments:
            comment.reply(f"No comments found for u/{user}.")
            return
            
        # Oldest & newest
        dates = [datetime.fromtimestamp(c.created_utc, UTC) for c in comments]
        newest = max(dates).date()
        eldest = min(dates).date()
        
        # Unique comment gaps
        sorted_dates = sorted(dates)
        gaps = [(t2 - t1).total_seconds() for t1, t2 in zip(sorted_dates, sorted_dates[1:])]
        avg_gap = sum(gaps) / len(gaps) / 86400 if gaps else 0
        max_gap = max(gaps) / 86400 if gaps else 0
        
        # Daily activity
        days = sorted(list({dt.date() for dt in dates}))
        day_gaps = [(t2 - t1).days for t1, t2 in zip(days, days[1:])]
        avg_day_gap = sum(day_gaps) / len(day_gaps) if day_gaps else 0
        max_day_gap = max(day_gaps) if day_gaps else 0
        
        # Karma by subreddit
        karma_map = {}
        for c in comments:
            sr = c.subreddit.display_name
            karma_map[sr] = karma_map.get(sr, 0) + c.score
        top_3 = sorted(karma_map.items(), key=lambda x: x[1], reverse=True)[:3]
        
        # Account info
        post_karma = redditor.link_karma
        comment_karma = redditor.comment_karma
        combined = post_karma + comment_karma
        created = datetime.fromtimestamp(redditor.created_utc, UTC)
        age_days = (now - created).days
        age_years = age_days / 365
        verified = getattr(redditor, 'has_verified_email', False)
        
        # Build reply - improved formatting with proper spacing and readability
        reply = [f"# Account Statistics for u/{user}"]
        reply.append("")  # blank line
        reply.append(f"**Comments Scanned:** {total_comments} (Last 180 days: {len(recent_comments)})")
        reply.append(f"**Newest Comment:** {newest}")
        reply.append(f"**Oldest Comment:** {eldest}")
        reply.append("")  # blank line
        reply.append("## Comment Activity")
        reply.append("")  # blank line
        reply.append("**Average Time Between Comments:**")
        reply.append(f"* All scanned: {avg_gap:.2f} day(s)")
        reply.append(f"* Last 180 days: {avg_gap:.2f} day(s)")
        reply.append("")  # blank line
        reply.append("**Maximum Time Between Comments:**")
        reply.append(f"* All scanned: {max_gap:.0f} day(s)")
        reply.append(f"* Last 180 days: {max_gap:.0f} day(s)")
        reply.append("")  # blank line
        reply.append("**Average Time Between Active Days:**")
        reply.append(f"* All scanned: {avg_day_gap:.2f} day(s)")
        reply.append(f"* Last 180 days: {avg_day_gap:.2f} day(s)")
        reply.append("")  # blank line
        reply.append("**Maximum Time Between Active Days:**")
        reply.append(f"* All scanned: {max_day_gap} day(s)")
        reply.append(f"* Last 180 days: {max_day_gap} day(s)")
        reply.append("")  # blank line
        reply.append("## Top 3 Subreddits by Comment Karma")
        reply.append("")  # blank line
        for i, (sr, k) in enumerate(top_3, 1):
            reply.append(f"{i}. r/{sr}: {k} karma")
        reply.append("")  # blank line
        reply.append("## Account Information")
        reply.append("")  # blank line
        reply.append(f"**Post Karma:** {post_karma}")
        reply.append(f"**Comment Karma:** {comment_karma}")
        reply.append(f"**Combined Karma:** {combined}")
        reply.append(f"**Account Age:** {age_days} days ({age_years:.2f} years)")
        reply.append(f"**Verified Email:** {'Yes' if verified else 'No'}")
        
        # Add USL link
        usl_url = f"https://www.universalscammerlist.com/?username={user}"
        reply.append(f"**USL Tags:** [Check here]({usl_url})")
        
        # Send reply
        comment.reply("\n".join(reply))
        logger.info(f"Stats sent for u/{user}")
    except Exception as e:
        logger.error(f"Error processing stats for u/{user}: {e}")
        logger.error(traceback.format_exc())
        try:
            comment.reply(f"Error fetching stats for u/{user}.")
        except:
            pass

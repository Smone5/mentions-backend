"""Node to rank threads by relevance."""

import logging
import random
from graph.state import GenerateState
from llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def rank_threads_node(state: GenerateState) -> GenerateState:
    """
    Rank threads by relevance to company goal and keyword.
    Selects the most promising thread for reply.
    Uses Pydantic structured outputs for reliable scoring.
    On retry, skips already-attempted threads and prefers more recent ones.
    """
    threads = state["threads_found"]
    attempted_thread_ids = state.get("attempted_thread_ids", [])
    thread_attempt = state.get("thread_attempt_count", 0)
    
    # Filter out already-attempted threads on retry
    if attempted_thread_ids:
        original_count = len(threads)
        threads = [t for t in threads if t["id"] not in attempted_thread_ids]
        logger.info(f"Filtered out {original_count - len(threads)} already-attempted threads. {len(threads)} remaining.")
    
    if not threads:
        logger.error("No more threads available to try")
        state["error"] = "No more threads available after filtering already-attempted threads"
        state["error_node"] = "rank_threads"
        return state
    
    logger.info(f"Ranking {len(threads)} threads (thread attempt {thread_attempt + 1})")
    
    try:
        llm_client = get_llm_client()
        
        scored_threads = []
        
        for thread in threads[:10]:  # Rank top 10 to save API calls
            try:
                # Use structured output for reliable scoring
                ranking = await llm_client.rank_thread(
                    thread_title=thread['title'],
                    thread_body=thread['body'],
                    keyword=state['keyword'],
                    company_goal=state['company_goal']
                )
                
                thread["relevance_score"] = ranking["score"]
                thread["ranking_reason"] = ranking["reason"]
                thread["is_question"] = ranking["is_question"]
                
                # Only include threads that are questions
                if ranking["is_question"]:
                    scored_threads.append(thread)
                else:
                    logger.info(
                        f"Skipping thread '{thread['title'][:50]}...' - not a question: {ranking['reason']}"
                    )
                
            except Exception as e:
                logger.warning(f"Failed to score thread {thread['id']}: {str(e)}")
                thread["relevance_score"] = 0
                thread["ranking_reason"] = f"Error: {str(e)}"
                thread["is_question"] = False
        
        # Check if we have any question threads
        if not scored_threads:
            logger.warning("No question threads found - all threads were statements")
            state["error"] = "No question threads found - only statements/announcements"
            state["error_node"] = "rank_threads"
            return state
        
        # Sort by score (primary) and recency (secondary, via created_utc timestamp descending)
        # More recent threads are preferred when scores are similar
        ranked = sorted(
            scored_threads,
            key=lambda t: (t["relevance_score"], t.get("created_utc", 0)),
            reverse=True
        )
        
        state["ranked_threads"] = ranked
        
        # On first attempt, select from top 3 randomly to diversify
        # On retry, prefer the top thread (most recent with good score)
        thread_attempt = state.get("thread_attempt_count", 0)
        if thread_attempt == 0:
            # First attempt - randomize from top 3 for diversity
            top_candidates = ranked[:min(3, len(ranked))]
            best_thread = random.choice(top_candidates)
            selection_method = f"randomly chosen from top {len(top_candidates)} questions"
            logger.info(f"First attempt: randomly chose from top {len(top_candidates)} threads")
        else:
            # Retry - pick the best (most recent high-scoring) thread
            best_thread = ranked[0]
            selection_method = f"best thread (most recent with highest score)"
            logger.info(f"Retry attempt: picking best thread (most recent with highest score)")
        
        state["current_thread"] = best_thread
        state["thread_id"] = best_thread["id"]
        state["thread_title"] = best_thread["title"]
        state["thread_body"] = best_thread["body"]
        
        # Check if thread has an image (external URL, not self post)
        if not best_thread.get("is_self", True) and best_thread.get("url"):
            url = best_thread["url"]
            # Check if URL points to an image (common image extensions)
            if any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']) or \
               any(domain in url.lower() for domain in ['i.redd.it', 'i.imgur.com', 'imgur.com/a/']):
                state["thread_image_url"] = url
                logger.info(f"Thread contains image: {url}")
            else:
                state["thread_image_url"] = None
        else:
            state["thread_image_url"] = None
        
        logger.info(
            f"Selected QUESTION thread: {best_thread['title']} "
            f"(score: {best_thread['relevance_score']}, {selection_method})"
        )
        
        # Fetch thread details including comments
        from reddit.client import get_reddit_client_for_account
        
        reddit_client = await get_reddit_client_for_account(
            company_id=state["company_id"],
            account_id=state["reddit_account_id"]
        )
        
        thread_details = await reddit_client.get_thread_details(best_thread["id"])
        
        await reddit_client.close()
        
        # Store full comment objects (not just bodies) to understand what's been said
        # This helps us avoid repeating existing advice
        state["top_comments"] = thread_details["top_comments"]
        
        logger.info(f"Fetched {len(thread_details['top_comments'])} comments for context")
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to rank threads: {str(e)}")
        state["error"] = f"Failed to rank threads: {str(e)}"
        state["error_node"] = "rank_threads"
        return state


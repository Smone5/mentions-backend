"""Node to rank threads by relevance."""

import logging
from graph.state import GenerateState
from llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def rank_threads_node(state: GenerateState) -> GenerateState:
    """
    Rank threads by relevance to company goal and keyword.
    Selects the most promising thread for reply.
    """
    threads = state["threads_found"]
    logger.info(f"Ranking {len(threads)} threads")
    
    try:
        llm_client = get_llm_client()
        
        # For simplicity, use LLM to score threads
        # In production, you might want more sophisticated ranking
        
        scored_threads = []
        
        for thread in threads[:10]:  # Rank top 10 to save API calls
            # Simple prompt to score relevance
            prompt = f"""Rate this Reddit thread's relevance to the company's goal (0-10):

Company Goal: {state['company_goal']}
Keyword: {state['keyword']}

Thread Title: {thread['title']}
Thread Body: {thread['body'][:500]}...

Respond with just a number 0-10:"""
            
            try:
                score_text = await llm_client.generate(
                    prompt=prompt,
                    temperature=0.2,
                    max_tokens=10
                )
                
                score = float(score_text.strip())
                
                thread["relevance_score"] = score
                scored_threads.append(thread)
                
            except Exception as e:
                logger.warning(f"Failed to score thread {thread['id']}: {str(e)}")
                thread["relevance_score"] = 0
                scored_threads.append(thread)
        
        # Sort by score
        ranked = sorted(scored_threads, key=lambda t: t["relevance_score"], reverse=True)
        
        state["ranked_threads"] = ranked
        
        # Select best thread
        best_thread = ranked[0]
        state["current_thread"] = best_thread
        state["thread_id"] = best_thread["id"]
        state["thread_title"] = best_thread["title"]
        state["thread_body"] = best_thread["body"]
        
        logger.info(
            f"Selected thread: {best_thread['title']} "
            f"(score: {best_thread['relevance_score']})"
        )
        
        # Fetch thread details including comments
        from reddit.client import get_reddit_client_for_account
        
        reddit_client = await get_reddit_client_for_account(
            company_id=state["company_id"],
            account_id=state["reddit_account_id"]
        )
        
        thread_details = await reddit_client.get_thread_details(best_thread["id"])
        
        await reddit_client.close()
        
        # Extract top comments
        state["top_comments"] = [
            comment["body"] for comment in thread_details["top_comments"][:5]
        ]
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to rank threads: {str(e)}")
        state["error"] = f"Failed to rank threads: {str(e)}"
        state["error_node"] = "rank_threads"
        return state


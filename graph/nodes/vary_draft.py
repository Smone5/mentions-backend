"""Node to create draft variations."""

import logging
from graph.state import GenerateState
from llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def vary_draft_node(state: GenerateState) -> GenerateState:
    """
    Create variations of the drafted reply.
    This gives users options to choose from.
    """
    logger.info(f"Creating variations of draft")
    
    try:
        llm_client = get_llm_client()
        
        # Create 2-3 variations
        variations = []
        
        for i, variation_type in enumerate(["tone", "length"], 1):
            try:
                variation = await llm_client.vary_draft(
                    original_draft=state["draft_body"],
                    variation_type=variation_type
                )
                variations.append(variation)
                logger.info(f"Created variation {i}: {variation_type}")
            except Exception as e:
                logger.warning(f"Failed to create variation {i}: {str(e)}")
        
        state["draft_variations"] = variations
        
        logger.info(f"Created {len(variations)} draft variations")
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to create variations: {str(e)}")
        # Don't fail the pipeline if variations fail
        state["draft_variations"] = []
        return state


"""OpenAI LLM client for text generation."""

import logging
from typing import Optional, List, Dict, Any
from openai import OpenAI, AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """
    OpenAI LLM client for text generation.
    
    Supports different temperature settings for different use cases:
    - Judges: Low temperature (0.2) for consistency
    - Drafts: Medium temperature (0.6) for quality
    - Variations: Higher temperature (0.7) for creativity
    """
    
    def __init__(self):
        """Initialize OpenAI client."""
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.sync_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.6,
        max_tokens: int = 500,
        model: str = "gpt-4",
        response_format: Optional[dict] = None,
    ) -> str:
        """
        Generate text using OpenAI's chat completion API.
        
        Args:
            prompt: The user prompt/question
            system_prompt: Optional system prompt to guide behavior
            temperature: Temperature for generation (0.0-2.0)
                - 0.2 for judges (consistent, deterministic)
                - 0.6 for drafts (balanced quality)
                - 0.7-0.9 for variations (creative)
            max_tokens: Maximum tokens to generate
            model: Model to use (gpt-4, gpt-4-turbo, gpt-3.5-turbo)
            response_format: Optional response format (e.g., {"type": "json_object"})
            
        Returns:
            Generated text response
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        try:
            logger.info(f"Generating with model={model}, temperature={temperature}, max_tokens={max_tokens}")
            
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
            
            generated_text = response.choices[0].message.content
            
            logger.info(
                f"Generated {len(generated_text)} chars, "
                f"used {response.usage.total_tokens} tokens"
            )
            
            return generated_text
            
        except Exception as e:
            logger.error(f"LLM generation failed: {str(e)}")
            raise
    
    async def judge_subreddit(
        self,
        subreddit: str,
        keyword: str,
        company_goal: str,
        subreddit_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Judge if a subreddit is appropriate for the company's goal.
        
        This is a HARD GATE (Hard Rule #3) - rejection stops the pipeline.
        
        Args:
            subreddit: Subreddit name
            keyword: Keyword being searched
            company_goal: Company's stated goal
            subreddit_description: Optional subreddit description
            
        Returns:
            Dictionary with verdict ("approve" or "reject"), reason, and confidence
        """
        system_prompt = """You are a subreddit relevance judge. Your job is to determine if a subreddit is appropriate for a company to participate in based on their goal.

CRITICAL: You must be conservative. When in doubt, REJECT.

Reject if:
- Subreddit is unrelated to the company's goal
- Subreddit is highly moderated and unlikely to allow promotional content
- Subreddit has strict rules against business participation
- Topic is controversial or high-risk
- Community is hostile to businesses

Approve if:
- Subreddit is clearly relevant to the company's goal
- Community seems open to helpful business participation
- Topic aligns well with the keyword and company goal

Respond ONLY in JSON format:
{
  "verdict": "approve" or "reject",
  "reason": "Brief explanation",
  "confidence": 0.0 to 1.0
}"""
        
        desc = f"\nSubreddit description: {subreddit_description}" if subreddit_description else ""
        
        prompt = f"""Evaluate this subreddit for participation:

Subreddit: r/{subreddit}
Keyword: {keyword}
Company Goal: {company_goal}{desc}

Should we participate in this subreddit?"""
        
        try:
            response = await self.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.2,  # Low temperature for consistency
                max_tokens=300,
                response_format={"type": "json_object"}
            )
            
            import json
            result = json.loads(response)
            
            logger.info(f"Subreddit judge r/{subreddit}: {result['verdict']} (confidence: {result['confidence']})")
            
            return result
            
        except Exception as e:
            logger.error(f"Subreddit judgment failed: {str(e)}")
            # On error, reject for safety
            return {
                "verdict": "reject",
                "reason": f"Judgment error: {str(e)}",
                "confidence": 0.0
            }
    
    async def judge_draft(
        self,
        draft_body: str,
        thread_title: str,
        thread_body: str,
        subreddit_rules: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Judge if a draft reply is high quality and safe to post.
        
        This is a HARD GATE (Hard Rule #3) - rejection stops the pipeline.
        Also enforces Hard Rule #2: No links in replies.
        
        Args:
            draft_body: The draft reply text
            thread_title: Reddit thread title
            thread_body: Reddit thread body
            subreddit_rules: Optional subreddit rules
            
        Returns:
            Dictionary with verdict, reason, confidence, and risk_level
        """
        system_prompt = """You are a draft quality judge. Your job is to determine if a Reddit reply is high quality, helpful, and safe to post.

CRITICAL RULES - MUST ENFORCE:
1. REJECT if draft contains ANY links, URLs, or domain references
   - http://, https://, www., .com, .net, etc.
   - "link in bio", "DM me", "check my profile", etc.
   - "example dot com" or obfuscated links
2. REJECT if draft is promotional, salesy, or spammy
3. REJECT if draft doesn't directly answer the question
4. REJECT if draft is low effort or generic
5. REJECT if draft violates subreddit rules (if provided)

APPROVE only if:
- Draft is genuinely helpful and specific
- Draft directly addresses the question/topic
- Draft sounds natural and conversational
- Draft has NO links or promotional content
- Draft follows all subreddit rules

Respond ONLY in JSON format:
{
  "verdict": "approve" or "reject",
  "reason": "Brief explanation",
  "confidence": 0.0 to 1.0,
  "risk_level": "low", "medium", or "high"
}"""
        
        rules_text = f"\nSubreddit Rules:\n{subreddit_rules}" if subreddit_rules else ""
        
        prompt = f"""Evaluate this draft reply:

Thread Title: {thread_title}
Thread Body: {thread_body[:500]}...{rules_text}

Draft Reply:
{draft_body}

Is this draft safe and high quality to post?"""
        
        try:
            response = await self.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.2,  # Low temperature for consistency
                max_tokens=400,
                response_format={"type": "json_object"}
            )
            
            import json
            result = json.loads(response)
            
            logger.info(
                f"Draft judge: {result['verdict']} "
                f"(confidence: {result['confidence']}, risk: {result['risk_level']})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Draft judgment failed: {str(e)}")
            # On error, reject for safety
            return {
                "verdict": "reject",
                "reason": f"Judgment error: {str(e)}",
                "confidence": 0.0,
                "risk_level": "high"
            }
    
    async def compose_draft(
        self,
        thread_title: str,
        thread_body: str,
        top_comments: List[str],
        subreddit_rules: str,
        company_context: str,
        rag_context: Optional[str] = None,
        keyword: str = "",
    ) -> str:
        """
        Compose a helpful Reddit reply draft.
        
        Enforces Hard Rule #2: No links in draft.
        
        Args:
            thread_title: Reddit thread title
            thread_body: Reddit thread body
            top_comments: List of top comments for context
            subreddit_rules: Subreddit rules
            company_context: Company goal and description
            rag_context: Optional relevant context from RAG
            keyword: Keyword that led to this thread
            
        Returns:
            Draft reply text
        """
        system_prompt = """You are a helpful Reddit community member. Your job is to write genuinely helpful, specific replies to questions.

CRITICAL RULES - MUST FOLLOW:
1. NEVER include links, URLs, or website references
2. NEVER be promotional or salesy
3. ALWAYS be specific and actionable
4. ALWAYS sound natural and conversational
5. NEVER mention being a bot or AI
6. Keep replies concise (2-4 paragraphs max)

Write as if you're a knowledgeable person who wants to help, not a business.
Use the provided context to give specific advice, but don't directly promote."""
        
        comments_text = "\n".join([f"- {c[:200]}..." for c in top_comments[:3]])
        rag_text = f"\n\nRelevant Context:\n{rag_context}" if rag_context else ""
        
        prompt = f"""Write a helpful reply to this Reddit thread:

Thread Title: {thread_title}
Thread Body: {thread_body}

Top Comments:
{comments_text}

Subreddit Rules: {subreddit_rules}

Company Context (use to inform your answer, but don't promote):
{company_context}{rag_text}

Write a helpful, specific reply (NO LINKS):"""
        
        try:
            draft = await self.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.6,  # Medium temperature for quality
                max_tokens=600,
            )
            
            logger.info(f"Draft composed: {len(draft)} characters")
            
            return draft.strip()
            
        except Exception as e:
            logger.error(f"Draft composition failed: {str(e)}")
            raise
    
    async def vary_draft(
        self,
        original_draft: str,
        variation_type: str = "tone"
    ) -> str:
        """
        Create a variation of an approved draft.
        
        Args:
            original_draft: The original draft text
            variation_type: Type of variation ("tone", "length", "style")
            
        Returns:
            Varied draft text
        """
        system_prompt = """You are a helpful editor. Create a variation of the provided text while maintaining its core message and helpfulness.

CRITICAL RULES - MUST FOLLOW:
1. NEVER add links, URLs, or website references
2. Keep the same core advice and helpfulness
3. Change wording, phrasing, and structure
4. Maintain the same level of specificity"""
        
        prompt = f"""Create a {variation_type} variation of this text:

Original:
{original_draft}

Write a variation (NO LINKS):"""
        
        try:
            variation = await self.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.7,  # Higher temperature for creativity
                max_tokens=600,
            )
            
            logger.info(f"Draft variation created: {len(variation)} characters")
            
            return variation.strip()
            
        except Exception as e:
            logger.error(f"Draft variation failed: {str(e)}")
            raise


# Global LLM client instance
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get or create global LLM client instance."""
    global _llm_client
    
    if _llm_client is None:
        _llm_client = LLMClient()
        logger.info("LLM client initialized")
    
    return _llm_client


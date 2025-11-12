"""OpenAI LLM client for text generation."""

import logging
from typing import Optional, List, Dict, Any, TypeVar, Type
from openai import OpenAI, AsyncOpenAI
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


# Pydantic models for structured outputs
class SubredditJudgment(BaseModel):
    """Pydantic model for subreddit judgment output."""
    verdict: str = Field(description="Either 'approve' or 'reject'")
    reason: str = Field(description="Brief explanation for the verdict")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")


class DraftJudgment(BaseModel):
    """Pydantic model for draft quality judgment output."""
    verdict: str = Field(description="Either 'approve' or 'reject'")
    reason: str = Field(description="Brief explanation for the verdict")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    risk_level: str = Field(description="Risk level: 'low', 'medium', or 'high'")


class ThreadRelevanceScore(BaseModel):
    """Pydantic model for thread relevance scoring."""
    score: float = Field(description="Relevance score from 0.0 to 10.0")
    reason: str = Field(description="Brief explanation for the score")
    is_question: bool = Field(description="Whether the thread is asking a question or seeking advice (not just a statement)")


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
        max_tokens: int = 1500,
        model: str = "gpt-5-mini-2025-08-07",
    ) -> str:
        """
        Generate text using OpenAI's chat completion API.
        
        GPT-5 Mini only supports default temperature (1.0) - no custom temperature values allowed.
        
        Args:
            prompt: The user prompt/question
            system_prompt: Optional system prompt to guide behavior
            max_tokens: Maximum tokens to generate (uses max_completion_tokens for GPT-5)
            model: Model to use (default: gpt-5-mini-2025-08-07)
            
        Returns:
            Generated text response
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        try:
            logger.info(f"Generating with model={model}, max_completion_tokens={max_tokens}")
            
            # GPT-5 Mini only supports default temperature (1.0), don't pass temperature parameter
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                max_completion_tokens=max_tokens,  # GPT-5 uses max_completion_tokens
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
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        max_tokens: int = 500,
        model: str = "gpt-5-mini-2025-08-07",
    ) -> T:
        """
        Generate structured output using OpenAI's Pydantic response parsing.
        
        This uses OpenAI's structured outputs feature for guaranteed schema compliance.
        Works with GPT-5 mini for superior instruction-following and structured outputs.
        
        Note: GPT-5 Mini uses default temperature (1.0) and doesn't support custom values.
        
        Args:
            prompt: The user prompt/question
            response_model: Pydantic model class for structured output
            system_prompt: Optional system prompt to guide behavior
            max_tokens: Maximum tokens to generate (uses max_completion_tokens for GPT-5)
            model: Model to use (default: gpt-5-mini-2025-08-07)
            
        Returns:
            Instance of response_model with parsed output
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        try:
            logger.info(f"Generating structured output with model={model}, max_completion_tokens={max_tokens}")
            
            # GPT-5 Mini only supports default temperature (1.0), don't pass temperature parameter
            # Use beta.chat.completions.parse for structured outputs
            completion = await self.client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                max_completion_tokens=max_tokens,  # GPT-5 uses max_completion_tokens
                response_format=response_model,
            )
            
            parsed_output = completion.choices[0].message.parsed
            
            logger.info(
                f"Generated structured output: {response_model.__name__}, "
                f"used {completion.usage.total_tokens} tokens"
            )
            
            return parsed_output
            
        except Exception as e:
            logger.error(f"Structured LLM generation failed: {str(e)}")
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
        Uses Pydantic structured outputs for guaranteed schema compliance.
        
        Args:
            subreddit: Subreddit name
            keyword: Keyword being searched
            company_goal: Company's stated goal
            subreddit_description: Optional subreddit description
            
        Returns:
            Dictionary with verdict ("approve" or "reject"), reason, and confidence
        """
        system_prompt = """You are a subreddit relevance judge. Your job is to determine if a subreddit is appropriate for participation based on the company's goal.

IMPORTANT CONTEXT: We participate as a real person who works at the company, sharing personal experience-based advice. We transparently mention our employer once but do NOT pitch services, include links, or act promotional. Our comments are purely helpful, value-first contributions that follow all subreddit rules.

DEFAULT STANCE: APPROVE relevant communities where we can provide helpful, non-promotional advice.

APPROVE when:
- The subreddit topic is relevant to the company's goal and keyword
- Providing personal, peer-style advice would be helpful to the community
- Rules do not explicitly ban professionals or outsiders from contributing helpful advice

REJECT only if:
- Subreddit is clearly unrelated to the keyword or company goal
- Rules explicitly forbid ANY business/professional participation, even non-promotional
- Topic is high-risk for brand safety (politics, harassment, illegal content, adult content, etc.)

For highly-moderated help/advice communities:
- APPROVE with a caution about following rules carefully
- These communities often value expertise when delivered non-promotionally
- Reject them ONLY if the rules explicitly ban professionals or require pre-approval we don't have

When in doubt and the subreddit is relevant: APPROVE with a note to follow rules carefully."""
        
        desc = f"\nSubreddit description: {subreddit_description}" if subreddit_description else ""
        
        prompt = f"""Evaluate this subreddit for participation:

Subreddit: r/{subreddit}
Keyword: {keyword}
Company Goal: {company_goal}{desc}

Should we participate in this subreddit?"""
        
        try:
            result = await self.generate_structured(
                prompt=prompt,
                response_model=SubredditJudgment,
                system_prompt=system_prompt,
                max_tokens=3000,  # GPT-5 Mini uses reasoning tokens, needs higher limit (3x safety margin)
            )
            
            logger.info(f"Subreddit judge r/{subreddit}: {result.verdict} (confidence: {result.confidence})")
            
            return {
                "verdict": result.verdict,
                "reason": result.reason,
                "confidence": result.confidence
            }
            
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
        top_comments: List[Dict[str, Any]],
        subreddit_rules: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Judge if a draft reply is high quality and safe to post.
        
        This is a HARD GATE (Hard Rule #3) - rejection stops the pipeline.
        Also enforces Hard Rule #2: No links in replies.
        Uses Pydantic structured outputs for guaranteed schema compliance.
        
        Args:
            draft_body: The draft reply text
            thread_title: Reddit thread title
            thread_body: Reddit thread body
            top_comments: List of existing comment objects to check for repetition
            subreddit_rules: Optional subreddit rules
            
        Returns:
            Dictionary with verdict, reason, confidence, and risk_level
        """
        system_prompt = """You are a draft quality judge. Your job is to determine if a Reddit reply is high quality, helpful, and safe to post.

CRITICAL RULES - MUST ENFORCE:
1. REJECT if the thread is NOT asking a question or seeking advice
   - We only respond to questions, not statements/announcements/rants
   - Thread must be seeking information or help
2. REJECT if draft contains ANY links, URLs, or domain references
   - http://, https://, www., .com, .net, etc.
   - "link in bio", "DM me", "check my profile", etc.
   - "example dot com" or obfuscated links
3. REJECT if draft is promotional, salesy, or spammy
   - A single transparency statement like "I work at [CompanyName]" is allowed and should NOT be considered promotional as long as nothing about the company's offerings is discussed
4. REJECT if draft doesn't directly answer the question asked
5. REJECT if draft is low effort or generic
6. REJECT if draft violates subreddit rules (if provided)
7. REJECT if draft repeats advice already given in existing comments
   - Draft MUST add new value, perspective, or insights
   - It's okay to build on existing advice, but must add something new
   - Simply rephrasing what others already said is NOT acceptable

APPROVE only if:
- Thread is asking a question or seeking advice (REQUIRED)
- Draft is genuinely helpful and specific
- Draft directly answers the question asked
- Draft sounds natural and conversational
- Draft has NO links or promotional content (except for the allowed transparency mention above)
- Draft follows all subreddit rules
- Draft adds NEW value not already covered by existing comments"""
        
        rules_text = f"\nSubreddit Rules:\n{subreddit_rules}" if subreddit_rules else ""
        
        # Format existing comments to check for repetition
        if top_comments:
            comments_text = "\n\n".join([
                f"Comment by u/{c['author']} (score: {c['score']}):\n{c['body'][:300]}{'...' if len(c['body']) > 300 else ''}"
                for c in top_comments[:10]
            ])
            comments_section = f"\n\nExisting Comments (check if draft repeats these):\n{comments_text}"
        else:
            comments_section = "\n\nNo existing comments yet."
        
        prompt = f"""Evaluate this draft reply:

Thread Title: {thread_title}
Thread Body: {thread_body[:500]}...{rules_text}{comments_section}

Draft Reply:
{draft_body}

Is this draft safe, high quality, AND adding new value (not repeating existing comments)?"""
        
        try:
            result = await self.generate_structured(
                prompt=prompt,
                response_model=DraftJudgment,
                system_prompt=system_prompt,
                max_tokens=3000,  # GPT-5 Mini uses reasoning tokens, needs higher limit (3x safety margin)
            )
            
            logger.info(
                f"Draft judge: {result.verdict} "
                f"(confidence: {result.confidence}, risk: {result.risk_level})"
            )
            
            return {
                "verdict": result.verdict,
                "reason": result.reason,
                "confidence": result.confidence,
                "risk_level": result.risk_level
            }
            
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
        top_comments: List[Dict[str, Any]],
        subreddit_rules: str,
        company_context: str,
        rag_context: Optional[str] = None,
        keyword: str = "",
        custom_prompt: Optional[str] = None,
        feedback_context: Optional[str] = None,
        image_analysis: Optional[str] = None,
    ) -> str:
        """
        Compose a helpful Reddit reply draft.
        
        Enforces Hard Rule #2: No links in draft.
        
        Args:
            thread_title: Reddit thread title
            thread_body: Reddit thread body
            top_comments: List of comment objects (with author, body, score) for context
            subreddit_rules: Subreddit rules
            company_context: Company goal and description
            rag_context: Optional relevant context from RAG
            keyword: Keyword that led to this thread
            feedback_context: Optional feedback from previous rejection (for retries)
            image_analysis: Optional AI analysis of an image in the post
            
        Returns:
            Draft reply text
        """
        # Use custom prompt if provided, otherwise use default
        if custom_prompt:
            system_prompt = f"""{custom_prompt}

CRITICAL RULES - MUST FOLLOW:
1. NEVER include links, URLs, or website references
2. NEVER be promotional or salesy
3. NEVER mention being a bot or AI
4. CRITICAL: READ ALL EXISTING COMMENTS CAREFULLY. Do NOT repeat advice already given by others. Add NEW value, perspective, or insights that haven't been mentioned yet.

NOTE: The company name is provided in the Company Context below. You can reference it naturally in your response (e.g., "I work at [CompanyName]").

Use the provided context to give specific advice, but don't directly promote."""
        else:
            system_prompt = """You are a helpful Reddit community member. Your job is to write genuinely helpful, specific replies to questions that read like a human comment in the thread.

CRITICAL RULES - MUST FOLLOW:
1. NEVER include links, URLs, or website references
2. NEVER be promotional or salesy
3. ALWAYS sound like a real person: warm, conversational, first-person voice
4. Keep it tight: one or two short paragraphs (max ~200 words)
5. NO bullet lists, numbered lists, or section headers
6. Avoid punctuation that feels formal (no semicolons, em dashes, double hyphens, or colon-led clauses). Rely on plain sentences with commas and periods
7. Ground the reply in lived experience. Use softeners like "I'd" or "I've seen" rather than frameworks or jargon. Share one or two clear actions inside the prose instead of separate lists
8. NEVER mention being a bot or AI
9. Do not ask for more information, invite follow-up replies, or suggest continuing the conversation elsewhere. Deliver a complete answer in this comment.
10. Always provide a substantive response: at least three sentences that answer the question directly and include one or two concrete, actionable tips drawn from your experience.
11. CRITICAL: READ ALL EXISTING COMMENTS CAREFULLY. Do NOT repeat advice already given by others. Add NEW value, perspective, or insights that haven't been mentioned yet. Build on or complement what others said, don't duplicate it.

Write as if you're a knowledgeable peer using the Reddit app on your phone. Start with a quick reaction that shows you understand their dilemma, then weave in practical advice they can act on without sounding like a pitch. Close with a concise takeaway or gentle encouragement—no invitations or questions back."""
        
        # Format comments with author and score to show what's already been said
        if top_comments:
            comments_text = "\n\n".join([
                f"Comment by u/{c['author']} (score: {c['score']}):\n{c['body'][:300]}{'...' if len(c['body']) > 300 else ''}"
                for c in top_comments[:10]  # Show top 10 to understand conversation
            ])
            comments_section = f"""
Existing Comments (READ CAREFULLY - do NOT repeat what's already been said):
{comments_text}

IMPORTANT: Your reply MUST add new value or perspective not already covered by these comments."""
        else:
            comments_section = "\nNo existing comments yet - you'll be first to reply!"
        
        rag_text = f"\n\nRelevant Context:\n{rag_context}" if rag_context else ""
        feedback_text = f"\n\n{feedback_context}" if feedback_context else ""
        image_text = f"\n\nImage in Post:\n{image_analysis}" if image_analysis else ""
        
        prompt = f"""Write a helpful reply to this Reddit thread:

Thread Title: {thread_title}
Thread Body: {thread_body}{image_text}
{comments_section}

Subreddit Rules: {subreddit_rules}

Company Context (use to inform your answer, but don't promote):
{company_context}{rag_text}{feedback_text}

Write a helpful, specific reply that adds NEW value (NO LINKS, NO REPETITION):"""
        
        try:
            draft = await self.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=1800,  # 3x safety margin
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
                max_tokens=1800,  # 3x safety margin
            )
            
            logger.info(f"Draft variation created: {len(variation)} characters")
            
            return variation.strip()
            
        except Exception as e:
            logger.error(f"Draft variation failed: {str(e)}")
            raise
    
    async def analyze_image(
        self,
        image_url: str,
        thread_title: str,
        thread_body: str,
    ) -> str:
        """
        Analyze an image from a Reddit post using vision capabilities.
        
        Args:
            image_url: URL of the image to analyze
            thread_title: Reddit thread title for context
            thread_body: Reddit thread body for context
            
        Returns:
            Analysis of the image content
        """
        system_prompt = """You are an image analyst. Your job is to analyze images from Reddit posts and provide a clear, concise description of what's in the image that would be useful for generating a helpful reply.

Focus on:
1. What the image shows (objects, text, diagrams, screenshots, etc.)
2. Any visible issues, problems, or questions the image illustrates
3. Technical details if relevant (error messages, code, configuration, etc.)
4. Context that would help someone provide better advice

Keep the analysis concise but informative (2-4 sentences)."""
        
        prompt = f"""Analyze this image from a Reddit post:

Thread Title: {thread_title}
Thread Body: {thread_body}

Describe what's in the image and what's relevant for providing helpful advice:"""
        
        try:
            logger.info(f"Analyzing image from URL: {image_url}")
            
            # Use vision model for image analysis
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url,
                                "detail": "high"  # High detail for better analysis
                            }
                        }
                    ]
                }
            ]
            
            response = await self.client.chat.completions.create(
                model="gpt-5-mini-2025-08-07",  # GPT-5 has vision capabilities
                messages=messages,
                max_completion_tokens=500,  # GPT-5 uses max_completion_tokens
            )
            
            analysis = response.choices[0].message.content
            
            logger.info(f"Image analysis completed: {len(analysis)} chars")
            
            return analysis
            
        except Exception as e:
            logger.error(f"Image analysis failed: {str(e)}")
            # Return a helpful error message instead of failing
            return f"[Image analysis unavailable: {str(e)}]"
    
    async def rank_thread(
        self,
        thread_title: str,
        thread_body: str,
        keyword: str,
        company_goal: str
    ) -> Dict[str, Any]:
        """
        Rank a Reddit thread's relevance to the company's goal and keyword.
        
        Uses Pydantic structured outputs for guaranteed schema compliance.
        
        Args:
            thread_title: Reddit thread title
            thread_body: Reddit thread body
            keyword: Keyword being searched
            company_goal: Company's stated goal
            
        Returns:
            Dictionary with score (0.0-10.0) and reason
        """
        system_prompt = """You are a thread relevance evaluator. Rate how relevant a Reddit thread is to a company's goal and keyword.

CRITICAL: We ONLY respond to threads that ask questions or seek advice. Statements, announcements, or rants are NOT appropriate for replies.

Consider (in order of importance):
1. Is the thread asking a question or seeking advice? (REQUIRED - if not, mark is_question=false and score 0-2)
2. Is the question relevant to the company's stated goal? (VERY IMPORTANT)
3. Does the thread topic align with the keyword?
4. Would our company's expertise help answer this question?
5. Is the thread active and likely to get engagement?

Rate from 0.0 to 10.0:
- 9-10: Perfect match - asking a relevant question that aligns with company goal
- 7-8: Very relevant question that our company can help with
- 5-6: Somewhat relevant question
- 3-4: Loosely related question
- 0-2: Not a question OR not relevant to company goal

IMPORTANT: 
- If the thread is a statement/announcement (not seeking advice), mark is_question=false and score LOW (0-2)
- If the question is not relevant to the company's goal, score LOW even if it mentions the keyword"""
        
        prompt = f"""Rate this Reddit thread's relevance:

Company Goal: {company_goal}
Keyword: {keyword}

Thread Title: {thread_title}
Thread Body: {thread_body[:500]}...

Is this thread asking a question or seeking advice? How relevant is it (0.0-10.0)?"""
        
        try:
            result = await self.generate_structured(
                prompt=prompt,
                response_model=ThreadRelevanceScore,
                system_prompt=system_prompt,
                max_tokens=2400,  # GPT-5 Mini uses reasoning tokens, needs higher limit (3x safety margin)
            )
            
            logger.info(f"Thread ranked: {result.score}/10.0 - {result.reason}")
            
            return {
                "score": result.score,
                "reason": result.reason,
                "is_question": result.is_question
            }
            
        except Exception as e:
            logger.error(f"Thread ranking failed: {str(e)}")
            # On error, return neutral score and mark as not a question (to skip it)
            return {
                "score": 5.0,
                "reason": f"Ranking error: {str(e)}",
                "is_question": False
            }


# Global LLM client instance
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get or create global LLM client instance."""
    global _llm_client
    
    if _llm_client is None:
        _llm_client = LLMClient()
        logger.info("LLM client initialized")
    
    return _llm_client


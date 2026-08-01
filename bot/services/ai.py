from __future__ import annotations

from typing import List, Optional

from loguru import logger
from openai import AsyncOpenAI

from bot.config.settings import settings


class AIService:
    def __init__(self) -> None:
        self.client: Optional[AsyncOpenAI] = None
        self._enabled = bool(settings.openai_api_key)
        self.available: bool = False

    async def initialize(self) -> None:
        if self._enabled:
            try:
                self.client = AsyncOpenAI(api_key=settings.openai_api_key)
                self.available = True
                logger.info("AI service initialized")
            except Exception as e:
                self.available = False
                logger.warning(f"AI service initialization failed: {e}")
        else:
            self.available = False
            logger.warning("AI service disabled - no OpenAI API key configured")

    async def _call_llm(self, prompt: str, system_prompt: str = "You are a helpful assistant.") -> str:
        if not self.available or not self.client:
            return "AI features are not available. Please configure an OpenAI API key."

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1000,
                temperature=0.7,
            )
            return response.choices[0].message.content or "No response generated."
        except Exception as e:
            logger.error(f"AI service error: {e}")
            return "Sorry, I couldn't process your request at this time."

    async def generate_summary(self, title: str, author: Optional[str], description: Optional[str]) -> str:
        prompt = (
            f"Book: '{title}' by {author or 'Unknown Author'}\n"
            f"Description: {description or 'No description available.'}\n\n"
            "Please provide a comprehensive summary of this book's content, including:\n"
            "1. Main themes and topics covered\n"
            "2. Key arguments or narrative structure\n"
            "3. Target audience\n"
            "4. Notable features\n\n"
            "Keep the summary between 200-300 words."
        )
        system = "You are a literary analyst. Provide clear, insightful book summaries."
        return await self._call_llm(prompt, system)

    async def answer_question(self, title: str, author: Optional[str], question: str) -> str:
        prompt = (
            f"Book: '{title}' by {author or 'Unknown Author'}\n"
            f"Question: {question}\n\n"
            "Please provide a detailed, accurate answer based on general knowledge of this book."
        )
        system = "You are a knowledgeable literature expert. Answer questions about books accurately and concisely."
        return await self._call_llm(prompt, system)

    async def extract_lessons(self, title: str, author: Optional[str], description: Optional[str]) -> str:
        prompt = (
            f"Book: '{title}' by {author or 'Unknown Author'}\n"
            f"Description: {description or 'No description available.'}\n\n"
            "Extract and explain the key lessons and takeaways from this book:\n"
            "1. Top 5-7 actionable lessons\n"
            "2. Practical applications\n"
            "3. Key quotes or principles\n"
            "Format with clear headings and bullet points."
        )
        system = "You are a learning and development expert. Extract practical, actionable lessons from books."
        return await self._call_llm(prompt, system)

    async def generate_study_notes(self, title: str, author: Optional[str], description: Optional[str]) -> str:
        prompt = (
            f"Book: '{title}' by {author or 'Unknown Author'}\n"
            f"Description: {description or 'No description available.'}\n\n"
            "Create comprehensive study notes for this book:\n"
            "1. Chapter-by-chapter breakdown (if applicable)\n"
            "2. Key concepts and definitions\n"
            "3. Important dates, people, or events\n"
            "4. Study questions (5-7 questions)\n"
            "5. Recommended further reading\n"
            "Format with clear sections for easy studying."
        )
        system = "You are an academic tutor. Create thorough, well-organized study notes."
        return await self._call_llm(prompt, system)

    async def suggest_similar_books(self, title: str, author: Optional[str], description: Optional[str]) -> str:
        prompt = (
            f"Book: '{title}' by {author or 'Unknown Author'}\n"
            f"Description: {description or 'No description available.'}\n\n"
            "Recommend 5-7 similar books that readers might enjoy, including:\n"
            "1. Book title and author for each recommendation\n"
            "2. Why it's similar\n"
            "3. What makes it unique\n"
            "Organize from most to least similar."
        )
        system = "You are a well-read librarian. Give thoughtful, personalized book recommendations."
        return await self._call_llm(prompt, system)


ai = AIService()

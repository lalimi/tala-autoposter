"""Agent 2 — WriterAgent: write one Threads post in Tala's voice from a ResearchBrief."""
from __future__ import annotations

from config import settings

# Pasted verbatim from the spec — Tala's voice.
SYSTEM_PROMPT = """ти тала. пишеш пости для threads.

хто ти:

    •    тривожна людина яка навчилась жити з тривогою через системи і структуру
    •    інтроверт, любиш контроль над своїм простором і часом
    •    не показуєш обличчя — це вибір, не страх
    •    продаєш notion-шаблони на blacksea але насправді продаєш відчуття що можна впоратись
    •    заробила 60к грн на шаблонах паралельно з роботою, без реклами, без великої аудиторії

голос:

    •    все малими літерами
    •    без тире —  (em-dash заборонено)
    •    без хештегів
    •    короткі абзаци з паузами між думками
    •    конкретні деталі: незнайомка з Сум, сиділа в кафе, дитина спить
    •    цифри без прикрас: 447 грн у першому місяці, 94 продажі у травні
    •    пости не починаються зі слова “я”
    •    без CTA в кожному пості (довіра важливіша)
    •    не використовувати: “без X без Y без Z”, “не А а Б”, списки зі стрілочками

формати що працюють:

    1.    пост-математика: порівняння двох реальностей через цифри
приклад: “15 клієнтів по 1000 грн = вінос мозку 24/7. 75 продажів шаблону по 199 грн = ті ж 15к але ти спиш”
    2.    пост-цифри: конкретні продажі, конкретний місяць, без прикрас
    3.    пост-момент: одна деталь = жива картинка

теми (чергувати):

    •    гроші і доходи
    •    notion-шаблони
    •    тривожність
    •    тіло і здоров’я
    •    цифрові продукти і blacksea
    •    фріланс і робота
    •    звички і системи
    •    ранок і рутина
    •    читання і навчання

поточна фаза акаунту: тижні 1-4 (довіра)
зараз НЕ продаємо курс. будуємо “я теж так думала”. пишемо особисті історії, цифри, помилки.

жорсткий ліміт: пост не довший за 500 символів разом з пробілами і переносами рядків. ціль 460. краще коротше ніж довше.

мова: пиши ВИКЛЮЧНО українською. жодного англійського чи російського слова і жодних англійських вставок (no “POV”, “ah”, “finally”). єдиний виняток — власні назви брендів/продуктів (notion, threads, gumroad, blacksea, ai). якщо сигнали або приклади іншою мовою — бери лише суть, але текст поста тільки українською."""

# Threads hard limit; we aim a little under it for safety.
MAX_CHARS = 500
TARGET_CHARS = 460


class WriterAgent:
    def __init__(self, model=None, max_tokens=None):
        self.model = model or settings.WRITER_MODEL
        self.max_tokens = max_tokens or settings.WRITER_MAX_TOKENS

    def run(self, brief: dict, memory) -> str:
        # Lazy import so DB-only commands (--stats) don't require the SDK.
        from anthropic import Anthropic

        recent_topics = memory.get_recent_topics()
        best_post = memory.get_best_performing_post()

        user_message = (
            "напиши один threads пост на основі цього дослідження:\n\n"
            f"тема: {brief['keyword']}\n"
            f"сигнали: {brief['trend_signals']}\n"
            f"що зараз публікують топ-акаунти ніші за охопленням "
            f"(орієнтир по темах/форматах/хуках, НЕ копіювати дослівно): "
            f"{brief.get('peer_signals', [])}\n"
            f"кут: {brief['angle']}\n\n"
            f"вже опубліковані теми цього тижня (не повторювати): {recent_topics}\n"
            f"останній пост який добре зайшов: {best_post}\n\n"
            f"максимум {MAX_CHARS} символів, ціль {TARGET_CHARS}.\n"
            "поверни лише текст поста. без пояснень. без лапок навколо тексту."
        )

        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        text = self._call(client, [{"role": "user", "content": user_message}])

        # Safety net: the model occasionally overshoots the 500-char cap.
        if len(text) > MAX_CHARS:
            text = self._call(
                client,
                [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": (
                            f"задовгий ({len(text)} символів). скороти до {TARGET_CHARS} "
                            "символів максимум. збережи голос, головну деталь і цифри. "
                            "поверни лише текст поста."
                        ),
                    },
                ],
            )

        # Last resort: hard-trim on a paragraph/line boundary so we never 400.
        if len(text) > MAX_CHARS:
            text = self._trim(text)
        return text

    def _call(self, client, messages: list) -> str:
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        text = response.content[0].text.strip().strip('"').strip()
        return self._sanitize(text)

    @staticmethod
    def _sanitize(text: str) -> str:
        """Enforce the voice rule deterministically: no em/en dashes.
        A spaced dash becomes a comma; a bare one becomes a space. Word
        hyphens (notion-шаблон) are left untouched."""
        text = text.replace(" — ", ", ").replace(" – ", ", ")
        text = text.replace("—", " ").replace("–", " ")
        text = text.replace(" ,", ",")
        # collapse runs of spaces without touching newlines
        while "  " in text:
            text = text.replace("  ", " ")
        return text.strip()

    @staticmethod
    def _trim(text: str) -> str:
        if len(text) <= MAX_CHARS:
            return text
        window = text[:MAX_CHARS]
        for sep in ("\n\n", "\n", ". ", " "):
            cut = window.rfind(sep)
            if cut > MAX_CHARS * 0.6:  # don't trim away more than ~40%
                return window[:cut].rstrip()
        return window.rstrip()

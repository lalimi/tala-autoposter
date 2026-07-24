"""Agent 2 — WriterAgent: write a Threads post (single) or chain (checklist/guide)
in the brand's voice from a ResearchBrief. The voice (system prompt) comes from
the Brand, so the same agent writes for @tala.sav and @blacksea."""
from __future__ import annotations

import re

from config import settings
from config.brands import TALA, Brand

# Threads hard limit; we aim a little under it for safety.
MAX_CHARS = 500
TARGET_CHARS = 460


class WriterAgent:
    def __init__(self, brand: Brand = TALA, model=None, max_tokens=None):
        self.brand = brand
        self.system_prompt = brand.system_prompt
        self.model = model or settings.WRITER_MODEL
        self.max_tokens = max_tokens or settings.WRITER_MAX_TOKENS

    def run(self, brief: dict, memory) -> str:
        recent_topics = memory.get_recent_topics()
        best_post = memory.get_best_performing_post()
        recent_texts = memory.recent_post_texts()

        seed = brief.get("seed")  # a real high-reach post to adapt, if scraped
        if seed:
            # Seed-driven: translate/adapt a post that actually worked, keeping
            # its hook and structure close but regrounding it in this persona.
            user_message = (
                "ось РЕАЛЬНИЙ пост що зібрав багато реакцій "
                f"({seed.get('likes', 0)}♥). твоя задача: переписати його "
                "українською в СВОЄМУ голосі як пост для threads.\n\n"
                f"пост-джерело:\n«{seed['text'][:600]}»\n\n"
                f"дотична тема з твоєї ротації: {brief['keyword']}\n"
                f"кут: {brief['angle']}\n\n"
                "правила адаптації:\n"
                "- тримайся близько до ХУКА і структури джерела, це те що спрацювало\n"
                "- переклади й адаптуй ідею українською, природно, не дослівний переклад\n"
                "- ВСІ особисті факти, цифри, суми, продукти замінюй на СВОЇ справжні "
                "(зі свого системного промпта). чужі цифри й claims не переносити\n"
                "- якщо джерело англійською чи про іншу нішу, бери лише механіку хука "
                "й перекладай у свій контекст\n"
                f"вже опубліковані теми (не повторювати): {recent_topics}\n"
                f"останні пости (не повторюй їх): {recent_texts}\n"
                f"максимум {MAX_CHARS} символів, ціль {TARGET_CHARS}.\n"
                "поверни лише текст поста. без пояснень. без лапок навколо тексту."
            )
        else:
            # No scraped seed yet (e.g. a brand without a scraper) — generate
            # from the topic + angle as before.
            peer_line = ""
            if brief.get("peer_signals"):
                peer_line = (
                    f"що зараз публікують топ-акаунти ніші за охопленням "
                    f"(орієнтир по темах/форматах/хуках, НЕ копіювати дослівно): "
                    f"{brief['peer_signals']}\n"
                )
            user_message = (
                "напиши один threads пост на основі цього дослідження:\n\n"
                f"тема: {brief['keyword']}\n"
                f"сигнали: {brief['trend_signals']}\n"
                f"{peer_line}"
                f"кут: {brief['angle']}\n\n"
                f"вже опубліковані теми цього тижня (не повторювати): {recent_topics}\n"
                f"останні пости (НЕ повторюй ці історії, деталі й формулювання): {recent_texts}\n"
                f"пост який зайшов найкраще за переглядами (орієнтир на стиль, не копіювати): {best_post}\n\n"
                f"важливо: тему “{brief['keyword']}” дослівно в пості не називати. "
                "покажи її через конкретну ситуацію, деталь або цифру.\n"
                f"максимум {MAX_CHARS} символів, ціль {TARGET_CHARS}.\n"
                "поверни лише текст поста. без пояснень. без лапок навколо тексту."
            )

        client = self._client()
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

        text = self._deslop(client, text)

        # Last resort: hard-trim on a paragraph/line boundary so we never 400.
        if len(text) > MAX_CHARS:
            text = self._trim(text)
        # A single post must never carry a chain-style "---" divider (the model
        # sometimes adds one); turn it into a plain paragraph break.
        return self._strip_dividers(text)

    def run_chain(self, brief: dict, memory, max_parts: int | None = None) -> list[str]:
        """Write a checklist / mini-guide as a short post chain. Returns the parts
        (each <=500 chars). The pipeline publishes them as a Threads reply-chain.
        Length is capped by settings.CHAIN_MAX_PARTS (3 on Vercel, more on a VPS)."""
        max_parts = max_parts or settings.CHAIN_MAX_PARTS
        steps = max(1, max_parts - 1)  # parts after the hook
        recent_topics = memory.get_recent_topics()
        recent_texts = memory.recent_post_texts()
        peer_line = ""
        if brief.get("peer_signals"):
            peer_line = (
                f"що публікують топ-акаунти (орієнтир ФОРМАТУ, не копіювати): "
                f"{brief['peer_signals']}\n"
            )
        user_message = (
            "напиши ЛАНЦЮЖОК (thread) для threads — чек-лист або міні-гайд "
            "на основі цього дослідження:\n\n"
            f"тема: {brief['keyword']}\n"
            f"сигнали: {brief['trend_signals']}\n"
            f"{peer_line}"
            f"кут: {brief['angle']}\n\n"
            f"вже опубліковані теми цього тижня (не повторювати): {recent_topics}\n"
            f"останні пости (НЕ повторюй ці історії, деталі й формулювання): {recent_texts}\n\n"
            "формат ланцюжка:\n"
            f"- РІВНО {max_parts} постів (1 хук + {steps} пункти), не більше.\n"
            "- 1-й пост: хук-обіцянка — що людина отримає, чому варто зберегти. коротко. "
            f"тему “{brief['keyword']}” дослівно не називати, хук через ситуацію чи цифру.\n"
            f"- далі {steps} пост(и): конкретні пункти чек-листа або кроки гайду. "
            "один пункт = один пост, з деталлю чи цифрою. остання частина — завершена думка.\n"
            "- це ГАЙД, тож структуровані короткі пункти й кроки тут доречні "
            "(виняток із правила про відсутність списків).\n"
            "- дотримуйся голосу бренду з системного промпта, тільки українською.\n"
            "- кожен пост максимум 500 символів.\n"
            "- розділяй пости рядком лише з трьох дефісів: ---\n"
            "- поверни лише пости й роздільники, без нумерації й пояснень."
        )
        client = self._client()
        raw = self._call(
            client, [{"role": "user", "content": user_message}], max_tokens=4000
        )
        raw = self._deslop(client, raw, is_chain=True)
        parts = [p.strip() for p in re.split(r"\n?-{3,}\n?", raw) if p.strip()]
        return [self._trim(p) for p in parts][:max_parts]

    def run_comment(self, target: dict) -> str:
        """Write a short, natural reply to someone else's post, in the brand
        voice. Reactive and relevant — no pitch, no link, no CTA."""
        user_message = (
            "ось чужий пост у threads, під яким ти хочеш залишити природний коментар:\n\n"
            f"автор: @{target.get('username', '')}\n"
            f"пост: «{(target.get('text') or '').strip()[:600]}»\n\n"
            "напиши коротку живу відповідь у твоєму голосі, як звичайна людина в коментарях:\n"
            "- 1-2 короткі речення, максимум ~250 символів\n"
            "- реагуй саме на зміст цього поста. це може бути будь-що доречне: "
            "підтримати, погодитись, легко пожартувати, поділитись схожим моментом\n"
            "- тема НЕ обовʼязково про продуктивність, notion чи продукти. "
            "коментуй на загальні, побутові теми так само природно\n"
            "- гумор вітається, якщо доречний; але без сарказму згори, по-доброму\n"
            "- нічого не рекламуй, без посилань, без згадки своїх продуктів, без CTA\n"
            "- не починай зі звертання на кшталт 'привіт', одразу думка\n"
            "- поверни лише текст коментаря, без лапок і пояснень"
        )
        client = self._client()
        text = self._call(client, [{"role": "user", "content": user_message}],
                          max_tokens=1500)
        return self._trim(text)

    # Traits that read as AI-written and should be edited out.
    _DESLOP_RULES = (
        "прибери все що видає що це писав чат:\n"
        "- вступні розгони й мета-фрази («ось», «сьогодні розкажу», «уяви»)\n"
        "- симетричні конструкції («не X, а Y», «коли роблю — добре, коли ні — погано»)\n"
        "- охайну мораль чи урок у фіналі, гладкі узагальнення, кліше\n"
        "- рівні тричастинні структури де все занадто складається\n"
        "додай натомість живого: обірвану думку, конкретну деталь якої не вигадаєш, "
        "нерівний ритм, як пише жива людина між справами.\n"
        "голос, факти, цифри й будь-які посилання ЗБЕРЕЖИ. довжину не збільшуй."
    )

    def _deslop(self, client, text: str, is_chain: bool = False) -> str:
        """Editor pass: rewrite a draft to sound human, stripping AI tells.
        Best-effort — on any failure the original draft is kept."""
        try:
            fmt = (
                "це ЛАНЦЮЖОК постів, розділених рядком ---. збережи роздільники "
                "--- і кількість частин.\n" if is_chain else ""
            )
            edited = self._call(client, [{"role": "user", "content": (
                "нижче чернетка поста. перепиши її живіше.\n\n"
                f"{fmt}{self._DESLOP_RULES}\n\n"
                f"чернетка:\n{text}\n\n"
                "поверни лише готовий текст, без пояснень і без лапок."
            )}], max_tokens=1200 if is_chain else 700)
            return edited if edited.strip() else text
        except Exception:
            return text

    @staticmethod
    def _client():
        # Lazy import so DB-only commands (--stats) don't require the SDK.
        # Kimi (Moonshot) exposes an Anthropic-compatible API, so the same SDK
        # serves both providers; base_url picks the provider.
        from anthropic import Anthropic

        kwargs = {"api_key": settings.WRITER_API_KEY}
        if settings.WRITER_BASE_URL:
            kwargs["base_url"] = settings.WRITER_BASE_URL
        return Anthropic(**kwargs)

    def _call(self, client, messages: list, max_tokens: int | None = None) -> str:
        # Thinking models (kimi-k3, sonnet-5) prepend a ThinkingBlock and can
        # burn the whole budget on it, returning no text at all — so take text
        # blocks only, and retry once with double the budget on an empty reply.
        budget = max_tokens or self.max_tokens
        thinking = (
            {"type": "enabled", "budget_tokens": settings.WRITER_THINKING_BUDGET}
            if settings.WRITER_THINKING_BUDGET
            else {"type": "disabled"}
        )
        for _attempt in range(2):
            response = client.messages.create(
                model=self.model,
                max_tokens=budget,
                system=self.system_prompt,
                messages=messages,
                thinking=thinking,
            )
            text = "".join(
                b.text for b in response.content if getattr(b, "type", "") == "text"
            )
            text = text.strip().strip('"').strip()
            if text:
                return self._sanitize(text)
            budget *= 2
        raise RuntimeError(
            f"writer returned no text after 2 attempts (model={self.model}, "
            f"stop_reason={getattr(response, 'stop_reason', '?')})"
        )

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
    def _strip_dividers(text: str) -> str:
        """Drop standalone '---' separator lines from a SINGLE post (they belong
        only between chain parts), collapsing them into a paragraph break."""
        text = re.sub(r"(?m)^[ \t]*-{2,}[ \t]*$", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
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

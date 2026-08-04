"""Agent 2 — WriterAgent: write a Threads post (single) or chain (checklist/guide)
in the brand's voice from a ResearchBrief. The voice (system prompt) comes from
the Brand, so the same agent writes for @tala.sav and @blacksea."""
from __future__ import annotations

import logging
import re

from config import settings
from config.brands import TALA, Brand

logger = logging.getLogger("tala")

# Threads hard limit; we aim a little under it for safety.
MAX_CHARS = 500
TARGET_CHARS = 460


class WriterAgent:
    def __init__(self, brand: Brand = TALA, model=None, max_tokens=None):
        self.brand = brand
        self.system_prompt = brand.system_prompt
        self.model = model or settings.WRITER_MODEL
        self.max_tokens = max_tokens or settings.WRITER_MAX_TOKENS
        # Per-brand so an X account without Premium (280 chars) can't silently
        # produce posts the publisher will reject. Threads stays at 500.
        self.max_chars = getattr(brand, "max_post_chars", MAX_CHARS) or MAX_CHARS
        self.target_chars = max(80, int(self.max_chars * 0.92))

    # Hook types the writer must rotate through. Left to the model, it always
    # reached for #1 (income reveal) because the system prompt names it the
    # strongest and hard-codes 447/94/60к — so 447 opened 11 of 40 posts. The
    # pipeline now picks one, and the numbers hook is just one option of six.
    # Descriptions of the MECHANISM, never a phrase to copy. Two of these used to
    # quote a stock opening ("не показуй нікому, збережи собі", "ВСІ ХТО ...") and
    # the model reproduced it verbatim every time that hook came up — three posts
    # in a row opened with the same 38 characters.
    # Formats taken from the donor accounts' own posts, not invented: numbered
    # how-tos, plain result statements, audience questions, tool stacks, honest
    # progress reports. The previous set pushed literary vignettes ("scene with
    # no conclusion", "a detail you couldn't invent") and produced posts about
    # kettles and cold tea that nobody in this niche writes.
    HOOK_TYPES = (
        "ВЕЛИКИЙ СПИСОК: заявка на досвід у першому рядку («прочитала понад "
        "1000 книжок», «зібрала 14 продуктів») + обіцянка («ось 20 з них») + "
        "далі 15-30 пронумерованих пунктів, кожен одним коротким рядком. це "
        "формат, який дав акаунту 21 191 перегляд проти звичайних 200-300",
        "нумерований список: заголовок-обіцянка, далі 5-10 коротких пунктів "
        "з нового рядка, кожен конкретний",
        "покрокова інструкція «як зробити X за N кроків», кроки пронумеровані",
        "прямий результат: що вийшло, з конкретною цифрою, без розгону",
        "питання до аудиторії, на яке хочеться відповісти у коментарях",
        "показати свою річ: «ось так виглядає мій …» і що це дає",
        "чесний звіт про процес: що робиш, скільки триває, що вийшло досі "
        "(навіть якщо результат нульовий)",
        "стек інструментів: перелік того, чим користуєшся, і навіщо кожен",
        "непопулярна думка про свою нішу і чому ти так вважаєш",
    )
    _URL_RE = re.compile(r"https?://\S+")

    @classmethod
    def _strip_links(cls, text: str) -> str:
        """Remove URLs the post was told not to include. The prompt-level ban was
        ignored — a sell=False draft still ended with the course link. On Threads
        a stray link costs reach; on X it costs ~13x more per post ($0.20 vs
        $0.015), so this is enforced rather than requested."""
        cleaned = cls._URL_RE.sub("", text or "")
        # tidy the empty line the URL usually sat on
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def _fact_block(fact: dict | None) -> str:
        """Ground the post in one real, brand-owned fact. The prompt's three
        hardcoded numbers meant every post was a rephrase of the same material;
        the owner's own posts each carried something new and measured ~1.8x
        better on views."""
        if not fact:
            return ""
        detail = f"\nдеталі: {fact['detail']}" if fact.get("detail") else ""
        return (
            "ФАКТ ДЛЯ ЦЬОГО ПОСТА (обовʼязково побудуй пост саме на ньому):\n"
            f"  {fact['text']}{detail}\n"
            "- це справжня інформація, не вигадуй навколо неї інших цифр\n"
            "- пост має нести саме ЦЕЙ факт як новину/суть, а не переказувати "
            "загальні тези про твій шлях\n"
            "- НЕ вигадуй історію створення продукту (скільки вечорів робила, "
            "коли саме сіла, за який час написала) — різні пости про той самий "
            "продукт почнуть суперечити один одному. якщо цього нема у факті, "
            "не називай\n"
            "- живу деталь бери зі свого боку досвіду (що відчувала, де була, "
            "що подумала), а не з вигаданої виробничої хронології\n"
        )

    # HOW the first line is built, kept separate from WHAT the hook does. The
    # hook alone still locked the grammar: "explain who shouldn't read this"
    # produces "не показуй ..." or "якщо ти ..., не читай" almost every time, so
    # rewriting the hook description only swapped one template for another.
    OPENING_FORMS = (
        "почни із заголовка-обіцянки: що читач отримає з цього поста",
        "почни з питання до читача",
        "почни з результату або цифри, одразу пояснивши, чого вона стосується",
        "почни зі слів «ось так виглядає …» і назви свою річ",
        "почни з «як я …» і назви конкретну дію",
        "почни з непопулярної думки про нішу",
        "почни з переліку інструментів або пунктів, без вступу",
        "почни з того, що саме ти зараз робиш і на якому етапі",
    )
    @staticmethod
    def _hook_block(hook: str | None, opening: str | None = None) -> str:
        if not hook and not opening:
            return ""
        out = ""
        if hook:
            out += (
                f"ТИП ХУКА ДЛЯ ЦЬОГО ПОСТА (обовʼязково саме цей): {hook}\n"
                "не підміняй його іншим типом, навіть якщо інший здається сильнішим.\n"
            )
        if opening:
            out += (
                f"ФОРМА ПЕРШОГО РЯДКА (обовʼязкова): {opening}\n"
                "перший рядок будується саме так, навіть якщо звично інакше.\n"
            )
        return out

    # Currency amounts and percentages — the shapes an invented business claim
    # takes. Process numbers ("4-5 годин", "2 місяці", "15 хвилин") don't match.
    _MONEY_RE = re.compile(
        r"[$€£₴]\s?\d|\d[\d\s.,]*\s*(?:грн|гривень|долар\w*|usd|eur|\$|₴|к\b|тис)",
        re.IGNORECASE,
    )
    _PERCENT_RE = re.compile(r"\d+\s*(?:%|відсот)")
    # Sales platforms that compete with BlackSea — a BlackSea-owned persona must
    # not recommend them. The first live SoloHub post advised "gumroad для
    # оплати", so this is checked in code, not left to the prompt.
    _RIVAL_RE = re.compile(
        r"\b(gumroad|payhip|lemonsqueezy|lemon squeezy|teachable|sendowl|"
        r"podia|thinkific|kajabi|patreon|etsy)\b", re.IGNORECASE)

    @classmethod
    def _names_rival(cls, text: str) -> str | None:
        m = cls._RIVAL_RE.search(text or "")
        return m.group(0) if m else None

    @classmethod
    def _has_money_claim(cls, text: str) -> str | None:
        """Return the offending fragment, or None. Used only for brands whose
        persona has no real figures to quote."""
        for rx in (cls._MONEY_RE, cls._PERCENT_RE):
            m = rx.search(text or "")
            if m:
                return m.group(0)
        return None

    @staticmethod
    def _is_duplicate(text: str, openings: list[str]) -> bool:
        """True when the draft opens too much like a recent post. The prompt-level
        ban was ignored (447/94 kept opening posts days after the fix), so the
        check is enforced in code."""
        import difflib

        first = (text or "").strip().split("\n")[0].strip().lower()
        if not first:
            return False
        for old in openings:
            o = old.strip().lower()
            if difflib.SequenceMatcher(None, first[:70], o[:70]).ratio() > 0.6:
                return True
            # A long identical run at the start is the same template even when
            # the tails diverge enough to keep the ratio down: three drafts all
            # opened "не показуй цей список тому хто ..." at ratios 0.56-0.81.
            common = 0
            for a, b in zip(first, o):
                if a != b:
                    break
                common += 1
            if common >= 25:
                return True
        return False

    @staticmethod
    def _anti_repeat(openings: list[str]) -> str:
        """Feeding 12 FULL recent posts was a wall the model ignored — openings
        repeated verbatim and the same three numbers (447/94/60к) carried 8-11 of
        40 posts. Show just the openings and ban reusing them."""
        if not openings:
            return ""
        listed = "\n".join(f"  - {o}" for o in openings[:20])
        return (
            "ЗАЧИНИ ОСТАННІХ ПОСТІВ (заборонено починати схоже, заборонено "
            f"повторювати ці ж цифри й факти в хуку):\n{listed}\n"
            "візьми ІНШИЙ вхід: інша ситуація, інша деталь, інша цифра або взагалі "
            "без цифри. не кожен пост про дохід.\n"
        )

    def _sell_block(self, sell: bool, via_bio: bool = False) -> str:
        """Selling is decided by the pipeline, not by the model's mood: as an
        optional suggestion in the system prompt it produced a link in 2% of
        posts. Here it is either mandatory or forbidden for this post."""
        if not self.brand.product_url:
            return ""
        if sell and via_bio:
            offer = self.brand.bio_offer or "продукт у біо"
            return (
                "\nЦЕ ПРОДАЖНИЙ ПОСТ, АЛЕ БЕЗ ПОСИЛАННЯ (обовʼязково):\n"
                "- спочатку корисний пост по темі, як завжди\n"
                f"- у фіналі один короткий рядок що веде в біо ({offer}), "
                "у твоєму голосі, буденно\n"
                "- URL у текст НЕ вставляй, жодних http. тільки згадка що це в біо\n"
            )
        if sell:
            return (
                "\nЦЕ ПРОДАЖНИЙ ПОСТ (обовʼязково):\n"
                "- спочатку живий пост по темі, як завжди. історія/цифра/деталь\n"
                "- потім ОДИН короткий рядок-місток від себе до продукту, у твоєму "
                "голосі, без пафосу й без знаків оклику\n"
                f"- останнім рядком саме це посилання: {self.brand.product_url}\n"
                "- не перетворюй пост на рекламу: місток це фінал, а не суть\n"
            )
        return "\nу цьому пості НЕ згадуй курс і НЕ додавай жодних посилань.\n"

    def run(self, brief: dict, memory, sell: bool = False,
            hook: str | None = None, via_bio: bool = False,
            opening: str | None = None) -> str:
        recent_topics = memory.get_recent_topics()
        best_post = memory.get_best_performing_post()
        recent_openings = memory.recent_openings()

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
                "- копіюй СТРУКТУРУ джерела якомога ближче: якщо там список на "
                "20 пунктів — роби список на 20 пунктів, якщо покрокова "
                "інструкція — роби покрокову, якщо питання до аудиторії — "
                "став питання. міняється зміст, не форма\n"
                "- тримайся близько до ХУКА джерела, це те що спрацювало\n"
                "- переклади й адаптуй ідею українською, природно, не дослівний переклад\n"
                "- ВСІ особисті факти, цифри, суми, продукти замінюй на СВОЇ справжні "
                "(зі свого системного промпта). чужі цифри й claims не переносити\n"
                "- якщо джерело англійською чи про іншу нішу, бери лише механіку хука "
                "й перекладай у свій контекст\n"
                f"вже опубліковані теми (не повторювати): {recent_topics}\n"
                f"{self._fact_block(brief.get('fact'))}"
                f"{self._anti_repeat(recent_openings)}"
                f"{self._hook_block(hook, opening)}"
                f"{self._sell_block(sell, via_bio)}"
                f"максимум {self.max_chars} символів, ціль {self.target_chars}.\n"
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
                f"{self._fact_block(brief.get('fact'))}"
                f"{self._anti_repeat(recent_openings)}"
                f"{self._hook_block(hook, opening)}"
                f"{self._sell_block(sell, via_bio)}"
                f"пост який зайшов найкраще за переглядами (орієнтир на стиль, не копіювати): {best_post}\n\n"
                f"важливо: тему “{brief['keyword']}” дослівно в пості не називати. "
                "покажи її через конкретну ситуацію, деталь або цифру.\n"
                f"максимум {self.max_chars} символів, ціль {self.target_chars}.\n"
                "поверни лише текст поста. без пояснень. без лапок навколо тексту."
            )

        client = self._client()
        text = self._call(client, [{"role": "user", "content": user_message}])

        # Safety net: the model occasionally overshoots the 500-char cap.
        if len(text) > self.max_chars:
            text = self._call(
                client,
                [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": (
                            f"задовгий ({len(text)} символів). скороти до {self.target_chars} "
                            "символів максимум. збережи голос, головну деталь і цифри. "
                            "поверни лише текст поста."
                        ),
                    },
                ],
            )

        text = self._apply_guards(
            client, text, user_message, recent_openings,
            sell=sell, via_bio=via_bio,
        )

        # Last resort: hard-trim on a paragraph/line boundary so we never 400.
        if len(text) > self.max_chars:
            text = self._trim(text)
        # A single post must never carry a chain-style "---" divider (the model
        # sometimes adds one); turn it into a plain paragraph break.
        return self._strip_dividers(text)

    def _apply_guards(self, client, text: str, user_message: str,
                      recent_openings: list[str], *, sell: bool = False,
                      via_bio: bool = False, is_chain: bool = False) -> str:
        """Every code-level check a draft must pass, for singles AND chains.

        These lived inline in run() only, so chains — 90% of Tala's output — went
        out unchecked: identical openings two posts running, and for X the link
        policy (a $0.20 vs $0.015 difference per post) never applied at all.
        """
        keep_format = (
            "збережи структуру ланцюжка: ті самі частини, розділені рядком ---.\n"
            if is_chain else ""
        )

        def regen(instruction: str) -> str:
            return self._call(
                client,
                [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": keep_format + instruction},
                ],
                max_tokens=4000 if is_chain else None,
            )

        # Repetition: the prompt-level ban kept being ignored.
        if self._is_duplicate(text, recent_openings):
            logger.info("draft repeated a recent opening — regenerating")
            text = regen(
                "цей зачин уже був у недавньому пості. перепиши з ЦІЛКОМ іншим "
                "входом: інша сцена, інша деталь, інші цифри або зовсім без "
                "цифр. тему й голос збережи. поверни лише текст."
            )

        # A BlackSea-owned persona must not advertise a competing storefront.
        if getattr(self.brand, "forbid_rival_platforms", False):
            rival = self._names_rival(text)
            if rival:
                logger.info("draft named a rival platform (%r) — regenerating", rival)
                text = regen(
                    f"у тексті згадана конкурентна платформа «{rival}». перепиши "
                    "без неї. якщо йдеться про приймання оплати чи де продавати "
                    "— це blacksea. notion, ai, no-code лишати можна. "
                    "поверни лише текст."
                )

        # Personas without a real trading history must not invent figures.
        if getattr(self.brand, "forbid_money_claims", False):
            bad = self._has_money_claim(text)
            if bad:
                logger.info("draft invented a figure (%r) — regenerating", bad)
                text = regen(
                    f"у тексті є вигадана цифра: «{bad}». перепиши БЕЗ сум, "
                    "відсотків, конверсій і кількості продажів. результат "
                    "описуй якісно. цифри дозволені лише про час і процес. "
                    "поверни лише текст."
                )
                still = self._has_money_claim(text)
                if still:
                    logger.warning("still contains a figure (%r) after retry", still)

        text = self._deslop(client, text, is_chain=is_chain)

        # Link policy runs LAST: the de-slop rewrite re-adds URLs an earlier pass
        # removed, which is how a sell=False post still went out with the link.
        if (not sell or via_bio) and self._URL_RE.search(text or ""):
            logger.info("stripping link from a %s post",
                        "bio-CTA" if via_bio else "non-sales")
            text = self._strip_links(text)
        elif sell and not via_bio and self.brand.product_url \
                and not self._URL_RE.search(text or ""):
            logger.info("sales post lost its link — reattaching")
            text = f"{text}\n\n{self.brand.product_url}"
        return text

    def run_chain(self, brief: dict, memory, max_parts: int | None = None,
                  sell: bool = False, hook: str | None = None,
                  via_bio: bool = False, opening: str | None = None) -> list[str]:
        """Write a checklist / mini-guide as a short post chain. Returns the parts
        (each <=500 chars). The pipeline publishes them as a Threads reply-chain.
        Length is capped by settings.CHAIN_MAX_PARTS (3 on Vercel, more on a VPS)."""
        max_parts = (max_parts or getattr(self.brand, "max_chain_parts", 0)
                     or settings.CHAIN_MAX_PARTS)
        steps = max(1, max_parts - 1)  # parts after the hook
        recent_topics = memory.get_recent_topics()
        recent_openings = memory.recent_openings()
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
            f"{self._fact_block(brief.get('fact'))}"
            f"{self._anti_repeat(recent_openings)}"
            f"{self._hook_block(hook, opening)}"
            f"{self._sell_block(sell, via_bio)}\n"
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
        raw = self._apply_guards(
            client, raw, user_message, recent_openings,
            sell=sell, via_bio=via_bio, is_chain=True,
        )
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
            "- нічого не рекламуй, без посилань, без згадки своїх продуктів, без CTA\n"
            "- не починай зі звертання на кшталт 'привіт', одразу думка\n"
            "\nЖОРСТКО (це коментар під постом РЕАЛЬНОЇ людини, яка це прочитає):\n"
            "- НЕ висміювати автора поста, не знецінювати його ситуацію, не "
            "прогнозувати йому провал, не вгадувати «що буде далі» глузливо\n"
            "- НЕ вчити й не давати непрошених порад зверхньо ('підказка:', "
            "'давайте вгадаю', 'класика'). ти рівний співрозмовник, не гуру\n"
            "- сарказм лише про СПІЛЬНІ обставини (клієнти, дедлайни, софт, "
            "рутина), ніколи в бік людини, якій відповідаєш\n"
            "- якщо людина шукає роботу, скаржиться, ділиться складним або "
            "просить допомоги — тільки по-людськи: підтримати або по суті\n"
            "\nРЕЛЕВАНТНІСТЬ (коментар має сенс лише там, де тебе почує твоя "
            "аудиторія):\n"
            "- пост мусить бути дотичним до твого світу (твоя ніша, робота, "
            "інструменти, гроші/фріланс, або просто життєва тема де твій досвід "
            "звучить природно). ключове слово могло зловити пост випадково: "
            "«ставка» про іпотеку, «премʼєра» про кіно — це НЕ твоє\n"
            "- якщо тема чужа (нерухомість, політика, спорт, крипта, реклама "
            "чужих послуг) — не вигадуй зачіпку, це виглядає як випадковий бот\n"
            "- пост не українською: відповідай українською лише якщо тема справді "
            "твоя; інакше пропускай\n"
            "\nякщо доречного, доброго І релевантного коментаря не виходить — "
            "поверни рівно: SKIP (це нормальний і частий результат)\n"
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
        "натомість зроби пост зрозумілішим: чітка обіцянка в першому рядку, "
        "конкретика по суті, зрозуміло навіщо це читати. НЕ додавай художніх "
        "деталей (чай, чайник, світло, погода, час на годиннику як атмосфера) — "
        "у цій ніші так не пишуть.\n"
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

    def _trim(self, text: str) -> str:
        if len(text) <= self.max_chars:
            return text
        window = text[:self.max_chars]
        for sep in ("\n\n", "\n", ". ", " "):
            cut = window.rfind(sep)
            if cut > self.max_chars * 0.6:  # don't trim away more than ~40%
                return window[:cut].rstrip()
        return window.rstrip()

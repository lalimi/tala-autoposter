"""Top up the @blacksea fact bank, 10.11.2026.

By 10.11 every active fact had been used 4-18 times, so posts kept retelling
the same material. Sources are public and checked on the site that day: the
blog posts of 04.11 (packaging a product) and 05.11 (AI landing builder) and
the commission agreement in force from 07.11. Deliberately left out: the
04.11 blog line that foreign buyers pay via Stripe or PayPal (the Global page
is still a waitlist), and the "1 092 авторів вже продають" counter (the admin
shows far fewer sellers with sales).

Idempotent: a fact whose text is already in the bank is skipped.

    .venv/bin/python -m scripts.add_blacksea_facts_2026_11
"""
from __future__ import annotations

import store

BLOG_0411 = "блог blacksea 04.11.2026 (як упакувати продукт)"

FACTS = [
    ("advice",
     "перед тим як ділитися посиланням, пройди покупку свого продукту сам від "
     "початку до кінця: чи приходить файл і чи відкривається notion-шаблон без "
     "запиту доступу", BLOG_0411),
    ("advice",
     "покажи продукт зсередини: 2–4 скріни реальних сторінок, а не тільки "
     "красиву обкладинку. людина має бачити, за що платить", BLOG_0411),
    ("advice",
     "перелік «що входить» з цифрами переконує краще за прикметники: кількість "
     "сторінок, формат, програма замість «унікальний якісний продукт»",
     BLOG_0411 + "; приклад: «52 сторінки · A4 · PDF»"),
    ("advice",
     "найдешевша ціна в ніші часто читається як «щось не так»: випиши ціни "
     "5–10 схожих продуктів і стань у середину діапазону, якщо твій не гірший "
     "обсягом і якістю", BLOG_0411),
    ("advice",
     "умови використання краще написати прямо на сторінці продукту одним-двома "
     "реченнями: тільки для себе чи можна в комерційних проєктах і чи можна "
     "перепродавати. без них частина людей просто не купує", BLOG_0411),
    ("advice",
     "почни з одного каналу і веди його хоча б місяць: пʼять платформ по одному "
     "посту результату не дадуть", BLOG_0411),
    ("advice",
     "pinterest працює як пошук по картинках, і там шукають саме планери, "
     "шаблони й розмальовки: пін живе місяцями, а сторіс зникає за добу",
     BLOG_0411),
    ("feature",
     "для AI-конструктора лендингу достатньо назви продукту й ціни: з них у "
     "кабінеті збирається промпт, а агент (Claude чи Cursor) робить і публікує "
     "сторінку з кнопкою оплати приблизно за 5 хвилин",
     "блог blacksea 05.11.2026"),
    ("mechanics",
     "з 07.11.2026, коли оплата йде на рахунок blacksea, продаж оформлюється "
     "договором комісії: у звіті комісіонера по кожному продажу видно ціну "
     "продажу, винагороду платформи і дохід автора",
     "договір комісії, п. 4.5 і розділ 6, чинний з 07.11.2026"),
    ("mechanics",
     "гроші приходять щопʼятниці за попередній розрахунковий цикл (7 "
     "календарних днів), а не одразу після покупки: цей час потрібен, щоб "
     "перевірити, що покупець отримав доступ, розглянути повернення і відсіяти "
     "шахрайські платежі",
     "договір комісії, п. 1.9 і 5.3. дати циклу видно у звіті комісіонера; не "
     "рахуй, на який саме день прийдуть гроші за конкретну покупку"),
]


def main() -> None:
    existing = {r["text"] for r in store._req("GET", "brand_facts", params={
        "select": "text", "brand": "eq.blacksea"}) or []}
    payload = [{"brand": "blacksea", "kind": k, "text": t, "detail": d,
                "active": True, "used_count": 0}
               for k, t, d in FACTS if t not in existing]
    if not payload:
        print("nothing to add: all facts already in the bank")
        return
    out = store._req("POST", "brand_facts", json=payload,
                     prefer="return=representation") or []
    for r in out:
        print(r["id"], r["kind"], r["text"][:80])
    print(f"added {len(out)} fact(s)")


if __name__ == "__main__":
    main()

import asyncio
import json
import random
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path
from playwright.async_api import async_playwright

# --- ТВОИ ДАННЫЕ ---
LOGIN = "тут логин"
PASSWORD = "тут пароль"
HEADLESS = False

EXPIRATION_DATE = date(2027, 6, 1)
SUMMER_MONTHS = [6, 7, 8]

COMMENTS = [
    "Круто",
    "Прикольно",
    "Очень круто",
    "Спасибо",
    "классно",
    "Было супер",
    "Крутой урок",
    "Спасибо за урок",
]

MAX_RETRIES = 3
STATE_FILE = Path(__file__).parent / "state.json"


def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Не удалось прочитать state.json ({e}). Начинаю с чистого листа.")
    return {"completed_lessons": [], "runs": 0, "last_run": None}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Не удалось сохранить state.json ({e}).")


async def get_card_title(btn):
    try:
        return await btn.evaluate("""el => {
            let node = el;
            for (let i = 0; i < 6; i++) {
                if (!node.parentElement) break;
                node = node.parentElement;
                const candidates = node.querySelectorAll(
                    'h1, h2, h3, h4, h5, [class*="title" i], [class*="name" i], [class*="heading" i]'
                );
                for (const c of candidates) {
                    const t = (c.innerText || '').trim();
                    if (t && t.length > 5 && t.length < 300 && !t.includes('Заполнить')) return t;
                }
            }
            return null;
        }""")
    except Exception:
        return None


async def click_next_page(page):
    try:
        pagination_text = page.locator('text=/Страница\\s+\\d+\\s+из\\s+\\d+/').locator("visible=true").first
        if await pagination_text.count() > 0:
            container = pagination_text.locator("xpath=..")
            buttons = container.locator('button, [role="button"]').locator("visible=true")
            btn_count = await buttons.count()
            if btn_count >= 2:
                last_btn = buttons.nth(btn_count - 1)
                try:
                    is_disabled = await last_btn.is_disabled()
                except Exception:
                    is_disabled = False
                if not is_disabled:
                    await last_btn.click(timeout=5000)
                    print("  ✅ Кликнул по '>' (последняя кнопка в пагинации)")
                    return True
                else:
                    print("  ⏹ Кнопка '>' неактивна — последняя страница")
                    return False
            svgs = container.locator('svg').locator("visible=true")
            if await svgs.count() >= 2:
                await svgs.last.click(timeout=5000)
                print("  ✅ Кликнул по '>' (svg в пагинации)")
                return True
    except Exception as e:
        print(f"  Способ 1 не сработал: {e}")

    try:
        for label in ["Следующая страница", "Следующая", "Next page", "Next"]:
            btn = page.locator(f'[aria-label*="{label}" i]').locator("visible=true").first
            if await btn.count() > 0:
                try:
                    if await btn.is_disabled():
                        return False
                except Exception:
                    pass
                await btn.click(timeout=5000)
                print(f"  ✅ Кликнул по aria-label='{label}'")
                return True
    except Exception:
        pass

    try:
        text_btn = page.locator(
            'button:has-text("Следующие"), a:has-text("Следующие"), '
            'button:has-text("Следующая"), a:has-text("Следующая"), '
            'button:has-text("Далее"), a:has-text("Далее")'
        ).locator("visible=true").first
        if await text_btn.count() > 0:
            try:
                if await text_btn.is_disabled():
                    return False
            except Exception:
                pass
            await text_btn.click(timeout=5000)
            print("  ✅ Кликнул по тексту")
            return True
    except Exception:
        pass

    print("  ❌ Не смог найти кнопку следующей страницы")
    return False


# ============ ИСПРАВЛЕННАЯ ФУНКЦИЯ ============
async def try_fill_anketa(page):
    try:
        modal = page.locator('[role="dialog"], div[class*="modal"], div[class*="Modal"]').locator("visible=true").first
        if await modal.count() > 0:
            scope = modal
        else:
            scope = page

        # ✅ ИЩЕМ СМАЙЛИКИ ПО КЛАССУ base-mood (как на скрине)
        smiles = scope.locator('div[class*="base-mood"]').locator("visible=true")
        n = await smiles.count()
        
        if n < 15:
            print(f"  ⚠️ Найдено {n} смайликов, ожидалось 15.")
            return False

        print("  Ставлю оценки...")
        await smiles.nth(4).click()
        await page.wait_for_timeout(400)
        await smiles.nth(9).click()
        await page.wait_for_timeout(400)
        await smiles.nth(14).click()
        await page.wait_for_timeout(400)

        # Комментарий
        comment_box = scope.locator("textarea").first
        if await comment_box.count() > 0 and await comment_box.is_visible():
            random_comment = random.choice(COMMENTS)
            await comment_box.fill(random_comment)
            print(f"  Оставил комментарий: «{random_comment}»")

        # ✅ КНОПКА ОТПРАВКИ (добавил точный текст "Отправить анкету")
        submit_btn = scope.locator(
            'button:has-text("Отправить анкету"), '
            'button:has-text("Отправить"), '
            'button:has-text("Завершить")'
        ).locator("visible=true").first

        if await submit_btn.count() > 0 and await submit_btn.is_visible():
            await submit_btn.click()
            print("  🚀 Анкета отправлена.")
            return True
        else:
            print("  ⚠️ Кнопка 'Отправить' не найдена.")
            return False
    except Exception as e:
        print(f"  ⚠️ Ошибка при заполнении: {e}")
        return False


async def close_modal(page):
    try:
        close_btn = page.locator('button[aria-label="Закрыть"], svg[class*="close"]').locator("visible=true").first
        if await close_btn.count() > 0:
            await close_btn.click(timeout=3000)
            await page.wait_for_timeout(1500)
    except Exception:
        pass


async def main():
    start_time = time.perf_counter()
    crashed = False
    today = date.today()

    if today >= EXPIRATION_DATE:
        print("🎓 Ну вот и всё, моя смена окончена! ...")
        return

    if today.month in SUMMER_MONTHS:
        print("🏖️ у меня каникулы! я на пляже 😃 ...")
        return

    print("Проверяю доступность сайта bvbinfo.ru...")
    try:
        await asyncio.to_thread(urllib.request.urlopen, "https://bvbinfo.ru", None, 10)
        print("✅ Сайт доступен. Продолжаю.")
    except Exception as e:
        print(f"\n❌ Ошибка доступа к сайту: {e}")
        print("🫡 Босс, у меня не получилось... Похоже, нет интернета или сайт лежит. 😔")
        return

    state = load_state()
    completed_set = set(state.get("completed_lessons", []))
    state["runs"] = state.get("runs", 0) + 1

    if completed_set:
        print(f"📂 Найдено state.json: уже пройдено {len(completed_set)} анкет ранее.")
    print(f"🔁 Запуск №{state['runs']}")

    print("Запуск браузера...")
    total_filled = 0
    total_skipped_titles = set()
    total_failed = 0
    page_num = 1

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 800, 'height': 600}
        )
        page = await context.new_page()

        try:
            print("Переход на страницу авторизации...")
            await page.goto("https://bvbinfo.ru/auth", wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)

            try:
                await page.locator('text="Логин"').first.click()
                await page.wait_for_timeout(2000)
            except Exception:
                pass

            print("Ввод логина и пароля...")
            await page.locator('input[type="text"]').first.fill(LOGIN)
            await page.locator('input[type="password"]').fill(PASSWORD)
            await page.locator('button:has-text("Войти")').click()
            await page.wait_for_timeout(7000)

            print("Вход выполнен. Переход в 'Мои горизонты'...")
            entered = False

            try:
                link = page.locator('a[href*="my-horizons"]').locator("visible=true").first
                if await link.count() > 0:
                    await link.click(timeout=5000)
                    entered = True
            except Exception:
                pass

            if not entered:
                try:
                    btn = page.get_by_text("Мои горизонты", exact=False).locator("visible=true").first
                    if await btn.count() > 0:
                        await btn.click(timeout=5000)
                        entered = True
                except Exception:
                    pass

            if not entered:
                try:
                    btn = page.get_by_text("РМГ", exact=True).locator("visible=true").first
                    if await btn.count() > 0:
                        await btn.click(timeout=5000)
                        entered = True
                except Exception:
                    pass

            if not entered:
                await page.goto("https://bvbinfo.ru/lk-student/my-horizons", wait_until="domcontentloaded")

            await page.wait_for_timeout(5000)

            try:
                await page.locator('text="Прошедшие"').first.wait_for(state="visible", timeout=10000)
                print("Успешно попали в раздел 'Мои горизонты'.")
            except Exception:
                await page.goto("https://bvbinfo.ru/lk-student/my-horizons", wait_until="domcontentloaded")
                await page.wait_for_timeout(5000)

            try:
                cookie_btn = page.locator('button:has-text("Хорошо")').first
                if await cookie_btn.count() > 0 and await cookie_btn.is_visible():
                    await cookie_btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            print("Переключаюсь на вкладку 'Прошедшие'...")
            try:
                await page.locator('text="Прошедшие"').first.click()
                await page.wait_for_timeout(3000)
            except Exception:
                pass

            while True:
                print(f"\n--- Обработка страницы {page_num} ---")
                filled_on_this_page = 0
                failed_attempts = {}

                while True:
                    fill_buttons = page.locator('button:has-text("Заполнить анкету")').locator("visible=true")
                    count = await fill_buttons.count()
                    if count == 0:
                        print("На этой странице больше нет доступных анкет.")
                        break

                    found_new = False
                    for i in range(count):
                        btn = fill_buttons.nth(i)
                        if not await btn.is_visible():
                            continue

                        title = await get_card_title(btn)
                        key = title if title else f"pos_{i}"

                        if title and title in completed_set:
                            if title not in total_skipped_titles:
                                print(f"  ⏭ Пропускаю (уже пройдено): {title}")
                                total_skipped_titles.add(title)
                            continue

                        if key in failed_attempts:
                            continue

                        print(f"  📝 Анкета: {title or '(без названия)'}")

                        success = False
                        for attempt in range(1, MAX_RETRIES + 1):
                            if attempt > 1:
                                print(f"  🔄 Попытка {attempt}/{MAX_RETRIES}...")
                            try:
                                await btn.click(timeout=5000) # защита от зависаний
                                await page.wait_for_timeout(3000)

                                if await try_fill_anketa(page):
                                    success = True
                                    break
                                else:
                                    print(f"  ⚠️ Попытка {attempt}/{MAX_RETRIES} не удалась.")
                            except Exception as e:
                                print(f"  ⚠️ Попытка {attempt}/{MAX_RETRIES} упала: {e}")

                            if attempt < MAX_RETRIES:
                                await close_modal(page)
                                await page.wait_for_timeout(2000)

                        if success:
                            filled_on_this_page += 1
                            total_filled += 1

                            if title:
                                completed_set.add(title)
                                state["completed_lessons"] = sorted(completed_set)
                                state["last_run"] = datetime.now().isoformat(timespec="seconds")
                                save_state(state)

                            await page.wait_for_timeout(3000)
                            found_new = True
                            break
                        else:
                            print(f"  ❌ Не смог заполнить после {MAX_RETRIES} попыток. Пропускаю.")
                            total_failed += 1
                            failed_attempts[key] = True
                            await close_modal(page)
                            await page.wait_for_timeout(1500)
                            continue

                    if not found_new:
                        print("  Все анкеты на этой странице либо пройдены, либо провалены.")
                        break

                print(f"На странице {page_num}: новых заполнено {filled_on_this_page}")

                print("Пытаюсь перейти на следующую страницу...")
                moved = await click_next_page(page)
                if moved:
                    page_num += 1
                    await page.wait_for_timeout(4000)
                else:
                    print("Все страницы обработаны.")
                    break

        except Exception as e:
            crashed = True
            print(f"\n❌ Произошла ошибка: {e}")
            error_text = str(e).lower()
            if "net::err" in error_text or "timeout" in error_text or "connection" in error_text or "internet" in error_text:
                print("🫡 Босс, у меня не получилось... Похоже, интернет отвалился прямо во время работы. 😔")

        finally:
            state["last_run"] = datetime.now().isoformat(timespec="seconds")
            save_state(state)

            elapsed = time.perf_counter() - start_time
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)

            print("\n" + "=" * 40)
            print(f"🫡 БОСС, Я ВСЁ СДЕЛАЛ!")
            print(f"⏱  Затрачено времени: {mins} мин {secs} сек")
            print(f"📊 Новых анкет заполнено: {total_filled}")
            print(f"📄 Проверено страниц: {page_num}")
            if total_failed > 0:
                print(f"❌ Провалено после {MAX_RETRIES} попыток: {total_failed}")

            if crashed:
                print(f"⏭  Пропущено (уже были в state.json): {len(total_skipped_titles)}")

            print(f"💾 Пройдено за всё время: {len(completed_set)} анкет")
            print("=" * 40)

            print("Закрываю браузер через:", end=" ", flush=True)
            for i in range(5, -1, -1):
                if i > 0:
                    print(f"{i},", end=" ", flush=True)
                else:
                    print("0...", flush=True)
                await asyncio.sleep(1)

            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
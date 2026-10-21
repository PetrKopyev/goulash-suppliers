import pytest

from app.pipeline.tidy import format_value, pick_name, tidy_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("640 Руб. за 1 кг.", "640 ₽/кг"),
        ("259 руб. /100г", "259 ₽/100 г"),
        ("136,50 р.", "136,50 ₽"),
        ("1 632 ₽ / кг", "1 632 ₽/кг"),
        ("от 10 000 до 500 000 рублей", "от 10 000 до 500 000 ₽"),
        ("от 60 кг по Екатеринбургу", "от 60 кг по Екатеринбургу"),
    ],
)
def test_money_values(raw, expected):
    assert format_value("price", raw) == expected
    assert format_value("price", expected) == expected


def test_other_values_untouched():
    assert format_value("payment", "оплата  по счёту, 100 руб.") == "оплата по счёту, 100 руб."


def test_names():
    assert tidy_name("ТК 'Синяя Вечность'") == "ТК «Синяя Вечность»"
    assert tidy_name('ООО "ОБИЛИЕ"') == "ООО «ОБИЛИЕ»"
    assert tidy_name("SuomiFish — c нами не заштормит") == "SuomiFish"
    assert tidy_name("Икорыч: Красная икра, рыба") == "Икорыч"
    assert tidy_name("Ресторан Ресторан ГАДЫ КРАБЫ И ВИНО") == "Ресторан ГАДЫ КРАБЫ И ВИНО"
    assert tidy_name("Ням Ням") == "Ням Ням"
    assert pick_name(["https://edaprof.ru/", None, 'ООО "ЭДА"'], "edaprof.ru") == "ООО «ЭДА»"
    assert pick_name(["", "Лосось оптом — Рыбный двор"], "rybdvor.ru") == "Rybdvor"
    assert pick_name(["КленМаркет.ру"], "klenmarket.ru") == "Klenmarket"
    assert pick_name(["Проверка безопасности соединения"], "хлебный-двор.рф") == "Хлебный-двор"


def test_product_titles_are_not_names():
    tvorog = "творог фермерский"
    text = "Творог фермерский 7-9% жирности от Деликатески – это натуральный продукт"
    assert pick_name(["Творог фермерский 7-9% жир. Деликатеска 500г"], "delikateska.ru", tvorog, text) == "Деликатеска"
    assert pick_name(["Нори, маменори"], "fishport.com", "нори и рис для суши") == "Fishport"
    assert pick_name(["Пластиковые контейнеры для суши", None], "rm-pack.ru", "нори") == "Rm-pack"
    containers = "Контейнеры и лотки для доставки еды оптом в Екатеринбурге"
    assert pick_name([containers], "ekb.complexbar.ru", "контейнеры", "на сайте Комплекс-Бар") == "Комплекс-Бар"
    assert pick_name(["Лосось охлажденный", 'ООО "БИК"'], "bik-fish.ru", "лосось охлаждённый") == "ООО «БИК»"
    legal = 'ООО "КРЕСТЬЯНСКОЕ ХОЗЯЙСТВО НИКОЛЬСКАЯ СЛОБОДА"'
    assert (
        pick_name(["Творог от Никольской Слободы", legal], "nksl.ru", "творог")
        == "ООО «КРЕСТЬЯНСКОЕ ХОЗЯЙСТВО НИКОЛЬСКАЯ СЛОБОДА»"
    )
    assert pick_name(["Творог от Никольской Слободы"], "nksl.ru", "творог") == "Nksl"
    assert pick_name(["Фермерский Магазин натуральных продуктов"], "fermersky.com", "", "Фермерский") == "Фермерский"


def test_brand_names_with_category_word_stay():
    bread = "хлеб от местной пекарни"
    assert pick_name(["Европейская пекарня"], "ekathleb.ru", bread) == "Европейская пекарня"
    assert pick_name(["Ремесленный Хлеб"], "ремесленныйхлеб.рф", bread) == "Ремесленный Хлеб"
    assert pick_name(["Птицефабрика «Северная»"], "severnaya.ru", "куриное филе") == "Птицефабрика «Северная»"

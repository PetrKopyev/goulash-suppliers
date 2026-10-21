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
    assert pick_name(["https://edaprof.ru/", None, 'ООО "ЭДА"'], "edaprof.ru") == "ООО «ЭДА»"
    assert pick_name(["", "Лосось оптом — Рыбный двор"], "rybdvor.ru") == "Лосось оптом"
    assert pick_name(["КленМаркет.ру"], "klenmarket.ru") == "klenmarket.ru"

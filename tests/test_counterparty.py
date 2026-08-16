"""Unit tests for counterparty extraction (stdlib unittest)."""

from __future__ import annotations

import unittest

from app.services.counterparty import extract_counterparty


class ExtractCounterpartyTests(unittest.TestCase):
    def test_user_examples(self) -> None:
        cases = [
            (
                r"Оплата товарів\послуг\SILPO KIYEV UKR : Google Pay ****8801.",
                "SILPO",
            ),
            (
                r"Оплата товарів\послуг\PELIKAN ROUG KYIV UKR : Google Pay ****8801.",
                "PELIKAN ROUG",
            ),
            (
                r"Оплата товарів\послуг - інтернет\WIZARDS OF COAST, INC RENTON USA : M4M ****2556.",
                "WIZARDS OF COAST, INC",
            ),
            (
                r"Переказ грошових коштів з карткового рахунку на картку через MasterCard\Visa\MONODirect KYIV UKR : Apple Pay ****3410.",
                "MONODirect",
            ),
        ]
        for note, expected in cases:
            with self.subTest(note=note):
                self.assertEqual(extract_counterparty(note), expected)

    def test_sample_file_merchants(self) -> None:
        cases = [
            (
                r"Оплата товарів\послуг - інтернет\SHOP.SILPO.UA 10 KYIV UKR : Google Pay ****8801.",
                "SHOP.SILPO.UA",
            ),
            (
                r"Оплата товарів\послуг - інтернет\Plarium Europe S.A.R.L Luxembourg LUX : Google Pay ****8801.",
                "Plarium Europe S.A.R.L",
            ),
            (
                r"Оплата товарів\послуг\GLOVOAPP.COM1 KYIV UKR : Google Pay ****8801.",
                "GLOVOAPP.COM1",
            ),
            (
                r"Оплата товарів\послуг - інтернет\ElectronCorp Kyiv UKR : Apple Pay ****3410.",
                "ElectronCorp",
            ),
            (
                r"Оплата товарів\послуг\Glovo Kyiv UKR : Google Pay ****8801.",
                "Glovo",
            ),
        ]
        for note, expected in cases:
            with self.subTest(note=note):
                self.assertEqual(extract_counterparty(note), expected)

    def test_ua_company_and_payee(self) -> None:
        self.assertEqual(
            extract_counterparty(
                'Оплата послуг компанії ТОВ "ЄВРО-РЕКОНСТРУКЦІЯ" (абоненська плата)'
            ),
            'ТОВ "ЄВРО-РЕКОНСТРУКЦІЯ"',
        )
        self.assertEqual(
            extract_counterparty("Оплата послуг компанії Київводоканал"),
            "Київводоканал",
        )
        self.assertEqual(
            extract_counterparty(
                "Оплата послуг компанії YASNO Київські енергетичні послуги (електроенергія)"
            ),
            "YASNO Київські енергетичні послуги",
        )
        self.assertEqual(
            extract_counterparty("Переказ на користь Дегтяр Тетяна Миколаївна"),
            "Дегтяр Тетяна Миколаївна",
        )
        self.assertEqual(
            extract_counterparty('Переказ на користь ОСББ "КИЇВСЬКА ВЕНЕЦІЯ"'),
            'ОСББ "КИЇВСЬКА ВЕНЕЦІЯ"',
        )

    def test_topup_and_insurance(self) -> None:
        self.assertEqual(
            extract_counterparty("Пополнение счета САПОЖНІКОВ ОЛЕКСАНДР ДМИТРОВИЧ"),
            "САПОЖНІКОВ ОЛЕКСАНДР ДМИТРОВИЧ",
        )
        self.assertEqual(
            extract_counterparty("Поповнення рахунку САПОЖНІКОВ ДМИТРО МИКОЛАЙОВИЧ"),
            "САПОЖНІКОВ ДМИТРО МИКОЛАЙОВИЧ",
        )
        self.assertEqual(
            extract_counterparty(
                "/=01~страховий платіж~  4300009996.6~Сапожніков Олександр Дмитрович~3263720573=/"
            ),
            "Сапожніков Олександр Дмитрович",
        )

    def test_no_counterparty(self) -> None:
        empties = [
            "",
            None,
            "Переказ на карту 536354****4120",
            "Списання коштів з карт.рах. за операцією Сплата за товар втерміналі S1160CUN за картою 522871******9460, код авторизації 772910, від 23.06.2026",
            "Купівля іноземної валюти в сумі 240,00 EUR по курсу 51,680000 за допомогою UKRSIB online",
            r"Комісія за переказ грошових коштів на картковий рахунок через MasterCard\Visa UKRSIBOnline",
            "винагор. згiд. Гiг-конт. 63/01/24 вiд 12.01.2024 БЕЗ ПДВ((11488655))",
        ]
        for note in empties:
            with self.subTest(note=note):
                self.assertEqual(extract_counterparty(note), "")

    def test_truncates_to_255(self) -> None:
        long_name = "A" * 300
        note = rf"Оплата товарів\послуг\{long_name} KYIV UKR : Google Pay ****8801."
        self.assertEqual(len(extract_counterparty(note)), 255)


if __name__ == "__main__":
    unittest.main()

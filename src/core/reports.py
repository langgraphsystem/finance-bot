"""PDF report generation using WeasyPrint + Jinja2."""

import asyncio
import logging
import uuid
from collections import Counter
from datetime import date

from jinja2 import BaseLoader, Environment
from sqlalchemy import func, select

from src.core.access import apply_scope_filter
from src.core.db import async_session
from src.core.models.category import Category
from src.core.models.enums import LifeEventType, TransactionType
from src.core.models.life_event import LifeEvent
from src.core.models.transaction import Transaction
from src.core.observability import observe

logger = logging.getLogger(__name__)

# HTML template for monthly report (with Jinja2 label variables)
MONTHLY_REPORT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; color: #333; }
        h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
        h2 { color: #2980b9; margin-top: 30px; }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th { background-color: #3498db; color: white; padding: 10px; text-align: left; }
        td { padding: 8px 10px; border-bottom: 1px solid #ddd; }
        tr:nth-child(even) { background-color: #f2f2f2; }
        .total-row { font-weight: bold; background-color: #ebf5fb !important; }
        .amount { text-align: right; }
        .summary { background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }
        .income { color: #27ae60; }
        .expense { color: #e74c3c; }
        .footer { margin-top: 40px; font-size: 0.8em; color: #999;
                  border-top: 1px solid #ddd; padding-top: 10px; }
    </style>
</head>
<body>
    <h1>{{ title }}</h1>
    <p>{{ labels.period }}: {{ period }}</p>

    <div class="summary">
        <h2>{{ labels.summary }}</h2>
        <p class="income">{{ labels.income }}: ${{ "%.2f"|format(total_income) }}</p>
        <p class="expense">{{ labels.expenses }}: ${{ "%.2f"|format(total_expense) }}</p>
        <p><strong>{{ labels.balance }}:
        ${{ "%.2f"|format(total_income - total_expense) }}</strong></p>
    </div>

    {% if expense_categories %}
    <h2>{{ labels.expenses_by_category }}</h2>
    <table>
        <tr><th>{{ labels.category }}</th>
        <th class="amount">{{ labels.amount }}</th>
        <th class="amount">%</th></tr>
        {% for cat in expense_categories %}
        <tr>
            <td>{{ cat.icon }} {{ cat.name }}</td>
            <td class="amount">${{ "%.2f"|format(cat.total) }}</td>
            <td class="amount">{{ "%.1f"|format(cat.percent) }}%</td>
        </tr>
        {% endfor %}
        <tr class="total-row">
            <td>{{ labels.total }}</td>
            <td class="amount">${{ "%.2f"|format(total_expense) }}</td>
            <td class="amount">100%</td>
        </tr>
    </table>
    {% endif %}

    {% if income_categories %}
    <h2>{{ labels.income_by_category }}</h2>
    <table>
        <tr><th>{{ labels.category }}</th><th class="amount">{{ labels.amount }}</th></tr>
        {% for cat in income_categories %}
        <tr>
            <td>{{ cat.icon }} {{ cat.name }}</td>
            <td class="amount">${{ "%.2f"|format(cat.total) }}</td>
        </tr>
        {% endfor %}
    </table>
    {% endif %}

    {% if life_summary %}
    <h2>{{ labels.life_entries }}</h2>
    <div class="summary">
        <p><strong>{{ labels.total_entries }}:</strong> {{ life_summary.total }}</p>
        {% if life_summary.by_type %}
        <table>
            <tr><th>{{ labels.type }}</th><th class="amount">{{ labels.count }}</th></tr>
            {% for item in life_summary.by_type %}
            <tr>
                <td>{{ item.icon }} {{ item.label }}</td>
                <td class="amount">{{ item.count }}</td>
            </tr>
            {% endfor %}
        </table>
        {% endif %}
        {% if life_summary.recent %}
        <h3 style="margin-top: 20px;">{{ labels.recent_entries }}</h3>
        {% for event in life_summary.recent %}
        <p style="margin: 4px 0;">
            <span style="color: #999;">{{ event.date }}</span>
            {{ event.icon }} {{ event.text }}
            {% if event.tags %}<span style="color: #3498db;">{{ event.tags }}</span>{% endif %}
        </p>
        {% endfor %}
        {% endif %}
    </div>
    {% endif %}

    <div class="footer">
        {{ labels.generated_by }} | {{ generated_date }}
    </div>
</body>
</html>
"""

MONTH_NAMES_I18N: dict[str, dict[int, str]] = {
    "en": {
        1: "January",
        2: "February",
        3: "March",
        4: "April",
        5: "May",
        6: "June",
        7: "July",
        8: "August",
        9: "September",
        10: "October",
        11: "November",
        12: "December",
    },
    "ru": {
        1: "Январь",
        2: "Февраль",
        3: "Март",
        4: "Апрель",
        5: "Май",
        6: "Июнь",
        7: "Июль",
        8: "Август",
        9: "Сентябрь",
        10: "Октябрь",
        11: "Ноябрь",
        12: "Декабрь",
    },
    "es": {
        1: "Enero",
        2: "Febrero",
        3: "Marzo",
        4: "Abril",
        5: "Mayo",
        6: "Junio",
        7: "Julio",
        8: "Agosto",
        9: "Septiembre",
        10: "Octubre",
        11: "Noviembre",
        12: "Diciembre",
    },
    "fr": {
        1: "Janvier",
        2: "Février",
        3: "Mars",
        4: "Avril",
        5: "Mai",
        6: "Juin",
        7: "Juillet",
        8: "Août",
        9: "Septembre",
        10: "Octobre",
        11: "Novembre",
        12: "Décembre",
    },
    "de": {
        1: "Januar",
        2: "Februar",
        3: "März",
        4: "April",
        5: "Mai",
        6: "Juni",
        7: "Juli",
        8: "August",
        9: "September",
        10: "Oktober",
        11: "November",
        12: "Dezember",
    },
    "pt": {
        1: "Janeiro",
        2: "Fevereiro",
        3: "Março",
        4: "Abril",
        5: "Maio",
        6: "Junho",
        7: "Julho",
        8: "Agosto",
        9: "Setembro",
        10: "Outubro",
        11: "Novembro",
        12: "Dezembro",
    },
    "it": {
        1: "Gennaio",
        2: "Febbraio",
        3: "Marzo",
        4: "Aprile",
        5: "Maggio",
        6: "Giugno",
        7: "Luglio",
        8: "Agosto",
        9: "Settembre",
        10: "Ottobre",
        11: "Novembre",
        12: "Dicembre",
    },
    "uk": {
        1: "Січень",
        2: "Лютий",
        3: "Березень",
        4: "Квітень",
        5: "Травень",
        6: "Червень",
        7: "Липень",
        8: "Серпень",
        9: "Вересень",
        10: "Жовтень",
        11: "Листопад",
        12: "Грудень",
    },
    "pl": {
        1: "Styczeń",
        2: "Luty",
        3: "Marzec",
        4: "Kwiecień",
        5: "Maj",
        6: "Czerwiec",
        7: "Lipiec",
        8: "Sierpień",
        9: "Wrzesień",
        10: "Październik",
        11: "Listopad",
        12: "Grudzień",
    },
    "tr": {
        1: "Ocak",
        2: "Şubat",
        3: "Mart",
        4: "Nisan",
        5: "Mayıs",
        6: "Haziran",
        7: "Temmuz",
        8: "Ağustos",
        9: "Eylül",
        10: "Ekim",
        11: "Kasım",
        12: "Aralık",
    },
    "ar": {
        1: "يناير",
        2: "فبراير",
        3: "مارس",
        4: "أبريل",
        5: "مايو",
        6: "يونيو",
        7: "يوليو",
        8: "أغسطس",
        9: "سبتمبر",
        10: "أكتوبر",
        11: "نوفمبر",
        12: "ديسمبر",
    },
    "zh": {
        1: "一月",
        2: "二月",
        3: "三月",
        4: "四月",
        5: "五月",
        6: "六月",
        7: "七月",
        8: "八月",
        9: "九月",
        10: "十月",
        11: "十一月",
        12: "十二月",
    },
    "ja": {
        1: "1月",
        2: "2月",
        3: "3月",
        4: "4月",
        5: "5月",
        6: "6月",
        7: "7月",
        8: "8月",
        9: "9月",
        10: "10月",
        11: "11月",
        12: "12月",
    },
    "ko": {
        1: "1월",
        2: "2월",
        3: "3월",
        4: "4월",
        5: "5월",
        6: "6월",
        7: "7월",
        8: "8월",
        9: "9월",
        10: "10월",
        11: "11월",
        12: "12월",
    },
    "hi": {
        1: "जनवरी",
        2: "फरवरी",
        3: "मार्च",
        4: "अप्रैल",
        5: "मई",
        6: "जून",
        7: "जुलाई",
        8: "अगस्त",
        9: "सितंबर",
        10: "अक्टूबर",
        11: "नवंबर",
        12: "दिसंबर",
    },
}

MONTH_NAMES = MONTH_NAMES_I18N["ru"]

REPORT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "period": "Period",
        "summary": "Summary",
        "income": "Income",
        "expenses": "Expenses",
        "balance": "Balance",
        "expenses_by_category": "Expenses by Category",
        "income_by_category": "Income by Category",
        "category": "Category",
        "amount": "Amount",
        "total": "Total",
        "life_entries": "Life Entries",
        "total_entries": "Total entries",
        "type": "Type",
        "count": "Count",
        "recent_entries": "Recent Entries",
        "generated_by": "Generated by FinBot",
        "report_title": "Financial Report",
    },
    "ru": {
        "period": "Период",
        "summary": "Итоги",
        "income": "Доходы",
        "expenses": "Расходы",
        "balance": "Баланс",
        "expenses_by_category": "Расходы по категориям",
        "income_by_category": "Доходы по категориям",
        "category": "Категория",
        "amount": "Сумма",
        "total": "Итого",
        "life_entries": "Записи и заметки",
        "total_entries": "Всего записей",
        "type": "Тип",
        "count": "Кол-во",
        "recent_entries": "Последние записи",
        "generated_by": "Сгенерировано FinBot",
        "report_title": "Финансовый отчёт",
    },
    "es": {
        "period": "Periodo",
        "summary": "Resumen",
        "income": "Ingresos",
        "expenses": "Gastos",
        "balance": "Balance",
        "expenses_by_category": "Gastos por categoría",
        "income_by_category": "Ingresos por categoría",
        "category": "Categoría",
        "amount": "Monto",
        "total": "Total",
        "life_entries": "Entradas de vida",
        "total_entries": "Total de entradas",
        "type": "Tipo",
        "count": "Cantidad",
        "recent_entries": "Entradas recientes",
        "generated_by": "Generado por FinBot",
        "report_title": "Informe financiero",
    },
    "fr": {
        "period": "Période",
        "summary": "Résumé",
        "income": "Revenus",
        "expenses": "Dépenses",
        "balance": "Solde",
        "expenses_by_category": "Dépenses par catégorie",
        "income_by_category": "Revenus par catégorie",
        "category": "Catégorie",
        "amount": "Montant",
        "total": "Total",
        "life_entries": "Entrées de vie",
        "total_entries": "Total des entrées",
        "type": "Type",
        "count": "Nombre",
        "recent_entries": "Entrées récentes",
        "generated_by": "Généré par FinBot",
        "report_title": "Rapport financier",
    },
    "de": {
        "period": "Zeitraum",
        "summary": "Zusammenfassung",
        "income": "Einnahmen",
        "expenses": "Ausgaben",
        "balance": "Saldo",
        "expenses_by_category": "Ausgaben nach Kategorie",
        "income_by_category": "Einnahmen nach Kategorie",
        "category": "Kategorie",
        "amount": "Betrag",
        "total": "Gesamt",
        "life_entries": "Lebenseinträge",
        "total_entries": "Einträge gesamt",
        "type": "Typ",
        "count": "Anzahl",
        "recent_entries": "Letzte Einträge",
        "generated_by": "Erstellt von FinBot",
        "report_title": "Finanzbericht",
    },
    "pt": {
        "period": "Período",
        "summary": "Resumo",
        "income": "Receitas",
        "expenses": "Despesas",
        "balance": "Saldo",
        "expenses_by_category": "Despesas por categoria",
        "income_by_category": "Receitas por categoria",
        "category": "Categoria",
        "amount": "Valor",
        "total": "Total",
        "life_entries": "Registros de vida",
        "total_entries": "Total de registros",
        "type": "Tipo",
        "count": "Quantidade",
        "recent_entries": "Registros recentes",
        "generated_by": "Gerado por FinBot",
        "report_title": "Relatório financeiro",
    },
    "it": {
        "period": "Periodo",
        "summary": "Riepilogo",
        "income": "Entrate",
        "expenses": "Spese",
        "balance": "Saldo",
        "expenses_by_category": "Spese per categoria",
        "income_by_category": "Entrate per categoria",
        "category": "Categoria",
        "amount": "Importo",
        "total": "Totale",
        "life_entries": "Registrazioni di vita",
        "total_entries": "Totale registrazioni",
        "type": "Tipo",
        "count": "Conteggio",
        "recent_entries": "Registrazioni recenti",
        "generated_by": "Generato da FinBot",
        "report_title": "Rapporto finanziario",
    },
    "uk": {
        "period": "Період",
        "summary": "Підсумки",
        "income": "Доходи",
        "expenses": "Витрати",
        "balance": "Баланс",
        "expenses_by_category": "Витрати за категоріями",
        "income_by_category": "Доходи за категоріями",
        "category": "Категорія",
        "amount": "Сума",
        "total": "Разом",
        "life_entries": "Записи та нотатки",
        "total_entries": "Усього записів",
        "type": "Тип",
        "count": "Кількість",
        "recent_entries": "Останні записи",
        "generated_by": "Згенеровано FinBot",
        "report_title": "Фінансовий звіт",
    },
    "pl": {
        "period": "Okres",
        "summary": "Podsumowanie",
        "income": "Przychody",
        "expenses": "Wydatki",
        "balance": "Saldo",
        "expenses_by_category": "Wydatki wg kategorii",
        "income_by_category": "Przychody wg kategorii",
        "category": "Kategoria",
        "amount": "Kwota",
        "total": "Razem",
        "life_entries": "Wpisy życiowe",
        "total_entries": "Łącznie wpisów",
        "type": "Typ",
        "count": "Ilość",
        "recent_entries": "Ostatnie wpisy",
        "generated_by": "Wygenerowano przez FinBot",
        "report_title": "Raport finansowy",
    },
    "tr": {
        "period": "Dönem",
        "summary": "Özet",
        "income": "Gelir",
        "expenses": "Giderler",
        "balance": "Bakiye",
        "expenses_by_category": "Kategoriye göre giderler",
        "income_by_category": "Kategoriye göre gelir",
        "category": "Kategori",
        "amount": "Tutar",
        "total": "Toplam",
        "life_entries": "Yaşam kayıtları",
        "total_entries": "Toplam kayıt",
        "type": "Tür",
        "count": "Sayı",
        "recent_entries": "Son kayıtlar",
        "generated_by": "FinBot tarafından oluşturuldu",
        "report_title": "Finansal rapor",
    },
    "ar": {
        "period": "الفترة",
        "summary": "الملخص",
        "income": "الدخل",
        "expenses": "المصروفات",
        "balance": "الرصيد",
        "expenses_by_category": "المصروفات حسب الفئة",
        "income_by_category": "الدخل حسب الفئة",
        "category": "الفئة",
        "amount": "المبلغ",
        "total": "الإجمالي",
        "life_entries": "سجلات الحياة",
        "total_entries": "إجمالي السجلات",
        "type": "النوع",
        "count": "العدد",
        "recent_entries": "السجلات الأخيرة",
        "generated_by": "تم الإنشاء بواسطة FinBot",
        "report_title": "التقرير المالي",
    },
    "zh": {
        "period": "期间",
        "summary": "摘要",
        "income": "收入",
        "expenses": "支出",
        "balance": "余额",
        "expenses_by_category": "按类别支出",
        "income_by_category": "按类别收入",
        "category": "类别",
        "amount": "金额",
        "total": "合计",
        "life_entries": "生活记录",
        "total_entries": "总记录数",
        "type": "类型",
        "count": "数量",
        "recent_entries": "最近记录",
        "generated_by": "由 FinBot 生成",
        "report_title": "财务报告",
    },
    "ja": {
        "period": "期間",
        "summary": "概要",
        "income": "収入",
        "expenses": "支出",
        "balance": "残高",
        "expenses_by_category": "カテゴリー別支出",
        "income_by_category": "カテゴリー別収入",
        "category": "カテゴリー",
        "amount": "金額",
        "total": "合計",
        "life_entries": "ライフ記録",
        "total_entries": "記録総数",
        "type": "種類",
        "count": "件数",
        "recent_entries": "最近の記録",
        "generated_by": "FinBot で生成",
        "report_title": "財務レポート",
    },
    "ko": {
        "period": "기간",
        "summary": "요약",
        "income": "수입",
        "expenses": "지출",
        "balance": "잔액",
        "expenses_by_category": "카테고리별 지출",
        "income_by_category": "카테고리별 수입",
        "category": "카테고리",
        "amount": "금액",
        "total": "합계",
        "life_entries": "생활 기록",
        "total_entries": "총 기록",
        "type": "유형",
        "count": "횟수",
        "recent_entries": "최근 기록",
        "generated_by": "FinBot이 생성",
        "report_title": "재무 보고서",
    },
    "hi": {
        "period": "अवधि",
        "summary": "सारांश",
        "income": "आय",
        "expenses": "व्यय",
        "balance": "शेष",
        "expenses_by_category": "श्रेणी के अनुसार व्यय",
        "income_by_category": "श्रेणी के अनुसार आय",
        "category": "श्रेणी",
        "amount": "राशि",
        "total": "कुल",
        "life_entries": "जीवन प्रविष्टियाँ",
        "total_entries": "कुल प्रविष्टियाँ",
        "type": "प्रकार",
        "count": "संख्या",
        "recent_entries": "हाल की प्रविष्टियाँ",
        "generated_by": "FinBot द्वारा बनाया गया",
        "report_title": "वित्तीय रिपोर्ट",
    },
}

_LIFE_TYPE_LABELS_I18N: dict[str, dict] = {
    "en": {
        LifeEventType.note: ("📝", "Notes"),
        LifeEventType.food: ("🍽", "Food"),
        LifeEventType.drink: ("☕", "Drinks"),
        LifeEventType.mood: ("😊", "Mood"),
        LifeEventType.task: ("✅", "Tasks"),
        LifeEventType.reflection: ("🌙", "Reflection"),
    },
    "ru": {
        LifeEventType.note: ("📝", "Заметки"),
        LifeEventType.food: ("🍽", "Питание"),
        LifeEventType.drink: ("☕", "Напитки"),
        LifeEventType.mood: ("😊", "Настроение"),
        LifeEventType.task: ("✅", "Задачи"),
        LifeEventType.reflection: ("🌙", "Рефлексия"),
    },
    "es": {
        LifeEventType.note: ("📝", "Notas"),
        LifeEventType.food: ("🍽", "Comida"),
        LifeEventType.drink: ("☕", "Bebidas"),
        LifeEventType.mood: ("😊", "Estado de ánimo"),
        LifeEventType.task: ("✅", "Tareas"),
        LifeEventType.reflection: ("🌙", "Reflexión"),
    },
    "fr": {
        LifeEventType.note: ("📝", "Notes"),
        LifeEventType.food: ("🍽", "Alimentation"),
        LifeEventType.drink: ("☕", "Boissons"),
        LifeEventType.mood: ("😊", "Humeur"),
        LifeEventType.task: ("✅", "Tâches"),
        LifeEventType.reflection: ("🌙", "Réflexion"),
    },
    "de": {
        LifeEventType.note: ("📝", "Notizen"),
        LifeEventType.food: ("🍽", "Essen"),
        LifeEventType.drink: ("☕", "Getränke"),
        LifeEventType.mood: ("😊", "Stimmung"),
        LifeEventType.task: ("✅", "Aufgaben"),
        LifeEventType.reflection: ("🌙", "Reflexion"),
    },
    "pt": {
        LifeEventType.note: ("📝", "Notas"),
        LifeEventType.food: ("🍽", "Alimentação"),
        LifeEventType.drink: ("☕", "Bebidas"),
        LifeEventType.mood: ("😊", "Humor"),
        LifeEventType.task: ("✅", "Tarefas"),
        LifeEventType.reflection: ("🌙", "Reflexão"),
    },
    "it": {
        LifeEventType.note: ("📝", "Note"),
        LifeEventType.food: ("🍽", "Cibo"),
        LifeEventType.drink: ("☕", "Bevande"),
        LifeEventType.mood: ("😊", "Umore"),
        LifeEventType.task: ("✅", "Attività"),
        LifeEventType.reflection: ("🌙", "Riflessione"),
    },
    "uk": {
        LifeEventType.note: ("📝", "Нотатки"),
        LifeEventType.food: ("🍽", "Їжа"),
        LifeEventType.drink: ("☕", "Напої"),
        LifeEventType.mood: ("😊", "Настрій"),
        LifeEventType.task: ("✅", "Завдання"),
        LifeEventType.reflection: ("🌙", "Рефлексія"),
    },
    "pl": {
        LifeEventType.note: ("📝", "Notatki"),
        LifeEventType.food: ("🍽", "Jedzenie"),
        LifeEventType.drink: ("☕", "Napoje"),
        LifeEventType.mood: ("😊", "Nastrój"),
        LifeEventType.task: ("✅", "Zadania"),
        LifeEventType.reflection: ("🌙", "Refleksja"),
    },
    "tr": {
        LifeEventType.note: ("📝", "Notlar"),
        LifeEventType.food: ("🍽", "Yemek"),
        LifeEventType.drink: ("☕", "İçecekler"),
        LifeEventType.mood: ("😊", "Ruh hali"),
        LifeEventType.task: ("✅", "Görevler"),
        LifeEventType.reflection: ("🌙", "Yansıma"),
    },
    "ar": {
        LifeEventType.note: ("📝", "ملاحظات"),
        LifeEventType.food: ("🍽", "طعام"),
        LifeEventType.drink: ("☕", "مشروبات"),
        LifeEventType.mood: ("😊", "مزاج"),
        LifeEventType.task: ("✅", "مهام"),
        LifeEventType.reflection: ("🌙", "تأمل"),
    },
    "zh": {
        LifeEventType.note: ("📝", "笔记"),
        LifeEventType.food: ("🍽", "饮食"),
        LifeEventType.drink: ("☕", "饮品"),
        LifeEventType.mood: ("😊", "心情"),
        LifeEventType.task: ("✅", "任务"),
        LifeEventType.reflection: ("🌙", "反思"),
    },
    "ja": {
        LifeEventType.note: ("📝", "メモ"),
        LifeEventType.food: ("🍽", "食事"),
        LifeEventType.drink: ("☕", "飲み物"),
        LifeEventType.mood: ("😊", "気分"),
        LifeEventType.task: ("✅", "タスク"),
        LifeEventType.reflection: ("🌙", "振り返り"),
    },
    "ko": {
        LifeEventType.note: ("📝", "메모"),
        LifeEventType.food: ("🍽", "식사"),
        LifeEventType.drink: ("☕", "음료"),
        LifeEventType.mood: ("😊", "기분"),
        LifeEventType.task: ("✅", "할 일"),
        LifeEventType.reflection: ("🌙", "성찰"),
    },
    "hi": {
        LifeEventType.note: ("📝", "नोट्स"),
        LifeEventType.food: ("🍽", "भोजन"),
        LifeEventType.drink: ("☕", "पेय"),
        LifeEventType.mood: ("😊", "मूड"),
        LifeEventType.task: ("✅", "कार्य"),
        LifeEventType.reflection: ("🌙", "चिंतन"),
    },
}

jinja_env = Environment(loader=BaseLoader())


def render_report_html(
    *,
    title: str,
    period: str,
    total_income: float,
    total_expense: float,
    expense_categories: list[dict],
    income_categories: list[dict],
    life_summary: dict | None = None,
    generated_date: str,
    language: str = "ru",
) -> str:
    """Render the monthly report HTML from template and data."""
    labels = REPORT_LABELS.get(language, REPORT_LABELS["en"])
    template = jinja_env.from_string(MONTHLY_REPORT_TEMPLATE)
    return template.render(
        title=title,
        period=period,
        total_income=total_income,
        total_expense=total_expense,
        expense_categories=expense_categories,
        income_categories=income_categories,
        life_summary=life_summary,
        generated_date=generated_date,
        labels=labels,
    )


async def has_transactions_for_period(
    family_id: str, year: int, month: int, role: str = "owner",
) -> bool:
    """Check if any transactions exist for the given year/month."""
    start_date = date(year, month, 1)
    end_date = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    async with async_session() as session:
        stmt = select(func.count()).select_from(Transaction).where(
            Transaction.family_id == uuid.UUID(family_id),
            Transaction.date >= start_date,
            Transaction.date < end_date,
        )
        result = await session.execute(
            apply_scope_filter(stmt, Transaction, role)
        )
        return (result.scalar() or 0) > 0


@observe(name="generate_report")
async def generate_monthly_report(
    family_id: str,
    year: int | None = None,
    month: int | None = None,
    language: str = "ru",
    role: str = "owner",
    user_id: str | None = None,
) -> tuple[bytes, str]:
    """Generate a monthly PDF report.

    Returns:
        Tuple of (pdf_bytes, filename).
    """
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)

    async with async_session() as session:
        # Get expenses by category
        expense_stmt = (
            select(
                Category.name,
                Category.icon,
                func.sum(Transaction.amount).label("total"),
            )
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= start_date,
                Transaction.date < end_date,
                Transaction.type == TransactionType.expense,
            )
            .group_by(Category.name, Category.icon)
            .order_by(func.sum(Transaction.amount).desc())
        )
        expense_result = await session.execute(apply_scope_filter(expense_stmt, Transaction, role))
        expense_rows = expense_result.all()

        # Get total expense
        total_exp_stmt = select(func.sum(Transaction.amount)).where(
            Transaction.family_id == uuid.UUID(family_id),
            Transaction.date >= start_date,
            Transaction.date < end_date,
            Transaction.type == TransactionType.expense,
        )
        total_exp_result = await session.execute(
            apply_scope_filter(total_exp_stmt, Transaction, role)
        )
        total_expense = float(total_exp_result.scalar() or 0)

        # Get income by category
        income_stmt = (
            select(
                Category.name,
                Category.icon,
                func.sum(Transaction.amount).label("total"),
            )
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= start_date,
                Transaction.date < end_date,
                Transaction.type == TransactionType.income,
            )
            .group_by(Category.name, Category.icon)
            .order_by(func.sum(Transaction.amount).desc())
        )
        income_result = await session.execute(apply_scope_filter(income_stmt, Transaction, role))
        income_rows = income_result.all()

        # Get total income
        total_inc_stmt = select(func.sum(Transaction.amount)).where(
            Transaction.family_id == uuid.UUID(family_id),
            Transaction.date >= start_date,
            Transaction.date < end_date,
            Transaction.type == TransactionType.income,
        )
        total_inc_result = await session.execute(
            apply_scope_filter(total_inc_stmt, Transaction, role)
        )
        total_income = float(total_inc_result.scalar() or 0)

        # Get life events for the period
        life_events: list[LifeEvent] = []
        if user_id:
            life_result = await session.execute(
                select(LifeEvent)
                .where(
                    LifeEvent.family_id == uuid.UUID(family_id),
                    LifeEvent.user_id == uuid.UUID(user_id),
                    LifeEvent.date >= start_date,
                    LifeEvent.date < end_date,
                )
                .order_by(LifeEvent.date.desc())
            )
            life_events = list(life_result.scalars().all())
        else:
            life_result = await session.execute(
                select(LifeEvent)
                .where(
                    LifeEvent.family_id == uuid.UUID(family_id),
                    LifeEvent.date >= start_date,
                    LifeEvent.date < end_date,
                )
                .order_by(LifeEvent.date.desc())
            )
            life_events = list(life_result.scalars().all())

    # Build life events summary
    life_summary = _build_life_summary(life_events, language) if life_events else None

    # Format categories with percentages
    expense_categories = []
    for name, icon, total in expense_rows:
        expense_categories.append(
            {
                "name": name,
                "icon": icon or "",
                "total": float(total),
                "percent": (float(total) / total_expense * 100) if total_expense > 0 else 0,
            }
        )

    income_categories = []
    for name, icon, total in income_rows:
        income_categories.append(
            {
                "name": name,
                "icon": icon or "",
                "total": float(total),
            }
        )

    # Render HTML
    month_names = MONTH_NAMES_I18N.get(language, MONTH_NAMES_I18N["en"])
    labels = REPORT_LABELS.get(language, REPORT_LABELS["en"])
    report_title = labels["report_title"]
    html_content = render_report_html(
        title=f"{report_title} — {month_names[month]} {year}",
        period=f"{month_names[month]} {year}",
        total_income=total_income,
        total_expense=total_expense,
        expense_categories=expense_categories,
        income_categories=income_categories,
        life_summary=life_summary,
        generated_date=today.isoformat(),
        language=language,
    )

    # Generate PDF (in thread to avoid blocking the event loop)
    pdf_bytes = await asyncio.to_thread(html_to_pdf, html_content)
    filename = f"report_{year}_{month:02d}.pdf"

    return pdf_bytes, filename


_LIFE_TYPE_LABELS = _LIFE_TYPE_LABELS_I18N["ru"]


def _build_life_summary(events: list, language: str = "ru") -> dict:
    """Build a summary dict of life events for the report template."""
    type_counts = Counter(e.type for e in events)
    life_labels = _LIFE_TYPE_LABELS_I18N.get(language, _LIFE_TYPE_LABELS_I18N["en"])

    by_type = []
    for event_type, count in type_counts.most_common():
        icon, label = life_labels.get(event_type, ("📌", str(event_type)))
        by_type.append({"icon": icon, "label": label, "count": count})

    # Recent events (last 10)
    recent = []
    for event in events[:10]:
        icon, _ = life_labels.get(event.type, ("📌", ""))
        text = (event.text or "")[:80]
        if len(event.text or "") > 80:
            text += "..."
        tag_str = ""
        if event.tags:
            tag_str = " ".join(f"#{t}" for t in event.tags)
        recent.append(
            {
                "date": event.date.strftime("%d.%m"),
                "icon": icon,
                "text": text,
                "tags": tag_str,
            }
        )

    return {
        "total": len(events),
        "by_type": by_type,
        "recent": recent,
    }


def html_to_pdf(html_content: str) -> bytes:
    """Convert an HTML string to PDF bytes using WeasyPrint.

    Separated into its own function to allow easy mocking in tests
    (WeasyPrint requires system libraries that may not be available in CI).
    """
    from weasyprint import HTML  # lazy import — requires system GTK/Pango libs

    return HTML(string=html_content).write_pdf()

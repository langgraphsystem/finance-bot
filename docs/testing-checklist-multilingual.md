# Bot Testing Checklist — Multilingual
# Чек-лист тестирования бота — Многоязычный

> 74 skills · 12 agents · 14 domains
> 5 languages: English, Spanish, German, Russian, Kyrgyz

---

## 1. Onboarding / Регистрация

### 1.1 Start command

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 1.1 | Start bot | `/start` | `/start` | `/start` | `/start` | `/start` |

**Expected:** Welcome message + 4 language buttons

### 1.2 Language selection (button)

Click the language button. Expected: welcome in chosen language + "New account" / "Join family" buttons.

### 1.3 Language selection (text input)

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 1.3 | Type language name | `English` | `Español` | `Deutsch` | `Русский` | `Кыргызча` |

**Expected:** Auto-detect language, proceed to welcome screen.

### 1.4 New account — activity description

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 1.4a | Personal use | `Just personal finances` | `Solo finanzas personales` | `Nur persönliche Finanzen` | `Просто для себя` | `Жеке колдонуу үчүн` |
| 1.4b | Taxi driver | `I'm a taxi driver` | `Soy taxista` | `Ich bin Taxifahrer` | `Я таксист` | `Мен такси айдоочумун` |
| 1.4c | Trucker | `I'm a trucker` | `Soy camionero` | `Ich bin LKW-Fahrer` | `У меня трак` | `Мен жүк ташуучумун` |
| 1.4d | Manicure salon | `I run a nail salon` | `Tengo un salón de uñas` | `Ich habe ein Nagelstudio` | `У меня маникюрный салон` | `Менин маникюр салоном бар` |
| 1.4e | Flower shop | `I have a flower shop` | `Tengo una florería` | `Ich habe einen Blumenladen` | `У меня цветочный магазин` | `Менин гүл дүкөнүм бар` |
| 1.4f | Construction | `I run a construction company` | `Tengo una empresa de construcción` | `Ich habe ein Bauunternehmen` | `У меня строительная компания` | `Менин курулуш компаниям бар` |

**Expected:** Profile created with correct business type and categories.

### 1.5 Join family — invite code

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 1.5a | Valid code | `ABC12XYZ` | `ABC12XYZ` | `ABC12XYZ` | `ABC12XYZ` | `ABC12XYZ` |
| 1.5b | Invalid code | `WRONG` | `WRONG` | `WRONG` | `WRONG` | `WRONG` |
| 1.5c | Too short | `AB` | `AB` | `AB` | `AB` | `AB` |

**Expected:** (a) Joined family. (b) Error: invalid code. (c) Error: code too short.

---

## 2. Finance — Expenses & Income

### 2.1 Add expense

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 2.1a | Simple expense | `coffee 5` | `café 5` | `Kaffee 5` | `кофе 5` | `кофе 5` |
| 2.1b | Expense with merchant | `gas 50 Shell` | `gasolina 50 Shell` | `Tanken 50 Shell` | `бензин 50 Shell` | `бензин 50 Shell` |
| 2.1c | Groceries | `groceries 87.50` | `supermercado 87.50` | `Lebensmittel 87,50` | `продукты 87.50` | `азык-түлүк 87.50` |
| 2.1d | Multiple items | `lunch 15, taxi 8` | `almuerzo 15, taxi 8` | `Mittagessen 15, Taxi 8` | `обед 15, такси 8` | `түшкү тамак 15, такси 8` |

**Expected:** Expense recorded with amount, category auto-detected, merchant if provided.

### 2.2 Add income

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 2.2a | Simple income | `earned 2500` | `gané 2500` | `2500 verdient` | `заработал 2500` | `2500 таптым` |
| 2.2b | Salary | `got paid 3000` | `recibí salario 3000` | `Gehalt 3000 bekommen` | `получил зарплату 3000` | `айлык алдым 3000` |
| 2.2c | Client payment | `received 500 from Mike` | `recibí 500 de Mike` | `500 von Mike erhalten` | `получил 500 от Майка` | `Майктан 500 алдым` |

**Expected:** Income recorded with amount and source.

### 2.3 Correct category

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 2.3 | Fix category | `that's not food, it's transport` | `eso no es comida, es transporte` | `das ist kein Essen, sondern Transport` | `это не еда, а транспорт` | `бул тамак эмес, транспорт` |

**Expected:** Last transaction category updated.

### 2.4 Undo last

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 2.4 | Undo | `undo` | `deshacer` | `rückgängig` | `отмени последнюю` | `акыркысын жокко чыгар` |

**Expected:** Last entry removed.

### 2.5 Set budget

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 2.5a | Category budget | `budget for food 500 per week` | `presupuesto de comida 500 por semana` | `Budget für Essen 500 pro Woche` | `бюджет на еду 500 в неделю` | `тамак-ашка бюджет 500 жумасына` |
| 2.5b | Total budget | `monthly budget 3000` | `presupuesto mensual 3000` | `Monatsbudget 3000` | `бюджет на месяц 3000` | `айлык бюджет 3000` |

**Expected:** Budget limit set.

### 2.6 Mark paid

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 2.6 | Mark as paid | `cargo is paid` | `carga pagada` | `Fracht bezahlt` | `груз оплачен` | `жүк төлөндү` |

**Expected:** Transaction status → paid (no amount created).

### 2.7 Recurring payment

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 2.7a | Subscription | `Netflix subscription 15 monthly` | `suscripción Netflix 15 mensual` | `Netflix Abo 15 monatlich` | `подписка Netflix 15 в месяц` | `Netflix жазылуу 15 айына` |
| 2.7b | Rent | `rent 1500 monthly` | `alquiler 1500 mensual` | `Miete 1500 monatlich` | `аренда 1500 в месяц` | `ижара 1500 айына` |

**Expected:** Recurring payment registered.

### 2.8 Delete data

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 2.8 | Delete expenses | `delete expenses for January` | `borrar gastos de enero` | `Ausgaben für Januar löschen` | `удали расходы за январь` | `январдагы чыгымдарды өчүр` |

**Expected:** Confirmation prompt → deletion on confirm.

---

## 3. Receipt Scanning

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 3.1 | Scan receipt | Send photo of receipt | Send photo of receipt | Send photo of receipt | Фото чека | Чектин сүрөтүн жөнөт |
| 3.2 | Scan document | Send photo of invoice | Send photo of invoice | Send photo of invoice | Фото счёта/накладной | Эсеп-фактуранын сүрөтүн жөнөт |

**Expected:** OCR extracts store, amount, date, items. Creates expense entry.

---

## 4. Analytics

### 4.1 Quick stats

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 4.1a | Weekly stats | `how much did I spend this week?` | `¿cuánto gasté esta semana?` | `Wie viel habe ich diese Woche ausgegeben?` | `сколько потратил за неделю?` | `бул жумада канча короттум?` |
| 4.1b | Monthly stats | `spending this month` | `gastos de este mes` | `Ausgaben diesen Monat` | `расходы за месяц` | `бул айдагы чыгымдар` |

**Expected:** Total spending + breakdown by category.

### 4.2 Comparison

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 4.2 | Compare periods | `compare to last month` | `compara con el mes pasado` | `vergleiche mit letztem Monat` | `сравни с прошлым месяцем` | `өткөн ай менен салыштыр` |

**Expected:** Spending change in % with trends.

### 4.3 Report

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 4.3 | PDF report | `monthly report` | `informe mensual` | `Monatsbericht` | `отчёт за месяц` | `айлык отчёт` |

**Expected:** PDF document with charts and summary.

### 4.4 Deep analysis

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 4.4 | Full analysis | `full spending analysis for 3 months` | `análisis completo de gastos de 3 meses` | `komplette Ausgabenanalyse für 3 Monate` | `полный анализ трат за 3 месяца` | `3 айлык чыгымдардын толук анализи` |

**Expected:** Multi-dimensional analysis with trends and outliers.

---

## 5. Finance Specialist

### 5.1 Financial summary

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 5.1 | Where money goes | `where does my money go?` | `¿a dónde va mi dinero?` | `Wo geht mein Geld hin?` | `куда уходят деньги?` | `акчам кайда кетет?` |

**Expected:** Category breakdown of spending.

### 5.2 Invoice

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 5.2 | Generate invoice | `invoice Mike for plumbing job 500` | `factura para Mike por fontanería 500` | `Rechnung an Mike für Klempnerarbeit 500` | `выставь счёт Майку за работу 500` | `Майкка 500 иш үчүн эсеп чыгар` |

**Expected:** PDF invoice document.

### 5.3 Tax estimate

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 5.3 | Quarterly taxes | `how much do I owe in taxes?` | `¿cuánto debo en impuestos?` | `Wie viel Steuern schulde ich?` | `сколько налогов за квартал?` | `кварталдык салыктар канча?` |

**Expected:** Tax estimate with disclaimer.

### 5.4 Cash flow forecast

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 5.4 | Affordability | `can we afford a vacation?` | `¿podemos pagar unas vacaciones?` | `Können wir uns einen Urlaub leisten?` | `хватит ли денег на отпуск?` | `эс алууга акча жетеби?` |

**Expected:** Cash flow forecast with confidence level.

---

## 6. Tasks & Shopping Lists

### 6.1 Create task

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 6.1a | Simple task | `task: buy milk` | `tarea: comprar leche` | `Aufgabe: Milch kaufen` | `задача: купить молоко` | `тапшырма: сүт сатып алуу` |
| 6.1b | Task with deadline | `task: call dentist by Friday` | `tarea: llamar al dentista antes del viernes` | `Aufgabe: Zahnarzt bis Freitag anrufen` | `задача: позвонить стоматологу до пятницы` | `тапшырма: жумага чейин тиш доктурга чалуу` |

**Expected:** Task created with title and optional deadline.

### 6.2 List tasks

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 6.2 | Show tasks | `my tasks` | `mis tareas` | `meine Aufgaben` | `мои задачи` | `менин тапшырмаларым` |

**Expected:** List of open tasks with deadlines.

### 6.3 Set reminder

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 6.3a | Relative time | `remind me in 5 minutes to call` | `recuérdame en 5 minutos llamar` | `erinnere mich in 5 Minuten anzurufen` | `напомни через 5 минут позвонить` | `5 мүнөттөн кийин чалууну эскерт` |
| 6.3b | Specific time | `remind me at 3pm: meeting` | `recuérdame a las 3pm: reunión` | `erinnere mich um 15 Uhr: Meeting` | `напомни в 15:00: встреча` | `саат 15:00дө эскерт: жолугушуу` |
| 6.3c | Recurring | `remind me every Monday: report` | `recuérdame cada lunes: informe` | `erinnere mich jeden Montag: Bericht` | `напоминай каждый понедельник: отчёт` | `ар дүйшөмбүдө эскерт: отчёт` |

**Expected:** Reminder set with time and recurrence.

### 6.4 Complete task

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 6.4 | Done | `done with: buy milk` | `hecho: comprar leche` | `erledigt: Milch kaufen` | `выполнено: купить молоко` | `аткарылды: сүт сатып алуу` |

**Expected:** Task marked as complete.

### 6.5–6.8 Shopping list

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 6.5 | Add item | `add bread to shopping list` | `agrega pan a la lista` | `Brot auf die Einkaufsliste` | `добавь хлеб в список покупок` | `нан сатып алуу тизмесине кош` |
| 6.6 | View list | `my shopping list` | `mi lista de compras` | `meine Einkaufsliste` | `мой список покупок` | `менин сатып алуу тизмем` |
| 6.7 | Remove item | `got the bread` | `ya compré el pan` | `Brot gekauft` | `купил хлеб` | `нан сатып алдым` |
| 6.8 | Clear list | `clear shopping list` | `borrar lista de compras` | `Einkaufsliste leeren` | `очисти список покупок` | `сатып алуу тизмесин тазала` |

**Expected:** (5) Item added. (6) All items shown. (7) Item removed. (8) List emptied.

---

## 7. Life Tracking

### 7.1 Quick capture

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 7.1a | Idea | `idea: build an MVP` | `idea: construir un MVP` | `Idee: MVP bauen` | `идея: сделать MVP` | `идея: MVP жасоо` |
| 7.1b | Note | `note: call mom tomorrow` | `nota: llamar a mamá mañana` | `Notiz: morgen Mama anrufen` | `заметка: позвонить маме завтра` | `эскертүү: эртең апага чалуу` |

**Expected:** Note/idea saved to memory.

### 7.2 Track food

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 7.2a | Breakfast | `breakfast: oatmeal with berries` | `desayuno: avena con frutas` | `Frühstück: Haferflocken mit Beeren` | `завтрак: овсянка с ягодами` | `таңкы тамак: жүзүмдүү ботко` |
| 7.2b | Lunch | `lunch: soup and salad` | `almuerzo: sopa y ensalada` | `Mittagessen: Suppe und Salat` | `обед: суп и салат` | `түшкү тамак: шорпо жана салат` |
| 7.2c | Dinner | `dinner: steak and potatoes` | `cena: bistec y papas` | `Abendessen: Steak und Kartoffeln` | `ужин: стейк и картошка` | `кечки тамак: стейк жана картошка` |

**Expected:** Meal logged (no cost, just food tracking).

### 7.3 Track drink

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 7.3a | Coffee | `coffee` | `café` | `Kaffee` | `кофе` | `кофе` |
| 7.3b | Water | `water 500ml` | `agua 500ml` | `Wasser 500ml` | `вода 500мл` | `суу 500мл` |
| 7.3c | Multiple | `2 coffees` | `2 cafés` | `2 Kaffee` | `2 кофе` | `2 кофе` |

**Expected:** Beverage logged (hydration/caffeine tracking, NOT expense).

### 7.4 Mood check-in

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 7.4a | Mood | `mood 7` | `ánimo 7` | `Stimmung 7` | `настроение 7` | `маанай 7` |
| 7.4b | Energy | `energy 5` | `energía 5` | `Energie 5` | `энергия 5` | `энергия 5` |
| 7.4c | Sleep | `slept 7 hours` | `dormí 7 horas` | `7 Stunden geschlafen` | `спал 7 часов` | `7 саат уктадым` |
| 7.4d | Combined | `mood 8, energy 6, slept 7h` | `ánimo 8, energía 6, dormí 7h` | `Stimmung 8, Energie 6, 7h geschlafen` | `настроение 8, энергия 6, сон 7ч` | `маанай 8, энергия 6, уйку 7с` |

**Expected:** Check-in recorded on 1–10 scale.

### 7.5 Day plan

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 7.5 | Set priorities | `plan: ship the release, call client` | `plan: lanzar la versión, llamar al cliente` | `Plan: Release veröffentlichen, Kunden anrufen` | `план: выпустить релиз, позвонить клиенту` | `план: релизди чыгаруу, кардарга чалуу` |

**Expected:** Day priorities recorded.

### 7.6 Day reflection

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 7.6 | Reflect | `reflection: got a lot done today` | `reflexión: hice mucho hoy` | `Reflexion: heute viel geschafft` | `рефлексия: сделал много полезного` | `рефлексия: бүгүн көп жасадым` |

**Expected:** Reflection logged.

### 7.7 Life search

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 7.7a | Food search | `what did I eat yesterday?` | `¿qué comí ayer?` | `Was habe ich gestern gegessen?` | `что я ел вчера?` | `кечээ эмне жедим?` |
| 7.7b | Notes search | `my ideas from last week` | `mis ideas de la semana pasada` | `meine Ideen von letzter Woche` | `мои идеи за прошлую неделю` | `өткөн жумадагы идеяларым` |

**Expected:** Results from Mem0 memory search.

### 7.8 Communication mode

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 7.8a | Silent | `silent mode` | `modo silencioso` | `stiller Modus` | `тихий режим` | `үнсүз режим` |
| 7.8b | Receipt | `receipt mode` | `modo recibo` | `Quittungsmodus` | `режим квитанция` | `квитанция режими` |
| 7.8c | Coaching | `coaching mode` | `modo coaching` | `Coaching-Modus` | `режим коучинг` | `коучинг режими` |

**Expected:** Communication style updated.

### 7.9 Evening recap

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 7.9 | Day summary | `evening recap` | `resumen del día` | `Tagesrückblick` | `итоги дня` | `күндүн жыйынтыгы` |

**Expected:** Full day synthesis (calendar + tasks + finance + life).

### 7.10 Price alert

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 7.10 | Set price alert | `alert me when lumber drops below $5` | `avísame cuando la madera baje de $5` | `benachrichtige mich wenn Holz unter $5 fällt` | `следи за ценой lumber ниже $5` | `lumber баасы $5тен төмөн түшсө кабарла` |

**Expected:** Price monitoring activated with threshold.

### 7.11 News monitor

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 7.11 | Monitor topic | `monitor crypto news` | `monitorear noticias de cripto` | `Krypto-Nachrichten überwachen` | `следи за новостями о crypto` | `crypto жаңылыктарын көзөмөлдө` |

**Expected:** News monitoring started.

---

## 8. Research

### 8.1 Quick answer

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 8.1a | Conversion | `how many ml in a cup?` | `¿cuántos ml hay en una taza?` | `Wie viele ml hat eine Tasse?` | `сколько мл в стакане?` | `бир стаканда канча мл?` |
| 8.1b | Fact | `capital of France?` | `¿capital de Francia?` | `Hauptstadt von Frankreich?` | `столица Франции?` | `Франциянын борбору?` |

**Expected:** Direct factual answer.

### 8.2 Web search

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 8.2a | Business hours | `what time does Costco close?` | `¿a qué hora cierra Costco?` | `Wann schließt Costco?` | `во сколько закрывается Costco?` | `Costco саат канчада жабылат?` |
| 8.2b | Prices | `bathroom renovation prices in Queens` | `precios de remodelación de baño en Queens` | `Badezimmerrenovierung Preise in Queens` | `расценки на ремонт ванной в Queens` | `Queens шаарында ванна ремонтунун баасы` |

**Expected:** Current web information with sources.

### 8.3 Compare options

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 8.3 | Compare | `compare iPhone vs Samsung` | `comparar iPhone vs Samsung` | `iPhone vs Samsung vergleichen` | `сравни iPhone и Samsung` | `iPhone менен Samsung салыштыр` |

**Expected:** Pros/cons comparison table.

### 8.4 Maps search

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 8.4a | Nearby places | `coffee shop nearby` | `cafetería cerca` | `Café in der Nähe` | `кафе рядом` | `жакын жерде кафе` |
| 8.4b | Directions | `closest gas station` | `gasolinera más cercana` | `nächste Tankstelle` | `ближайшая заправка` | `эң жакын бензин куюучу жай` |

**Expected:** Places with addresses and distances.

### 8.5 YouTube search

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 8.5 | Find video | `video how to fix a leaky faucet` | `video cómo arreglar un grifo` | `Video wie man einen Wasserhahn repariert` | `видео как починить кран` | `кранды кантип оңдоо видеосу` |

**Expected:** YouTube video links with descriptions.

### 8.6 Price check

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 8.6 | Check price | `lumber price at Home Depot` | `precio de madera en Home Depot` | `Holzpreis bei Home Depot` | `цена lumber в Home Depot` | `Home Depotтогу lumber баасы` |

**Expected:** Current price from retailer.

---

## 9. Writing

### 9.1 Draft message

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 9.1 | Write message | `write a letter to the school about absence` | `escribe una carta a la escuela sobre ausencia` | `schreibe einen Brief an die Schule wegen Abwesenheit` | `напиши письмо в школу об отсутствии` | `мектепке жок болгондугу тууралуу кат жаз` |

**Expected:** Drafted message with appropriate tone.

### 9.2 Translate

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 9.2a | To English | `translate to English: Привет мир` | `traducir al inglés: Hola mundo` | `ins Englische übersetzen: Hallo Welt` | `переведи на английский: Привет мир` | `англисчеге которгулa: Салам дүйнө` |
| 9.2b | To Spanish | `translate to Spanish: Hello world` | `traducir al español: Hello world` | `ins Spanische übersetzen: Hello world` | `переведи на испанский: Hello world` | `испанчага которгулa: Hello world` |

**Expected:** Accurate translation.

### 9.3 Write post

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 9.3 | Social media post | `write an Instagram post about my flower shop` | `escribe un post de Instagram sobre mi florería` | `schreibe einen Instagram-Post über meinen Blumenladen` | `напиши пост для Instagram о моём цветочном магазине` | `менин гүл дүкөнүм тууралуу Instagram пост жаз` |

**Expected:** Platform-appropriate post with hashtags.

### 9.4 Proofread

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 9.4 | Check grammar | `proofread: I goes to the store yesterday` | `corregir: Yo fue al tienda ayer` | `korrekturlesen: Ich gehen gestern in Laden` | `проверь: Я пошёл в магазине вчера` | `текшер: Мен кечээ дүкөнгө бардым` |

**Expected:** Errors identified with corrections.

### 9.5 Generate image

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 9.5 | Create image | `draw a cat in space` | `dibuja un gato en el espacio` | `zeichne eine Katze im Weltraum` | `нарисуй кота в космосе` | `космостогу мышыкты тарт` |

**Expected:** Generated image returned.

### 9.6 Generate card/infographic

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 9.6 | Create tracker | `create a 30-day reading tracker` | `crea un rastreador de lectura de 30 días` | `erstelle einen 30-Tage-Lesetracker` | `сделай трекер чтения на 30 дней` | `30 күндүк окуу трекерин жаса` |

**Expected:** Infographic card image.

### 9.7 Generate program

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 9.7 | Write code | `write a Python web scraper` | `escribe un scraper web en Python` | `schreibe einen Python-Web-Scraper` | `напиши парсер сайта на Python` | `Python менен сайт парсерин жаз` |

**Expected:** Working code + E2B sandbox execution result.

### 9.8 Modify program

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 9.8 | Update code | `add error handling to the script` | `agrega manejo de errores al script` | `füge Fehlerbehandlung zum Skript hinzu` | `добавь обработку ошибок` | `ката иштетүүнү кош` |

**Expected:** Updated code with changes applied.

### 9.9 Convert document

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 9.9 | Convert file | Send file + `convert to PDF` | Send file + `convertir a PDF` | Send file + `in PDF konvertieren` | Файл + `конвертируй в PDF` | Файл + `PDFке айландыр` |

**Expected:** Converted document returned.

---

## 10. Email (requires Google OAuth)

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 10.1 | Check inbox | `check my email` | `revisa mi correo` | `check meine E-Mails` | `проверь почту` | `почтамды текшер` |
| 10.2 | Send email | `email John about the meeting` | `envía un correo a John sobre la reunión` | `schreibe John eine E-Mail wegen des Meetings` | `напиши письмо Джону о встрече` | `Джонго жолугушуу тууралуу email жаз` |
| 10.3 | Reply | `reply to the last email` | `responde al último correo` | `antworte auf die letzte E-Mail` | `ответь на последнее письмо` | `акыркы emailге жооп бер` |
| 10.4 | Unreplied | `any emails I haven't replied to?` | `¿hay correos sin responder?` | `gibt es unbeantwortete E-Mails?` | `на какие письма не ответил?` | `кайсы emailдерге жооп бере элекмин?` |
| 10.5 | Summarize thread | `summarize the thread with Sarah` | `resume el hilo con Sarah` | `fasse den Thread mit Sarah zusammen` | `перескажи переписку с Сарой` | `Сара менен кат алышууну кыскача айтып бер` |

**Expected:** (1) Inbox summary. (2) Draft → approval → send. (3) Reply draft. (4) Unreplied list. (5) Thread summary.

---

## 11. Calendar (requires Google OAuth)

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 11.1 | Show schedule | `what's on my calendar today?` | `¿qué tengo hoy en el calendario?` | `Was steht heute im Kalender?` | `что на сегодня?` | `бүгүн эмне бар?` |
| 11.2 | Create event | `meeting tomorrow at 3pm` | `reunión mañana a las 3pm` | `Meeting morgen um 15 Uhr` | `встреча завтра в 15:00` | `эртең саат 15:00дө жолугушуу` |
| 11.3 | Free slots | `when am I free this week?` | `¿cuándo estoy libre esta semana?` | `Wann bin ich diese Woche frei?` | `когда я свободен на этой неделе?` | `бул жумада качан бошмун?` |
| 11.4 | Reschedule | `move the dentist to Thursday` | `mueve al dentista al jueves` | `verschiebe den Zahnarzt auf Donnerstag` | `перенеси стоматолога на четверг` | `тиш доктурду бейшембиге которгулa` |
| 11.5 | Morning brief | `morning brief` | `resumen matutino` | `Morgenübersicht` | `утренняя сводка` | `таңкы кыскача маалымат` |

**Expected:** (1) Event list. (2) Confirmation → event created. (3) Available slots. (4) Event moved. (5) Full day briefing.

---

## 12. Booking & CRM

### 12.1–12.4 Appointments

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 12.1 | Create booking | `book John tomorrow 2pm` | `reservar a John mañana 2pm` | `John morgen 14 Uhr buchen` | `запиши Ивана на завтра 14:00` | `Иванды эртеңки саат 14:00гө жазып кой` |
| 12.2 | List bookings | `my bookings today` | `mis reservas de hoy` | `meine Buchungen heute` | `мои записи на сегодня` | `бүгүнкү жазуулар` |
| 12.3 | Cancel booking | `cancel John's appointment` | `cancela la cita de John` | `Johns Termin absagen` | `отмени запись Ивана` | `Ивандын жазуусун жокко чыгар` |
| 12.4 | Reschedule | `move John to Thursday` | `mueve a John al jueves` | `John auf Donnerstag verschieben` | `перенеси Ивана на четверг` | `Иванды бейшембиге которгулa` |

**Expected:** (1) Booking created. (2) Today's appointments. (3) Booking cancelled. (4) Booking rescheduled.

### 12.5–12.7 Contacts

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 12.5 | Add contact | `add client John 917-555-1234` | `agregar cliente John 917-555-1234` | `Kunde John 917-555-1234 hinzufügen` | `добавь клиента Иван +79991234567` | `Иван кардарды кош +79991234567` |
| 12.6 | List contacts | `my contacts` | `mis contactos` | `meine Kontakte` | `список клиентов` | `кардарлар тизмеси` |
| 12.7 | Find contact | `find John` | `buscar a John` | `John suchen` | `найди Ивана` | `Иванды тап` |

**Expected:** (5) Contact saved. (6) All contacts. (7) Contact card found.

### 12.8–12.9 Communication & Receptionist

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 12.8 | Message client | `text John I'm running late` | `envía a John que llego tarde` | `schreibe John dass ich mich verspäte` | `напиши Ивану что опаздываю` | `Иванга кечигип жатам деп жаз` |
| 12.9 | Receptionist | `what services do you offer?` | `¿qué servicios ofrecen?` | `Welche Dienstleistungen bieten Sie an?` | `какие у вас услуги?` | `кандай кызматтарыңыз бар?` |

**Expected:** (8) Message sent to client. (9) Services, prices, hours listed.

---

## 13. Browser Actions

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 13.1 | Browse website | `go to website and check prices` | `ve al sitio y revisa precios` | `gehe auf die Website und prüfe Preise` | `зайди на сайт и посмотри цены` | `сайтка кирип бааларды көр` |
| 13.2 | Book hotel | `book a hotel on booking.com` | `reserva un hotel en booking.com` | `buche ein Hotel auf booking.com` | `забронируй отель на booking.com` | `booking.com дон мейманкана брондо` |

**Expected:** (1) Website visited, data extracted. (2) Booking flow with confirmation.

---

## 14. General Chat

| # | Test | EN | ES | DE | RU | KY |
|---|------|----|----|----|----|-----|
| 14.1 | Greeting | `hello!` | `¡hola!` | `hallo!` | `привет!` | `салам!` |
| 14.2 | Thanks | `thank you` | `gracias` | `danke` | `спасибо` | `рахмат` |
| 14.3 | What can you do? | `what can you do?` | `¿qué puedes hacer?` | `Was kannst du?` | `что ты умеешь?` | `сен эмне кыла аласың?` |

**Expected:** Friendly conversational response with capabilities overview.

---

## Testing Order (recommended)

| Phase | Domain | Tests | Prerequisites |
|-------|--------|-------|---------------|
| 1 | Onboarding | 1.1–1.8 | Clean start, no data |
| 2 | Finance: expenses/income | 2.1–2.8 | Creates data for analytics |
| 3 | Receipt scanning | 3.1–3.2 | Photo of receipt needed |
| 4 | Life tracking | 7.1–7.8 | Builds data for summaries |
| 5 | Tasks & shopping | 6.1–6.8 | Creates tasks for briefs |
| 6 | Analytics | 4.1–4.4 | Needs transaction history |
| 7 | Finance specialist | 5.1–5.4 | Needs data from phases 2–3 |
| 8 | Research | 8.1–8.6 | Independent, no data needed |
| 9 | Writing | 9.1–9.9 | Independent |
| 10 | Email | 10.1–10.5 | Requires Google OAuth |
| 11 | Calendar | 11.1–11.5 | Requires Google OAuth |
| 12 | Booking & CRM | 12.1–12.9 | Independent |
| 13 | Browser | 13.1–13.2 | Complex, test last |
| 14 | General chat | 14.1–14.3 | Independent |

---

**Total test cases: 95** across 14 domains, each in 5 languages.

<!-- Recovered 2026-08-15 from the 37-agent translation-review workflow
     (wf_23d5e15c-ce0, run 2026-08-14). The original lived at a session
     scratchpad path (whysj69vf.output) that no longer exists — task #56
     pointed at a dead file for a day. Internal: docs/plans/ never ships. -->
# OutMass email localisation — fix list

*12 languages, 133 claimed findings, 78 survived skeptics. I re-verified every code-level and panel-label claim against the repo; where a reviewer was wrong or incomplete, I say so.*

---

## 1. Is this shippable?

**Yes, after one pass — but no language came back clean, and the two biggest problems are not in the translations at all.** The prose quality is genuinely high everywhere: register is consistent, nothing over-promises past the English, `${placeholders}`, URLs and the literal `{{firstName}}` survived intact in all twelve files. **French, Japanese and Brazilian Portuguese are close to ready** — one real bug each. **Spanish and both Chinese variants need a short pass** — three fixable items each. **European Portuguese and Turkish each carry one blocker** — an email tells the customer to click a button that does not exist under that name. **Russian, German, Hindi and Arabic need real work** — Russian breaks numeral agreement in six live strings, German has an English thousands separator that makes "10,000 e-mails" read as *ten*, Hindi has three ungrammatical sentences including a subject line, Arabic has an ungrammatical subject line for almost every recipient count. Underneath that: **one line of Python zero-pads the day in all thirteen languages including English** ("on September 05"), and **the English source itself quotes a button label that doesn't match the English panel** — which is why ten of twelve translations got it wrong too. Fix the code and the source first; a third of the translation "errors" evaporate.

---

## 2. Blockers and majors

Email strings live in `D:\dev\git\outmass\backend\emails\strings\<lang>.json`. Panel strings in `D:\dev\git\outmass\extension\_locales\<lang>\messages.json`.

### FIRST — three code fixes, no translation work, 13 languages each

**C1. Zero-padded day — `backend/utils/welcome_email.py:126`** `day=f"{d.day:02d}"` → `day=str(d.day)`.
I checked all 13 `quota_capped.reset_on_date` strings: **every one is affected.** English renders "on September 05", German "am 05. September", French "le 05 septembre", Japanese "9月05日", Spanish "el 05 de septiembre", Turkish "05 eylül". No language on earth pads the day next to a spelled month. French additionally needs `1er` when `d.day == 1` — `le 01 septembre` is wrong twice over. Reviewers flagged this in de/fr/ja/zh_TW; it is universal.

**C2. English thousands separator — `backend/utils/welcome_email.py` lines 96, 137, 157, 194** — `f"{monthly_limit_for_plan(plan):,}"` and `f"{limit:,}"`.
Renders `2,500` / `10,000` into every language. In **de, tr, es, pt_BR, pt_PT** the comma is the decimal separator, so *"bis zu 10,000 E-Mails"* and *"Ayda 10,000 e-postaya kadar"* say **ten**. **fr and ru** use a space, not a comma. That is **7 of 12 languages wrong today**, on the paid-upgrade email and the quota-cap email. Reviewers caught de and tr only. The panel already gets this right in the same product (`upgradeModalPro`: "Pro: 10.000 email/ay"). Fix: format per-locale at send time, not `:,`. Note `free_quota` is 250 today so it renders clean — it breaks the moment free goes above 999.

**C3. No plural machinery — `skipped=skipped` is passed as a raw int.**
Russian breaks for nearly every value, Arabic for everything outside 11–99, French at 1 (`1 destinataires mis de côté`), and **English at 1** — `quota_capped.subject` is hardcoded `"${skipped} recipients saved"`, so a send capped one recipient over sends *"1 recipients saved"*. Cheapest fix is the count-safe phrasing per language (below); the English source needs the same treatment.

---

### Arabic — 5 majors

**`welcome.step3`** — quotes a test-send button called **رسالة اختبار**; the panel's `btnTestSend` is **إرسال اختباري**.
```
اضغط **معاينة**، أو **إرسال اختباري** لترسل الرسالة إلى نفسك أولًا، ثم اضغط **إرسال**. يوزّع OutMass الإرسال على مهل ويتتبّع عمليات الفتح والنقر والردود.
```
**`reauth.how_to_fix`** — quotes **إعادة الربط بـ Outlook**; the banner (`reauthBannerText`) reads **أعد الاتصال بـ Outlook**. Verified.
```
**كيف تصلح ذلك:** افتح لوحة OutMass داخل Outlook على الويب، واضغط على شريط **أعد الاتصال بـ Outlook**، ثم سجّل الدخول من جديد. يستغرق ذلك نحو 10 ثوانٍ.
```
**`quota_capped.subject`** — `مستلمًا` is only grammatical for 11–99; "250 parked" renders ungrammatically.
```
تم حفظ ${skipped} من المستلمين — وسيُرسَلون تلقائيًا
```
**`quota_capped.heading`** — same error, separate key.
```
تم حفظ ${skipped} من المستلمين 📬
```
**`plan_dropped.opening_payment_failed`** — `حاول … على البطاقة` is not Arabic; حاول takes no على and no object here.
```
انتهى اشتراكك اليوم. ظلّ Stripe نحو أسبوعين يحاول الخصم من البطاقة المحفوظة، ولا بد أنك تلقّيت رسائله بهذا الشأن.
```

### German — 8 majors

**`upgrade.point_quota`, `quota_capped.saved`** — see **C1/C2**. The German strings are correct; do not edit them.

**Tarif → Plan (8 keys).** Emails say *Tarif* throughout; the panel says *Plan* everywhere the customer looks (`settingsPlan`, `btnUpgrade` "Plan upgraden", `planEndedNotice`). Worst in `plan_dropped`, where mail and in-panel notice arrive together and disagree.
- `welcome.free_plan`: `**Free-Tarif**` → `**Free-Plan**`
- `upgrade.subject`: `Ihr OutMass-${plan_label}-Plan ist aktiv — vielen Dank!`
- `upgrade.heading`: `Ihr ${plan_label}-Plan ist aktiv 🎉`
- `upgrade.intro`: `…Ihr **${plan_label}**-Plan ist ab sofort aktiv…`
- `plan_dropped.subject_payment_failed`: `Ihr OutMass-Plan wurde auf Free zurückgesetzt`
- `plan_dropped.subject_promo_ended`: `Ihr OutMass-Plan ist beendet`
- `plan_dropped.opening_promo_ended`: `Der Plan, den wir für Sie eingerichtet hatten, ist ausgelaufen, und Ihr Konto ist wieder auf Free.`
- `plan_dropped.carry_on_*`: `wählen Sie einen Tarif` → `wählen Sie einen Plan`
- (panel) `alertBackendUnreachable`: `…oder Tarif` → `…oder Plan`

**`upgrade.point_manage`** and **`inactivity_30d.stop_panel`** — quote **Abo verwalten**; the button (`btnManageSub`) is **Abonnement verwalten**. Verified. This is the cancellation path.
```
Ihren Verbrauch sehen Sie jederzeit im OutMass-Panel unter **Konto**, verwalten oder kündigen können Sie über **Abonnement verwalten**.
```
```
Öffnen Sie das OutMass-Panel → **Konto** → **Abonnement verwalten**, oder
```
**`reauth.how_to_fix`** — quotes **Mit Outlook neu verbinden**; banner reads **Outlook erneut verbinden**. Verified.
```
**So beheben Sie das:** Öffnen Sie die OutMass-Seitenleiste in Outlook im Browser, klicken Sie auf das Banner **Outlook erneut verbinden** und melden Sie sich erneut an. Dauert etwa 10 Sekunden.
```
**`inactivity_90d.noticed`** — `nichts weiter berechnen, das Sie nicht nutzen` is broken; the relative clause cannot attach to `nichts`.
```
Es ist etwa ${days} Tage her, dass Sie OutMass zuletzt genutzt haben. Wir haben Ihnen bereits zweimal geschrieben, und wir möchten Ihnen nicht weiter etwas in Rechnung stellen, das Sie gar nicht nutzen.
```
**`quota_capped.reset_on_date`** — composes into `…automatisch, am 5. September, wenn…`; comma before a bare time adverbial is wrong.
```
und zwar am ${day}. ${month}, wenn Ihr monatliches Kontingent zurückgesetzt wird
```
**`plan_dropped.opening_payment_failed`** — *"eine Karte versuchen"* is not a German collocation; *"Sie werden … erhalten haben"* is Futur II of supposition, stiff and faintly accusatory in a dunning email.
```
Ihr Abo ist heute ausgelaufen. Stripe hat es rund zwei Wochen lang mit der hinterlegten Karte versucht; die entsprechenden E-Mails von Stripe haben Sie sicher schon erhalten.
```
**`account_deleted.audit_record`** — you cannot *fulfil a prevention*.
```
Gemäß unserer Datenschutzerklärung bewahren wir 5 Jahre lang einen anonymisierten Prüfeintrag auf, um Anforderungen der Betrugsprävention und gesetzliche Pflichten zu erfüllen. Dieser Eintrag enthält nur einen Hash Ihrer E-Mail-Adresse und aggregierte Zähler — keine Inhalte.
```
**Panel file, separate from this release:** `extension/_locales/de/messages.json` ships **23 keys** with ASCII transliterations instead of umlauts/ß — `Pruefen`, `fuer`, `Empfaenger`, `Schaltflaeche`, `Grosse`, `ueber`, `koennte`, `naechsten`, `zusaetzlich`. I verified the count. The rest of the file has proper ä/ö/ü, so the panel visibly mixes both spellings. **The de email catalogue is clean — this is panel-only.**

### Spanish — 3 majors

**`reauth.how_to_fix`** — quotes **Volver a conectar con Outlook**; the banner reads **Reconecta con Outlook**. Verified.
```
**Cómo solucionarlo:** abre el panel de OutMass en Outlook en el navegador, haz clic en el aviso **Reconecta con Outlook** e inicia sesión otra vez. Tarda unos 10 segundos.
```
**`inactivity_90d.subject`** and **`inactivity_90d.heading`** — *comprobación* means a technical verification/audit of the account, not "check-in". Wrong signal on a churn email. Both keys carry the same string; fix both.
```
OutMass: un último mensaje
```
**Panel file, my finding, not a reviewer's — major.** `extension/_locales/es/messages.json` has **25 keys** with stripped diacritics, and in Spanish that is not cosmetic: **`labelCampaignName` reads "Nombre de la campana (opcional)" — *campana* is a bell.** Same in `campaignNameDuplicate` ("Ya existe una campana llamada…"), `archiveConfirm` ("¿Archivar esta campana? … desde la pestana Archivadas" — *pestana* for *pestaña*), `quotaInfoBody2` ("campanas grandes"). Plus `btnTestSend` "Envio de prueba", `alertSignInFirst` "inicia sesion … el boton", `langAuto` "Automatico". The Spanish reviewer noticed `btnTestSend` in passing and stopped there. The es email catalogue is clean.

### French — 1 major

**`quota_capped.sooner`** — quotes **Améliorer**. No such control: `btnUpgrade` is **Changer de plan**. Verified.
```
Vous voulez qu'ils partent plus tôt ? Passer à un forfait supérieur relève votre limite immédiatement et les destinataires conservés partent au prochain envoi : ouvrez le panneau OutMass et cliquez sur **Changer de plan**.
```
**Panel file:** `extension/_locales/fr/messages.json` — **23 keys** accent-stripped (`Apercu`, `Etape`, `Verifiez`, `envoye`, `probleme`, `deja`, `etre`, `etes`, `premiere`, `fenetre`, `Telecharger`). Same class as the Turkish diacritic incident. fr email catalogue is clean.

### Hindi — 6 majors

**`quota_capped.automatic`** — both `${reset_phrase}` variants are जब-clauses; embedding one mid-verb-phrase produces a broken sentence.
```
${reset_phrase}, OutMass उन्हें **अपने आप** भेज देगा।
```
**`reauth.how_to_fix`** — quotes **Outlook से फिर जुड़ें**; banner reads **Outlook से फिर से कनेक्ट करें**. Verified.
```
**इसे कैसे ठीक करें:** ब्राउज़र वाले Outlook में OutMass साइडबार खोलें, **Outlook से फिर से कनेक्ट करें** बैनर पर क्लिक करें और दोबारा साइन इन करें। लगभग 10 सेकंड लगते हैं।
```
**`inactivity_60d.subject`** and **`inactivity_60d.heading`** — `करते रह रहे हैं` stacks रहना on the progressive; no native speaker produces this. Same string in both keys.
```
OutMass इस्तेमाल नहीं कर रहे, फिर भी उसका भुगतान कर रहे हैं?
```
**`plan_dropped.opening_payment_failed`** — `फ़ाइल पर मौजूद कार्ड` is a literal calque of "card on file" and reads as a card lying on a file.
```
आपकी सदस्यता आज समाप्त हो गई। Stripe ने लगभग दो हफ़्ते तक आपके सहेजे हुए कार्ड से भुगतान की कोशिश की, और उसके ईमेल आपको मिले होंगे।
```
**`quota_capped.sooner`** — `भेजाई` is not a word for "sending run"; where it exists it means a freight charge, inside a paragraph about paying more money.
```
उन्हें जल्दी भेजना चाहते हैं? अपग्रेड करने से आपकी सीमा तुरंत बढ़ जाती है और सहेजे गए प्राप्तकर्ता अगले भेजने के चक्र में चले जाएँगे — OutMass पैनल खोलें और **अपग्रेड** पर क्लिक करें।
```

### Japanese — 1 major

**`quota_capped.saved`** — 「こちらで対応いただくことはありません」 mixes こちら (our side) with いただく (reader acts); it parses as *"we won't be doing anything about it"* — the opposite of the intended reassurance, in the one sentence that matters.
```
キャンペーンが月間上限の **${limit} 通**に達しました。残りの **${skipped} 件の宛先は安全に保存されています**。失われたものはなく、お客様に必要な操作もありません。
```

### Brazilian Portuguese — 2 majors

**`welcome.step3`** — quotes **Pré-visualizar**; the panel button (`btnPreview`) is **Visualizar**, and the panel's own onboarding says "Clique em Visualizar ou Envio de teste". Verified.
```
Clique em **Visualizar** ou mande um **Envio de teste** para você mesmo e depois clique em **Enviar**. O OutMass distribui o envio e acompanha aberturas, cliques e respostas.
```
**`inactivity_30d.noticed`** — *"abrindo você ou não"* is not Portuguese: dangling gerund, no object. It is the one sentence in the email about the customer's money.
```
Percebemos que você não usa o OutMass há cerca de ${days} dias. Mais um aviso do que uma cutucada: sua assinatura paga continua ativa e continua sendo cobrada todo mês, quer você abra o OutMass ou não.
```

### European Portuguese — 1 blocker, 3 majors

**BLOCKER — `quota_capped.sooner`** — sends the customer to **Mudar de plano**. The button (`btnUpgrade`) is **Fazer upgrade**. Verified. This is the upgrade email.
```
Quer que saiam mais cedo? Fazer upgrade aumenta o limite de imediato e os destinatários guardados saem no envio seguinte — abra o painel do OutMass e clique em **Fazer upgrade**.
```
**`welcome.intro`** — *impressão em série* is Word's PT-PT term for mail merge and literally says "serial printing". First sentence of the first email; also off-brand versus `appDesc` ("Campanhas de e-mail em massa…").
```
Obrigado por iniciar sessão no OutMass! Já pode enviar campanhas de email em massa, com cada mensagem personalizada, a partir da sua própria conta do Outlook.
```
**`inactivity_60d.one_more`** — *diligência* is debt-collection/legal vocabulary in Portugal.
```
Se não tivermos resposta, escrevemos mais uma vez aos 90 dias antes de darmos qualquer outro passo.
```
**`account_deleted.audit_record`** — *cumprir a prevenção de fraude* is impossible; the two purposes need splitting.
```
De acordo com a nossa Política de Privacidade, mantemos um registo de auditoria anonimizado durante 5 anos, para efeitos de prevenção de fraude e para cumprir obrigações legais. Esse registo contém apenas um hash do seu endereço de email e contadores agregados — nenhum conteúdo.
```

### Russian — 10 majors

**`reauth.expired`** — **wrong feature named.** "follow-ups" became *автоответы* = auto-replies/out-of-office, which OutMass does not do. The panel calls them *повторные письма*.
```
Подключение OutMass к Microsoft Outlook истекло. Пока вы не подключите его заново, запланированные рассылки и повторные письма будут приостанавливаться вместо отправки.
```
**`quota_capped.subject`** — numeral agreement fails for most values ("2 получателей сохранены").
```
Сохранено получателей: ${skipped} — они уйдут автоматически
```
**`quota_capped.heading`**
```
Сохранено получателей: ${skipped} 📬
```
**`quota_capped.saved`** — needs nominative plus a parenthesised count to be safe at every value.
```
Ваша рассылка достигла месячного лимита в **${limit} писем**. Остальные получатели (${skipped}) **надёжно сохранены** — ничего не потеряно, и от вас ничего не требуется.
```
**`inactivity_30d.noticed`** — `${days}` is the real elapsed count (I verified: `backend/workers/inactivity_nudge.py:226` passes `days=days_inactive`, not the round threshold), so "31 дней" ships. Plus *"открываете вы её или нет"* attaches to *подписка* — you cannot open a subscription.
```
Мы заметили, что вы не пользовались OutMass примерно ${days} дн. Это скорее уведомление, чем напоминание: ваша платная подписка по-прежнему активна и списывается каждый месяц — независимо от того, пользуетесь вы OutMass или нет.
```
**`inactivity_60d.noticed`**
```
Вы не входили в OutMass около ${days} дн. Всё это время платная подписка продолжала продлеваться. Мы не хотим, чтобы вы платили за то, от чего не получаете пользы.
```
**`inactivity_90d.noticed`**
```
Прошло около ${days} дн. с тех пор, как вы в последний раз пользовались OutMass. Мы уже писали дважды и не хотим продолжать брать плату за то, чем вы не пользуетесь.
```
**`quota_capped.sooner`** — quotes **Сменить тариф**; `btnUpgrade` is **Улучшить план**. Verified.
```
Хотите быстрее? Переход на другой тариф сразу поднимает лимит, и сохранённые получатели уйдут при следующей отправке — откройте панель OutMass и нажмите **Улучшить план**.
```
**`welcome.step3`** — quotes **Тестовое письмо**; `btnTestSend` is **Тестовая отправка**. Verified.
```
Нажмите **Предпросмотр** или отправьте письмо себе через **Тестовая отправка**, а затем нажмите **Отправить**. OutMass распределяет отправку и отслеживает открытия, клики и ответы.
```
**`reauth.how_to_fix`** — quotes **Подключить Outlook заново**; banner is **Переподключите Outlook**, its button **Войти**. Verified.
```
**Как исправить:** откройте панель OutMass в Outlook в браузере, найдите баннер **Переподключите Outlook** и нажмите на нём кнопку **Войти**. Занимает около 10 секунд.
```

### Turkish — 1 blocker, 3 majors

**BLOCKER — `reauth.how_to_fix`** — quotes **Outlook'a yeniden bağlan**. The panel has no such element: `reauthBannerText` is **"Outlook bağlantını yenile — yetkilendirmen sona erdi…"** and its button is **Giriş yap**. Verified. Also *"banda tıklamak"* is not how anyone refers to a notification strip.
```
**Nasıl düzeltilir:** Outlook Web'de OutMass panelini açın, **Outlook bağlantını yenile** uyarısındaki **Giriş yap** düğmesine tıklayın ve tekrar oturum açın. Yaklaşık 10 saniye sürer.
```
**`welcome.step3`** — invents **Test Gönderimi**; the button is **Test Gönder**. And *"gönderimi dengeler"* = "balances the sending", which carries none of "paces delivery"; the panel already says `largeSendWarn`: "otomatik olarak yavaşlatır".
```
**Önizleme**'ye tıklayın ya da **Test Gönder** ile kendinize bir deneme yollayın, sonra **Gönder**'e basın. OutMass gönderimi zamana yayar; açılmaları, tıklamaları ve yanıtları takip eder.
```
**`upgrade.point_quota`** — see **C2**. The tr string is correct; **do not edit it**. The panel already does this right: `upgradeModalPro` "Pro: 10.000 email/ay".

**`account_deleted.audit_record`** — *"e-posta adresinizin bir özeti"* reads as *a summary of your address* to a non-technical reader; loses the irreversibility that "hash" carries. Also `içerir — hiçbir içerik içermez` stutters.
```
Gizlilik Politikamız gereği, dolandırıcılık önleme ve yasal yükümlülükler için 5 yıl boyunca anonimleştirilmiş bir denetim kaydı tutuyoruz. Bu kayıt yalnızca e-posta adresinizin geri döndürülemez bir özetini (hash) ve toplam sayaçları içerir — içeriğinizden hiçbir şey saklanmaz.
```

### Simplified Chinese — 3 majors

**`welcome.step3`** — bolds **测试邮件** as a button; `btnTestSend` is **测试发送**. 测试邮件 exists only as the name of the message sent (`testSendSuccess`), not as anything clickable. Verified.
```
点击**预览**，或用**测试发送**给自己发一封，然后点击**发送**。OutMass 会控制发送节奏，并跟踪打开、点击和回复。
```
**`account_deleted.audit_record`** — 「不含任何内容」 reads as *contains nothing at all*, contradicting the immediately preceding clause. In a deletion confirmation this reads as hedging.
```
根据我们的隐私政策，为满足反欺诈与法律义务，我们会保留一条匿名化的审计记录 5 年。该记录只包含你邮箱地址的哈希值和汇总计数 — 不含任何邮件内容。
```
**`quota_capped.reset_on_date`** — I confirmed the stray space at byte level: the string is `'在 ${month}${day} 日，…'`, rendering **"8月14 日"**. Combined with C1 it currently renders "8月05 日".
```
在 ${month}${day}日（你的每月配额重置日）
```

### Traditional Chinese — 3 majors

**`welcome.step3`** — two of three bolded labels don't exist: panel says **測試傳送** (not 測試信) and **傳送** (not 寄送). The panel is 傳送 throughout. Verified.
```
點**預覽**，或用**測試傳送**寄一封給自己，然後按**傳送**。OutMass 會調節寄送節奏，並追蹤開信、點擊與回覆。
```
**`welcome.subject`** + 6 more — "campaign" is **行銷活動** everywhere in the panel (`tabCampaign`, `btnDashboard` "開啟行銷活動面板", `labelCampaignName`). The emails invent **群發**, which appears nowhere in the product. Fix in `welcome.subject`, `welcome.intro`, `welcome.steps_lead`, `quota_capped.saved`, `plan_dropped.free_quota`, `reauth.expired`, `account_deleted.removed` — the last two matter most, they enumerate what the user then goes to look at.
```
歡迎使用 OutMass — 三個步驟完成你的第一個行銷活動
```
**`quota_capped.reset_on_date`** — same stray space as zh, confirmed at byte level.
```
在 ${month}${day}日，也就是你的每月額度重置時
```

---

## 3. Minors

**ar** — `quota_capped.sooner`: recipients "خرج/يخرجون" (go out) — people don't go out, messages get sent.
**de** — `quota_capped.reset_on_date`: covered by C1. · `inactivity_30d.tell_us`: "sagen Sie uns was" is clipped spoken German; same in `inactivity_90d.what_stopped` ("wissen, was." → "was es war"). · `welcome.reply`: "oder haben eine Frage?" drops the required second *Sie*. · `quota_capped.questions` and `plan_dropped.questions`: "es kommt" has no antecedent → "das kommt".
**es** — `inactivity_90d.what_stopped`: "aún así" should be "aun así"; "saber qué." needs "qué fue". · `upgrade.thanks`: "apoyar pronto" = "support soon", wrong sense of *early*. · `welcome.step3`: "reparte la entrega" doesn't say sends are spaced out; panel says "espacia". · `inactivity_30d.noticed`: "la abras o no" → the feminine attaches to *suscripción*; should be "lo abras o no".
**fr** — `plan_dropped.opening_payment_failed`: "tenter une carte" is a calque; "vous aurez reçu" is stiff. · `upgrade.thanks`: "soutenir tôt" is English adverb placement. · `inactivity_30d.tell_us`: "chacune d'elles" has no antecedent. · `quota_capped.reset_on_date`: covered by C1 — **do not edit the fr string**. · `welcome.step3`: quotes "Envoi de test"; the button is "Envoi test" (my finding, near-miss).
**hi** — `plan_dropped.questions`: "कुछ काम नहीं किया" reads as "you did no work"; needs progressive + copula. · `welcome.subject` +6: emails say कैंपेन, the panel tab says अभियान (19 of 21 campaign strings).
**ja** — `quota_capped.reset_on_date`: two comma-spliced adverbials; put the relative clause before the date → `月間クォータがリセットされる ${month}${day}日に`. · `upgrade.point_manage` + `inactivity_30d.stop_panel`: button is 「サブスクリプション管理」, no の (verified). · `upgrade.point_billing`: 「1 日」 ambiguous between ついたち and いちにち. · `plan_dropped.opening_payment_failed`: 試行 left without an object. · `account_deleted.removed`: 「Microsoft の認可」 reads as a government permit, not an OAuth grant.
**pt_BR** — `inactivity_30d.tell_us`: "cada uma" has no antecedent → "todas as respostas". · `upgrade.thanks`: "apoiar cedo um produto" copies English adverb placement. · `reauth.how_to_fix`: quotes "Reconectar ao Outlook", banner says "Reconecte ao Outlook" (my finding, near-miss).
**pt_PT** — `inactivity_30d.noticed`: "quer a abra" attaches to *subscrição*. · `inactivity_30d.tell_us`: "cada uma delas" has no plural antecedent. · `reauth.how_to_fix`: quotes "Voltar a ligar ao Outlook", banner says "Volte a ligar-se ao Outlook" (my finding, near-miss).
**ru** — `account_deleted.audit_record`: "аудиторская запись" = an auditor's record; should be "запись в журнале аудита". · `account_deleted.archive_reference`: "Ссылка" means hyperlink, but `${archive_id}` is an ID. · `common.signature_founder`: "Основатель, OutMass" — English apposition comma, appears under your name in every founder-signed email.
**tr** — `quota_capped.sooner`: "Yükseltme sınırınızı" garden-paths as "your upgrade limit"; also button is "Planı Yükselt" not "Yükselt".
**zh** — `quota_capped.automatic` / `quota_capped.sooner`: 把他们发出去 / 收件人…送出 — sending *people*. · `welcome.intro`: 发送…群发 is redundant, three nouns stacked. · `inactivity_60d.three_ways`: 走法 is a chess term. · `inactivity_60d.subject`+`heading`: drops the English "Still", which is the entire point. · `plan_dropped.questions`: 跑通 is engineer jargon.
**zh_TW** — `quota_capped.subject`+4: emails say 收件人, the panel says 收件者 without exception — including `alertQuotaCapped`, the in-panel alert for this exact event. · `welcome.step2`: 範本 means *email template* (a paid feature) in the panel; the thing described is the sample CSV (`csvTemplateDownload` 範例檔) — a Free user goes looking and hits a lock. · `plan_dropped.opening_payment_failed`: 嘗試了大約兩週 has no object; 留存的卡 is not how a card on file is described. · `quota_capped.automatic`: 把他們寄出去 — mailing the people.

---

## 4. What repeats across languages

**This is where the real work is. Five patterns account for roughly half of all 78 findings.**

**① The emails quote UI labels as prose, and nothing checks them.** I compared every UI-quoting email key against the actual panel file in all 13 languages:

- `reauth.how_to_fix` — the quoted banner **mismatches in 10 of 13 languages**. Only en, ja and zh get it right. Reviewers caught 6 (ar, de, es, hi, ru, tr); fr, pt_BR and pt_PT also drift and their reviewers missed it.
- `quota_capped.sooner` — the quoted upgrade button **mismatches in 10 of 13, including English**. The English email says click **Upgrade**; the English panel button (`btnUpgrade`) says **Upgrade Plan**. Every translator faithfully translated a label that was already wrong. Only es and pt_BR happen to match. Reviewers caught 4.
- `welcome.step3` — the test-send label mismatches in 7.

The lesson is not "translators were careless". **The source was written quoting labels loosely, and there is no test asserting that a bolded label in `backend/emails/strings/*.json` exists in `extension/_locales/*/messages.json`.** `test_email_catalog.py` checks key parity, placeholder parity and paired `**` markers — it does not check that what's between the markers is real. That test is the single highest-value thing to add, and it would have caught 21 of the 78 findings, in English first.

**② Three code defects that the strings cannot fix.** C1 (zero-padded day, 13/13 languages), C2 (`:,` separator, 7/12), C3 (no plural machinery, breaks ru/ar/fr and English at n=1). All three live in `backend/utils/welcome_email.py`, none is a translation problem, and several reviewers correctly told you *not* to edit their string. Anyone applying this fix list must respect that — pasting "10.000" into de.json would hard-code a number the code is supposed to read.

**③ Four English sentences that do not survive literal translation.** Each was independently flagged by 3–6 different native speakers, which is the signature of a source problem, not a translation problem:
- *"Stripe tried the card on file for about two weeks, and you'll have had its emails about it"* — broke in **ar, de, fr, hi, ja, zh_TW**. "Try a card" is not a collocation in any of them, and the futur-antérieur-of-supposition ("you'll have had") lands as stiff or accusatory in a dunning email. Rewrite the English: *Stripe spent about two weeks trying to charge your saved card; you'll have seen its emails.*
- *"to comply with fraud prevention and legal obligations"* — broke in **de, pt_PT, tr, ru**. You cannot comply with a prevention. Split the two purposes in the English.
- *"Thanks for backing a small product early"* — adverb placement broke in **es, fr, pt_BR**.
- *"a human reads every one"* — the dangling pronoun broke in **fr, pt_BR, pt_PT**. Name the noun: *reads every reply*.

**④ "Send them" / "they go out", where "them" is people.** `quota_capped.sooner` and `quota_capped.automatic` broke in **ar, zh, zh_TW** because the English metonymy — sending recipients rather than sending messages to recipients — is not available in those languages. Same root: `inactivity_30d.noticed`'s *"whether or not you open it"*, where the ungendered English "it" resolves to the wrong noun in **es, pt_PT, ru** (all three read as "whether you open the *subscription*").

**⑤ Panel and email vocabulary have drifted apart, per language, independently.** German (*Tarif* vs *Plan*), Hindi (*कैंपेन* vs *अभियान*), Traditional Chinese (*群發* vs *行銷活動*, *收件人* vs *收件者*), Russian (*тариф* vs *план*). Nobody chose these; the two catalogues were written at different times by different processes and no glossary bound them. A per-language glossary of ~15 product nouns, checked by a test, prevents the whole class.

**⑥ Bonus, panel-only: stripped diacritics in three Latin-script locales.** `de` 23 keys, `fr` 23 keys, `es` 25 keys — verified counts. This is the exact defect from the Turkish incident, and it is now in three more languages. Spanish is the worst because ñ→n is not cosmetic: the panel currently offers to archive *"esta campana"* — a bell. **The email catalogues are all clean; this is entirely in `extension/_locales/`.** Turkish, Portuguese, Russian, Arabic, Hindi, Japanese and Chinese panel files are clean.

---

## 5. What nobody checked, and could not have

- **The rendered email.** Reviewers read JSON strings. They did not see the output of `emails/render.py` — how `**bold**` converts, how the RTL shell wraps Arabic, how `_wrap` breaks lines in CJK (which has no spaces), or how the em-dash and 📬 render in Outlook Web, Outlook mobile and Gmail. A string can be perfect and the email still look broken.
- **Whether the corrected strings are right.** Every suggestion above is one native speaker's proposal, written under adversarial pressure but **never itself reviewed**. You are about to change ~60 strings across 12 files on the strength of a single unreviewed opinion each. That is a real risk and it is larger than the risk of shipping some of the minors.
- **The golden-copy tests will not protect you here.** `test_email_copy_golden.py` pins rendered output — every fix will fail it until the goldens are regenerated, and regeneration blesses whatever was typed, including a typo. Re-run `pytest backend/tests/test_email_catalog.py` (key parity, placeholder parity, paired `**`) *before* regenerating goldens, not after.
- **Nobody read the emails as a customer.** "Warm", "salesy", "reads like a lawyer" are one person's judgment, and two skeptics arguing about tone does not make it market research. The factual and grammatical findings are solid; the register findings are opinion.
- **Legal equivalence of the retention sentence.** `account_deleted.audit_record` makes a 5-year data-retention claim in 12 languages. Reviewers checked whether it is grammatical and whether it over-promises versus the English. Whether "anonymised audit record" is the legally correct term under, say, Brazilian LGPD or Russian 152-FZ is not a linguistic question and was not answered.
- **The numbers themselves.** Reviewers verified that `${limit}` renders; nobody verified the value is right. Those come from `monthly_limit_for_plan()` in `backend/config.py`, which is the correct single source — but note that per your own CLAUDE.md, a stale number in copy has already cost you once.
- **zh_CN.** The panel has a `zh_CN` locale; `backend/emails/strings/` has no `zh_CN.json`. Mainland users get the `zh` emails by fallback — which is correct behaviour, and `test_every_language_the_panel_speaks_has_email_copy` covers it — but no reviewer looked at that pairing, and the zh panel/zh email vocabulary drift affects those users too.
- **Nothing here was A/B'd.** Whether "un último mensaje" churns fewer customers than "una última comprobación" is unknown. Every recommendation above is a correctness or naming argument, not a performance one.